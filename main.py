import time
import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def get_official_candles(symbol, timeframe="15m"):
    now = int(time.time())
    url = "https://api.bitpin.org/api/v1/mkt/candles/"
    params = {
        "symbol": symbol,
        "from": now - 43200,  # ۱۲ ساعت قبل
        "to": now,
        "res": timeframe      # 15m
    }
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            # بیت‌پین پاسخ را به صورت لیست مستقیم از کندل‌ها برمی‌گرداند
            if isinstance(data, list) and len(data) > 0:
                last_c = data[-1]
                print(f"✅ [{symbol}] تعداد کندل: {len(data)} | کلوز: {last_c.get('close')} | حجم: {last_c.get('volume')}")
                return True
            else:
                print(f"⚠️ [{symbol}] پاسخ خالی بود (ممکن است این نماد در بازار تتری موجود نباشد).")
        else:
            print(f"❌ [{symbol}] خطا با کد: {res.status_code}")
    except Exception as e:
        print(f"❌ [{symbol}] خطای شبکه: {e}")
    return False

if __name__ == "__main__":
    print("--- تست دریافت کندل از اندپوینت رسمی بیت‌پین ---\n")
    # ارزهایی که قبلاً خطا دادند را تست می‌کنیم:
    test_coins = ["BTC_USDT", "ETH_USDT", "PEPE_USDT", "SHIB_USDT", "FET_USDT", "PEPE_IRT", "SHIB_IRT"]
    
    for coin in test_coins:
        get_official_candles(coin)
        time.sleep(0.3)
