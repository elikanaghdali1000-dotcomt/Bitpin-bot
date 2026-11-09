import requests

# تست دریافت تیکرها از طریق ورکر کلودفلر
url = "https://divine-wildflower-badc.elikanaghdali1000.workers.dev/v1/mkt/tickers/"

try:
    response = requests.get(url, timeout=10)
    print("Status Code:", response.status_code)
    print("Response Preview:", response.text[:200])
except Exception as e:
    print("Error:", e)
