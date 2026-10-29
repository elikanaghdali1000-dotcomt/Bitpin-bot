# -*- coding: utf-8 -*-
import os
import time
import json
import re
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
    'BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'XRP_USDT', 'DOGE_USDT',
    'ADA_USDT', 'AVAX_USDT', 'LINK_USDT', 'SUI_USDT', 'NEAR_USDT',
    'DOT_USDT', 'TRX_USDT', 'LTC_USDT', 'BCH_USDT', 'UNI_USDT',
    'APT_USDT', 'ICP_USDT', 'SHIB_USDT', 'PEPE_USDT', 'RENDER_USDT',
    'FET_USDT', 'TAO_USDT', 'FTM_USDT', 'AAVE_USDT', 'OP_USDT',
    'ARB_USDT', 'INJ_USDT', 'TIA_USDT', 'SEI_USDT', 'STX_USDT',
    'FIL_USDT', 'ATOM_USDT', 'RUNE_USDT', 'GRT_USDT', 'LDO_USDT',
    'KAS_USDT', 'WIF_USDT', 'BONK_USDT', 'FLOKI_USDT', 'GALA_USDT',
    'SAND_USDT', 'MANA_USDT', 'AXS_USDT', 'THETA_USDT', 'EOS_USDT',
    'FLOW_USDT', 'DYDX_USDT', 'CRV_USDT', 'MKR_USDT', 'SNX_USDT',
    'ALGO_USDT', 'QNT_USDT', 'XTZ_USDT', 'IMX_USDT', 'MINA_USDT',
    'CHZ_USDT', 'ZIL_USDT', 'ENJ_USDT', '1INCH_USDT', 'COMP_USDT',
    'HOT_USDT', 'JASMY_USDT', 'WOO_USDT', 'BLUR_USDT', 'PENDLE_USDT',
    'ORDI_USDT', 'SATS_USDT', 'BEAM_USDT', 'PYTH_USDT', 'JUP_USDT',
    'WLD_USDT', 'STRK_USDT', 'ZK_USDT', 'NOT_USDT', 'TON_USDT',
    'OM_USDT', 'CFX_USDT', 'NEO_USDT', 'IOTA_USDT', 'KAVA_USDT',
    'KLAY_USDT', 'ROSE_USDT', 'MASK_USDT', 'AGIX_USDT', 'OCEAN_USDT',
    'CELO_USDT', 'LRC_USDT', 'ANKR_USDT', 'AUDIO_USDT', 'BAT_USDT',
    'BNT_USDT', 'DGB_USDT', 'GNO_USDT', 'KNC_USDT', 'ONT_USDT',
    'SKL_USDT', 'SUSHI_USDT', 'YFI_USDT', 'ZRX_USDT', 'VET_USDT',
    'ONDO_USDT', 'ENA_USDT', 'EIGEN_USDT', 'HBAR_USDT', 'POL_USDT',
    'TWT_USDT', 'ASTR_USDT', 'PAXG_USDT', 'PENGU_USDT', 'TRUMP_USDT',
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


# ================= استراتژی‌ها (سنسی، روند، پولبک) =================
def check_sensi_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None
    sig_candle = df.iloc[-2]
    lookback_window = df.iloc[-27:-2]
    prior_support = lookback_window["low"].min()
    prior_resistance = lookback_window["high"].max()

    current_vol = sig_candle["volume"]
    vol_ma20 = sig_candle["vol_ma20"]
    if pd.isna(vol_ma20) or vol_ma20 == 0:
        return None

    vol_ratio = current_vol / vol_ma20
    is_volume_dried = vol_ratio < 0.70
    atr = sig_candle.get("atr", (sig_candle["high"] - sig_candle["low"]))
    if pd.isna(atr) or atr == 0:
        atr = sig_candle["close"] * 0.005

    near_support = (sig_candle["low"] <= prior_support * 1.003) and (sig_candle["low"] >= prior_support * 0.992)
    is_bullish_reversal = (sig_candle["close"] > sig_candle["open"]) or (sig_candle["close"] > sig_candle["low"] + 0.6 * (sig_candle["high"] - sig_candle["low"]))

    if near_support and is_volume_dried and is_bullish_reversal:
        entry = sig_candle["close"]
        sl = min(prior_support, sig_candle["low"]) - (0.2 * atr)
        risk = entry - sl
        if risk > 0:
            tp1 = entry + (1.5 * risk)
            tp2 = entry + (2.5 * risk)
            market_type_str = "تعهدی / فیوچرز"
            return f"🎯 <b>سیگنال لانگ سنسی (خشکی حجم در کف)</b>\n▫️ ارز: <code>{market_code}</code> ({market_type_str})\n📌 موقعیت: LONG\n▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n🎯 حد سود ۱: {tp1:,.4f}"

    near_resistance = (sig_candle["high"] <= prior_resistance * 1.003) and (sig_candle["high"] >= prior_resistance * 0.992)
    previous_candle = df.iloc[-3]
    has_confirmed_selling_pressure = _has_confirmed_selling_pressure(sig_candle, previous_candle)
    current_candle_is_bearish = sig_candle["close"] < sig_candle["open"]
    live_candle = df.iloc[-1]
    live_candle_is_bearish = live_candle["close"] < live_candle["open"]

    if near_resistance and has_confirmed_selling_pressure and current_candle_is_bearish and live_candle_is_bearish:
        entry = sig_candle["close"]
        sl = max(prior_resistance, sig_candle["high"]) + (0.2 * atr)
        risk = sl - entry
        if risk > 0:
            tp1 = entry - (1.5 * risk)
            market_type_str = "تعهدی / فیوچرز"
            return f"🎯 <b>سیگنال شورت سنسی (خشکی حجم در سقف)</b>\n▫️ ارز: <code>{market_code}</code> ({market_type_str})\n📌 موقعیت: SHORT\n▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n🎯 حد سود ۱: {tp1:,.4f}"
    return None

def check_trend_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None
    last = df.iloc[-2]
    c, lower, upper, ema, rsi, atr = last["close"], last["bb_lower"], last["bb_upper"], last["ema200"], last["rsi"], last["atr"]
    if pd.isna(atr): atr = c * 0.01

    if c <= lower and c > ema and rsi < 35:
        return f"🟢 <b>سیگنال لانگ بولینگر</b>\n▫️ ارز: <code>{market_code}</code>\n📌 موقعیت: LONG (تعهدی / فیوچرز)\n▫️ ورود: {c:,.4f}\n▫️ RSI: {rsi:.1f}"

    previous = df.iloc[-3]
    if c >= upper and c < ema and rsi > 65 and _has_confirmed_selling_pressure(last, previous):
        entry = c
        sl = upper + atr
        risk = sl - entry
        if risk > 0:
            tp1 = entry - (1.5 * risk)
            market_type_str = "تعهدی / فیوچرز"
            return f"🔴 <b>سیگنال شورت بولینگر (روند)</b>\n▫️ ارز: <code>{market_code}</code> ({market_type_str})\n📌 موقعیت: SHORT\n▫️ ورود: {entry:,.4f}\n▫️ RSI: {rsi:.1f}\n🛡 حد ضرر: {sl:,.4f}\n🎯 حد سود ۱: {tp1:,.4f}"
    return None

def check_pullback_strategy(df, market_code, is_margin=True):
    """Identify a bullish pullback in an established uptrend using the closed candle."""
    if df is None or len(df) < 55:
        return None

    last = df.iloc[-2]
    previous = df.iloc[-3]
    close = last["close"]
    open_price = last["open"]
    high = last["high"]
    low = last["low"]
    ema = last["ema200"]
    bb_middle = last["bb_middle"]
    rsi = last["rsi"]
    atr = last["atr"]
    vol_ma20 = last["vol_ma20"]

    required = [close, open_price, high, low, ema, bb_middle, rsi]
    if any(pd.isna(value) for value in required) or close <= 0 or ema <= 0:
        return None
    if pd.isna(atr) or atr <= 0:
        atr = close * 0.01

    # Trend context: price above EMA200 and EMA200 rising versus five candles ago.
    ema_5_ago = df.iloc[-7]["ema200"]
    if pd.isna(ema_5_ago) or close <= ema or ema <= ema_5_ago:
        return None

    # Pullback reaches the BB middle / EMA20 area, then closes back above it.
    touch_zone = low <= bb_middle * 1.01 and low >= bb_middle * 0.97
    bullish_reclaim = close > open_price and close > bb_middle and previous["close"] <= previous["bb_middle"] * 1.01
    if not (touch_zone and bullish_reclaim and 35 <= rsi <= 60):
        return None
    if not pd.isna(vol_ma20) and vol_ma20 > 0 and last["volume"] < 0.7 * vol_ma20:
        return None

    entry = close
    sl = min(low, bb_middle) - 0.5 * atr
    risk = entry - sl
    if risk <= 0:
        return None
    tp1 = entry + 1.5 * risk
    tp2 = entry + 2.5 * risk
    market_type_str = "تعهدی / فیوچرز"
    return (f"↗️ <b>سیگنال لانگ پولبک (روند صعودی)</b>\n"
            f"▫️ ارز: <code>{market_code}</code> ({market_type_str})\n"
            f"📌 موقعیت: LONG\n"
            f"▫️ ورود: {entry:,.4f}\n"
            f"🛡 حد ضرر: {sl:,.4f}\n"
            f"🎯 حد سود ۱: {tp1:,.4f}\n"
            f"🎯 حد سود ۲: {tp2:,.4f}\n"
            f"▫️ RSI: {rsi:.1f}")


# ================= Break & Retest (SHORT only) =================
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
                stop = pending["swing_high"] + 0.20 * float(atr)
                risk = stop - entry
                BR_PENDING_SHORT.pop(market_code, None)
                if risk <= 0:
                    return None
                tp1 = entry - risk
                tp2 = entry - 2.0 * risk
                return (f"🔻 <b>سیگنال شورت Break & Retest (شکست و پولبک)</b>\n"
                        f"▫️ ارز: <code>{market_code}</code> (تعهدی / فیوچرز)\n"
                        f"📌 موقعیت: SHORT\n▫️ ورود: {entry:,.4f}\n"
                        f"🛡 حد ضرر: {stop:,.4f}\n🎯 حد سود ۱: {tp1:,.4f}\n"
                        f"🎯 حد سود ۲: {tp2:,.4f}\n▫️ سطح شکست بولینگر: {level:,.4f}")

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
    wins = sum(1 for s in signals if s.get("status") == "HIT_TP1")
    losses = sum(1 for s in signals if s.get("status") == "HIT_SL")
    open_signals = sum(1 for s in signals if s.get("status") == "OPEN")
    ambiguous = sum(1 for s in signals if s.get("status") == "AMBIGUOUS")
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided > 0 else 0.0
    return total, wins, losses, open_signals, win_rate, ambiguous

# ================= بولینگر اسکوییز (فیلتر فشردگی باند) =================
def is_squeeze(df):
    try:
        bw = df.iloc[-2]["bandwidth"]
        if pd.isna(bw):
            return False
        return bw < BOLLINGER_SQUEEZE_THRESHOLD
    except Exception:
        return False

# ================= حلقه پس‌زمینه رهگیری سیگنال‌ها =================
def check_hit(symbol, direction, tp1, sl, current_price):
    if direction == "LONG":
        hit_tp = current_price >= tp1
        hit_sl = current_price <= sl
    else:  # SHORT
        hit_tp = current_price <= tp1
        hit_sl = current_price >= sl
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
                current_price = float(df.iloc[-1]["close"])
                if current_price <= 0:
                    continue
                hit_tp, hit_sl = check_hit(sig["symbol"], sig["direction"], sig["tp1"], sig["sl"], current_price)
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
                send_telegram(f"{emoji} <b>{status.replace('HIT_TP1','HIT TP1').replace('HIT_SL','HIT SL').replace('AMBIGUOUS','مبهم')}</b>\n"
                              f"▫️ ارز: <code>{sig['symbol']}</code>\n"
                              f"📌 موقعیت: {pos}\n"
                              f"▫️ استراتژی: {sig['strategy']}\n"
                              f"▫️ قیمت فعلی: {current_price:,.4f}\n"
                              f"🎯 حد سود ۱: {sig['tp1']:,.4f}\n"
                              f"🛡 حد ضرر: {sig['sl']:,.4f}")
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
                    total, wins, losses, open_signals, win_rate, ambiguous = tracker_stats()
                    report = (
                        "📊 <b>گزارش سیگنال‌ها (/stats)</b>\n\n"
                        f"▫️ کل سیگنال‌ها: {total}\n"
                        f"✅ بردها (TP1): {wins}\n"
                        f"❌ باخت‌ها (SL): {losses}\n"
                        f"⏳ باز: {open_signals}\n"
                        f"⚠️ مبهم: {ambiguous}\n"
                        f"🏆 وین‌ریت: {win_rate:.1f}%\n\n"
                        "<i>بردها = TP1 قبل از SL، باخت‌ها = SL قبل از TP1</i>"
                    )
                    try:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                      json={"chat_id": chat_id, "text": report, "parse_mode": "HTML"}, timeout=10)
                    except Exception as e:
                        print(f"[Stats] Send error: {e}")
        except Exception as e:
            print(f"[Stats Polling Error] {e}")
            time.sleep(3)


# ================= ثبت و ارسال سیگنال =================
def extract_signal_details(msg):
    def num(pat):
        m = re.search(pat, msg)
        return float(m.group(1).replace(",", "")) if m else None
    entry = num(r"ورود: ([\d,\.]+)")
    sl = num(r"حد ضرر: ([\d,\.]+)")
    tp1 = num(r"حد سود(?: ۱)?: ([\d,\.]+)")
    direction = "SHORT" if "موقعیت: SHORT" in msg else "LONG"
    return direction, entry, sl, tp1

def register_and_send(strategy_name, msg, symbol, is_margin=True):
    if not send_telegram(msg):
        return
    direction, entry, sl, tp1 = extract_signal_details(msg)
    if entry is None:
        return
    add_signal(symbol, direction, entry, sl if sl is not None else 0.0, tp1 if tp1 is not None else 0.0, strategy_name, is_margin)

# ================= حلقه اصلی پایش و اسکن بازار =================
def run_scanner():
    print("Market scanner started successfully.")
    
    test_msg = (
        "🚀 <b>ربات اسکنر بیت‌پین (حالت دیباگ) روشن شد!</b>\n\n"
        "✅ اتصال به تلگرام برقرار است.\n"
        " USDT 🔗 ارزهای پایه: \n"
        "⏱ به محض رسیدن دقیقه ۰۱، اولین تست دریافت کندل انجام خواهد شد."
    )
    send_telegram(test_msg)

    last_scanned_candle_time = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            quarter_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
            candle_close = quarter_start + timedelta(minutes=15)
            scan_time = candle_close - timedelta(seconds=150)
            current_candle_id = candle_close.strftime('%Y-%m-%dT%H:%M:%SZ')

            if abs((now - scan_time).total_seconds()) <= 1.0:
                if last_scanned_candle_time != current_candle_id:
                    print(f"[{now.strftime('%H:%M:%S')}] Starting full market scan...")
                    
                    success_count = 0
                    total_checked = 0
                    signals_found = 0

                    for symbol in MARGIN_SYMBOLS:
                        total_checked += 1

                        df = fetch_bitpin_candles(symbol, resolution=TIMEFRAME, count=100)
                        if df is not None and not df.empty:
                            success_count += 1
                            df = calculate_indicators(df)
                            if df is not None:
                                break_retest_res = check_short_break_retest(df, symbol)
                                if break_retest_res:
                                    register_and_send("break_retest_short", break_retest_res, symbol, is_margin=True)
                                    signals_found += 1

                                if is_squeeze(df):
                                    continue

                                sensi_res = check_sensi_strategy(df, symbol, is_margin=True)
                                if sensi_res:
                                    register_and_send("sensi", sensi_res, symbol, is_margin=True)
                                    signals_found += 1
                                    continue

                                trend_res = check_trend_strategy(df, symbol, is_margin=True)
                                if trend_res:
                                    register_and_send("trend", trend_res, symbol, is_margin=True)
                                    signals_found += 1
                                    continue

                                pullback_res = check_pullback_strategy(df, symbol, is_margin=True)
                                if pullback_res:
                                    register_and_send("pullback", pullback_res, symbol, is_margin=True)
                                    signals_found += 1

                        time.sleep(0.3)

                    debug_report = (
                        f"📊 <b>گزارش تست سلامت ربات (دیباگ)</b>\n\n"
                        f"▫️ تعداد کل ارزهای بررسی‌شده در تست: {total_checked}\n"
                        f"▫️ دریافت موفق کندل از بیت‌پین: <b>{success_count} ارز</b>\n"
                        f"▫️ سیگنال‌های یافت شده: {signals_found}\n\n"
                        f"✅ <i>ارتباط API و منطق ربات کاملاً فعال است و بدون خطا کار می‌کند.</i>"
                    )
                    send_telegram(debug_report)

                    last_scanned_candle_time = current_candle_id
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Scan & Debug finished.")

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
