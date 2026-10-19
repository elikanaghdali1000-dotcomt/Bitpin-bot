import time
import requests

# هدر استاندارد برای جلوگیری از بلاک شدن توسط سرور بیت‌پین
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def test_connection():
    print("--- ۱. بررسی قیمت لحظه‌ای (BTC_USDT) ---")
    try:
        ticker_url = "https://api.bitpin.org/v1/mkt/tickers/"
        res = requests.get(ticker_url, headers=headers, timeout=10)
        print(f"وضعیت درخواست تیکر: {res.status_code}")
        
        if res.status_code == 200:
            data = res.json()
            # پیدا کردن بیت‌کوین تتر
            btc_data = next((item for item in data if item.get("symbol") == "BTC_USDT"), None)
            if btc_data:
                print(f"✅ قیمت آخرین معامله بیت‌کوین: {btc_data.get('price')} USDT")
            else:
                print("⚠️ تیکر باز شد ولی جفت ارز BTC_USDT پیدا نشد.")
        else:
            print(f"❌ خطا در خواندن قیمت: کد وضعیت {res.status_code}")
    except Exception as e:
        print(f"❌ خطای اتصال به تیکر: {e}")

    print("\n--- ۲. بررسی دریافت کندل‌های ۱۵ دقیقه (BTC_USDT) ---")
    try:
        now = int(time.time())
        candles_url = "https://api.bitpin.org/api/v1/mkt/tv/history/"
        params = {
            "symbol": "BTC_USDT",
            "from": now - 43200,  # ۱۲ ساعت قبل
            "to": now,
            "resolution": "15"    # کندل‌های ۱۵ دقیقه
        }
        res = requests.get(candles_url, params=params, headers=headers, timeout=10)
        print(f"وضعیت درخواست کندل: {res.status_code}")
        
        if res.status_code == 200:
            data = res.json()
            if data.get("s") == "ok" and "c" in data and len(data["c"]) > 0:
                total_candles = len(data["c"])
                last_close = data["c"][-1]
                last_high = data["h"][-1]
                last_low = data["l"][-1]
                print(f"✅ کندل‌ها با موفقیت دریافت شدند!")
                print(f"تعداد کندل‌های گرفته‌شده: {total_candles}")
                print(f"آخرین کندل -> سقف: {last_high} | کف: {last_low} | قیمت بسته‌شدن: {last_close}")
            else:
                print(f"⚠️ پاسخ سرور آمد اما دیتا معتبر نیست: {data}")
        else:
            print(f"❌ خطا در دریافت کندل: کد وضعیت {res.status_code}")
    except Exception as e:
        print(f"❌ خطای اتصال به کندل‌ها: {e}")

if __name__ == "__main__":
    test_connection()
