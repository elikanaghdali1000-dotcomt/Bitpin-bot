import time
import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def test_connection():
    print("--- ۱. تست قیمت لحظه‌ای و تیکرها ---")
    try:
        # آدرس اصلاح‌شده: اضافه شدن /api/
        ticker_url = "https://api.bitpin.org/api/v1/mkt/tickers/"
        res = requests.get(ticker_url, headers=headers, timeout=10)
        print(f"کد وضعیت تیکر: {res.status_code}")
        
        if res.status_code == 200:
            data = res.json()
            btc_data = next((item for item in data if item.get("symbol") == "BTC_USDT"), None)
            if btc_data:
                print(f"✅ موفق! قیمت BTC_USDT: {btc_data.get('price')} دلار")
            else:
                print("⚠️ تیکر دریافت شد ولی BTC_USDT در لیست نبود.")
        else:
            print(f"❌ خطا: {res.status_code}")
    except Exception as e:
        print(f"❌ خطا در اتصال به تیکر: {e}")

    print("\n--- ۲. تست کندل‌های ۱۵ دقیقه ---")
    try:
        now = int(time.time())
        candles_url = "https://api.bitpin.org/api/v1/mkt/tv/history/"
        params = {
            "symbol": "BTC_USDT",
            "from": now - 43200,  # ۱۲ ساعت قبل
            "to": now,
            "resolution": "15"
        }
        res = requests.get(candles_url, params=params, headers=headers, timeout=10)
        print(f"کد وضعیت کندل‌ها: {res.status_code}")
        
        if res.status_code == 200:
            data = res.json()
            if data.get("s") == "ok" and "c" in data and len(data["c"]) > 0:
                print(f"✅ موفق! تعداد کندل‌ها: {len(data['c'])}")
                print(f"آخرین قیمت کلوز کندل: {data['c'][-1]}")
            else:
                print(f"⚠️ پاسخ سرور آمد اما ناقص است: {data}")
        else:
            print(f"❌ خطا در دریافت کندل‌ها: {res.status_code}")
    except Exception as e:
        print(f"❌ خطا در اتصال به کندل‌ها: {e}")

if __name__ == "__main__":
    test_connection()
