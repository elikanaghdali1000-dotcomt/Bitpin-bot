# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")

# اصلاح مسیر آدرس (اضافه کردن /api)
BASE_API = "https://api.bitpin.org/api" 
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"
MARKETS_URL = f"{BASE_API}/v1/mkt/markets/"

BITPIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://bitpin.ir",
    "Referer": "https://bitpin.ir/"
}

BINANCE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BINANCE_MIRRORS = ["https://fapi.binance.com", "https://api.binance.com", "https://data-api.binance.vision"]
WHALE_VOLUME_THRESHOLD = 500000.0

# ================= سرور سلامت =================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Running!")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthCheckHandler).serve_forever()

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

# ================= توابع دریافت داده =================
def fetch_bitpin_markets():
    try:
        res = requests.get(MARKETS_URL, headers=BITPIN_HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("results", data) if isinstance(data, dict) else data
        else:
            print(f"Bitpin Error: {res.status_code}") # نمایش کد خطا در کنسول
    except Exception as e:
        print(f"Bitpin Exception: {e}")
    return []

def fetch_bitpin_candles(symbol, resolution="1h", limit=100):
    try:
        res = requests.get(OHLC_URL, params={"symbol": symbol, "res": resolution, "limit": limit}, headers=BITPIN_HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            candles = data if isinstance(data, list) else data.get("results", [])
            df = pd.DataFrame(candles)
            if "time" in df.columns:
                df.rename(columns={"time": "timestamp", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
                for col in ["Open", "High", "Low", "Close", "Volume"]: df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.dropna()
    except: pass
    return None

def check_binance_whales():
    for base in BINANCE_MIRRORS:
        url = f"{base}/fapi/v1/ticker/24hr" if "fapi" in base else f"{base}/api/v3/ticker/24hr"
        try:
            res = requests.get(url, headers=BINANCE_HEADERS, timeout=10)
            if res.status_code == 200:
                tickers = res.json()
                return [(t["symbol"], float(t["quoteVolume"])) for t in tickers if t.get("symbol", "").endswith("USDT") and float(t.get("quoteVolume", 0)) >= WHALE_VOLUME_THRESHOLD]
        except: continue
    return []

# ================= موتور اصلی =================
def main_loop():
    threading.Thread(target=run_server, daemon=True).start()
    
    # تست اولیه
    test_markets = fetch_bitpin_markets()
    test_whales = check_binance_whales()
    
    status_msg = "🤖 <b>ربات راه‌اندازی شد</b>\n\n"
    status_msg += f"📊 <b>بیت‌پین:</b> {'متصل ✅' if test_markets else 'خطا ❌'}\n"
    status_msg += f"🐋 <b>بایننس:</b> {'متصل ✅' if test_whales else 'خطا ❌'}\n"
    send_telegram_message(status_msg)
    
    while True:
        # (بقیه منطق ربات در اینجا قرار می‌گیرد)
        time.sleep(300)

if __name__ == "__main__":
    main_loop()
