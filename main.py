# -*- coding: utf-8 -*-
import os
import time
import json
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")

# تنظیمات پروکسی برای بایننس (در صورت نیاز روی رندر)
BINANCE_PROXY = os.getenv("BINANCE_PROXY", "")
PROXIES = {
    'http': BINANCE_PROXY,
    'https': BINANCE_PROXY
} if BINANCE_PROXY else None

# هدرهای مرورگر برای جلوگیری از خطای 403 بیت‌پین
BITPIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://bitpin.ir/"
}

BASE_API_BITPIN = "https://api.bitpin.org/api"
OHLC_URL_BITPIN = f"{BASE_API_BITPIN}/v1/mkt/candles/"
MARKETS_URL_BITPIN = f"{BASE_API_BITPIN}/v1/mkt/markets/"

# آدرس‌های بایننس فیوچرز
BINANCE_FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_FAPI_KLINES = "https://fapi.binance.com/fapi/v1/klines"

# ================= ارسال پیام به تلگرام =================
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "*******":
        print(f"[Telegram Mock]: {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ================= توابع دریافت داده بیت‌پین =================
def fetch_bitpin_markets():
    try:
        res = requests.get(MARKETS_URL_BITPIN, headers=BITPIN_HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("results", data) if isinstance(data, dict) else data
    except Exception as e:
        print(f"Bitpin Markets Error: {e}")
    return []

def fetch_bitpin_candles(symbol, resolution="60", count=100):
    try:
        params = {"symbol": symbol, "resolution": resolution, "count": count}
        res = requests.get(OHLC_URL_BITPIN, headers=BITPIN_HEADERS, params=params, timeout=15)
        if res.status_code == 200:
            data = res.json()
            candles = data.get("candles", data) if isinstance(data, dict) else data
            if isinstance(candles, list) and len(candles) > 0:
                df = pd.DataFrame(candles)
                if "time" in df.columns:
                    df.rename(columns={"time": "Timestamp", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
    except Exception as e:
        print(f"Bitpin Candles Error for {symbol}: {e}")
    return None

# ================= توابع دریافت داده بایننس فیوچرز =================
def fetch_binance_symbols():
    try:
        res = requests.get(BINANCE_FAPI_EXCHANGE_INFO, proxies=PROXIES, timeout=15)
        if res.status_code == 200:
            data = res.json()
            symbols = [s["symbol"] for s in data.get("symbols", []) if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"]
            return symbols
    except Exception as e:
        print(f"Binance Symbols Error: {e}")
    return []

def fetch_binance_candles(symbol, interval="1h", limit=100):
    try:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        res = requests.get(BINANCE_FAPI_KLINES, params=params, proxies=PROXIES, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data, columns=[
                    'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume',
                    'Close_time', 'Quote_asset_volume', 'Number_of_trades',
                    'Taker_buy_base_asset_volume', 'Taker_buy_quote_asset_volume', 'Ignore'
                ])
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
    except Exception as e:
        print(f"Binance Candles Error for {symbol}: {e}")
    return None

# ================= ۴ استراتژی معاملاتی مشترک =================
def evaluate_strategies(exchange_name, symbol, df):
    if df is None or len(df) < 30:
        return

    last = df.iloc[-1]
    prev = df.iloc[-2]
    close_price = last['Close']
    
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['UpperBB'] = df['SMA20'] + (df['STD20'] * 2)
    df['LowerBB'] = df['SMA20'] - (df['STD20'] * 2)
    
    sma20 = df['SMA20'].iloc[-1]
    upper_bb = df['UpperBB'].iloc[-1]
    lower_bb = df['LowerBB'].iloc[-1]

    signals = []

    # 1. Sensi Strategy
    if prev['Close'] < df['SMA20'].iloc[-2] and last['Close'] > sma20:
        signals.append("🟢 استراتژی Sensi: تقاطع صعودی SMA20")

    # 2. Bollinger Trend
    if last['Close'] > upper_bb:
        signals.append("🚀 استراتژی Bollinger: شکست باند بالایی به سمت بالا")
    elif last['Close'] < lower_bb:
        signals.append("⚠️ استراتژی Bollinger: نفوذ به زیر باند پایینی")

    # 3. Pullback
    if last['Low'] <= sma20 and close_price > sma20:
        signals.append("🔄 استراتژی Pullback: پولبک موفق به SMA20")

    # 4. Break & Retest
    recent_high = df['High'].iloc[-20:-2].max()
    if prev['Close'] > recent_high and last['Close'] >= recent_high:
        signals.append("⭐ استراتژی Break & Retest: شکست مقاومت کلیدی")

    if signals:
        msg = f"🔔 *سیگنال جدید ({exchange_name})*\nارز: `{symbol}`\nقیمت: `{close_price}`\n\n" + "\n".join(signals)
        send_telegram_message(msg)

# ================= ترد اسکن بیت‌پین =================
def bitpin_worker():
    while True:
        try:
            markets = fetch_bitpin_markets()
            for m in markets:
                symbol = m.get("code") or m.get("symbol")
                if symbol and symbol.endswith("_IRT"):
                    df = fetch_bitpin_candles(symbol, "60", 100)
                    if df is not None and not df.empty:
                        evaluate_strategies("Bitpin", symbol, df)
                    time.sleep(0.5)
            time.sleep(300)
        except Exception as e:
            print(f"Bitpin Worker Error: {e}")
            time.sleep(60)

# ================= ترد اسکن بایننس فیوچرز =================
def binance_worker():
    while True:
        try:
            symbols = fetch_binance_symbols()
            for symbol in symbols:
                df = fetch_binance_candles(symbol, "1h", 100)
                if df is not None and not df.empty:
                    evaluate_strategies("Binance Futures", symbol, df)
                time.sleep(0.3)
            time.sleep(300)
        except Exception as e:
            print(f"Binance Worker Error: {e}")
            time.sleep(60)

# ================= وب‌سرور مانیتورینگ برای Render =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Both Bitpin and Binance Bots are running successfully! /ok")
    def log_message(self, format, *args):
        return

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# ================= اجرای اصلی =================
if __name__ == "__main__":
    send_telegram_message("🤖 ربات ترکیبی تحلیل بازار راه‌اندازی شد\n\n📊 وضعیت: اسکن همزمان بازارهای بیت‌پین و بایننس فیوچرز با ۴ استراتژی آغاز شد. /ok")
    
    # راه‌اندازی وب‌سرور رندر
    threading.Thread(target=run_http_server, daemon=True).start()
    
    # راه‌اندازی ترد بیت‌پین
    threading.Thread(target=bitpin_worker, daemon=True).start()
    
    # راه‌اندازی ترد بایننس فیوچرز
    threading.Thread(target=binance_worker, daemon=True).start()
    
    # نگه داشتن ترد اصلی برنامه
    while True:
        time.sleep(1)
