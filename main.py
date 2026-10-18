import os
import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# تنظیمات تلگرام
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "*******")
CHAT_ID = os.environ.get("CHAT_ID", "6643451227")

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo}/sendMessage"
        payload = {
            "chat_id": 6643451227,
            "text": message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Telegram message sent successfully.")
        else:
            print(f"Failed to send Telegram message: {response.status_code}, {response.text}")
    except Exception as e:
        print("Error sending Telegram message:", e)

# تنظیمات وب‌سرور برای زنده ماندن روی Render
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bitpin Anti-Range Pro Trading Bot is running 24/7 with Telegram!")

def run_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

def check_bitpin_market():
    try:
        url = "https://api.bitpin.org/v1/mkt/markets/"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for market in data.get('results', []):
                if market.get('code') == 'BTC_USDT':
                    price = float(market.get('price', 0))
                    print(f"BTC Price fetched: {price}")
                    return price
        else:
            print(f"Bitpin API error status: {response.status_code}")
    except Exception as e:
        print("Error fetching Bitpin market:", e)
    return None

def bot_loop():
    # پیام اولیه برای تست اتصال تلگرام
    send_telegram_message("🤖 **ربات معامله‌گری بیت‌پین با موفقیت روی سرور روشن شد!**\nدر حال رصد بازار بیت‌کوین...")
    
    while True:
        print("Checking market prices...")
        price = check_bitpin_market()
        if price:
            print(f"Current BTC/USDT price on Bitpin: {price}")
            # اینجا می‌توانید شرط‌های سیگنال‌دهی و ارسال پیام به تلگرام را قرار دهید
        else:
            print("Could not fetch price, retrying...")
        time.sleep(300)

if __name__ == "__main__":
    # راه‌اندازی وب‌سرور در ترد جداگانه
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()
    
    # اجرای حلقه اصلی ربات
    bot_loop()
