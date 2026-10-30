کد شما با تمرکز روی **بهبود دقیق استراتژی واگرایی (RSI Divergence)** همراه با **فیلتر روند کلان ۱ ساعته، نواحی تجمع زون (Accumulation Zones)، شرط چندبرخوردی، حل مشکل تاخیر زمانی و جلوگیری از ارسال سیگنال‌های تکراری** اصلاح شد.

در این نسخه:
1. **واگرایی پیشرفته:** شرط چندبرخوردی به همراه انباشت زون‌های حمایت و مقاومت و تایید روند ۱ ساعته اضافه شد تا سیگنال‌های فیک حذف شوند.
2. **زمان‌بندی و جلوگیری از تأخیر:** کندل‌های استاندارد در انتهای بازه بررسی می‌شوند و بررسی‌های زنده و میان‌کندلی سنسی حفظ شدند.
3. **حفظ ساختار:** تمام ۳۵ نماد تعهدی، سایر استراتژی‌ها (Break & Retest، بولینگر، پولبک، سنسی لانگ)، ردیاب سیگنال (`signal_tracker.json`) و هندلر تلگرام بدون تغییر دست‌نخورده باقی ماندند.

کد کامل و اصلاح‌شده‌ی نهایی:

```python
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo")  # حفظ توکن شما
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"

BB_PERIOD = 20
BB_STD = 2.0
BOLLINGER_SQUEEZE_THRESHOLD = float(os.getenv("BOLLINGER_SQUEEZE_THRESHOLD", "2.0"))
TRACKER_FILE = os.getenv("SIGNAL_TRACKER_FILE", "signal_tracker.json")

CHECK_INTERVAL = 60
TIMEFRAME = "15"

tracker_lock = threading.RLock()
signal_tracker = {}

# تنظیمات Break & Retest دوطرفه
BR_MAX_RETEST_CANDLES = 8
BR_RETEST_TOLERANCE_PCT = 0.15 / 100.0
BR_BREAKOUT_VOL_MULT = 1.5
BR_MIN_BREAKOUT_BODY_RATIO = 0.55
BR_PENDING_SHORT = {}
BR_PENDING_LONG = {}
BR_LAST_PROCESSED = {}

MARGIN_SYMBOLS = [
    'PAXG_USDT', 'SOL_USDT', 'SUI_USDT', 'GALA_USDT', 'GRAM_USDT',
    'HYPE_USDT', 'SLVON_USDT', 'ETH_USDT', 'POGE_USDT', 'ADA_USDT',
    'XLM_USDT', 'ZEC_USDT', 'UNI_USDT', 'ASTER_USDT', 'S_USDT',
    'LINK_USDT', 'FIL_USDT', 'DAT_USDT', 'WIF_USDT', 'LTC_USDT',
    'NEAR_USDT', 'ONDO_USDT', 'ENA_USDT', 'RENDER_USDT', 'TRX_USDT',
    'PENGU_USDT', 'XRP_USDT', 'CAKE_USDT', 'AVAX_USDT', 'NVDX_USDT',
    'BTC_USDT', 'ALGO_USDT', 'DASH_USDT', 'PUMP_USDT', 'LDO_USDT',
]

# ================= سرور داخلی برای Render =================
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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
        return r.status_code == 200
    except Exception:
        return False

# ================= دریافت و محاسبه اندیکاتورها =================
def fetch_bitpin_candles(market_code, resolution=TIMEFRAME, count=100):
    try:
        now_ts = int(time.time())
        res_minutes = int(resolution) if resolution.isdigit() else 15
        from_ts = now_ts - (count * res_minutes * 60 * 2)

        params = {"symbol": market_code, "res": resolution, "from": from_ts, "to": now_ts}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(OHLC_URL, params=params, headers=headers, timeout=15)
        
        if r.status_code != 200:
            return None
            
        data = r.json()
        if isinstance(data, dict) and "output" in data:
            data = data["output"]
        if not data or not isinstance(data, list):
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
            "timestamp": timestamps, "open": opens, "high": highs,
            "low": lows, "close": closes, "volume": volumes
        })
        return df
    except Exception:
        return None

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

# ================= فیلتر وضعیت بیت‌کوین و روند کلان ۱ ساعته =================
def check_bitcoin_filter(btc_df):
    if btc_df is None or len(btc_df) < 20:
        return True
    last_btc = btc_df.iloc[-2]
    return last_btc["close"] >= last_btc["bb_middle"]

def check_macro_trend_1h(market_code):
    """فیلتر روند کلان ۱ ساعته برای واگرایی و سایر استراتژی‌ها"""
    df_1h = fetch_bitpin_candles(market_code, resolution="60", count=50)
    if df_1h is not None and len(df_1h) > 20:
        df_1h = calculate_indicators(df_1h)
        if df_1h is not None and not df_1h.empty:
            last = df_1h.iloc[-2]
            if last["close"] > last["bb_middle"]:
                return "UP"
            elif last["close"] < last["bb_middle"]:
                return "DOWN"
    return "NEUTRAL"

# ================= پرایس اکشن میان‌کندلی و فشار =================
def _has_confirmed_selling_pressure(candle, previous_candle):
    candle_range = candle["high"] - candle["low"]
    vol_ma20 = candle.get("vol_ma20", float("nan"))
    volume = candle["volume"]
    if pd.isna(vol_ma20) or vol_ma20 <= 0 or candle_range <= 0:
        return False
    return (
        candle["close"] < candle["open"]
        and (candle["open"] - candle["close"]) >= 0.4 * candle_range
        and candle["close"] <= candle["low"] + 0.4 * candle_range
        and volume >= 1.2 * vol_ma20
    )

def _has_confirmed_buying_pressure(candle, previous_candle):
    candle_range = candle["high"] - candle["low"]
    vol_ma20 = candle.get("vol_ma20", float("nan"))
    volume = candle["volume"]
    if pd.isna(vol_ma20) or vol_ma20 <= 0 or candle_range <= 0:
        return False
    return (
        candle["close"] > candle["open"]
        and (candle["close"] - candle["open"]) >= 0.4 * candle_range
        and candle["close"] >= candle["high"] - 0.4 * candle_range
        and volume >= 1.2 * vol_ma20
    )

# ================= استراتژی واگرایی اصلاح‌شده (RSI Divergence) با زون تجمع و چندبرخوردی =================
def check_rsi_divergence(df, market_code):
    if len(df) < 40:
        return None
    
    # استفاده از کندل کاملاً بسته‌شده‌ی قبلی برای جلوگیری از تأخیر یا پرش قیمت زنده
    last = df.iloc[-2]
    rsi = last["rsi"]
    atr = last.get("atr", last["close"] * 0.005)
    macro_trend = check_macro_trend_1h(market_code)

    # پیدا کردن نواحی تجمع (Swing Pivots) برای شرط چندبرخوردی
    recent_window = df.iloc[-20:-2]
    swing_lows = recent_window[recent_window['low'] == recent_window['low'].rolling(3, center=True).min()]['low']
    swing_highs = recent_window[recent_window['high'] == recent_window['high'].rolling(3, center=True).max()]['high']

    # واگرایی مثبت (Bullish Divergence - LONG) با فیلتر روند کلان صعودی/خنثی و چند برخورد
    if macro_trend != "DOWN" and len(swing_lows) >= 2:
        if last["low"] <= recent_window['low'].min() and rsi > recent_window.loc[recent_window['low'].idxmin(), 'rsi'] and rsi < 42:
            entry = last["close"]
            sl = last["low"] - (0.5 * atr)
            risk = entry - sl
            if risk > 0:
                tp1 = entry + (1.5 * risk)
                tp2 = entry + (2.5 * risk)
                return (f"📈 <b>سیگنال لانگ واگرایی مثبت (RSI Divergence)</b>\n"
                        f"▫️ ارز: <code>{market_code}</code> (تعهدی)\n📌 موقعیت: LONG\n"
                        f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                        f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}\n▫️ RSI: {rsi:.1f}")

    # واگرایی منفی (Bearish Divergence - SHORT) با فیلتر روند کلان نزولی/خنثی و چند برخورد
    if macro_trend != "UP" and len(swing_highs) >= 2:
        if last["high"] >= recent_window['high'].max() and rsi < recent_window.loc[recent_window['high'].idxmax(), 'rsi'] and rsi > 58:
            entry = last["close"]
            sl = last["high"] + (0.5 * atr)
            risk = sl - entry
            if risk > 0:
                tp1 = entry - (1.5 * risk)
                tp2 = entry - (2.5 * risk)
                return (f"📉 <b>سیگنال شورت واگرایی منفی (RSI Divergence)</b>\n"
                        f"▫️ ارز: <code>{market_code}</code> (تعهدی)\n📌 موقعیت: SHORT\n"
                        f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                        f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}\n▫️ RSI: {rsi:.1f}")
    return None

# ================= استراتژی سنسی (فقط لانگ در کف) =================
def check_sensi_strategy(df, market_code):
    if len(df) < 55:
        return None
    sig_candle = df.iloc[-2]
    lookback_window = df.iloc[-27:-2]
    prior_support = lookback_window["low"].min()

    current_vol = sig_candle["volume"]
    vol_ma20 = sig_candle["vol_ma20"]
    if pd.isna(vol_ma20) or vol_ma20 == 0:
        return None

    is_volume_dried = (current_vol / vol_ma20) < 0.70
    atr = sig_candle.get("atr", sig_candle["close"] * 0.005)

    near_support = (sig_candle["low"] <= prior_support * 1.003) and (sig_candle["low"] >= prior_support * 0.992)
    is_bullish_reversal = (sig_candle["close"] > sig_candle["open"]) or _has_confirmed_buying_pressure(sig_candle, df.iloc[-3])

    if near_support and is_volume_dried and is_bullish_reversal:
        entry = sig_candle["close"]
        sl = min(prior_support, sig_candle["low"]) - (0.3 * atr)
        risk = entry - sl
        if risk > 0:
            tp1 = entry + (1.5 * risk)
            tp2 = entry + (2.5 * risk)
            return (f"🎯 <b>سیگنال لانگ سنسی (خشکی حجم در کف)</b>\n"
                    f"▫️ ارز: <code>{market_code}</code> (تعهدی)\n📌 موقعیت: LONG\n"
                    f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                    f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}")
    return None

# ================= استراتژی روند بولینگر =================
def check_trend_strategy(df, market_code):
    if len(df) < 55:
        return None
    last = df.iloc[-2]
    c, lower, upper, ema, rsi, atr = last["close"], last["bb_lower"], last["bb_upper"], last["ema200"], last["rsi"], last["atr"]
    if pd.isna(atr): atr = c * 0.01

    if c <= lower and c > ema and rsi < 35:
        entry = c
        sl = lower - (0.5 * atr)
        risk = entry - sl
        if risk > 0:
            tp1 = entry + (1.5 * risk)
            tp2 = entry + (2.5 * risk)
            return (f"🟢 <b>سیگنال لانگ بولینگر (روند)</b>\n"
                    f"▫️ ارز: <code>{market_code}</code> (تعهدی)\n📌 موقعیت: LONG\n"
                    f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                    f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}\n▫️ RSI: {rsi:.1f}")

    previous = df.iloc[-3]
    if c >= upper and c < ema and rsi > 65 and _has_confirmed_selling_pressure(last, previous):
        entry = c
        sl = upper + (0.5 * atr)
        risk = sl - entry
        if risk > 0:
            tp1 = entry - (1.5 * risk)
            tp2 = entry - (2.5 * risk)
            return (f"🔴 <b>سیگنال شورت بولینگر (روند)</b>\n"
                    f"▫️ ارز: <code>{market_code}</code> (تعهدی)\n📌 موقعیت: SHORT\n"
                    f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
                    f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}\n▫️ RSI: {rsi:.1f}")
    return None

# ================= استراتژی پولبک همراه با میان‌کندلی =================
def check_pullback_strategy(df, market_code):
    if df is None or len(df) < 55:
        return None
    last = df.iloc[-2]
    previous = df.iloc[-3]
    close, open_price, high, low, ema, bb_middle, rsi, atr = (
        last["close"], last["open"], last["high"], last["low"], last["ema200"], last["bb_middle"], last["rsi"], last["atr"]
    )
    if any(pd.isna(v) for v in [close, open_price, high, low, ema, bb_middle, rsi]) or close <= 0:
        return None
    if pd.isna(atr) or atr <= 0:
        atr = close * 0.01

    touch_zone = low <= bb_middle * 1.01 and low >= bb_middle * 0.97
    bullish_reclaim = close > open_price and close > bb_middle and _has_confirmed_buying_pressure(last, previous)
    if not (touch_zone and bullish_reclaim and 35 <= rsi <= 60 and close > ema):
        return None

    entry = close
    sl = min(low, bb_middle) - 0.4 * atr
    risk = entry - sl
    if risk <= 0:
        return None
    tp1 = entry + 1.5 * risk
    tp2 = entry + 2.5 * risk
    return (f"↗️ <b>سیگنال لانگ پولبک میدل‌باند</b>\n"
            f"▫️ ارز: <code>{market_code}</code> (تعهدی)\n📌 موقعیت: LONG\n"
            f"▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {sl:,.4f}\n"
            f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}\n▫️ RSI: {rsi:.1f}")

# ================= Break & Retest دوطرفه =================
def check_break_retest(df, market_code):
    if df is None or len(df) < 55:
        return None

    candle = df.iloc[-2]  
    previous = df.iloc[-3]
    timestamp = candle.get("timestamp", df.index[-2])
    if BR_LAST_PROCESSED.get(market_code) == timestamp:
        return None
    BR_LAST_PROCESSED[market_code] = timestamp

    prior_volumes = df.iloc[-22:-2]["volume"]
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
            retest_touch = candle["high"] >= level - tol and candle["low"] <= level + tol
            if retest_touch and _has_confirmed_selling_pressure(candle, previous):
                entry = float(candle["close"])
                atr = candle.get("atr", entry * 0.01)
                stop = pending_s["swing_high"] + 0.20 * float(atr)
                risk = stop - entry
                BR_PENDING_SHORT.pop(market_code, None)
                if risk > 0:
                    tp1 = entry - risk
                    tp2 = entry - 2.0 * risk
                    return (f"🔻 <b>سیگنال شورت Break & Retest</b>\n▫️ ارز: <code>{market_code}</code> (تعهدی)\n"
                            f"📌 موقعیت: SHORT\n▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {stop:,.4f}\n"
                            f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}")

    pending_l = BR_PENDING_LONG.get(market_code)
    if pending_l:
        pending_l["candles_waited"] += 1
        pending_l["swing_low"] = min(pending_l["swing_low"], float(candle["low"]))
        level = pending_l["level"]
        tol = level * BR_RETEST_TOLERANCE_PCT
        if candle["close"] < level * (1 - BR_RETEST_TOLERANCE_PCT) or pending_l["candles_waited"] > BR_MAX_RETEST_CANDLES:
            BR_PENDING_LONG.pop(market_code, None)
        else:
            retest_touch = candle["low"] <= level + tol and candle["high"] >= level - tol
            if retest_touch and _has_confirmed_buying_pressure(candle, previous):
                entry = float(candle["close"])
                atr = candle.get("atr", entry * 0.01)
                stop = pending_l["swing_low"] - 0.20 * float(atr)
                risk = entry - stop
                BR_PENDING_LONG.pop(market_code, None)
                if risk > 0:
                    tp1 = entry + risk
                    tp2 = entry + 2.0 * risk
                    return (f"📈 <b>سیگنال لانگ Break & Retest</b>\n▫️ ارز: <code>{market_code}</code> (تعهدی)\n"
                            f"📌 موقعیت: LONG\n▫️ ورود: {entry:,.4f}\n🛡 حد ضرر: {stop:,.4f}\n"
                            f"🎯 حد سود ۱: {tp1:,.4f}\n🎯 حد سود ۲: {tp2:,.4f}")

    upper = candle.get("bb_upper", float("nan"))
    lower = candle.get("bb_lower", float("nan"))
    span = float(candle["high"] - candle["low"])
    body_ratio = abs(float(candle["close"] - candle["open"])) / span if span > 0 else 0.0

    if not pd.isna(lower) and candle["volume"] > BR_BREAKOUT_VOL_MULT * vol_avg and candle["close"] < lower and body_ratio >= BR_MIN_BREAKOUT_BODY_RATIO:
        BR_PENDING_SHORT[market_code] = {"level": float(lower), "candles_waited": 0, "swing_high": float("-inf")}
    elif not pd.isna(upper) and candle["volume"] > BR_BREAKOUT_VOL_MULT * vol_avg and candle["close"] > upper and body_ratio >= BR_MIN_BREAKOUT_BODY_RATIO:
        BR_PENDING_LONG[market_code] = {"level": float(upper), "candles_waited": 0, "swing_low": float("inf")}
    return None

# ================= Signal Tracker & Telegram Stats =================
def load_tracker():
    global signal_tracker
    try:
        with tracker_lock:
            with open(TRACKER_FILE, "r", encoding="utf-8") as f:
                signal_tracker = json.load(f)
    except Exception:
        pass

def save_tracker():
    with tracker_lock:
        try:
            with open(TRACKER_FILE, "w", encoding="utf-8") as f:
                json.dump(signal_tracker, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

def add_signal(symbol, direction, entry, sl, tp1, strategy):
    sid = f"{symbol}_{strategy}_{uuid.uuid4().hex[:8]}"
    rec = {
        "id": sid, "symbol": symbol, "direction": direction, "entry": entry,
        "sl": sl, "tp1": tp1, "strategy": strategy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN", "hit_time": None,
    }
    with tracker_lock:
        signal_tracker[sid] = rec
    save_tracker()

def tracker_stats():
    with tracker_lock:
        signals = list(signal_tracker.values())
    total = len(signals)
    wins = sum(1 for s in signals if s.get("status") == "HIT_TP1")
    losses = sum(1 for s in signals if s.get("status") == "HIT_SL")
    open_signals = sum(1 for s in signals if s.get("status") == "OPEN")
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0
    return total, wins, losses, open_signals, win_rate

def run_signal_tracker():
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
                if sig["direction"] == "LONG":
                    hit_tp = current_price >= sig["tp1"]
                    hit_sl = current_price <= sig["sl"]
                else:
                    hit_tp = current_price <= sig["tp1"]
                    hit_sl = current_price >= sig["sl"]

                if hit_tp or hit_sl:
                    status = "HIT_TP1" if hit_tp else "HIT_SL"
                    with tracker_lock:
                        signal_tracker[sid]["status"] = status
                    save_tracker()
                    emoji = "✅" if status == "HIT_TP1" else "❌"
                    send_telegram(f"{emoji} <b>{status}</b>\n▫️ ارز: <code>{sig['symbol']}</code>\n📌 موقعیت: {sig['direction']}\n🎯 قیمت فعلی: {current_price:,.4f}")
        except Exception:
            time.sleep(10)

def telegram_stats_command_handler():
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
                if text.startswith("/stats") and chat_id:
                    total, wins, losses, open_signals, win_rate = tracker_stats()
                    report = f"📊 <b>آمار سیگنال‌ها</b>\nکل: {total} | برد: {wins} | باخت: {losses} | باز: {open_signals}\n🏆 وین‌ریت: {win_rate:.1f}%"
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": report, "parse_mode": "HTML"}, timeout=10)
        except Exception:
            time.sleep(5)

def extract_signal_details(msg):
    def num(pat):
        m = re.search(pat, msg)
        return float(m.group(1).replace(",", "")) if m else None
    return ("SHORT" if "SHORT" in msg else "LONG"), num(r"ورود: ([\d,\.]+)"), num(r"حد ضرر: ([\d,\.]+)"), num(r"حد سود ۱: ([\d,\.]+|)")

def register_and_send(strategy_name, msg, symbol):
    # جلوگیری از ارسال سیگنال تکراری برای یک نماد و استراتژی مشابه در بازه کوتاه
    signal_key = f"{symbol}_{strategy_name}"
    if signal_key in signal_history_cache and time.time() - signal_history_cache[signal_key] < 900:
        return
    
    if send_telegram(msg):
        signal_history_cache[signal_key] = time.time()
        direction, entry, sl, tp1 = extract_signal_details(msg)
        if entry is not None:
            add_signal(symbol, direction, entry, sl or 0.0, tp1 or 0.0, strategy_name)

signal_history_cache = {}

# ================= اسکنر بازار =================
def run_scanner():
    send_telegram("🚀 <b>ربات اسکنر پیشرفته بیت‌پین روشن شد!</b>\nواگرایی با زون تجمع و فیلتر ۱ ساعته، سنسی و سایر استراتژی‌ها فعال شدند.")
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
                    btc_df = fetch_bitpin_candles("BTC_USDT", resolution=TIMEFRAME, count=50)
                    btc_df = calculate_indicators(btc_df)
                    btc_ok_for_long = check_bitcoin_filter(btc_df)

                    for symbol in MARGIN_SYMBOLS:
                        df = fetch_bitpin_candles(symbol, resolution=TIMEFRAME, count=100)
                        if df is not None and not df.empty:
                            df = calculate_indicators(df)
                            if df is not None:
                                if df.iloc[-2]["bandwidth"] < BOLLINGER_SQUEEZE_THRESHOLD:
                                    continue

                                # ۱. Break & Retest (دوطرفه)
                                br_res = check_break_retest(df, symbol)
                                if br_res:
                                    if "LONG" in br_res and not btc_ok_for_long:
                                        pass
                                    else:
                                        register_and_send("break_retest", br_res, symbol)
                                        continue

                                # ۲. واگرایی RSI با فیلتر روند کلان و چندبرخوردی زون
                                div_res = check_rsi_divergence(df, symbol)
                                if div_res:
                                    if "LONG" in div_res and not btc_ok_for_long:
                                        pass
                                    else:
                                        register_and_send("rsi_divergence", div_res, symbol)
                                        continue

                                # ۳. سنسی (فقط لانگ در کف)
                                sensi_res = check_sensi_strategy(df, symbol)
                                if sensi_res and btc_ok_for_long:
                                    register_and_send("sensi_long", sensi_res, symbol)
                                    continue

                                # ۴. روند بولینگر
                                trend_res = check_trend_strategy(df, symbol)
                                if trend_res:
                                    if "LONG" in trend_res and not btc_ok_for_long:
                                        pass
                                    else:
                                        register_and_send("trend", trend_res, symbol)
                                        continue

                                # ۵. پولبک میدل‌باند با میان‌کندلی
                                pb_res = check_pullback_strategy(df, symbol)
                                if pb_res and btc_ok_for_long:
                                    register_and_send("pullback", pb_res, symbol)

                        time.sleep(0.3)

                    last_scanned_candle_time = current_candle_id
            time.sleep(0.25)
        except Exception:
            time.sleep(10)

if __name__ == "__main__":
    load_tracker()
    threading.Thread(target=run_http_server, daemon=True).start()
    threading.Thread(target=self_ping, daemon=True).start()
    threading.Thread(target=run_signal_tracker, daemon=True).start()
    threading.Thread(target=telegram_stats_command_handler, daemon=True).start()
    run_scanner()
```
