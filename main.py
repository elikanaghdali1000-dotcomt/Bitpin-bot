import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def check_multiple_coins():
    url = "https://api.bitpin.org/api/v1/mkt/tickers/"
    res = requests.get(url, headers=headers, timeout=10)
    
    if res.status_code == 200:
        data = res.json()
        print(f"✅ کلاً {len(data)} جفت‌ارز از بیت‌پین دریافت شد.\n")
        
        # چند ارز نمونه برای تست تتری و تومانی
        test_symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "DOGE_USDT", "BTC_IRT", "ETH_IRT"]
        
        # تبدیل لیست به دیکشنری برای جستجوی سریع با نماد
        ticker_dict = {item.get("symbol"): item.get("price") for item in data}
        
        for sym in test_symbols:
            price = ticker_dict.get(sym)
            if price:
                print(f"🔸 نماد {sym:10} -> قیمت: {price}")
            else:
                print(f"❌ نماد {sym:10} -> یافت نشد!")
    else:
        print(f"خطا در ارتباط: {res.status_code}")

if __name__ == "__main__":
    check_multiple_coins()
