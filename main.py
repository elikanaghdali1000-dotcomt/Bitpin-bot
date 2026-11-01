# -*- coding: utf-8 -*-
import os
import time
import json
import re
import math
import uuid
import requests
import pandas as pd
import threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"  # اندپوینت رسمی بیت‌پین

BB_PERIOD = 20
BB_STD = 2.0
BOLLINGER_SQUEEZE_THRESHOLD = float(os.getenv("BOLLINGER_SQUEEZE_THRESHOLD", "2.0"))  # درصد؛ کمتر از این مقدار سیگنال مسدود می‌شود
TRACKER_FILE = os.getenv("SIGNAL_TRACKER_FILE", "signal_tracker.json")

CHECK_INTERVAL = 60   # هر ۱ دقیقه چک می‌کند
TIMEFRAME = "15"      # تایم‌فریم ۱۵ دقیقه

# فیلتر حجم استراتژی پولبک: کندل سیگنال باید حجمی >= این ضریب × vol_ma20 داشته باشد.
# استراتژی سنسی از این قانون مستثناست (منطق «خشکی حجم» آن دست‌نخورده می‌ماند).
PULLBACK_MIN_VOLUME_MULT = float(os.getenv("PULLBACK_MIN_VOLUME_MULT", "1.1"))

# وضعیت سیگنال‌ها در حافظه و فایل JSON
tracker_lock = threading.RLock()
signal_tracker = {}

# Break & Retest (SHORT only): isolated state/settings; existing strategy settings stay unchanged.
BR_MAX_RETEST_CANDLES = 8
BR_RETEST_TOLERANCE_PCT = 0.15 / 100.0
BR_BREAKOUT_VOL_MULT = 1.5
BR_MIN_BREAKOUT_BODY_RATIO = 0.55
BR_MIN_REJECTION_BODY_RATIO = 0.30
BR_PENDING_SHORT = {}
BR_LAST_PROCESSED = {}

# ----------------- ۱۱۰ نماد مارجین / فیوچرز (پایه USDT) -----------------
MARGIN_SYMBOLS = [
    'PAXG_USDT', 'SOL_USDT', 'SUI_USDT', 'GALA_USDT', 'GRAM_USDT',
    'HYPE_USDT', 'SLVON_USDT', 'ETH_USDT', 'POGE_USDT', 'ADA_USDT',
    'XLM_USDT', 'ZEC_USDT', 'UNI_USDT', 'ASTER_USDT', 'S_USDT',
    'LINK_USDT', 'FIL_USDT', 'DAT_USDT', 'WIF_USDT', 'LTC_USDT',
    'NEAR_USDT', 'ONDO_USDT', 'ENA_USDT', 'RENDER_USDT', 'TRX_USDT',
    'PENGU_USDT', 'XRP_USDT', 'CAKE_USDT', 'AVAX_USDT', 'NVDX_USDT',
    'BTC_USDT', 'ALGO_USDT', 'DASH_USDT', 'PUMP_USDT', 'LDO_USDT',
]

# ================= سرور داخلی برای زنده نگه داشتن Render =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is Running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

def self_ping():
    while True:
        try:
            time.sleep(600)
            if APP_URL:
                requests.get(APP_URL, timeout=10)
        except Exception:
            pass

# ================= ارسال پیام به تلگرام =================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN == "توکن_بات_خودت_را_اینجا_بگذار":
        print("[Telegram] Token not set!")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[Telegram Error] status: {r.status_code}, response: {r.text}")
            return False
        else:
            print("[Telegram] Message sent successfully.")
            return True
    except Exception as e:
        print(f"[Telegram Exception] {e}")
        return False

# ================= دریافت کندل‌ها از بیت‌پین =================
def fetch_bitpin_candles(market_code, resolution=TIMEFRAME, count=100):
    try:
        now_ts = int(time.time())
        res_minutes = int(resolution) if resolution.isdigit() else 15
        from_ts = now_ts - (count * res_minutes * 60 * 2)

        params = {
            "symbol": market_code,
            "res": resolution,
            "from": from_ts,
            "to": now_ts
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(OHLC_URL, params=params, headers=headers, timeout=15)

        if r.status_code != 200:
            return None

        data = r.json()

        if not data or not isinstance(data, list):
            if isinstance(data, dict) and "output" in data:
                data = data["output"]
            else:
                return None

        timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []

        for c in data:
            timestamps.append(int(c.get("time", c.get("t", 0))))
            opens.append(float(c.get("open", c.get("o", 0))))
            highs.append(float(c.get("high", c.get("h", 0))))
            lows.append(float(c.get("low", c.get("l", 0))))
            closes.append(float(c.get("close", c.get("c", 0))))
            volumes.append(float(c.get("volume", c.get("v", 0))))

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })
        return df
    except Exception as e:
        return None

# ================= محاسبه اندیکاتورها =================
def calculate_indicators(df):
    if df is None or len(df) < 55:
        return None

    df["bb_middle"] = df["close"].rolling(window=BB_PERIOD).mean()
    df["bb_std"] = df["close"].rolling(window=BB_PERIOD).std()
    df["bb_upper"] = df["bb_middle"] + (BB_STD * df["bb_std"])
    df["bb_lower"] = df["bb_middle"] - (BB_STD * df["bb_std"])
    df["bandwidth"] = ((df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]) * 100

    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["vol_ma20"] = df["volume"].rolling(window=20).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=14).mean()

    return df

# تایید فشار فروش: کندل قرمز قوی، بسته‌شدن در بخش پایینی دامنه و حجم بالاتر از میانگین
def _has_confirmed_selling_pressure(candle, previous_candle):
    candle_range = candle["high"] - candle["low"]
    vol_ma20 = candle.get("vol_ma20", float("nan"))
    volume = candle["volume"]
    previous_volume = previous_candle["volume"]
    if pd.isna(vol_ma20) or vol_ma20 <= 0 or candle_range <= 0:
        return False
    return (
        candle["close"] < candle["open"]
        and (candle["open"] - candle["close"]) >= 0.4 * candle_range
        and candle["close"] <= candle["low"] + 0.4 * candle_range
        and volume >= 1.2 * vol_ma20
        and volume > previous_volume
    )

def format_price(value):
    """Render a plain, copyable price with exactly six decimal places."""
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Signal price must be finite")
    return f"{value:.6f}"

def bollinger_stop(candle, direction):
    """Place stop just beyond the nearest directional Bollinger band."""
    atr = candle.get("atr", float("nan"))
    if pd.isna(atr) or float(atr) <= 0:
        atr = float(candle["close"]) * 0.005
    band_key = "bb_lower" if direction == "LONG" else "bb_upper"
    band = candle.get(band_key, float("nan"))
    if pd.isna(band) or float(band) <= 0:
        return None
    buffer = 0.10 * float(atr)
    return float(band) - buffer if direction == "LONG" else float(band) + buffer

def risk_target(entry, direction, risk, multiple=1.5):
    """Calculate a TP in the profitable direction from entry, never toward the stop."""
    entry, risk, multiple = float(entry), float(risk), float(multiple)
    if direction not in ("LONG", "SHORT") or not math.isfinite(entry + risk + multiple):
        raise ValueError("Invalid direction or non-finite risk/entry/target multiple")
    if entry <= 0 or risk <= 0 or multiple <= 0:
        raise ValueError("Entry, risk, and target multiple must be positive")
    target = entry + risk * multiple if direction == "LONG" else entry - risk * multiple
    if (direction == "LONG" and target <= entry) or (direction == "SHORT" and target >= entry):
        raise ValueError("Take-profit must lie beyond entry in the profitable direction")
    return target

def build_signal(strategy, market_code, direction, entry, order_type, stop, tp1, tp2=None, extra=None):
    entry, stop, tp1 = float(entry), float(stop), float(tp1)
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"Unsupported signal direction: {direction}")
    valid = (stop < entry and tp1 > entry) if direction == "LONG" else (stop > entry and tp1 < entry)
    if not valid:
        raise ValueError(f"Invalid {direction} signal levels: require SL/TP on opposite sides of entry")
    if tp2 is not None:
        tp2 = float(tp2)
        if (direction == "LONG" and tp2 <= entry) or (direction == "SHORT" and tp2 >= entry):
            raise ValueError(f"Invalid {direction} TP2: must lie in the profitable direction")
    side_emoji = "🟢" if direction == "LONG" else "🔴"
    lines = [f"{side_emoji} <b>{direction} SIGNAL</b>",
             f"Symbol: <code>{market_code}</code>", f"Strategy: {strategy}",
             f"Side: {direction}", f"Entry Type: {order_type}",
             f"💰 Entry Price: <code>{format_price(entry)}</code>",
             f"🎯 TP1: <code>{format_price(tp1)}</code>"]
    if tp2 is not None:
        lines.append(f"✅ TP2: <code>{format_price(tp2)}</code>")
    lines.append(f"🔴 Stop Loss: <code>{format_price(stop)}</code>")
    if extra:
        lines.append(extra)
    return "\n".join(lines)

# ================= استراتژی‌ها (سنسی، روند، پولبک) =================
def check_sensi_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None
    # At the close-phase scan (150 seconds before close), evaluate the live
    # forming candle itself and compare it with the 15 candles immediately before it.
    candle = df.iloc[-1]
    window = df.iloc[-26:-1]
    support, resistance = window["low"].min(), window["high"].max()
    min_vol_15 = df.iloc[-16:-1]["volume"].min()
    if pd.isna(min_vol_15):
        return None
    dried = candle["volume"] <= min_vol_15
    near_support = support * 0.992 <= candle["low"] <= support * 1.003
    bullish = (candle["close"] > candle["open"] or
               candle["close"] > candle["low"] + 0.6 * (candle["high"] - candle["low"]))
    if near_support and dried and bullish:
        entry = float(candle["close"])
        stop = bollinger_stop(candle, "LONG")
        if stop is not None and stop < entry:
            risk = entry - stop
            return build_signal("بازگشت سنسی با کاهش حجم", market_code, "LONG", entry,
                                "MARKET", stop, risk_target(entry, "LONG", risk, 1.5),
                                risk_target(entry, "LONG", risk, 2.5))

    near_resistance = resistance * 0.992 <= candle["high"] <= resistance * 1.003
    previous = df.iloc[-2]
    confirmed = _has_confirmed_selling_pressure(candle, previous)
    live_bearish = candle["close"] < candle["open"]
    if near_resistance and dried and confirmed and candle["close"] < candle["open"] and live_bearish:
        entry = float(candle["close"])
        stop = bollinger_stop(candle, "SHORT")
        if stop is not None and stop > entry:
            risk = stop - entry
            return build_signal("بازگشت سنسی با کاهش حجم", market_code, "SHORT", entry,
                                "MARKET", stop, risk_target(entry, "SHORT", risk, 1.5))
    return None

def check_trend_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None
    candle = df.iloc[-2]
    close, lower, upper = candle["close"], candle["bb_lower"], candle["bb_upper"]
    ema, rsi = candle["ema200"], candle["rsi"]
    if any(pd.isna(v) for v in (close, lower, upper, ema, rsi)):
        return None
    if close <= lower and close > ema and rsi < 35:
        entry = float(close)
        stop = bollinger_stop(candle, "LONG")
        if stop is not None and stop < entry:
            risk = entry - stop
            return build_signal("بازگشت روند بولینگر", market_code, "LONG", entry,
                                "MARKET", stop, risk_target(entry, "LONG", risk, 1.5),
                                risk_target(entry, "LONG", risk, 2.5),
                                f"RSI: {float(rsi):.1f}")
    previous = df.iloc[-3]
    if (close >= upper and close < ema and rsi > 65
            and _has_confirmed_selling_pressure(candle, previous)):
        entry = float(close)
        stop = bollinger_stop(candle, "SHORT")
        if stop is not None and stop > entry:
            risk = stop - entry
            return build_signal("بازگشت روند بولینگر", market_code, "SHORT", entry,
                                "MARKET", stop, risk_target(entry, "SHORT", risk, 1.5),
                                extra=f"RSI: {float(rsi):.1f}")
    return None

def check_pullback_strategy(df, market_code, is_margin=True):
    if df is None or len(df) < 55:
        return None
    candle, previous = df.iloc[-2], df.iloc[-3]
    close, op, high, low = (float(candle[k]) for k in ("close", "open", "high", "low"))
    ema, middle, rsi, atr = candle["ema200"], candle["bb_middle"], candle["rsi"], candle["atr"]
    vol_ma20 = candle["vol_ma20"]
    if any(pd.isna(v) for v in (ema, middle, rsi)) or close <= 0 or ema <= 0:
        return None
    ema_5_ago = df.iloc[-7]["ema200"]
    if pd.isna(ema_5_ago) or close <= ema or ema <= ema_5_ago:
        return None
    touch_zone = low <= middle * 1.01 and low >= middle * 0.97
    reclaim = close > op and close > middle and previous["close"] <= previous["bb_middle"] * 1.01
    if not (touch_zone and reclaim and 35 <= rsi <= 60):
        return None
    if pd.isna(vol_ma20) or vol_ma20 <= 0 or candle["volume"] < PULLBACK_MIN_VOLUME_MULT * vol_ma20:
        return None
    if pd.isna(atr) or atr <= 0:
        atr = close * 0.01
    # Prefer a resting bid at the BB middle; never suggest a buy above the signal close.
    entry = min(close, float(middle))
    stop = bollinger_stop(candle, "LONG")
    if stop is None or stop >= entry:
        return None
    risk = entry - stop
    ratio = float(candle["volume"] / vol_ma20)
    return build_signal("پولبک روند صعودی", market_code, "LONG", entry, "LIMIT",
                        stop, entry + 1.5*risk, entry + 2.5*risk,
                        f"RSI: {float(rsi):.1f} | Volume: {ratio:.2f}x 20-candle average")

def check_short_break_retest(df, market_code):
    """Track a strong lower-Bollinger breakout, then alert on bearish retest rejection."""
    if df is None or len(df) < 55:
        return None

    candle = df.iloc[-2]
    previous = df.iloc[-3]
    timestamp = candle.get("timestamp", None)
    if timestamp is None:
        timestamp = df.index[-2]
    if BR_LAST_PROCESSED.get(market_code) == timestamp:
        return None
    BR_LAST_PROCESSED[market_code] = timestamp

    prior_volumes = df.iloc[-22:-2]["volume"]
    if len(prior_volumes) < 20:
        return None
    vol_avg = float(prior_volumes.mean())
    if pd.isna(vol_avg) or vol_avg <= 0:
        return None

    pending = BR_PENDING_SHORT.get(market_code)
    if pending:
        pending["candles_waited"] += 1
        pending["swing_high"] = max(pending["swing_high"], float(candle["high"]))
        level = pending["level"]
        tol = level * BR_RETEST_TOLERANCE_PCT
        failed = candle["close"] > level * (1 + BR_RETEST_TOLERANCE_PCT)
        if failed or pending["candles_waited"] > BR_MAX_RETEST_CANDLES:
            BR_PENDING_SHORT.pop(market_code, None)
            pending = None
        else:
            span = float(candle["high"] - candle["low"])
            body_ratio = abs(float(candle["close"] - candle["open"])) / span if span > 0 else 0.0
            retest_touch = candle["high"] >= level - tol and candle["low"] <= level + tol
            selling_confirmation = candle["volume"] > vol_avg and candle["volume"] > previous["volume"]
            rejection = (
                retest_touch and span > 0 and selling_confirmation
                and candle["close"] < level and candle["close"] < candle["open"]
                and (candle["close"] - candle["low"]) / span <= 0.45
                and body_ratio >= BR_MIN_REJECTION_BODY_RATIO
            )
            if rejection:
                entry = float(candle["close"])
                atr = candle.get("atr", float("nan"))
                if pd.isna(atr) or atr <= 0:
                    atr = entry * 0.01
                stop = bollinger_stop(candle, "SHORT")
                risk = stop - entry if stop is not None else -1
                BR_PENDING_SHORT.pop(market_code, None)
                if risk <= 0:
                    return None
                return build_signal("شکست و بازآزمایی باند پایینی بولینگر", market_code, "SHORT", entry,
                                    "LIMIT", stop, risk_target(entry, "SHORT", risk, 1.0),
                                    risk_target(entry, "SHORT", risk, 2.0),
                                    f"Breakout Level: {format_price(level)}")

    if pending is None:
        lower = candle.get("bb_lower", float("nan"))
        span = float(candle["high"] - candle["low"])
        body_ratio = abs(float(candle["close"] - candle["open"])) / span if span > 0 else 0.0
        if (not pd.isna(lower) and span > 0
                and candle["volume"] > BR_BREAKOUT_VOL_MULT * vol_avg
                and body_ratio >= BR_MIN_BREAKOUT_BODY_RATIO
                and candle["close"] < lower and candle["close"] < candle["open"]
                and (candle["close"] - candle["low"]) / span <= 0.35):
            BR_PENDING_SHORT[market_code] = {
                "level": float(lower), "candles_waited": 0,
                "swing_high": float("-inf"),
            }
    return None

# ================= Signal Tracker (ذخیره و پیگیری سیگنال‌ها) =================
def load_tracker():
    global signal_tracker
    try:
        with tracker_lock:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                signal_tracker = data
    except Exception:
        pass

def save_tracker():
    with tracker_lock:
        try:
            with open(TRACKER_FILE, "w", encoding="utf-8") as f:
                json.dump(signal_tracker, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Tracker] Save error: {e}")

def add_signal(symbol, direction, entry, sl, tp1, strategy, is_margin=True):
    sid = f"{symbol}_{strategy}_{uuid.uuid4().hex[:8]}"
    rec = {
        "id": sid,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "strategy": strategy,
        "is_margin": is_margin,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
        "hit_time": None,
    }
    with tracker_lock:
        signal_tracker[sid] = rec
    save_tracker()
    return rec

def tracker_stats():
    with tracker_lock:
        signals = list(signal_tracker.values())
    total = len(signals)
    wins = sum(1 for item in signals if item.get("status") == "HIT_TP1")
    losses = sum(1 for item in signals if item.get("status") == "HIT_SL")
    open_signals = sum(1 for item in signals if item.get("status") == "OPEN")
    ambiguous = sum(1 for item in signals if item.get("status") == "AMBIGUOUS")
    return total, wins, losses, open_signals, ambiguous

def is_squeeze(df):
    try:
        bw = df.iloc[-2]["bandwidth"]
        if pd.isna(bw):
            return False
        return bw < BOLLINGER_SQUEEZE_THRESHOLD
    except Exception:
        return False

# ================= حلقه پس‌زمینه رهگیری سیگنال‌ها =================
def check_hit(symbol, direction, tp1, sl, candle_high, candle_low):
    if direction == "LONG":
        hit_tp = candle_high >= tp1
        hit_sl = candle_low <= sl
    else:  # SHORT
        hit_tp = candle_low <= tp1
        hit_sl = candle_high >= sl
    return hit_tp, hit_sl

def run_signal_tracker():
    print("Signal tracker loop started.")
    while True:
        try:
            time.sleep(60)
            with tracker_lock:
                open_signals = {k: v for k, v in signal_tracker.items() if v.get("status") == "OPEN"}
            for sid, sig in open_signals.items():
                df = fetch_bitpin_candles(sig["symbol"], resolution=TIMEFRAME, count=2)
                if df is None or df.empty:
                    continue
                last_candle = df.iloc[-1]
                current_price = float(last_candle["close"])
                candle_high = float(last_candle["high"])
                candle_low = float(last_candle["low"])
                if current_price <= 0:
                    continue
                hit_tp, hit_sl = check_hit(sig["symbol"], sig["direction"], sig["tp1"], sig["sl"], candle_high, candle_low)
                if hit_tp and hit_sl:
                    status = "AMBIGUOUS"
                elif hit_tp:
                    status = "HIT_TP1"
                elif hit_sl:
                    status = "HIT_SL"
                else:
                    continue
                with tracker_lock:
                    signal_tracker[sid]["status"] = status
                    signal_tracker[sid]["hit_time"] = datetime.now(timezone.utc).isoformat()
                save_tracker()
                emoji = "✅" if status == "HIT_TP1" else ("❌" if status == "HIT_SL" else "⚠️")
                pos = "LONG" if sig["direction"] == "LONG" else "SHORT"
                status_text = status.replace("HIT_TP1", "HIT TP1").replace("HIT_SL", "HIT SL")
                send_telegram(f"{emoji} <b>{status_text}</b>\nSymbol: <code>{sig['symbol']}</code>\n"
                              f"Strategy: {sig['strategy']}\nSide: {pos}\nCurrent Price:\n"
                              f"<code>{format_price(current_price)}</code>\nTake Profit 1:\n"
                              f"<code>{format_price(sig['tp1'])}</code>\nStop Loss:\n"
                              f"<code>{format_price(sig['sl'])}</code>")
        except Exception as e:
            print(f"[Tracker Loop Error] {e}")

# ================= Telegram /stats =================
def telegram_stats_command_handler():
    print("Telegram /stats polling loop started.")
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": offset, "timeout": 25}, timeout=35)
            data = r.json() if r.status_code == 200 else {}
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")
                if text.startswith("/stats") and chat_id is not None:
                    total, wins, losses, open_signals, ambiguous = tracker_stats()
                    report = (
                        "📊 <b>گزارش سیگنال‌ها (/stats)</b>\n\n"
                        f"▫️ کل سیگنال‌ها: {total}\n"
                        f"✅ بردها (TP1): {wins}\n"
                        f"❌ باخت‌ها (SL): {losses}\n"
                        f"⏳ باز: {open_signals}\n"
                        f"⚠️ Ambiguous: {ambiguous}\n\n"
                        "<i>Wins = TP1 before SL; losses = SL before TP1.</i>"
                    )
                    try:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                      json={"chat_id": chat_id, "text": report, "parse_mode": "HTML"}, timeout=10)
                    except Exception as e:
                        print(f"[Stats] Send error: {e}")
        except Exception as e:
            print(f"[Stats Polling Error] {e}")
            time.sleep(3)

# ================= تأیید میانی بولینگر BTC برای LONG =================
def btc_long_middle_band_confirmed():
    """Require the last closed BTC candle above its BB middle on both 15m and 1h."""
    for resolution in ("15", "60"):
        btc_df = fetch_bitpin_candles("BTC_USDT", resolution=resolution, count=100)
        btc_df = calculate_indicators(btc_df)
        if btc_df is None or len(btc_df) < 2:
            return False
        closed = btc_df.iloc[-2]
        close = closed.get("close")
        middle = closed.get("bb_middle")
        if pd.isna(close) or pd.isna(middle) or not (float(close) > float(middle)):
            return False
    return True

# ================= ثبت و ارسال سیگنال =================
def extract_signal_details(msg):
    def num(label):
        pattern = rf"{label}:\s*<code>([0-9]+(?:\.[0-9]+)?)</code>"
        match = re.search(pattern, msg)
        return float(match.group(1)) if match else None
    entry = num("Entry Price")
    sl = num("Stop Loss")
    tp1 = num("TP1") or num("Take Profit 1")
    direction = "SHORT" if re.search(r"Side:\s*SHORT", msg) else "LONG"
    return direction, entry, sl, tp1

def register_and_send(strategy_name, msg, symbol, is_margin=True, long_confirmed=False):
    direction, entry, sl, tp1 = extract_signal_details(msg)
    if entry is None or sl is None or tp1 is None:
        print(f"[Signal] Rejected malformed signal for {symbol} ({strategy_name}).")
        return False
    geometry_ok = (sl < entry < tp1) if direction == "LONG" else (tp1 < entry < sl)
    if not geometry_ok:
        print(f"[Signal] Rejected invalid {direction} SL/entry/TP ordering for {symbol} ({strategy_name}).")
        return False
    if direction == "LONG" and not long_confirmed and strategy_name.lower() != "sensi":
        print(f"[BTC filter] Blocked LONG signal for {symbol}: BTC 15m/1h middle-band confirmation failed.")
        return False
    now = datetime.now(timezone.utc)
    with tracker_lock:
        for record in signal_tracker.values():
            if (record.get("symbol") == symbol and record.get("strategy") == strategy_name
                    and record.get("direction") == direction):
                if record.get("status") == "OPEN":
                    print(f"[Duplicate] Active {strategy_name} {direction} already tracked for {symbol}.")
                    return False
                try:
                    created = datetime.fromisoformat(record.get("timestamp", ""))
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if now - created < timedelta(minutes=15):
                        print(f"[Duplicate] {strategy_name} {direction} already issued for {symbol} in this candle.")
                        return False
                except (TypeError, ValueError):
                    pass
    if not send_telegram(msg):
        return False
    add_signal(symbol, direction, entry, sl, tp1, strategy_name, is_margin)
    return True

def run_scanner():
    print("Market scanner started successfully.")

    test_msg = (
        "🚀 <b>ربات اسکنر بیت‌پین (حالت دیباگ) روشن شد!</b>\n\n"
        "✅ اتصال به تلگرام برقرار است.\n"
        " USDT 🔗 ارزهای پایه: \n"
        "⏱ به محض رسیدن دقیقه ۰۱، اولین تست دریافت کندل انجام خواهد شد."
    )
    send_telegram(test_msg)

    last_scanned_candle_time = {"open": None, "close": None}

    while True:
        try:
            now = datetime.now(timezone.utc)
            quarter_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
            candle_close = quarter_start + timedelta(minutes=15)
            scan_time = candle_close - timedelta(seconds=150)
            current_candle_id = candle_close.strftime('%Y-%m-%dT%H:%M:%SZ')

            if abs((now - quarter_start).total_seconds()) <= 1.0:
                scan_phase = "open"
            elif abs((now - scan_time).total_seconds()) <= 1.0:
                scan_phase = "close"
            else:
                scan_phase = None

            if scan_phase and last_scanned_candle_time[scan_phase] != current_candle_id:
                print(f"[{now.strftime('%H:%M:%S')}] Starting {scan_phase} market scan...")

                btc_long_confirmed = btc_long_middle_band_confirmed()
                for symbol in MARGIN_SYMBOLS:
                    df = fetch_bitpin_candles(symbol, resolution=TIMEFRAME, count=300)
                    if df is not None and not df.empty:
                        df_ind = calculate_indicators(df)
                        if df_ind is not None:
                            if len(df_ind) >= 2 and pd.notna(df_ind.iloc[-2]["bandwidth"]) and df_ind.iloc[-2]["bandwidth"] < BOLLINGER_SQUEEZE_THRESHOLD:
                                time.sleep(0.3)
                                continue

                            if scan_phase == "close":
                                break_retest_res = check_short_break_retest(df_ind, symbol)
                                if break_retest_res:
                                    register_and_send("break_retest_short", break_retest_res, symbol, is_margin=True, long_confirmed=btc_long_confirmed)

                            if scan_phase == "close":
                                sensi_res = check_sensi_strategy(df_ind, symbol, is_margin=True)
                                if sensi_res:
                                    register_and_send("sensi", sensi_res, symbol, is_margin=True, long_confirmed=btc_long_confirmed)
                            else:
                                trend_res = check_trend_strategy(df_ind, symbol, is_margin=True)
                                if trend_res:
                                    register_and_send("trend", trend_res, symbol, is_margin=True, long_confirmed=btc_long_confirmed)

                                pullback_res = check_pullback_strategy(df_ind, symbol, is_margin=True)
                                if pullback_res:
                                    register_and_send("pullback", pullback_res, symbol, is_margin=True, long_confirmed=btc_long_confirmed)

                    time.sleep(0.3)

                last_scanned_candle_time[scan_phase] = current_candle_id
                print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {scan_phase.capitalize()} scan finished.")

            time.sleep(0.25)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

# ================= نقطه اجرای برنامه =================
if __name__ == "__main__":
    load_tracker()

    server_thread = threading.Thread(target=run_http_server, daemon=True)
    server_thread.start()

    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()

    tracker_thread = threading.Thread(target=run_signal_tracker, daemon=True)
    tracker_thread.start()

    stats_thread = threading.Thread(target=telegram_stats_command_handler, daemon=True)
    stats_thread.start()

    run_scanner()
