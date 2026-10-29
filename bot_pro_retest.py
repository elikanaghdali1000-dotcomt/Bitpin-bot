#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Alert-only Bollinger Break & Retest scanner. No exchange orders are placed.

Required: pip install requests
Required environment variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
See the configuration comments below. Public Bitpin candle request/response
shape mirrors the other local bot files; verify it against the current exchange API.
"""

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

# ── Config (environment overrides) ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Bitpin public market-data endpoint pattern mirrored from existing local bots.
BITPIN_CANDLES_URL = os.getenv(
    "BITPIN_CANDLES_URL", "https://api.bitpin.org/api/v1/mkt/candles/"
).strip()
SYMBOLS = [s.strip() for s in os.getenv("SYMBOLS", "BTC_USDT,ETH_USDT").split(",") if s.strip()]
TIMEFRAME = os.getenv("TIMEFRAME", "15")  # Existing futures bots use 15-minute candles.
POLL_SECONDS = max(5, int(os.getenv("POLL_SECONDS", "60")))
FETCH_COUNT = max(60, int(os.getenv("FETCH_COUNT", "120")))
HTTP_TIMEOUT = max(3, int(os.getenv("HTTP_TIMEOUT", "15")))

BB_PERIOD = max(5, int(os.getenv("BB_PERIOD", "20")))
BB_STD = float(os.getenv("BB_STD", "2.0"))
VOLUME_PERIOD = max(2, int(os.getenv("VOLUME_PERIOD", "20")))
BREAKOUT_VOL_MULT = float(os.getenv("BREAKOUT_VOL_MULT", "1.5"))
PULLBACK_VOL_MAX_RATIO = float(os.getenv("PULLBACK_VOL_MAX_RATIO", "0.8"))
MAX_RETEST_CANDLES = max(1, int(os.getenv("MAX_RETEST_CANDLES", "8")))
RETEST_TOLERANCE_PCT = max(0.0, float(os.getenv("RETEST_TOLERANCE_PCT", "0.15"))) / 100.0
MIN_BREAKOUT_BODY_RATIO = min(1.0, max(0.0, float(os.getenv("MIN_BREAKOUT_BODY_RATIO", "0.55"))))
MIN_REJECTION_BODY_RATIO = min(1.0, max(0.0, float(os.getenv("MIN_REJECTION_BODY_RATIO", "0.30"))))
ATR_PERIOD = max(2, int(os.getenv("ATR_PERIOD", "14")))
STOP_ATR_BUFFER = max(0.0, float(os.getenv("STOP_ATR_BUFFER", "0.20")))
# Minimum tick distance is applied alongside ATR buffer; set per market if desired.
PRICE_TICK_SIZE = max(0.0, float(os.getenv("PRICE_TICK_SIZE", "0")))
TP1_R = float(os.getenv("TP1_R", "1.0"))
TP2_R = float(os.getenv("TP2_R", "2.0"))
DEDUPE_FILE = os.getenv("DEDUPE_FILE", "bot_pro_retest_alerts.json").strip()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                    format="%(asctime)s %(levelname)s | %(message)s")
LOG = logging.getLogger("break-retest")

@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class Candidate:
    symbol: str
    direction: str  # LONG / SHORT
    level: float    # upper/lower Bollinger band at the breakout
    breakout_time: int
    breakout_volume: float
    candles_waited: int = 0
    swing_low: float = math.inf
    swing_high: float = -math.inf

# Candidates are intentionally in-memory only; alerts are separately persisted.
pending: Dict[str, Candidate] = {}
last_processed: Dict[str, int] = {}
alerted_ids = set()


def _load_alert_ids() -> None:
    global alerted_ids
    if not DEDUPE_FILE or not os.path.isfile(DEDUPE_FILE):
        return
    try:
        with open(DEDUPE_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        alerted_ids = set(obj if isinstance(obj, list) else [])
        LOG.info("Loaded %d duplicate-protection keys", len(alerted_ids))
    except (OSError, ValueError) as exc:
        LOG.warning("Could not read dedupe file (%s); starting with empty alert history", exc)


def _save_alert_ids() -> None:
    if not DEDUPE_FILE:
        return
    try:
        # Keep the ledger bounded; keys are unique by symbol, direction, and candle time.
        recent = sorted(alerted_ids)[-5000:]
        temp = DEDUPE_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(recent, f)
        os.replace(temp, DEDUPE_FILE)
    except OSError as exc:
        LOG.warning("Could not persist duplicate-protection keys: %s", exc)


def _to_candle(item: Any) -> Optional[Candle]:
    """Accept Bitpin-style objects (time/open/... or t/o/...) and OHLC arrays.
    Array convention assumed: [timestamp, open, high, low, close, volume].
    """
    try:
        if isinstance(item, dict):
            get = item.get
            ts = get("time", get("t"))
            vals = (get("open", get("o")), get("high", get("h")),
                    get("low", get("l")), get("close", get("c")),
                    get("volume", get("v")))
        elif isinstance(item, (list, tuple)) and len(item) >= 6:
            ts, *vals = item[:6]
        else:
            return None
        ts = int(float(ts))
        # Normalize millisecond timestamps to seconds; datetime formatting needs seconds.
        if ts > 10**12:
            ts //= 1000
        o, h, l, c, v = map(float, vals)
        if not all(math.isfinite(x) for x in (o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0:
            return None
        if h < max(o, c, l) or l > min(o, c, h):
            return None
        return Candle(ts, o, h, l, c, v)
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_bitpin_candles(symbol: str, count: int = FETCH_COUNT) -> List[Candle]:
    """Isolated exchange adapter. The URL/params/field aliases mirror local code.
    Existing files use public GET params symbol, res, from, to and User-Agent; no
    authentication was present for candles. Override URL if Bitpin changes this.
    """
    now = int(time.time())
    try:
        minutes = int(TIMEFRAME) if TIMEFRAME.isdigit() else 15
    except ValueError:
        minutes = 15
    params = {"symbol": symbol, "res": TIMEFRAME,
              "from": now - count * minutes * 60 * 2, "to": now}
    response = requests.get(BITPIN_CANDLES_URL, params=params,
                            headers={"User-Agent": "Mozilla/5.0 bot-pro-retest/1.0"},
                            timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    # Existing bots expect list or {"output": list}; accept a few common wrappers too.
    if isinstance(payload, dict):
        for key in ("output", "data", "results", "candles"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError("Unexpected candle response: expected a list or list wrapper")
    candles = [c for row in payload if (c := _to_candle(row)) is not None]
    candles.sort(key=lambda c: c.timestamp)
    # Duplicate timestamps can appear in paginated or odd responses; keep last row.
    unique = {c.timestamp: c for c in candles}
    return [unique[t] for t in sorted(unique)]


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def indicators(candles: List[Candle], index: int):
    """Bollinger bands include the evaluated candle; volume average excludes it."""
    if index + 1 < BB_PERIOD or index < VOLUME_PERIOD:
        return None
    closes = [x.close for x in candles[index - BB_PERIOD + 1:index + 1]]
    middle = _mean(closes)
    variance = _mean([(x - middle) ** 2 for x in closes])
    sd = math.sqrt(variance)
    vol_avg = _mean([x.volume for x in candles[index - VOLUME_PERIOD:index]])
    if vol_avg <= 0:
        return None
    return middle - BB_STD * sd, middle + BB_STD * sd, vol_avg


def _atr(candles: List[Candle], index: int) -> float:
    start = max(1, index - ATR_PERIOD + 1)
    true_ranges = []
    for i in range(start, index + 1):
        c, prev = candles[i], candles[i - 1]
        true_ranges.append(max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close)))
    return _mean(true_ranges) if true_ranges else candles[index].high - candles[index].low


def _body_ratio(c: Candle) -> float:
    span = c.high - c.low
    return abs(c.close - c.open) / span if span > 0 else 0.0


def _is_strong_breakout(c: Candle, lower: float, upper: float, vol_avg: float):
    if c.volume <= BREAKOUT_VOL_MULT * vol_avg or _body_ratio(c) < MIN_BREAKOUT_BODY_RATIO:
        return None
    span = c.high - c.low
    if span <= 0:
        return None
    if c.close < lower and c.close < c.open and (c.close - c.low) / span <= 0.35:
        return "SHORT"
    if c.close > upper and c.close > c.open and (c.high - c.close) / span <= 0.35:
        return "LONG"
    return None


def _is_retest_rejection(c: Candle, candidate: Candidate, vol_avg: float,
                         previous_volume: float) -> bool:
    tol = candidate.level * RETEST_TOLERANCE_PCT
    low_touch = c.low <= candidate.level + tol and c.high >= candidate.level - tol
    if not (low_touch and c.high > c.low):
        return False
    span = c.high - c.low
    body_ok = _body_ratio(c) >= MIN_REJECTION_BODY_RATIO
    if candidate.direction == "LONG":
        # Keep the existing LONG retest: low-volume pullback and bullish reclaim.
        low_volume = c.volume <= vol_avg * PULLBACK_VOL_MAX_RATIO
        return (low_volume and c.low <= candidate.level + tol and c.close > candidate.level
                and c.close > c.open and (c.high - c.close) / span <= 0.45 and body_ok)
    # SHORT confirmation: strict red candle plus volume above both the configured
    # rolling baseline and the immediately preceding candle's volume.
    selling_confirmation = c.volume > vol_avg and c.volume > previous_volume
    return (selling_confirmation and c.high >= candidate.level - tol
            and c.close < candidate.level and c.close < c.open
            and (c.close - c.low) / span <= 0.45 and body_ok)


def _format_price(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def make_alert(symbol: str, candidate: Candidate, candle: Candle,
               candles: List[Candle], index: int) -> Optional[str]:
    entry = candle.close
    atr = _atr(candles, index)
    buffer = max(atr * STOP_ATR_BUFFER, PRICE_TICK_SIZE)
    if candidate.direction == "LONG":
        stop = candidate.swing_low - buffer
        risk = entry - stop
        if risk <= 0:
            return None
        tp1, tp2 = entry + TP1_R * risk, entry + TP2_R * risk
    else:
        stop = candidate.swing_high + buffer
        risk = stop - entry
        if risk <= 0:
            return None
        tp1, tp2 = entry - TP1_R * risk, entry - TP2_R * risk
    dt = datetime.fromtimestamp(candle.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    side = "🟢 LONG / خرید" if candidate.direction == "LONG" else "🔴 SHORT / فروش"
    return ("⚠️ ALERT ONLY — Break & Retest (اطلاع‌رسانی؛ بدون سفارش)\n"
            f"Symbol: {symbol} | TF: {TIMEFRAME}m | {side}\n"
            f"Breakout/retest candle: {dt}\nBroken Bollinger level: {_format_price(candidate.level)}\n"
            f"Entry (rejection close): {_format_price(entry)}\n"
            f"Structural stop: {_format_price(stop)} (pullback swing + buffer)\n"
            f"TP1 ({TP1_R:g}R): {_format_price(tp1)} | TP2 ({TP2_R:g}R): {_format_price(tp2)}\n"
            f"Risk distance: {_format_price(risk)} | ATR buffer: {_format_price(buffer)}\n"
            "Educational signal only; not financial advice. Risk is real; no profit is guaranteed.")


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        LOG.error("Telegram env missing: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        result = r.json()
        if not result.get("ok", False):
            LOG.error("Telegram API rejected message: %s", result)
            return False
        return True
    except (requests.RequestException, ValueError) as exc:
        LOG.warning("Telegram send failed: %s", exc)
        return False


def process_closed_candle(symbol: str, candles: List[Candle], index: int) -> None:
    candle = candles[index]
    key = f"{symbol}|{candle.timestamp}"
    if last_processed.get(symbol) == candle.timestamp:
        return
    last_processed[symbol] = candle.timestamp
    ind = indicators(candles, index)
    if ind is None:
        return
    lower, upper, vol_avg = ind
    candidate = pending.get(symbol)

    if candidate:
        candidate.candles_waited += 1
        candidate.swing_low = min(candidate.swing_low, candle.low)
        candidate.swing_high = max(candidate.swing_high, candle.high)
        # Invalidate if price closes back through the breakout origin, or expire after N bars.
        failed = ((candidate.direction == "LONG" and candle.close < candidate.level * (1 - RETEST_TOLERANCE_PCT))
                  or (candidate.direction == "SHORT" and candle.close > candidate.level * (1 + RETEST_TOLERANCE_PCT)))
        if failed or candidate.candles_waited > MAX_RETEST_CANDLES:
            pending.pop(symbol, None)
            LOG.info("%s candidate expired/invalidated (%s)", symbol, "باطل شد" if failed else "مهلت تمام شد")
            candidate = None
        elif _is_retest_rejection(candle, candidate, vol_avg, candles[index - 1].volume):
            alert_id = f"{key}|{candidate.direction}|{candidate.breakout_time}"
            text = make_alert(symbol, candidate, candle, candles, index)
            if text and alert_id not in alerted_ids:
                if send_telegram(text):
                    alerted_ids.add(alert_id)
                    _save_alert_ids()
                    LOG.info("%s %s alert sent / هشدار ارسال شد", symbol, candidate.direction)
                else:
                    LOG.warning("Alert not sent; candidate retained to retry on a later qualifying candle")
                    # Retain candidate, but avoid retrying a Telegram failure on the same candle.
                    return
            pending.pop(symbol, None)
            return

    if candidate is None:
        direction = _is_strong_breakout(candle, lower, upper, vol_avg)
        if direction:
            level = upper if direction == "LONG" else lower
            pending[symbol] = Candidate(symbol, direction, level, candle.timestamp, candle.volume,
                                        swing_low=math.inf, swing_high=-math.inf)
            LOG.info("%s breakout %s; waiting up to %d candles for retest / شکست؛ منتظر retest",
                     symbol, direction, MAX_RETEST_CANDLES)


def scan_symbol(symbol: str) -> None:
    candles = fetch_bitpin_candles(symbol)
    # Existing bots treat df[-2] as the last fully closed bar. Follow that convention.
    if len(candles) < max(BB_PERIOD, VOLUME_PERIOD) + 3:
        LOG.info("%s not enough candles (%d); need more history", symbol, len(candles))
        return
    closed_index = len(candles) - 2
    closed = candles[closed_index]
    previous = last_processed.get(symbol)
    if previous is None:
        # On startup process only the latest closed candle, not old history.
        process_closed_candle(symbol, candles, closed_index)
    elif closed.timestamp > previous:
        # If polling missed bars, process available closed candles sequentially to honor N bars.
        start = next((i for i, c in enumerate(candles[:closed_index + 1]) if c.timestamp > previous), closed_index)
        for i in range(start, closed_index + 1):
            process_closed_candle(symbol, candles, i)
    elif closed.timestamp < previous:
        LOG.warning("%s candle history moved backwards; resetting per-symbol cursor", symbol)
        last_processed.pop(symbol, None)
        process_closed_candle(symbol, candles, closed_index)


def main() -> None:
    if not SYMBOLS:
        raise SystemExit("Set SYMBOLS, e.g. BTC_USDT,ETH_USDT")
    _load_alert_ids()
    LOG.info("Break & Retest scanner started | symbols=%s | TF=%sm | poll=%ss",
             ",".join(SYMBOLS), TIMEFRAME, POLL_SECONDS)
    LOG.info("Telegram credentials are read only from TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    while True:
        cycle_start = time.monotonic()
        for symbol in SYMBOLS:
            try:
                scan_symbol(symbol)
            except requests.RequestException as exc:
                LOG.warning("%s candle API/network error: %s", symbol, exc)
            except (ValueError, KeyError, TypeError) as exc:
                LOG.warning("%s bad candle response/data: %s", symbol, exc)
            except Exception:
                LOG.exception("Unexpected scan error for %s", symbol)
        delay = max(1.0, POLL_SECONDS - (time.monotonic() - cycle_start))
        time.sleep(delay)

if __name__ == "__main__":
    main()
