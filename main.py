# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo"
TELEGRAM_CHAT_ID = "6643451227"
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

API_URL = "https://api.bitpin.ir/v1/mkt/markets/"
OHLC_URL = "https://api.bitpin.ir/v1/mkt/tv/history/"

BB_PERIOD = 20
BB_STD = 2.0

# حد سود و ضرر مخصوص پولبک
PULLBACK_SL_PCT = 0.02
PULLBACK_TP1_PCT = 0.02
PULLBACK_TP2_PCT = 0.04

# حد سود و ضرر مخصوص استاد (بازگشتی)
SENSEI_SL_PCT = 0.025
SENSEI_TP1_PCT = 0.03
SENSEI_TP2_PCT = 0.06

LEVERAGE = 3
CHECK_INTERVAL = 300  # هر 5 دقیقه

# وضعیت پوزیشن‌های فعال (برای مدیریت SL/TP)
active_positions = {}
positions_lock = threading.Lock()

# کش برای داده‌های کندل جهت کاهش درخواست‌های تکراری
ohlc_cache = {}
ohlc_cache_lock = threading.Lock()
CACHE_TTL = 180  # 3 دقیقه

# ================= سرور HTTP برای پایش در رندر (Keep-Alive) =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is Running Successfully!")
    def log_message(self, format, *args):
        return

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# ================= توابع ارتباطی و ارسال پیام =================
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return
        except Exception as e:
            time.sleep(2)

def get_bitpin_markets():
    try:
        resp = requests.get(API_URL, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get("results", [])
            symbols = []
            for m in markets:
                if m.get("quote_currency", {}).get("code") in ["USDT", "IRT", "USD"]:
                    code = m.get("code")
                    if code:
                        symbols.append(code)
            return symbols
    except Exception as e:
        print(f"Error fetching markets: {e}")
    return []

def get_ohlcv(symbol, resolution="60", count=100):
    cache_key = f"{symbol}_{resolution}"
    now = time.time()
    
    with ohlc_cache_lock:
        if cache_key in ohlc_cache:
            cached_data, timestamp = ohlc_cache[cache_key]
            if now - timestamp < CACHE_TTL:
                return cached_data.copy()

    end_time = int(now)
    # احتیاط برای تایم‌فریم‌های مختلف
    if resolution == "15":
        start_time = end_time - (count * 15 * 60 * 2)
    else:
        start_time = end_time - (count * 3600 * 2)

    params = {
        "symbol": symbol,
        "resolution": resolution,
        "from": start_time,
        "to": end_time
    }
    
    for attempt in range(3):
        try:
            resp = requests.get(OHLC_URL, params=params, timeout=10)
            if resp.status_code == 200:
                res_data = resp.json()
                if res_data.get("s") == "ok":
                    df = pd.DataFrame({
                        "time": res_data.get("t"),
                        "open": res_data.get("o"),
                        "high": res_data.get("h"),
                        "low": res_data.get("l"),
                        "close": res_data.get("c"),
                        "volume": res_data.get("v")
                    })
                    df = df.dropna()
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = df[col].astype(float)
                    
                    if len(df) > count:
                        df = df.tail(count).reset_index(drop=True)
                        
                    with ohlc_cache_lock:
                        ohlc_cache[cache_key] = (df, now)
                    return df
            time.sleep(1)
        except Exception as e:
            time.sleep(2)
            
    return None

# ================= توابع اندیکاتورها و تحلیل تکنیکال =================
def calculate_indicators(df):
    if df is None or len(df) < BB_PERIOD:
        return df
    
    df["sma"] = df["close"].rolling(window=BB_PERIOD).mean()
    df["std"] = df["close"].rolling(window=BB_PERIOD).std()
    df["upper_bb"] = df["sma"] + (df["std"] * BB_STD)
    df["lower_bb"] = df["sma"] - (df["std"] * BB_STD)
    df["volume_sma"] = df["volume"].rolling(window=20).mean()
    
    # اندیکاتورهای کمکی برای روش استاد
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    
    return df

def get_btc_trend():
    """بررسی روند کلی بازار از روی بیت‌کوین (BTC_USDT)"""
    df = get_ohlcv("BTC_USDT", resolution="60", count=50)
    if df is None or len(df) < 20:
        return "NEUTRAL"
    df = calculate_indicators(df)
    last = df.iloc[-1]
    if last["close"] > last["ema20"]:
        return "BULLISH"
    elif last["close"] < last["ema20"]:
        return "BEARISH"
    return "NEUTRAL"

# ================= استراتژی ۱: روش استاد (SENSEI - بازگشتی / S&D / حجم) =================
def check_sensei_strategy(df, symbol):
    """
    روش استاد: بازگشت از حمایت/مقاومت با کندل رد (Pinbar/Rejection) و فرسودگی حجم
    """
    if df is None or len(df) < 30:
        return None
        
    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]
    
    # شناسایی سطوح کلیدی (مینیمم و ماکزیمم 20 کندل قبل به جز 3 کندل آخر)
    history_slice = df.iloc[-25:-3]
    support_level = history_slice["low"].min()
    resistance_level = history_slice["high"].max()
    
    # بررسی فرسودگی حجم در نواحی بحرانی
    avg_vol = df["volume"].tail(20).mean()
    is_exhaustion_vol = prev["volume"] < (avg_vol * 0.7) or last["volume"] < (avg_vol * 0.7)
    
    body = abs(last["close"] - last["open"])
    candle_range = last["high"] - last["low"]
    if candle_range == 0:
        return None
        
    # کندل بازگشتی (پین‌بار یا رد قیمت)
    is_pinbar_long = (last["close"] > last["open"]) and ((last["open"] - last["low"]) > body * 1.5)
    is_pinbar_short = (last["close"] < last["open"]) and ((last["high"] - last["open"]) > body * 1.5)
    
    # 1. سیگنال SHORT استاد (برخورد به مقاومت بالا + حجم فرسوده + رد قیمت)
    near_resistance = last["high"] >= resistance_level * 0.992
    if near_resistance and (is_pinbar_short or last["close"] < prev["low"]) and is_exhaustion_vol:
        entry = last["close"]
        sl = entry * (1 + SENSEI_SL_PCT)
        tp1 = entry * (1 - SENSEI_TP1_PCT)
        tp2 = entry * (1 - SENSEI_TP2_PCT)
        return {
            "strategy": "SENSEI",
            "type": "SHORT",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reason": "مقاومت استاد + حجم فرسوده + رد قیمت (Short)"
        }
        
    # 2. سیگنال LONG استاد (برخورد به حمایت پایین + حجم فرسوده + رد قیمت)
    near_support = last["low"] <= support_level * 1.008
    if near_support and (is_pinbar_long or last["close"] > prev["high"]) and is_exhaustion_vol:
        entry = last["close"]
        sl = entry * (1 - SENSEI_SL_PCT)
        tp1 = entry * (1 + SENSEI_TP1_PCT)
        tp2 = entry * (1 + SENSEI_TP2_PCT)
        return {
            "strategy": "SENSEI",
            "type": "LONG",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reason": "حمایت استاد + حجم فرسوده + رد قیمت (Long)"
        }
        
    return None

# ================= استراتژی ۲: روش خودمان (TREND - موج‌سواری و پولبک) =================
def check_trend_strategy(df, symbol, btc_trend):
    """
    روش خودمان: پولبک به میانگین / باندهای بولینگر همراه با روند کلی
    """
    if df is None or len(df) < BB_PERIOD + 5:
        return None
        
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # فیلتر روند بیت‌کوین
    if btc_trend == "BEARISH":
        # در بازار نزولی بیت‌کوین، ترجیحاً شورت یا فیلتر سخت‌گیرانه لانگ
        pass
    
    # بررسی پولبک لانگ: قیمت به باند پایین یا نزدیک SMA خورده و برمی‌گشته
    is_long_pullback = (prev["low"] <= prev["lower_bb"]) and (last["close"] > prev["open"]) and (last["volume"] > last["volume_sma"])
    if is_long_pullback and btc_trend != "BEARISH":
        entry = last["close"]
        sl = entry * (1 - PULLBACK_SL_PCT)
        tp1 = entry * (1 + PULLBACK_TP1_PCT)
        tp2 = entry * (1 + PULLBACK_TP2_PCT)
        return {
            "strategy": "TREND",
            "type": "LONG",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reason": "پولبک باند بولینگر + تایید حجم (Long)"
        }
        
    # بررسی پولبک شورت: قیمت به باند بالا خورده و ریخته
    is_short_pullback = (prev["high"] >= prev["upper_bb"]) and (last["close"] < prev["open"]) and (last["volume"] > last["volume_sma"])
    if is_short_pullback and btc_trend != "BULLISH":
        entry = last["close"]
        sl = entry * (1 + PULLBACK_SL_PCT)
        tp1 = entry * (1 - PULLBACK_TP1_PCT)
        tp2 = entry * (1 - PULLBACK_TP2_PCT)
        return {
            "strategy": "TREND",
            "type": "SHORT",
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reason": "پولبک باند بولینگر بالایی + ریزش حجم (Short)"
        }
        
    return None

# ================= مدیریت پوزیشن‌ها و ارسال سیگنال =================
def manage_positions_and_scan():
    symbols = get_bitpin_markets()
    if not symbols:
        return
        
    btc_trend = get_btc_trend()
    
    for symbol in symbols:
        # دریافت داده‌های تایم‌فریم اصلی (مثلا 1 ساعته برای دقت بیشتر)
        df = get_ohlcv(symbol, resolution="60", count=60)
        if df is None or len(df) < 30:
            continue
            
        df = calculate_indicators(df)
        
        with positions_lock:
            if symbol in active_positions:
                # مدیریت پوزیشن باز (بررسی TP و SL)
                pos = active_positions[symbol]
                current_price = df.iloc[-1]["close"]
                
                if pos["type"] == "LONG":
                    if current_price >= pos["tp2"]:
                        send_telegram_message(f"🏆 **تارگت ۲ لمس شد (بستن کامل پوزیشن)**\nارز: `{symbol}`\nقیمت: `{current_price}`")
                        del active_positions[symbol]
                    elif current_price <= pos["sl"]:
                        send_telegram_message(f"❌ **حد ضرر (SL) فعال شد**\nارز: `{symbol}`\nقیمت: `{current_price}`")
                        del active_positions[symbol]
                elif pos["type"] == "SHORT":
                    if current_price <= pos["tp2"]:
                        send_telegram_message(f"🏆 **تارگت ۲ لمس شد (بستن کامل پوزیشن)**\nارز: `{symbol}`\nقیمت: `{current_price}`")
                        del active_positions[symbol]
                    elif current_price >= pos["sl"]:
                        send_telegram_message(f"❌ **حد ضرر (SL) فعال شد**\nارز: `{symbol}`\nقیمت: `{current_price}`")
                        del active_positions[symbol]
                continue

        # اگر پوزیشنی روی این ارز نداریم، بررسی استراتژی‌ها
        # **اولویت اول: روش استاد (SENSEI)**
        signal = check_sensei_strategy(df, symbol)
        
        # **اولویت دوم: روش خودمان (TREND)** اگر روش استاد سیگنالی نداد
        if not signal:
            signal = check_trend_strategy(df, symbol, btc_trend)
            
        if signal:
            with positions_lock:
                active_positions[symbol] = signal
                
            # تفکیک برچسب سیگنال‌ها بر اساس درخواست شما
            if signal["strategy"] == "SENSEI":
                header = "🎯 روش استاد | بازگشتی"
            else:
                header = "🚀 روش خودمان | روند"
                
            msg = (
                f"{header}\n\n"
                f"💎 نماد: `{symbol}`\n"
                f"📌 جهت پوزیشن: `{signal['type']}` (اهرم {LEVERAGE}x)\n"
                f"📥 قیمت ورود: `{signal['entry']:.4f}`\n"
                f"🛑 حد ضرر (SL): `{signal['sl']:.4f}`\n"
                f"🎯 تارگت اول (TP1): `{signal['tp1']:.4f}`\n"
                f"🎯 تارگت دوم (TP2): `{signal['tp2']:.4f}`\n"
                f"💡 دلیل: {signal['reason']}"
            )
            send_telegram_message(msg)

        time.sleep(0.5)  # جلوگیری از فشار روی API

def bot_loop():
    send_telegram_message("🤖 **ربات معامله‌گری بیت‌پین با موفقیت روشن شد و شروع به اسکن بازار کرد.**")
    while True:
        try:
            manage_positions_and_scan()
        except Exception as e:
            print(f"Error in main loop: {e}")
        time.sleep(CHECK_INTERVAL)

# ================= نقطه شروع برنامه =================
if __name__ == "__main__":
    # اجرای سرور HTTP در یک ترد جداگانه برای رندر
    server_thread = threading.Thread(target=run_http_server, daemon=True)
    server_thread.start()
    
    # اجرای حلقه اصلی ربات
    bot_loop()
