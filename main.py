import os
import time
import requests
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAG-Wfh8j905Q2BGXe3BZFJ3jdw8Ow8myV...")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

API_URL = "https://api.bitpin.org/api/v1/mkt/candles/"
TICKERS_URL = "https://api.bitpin.org/api/v1/mkt/tickers/"

RESOLUTION = "15"           # تایم‌فریم ۱۵ دقیقه
PERIOD = 20                 # دوره بولینگر
STD_DEV = 2.0               # انحراف معیار بولینگر
MIN_BANDWIDTH = 0.008       # حداقل پهنای باند برای فشرده نبودن مطلق
VOLUME_MULTIPLIER = 1.4     # ضریب حجم بریک‌آوت

# ================= توابع تلگرام =================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "PUT_TOKEN_HERE":
        print("[Telegram] Token is not set!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"[Telegram Error] {response.text}")
    except Exception as e:
        print(f"[Telegram Exception] {e}")

# ================= دریافت لیست ارزها =================
def get_active_symbols():
    try:
        response = requests.get(TICKERS_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            tickers = data.get("results", data) if isinstance(data, dict) else data
            symbols = []
            for item in tickers:
                # فقط بازار پایه تومان یا تتر
                symbol = item.get("symbol", "")
                if symbol and (symbol.endswith("_IRT") or symbol.endswith("_USDT")):
                    symbols.append(symbol)
            print(f"[Bitpin] Total symbols found: {len(symbols)}")
            return symbols[:30] # محدود کردن به 30 ارز پرطرفدار برای جلوگیری از بن شدن IP
    except Exception as e:
        print(f"[Bitpin Error] Fetching tickers failed: {e}")
    # لیست پیش‌فرض در صورت خطا
    return ["BTC_IRT", "ETH_IRT", "SOL_IRT", "DOGE_IRT", "PEPE_IRT"]

# ================= وب‌سرور Keep-Alive برای رندر =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is running live!")
    def log_message(self, format, *args):
        return

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"[Server] Keep-alive server running on port {port}")
    server.serve_forever()

# ================= منطق اصلی تحلیل بازار =================
def fetch_candles(symbol, resolution="15", limit=100):
    try:
        end_time = int(time.time())
        start_time = end_time - (limit * int(resolution) * 60 * 3)
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start_time": start_time,
            "end_time": end_time
        }
        response = requests.get(API_URL, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                # ساختار معمول بیت‌پین: [timestamp, open, high, low, close, volume]
                if len(df.columns) >= 6:
                    df = df.iloc[:, :6]
                    df.columns = ['time', 'open', 'high', 'low', 'close', 'volume']
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.dropna(inplace=True)
                    return df
    except Exception as e:
        print(f"[Candle Error] {symbol}: {e}")
    return None

def analyze_market():
    print(f"\n[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] Starting market scan...")
    symbols = get_active_symbols()
    
    for symbol in symbols:
        df = fetch_candles(symbol, RESOLUTION, limit=50)
        if df is None or len(df) < PERIOD + 5:
            continue
            
        # محاسبات اندیکاتورها
        df['sma'] = df['close'].rolling(window=PERIOD).mean()
        df['std'] = df['close'].rolling(window=PERIOD).std()
        df['upper'] = df['sma'] + (STD_DEV * df['std'])
        df['lower'] = df['sma'] - (STD_DEV * df['std'])
        df['bandwidth'] = (df['upper'] - df['lower']) / df['sma']
        df['avg_vol'] = df['volume'].rolling(window=PERIOD).mean()
        
        # بررسی کندل آخر بسته شده (اندیس -2 چون کندل آخر در حال تشکیل است)
        c_open = df['open'].iloc[-2]
        c_high = df['high'].iloc[-2]
        c_low = df['low'].iloc[-2]
        c_close = df['close'].iloc[-2]
        c_vol = df['volume'].iloc[-2]
        c_avg_vol = df['avg_vol'].iloc[-2]
        c_sma = df['sma'].iloc[-2]
        c_upper = df['upper'].iloc[-2]
        c_lower = df['lower'].iloc[-2]
        c_bandwidth = df['bandwidth'].iloc[-2]
        
        c_body = abs(c_close - c_open)
        c_range = c_high - c_low
        if c_range == 0: 
            continue
            
        is_small_body = (c_body <= c_range * 0.6)
        
        # شرایط پولبک لانگ
        is_pullback_long = (c_low <= c_sma * 1.005) and (c_close > c_open) and is_small_body and (c_vol <= c_avg_vol)
        
        if is_pullback_long:
            print(f"[SIGNAL FOUND] Long pullback on {symbol}! Price: {c_close}")
            msg = f"🚀 **سیگنال لانگ (خرید)**\nارز: `{symbol}`\nقیمت ورود: `{c_close}`"
            send_telegram(msg)
            
        # شرایط پولبک شورت
        is_pullback_short = (c_high >= c_sma * 0.995) and (c_close < c_open) and is_small_body and (c_vol <= c_avg_vol)
        
        if is_pullback_short:
            print(f"[SIGNAL FOUND] Short pullback on {symbol}! Price: {c_close}")
            msg = f"📉 **سیگنال شورت (فروش تعهدی)**\nارز: `{symbol}`\nقیمت ورود: `{c_close}`"
            send_telegram(msg)

    print("[Scan Completed] Waiting for next interval...")

# ================= حلقه زمان‌بندی اصلی =================
def bot_loop():
    print("Bot loop started. Sending startup notification...")
    send_telegram("🤖 **ربات معامله‌گری بیت‌پین با موفقیت روشن شد و در حال رصد بازار است.**")
    
    while True:
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        
        # بررسی در دقایق 12، 13، 14 و 0 (ابتدای کندل جدید 15 دقیقه‌ای)
        if current_minute in [12, 13, 14, 0]:
            try:
                analyze_market()
            except Exception as e:
                print(f"[Loop Error] {e}")
            # خوابیدن برای جلوگیری از اجرای مکرر در یک دقیقه
            time.sleep(60)
        else:
            time.sleep(15)

if __name__ == "__main__":
    # اجرای وب‌سرور در یک ترد جداگانه
    t_server = threading.Thread(target=run_server, daemon=True)
    t_server.start()
    
    # اجرای حلقه اصلی ربات
    bot_loop()
