import os
import time
import requests
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo"  # توکن تلگرام
TELEGRAM_CHAT_ID = "6643451227"    # چت‌آیدی تلگرام
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

API_URL = "https://api.bitpin.org/api/v1/mkt/candles/"
RESOLUTION = "15"           # تایم‌فریم ۱۵ دقیقه
PERIOD = 20                 # دوره بولینگر
SL_PERCENT = 0.012          # حد ضرر: 1.2 درصد
TP1_PERCENT = 0.015         # حد سود اول: 1.5 درصد
TP2_PERCENT = 0.030         # حد سود دوم: 3 درصد
MIN_BANDWIDTH = 0.008       # حداقل پهنای باند برای فیلتر رنج
VOLUME_MULTIPLIER = 1.35    # ضریب حجم بریک‌آوت استاندارد
CHECK_INTERVAL = 30         # بررسی هر 30 ثانیه

# تاخیر ایمن‌تر برای جلوگیری از بلاک شدن توسط بیت‌پین
SYMBOL_SLEEP = 0.65         # مکث بین هر نماد (افزایش‌یافته برای امنیت بیشتر)
REQUEST_TIMEOUT = 12        
MAX_RETRIES = 3             

last_signals = {}
tp1_notified = {}
sl_notified = {}
last_processed_candle_time = {}

trend_cache = {}  # کش روند ۱ ساعته

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}
session = requests.Session()
session.headers.update(HEADERS)

# ================= توابع وب‌سرور و اعلان =================

def format_number(val):
    if val is None:
        return "0"
    if val < 0.0001:
        return f"{val:.8f}".rstrip('0').rstrip('.')
    elif val < 1:
        return f"{val:.4f}".rstrip('0').rstrip('.')
    else:
        return f"{val:,.2f}"

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
        res = session.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}", flush=True)
        return False

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is Active & Running!")
    def log_message(self, format, *args):
        return

def run_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Web server started on 0.0.0.0:{port}", flush=True)
    server.serve_forever()

def keep_alive_ping():
    time.sleep(30)
    while True:
        try:
            if APP_URL:
                session.get(APP_URL, timeout=10)
        except Exception:
            pass
        time.sleep(480)

# ================= درخواست امن و ضد کرش =================

def safe_get_json(url, label=""):
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                text_content = resp.text.strip()
                if not text_content:
                    return None
                # بررسی اینکه آیا پاسخ واقعاً JSON است یا صفحه خطا (HTML)
                if text_content.startswith("<"):
                    print(f"[هشدار] دریافت صفحه HTML به جای JSON برای {label} (احتمال لیمیت سرعت)", flush=True)
                    time.sleep(2.0 * (attempt + 1))
                    continue
                return resp.json()
            elif resp.status_code in (429, 502, 503, 504):
                wait = 2.0 * (attempt + 1)
                print(f"[محدودیت بیت‌پین] کد {resp.status_code} برای {label}. انتظار {wait} ثانیه...", flush=True)
                time.sleep(wait)
            else:
                time.sleep(1.0)
        except Exception as e:
            time.sleep(1.5)
    return None

# ================= تحلیل تکنیکال و فیلترها =================

def get_market_trend(symbol):
    now = time.time()
    if symbol in trend_cache:
        cached_trend, cached_time = trend_cache[symbol]
        if now - cached_time < 300:
            return cached_trend

    url = f"{API_URL}?symbol={symbol}&resolution=60&to={int(now)}&count=40"
    data = safe_get_json(url, label=f"trend {symbol}")
    if not data or 'result' not in data or len(data['result']) == 0:
        return trend_cache.get(symbol, ("NEUTRAL", 0))[0]

    try:
        df_1h = pd.DataFrame(data['result'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        for col in ['open', 'high', 'low', 'close']:
            df_1h[col] = df_1h[col].astype(float)
        closes = df_1h['close']
        ema20 = closes.ewm(span=20, adjust=False).mean().iloc[-1]
        current_p = closes.iloc[-1]
        trend = "BULLISH" if current_p >= ema20 else "BEARISH"
        trend_cache[symbol] = (trend, now)
        return trend
    except Exception:
        return trend_cache.get(symbol, ("NEUTRAL", 0))[0]

def fetch_candles(symbol, resolution="15", count=150):
    url = f"{API_URL}?symbol={symbol}&resolution={resolution}&to={int(time.time())}&count={count}"
    data = safe_get_json(url, label=f"candles {symbol}")
    if not data or 'result' not in data or len(data['result']) == 0:
        return None

    try:
        df = pd.DataFrame(data['result'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

def manage_open_positions(symbol, market_type, current_price):
    for base_key in [f"{symbol}_{market_type}_LONG", f"{symbol}_{market_type}_SHORT"]:
        saved = last_signals.get(base_key)
        if not saved:
            continue
        
        side = saved["side"]
        entry_p = saved.get("entry", current_price)
        sl_val = saved.get("sl")
        tp1 = saved["tp1"]

        if not sl_notified.get(base_key, False) and sl_val:
            if (side == "LONG" and current_price <= sl_val) or (side == "SHORT" and current_price >= sl_val):
                pnl = ((current_price - entry_p) / entry_p) * 100 if side == "LONG" else ((entry_p - current_price) / entry_p) * 100
                msg = (
                    f"🛑 <b>هشدار حد ضرر (Stop Loss) - #{symbol}</b>\n"
                    f"📌 بازار: {market_type} ({side})\n"
                    f"💵 قیمت خروج: <code>{format_number(current_price)}</code>\n"
                    f"📉 میزان زیان: <code>{pnl:.2f}% ❌</code>"
                )
                send_telegram_message(msg)
                sl_notified[base_key] = True
                last_signals.pop(base_key, None)
                continue

        if not tp1_notified.get(base_key, False):
            if (side == "LONG" and current_price >= tp1 * 0.998) or (side == "SHORT" and current_price <= tp1 * 1.002):
                pnl = ((current_price - entry_p) / entry_p) * 100 if side == "LONG" else ((entry_p - current_price) / entry_p) * 100
                msg = (
                    f"🎯 <b>تارگت اول لمس شد! (#{symbol})</b>\n"
                    f"📌 بازار: {market_type} ({side})\n"
                    f"📈 سود ثبت‌شده: <code>+{pnl:.2f}% 🚀</code>\n"
                    f"🛡 حد ضرر به نقطه ورود (ریسک‌فری) منتقل شد."
                )
                send_telegram_message(msg)
                tp1_notified[base_key] = True
                last_signals[base_key]["sl"] = entry_p

def analyze_and_signal(symbol, market_type):
    df = fetch_candles(symbol, RESOLUTION, count=150)
    if df is None or len(df) < PERIOD + 10:
        return

    current_price = df['close'].iloc[-1]
    manage_open_positions(symbol, market_type, current_price)

    current_minute = datetime.now(timezone.utc).minute
    if current_minute % 15 not in [11, 12, 13, 14, 0]:
        return

    current_candle = df.iloc[-1]
    candle_ts = current_candle['timestamp']
    state_key = f"{symbol}_{market_type}"
    
    if last_processed_candle_time.get(state_key) == candle_ts:
        return

    closes = df['close']
    highs = df['high']
    lows = df['low']
    volumes = df['volume']
    
    sma = closes.rolling(window=PERIOD).mean()
    std = closes.rolling(window=PERIOD).std()
    upper_band = sma + (std * 2.0)
    lower_band = sma - (std * 2.0)
    bandwidth = (upper_band - lower_band) / sma
    avg_volume = volumes.rolling(window=20).mean()

    i = -1
    c_close = closes.iloc[i]
    c_open = df['open'].iloc[i]
    c_high = highs.iloc[i]
    c_low = lows.iloc[i]
    c_vol = volumes.iloc[i]
    c_sma = sma.iloc[i]
    c_upper = upper_band.iloc[i]
    c_lower = lower_band.iloc[i]
    c_bw = bandwidth.iloc[i]
    c_avg_vol = avg_volume.iloc[i]

    if pd.isna(c_sma) or pd.isna(c_upper) or pd.isna(c_lower) or pd.isna(c_avg_vol):
        return

    if c_bw < MIN_BANDWIDTH:
        return

    trend_1h = get_market_trend(symbol)
    is_bullish = c_close >= c_sma
    is_bearish = c_close <= c_sma

    c_body = abs(c_close - c_open)
    c_range = c_high - c_low
    is_small_body = c_body <= (c_range * 0.65) if c_range > 0 else True

    # سیگنال LONG
    if trend_1h == "BULLISH" and is_bullish:
        is_breakout = (c_close > c_upper) and (c_close > c_open) and (c_vol > c_avg_vol * VOLUME_MULTIPLIER)
        recent_break = highs.iloc[-4:-1].max() >= upper_band.iloc[-4:-1].min() * 0.998
        touched_roof = recent_break and (c_low <= c_upper * 1.006 and c_low >= c_sma)
        touched_sma = (c_low <= c_sma * 1.005)
        
        is_pullback = (
            (touched_roof or touched_sma)
            and (c_close >= c_sma) 
            and (c_close >= c_open) 
            and is_small_body 
            and (c_vol <= c_avg_vol * 1.15)
        )

        if is_breakout or is_pullback:
            base_key = f"{symbol}_{market_type}_LONG"
            if base_key not in last_signals:
                last_processed_candle_time[state_key] = candle_ts
                sl = c_close * (1 - SL_PERCENT)
                tp1 = c_close * (1 + TP1_PERCENT)
                tp2 = c_close * (1 + TP2_PERCENT)
                
                last_signals[base_key] = {"side": "LONG", "entry": c_close, "sl": sl, "tp1": tp1}
                tp1_notified[base_key] = False
                sl_notified[base_key] = False

                pattern = "بریک‌آوت صعودی 🚀" if is_breakout else "پولبک صعودی (تاییدشده با کندل کوچک و کم‌حجم) 📈"
                msg = (
                    f"🟢 <b>سیگنال خرید (لانگ) - #{symbol}</b>\n"
                    f"📌 بازار: {market_type}\n"
                    f"💵 قیمت ورود: <code>{format_number(c_close)}</code>\n"
                    f"📊 الگو: {pattern}\n"
                    f"🎯 هدف ۱: <code>{format_number(tp1)}</code>\n"
                    f"🚀 هدف ۲: <code>{format_number(tp2)}</code>\n"
                    f"🛑 حد ضرر: <code>{format_number(sl)}</code>"
                )
                send_telegram_message(msg)

    # سیگنال SHORT
    if market_type == "MARGIN" and trend_1h == "BEARISH" and is_bearish:
        is_breakout_s = (c_close < c_lower) and (c_close < c_open) and (c_vol > c_avg_vol * VOLUME_MULTIPLIER)
        recent_break_s = lows.iloc[-4:-1].min() <= lower_band.iloc[-4:-1].max() * 1.002
        touched_floor = recent_break_s and (c_high >= c_lower * 0.994 and c_high <= c_sma)
        touched_sma_s = (c_high >= c_sma * 0.995)
        
        is_pullback_s = (
            (touched_floor or touched_sma_s)
            and (c_close <= c_sma) 
            and (c_close <= c_open) 
            and is_small_body 
            and (c_vol <= c_avg_vol * 1.15)
        )

        if is_breakout_s or is_pullback_s:
            base_key = f"{symbol}_{market_type}_SHORT"
            if base_key not in last_signals:
                last_processed_candle_time[state_key] = candle_ts
                sl = c_close * (1 + SL_PERCENT)
                tp1 = c_close * (1 - TP1_PERCENT)
                tp2 = c_close * (1 - TP2_PERCENT)
                
                last_signals[base_key] = {"side": "SHORT", "entry": c_close, "sl": sl, "tp1": tp1}
                tp1_notified[base_key] = False
                sl_notified[base_key] = False

                pattern = "بریک‌آوت نزولی 🔻" if is_breakout_s else "پولبک نزولی (تاییدشده با کندل کوچک و کم‌حجم) 📉"
                msg = (
                    f"🔴 <b>سیگنال فروش (شورت) - #{symbol}</b>\n"
                    f"📌 بازار: تعهدی\n"
                    f"💵 قیمت ورود: <code>{format_number(c_close)}</code>\n"
                    f"📊 الگو: {pattern}\n"
                    f"🎯 هدف ۱: <code>{format_number(tp1)}</code>\n"
                    f"🚀 هدف ۲: <code>{format_number(tp2)}</code>\n"
                    f"🛑 حد ضرر: <code>{format_number(sl)}</code>"
                )
                send_telegram_message(msg)

# ================= حلقه اصلی =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()

    startup_msg = (
        "📱 <b>اعلان راه‌اندازی ربات موبایل</b>\n\n"
        "🚀 ربات معامله‌گری بیت‌پین با موفقیت روی سرور آنلاین شد!\n"
        "⚡️ نسخه ضد لیمیت و پایدار فعال گردید."
    )
    send_telegram_message(startup_msg)

    spot_watchlist = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "PEPE_USDT", "NEAR_USDT", "SUI_USDT",
        "LINK_USDT", "ADA_USDT", "AVAX_USDT", "ZEC_USDT", "ARPA_USDT", "FTM_USDT", "MATIC_USDT", "SHIB_USDT",
        "TON_USDT", "APT_USDT", "AR_USDT", "ATOM_USDT", "BCH_USDT", "BNB_USDT", "DOT_USDT", "ETC_USDT",
        "FIL_USDT", "ICP_USDT", "INJ_USDT", "LTC_USDT", "OP_USDT", "POL_USDT", "RNDR_USDT", "RENDER_USDT",
        "RUNE_USDT", "SAND_USDT", "TIA_USDT", "UNI_USDT", "WLD_USDT", "XLM_USDT", "XMR_USDT", "TRX_USDT",
        "FLOKI_USDT", "BONK_USDT", "DOGS_USDT", "HMSTR_USDT", "NOT_USDT", "KAS_USDT", "SEI_USDT", "MANA_USDT", 
        "CHZ_USDT", "CRV_USDT", "GRT_USDT", "AAVE_USDT", "MKR_USDT", "SNX_USDT", "ENJ_USDT", "BAT_USDT", 
        "ZRX_USDT", "BAL_USDT", "COMP_USDT", "YFI_USDT", "SUSHI_USDT", "STX_USDT", "IMX_USDT", "GMT_USDT", 
        "GAL_USDT", "EDU_USDT", "HOOK_USDT", "ID_USDT", "LQTY_USDT", "AGIX_USDT", "FET_USDT", "OCEAN_USDT", 
        "PHB_USDT", "CFX_USDT", "ACH_USDT", "IOST_USDT"
    ]
    spot_watchlist = list(set(spot_watchlist))
    
    margin_watchlist = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "PEPE_USDT", "NEAR_USDT", 
        "SUI_USDT", "LINK_USDT", "ADA_USDT", "AVAX_USDT", "ZEC_USDT", "FTM_USDT", "MATIC_USDT", 
        "SHIB_USDT", "TON_USDT", "APT_USDT", "INJ_USDT", "RNDR_USDT", "UNI_USDT", "ARB_USDT",
        "OP_USDT", "ICP_USDT", "ATOM_USDT", "DOT_USDT", "LTC_USDT", "BCH_USDT", "TRX_USDT", "FIL_USDT"
    ]
    margin_watchlist = list(set(margin_watchlist))

    while True:
        try:
            for sym in spot_watchlist:
                analyze_and_signal(sym, "SPOT")
                time.sleep(SYMBOL_SLEEP)  # مکث ایمن بین هر ارز

            for sym in margin_watchlist:
                analyze_and_signal(sym, "MARGIN")
                time.sleep(SYMBOL_SLEEP)  # مکث ایمن بین هر ارز

            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"خطای حلقه اصلی: {e}", flush=True)
            time.sleep(10)
