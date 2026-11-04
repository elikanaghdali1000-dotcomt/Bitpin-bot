import os
import time
import json
import logging
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# GLOBAL HEADERS FOR ANTI-BLOCK / BROWSER EMULATION
# ---------------------------------------------------------------------------
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"

# USD-M Futures API origins
BINANCE_FUTURES_BASES = tuple(base.strip().rstrip("/") for base in os.getenv(
    "BINANCE_FUTURES_BASES",
    "https://fapi.binance.com,https://fapi1.binance.com,https://fapi2.binance.com,https://fapi3.binance.com"
).split(",") if base.strip())
BINANCE_HTTP_PROXY = os.getenv("BINANCE_HTTP_PROXY", "").strip()
PRICE_CHECK_TOLERANCE_PCT = float(os.getenv("PRICE_CHECK_TOLERANCE_PCT", "2.5"))

# ---------------------------------------------------------------------------
# BITPIN TIKKER FETCH WITH FULL HEADERS
# ---------------------------------------------------------------------------
def fetch_bitpin_ticker_price(market_code):
    """Return the live Bitpin ticker price with robust anti-block headers."""
    urls = [
        f"{BASE_API}/v1/mkt/ticker/{market_code}/",
        f"{BASE_API}/v1/mkt/tickers/",
    ]
    for url in urls:
        try:
            response = requests.get(url, headers=BROWSER_HEADERS, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "ticker" in url:
                    # Single ticker format
                    price = data.get("price") or data.get("last_price")
                    if price:
                        return float(price)
                else:
                    # List of tickers format
                    results = data.get("results", [])
                    for item in results:
                        if item.get("market_code") == market_code or item.get("code") == market_code:
                            price = item.get("price") or item.get("last_price")
                            if price:
                                return float(price)
        except Exception as e:
            continue
    return None

# ---------------------------------------------------------------------------
# BITPIN CANDLES FETCH WITH FULL HEADERS
# ---------------------------------------------------------------------------
def fetch_bitpin_candles(market_code, resolution="1h", limit=100):
    """Fetch candlestick data from Bitpin with full browser headers."""
    try:
        now_ts = int(time.time())
        # Default lookback window based on limit and resolution
        from_ts = now_ts - (limit * 3600 if resolution == "1h" else limit * 60)
        params = {
            "symbol": market_code,
            "from": from_ts,
            "to": now_ts,
            "res": resolution
        }
        response = requests.get(OHLC_URL, params=params, headers=BROWSER_HEADERS, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        pass
    return None

# ---------------------------------------------------------------------------
# BINANCE USD-M FUTURES REQUEST WRAPPER
# ---------------------------------------------------------------------------
def _binance_get(path, params=None, timeout=10):
    """GET USD-M Futures public data with mirror rotation, full headers, and optional proxy."""
    proxies = ({"http": BINANCE_HTTP_PROXY, "https": BINANCE_HTTP_PROXY}
               if BINANCE_HTTP_PROXY else None)
    for base in BINANCE_FUTURES_BASES:
        try:
            url = base + path
            response = requests.get(
                url, 
                params=params or {}, 
                headers=BROWSER_HEADERS, 
                proxies=proxies, 
                timeout=timeout
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            continue
    return None
