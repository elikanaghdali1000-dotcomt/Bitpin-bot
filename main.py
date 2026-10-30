# -*- coding: utf-8 -*-
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd
import requests


# ================= تنظیمات =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"

TIMEFRAME = "15"
TIMEFRAME_SECONDS = int(TIMEFRAME) * 60
CHECK_INTERVAL = 60

BB_PERIOD = 20
BB_STD = 2.0
BOLLINGER_SQUEEZE_THRESHOLD = float(
    os.getenv("BOLLINGER_SQUEEZE_THRESHOLD", "2.0")
)

TRACKER_FILE = os.getenv("SIGNAL_TRACKER_FILE", "signal_tracker.json")
SCAN_HEALTH_FILE = os.getenv("SCAN_HEALTH_FILE", "first_scan_notified.flag")

tracker_lock = threading.RLock()
signal_tracker = {}
signal_history_cache = {}

BR_MAX_RETEST_CANDLES = 8
BR_RETEST_TOLERANCE_PCT = 0.15 / 100.0
BR_BREAKOUT_VOL_MULT = 1.5
BR_MIN_BREAKOUT_BODY_RATIO = 0.55
BR_PENDING_SHORT = {}
BR_PENDING_LONG = {}
BR_LAST_PROCESSED = {}

SETUP_MAX_RETEST_CANDLES = 6
SETUP_PENDING = {}
SETUP_LAST_PROCESSED = {}

MARGIN_SYMBOLS = [
    "PAXG_USDT", "SOL_USDT", "SUI_USDT", "GALA_USDT", "GRAM_USDT",
    "HYPE_USDT", "SLVON_USDT", "ETH_USDT", "POGE_USDT", "ADA_USDT",
    "XLM_USDT", "ZEC_USDT", "UNI_USDT", "ASTER_USDT", "S_USDT",
    "LINK_USDT", "FIL_USDT", "DAT_USDT", "WIF_USDT", "LTC_USDT",
    "NEAR_USDT", "ONDO_USDT", "ENA_USDT", "RENDER_USDT", "TRX_USDT",
    "PENGU_USDT", "XRP_USDT", "CAKE_USDT", "AVAX_USDT", "NVDX_USDT",
    "BTC_USDT", "ALGO_USDT", "DASH_USDT", "PUMP_USDT", "LDO_USDT",
]


# ================= سرور Render =================
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
    HTTPServer(("0.0.0.0", port), SimpleHandler).serve_forever()


def self_ping():
    while True:
        time.sleep(600)
        if APP_URL:
            try:
                requests.get(APP_URL, timeout=10)
            except Exception:
                pass


# ================= تلگرام =================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials are not configured.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"Telegram send failed: HTTP {response.status_code}")
        return response.status_code == 200
    except Exception as exc:
        print(f"Telegram send failed: {type(exc).__name__}")
        return False


def notify_first_successful_scan(scanned_count):
    if os.path.exists(SCAN_HEALTH_FILE):
        return

    try:
        fd = os.open(
            SCAN_HEALTH_FILE,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(datetime.now(timezone.utc).isoformat())
    except FileExistsError:
        return
    except OSError as exc:
        print(f"Could not record first scan notification: {exc}")
        return

    send_telegram(
        "✅ <b>اسکن اول ربات انجام شد.</b>\n"
        f"دادهٔ معتبر برای {scanned_count} بازار از "
        f"{len(MARGIN_SYMBOLS)} بازار دریافت و بررسی شد."
    )


# ================= داده و اندیکاتورها =================
def _normalized_timestamp(value):
    timestamp = int(value)
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    return timestamp


def fetch_bitpin_candles(market_code, resolution=TIMEFRAME, count=100):
    try:
        now_ts = int(time.time())
        minutes = int(resolution) if resolution.isdigit() else 15
        from_ts = now_ts - count * minutes * 60 * 2

        response = requests.get(
            OHLC_URL,
            params={
                "symbol": market_code,
                "res": resolution,
                "from": from_ts,
                "to": now_ts,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if response.status_code != 200:
            print(f"OHLC {market_code}: HTTP {response.status_code}")
            return None

        data = response.json()
        if isinstance(data, dict):
            data = data.get("output")
        if not isinstance(data, list) or not data:
            return None

        rows = []
        for candle in data:
            rows.append({
                "timestamp": _normalized_timestamp(
                    candle.get("time", candle.get("t"))
                ),
                "open": float(candle.get("open", candle.get("o"))),
                "high": float(candle.get("high", candle.get("h"))),
                "low": float(candle.get("low", candle.get("l"))),
                "close": float(candle.get("close", candle.get("c"))),
                "volume": float(candle.get("volume", candle.get("v"))),
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("timestamp")
        df = df.drop_duplicates(subset="timestamp", keep="last")
        return df.tail(count).reset_index(drop=True)
    except Exception as exc:
        print(f"OHLC {market_code} failed: {type(exc).__name__}")
        return None


def closed_candles(df, resolution=TIMEFRAME, now_ts=None):
    if df is None or df.empty:
        return None
    if now_ts is None:
        now_ts = time.time()
    period = int(resolution) * 60
    result = df[df["timestamp"] + period <= now_ts].copy()
    return result.reset_index(drop=True)


def calculate_indicators(df):
    if df is None or len(df) < 55:
        return None

    df = df.copy()
    df["bb_middle"] = df["close"].rolling(BB_PERIOD).mean()
    df["bb_std"] = df["close"].rolling(BB_PERIOD).std()
    df["bb_upper"] = df["bb_middle"] + BB_STD * df["bb_std"]
    df["bb_lower"] = df["bb_middle"] - BB_STD * df["bb_std"]
    df["bandwidth"] = (
        (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"] * 100
    )

    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - 100 / (1 + rs)

    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    return df


def check_bitcoin_filter(btc_df):
    if btc_df is None or len(btc_df) < 20:
        return True
    last = btc_df.iloc[-1]
    return last["close"] >= last["bb_middle"]


def check_macro_trend_1h(market_code):
    df = fetch_bitpin_candles(market_code, resolution="60", count=60)
    df = closed_candles(df, resolution="60")
    df = calculate_indicators(df)
    if df is None or df.empty:
        return "NEUTRAL"
    last = df.iloc[-1]
    if last["close"] > last["bb_middle"]:
        return "UP"
    if last["close"] < last["bb_middle"]:
        return "DOWN"
    return "NEUTRAL"


def _has_confirmed_selling_pressure(candle, previous_candle):
    candle_range = candle["high"] - candle["low"]
    vol_ma20 = candle.get("vol_ma20", float("nan"))
    if pd.isna(vol_ma20) or vol_ma20 <= 0 or candle_range <= 0:
        return False
    return (
        candle["close"] < candle["open"]
        and candle["open"] - candle["close"] >= 0.4 * candle_range
        and candle["close"] <= candle["low"] + 0.4 * candle_range
        and candle["volume"] >= 1.2 * vol_ma20
    )


def _has_confirmed_buying_pressure(candle, previous_candle):
    candle_range = candle["high"] - candle["low"]
    vol_ma20 = candle.get("vol_ma20", float("nan"))
    if pd.isna(vol_ma20) or vol_ma20 <= 0 or candle_range <= 0:
        return False
    return (
        candle["close"] > candle["open"]
        and candle["close"] - candle["open"] >= 0.4 * candle_range
        and candle["close"] >= candle["high"] - 0.4 * candle_range
        and candle["volume"] >= 1.2 * vol_ma20
    )


# ================= استراتژی‌ها =================
def check_rsi_divergence(df, market_code):
    if len(df) < 40:
        return None
    last = df.iloc[-1]
    rsi = last["rsi"]
    atr = last["atr"]
    macro_trend = check_macro_trend_1h(market_code)

    recent = df.iloc[-19:-1]
    swing_lows = recent[
        recent["low"] == recent["low"].rolling(3, center=True).min()
    ]["low"]
    swing_highs = recent[
        recent["high"] == recent["high"].rolling(3, center=True).max()
    ]["high"]

    if macro_trend != "DOWN" and len(swing_lows) >= 2:
        previous_low = recent["low"].idxmin()
        if (
            last["low"] <= recent["low"].min()
            and rsi > recent.loc[previous_low, "rsi"]
            and rsi < 42
        ):
            entry = last["close"]
            sl = last["low"] - 0.5 * atr
            risk = entry - sl
            if risk > 0:
                return (
                    f"📈 <b>سیگنال لانگ واگرایی مثبت (RSI)</b>\n"
                    f"▫️ ارز: <code>{market_code}</code>\n📌 LONG\n"
                    f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                    f"🎯 سود ۱: {entry + 1.5 * risk:,.4f}\n🎯 سود ۲: {entry + 2.5 * risk:,.4f}"
                )

    if macro_trend != "UP" and len(swing_highs) >= 2:
        previous_high = recent["high"].idxmax()
        if (
            last["high"] >= recent["high"].max()
            and rsi < recent.loc[previous_high, "rsi"]
            and rsi > 58
        ):
            entry = last["close"]
            sl = last["high"] + 0.5 * atr
            risk = sl - entry
            if risk > 0:
                return (
                    f"📉 <b>سیگنال شورت واگرایی منفی (RSI)</b>\n"
                    f"▫️ ارز: <code>{market_code}</code>\n📌 SHORT\n"
                    f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                    f"🎯 سود ۱: {entry - 1.5 * risk:,.4f}\n🎯 سود ۲: {entry - 2.5 * risk:,.4f}"
                )
    return None


def check_sensi_strategy(df, market_code):
    if df is None or len(df) < 55:
        return None
    sig_candle = df.iloc[-1]
    lookback = df.iloc[-26:-1]
    prior_support = lookback["low"].min()
    vol_ma20 = sig_candle["vol_ma20"]
    if pd.isna(vol_ma20) or vol_ma20 <= 0:
        return None

    is_volume_dried = sig_candle["volume"] / vol_ma20 < 0.70
    atr = sig_candle["atr"]
    near_support = (
        sig_candle["low"] <= prior_support * 1.003
        and sig_candle["low"] >= prior_support * 0.992
    )
    is_bullish_reversal = (
        sig_candle["close"] > sig_candle["open"]
        or _has_confirmed_buying_pressure(sig_candle, df.iloc[-2])
    )

    if near_support and is_volume_dried and is_bullish_reversal:
        entry = sig_candle["close"]
        sl = min(prior_support, sig_candle["low"]) - 0.3 * atr
        risk = entry - sl
        if risk > 0:
            return (
                f"🎯 <b>سیگنال لانگ سنسی (خشکی حجم)</b>\n"
                f"▫️ ارز: <code>{market_code}</code>\n📌 LONG\n"
                f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                f"🎯 سود ۱: {entry + 1.5 * risk:,.4f}\n🎯 سود ۲: {entry + 2.5 * risk:,.4f}"
            )
    return None


def check_trend_strategy(df, market_code):
    if len(df) < 55:
        return None
    last = df.iloc[-1]
    c = last["close"]
    lower = last["bb_lower"]
    upper = last["bb_upper"]
    ema = last["ema200"]
    rsi = last["rsi"]
    atr = last["atr"]
    if pd.isna(atr):
        atr = c * 0.01

    if c <= lower and c > ema and rsi < 35:
        sl = lower - 0.5 * atr
        risk = c - sl
        if risk > 0:
            return (
                f"🟢 <b>سیگنال لانگ بولینگر</b>\n"
                f"▫️ ارز: <code>{market_code}</code>\n📌 LONG\n"
                f"▫️ ورود: {c:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                f"🎯 سود ۱: {c + 1.5 * risk:,.4f}\n🎯 سود ۲: {c + 2.5 * risk:,.4f}"
            )
    if (
        c >= upper and c < ema and rsi > 65
        and _has_confirmed_selling_pressure(last, df.iloc[-2])
    ):
        sl = upper + 0.5 * atr
        risk = sl - c
        if risk > 0:
            return (
                f"🔴 <b>سیگنال شورت بولینگر</b>\n"
                f"▫️ ارز: <code>{market_code}</code>\n📌 SHORT\n"
                f"▫️ ورود: {c:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                f"🎯 سود ۱: {c - 1.5 * risk:,.4f}\n🎯 سود ۲: {c - 2.5 * risk:,.4f}"
            )
    return None


def check_pullback_strategy(df, market_code):
    if df is None or len(df) < 55:
        return None
    last = df.iloc[-1]
    previous = df.iloc[-2]
    close = last["close"]
    open_price = last["open"]
    high = last["high"]
    low = last["low"]
    ema = last["ema200"]
    bb_middle = last["bb_middle"]
    rsi = last["rsi"]
    atr = last["atr"]

    if any(pd.isna(v) for v in [close, open_price, high, low, ema, bb_middle, rsi]) or close <= 0:
        return None
    if pd.isna(atr) or atr <= 0:
        atr = close * 0.01

    touch_zone = low <= bb_middle * 1.01 and low >= bb_middle * 0.97
    bullish_reclaim = (
        close > open_price
        and close > bb_middle
        and _has_confirmed_buying_pressure(last, previous)
    )
    if not (touch_zone and bullish_reclaim and 35 <= rsi <= 60 and close > ema):
        return None

    sl = min(low, bb_middle) - 0.4 * atr
    risk = close - sl
    if risk <= 0:
        return None

    return (
        f"↗️ <b>سیگنال لانگ پولبک میدل‌باند</b>\n"
        f"▫️ ارز: <code>{market_code}</code>\n📌 LONG\n"
        f"▫️ ورود: {close:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
        f"🎯 سود ۱: {close + 1.5 * risk:,.4f}\n🎯 سود ۲: {close + 2.5 * risk:,.4f}"
    )


def check_break_retest(df, market_code):
    if df is None or len(df) < 55:
        return None
    candle = df.iloc[-1]
    previous = df.iloc[-2]
    timestamp = int(candle["timestamp"])

    if BR_LAST_PROCESSED.get(market_code) == timestamp:
        return None
    BR_LAST_PROCESSED[market_code] = timestamp

    prior_volumes = df.iloc[-21:-1]["volume"]
    if len(prior_volumes) < 20:
        return None
    vol_avg = float(prior_volumes.mean())
    if pd.isna(vol_avg) or vol_avg <= 0:
        return None

    pending_s = BR_PENDING_SHORT.get(market_code)
    if pending_s:
        pending_s["candles_waited"] += 1
        pending_s["swing_high"] = max(pending_s["swing_high"], float(candle["high"]))
        level = pending_s["level"]
        tol = level * BR_RETEST_TOLERANCE_PCT
        if candle["close"] > level * (1 + BR_RETEST_TOLERANCE_PCT) or pending_s["candles_waited"] > BR_MAX_RETEST_CANDLES:
            BR_PENDING_SHORT.pop(market_code, None)
        else:
            touched = candle["high"] >= level - tol and candle["low"] <= level + tol
            if touched and _has_confirmed_selling_pressure(candle, previous):
                entry = float(candle["close"])
                atr = candle.get("atr", entry * 0.01)
                stop = pending_s["swing_high"] + 0.20 * float(atr)
                risk = stop - entry
                BR_PENDING_SHORT.pop(market_code, None)
                if risk > 0:
                    return (
                        f"🔻 <b>سیگنال شورت Break & Retest</b>\n"
                        f"▫️ ارز: <code>{market_code}</code>\n📌 SHORT\n"
                        f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {stop:,.4f}\n"
                        f"🎯 سود ۱: {entry - risk:,.4f}\n🎯 سود ۲: {entry - 2 * risk:,.4f}"
                    )

    pending_l = BR_PENDING_LONG.get(market_code)
    if pending_l:
        pending_l["candles_waited"] += 1
        pending_l["swing_low"] = min(pending_l["swing_low"], float(candle["low"]))
        level = pending_l["level"]
        tol = level * BR_RETEST_TOLERANCE_PCT
        if candle["close"] < level * (1 - BR_RETEST_TOLERANCE_PCT) or pending_l["candles_waited"] > BR_MAX_RETEST_CANDLES:
            BR_PENDING_LONG.pop(market_code, None)
        else:
            touched = candle["low"] <= level + tol and candle["high"] >= level - tol
            if touched and _has_confirmed_buying_pressure(candle, previous):
                entry = float(candle["close"])
                atr = candle.get("atr", entry * 0.01)
                stop = pending_l["swing_low"] - 0.20 * float(atr)
                risk = entry - stop
                BR_PENDING_LONG.pop(market_code, None)
                if risk > 0:
                    return (
                        f"📈 <b>سیگنال لانگ Break & Retest</b>\n"
                        f"▫️ ارز: <code>{market_code}</code>\n📌 LONG\n"
                        f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {stop:,.4f}\n"
                        f"🎯 سود ۱: {entry + risk:,.4f}\n🎯 سود ۲: {entry + 2 * risk:,.4f}"
                    )

    upper = candle.get("bb_upper", float("nan"))
    lower = candle.get("bb_lower", float("nan"))
    span = float(candle["high"] - candle["low"])
    body_ratio = abs(float(candle["close"] - candle["open"])) / span if span > 0 else 0.0

    if not pd.isna(lower) and candle["volume"] > BR_BREAKOUT_VOL_MULT * vol_avg and candle["close"] < lower and body_ratio >= BR_MIN_BREAKOUT_BODY_RATIO:
        BR_PENDING_SHORT[market_code] = {"level": float(lower), "candles_waited": 0, "swing_high": float("-inf")}
    elif not pd.isna(upper) and candle["volume"] > BR_BREAKOUT_VOL_MULT * vol_avg and candle["close"] > upper and body_ratio >= BR_MIN_BREAKOUT_BODY_RATIO:
        BR_PENDING_LONG[market_code] = {"level": float(upper), "candles_waited": 0, "swing_low": float("inf")}

    return None


def check_setup_strategy(df, market_code):
    if df is None or len(df) < 55:
        return None
    last = df.iloc[-1]
    last_time = int(last["timestamp"])

    if SETUP_LAST_PROCESSED.get(market_code) == last_time:
        return None
    SETUP_LAST_PROCESSED[market_code] = last_time

    pending = SETUP_PENDING.get(market_code)
    if pending is not None:
        age = (last_time - pending["created_at"]) // TIMEFRAME_SECONDS
        if age > SETUP_MAX_RETEST_CANDLES:
            SETUP_PENDING.pop(market_code, None)
        elif age >= 1:
            zone_low = pending["zone_low"]
            zone_high = pending["zone_high"]
            touched = last["low"] <= zone_high and last["high"] >= zone_low
            if pending["direction"] == "LONG":
                invalid = last["close"] <= pending["sweep_extreme"]
                bounced = touched and last["close"] > last["open"] and last["close"] > zone_high
            else:
                invalid = last["close"] >= pending["sweep_extreme"]
                bounced = touched and last["close"] < last["open"] and last["close"] < zone_high

            if invalid:
                SETUP_PENDING.pop(market_code, None)
            elif bounced:
                SETUP_PENDING.pop(market_code, None)
                entry = float(last["close"])
                atr = float(last["atr"])
                if pd.isna(atr) or atr <= 0:
                    atr = entry * 0.01

                if pending["direction"] == "LONG":
                    stop = pending["sweep_extreme"] - 0.2 * atr
                    risk = entry - stop
                    tp1 = entry + 1.5 * risk
                    tp2 = entry + 2.5 * risk
                    title = "📈 <b>سیگنال لانگ ستاپ (Sweep+FVG)</b>"
                else:
                    stop = pending["sweep_extreme"] + 0.2 * atr
                    risk = stop - entry
                    tp1 = entry - 1.5 * risk
                    tp2 = entry - 2.5 * risk
                    title = "📉 <b>سیگنال شورت ستاپ (Sweep+FVG)</b>"

                if risk > 0:
                    return (
                        f"{title}\n▫️ ارز: <code>{market_code}</code>\n📌 {pending['direction']}\n"
                        f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {stop:,.4f}\n"
                        f"🎯 سود ۱: {tp1:,.4f}\n🎯 سود ۲: {tp2:,.4f}"
                    )
                return None

    if market_code in SETUP_PENDING or len(df) < 14:
        return None

    sweep = df.iloc[-3]
    displacement = df.iloc[-2]
    confirmation = df.iloc[-1]
    prior = df.iloc[-13:-3]
    if len(prior) < 10:
        return None

    prior_low = prior["low"].min()
    prior_high = prior["high"].max()

    bullish_sweep = sweep["low"] < prior_low and sweep["close"] > prior_low
    bullish_fvg = confirmation["low"] > sweep["high"]
    bullish_displacement = displacement["close"] > displacement["open"] and displacement["close"] > sweep["high"]

    bearish_sweep = sweep["high"] > prior_high and sweep["close"] < prior_high
    bearish_fvg = confirmation["high"] < sweep["low"]
    bearish_displacement = displacement["close"] < displacement["open"] and displacement["close"] < sweep["low"]

    if bullish_sweep and bullish_fvg and bullish_displacement:
        SETUP_PENDING[market_code] = {
            "direction": "LONG",
            "zone_low": float(sweep["high"]),
            "zone_high": float(confirmation["low"]),
            "sweep_extreme": float(sweep["low"]),
            "created_at": last_time,
        }
    elif bearish_sweep and bearish_fvg and bearish_displacement:
        SETUP_PENDING[market_code] = {
            "direction": "SHORT",
            "zone_low": float(confirmation["high"]),
            "zone_high": float(sweep["low"]),
            "sweep_extreme": float(sweep["high"]),
            "created_at": last_time,
        }
    return None


# ================= مدیریت سیگنال‌ها =================
def load_tracker():
    global signal_tracker
    try:
        with tracker_lock:
            with open(TRACKER_FILE, "r", encoding="utf-8") as file:
                signal_tracker = json.load(file)
    except (OSError, ValueError):
        pass


def save_tracker():
    with tracker_lock:
        try:
            with open(TRACKER_FILE, "w", encoding="utf-8") as file:
                json.dump(signal_tracker, file, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"Could not save tracker: {exc}")


def add_signal(symbol, direction, entry, sl, tp1, strategy):
    sid = f"{symbol}_{strategy}_{uuid.uuid4().hex[:8]}"
    record = {
        "id": sid,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "strategy": strategy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
    }
    with tracker_lock:
        signal_tracker[sid] = record
    save_tracker()


def tracker_stats():
    with tracker_lock:
        signals = list(signal_tracker.values())
    total = len(signals)
    wins = sum(s.get("status") == "HIT_TP1" for s in signals)
    losses = sum(s.get("status") == "HIT_SL" for s in signals)
    open_signals = sum(s.get("status") == "OPEN" for s in signals)
    win_rate = wins / (wins + losses) * 100 if wins + losses else 0.0
    return total, wins, losses, open_signals, win_rate


def run_signal_tracker():
    while True:
        try:
            time.sleep(60)
            with tracker_lock:
                open_signals = {
                    k: v for k, v in signal_tracker.items()
                    if v.get("status") == "OPEN"
                }
            for sid, sig in open_signals.items():
                df = fetch_bitpin_candles(sig["symbol"], resolution=TIMEFRAME, count=2)
                if df is None or df.empty:
                    continue
                current_price = float(df.iloc[-1]["close"])
                if sig["direction"] == "LONG":
                    hit_tp = current_price >= sig["tp1"]
                    hit_sl = current_price <= sig["sl"]
                else:
                    hit_tp = current_price <= sig["tp1"]
                    hit_sl = current_price >= sig["sl"]

                if hit_tp or hit_sl:
                    status = "HIT_TP1" if hit_tp else "HIT_SL"
                    with tracker_lock:
                        if signal_tracker[sid].get("status") != "OPEN":
                            continue
                        signal_tracker[sid]["status"] = status
                    save_tracker()
                    emoji = "✅" if status == "HIT_TP1" else "❌"
                    send_telegram(
                        f"{emoji} <b>{status}</b>\n▫️ ارز: <code>{sig['symbol']}</code>\n"
                        f"📌 {sig['direction']}\n🎯 قیمت: {current_price:,.4f}"
                    )
        except Exception as exc:
            print(f"Tracker failed: {type(exc).__name__}")
            time.sleep(10)


def telegram_stats_command_handler():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            response = requests.get(url, params={"offset": offset, "timeout": 25}, timeout=35)
            data = response.json() if response.status_code == 200 else {}

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or {}
                text = (msg.get("text") or "").strip()
                chat_id = msg.get("chat", {}).get("id")

                if text.startswith("/stats") and chat_id:
                    total, wins, losses, opened, win_rate = tracker_stats()
                    report = (
                        "📊 <b>آمار سیگنال‌های ربات</b>\n"
                        f"▫️ کل سیگنال‌ها: {total}\n"
                        f"▫️ موفق (TP): {wins}\n"
                        f"▫️ ناموفق (SL): {losses}\n"
                        f"▫️ باز: {opened}\n"
                        f"▫️ وین‌ریت: {win_rate:.1f}%"
                    )
                    send_telegram(report)
        except Exception as exc:
            print(f"Telegram updates failed: {type(exc).__name__}")
            time.sleep(10)


# ================= حلقه اصلی اسکن بازار =================
def main_scanner_loop():
    send_telegram(f"🤖 <b>ربات معامله‌گری بیت‌پین استارت شد.</b>\nتایم‌فریم: ۱۵ دقیقه | تعداد نمادها: {len(MARGIN_SYMBOLS)}")
    load_tracker()

    while True:
        try:
            scanned_count = 0
            btc_df = fetch_bitpin_candles("BTC_USDT", resolution=TIMEFRAME, count=50)
            btc_df = closed_candles(btc_df, resolution=TIMEFRAME)
            btc_df = calculate_indicators(btc_df)
            btc_ok = check_bitcoin_filter(btc_df)

            for symbol in MARGIN_SYMBOLS:
                df = fetch_bitpin_candles(symbol, resolution=TIMEFRAME, count=100)
                if df is None or len(df) < 55:
                    time.sleep(0.5)
                    continue

                # بررسی روی کندل‌های بسته‌شده
                df_closed = closed_candles(df, resolution=TIMEFRAME)
                df_ind = calculate_indicators(df_closed)
                if df_ind is None or len(df_ind) < 40:
                    time.sleep(0.5)
                    continue

                scanned_count += 1

                # اجرای استراتژی‌ها
                strategies = [
                    ("RSI_DIV", lambda d: check_rsi_divergence(d, symbol)),
                    ("SENSI", lambda d: check_sensi_strategy(df_closed, symbol)),
                    ("BOLLINGER", lambda d: check_trend_strategy(d, symbol)),
                    ("PULLBACK", lambda d: check_pullback_strategy(d, symbol)),
                    ("BREAK_RETEST", lambda d: check_break_retest(d, symbol)),
                    ("SETUP_SWEEP_FVG", lambda d: check_setup_strategy(d, symbol)),
                ]

                for strat_name, strat_func in strategies:
                    try:
                        signal_msg = strat_func(df_ind)
                        if signal_msg:
                            # استخراج اطلاعات برای تکرار نشدن یا ثبت در تراکر
                            direction = "LONG" if "LONG" in signal_msg or "لانگ" in signal_msg else "SHORT"
                            last_c = float(df_ind.iloc[-1]["close"])
                            atr_val = float(df_ind.iloc[-1]["atr"]) if not pd.isna(df_ind.iloc[-1]["atr"]) else last_c * 0.01
                            
                            sl_val = last_c - (1.5 * atr_val) if direction == "LONG" else last_c + (1.5 * atr_val)
                            tp1_val = last_c + (2.0 * atr_val) if direction == "LONG" else last_c - (2.0 * atr_val)

                            send_telegram(signal_msg)
                            add_signal(symbol, direction, last_c, sl_val, tp1_val, strat_name)
                            time.sleep(1)
                    except Exception as e:
                        print(f"Error in {strat_name} for {symbol}: {e}")

                time.sleep(1)

            if scanned_count > 0:
                notify_first_successful_scan(scanned_count)

            time.sleep(CHECK_INTERVAL)
        except Exception as exc:
            print(f"Main loop error: {exc}")
            time.sleep(15)


# ================= نقطه شروع برنامه =================
if __name__ == "__main__":
    print("Starting HTTP Server thread...")
    threading.Thread(target=run_http_server, daemon=True).start()
    
    print("Starting Self-Ping thread...")
    threading.Thread(target=self_ping, daemon=True).start()
    
    print("Starting Signal Tracker thread...")
    threading.Thread(target=run_signal_tracker, daemon=True).start()
    
    print("Starting Telegram Updates thread...")
    threading.Thread(target=telegram_stats_command_handler, daemon=True).start()

    print("Starting Main Scanner Loop...")
    main_scanner_loop()


                # بررسی روی کندل‌های بسته‌شده
                df_closed = closed_candles(df, resolution=TIMEFRAME)
                df_ind = calculate_indicators(df_closed)
                if df_ind is None or len(df_ind) < 40:
                    time.sleep(0.5)
                    continue

                scanned_count += 1

                # اجرای استراتژی‌ها
                strategies = [
                    ("RSI_DIV", lambda d: check_rsi_divergence(d, symbol)),
                    ("SENSI", lambda d: check_sensi_strategy(df_closed, symbol)),
                    ("BOLLINGER", lambda d: check_trend_strategy(d, symbol)),
                    ("PULLBACK", lambda d: check_pullback_strategy(d, symbol)),
                    ("BREAK_RETEST", lambda d: check_break_retest(d, symbol)),
                    ("SETUP_SWEEP_FVG", lambda d: check_setup_strategy(d, symbol)),
                ]

                for strat_name, strat_func in strategies:
                    try:
                        signal_msg = strat_func(df_ind)
                        if signal_msg:
                            # استخراج اطلاعات برای تکرار نشدن یا ثبت در تراکر
                            direction = "LONG" if "LONG" in signal_msg or "لانگ" in signal_msg else "SHORT"
                            last_c = float(df_ind.iloc[-1]["close"])
                            atr_val = float(df_ind.iloc[-1]["atr"]) if not pd.isna(df_ind.iloc[-1]["atr"]) else last_c * 0.01
                            
                            sl_val = last_c - (1.5 * atr_val) if direction == "LONG" else last_c + (1.5 * atr_val)
                            tp1_val = last_c + (2.0 * atr_val) if direction == "LONG" else last_c - (2.0 * atr_val)

                            send_telegram(signal_msg)
                            add_signal(symbol, direction, last_c, sl_val, tp1_val, strat_name)
                            time.sleep(1)
                    except Exception as e:
                        print(f"Error in {strat_name} for {symbol}: {e}")

                time.sleep(1)

            if scanned_count > 0:
                notify_first_successful_scan(scanned_count)

            time.sleep(CHECK_INTERVAL)
        except Exception as exc:
            print(f"Main loop error: {exc}")
            time.sleep(15)


# ================= نقطه شروع برنامه =================
if __name__ == "__main__":
    print("Starting HTTP Server thread...")
    threading.Thread(target=run_http_server, daemon=True).start()
    
    print("Starting Self-Ping thread...")
    threading.Thread(target=self_ping, daemon=True).start()
    
    print("Starting Signal Tracker thread...")
    threading.Thread(target=run_signal_tracker, daemon=True).start()
    
    print("Starting Telegram Updates thread...")
    threading.Thread(target=telegram_stats_command_handler, daemon=True).start()

    print("Starting Main Scanner Loop...")
    main_scanner_loop()


                # بررسی روی کندل‌های بسته‌شده
                df_closed = closed_candles(df, resolution=TIMEFRAME)
                df_ind = calculate_indicators(df_closed)
                if df_ind is None or len(df_ind) < 40:
                    time.sleep(0.5)
                    continue

                scanned_count += 1

                # اجرای استراتژی‌ها
                strategies = [
                    ("RSI_DIV", lambda d: check_rsi_divergence(d, symbol)),
                    ("SENSI", lambda d: check_sensi_strategy(df_closed, symbol)),
                    ("BOLLINGER", lambda d: check_trend_strategy(d, symbol)),
                    ("PULLBACK", lambda d: check_pullback_strategy(d, symbol)),
                    ("BREAK_RETEST", lambda d: check_break_retest(d, symbol)),
                    ("SETUP_SWEEP_FVG", lambda d: check_setup_strategy(d, symbol)),
                ]

                for strat_name, strat_func in strategies:
                    try:
                        signal_msg = strat_func(df_ind)
                        if signal_msg:
                            # استخراج اطلاعات برای تکرار نشدن یا ثبت در تراکر
                            direction = "LONG" if "LONG" in signal_msg or "لانگ" in signal_msg else "SHORT"
                            last_c = float(df_ind.iloc[-1]["close"])
                            atr_val = float(df_ind.iloc[-1]["atr"]) if not pd.isna(df_ind.iloc[-1]["atr"]) else last_c * 0.01
                            
                            sl_val = last_c - (1.5 * atr_val) if direction == "LONG" else last_c + (1.5 * atr_val)
                            tp1_val = last_c + (2.0 * atr_val) if direction == "LONG" else last_c - (2.0 * atr_val)

                            send_telegram(signal_msg)
                            add_signal(symbol, direction, last_c, sl_val, tp1_val, strat_name)
                            time.sleep(1)
                    except Exception as e:
                        print(f"Error in {strat_name} for {symbol}: {e}")

                time.sleep(1)

            if scanned_count > 0:
                notify_first_successful_scan(scanned_count)

            time.sleep(CHECK_INTERVAL)
        except Exception as exc:
            print(f"Main loop error: {exc}")
            time.sleep(15)
