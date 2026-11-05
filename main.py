# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و متغیرها =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")

# دامنه‌های رسمی بیت‌پین
BITPIN_HOSTS = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org"
]

# میرورهای متنوع بایننس (اسپات و فیوچرز برای عبور از تحریم سرور اروپا)
BINANCE_ENDPOINTS = [
    ("https://data-api.binance.vision/api/v3/ticker/24hr", "spot"),
    ("https://api.binance.com/api/v3/ticker/24hr", "spot"),
    ("https://fapi.binance.com/fapi/v1/ticker/24hr", "futures")
]

WHALE_VOLUME_THRESHOLD = 500000.0

# سشن پایدار با تنظیمات کامل مرورگر
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
})

# ================= سرور سلامت رندر =================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot is Running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ================= پیام‌رسان تلگرام =================
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        SESSION.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=12)
    except Exception as e:
        print(f"[Telegram Err] {e}")

# ================= دریافت داده از بیت‌پین =================
ACTIVE_BITPIN_HOST = BITPIN_HOSTS[0]

def fetch_bitpin_markets():
    global ACTIVE_BITPIN_HOST
    for host in BITPIN_HOSTS:
        url = f"{host}/v1/mkt/markets/"
        try:
            res = SESSION.get(url, timeout=12)
            if res.status_code == 200:
                ACTIVE_BITPIN_HOST = host
                data = res.json()
                return data.get("results", data) if isinstance(data, dict) else data
            else:
                print(f"[Bitpin HTTP Error] {host} returned {res.status_code}")
        except Exception as e:
            print(f"[Bitpin Conn Error] {host} -> {e}")
    return []

def fetch_bitpin_candles(symbol, resolution="1h", limit=100):
    url = f"{ACTIVE_BITPIN_HOST}/v1/mkt/candles/"
    try:
        params = {"symbol": symbol, "res": resolution, "limit": limit}
        res = SESSION.get(url, params=params, timeout=12)
        if res.status_code == 200:
            data = res.json()
            candles = data if isinstance(data, list) else data.get("results", [])
            if candles:
                df = pd.DataFrame(candles)
                if "time" in df.columns:
                    df.rename(columns={"time": "timestamp", "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}, inplace=True)
                for col in ["Open", "High", "Low", "Close", "Volume"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df.dropna()
    except Exception as e:
        print(f"[Bitpin Candle Err] {symbol} -> {e}")
    return None

# ================= پایش نهنگ‌های بایننس =================
def check_binance_whales():
    for url, market_type in BINANCE_ENDPOINTS:
        try:
            res = SESSION.get(url, timeout=10)
            if res.status_code == 200:
                tickers = res.json()
                whales = []
                for t in tickers:
                    symbol = t.get("symbol", "")
                    if symbol.endswith("USDT"):
                        vol_key = "quoteVolume" if "quoteVolume" in t else "volume"
                        quote_vol = float(t.get(vol_key, 0.0))
                        if quote_vol >= WHALE_VOLUME_THRESHOLD:
                            whales.append((symbol, quote_vol))
                if whales:
                    return whales
            else:
                print(f"[Binance HTTP Error] {url} returned {res.status_code}")
        except Exception as e:
            print(f"[Binance Conn Error] {url} -> {e}")
    return []

# ================= اندیکاتورها و فیلترها =================
def calculate_indicators(df):
    if df is None or len(df) < 30:
        return None
    close = df["Close"]
    df["EMA200"] = close.ewm(span=200, adjust=False).mean() if len(df) >= 200 else close.ewm(span=len(df), adjust=False).mean()
    df["SMA20"] = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std()
    df["BB_Upper"] = df["SMA20"] + (std20 * 2)
    df["BB_Lower"] = df["SMA20"] - (std20 * 2)
    
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df

def check_btc_filter():
    df_btc = fetch_bitpin_candles("BTC_IRT", "1h", 50)
    if df_btc is not None and len(df_btc) > 20:
        df_btc = calculate_indicators(df_btc)
        if df_btc is not None:
            last = df_btc.iloc[-1]
            return last["Close"] >= last["SMA20"]
    return True  # در صورت در دسترس نبودن موقت بیت‌کوین مانع سایر سیگنال‌ها نشود

# ================= استراتژی‌های معاملاتی ۴ گانه =================
def evaluate_strategies(symbol, df):
    df = calculate_indicators(df)
    if df is None or len(df) < 2:
        return
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # ۱. سنسی
    vol_mean = df["Volume"].rolling(20).mean().iloc[-1]
    if last["Volume"] < (vol_mean * 0.6) and last["Low"] <= last["BB_Lower"] and last["Close"] > prev["Close"]:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (سنسی)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nخشکی حجم در کف بولینگر")

    # ۲. روند بولینگر
    if last["Close"] <= last["BB_Lower"] and last["Close"] > last["EMA200"] and last["RSI"] < 35:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (روند بولینگر)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nRSI: {last['RSI']:.1f}")

    # ۳. پولبک صعودی
    if last["Close"] > last["EMA200"] and prev["Low"] <= last["SMA20"] and last["Close"] > last["SMA20"] and 35 <= last["RSI"] <= 60:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (پولبک صعودی)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nبرخورد به میانگین متحرک")

    # ۴. شکست و پولبک نزولی
    if prev["Close"] < prev["BB_Lower"] and last["Close"] > prev["Close"] and last["Close"] < last["SMA20"] and last["RSI"] > 60:
        send_telegram_message(f"🔴 <b>سیگنال SHORT (شکست و پولبک ناموفق)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nری‌تست ناموفق به سطح شکسته")

# ================= حلقه اصلی =================
def main_loop():
    print("🚀 Bot starting on Render...")
    threading.Thread(target=run_server, daemon=True).start()
    
    time.sleep(2)
    test_markets = fetch_bitpin_markets()
    test_whales = check_binance_whales()
    
    bitpin_ok = bool(test_markets)
    binance_ok = bool(test_whales)
    
    msg = "🤖 <b>ربات تحلیل و شکار نهنگ راه‌اندازی شد</b>\n\n"
    if bitpin_ok and binance_ok:
        msg += "✅ <b>وضعیت کلی: کاملاً سالم و آنلاین</b> (/ok)\n\n"
    else:
        msg += "⚠️ <b>وضعیت کلی: بررسی خطا</b>\n\n"
        
    msg += f"📊 <b>بیت‌پین:</b> {'متصل ✅ (' + str(len(test_markets)) + ' بازار)' if bitpin_ok else 'خطا در ارتباط ❌'}\n"
    msg += f"🐋 <b>بایننس:</b> {'متصل ✅ (' + str(len(test_whales)) + ' نماد)' if binance_ok else 'خطا در ارتباط ❌'}\n\n"
    msg += "عملیات جمع‌آوری داده‌ها آغاز شد."
    send_telegram_message(msg)
    
    while True:
        try:
            whales = check_binance_whales()
            if whales:
                whales.sort(key=lambda x: x[1], reverse=True)
                w_msg = "🐋 <b>۵ نماد برتر با حجم سنگین بایننس:</b>\n"
                for s, v in whales[:5]:
                    w_msg += f"• {s}: {v:,.0f} USDT\n"
                send_telegram_message(w_msg)
                
            markets = fetch_bitpin_markets()
            if markets:
                irt_markets = [m for m in markets if (m.get("code") or m.get("symbol") or "").endswith("_IRT")]
                for m in irt_markets[:20]:
                    sym = m.get("code") or m.get("symbol")
                    if sym:
                        df = fetch_bitpin_candles(sym, "1h", 100)
                        if df is not None and not df.empty:
                            evaluate_strategies(sym, df)
                        time.sleep(1)
        except Exception as e:
            print(f"[Loop Exception] {e}")
        time.sleep(300)

if __name__ == "__main__":
    main_loop()
