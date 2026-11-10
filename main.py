"""تست مستقل دریافت قیمت BTC_USDT از بیت‌پین (یا از طریق Cloudflare Worker)."""
import requests

WORKER = "https://divine-wildflower-badc.elikanaghdali1000.workers.dev"
HOSTS  = [WORKER, "https://api.bitpin.org", "https://api.bitpin.ir"]
PATH   = "/api/v1/mkt/tickers/"
SYMBOL = "BTC_USDT"

HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://bitpin.ir",
    "Referer": "https://bitpin.ir/",
}

for host in HOSTS:
    url = host + PATH
    try:
        r = requests.get(url, headers=HDR, timeout=15)
        if r.status_code == 200:
            data = r.json()
            # اگر آرایه بود، دنبال BTC بگرد
            if isinstance(data, list):
                found = next((t.get("price") for t in data if str(t.get("symbol", "")).upper() == SYMBOL), None)
                if found:
                    print(f"✅ موفق از طریق {host} -> قیمت بیت‌کوین: {found}")
                    continue
            print(f"⚠️ پاسخ موفق ۲٠٠ بود اما ساختار داده متفاوت بود از {host}")
        else:
            print(f"❌ خطا {r.status_code} از {host}")
    except Exception as e:
        print(f"🚨 استثنا برای {host}: {e}")
