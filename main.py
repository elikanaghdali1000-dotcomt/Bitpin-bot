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
# Bitpin trade fee, separately charged on entry and exit (0.1% each by default).
# Set either rate to 0.001 for 0.1%; override independently with environment variables.
BITPIN_ENTRY_FEE_RATE = float(os.getenv("BITPIN_ENTRY_FEE_RATE", "0.001"))
BITPIN_EXIT_FEE_RATE = float(os.getenv("BITPIN_EXIT_FEE_RATE", "0.001"))
ESTIMATED_ROUND_TRIP_FEE = float(os.getenv(
    "ESTIMATED_ROUND_TRIP_FEE",
    str(BITPIN_ENTRY_FEE_RATE + BITPIN_EXIT_FEE_RATE)))
# P&L amount is expressed in quote currency for this many units of the asset.
NET_PROFIT_UNITS = float(os.getenv("NET_PROFIT_UNITS", "1.0"))
BOLLINGER_SQUEEZE_THRESHOLD = float(os.getenv("BOLLINGER_SQUEEZE_THRESHOLD", "1.9"))  # درصد؛ کمتر از این مقدار سیگنال مسدود می‌شود
TRACKER_FILE = os.getenv("SIGNAL_TRACKER_FILE", "signal_tracker.json")

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

# ================= دریافت قیمت لحظه‌ای تیکر از بیت‌پین =================
def fetch_bitpin_ticker_price(market_code):
    """Return the live Bitpin ticker price; never substitute a candle close."""
    headers = {"User-Agent": "Mozilla/5.0"}
    urls = [
        f"{BASE_API}/v1/mkt/ticker/{market_code}/",
        f"{BASE_API}/v1/mkt/tickers/",
    ]

    def extract_price(payload):
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("symbol", item.get("market")) == market_code:
                    found = extract_price(item)
                    if found is not None:
                        return found
            return None
        if not isinstance(payload, dict):
            return None
        for key in ("last", "last_price", "price", "close", "c", "rate"):
            value = payload.get(key)
            try:
                price = float(value)
                if math.isfinite(price) and price > 0:
                    return price
            except (TypeError, ValueError):
                pass
        for key in ("data", "output", "result", "ticker"):
            nested = payload.get(key)
            found = extract_price(nested)
            if found is not None:
                return found
        # Some public ticker responses map market symbols directly to records.
        return extract_price(payload.get(market_code))

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=8)
            if response.status_code == 200:
                price = extract_price(response.json())
                if price is not None:
                    return price
        except Exception as e:
            print(f"[Bitpin Ticker] {market_code} fetch error: {e}")
    print(f"[Bitpin Ticker] No live price available for {market_code}; signal skipped.")
    return None

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
    buffer = 0.20 * float(atr)
    return float(band) - buffer if direction == "LONG" else float(band) + buffer

def risk_target(entry, direction, risk, multiple=1.5):
    """Calculate a TP in the profitable direction from entry, never toward the stop."""
    entry, risk, multiple = float(entry), float(risk), float(multiple)
    if direction not in ("LONG", "SHORT") or not math.isfinite(entry + risk + multiple):
        raise ValueError("Invalid direction or non-finite risk/entry/target multiple")
    if entry <= 0 or risk <= 0 or multiple <= 0:
        raise ValueError("Entry, risk, and target multiple must be positive")
    # Solve for target after both notional-based fees, so the intended gross
    # risk multiple remains after fees (fee charged on exit target notional).
    entry_fee = max(0.0, BITPIN_ENTRY_FEE_RATE)
    exit_fee = max(0.0, BITPIN_EXIT_FEE_RATE)
    desired_net_move = risk * multiple
    if direction == "LONG":
        target = (entry * (1.0 + entry_fee) + desired_net_move) / (1.0 - exit_fee)
    else:
        target = (entry * (1.0 - entry_fee) - desired_net_move) / (1.0 + exit_fee)
    if (direction == "LONG" and target <= entry) or (direction == "SHORT" and target >= entry):
        raise ValueError("Take-profit must lie beyond entry in the profitable direction")
    return target

def net_profit_at_target(entry, target, direction, units=NET_PROFIT_UNITS):
    """Return fee-adjusted P&L for a target, as percent of entry notional and quote amount."""
    entry, target, units = float(entry), float(target), float(units)
    if entry <= 0 or target <= 0 or units < 0 or direction not in ("LONG", "SHORT"):
        raise ValueError("Invalid inputs for net-profit calculation")
    gross_per_unit = target - entry if direction == "LONG" else entry - target
    fee_per_unit = (entry * BITPIN_ENTRY_FEE_RATE) + (target * BITPIN_EXIT_FEE_RATE)
    net_per_unit = gross_per_unit - fee_per_unit
    net_pct = (net_per_unit / entry) * 100.0
    return net_pct, net_per_unit * units

def build_signal(strategy, market_code, direction, entry, order_type, stop, tp1, tp2=None, extra=None):
    # Candle values still drive strategy/filter calculations; the emitted entry uses
    # Bitpin's live ticker, and no candle-close fallback is allowed.
    live_entry = fetch_bitpin_ticker_price(market_code)
    if live_entry is None:
        return None
    entry, stop, tp1 = float(live_entry), float(stop), float(tp1)
    if direction not in ("LONG", "SHORT"):
        raise ValueError(f"Unsupported signal direction: {direction}")
    valid = (stop < entry and tp1 > entry) if direction == "LONG" else (stop > entry and tp1 < entry)
    if not valid:
        raise ValueError(f"Invalid {direction} signal levels: require SL/TP on opposite sides of entry")
    if tp2 is not None:
        tp2 = float(tp2)
        if (direction == "LONG" and tp2 <= entry) or (direction == "SHORT" and tp2 >= entry):
            raise ValueError(f"Invalid {direction} TP2: must lie in the profitable direction")
    if BITPIN_ENTRY_FEE_RATE < 0 or BITPIN_EXIT_FEE_RATE < 0:
        raise ValueError("Bitpin fee rates cannot be negative")
    side_emoji = "🟢" if direction == "LONG" else "🔴"
    if str(order_type).upper() == "LIMIT":
        entry_label = "Entry Price (planned LIMIT; fill not guaranteed)"
        entry_note = "قیمت ورود لیمیت برنامه‌ریزی‌شده است؛ تا زمان پرشدن سفارش، قیمت اجرا قطعی نیست."
    else:
        entry_label = "Entry Price (signal-candle close reference)"
        entry_note = "قیمت مرجع، کلوز آخرین کندل بررسی‌شده است؛ قیمت اجرای واقعی سفارش بازار ممکن است متفاوت باشد."
    lines = [f"{side_emoji} <b>{direction} SIGNAL</b>",
             f"Symbol: <code>{market_code}</code>", f"Strategy: {strategy}",
             f"Side: {direction}", f"Entry Type: {order_type}",
             f"💰 {entry_label}: <code>{format_price(entry)}</code>",
             f"🎯 TP1: <code>{format_price(tp1)}</code>"]
    net_pct, net_amount = net_profit_at_target(entry, tp1, direction)
    lines.append(f"   Net Profit @ TP1 (after entry+exit fees): {net_pct:+.3f}% | {net_amount:+.8f} quote / {NET_PROFIT_UNITS:g} unit(s)")
    if tp2 is not None:
        lines.append(f"✅ TP2: <code>{format_price(tp2)}</code>")
        net_pct2, net_amount2 = net_profit_at_target(entry, tp2, direction)
        lines.append(f"   Net Profit @ TP2 (after entry+exit fees): {net_pct2:+.3f}% | {net_amount2:+.8f} quote / {NET_PROFIT_UNITS:g} unit(s)")
    lines.append(f"🔴 Stop Loss: <code>{format_price(stop)}</code>")
    lines.append(f"Fees: entry {BITPIN_ENTRY_FEE_RATE*100:.3f}% + exit {BITPIN_EXIT_FEE_RATE*100:.3f}% (Bitpin trade fees)")
    lines.append(f"<i>{entry_note}</i>")
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
    candle_range = float(candle["high"] - candle["low"])
    bearish = (candle["close"] < candle["open"] or
               (candle_range > 0 and candle["close"] < candle["low"] + 0.4 * candle_range))
    if near_resistance and dried and bearish:
        entry = float(candle["close"])
        stop = bollinger_stop(candle, "SHORT")
        if stop is not None and stop > entry:
            risk = stop - entry
            return build_signal("بازگشت سنسی با کاهش حجم", market_code, "SHORT", entry,
                                "MARKET", stop, risk_target(entry, "SHORT", risk, 1.5),
                                risk_target(entry, "SHORT", risk, 2.5))
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
                                risk_target(entry, "SHORT", risk, 2.5),
                                extra=f"RSI: {float(rsi):.1f}")
    return None

def check_pullback_strategy(df, market_code, is_margin=True):
    if df is None or len(df) < 55:
        return None
    candle, previous = df.iloc[-2], df.iloc[-3]
    close, op, low = (float(candle[k]) for k in ("close", "open", "low"))
    ema, middle, rsi = candle["ema200"], candle["bb_middle"], candle["rsi"]
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
    # Prefer a resting bid at the BB middle; never suggest a buy above the signal close.
    entry = min(close, float(middle))
    stop = bollinger_stop(candle, "LONG")
    if stop is None or stop >= entry:
        return None
    risk = entry - stop
    ratio = float(candle["volume"] / vol_ma20)
    return build_signal("پولبک روند صعودی", market_code, "LONG", entry, "LIMIT",
                        stop, risk_target(entry, "LONG", risk, 1.5), risk_target(entry, "LONG", risk, 2.5),
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
                stop = bollinger_stop(candle, "SHORT")
                risk = stop - entry if stop is not None else -1
                BR_PENDING_SHORT.pop(market_code, None)
                if risk <= 0:
                    return None
                return build_signal("شکست و بازآزمایی باند پایینی بولینگر", market_code, "SHORT", entry,
                                    "LIMIT", stop, risk_target(entry, "SHORT", risk, 1.5),
                                    risk_target(entry, "SHORT", risk, 2.5),
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
            }
    return None



# ================= استراتژی‌های Elite با تقارن LONG/SHORT =================
def _valid_candle(c):
    return all(pd.notna(c.get(k)) for k in ("open", "high", "low", "close", "volume")) and float(c["high"]) > float(c["low"])

def _structural_stop(df, candle, direction, lookback=20):
    """Use the more protective of nearby structure and Bollinger edge, with ATR buffer."""
    base = bollinger_stop(candle, direction)
    if base is None:
        return None
    recent = df.iloc[-(lookback + 2):-2] if len(df) > 2 else df.iloc[:-1]
    if recent.empty:
        return base
    atr = candle.get("atr", float("nan"))
    atr = float(atr) if pd.notna(atr) and float(atr) > 0 else float(candle["close"]) * 0.005
    pad = 0.20 * atr
    swing = float(recent["low"].min()) if direction == "LONG" else float(recent["high"].max())
    structural = swing - pad if direction == "LONG" else swing + pad
    # Select nearest valid protective boundary to avoid unnecessarily wide stops.
    entry = float(candle["close"])
    candidates = [x for x in (base, structural) if (x < entry if direction == "LONG" else x > entry)]
    if not candidates:
        return None
    return max(candidates) if direction == "LONG" else min(candidates)

def _signal_from_candle(df, candle, market_code, direction, strategy, order_type="MARKET", extra=None):
    entry = float(candle["close"])
    stop = _structural_stop(df, candle, direction)
    if stop is None or (stop >= entry if direction == "LONG" else stop <= entry):
        return None
    risk = abs(entry - stop)
    return build_signal(strategy, market_code, direction, entry, order_type, stop,
                        risk_target(entry, direction, risk, 1.5),
                        risk_target(entry, direction, risk, 2.5), extra)

def check_liquidity_sweep(df, market_code):
    if df is None or len(df) < 55:
        return None
    c = df.iloc[-2]
    prior = df.iloc[-22:-2]
    if not _valid_candle(c) or len(prior) < 15:
        return None
    span = float(c.high - c.low)
    lower_wick = min(float(c.open), float(c.close)) - float(c.low)
    upper_wick = float(c.high) - max(float(c.open), float(c.close))
    ma = c.get("vol_ma20", float("nan"))
    if pd.isna(ma) or ma <= 0 or float(c.volume) < 1.2 * float(ma):
        return None
    swing_low, swing_high = float(prior.low.min()), float(prior.high.max())
    if float(c.low) < swing_low and float(c.close) > swing_low and lower_wick / span >= 0.40:
        return _signal_from_candle(df, c, market_code, "LONG", "شکار نقدینگی و رد قیمت")
    if float(c.high) > swing_high and float(c.close) < swing_high and upper_wick / span >= 0.40:
        return _signal_from_candle(df, c, market_code, "SHORT", "شکار نقدینگی و رد قیمت")
    return None

def check_volume_divergence(df, market_code):
    if df is None or len(df) < 55:
        return None
    c = df.iloc[-2]
    prior = df.iloc[-22:-2]
    if len(prior) < 15:
        return None
    ma, rsi = c.get("vol_ma20", float("nan")), c.get("rsi", float("nan"))
    if pd.isna(ma) or ma <= 0 or pd.isna(rsi):
        return None
    old_high, old_low = float(prior.high.max()), float(prior.low.min())
    old_vol = float(prior.volume.max())
    # New swing extreme on at least 0.1% extension, with materially lower participation.
    if float(c.high) > old_high * 1.001 and float(c.volume) < 0.70 * old_vol and rsi >= 60:
        return _signal_from_candle(df, c, market_code, "SHORT", "واگرایی حجم و فرسودگی سقف")
    if float(c.low) < old_low * 0.999 and float(c.volume) < 0.70 * old_vol and rsi <= 40:
        return _signal_from_candle(df, c, market_code, "LONG", "واگرایی حجم و فرسودگی کف")
    return None

def check_climax_exhaustion(df, market_code):
    if df is None or len(df) < 55:
        return None
    c = df.iloc[-2]
    if not _valid_candle(c):
        return None
    ma = c.get("vol_ma20", float("nan"))
    if pd.isna(ma) or ma <= 0 or float(c.volume) < 2.5 * float(ma):
        return None
    span = float(c.high - c.low)
    upper_wick = float(c.high) - max(float(c.open), float(c.close))
    lower_wick = min(float(c.open), float(c.close)) - float(c.low)
    at_upper = pd.notna(c.get("bb_upper")) and float(c.high) >= float(c.bb_upper)
    at_lower = pd.notna(c.get("bb_lower")) and float(c.low) <= float(c.bb_lower)
    if at_upper and upper_wick / span >= 0.35 and float(c.close) < float(c.high) - 0.4 * span:
        return _signal_from_candle(df, c, market_code, "SHORT", "حجم اوج و فرسودگی صعودی")
    if at_lower and lower_wick / span >= 0.35 and float(c.close) > float(c.low) + 0.4 * span:
        return _signal_from_candle(df, c, market_code, "LONG", "حجم اوج و فرسودگی نزولی")
    return None

def check_pullback_short_strategy(df, market_code):
    if df is None or len(df) < 55:
        return None
    c, prev = df.iloc[-2], df.iloc[-3]
    ema, middle, rsi, ma = c.get("ema200"), c.get("bb_middle"), c.get("rsi"), c.get("vol_ma20")
    ema_old = df.iloc[-7].get("ema200")
    if any(pd.isna(v) for v in (ema, middle, rsi, ma, ema_old)) or ma <= 0:
        return None
    touched = float(c.high) >= float(middle) * 0.97 and float(c.high) <= float(middle) * 1.03
    rejection = float(c.close) < float(c.open) and float(c.close) < float(middle) and float(prev.close) >= float(prev.bb_middle) * 0.99
    if float(c.close) < float(ema) and float(ema) < float(ema_old) and touched and rejection and 40 <= float(rsi) <= 65 and float(c.volume) >= PULLBACK_MIN_VOLUME_MULT * float(ma):
        return _signal_from_candle(df, c, market_code, "SHORT", "پولبک روند نزولی")
    return None

BR_PENDING_LONG = {}
def check_long_break_retest(df, market_code):
    """Mirror of lower-band short breakout/retest using upper-band bullish retest."""
    if df is None or len(df) < 55:
        return None
    c, prev = df.iloc[-2], df.iloc[-3]
    ts = c.get("timestamp", df.index[-2])
    key = (market_code, "long")
    if BR_LAST_PROCESSED.get(key) == ts:
        return None
    BR_LAST_PROCESSED[key] = ts
    avg = float(df.iloc[-22:-2]["volume"].mean())
    if not math.isfinite(avg) or avg <= 0:
        return None
    pending = BR_PENDING_LONG.get(market_code)
    if pending:
        pending["candles_waited"] += 1
        level = pending["level"]
        if c.close < level * (1 - BR_RETEST_TOLERANCE_PCT) or pending["candles_waited"] > BR_MAX_RETEST_CANDLES:
            BR_PENDING_LONG.pop(market_code, None); pending = None
        else:
            span = float(c.high - c.low)
            body = abs(float(c.close-c.open))/span if span > 0 else 0
            touched = c.low <= level * (1 + BR_RETEST_TOLERANCE_PCT) and c.high >= level * (1 - BR_RETEST_TOLERANCE_PCT)
            if touched and c.close > c.open and c.close > level and c.volume > avg and c.volume > prev.volume and body >= BR_MIN_REJECTION_BODY_RATIO and (c.close-c.low)/span >= 0.55:
                BR_PENDING_LONG.pop(market_code, None)
                return _signal_from_candle(df, c, market_code, "LONG", "شکست و بازآزمایی باند بالایی بولینگر", "LIMIT", f"Breakout Level: {format_price(level)}")
    if pending is None:
        span = float(c.high-c.low)
        body = abs(float(c.close-c.open))/span if span > 0 else 0
        upper = c.get("bb_upper", float("nan"))
        if pd.notna(upper) and span > 0 and c.volume > BR_BREAKOUT_VOL_MULT*avg and body >= BR_MIN_BREAKOUT_BODY_RATIO and c.close > upper and c.close > c.open and (c.close-c.low)/span >= 0.65:
            BR_PENDING_LONG[market_code] = {"level": float(upper), "candles_waited": 0}
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

def add_signal(symbol, direction, entry, sl, tp1, strategy, is_margin=True, tp2=None):
    sid = f"{symbol}_{strategy}_{uuid.uuid4().hex[:8]}"
    rec = {
        "id": sid,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_hit": False,
        "last_companion_alert": {},
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
    wins = sum(1 for item in signals if item.get("tp1_hit") or item.get("status") == "HIT_TP1")
    losses = sum(1 for item in signals if item.get("status") == "HIT_SL")
    open_signals = sum(1 for item in signals if item.get("status") == "OPEN")
    ambiguous = sum(1 for item in signals if item.get("status") == "AMBIGUOUS")
    return total, wins, losses, open_signals, ambiguous



# ================= Order Book Watcher =================
ORDERBOOK_DEPTH_LEVELS = 15
ORDERBOOK_IMBALANCE_MULT = 2.5
ORDERBOOK_WHALE_DEPTH_FRACTION = 0.35
ORDERBOOK_WHALE_AVG_MULT = 4.0
ORDERBOOK_WALL_DISTANCE_PCT = 0.02

def fetch_order_book(symbol):
    """Fetch Bitpin depth. Prefer the user-provided /mth/ path, then /mkt/ and .ir."""
    urls = [
        f"{BASE_API}/v1/mth/orderbook/{symbol}/",
        f"{BASE_API}/v1/mkt/orderbook/{symbol}/",
        f"https://api.bitpin.ir/api/v1/mth/orderbook/{symbol}/",
        f"https://api.bitpin.ir/api/v1/mkt/orderbook/{symbol}/",
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code != 200:
                continue
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                data = data["data"]
            if not isinstance(data, dict):
                continue
            orders = data.get("orders", data)
            if isinstance(orders, dict) and ("bids" in orders or "asks" in orders):
                return {"bids": orders.get("bids", []), "asks": orders.get("asks", [])}
        except Exception as exc:
            print(f"[OrderBook] Fetch failed {url}: {exc}")
    return None

def _orderbook_levels(raw_levels):
    """Normalize public API list/dict levels into positive (price, amount) pairs."""
    levels = []
    if not isinstance(raw_levels, (list, tuple)):
        return levels
    for item in raw_levels[:ORDERBOOK_DEPTH_LEVELS]:
        try:
            if isinstance(item, dict):
                price = float(item.get("price", item.get("rate")))
                amount = float(item.get("amount", item.get("volume", item.get("quantity", item.get("qty")))))
            else:
                price, amount = float(item[0]), float(item[1])
            if math.isfinite(price) and math.isfinite(amount) and price > 0 and amount > 0:
                levels.append((price, amount))
        except (TypeError, ValueError, IndexError):
            continue
    return levels

def analyze_order_book(book, direction, current_price):
    """Return adverse depth alerts and auditable depth metrics; no alert on bad inputs."""
    if not isinstance(book, dict) or direction not in ("LONG", "SHORT"):
        return [], {}
    try:
        price_now = float(current_price)
    except (TypeError, ValueError):
        return [], {}
    if not math.isfinite(price_now) or price_now <= 0:
        return [], {}
    bids = _orderbook_levels(book.get("bids", []))
    asks = _orderbook_levels(book.get("asks", []))
    bid_volume = sum(amount for _, amount in bids)
    ask_volume = sum(amount for _, amount in asks)
    total = bid_volume + ask_volume
    metrics = {"bid_volume": bid_volume, "ask_volume": ask_volume,
               "imbalance_ratio": bid_volume / ask_volume if ask_volume else None,
               "levels": len(bids) + len(asks)}
    if not bids or not asks or total <= 0:
        return [], metrics
    alerts = []
    if direction == "LONG" and ask_volume >= ORDERBOOK_IMBALANCE_MULT * bid_volume:
        alerts.append(("orderbook_imbalance", "⚠️ عدم تعادل سنگین اردربوک (فشار فروش در عمق بازار)"))
    elif direction == "SHORT" and bid_volume >= ORDERBOOK_IMBALANCE_MULT * ask_volume:
        alerts.append(("orderbook_imbalance", "⚠️ عدم تعادل سنگین اردربوک (فشار خرید و حمایت سنگین در عمق بازار)"))

    # Whale threshold is evaluated against all returned top-depth levels.
    all_volumes = [v for _, v in bids + asks]
    avg_level = total / len(all_volumes) if all_volumes else 0
    whale = lambda amount: amount >= ORDERBOOK_WHALE_DEPTH_FRACTION * total or (avg_level > 0 and amount > ORDERBOOK_WHALE_AVG_MULT * avg_level)
    if direction == "LONG":
        walls = [(p, v) for p, v in asks if p >= price_now and (p-price_now)/price_now <= ORDERBOOK_WALL_DISTANCE_PCT and whale(v)]
        if walls:
            alerts.append(("whale_wall", "🐋 دیوار فروش سنگین (Whale Sell Wall) در اردر بوک شناسایی شد!"))
    else:
        walls = [(p, v) for p, v in bids if p <= price_now and (price_now-p)/price_now <= ORDERBOOK_WALL_DISTANCE_PCT and whale(v)]
        if walls:
            alerts.append(("whale_wall", "🐋 دیوار خرید سنگین (Whale Buy Wall) در اردر بوک شناسایی شد!"))
    metrics["whale_walls"] = walls if "walls" in locals() else []
    metrics["total_depth"] = total
    return alerts, metrics

def companion_alerts(sig, df):
    """Return alert texts and state updates from latest candle; direction symmetric."""
    if df is None or df.empty:
        return [], {}
    c = df.iloc[-1]
    if not _valid_candle(c):
        return [], {}
    side = sig.get("direction")
    if side not in ("LONG", "SHORT"):
        return [], {}
    entry, tp1, sl = float(sig["entry"]), float(sig["tp1"]), float(sig["sl"])
    tp2 = sig.get("tp2")
    price = float(c.close)
    volume_ma = c.get("vol_ma20", float("nan"))
    ratio = float(c.volume) / float(volume_ma) if pd.notna(volume_ma) and float(volume_ma) > 0 else 0
    span = float(c.high-c.low)
    upper_wick = (float(c.high)-max(float(c.open),float(c.close)))/span if span > 0 else 0
    lower_wick = (min(float(c.open),float(c.close))-float(c.low))/span if span > 0 else 0
    middle = c.get("bb_middle", float("nan"))
    upper, lower = c.get("bb_upper", float("nan")), c.get("bb_lower", float("nan"))
    bearish = float(c.close) < float(c.open)
    bullish = float(c.close) > float(c.open)
    alerts, updates = [], {}
    tag = str(c.get("timestamp", df.index[-1]))
    if side == "LONG":
        if bearish and ratio >= 2.0 and (float(c.open)-float(c.close))/span >= 0.45:
            alerts.append(("volume_reversal", "🚨 <b>هشدار همراه معامله (خطر بازگشت نزولی)</b>\nحجم فروش غیرعادی و کندل نزولی مشکوک مشاهده شد. پیشنهاد: سیو سود، بستن دستی یا انتقال حد ضرر به نقطه ورود (Risk-Free)."))
        if pd.notna(upper) and float(c.high) >= float(upper) and upper_wick >= 0.35 and ratio < 1.0:
            alerts.append(("exhaustion", "⚠️ <b>هشدار همراه معامله (کاهش مومنتوم)</b>\nبرخورد با باند/مقاومت و سایه بالایی همراه کاهش حجم؛ پیشنهاد: سیو سود پله‌ای."))
        if pd.notna(middle) and float(c.close) < float(middle) and ratio >= 1.0:
            alerts.append(("structure_flip", "⚠️ شکست رو به پایین خط تعادل (میانگین متحرک). ساختار صعودی تضعیف شد."))
        reached = float(c.high) >= tp1
        favorable = price >= entry
        progress = (price-entry)/(float(tp2)-entry) if tp2 and float(tp2)>entry else 0
    else:
        if bullish and ratio >= 2.0 and (float(c.close)-float(c.open))/span >= 0.45:
            alerts.append(("volume_reversal", "🚨 <b>هشدار همراه معامله (خطر بازگشت صعودی)</b>\nحجم خرید غیرعادی و کندل صعودی مشکوک مشاهده شد. پیشنهاد: سیو سود، بستن دستی یا انتقال حد ضرر به نقطه ورود (Risk-Free)."))
        if pd.notna(lower) and float(c.low) <= float(lower) and lower_wick >= 0.35 and ratio < 1.0:
            alerts.append(("exhaustion", "⚠️ <b>هشدار همراه معامله (کاهش مومنتوم)</b>\nبرخورد با باند/حمایت و سایه پایینی همراه کاهش حجم؛ پیشنهاد: سیو سود پله‌ای."))
        if pd.notna(middle) and float(c.close) > float(middle) and ratio >= 1.0:
            alerts.append(("structure_flip", "⚠️ شکست رو به بالای خط تعادل (میانگین متحرک). ساختار نزولی تضعیف شد."))
        reached = float(c.low) <= tp1
        favorable = price <= entry
        progress = (entry-price)/(entry-float(tp2)) if tp2 and float(tp2)<entry else 0
    if reached and not sig.get("tp1_hit"):
        updates["tp1_hit"] = True
        alerts.append(("tp1_milestone", f"✅ <b>هدف TP1 لمس شد</b>\nپیشنهاد همراه: بستن ۵۰٪ موقعیت و انتقال حد ضرر به نقطه ورود (Risk-Free) = <code>{format_price(entry)}</code>."))
    if favorable and progress >= 0.50 and not sig.get("trail_50"):
        updates["trail_50"] = True
        trail = entry + (float(tp2)-entry)*0.20 if side == "LONG" else entry - (entry-float(tp2))*0.20
        alerts.append(("trail_50", f"📈 قیمت در مسیر TP2 است؛ حدضرر متحرک پیشنهادی: <code>{format_price(trail)}</code> (پیشرفت ۵۰٪)."))
    if favorable and progress >= 0.75 and not sig.get("trail_75"):
        updates["trail_75"] = True
        trail = entry + (float(tp2)-entry)*0.45 if side == "LONG" else entry - (entry-float(tp2))*0.45
        alerts.append(("trail_75", f"📈 پیشرفت ۷۵٪ به‌سوی TP2؛ حدضرر متحرک پیشنهادی: <code>{format_price(trail)}</code>."))
    # At TP2, close out tracking; SL still monitored until this point.
    if tp2 and (float(c.high) >= float(tp2) if side == "LONG" else float(c.low) <= float(tp2)):
        updates["status"] = "HIT_TP2"
    elif (float(c.low) <= sl if side == "LONG" else float(c.high) >= sl):
        updates["status"] = "HIT_SL"
    updates["last_candle"] = tag
    return [(key, text, tag) for key, text in alerts], updates


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
                open_signals = {k: v.copy() for k, v in signal_tracker.items() if v.get("status") == "OPEN"}
            for sid, sig in open_signals.items():
                df = fetch_bitpin_candles(sig["symbol"], resolution=TIMEFRAME, count=60)
                df = calculate_indicators(df)
                if df is None or df.empty:
                    continue
                alerts, updates = companion_alerts(sig, df)
                # Query depth once each tracker cycle (60s); deduplication below is per candle/signal.
                book = fetch_order_book(sig["symbol"])
                if book:
                    ob_alerts, _ob_metrics = analyze_order_book(book, sig.get("direction"), float(df.iloc[-1].close))
                    candle_tag = str(df.iloc[-1].get("timestamp", df.index[-1]))
                    alerts.extend((key, text, candle_tag) for key, text in ob_alerts)
                changed = False
                with tracker_lock:
                    record = signal_tracker.get(sid)
                    if not record or record.get("status") != "OPEN":
                        continue
                    record.update(updates)
                    sent = record.setdefault("last_companion_alert", {})
                    for key, message, candle_id in alerts:
                        # A given alert class is sent at most once per candle, with milestone alerts once per trade.
                        if sent.get(key) == candle_id or (key in ("tp1_milestone", "trail_50", "trail_75") and sent.get(key)):
                            continue
                        sent[key] = candle_id
                        send_telegram(f"{message}\nSymbol: <code>{sig['symbol']}</code> | Side: {sig['direction']}")
                    if updates.get("status") in ("HIT_SL", "HIT_TP2"):
                        record["hit_time"] = datetime.now(timezone.utc).isoformat()
                        price = float(df.iloc[-1].close)
                        label = "HIT TP2" if updates["status"] == "HIT_TP2" else "HIT SL"
                        send_telegram(f"{'✅' if label == 'HIT TP2' else '❌'} <b>{label}</b>\nSymbol: <code>{sig['symbol']}</code>\nSide: {sig['direction']}\nCurrent Price: <code>{format_price(price)}</code>")
                    changed = True
                if changed:
                    save_tracker()
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
    entry_match = re.search(r"Entry Price(?:[^:]*):\s*<code>([0-9]+(?:\.[0-9]+)?)</code>", msg)
    entry = float(entry_match.group(1)) if entry_match else None
    sl = num("Stop Loss")
    tp1 = num("TP1") or num("Take Profit 1")
    tp2 = num("TP2")
    direction = "SHORT" if re.search(r"Side:\s*SHORT", msg) else "LONG"
    return direction, entry, sl, tp1, tp2

def register_and_send(strategy_name, msg, symbol, is_margin=True, long_confirmed=False):
    direction, entry, sl, tp1, tp2 = extract_signal_details(msg)
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
    add_signal(symbol, direction, entry, sl, tp1, strategy_name, is_margin, tp2)
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
                                elite_checks = (check_long_break_retest, check_liquidity_sweep,
                                                check_volume_divergence, check_climax_exhaustion,
                                                check_pullback_short_strategy)
                                for strategy_fn in elite_checks:
                                    elite_msg = strategy_fn(df_ind, symbol)
                                    if elite_msg:
                                        # Strategy key remains stable for duplicate prevention.
                                        strategy_key = {check_long_break_retest: "break_retest_long",
                                            check_liquidity_sweep: "liquidity_sweep",
                                            check_volume_divergence: "volume_divergence",
                                            check_climax_exhaustion: "climax_exhaustion",
                                            check_pullback_short_strategy: "pullback_short"}[strategy_fn]
                                        register_and_send(strategy_key, elite_msg, symbol, is_margin=True, long_confirmed=btc_long_confirmed)
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
                                pullback_short_res = check_pullback_short_strategy(df_ind, symbol)
                                if pullback_short_res:
                                    register_and_send("pullback_short", pullback_short_res, symbol, is_margin=True, long_confirmed=btc_long_confirmed)

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
