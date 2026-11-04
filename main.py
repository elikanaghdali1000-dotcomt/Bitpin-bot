"""Minimal Bitpin candle API client based on the endpoint shown in IMG_9873.webp.

The screenshot documents GET https://api.bitpin.org/api/v1/mkt/candles
with query parameters: symbol, from, to, and res (not resolution/count).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any

import requests

CANDLES_URL = "https://api.bitpin.org/api/v1/mkt/candles"


def get_candles(
    symbol: str,
    from_ts: int,
    to_ts: int,
    res: str = "1h",
    *,
    timeout: float = 30.0,
) -> Any:
    """Fetch candle data for a market using Bitpin's documented query names."""
    params = {
        "symbol": symbol,
        "from": from_ts,
        "to": to_ts,
        "res": res,
    }
    response = requests.get(CANDLES_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def startup_health_verification(
    *,
    bitpin_symbol: str = "BTC_IRT",
    binance_symbol: str = "BTCUSDT",
    timeout: float = 15.0,
) -> dict[str, bool]:
    """Check that both exchanges return market data, then send one Telegram report.

    Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment.
    Call this once during bot startup; it does not schedule periodic checks.
    """
    now = int(time.time())
    results: dict[str, bool] = {"Bitpin": False, "Binance": False}
    details: dict[str, str] = {}

    try:
        response = requests.get(
            CANDLES_URL,
            params={"symbol": bitpin_symbol, "from": now - 3600, "to": now, "res": "1m"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        has_data = bool(payload)
        if isinstance(payload, dict):
            has_data = any(bool(payload.get(key)) for key in ("data", "results", "candles"))
        results["Bitpin"] = has_data
        details["Bitpin"] = "داده دریافت شد" if has_data else "پاسخ بدون داده"
    except Exception as exc:
        details["Bitpin"] = f"خطا: {type(exc).__name__}: {exc}"

    try:
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": binance_symbol, "interval": "1m", "limit": 1},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        has_data = isinstance(payload, list) and len(payload) > 0
        results["Binance"] = has_data
        details["Binance"] = "داده دریافت شد" if has_data else "پاسخ بدون داده"
    except Exception as exc:
        details["Binance"] = f"خطا: {type(exc).__name__}: {exc}"

    report = (
        "گزارش بررسی سلامت هنگام راه‌اندازی ربات\n"
        f"Bitpin ({bitpin_symbol}): {'✅' if results['Bitpin'] else '❌'} {details['Bitpin']}\n"
        f"Binance ({binance_symbol}): {'✅' if results['Binance'] else '❌'} {details['Binance']}"
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to send the startup report")
    telegram_response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": report},
        timeout=timeout,
    )
    telegram_response.raise_for_status()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Bitpin market candles")
    parser.add_argument("symbol", nargs="?", help="Market symbol, e.g. BTC_IRT")
    parser.add_argument("--startup-health", action="store_true", help="Check Bitpin and Binance once and send one Telegram report")
    parser.add_argument("from_ts", nargs="?", type=int, help="Start Unix timestamp in seconds")
    parser.add_argument("to_ts", nargs="?", type=int, help="End Unix timestamp in seconds")
    parser.add_argument("--res", default="1h", help="Candle resolution, e.g. 1h")
    args = parser.parse_args()

    if args.startup_health:
        result = startup_health_verification()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.symbol is None or args.from_ts is None or args.to_ts is None:
        parser.error("symbol, from_ts, and to_ts are required unless --startup-health is used")
    result = get_candles(args.symbol, args.from_ts, args.to_ts, args.res)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
