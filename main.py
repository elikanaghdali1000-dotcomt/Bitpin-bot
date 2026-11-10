import os
import requests

# آدرس ورکر کلودفلر و میزبان‌های اصلی بیت‌پین
HOSTS = [
    "https://divine-wildflower-badc.elikanaghdali1000.workers.dev",
    "https://api.bitpin.org",
    "https://api.bitpin.ir",
    "https://api.bitpin.com"
]

PATH = "/api/v1/mkt/tickers/"

# هدرهای شبیه‌سازی مرورگر (دقیقاً مشابه ربات اصلی)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Origin": "https://bitpin.ir",
    "Referer": "https://bitpin.ir/",
}

print("=== تست اتصال به بیت‌پین و گرفتن قیمت بیت‌کوین ===")

for host in HOSTS:
    url = host + PATH
    print(f"\nتلاش با میزبان: {host}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            # پیدا کردن بیت‌کوین در لیست
            btc = next((item for item in data if item.get("symbol") == "BTC_USDT"), None)
            if btc:
                print(f"✅ موفق! قیمت بیت‌کوین (BTC_USDT): {btc.get('price')}")
            else:
                print("⚠️ پاسخ دریافت شد اما نماد BTC_USDT پیدا نشد.")
            break
        else:
            print(f"❌ خطا: {response.status_code} - متن پاسخ: {response.text[:150]}")
            
    except Exception as e:
        print(f"❌ استثنا (Exception): {type(e).__name__} - {e}")
