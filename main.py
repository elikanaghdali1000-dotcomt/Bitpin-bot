import os
import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

TELEGRAM_TOKEN = "*******"
CHAT_ID = "6643451227"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo}/sendMessage"
        payload = {"chat_id": CHAT_ID, "6643451227": text, "parse_mode": "Markdown"}
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
    # استارت وب‌سرور در پس‌زمینه
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()
    
    print("Server started. Sending startup message to Telegram...")
    # ارسال پیام تلگرام بلافاصله بعد از شروع
    send_telegram_message("🤖 **ربات معامله‌گری بیت‌پین با موفقیت روشن شد!** پیام تست برقرار است.")
    
    # حلقه ساده برای زنده نگه داشتن برنامه
    while True:
        time.sleep(60)
