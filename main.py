import requests

url = "https://api.bitpin.org/v1/mkt/markets/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

res = requests.get(url, headers=headers)
print("Status Code:", res.status_code)
print("Response preview:", res.text[:100])
