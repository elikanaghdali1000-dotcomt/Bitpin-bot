import requests

BASE_URL = "https://api.bitpin.org/api/v1/mkt"


def get_candles(symbol="BTC_IRT", start=1735689600, end=1735776000, resolution="1h"):
    response = requests.get(
        f"{BASE_URL}/candles/",
        params={"symbol": symbol, "from": start, "to": end, "res": resolution},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_currencies():
    response = requests.get(f"{BASE_URL}/currencies/", timeout=20)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    print("Candles:", get_candles())
    print("Currencies:", get_currencies())
