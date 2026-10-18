import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# تنظیمات وب‌سرور برای زنده ماندن روی Render
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bitpin Anti-Range Pro Trading Bot is running 24/7")

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
                    price = market.get('price')
                    print(f"BTC Price fetched successfully: {price}")
                    return price
        else:
            print(f"Bitpin API error status: {response.status_code}")
    except Exception as e:
        print("Error fetching Bitpin market:", e)
    return None

def bot_loop():
    while True:
        print("Checking market prices...")
        price = check_bitpin_market()
        if price:
            print(f"Current BTC/USDT price on Bitpin: {price}")
        else:
            print("Could not fetch price, retrying...")
        time.sleep(300)

if __name__ == "__main__":
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()
    
    bot_loop()
