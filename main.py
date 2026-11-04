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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"
MARKETS_URL = f"{BASE_API}/v1/mkt/markets/"

# هدرهای شبیه‌ساز مرورگر برای جلوگیری از خطاهای 403 / 418 / 451
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Referer": "https://bitpin.ir/"
}

# تنظیمات معاملاتی و فیلترها
BOLLINGER_SQUEEZE_THRESHOLD = 2.0
WHALE_VOLUME_THRESHOLD = 500000.0  # ۵۰۰ هزار تتر حجم تجمیعی بایننس فیوچرز
SIGNAL_TRACKER_FILE = "signal_tracker.json"

# راه‌اندازی سرور مانیتورینگ سبک برای رندر (Render Health Check)
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Multi-Strategy & Binance Whale Bot is Running Successfully!")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# ================= توابع تلگرام و ذخیره‌سازی سیگنال‌ها =================
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send error: {e}")

def load_signal_tracker():
    if os.path.exists(SIGNAL_TRACKER_FILE):
        try:
            with open(SIGNAL_TRACKER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_signal_tracker(tracker_data):
    try:
        with open(SIGNAL_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(tracker_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Tracker save error: {e}")

# ================= دریافت داده از بیت‌پین =================
def fetch_bitpin_markets():
    try:
        res = requests.get(MARKETS_URL, headers=BROWSER_HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict) and "results" in data:
                return data["results"]
            elif isinstance(data, list):
                return data
    except Exception as e:
        print(f"Error fetching Bitpin markets: {e}")
    return []

def fetch_bitpin_candles(symbol, resolution="1h", limit=100):
    try:
        params = {
            "symbol": symbol,
            "res": resolution,
            "limit": limit
        }
        res = requests.get(OHLC_URL, params=params, headers=BROWSER_HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            # ساختار کندل‌های بیت‌پین معمولاً آرایه‌ای از لیست‌ها یا دیکشنری‌هاست
            candles = data if isinstance(data, list) else data.get("results", [])
            if candles:
                df = pd.DataFrame(candles)
                # استانداردسازی ستون‌ها
                if "time" in df.columns:
                    df.rename(columns={"time": "timestamp", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                df.dropna(inplace=True)
                return df
    except Exception as e:
        print(f"Error fetching candles for {symbol}: {e}")
    return None

# ================= موتور رصد نهنگ‌های بایننس فیوچرز =================
def check_binance_whales():
    """رصد حجم‌های بالای ۵۰۰,۰۰۰ تتر در بایننس فیوچرز"""
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            tickers = res.json()
            whales = []
            for t in tickers:
                symbol = t.get("symbol", "")
                if symbol.endswith("USDT"):
                    quote_volume = float(t.get("quoteVolume", 0.0))
                    if quote_volume >= WHALE_VOLUME_THRESHOLD:
                        whales.append((symbol, quote_volume))
            return whales
    except Exception as e:
        print(f"Binance whale tracker error: {e}")
    return []

# ================= توابع محاسباتی تکنیکال =================
def calculate_indicators(df):
    if df is None or len(df) < 30:
        return None
    
    close = df["Close"]
    df["EMA200"] = close.ewm(span=200, adjust=False).mean() if len(df) >= 200 else close.ewm(span=len(df), adjust=False).mean()
    df["SMA20"] = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std()
    
    df["BB_Upper"] = df["SMA20"] + (std20 * 2)
    df["BB_Lower"] = df["SMA20"] - (std20 * 2)
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["SMA20"] * 100
    
    # محاسبه RSI (۱۴ دوره‌ای)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    
    return df

def check_btc_filter():
    """فیلتر میانی بولینگر بیت‌کوین برای تایید لانگ‌ها"""
    df_btc = fetch_bitpin_candles("BTC_IRT", "1h", 50)
    if df_btc is not None and len(df_btc) > 20:
        df_btc = calculate_indicators(df_btc)
        last = df_btc.iloc[-1]
        if last["Close"] >= last["SMA20"]:
            return True
    return False

# ================= اجرای استراتژی‌های معاملاتی =================
def evaluate_strategies(symbol, df):
    df = calculate_indicators(df)
    if df is None or len(df) < 2:
        return
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # بررسی فشردگی بولینگر
    is_squeeze = last["BB_Width"] <= BOLLINGER_SQUEEZE_THRESHOLD

    # ۱. استراتژی سنسی (Sensi)
    # لانگ سنسی: خشکی حجم در کف + بازگشت صعودی
    vol_mean = df["Volume"].rolling(20).mean().iloc[-1]
    if last["Volume"] < (vol_mean * 0.6) and last["Low"] <= last["BB_Lower"] and last["Close"] > prev["Close"]:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (سنسی)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nخشکی حجم در کف و حمایت بولینگر")

    # ۲. استراتژی روند بولینگر (Trend Strategy)
    if last["Close"] <= last["BB_Lower"] and last["Close"] > last["EMA200"] and last["RSI"] < 35:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (روند بولینگر)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nRSI: {last['RSI']:.1f}")

    # ۳. استراتژی پولبک (Pullback Strategy)
    if last["Close"] > last["EMA200"] and prev["Low"] <= last["SMA20"] and last["Close"] > last["SMA20"] and 35 <= last["RSI"] <= 60:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (پولبک صعودی)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nبرخورد به میانگین متحرک و تایید صعود")

    # ۴. استراتژی شکست و پولبک (Break & Retest - مخصوص SHORT)
    if prev["Close"] < prev["BB_Lower"] and last["Close"] > prev["Close"] and last["Close"] < last["SMA20"] and last["RSI"] > 60:
        send_telegram_message(f"🔴 <b>سیگنال SHORT (شکست و پولبک ناموفق)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nپولبک ناموفق به سطح شکسته شده")

# ================= حلقه اصلی ربات =================
def main_loop():
    print("Bitpin & Binance Whale Bot Started Successfully.")
    # اجرای سرور وب در یک ترد جداگانه برای رندر
    threading.Thread(target=run_server, daemon=True).start()
    
    while True:
        try:
            # ۱. رصد نهنگ‌های بایننس
            whales = check_binance_whales()
            if whales:
                msg = "🐋 <b>گزارش حجم نهنگ‌های بایننس فیوچرز (>500k USDT):</b>\n"
                for sym, vol in whales[:5]: # ارسال ۵ مورد برتر
                    msg += f"- {sym}: {vol:,.0f} USDT\n"
                send_telegram_message(msg)

            # ۲. بررسی بازارهای بیت‌پین
            markets = fetch_bitpin_markets()
            for m in markets[:15]: # بررسی ۱۵ بازار اول برای نمونه
                symbol = m.get("code") or m.get("symbol")
                if symbol and symbol.endswith("_IRT"):
                    df = fetch_bitpin_candles(symbol, "1h", 100)
                    if df is not None and not df.empty:
                        evaluate_strategies(symbol, df)
                    time.sleep(1) # فاصله کوتاه بین درخواست‌ها جهت جلوگیری از بن شدن

        except Exception as e:
            print(f"Main loop error: {e}")
        
        # استراحت بین هر دور کامل بررسی بازارها
        time.sleep(300)

if __name__ == "__main__":
    main_loop()
