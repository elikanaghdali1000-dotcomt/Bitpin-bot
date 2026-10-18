import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

TELEGRAM_TOKEN = "*******"
CHAT_ID = "6643451227"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload, timeout=10)
        print("Telegram Response Code:", response.status_code)
        print("Telegram Response Body:", response.text)
    except Exception as e:
        print("Error sending Telegram message:", e)

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    # استارت وب‌سرور در ترد جداگانه
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()
    
    print("Server started. Sending startup message...")
    # ارسال پیام تلگرام بلافاصله بعد از شروع
    send_telegram_message("🤖 ربات معامله‌گری بیت‌پین روشن شد و آماده تست است!")
    
    # حلقه برای بررسی قیمت و ارسال پیام
    while True:
        try:
            url = "https://api.bitpin.org/v1/mkt/markets/"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for market in data.get('results', []):
                    if market.get('code') == 'BTC_USDT':
                        price = market.get('price')
                        print(f"Current BTC Price: {price}")
        except Exception as err:
            print("Error fetching price:", err)
        
        time.sleep(60)
