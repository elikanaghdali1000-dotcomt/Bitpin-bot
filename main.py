# -*- coding: utf-8 -*-
"""
=====================================================================
 Bitpin Leveraged 15m Multi-Strategy Bot  (v2 - hardened)
=====================================================================
استراتژی‌ها:
  1) Sensi            : در ۲ دقیقه آخر کندل (دقیقه ۱۳ و ۱۴ از ۱۵)
  2) Pullback  Bull/Bear : دقیقاً روی بسته‌شدن کندل (دقیقه ۰ و ۱)
  3) Break&Retest Bull/Bear : دقیقاً روی بسته‌شدن کندل (دقیقه ۰ و ۱)

نکات مهم پیاده‌سازی:
  - فقط کندل‌های «بسته‌شده» برای اندیکاتورها و سیگنال‌های کندل‌محور استفاده می‌شوند.
  - کندل در حال تشکیل بیت‌پین حذف می‌شود (منبع اصلی باگ نسخه قبلی).
  - فیلتر روند BTC از کندل‌های بسته‌شده محاسبه می‌شود.
  - ضدتکرار بر اساس (symbol, candle_ts, strategy) و cooldown نماد.
  - مدیریت ریسک ATR-based با SL/TP1/TP2 و محاسبه حجم پوزیشن.
=====================================================================
"""
import os
import csv
import json
import time
import math
import signal
import logging
import threading
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
import pandas as pd

# =====================================================================
# 1) تنظیمات (همه از طریق متغیر محیطی قابل تغییرند)
# =====================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DRY_RUN = os.getenv("DRY_RUN", "1") == "1"          # 1 = بدون معامله واقعی، فقط سیگنال
TIMEFRAME = os.getenv("TIMEFRAME", "15m")
PERIOD = 900                                        # ثانیه
CANDLE_COUNT = int(os.getenv("CANDLE_COUNT", "200"))  # حداقل ۲۰۰ برای EMA200

# --- سرمایه و ریسک ---
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY", "1000"))   # موجودی حساب (USDT)
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0"))
LEVERAGE = float(os.getenv("LEVERAGE", "3"))
FEE_RATE = float(os.getenv("FEE_RATE", "0.002"))               # کارمزد هر طرف (۰.۲٪)
MIN_TP_FEE_MULT = float(os.getenv("MIN_TP_FEE_MULT", "1.2"))   # TP1 حداقل چند برابر کارمزد رفت‌وبرگشت
MIN_RR = float(os.getenv("MIN_RR", "1.8"))                     # حداقل نسبت ریوارد/ریسک
ATR_SL_MULT = float(os.getenv("ATR_SL_MULT", "1.5"))
ATR_TP1_MULT = float(os.getenv("ATR_TP1_MULT", "3.0"))
ATR_TP2_MULT = float(os.getenv("ATR_TP2_MULT", "4.5"))

# --- فیلترها ---
BB_WIDTH_MIN = float(os.getenv("BB_WIDTH_MIN", "0.30"))   # درصد؛ کمتر از این = فشردگی بیش از حد
BB_WIDTH_MAX = float(os.getenv("BB_WIDTH_MAX", "6.0"))    # بیشتر از این = نویز شدید
VOLUME_DRY_RATIO = float(os.getenv("VOLUME_DRY_RATIO", "0.75"))
MIN_VOLUME_USDT = float(os.getenv("MIN_VOLUME_USDT", "0"))  # 0 = غیرفعال
SYMBOL_COOLDOWN = int(os.getenv("SYMBOL_COOLDOWN", "1800"))  # ۳۰ دقیقه
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", "3600"))  # کف ۱ ساعت بین سیگنال‌های نماد

# --- نمادها (لیست دستی؛ با SYMBOLS="A_USDT,B_USDT" قابل تغییر) ---
DEFAULT_SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT",
    "ADA_USDT", "BNB_USDT", "AVAX_USDT", "LINK_USDT", "DOT_USDT",
    "TRX_USDT", "LTC_USDT", "BCH_USDT", "NEAR_USDT", "SUI_USDT",
    "APT_USDT", "ARB_USDT", "OP_USDT", "TON_USDT", "PEPE_USDT",
    "SHIB_USDT", "WIF_USDT", "ENA_USDT", "FET_USDT", "INJ_USDT",
]
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()] or DEFAULT_SYMBOLS

# --- فایل‌ها ---
STATE_FILE = os.getenv("STATE_FILE", "signal_tracker.json")
OUTCOME_FILE = os.getenv("OUTCOME_FILE", "signal_outcomes.csv")
LOG_FILE = os.getenv("LOG_FILE", "bot.log")

# =====================================================================
# 2) لاگ
# =====================================================================
logger = logging.getLogger("bitpin")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
_fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
logger.handlers = [_fh, _sh]


def log(msg, level="info"):
    getattr(logger, level, logger.info)(msg)


# =====================================================================
# 3) کلاینت بیت‌پین (Mirror hosts + retry + rate limit)
# =====================================================================
BITPIN_HOSTS = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org",
    "https://api.bitpin.com",
]
MARKETS_PATH = "/api/v1/mkt/markets/"
CANDLES_PATH = "/api/v1/mkt/candles/"

RES_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
RES_ALIASES = {
    "60": "1h", "1H": "1h", "h1": "1h",
    "240": "4h", "4H": "4h", "h4": "4h",
    "D": "1d", "1D": "1d", "d": "1d",
    "2h": "1h", "6h": "4h", "12h": "4h", "1w": "1d",
}

HEADERS_FULL = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Referer": "https://bitpin.ir/",
}
HEADERS_MIN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

SESSION = requests.Session()
_HOST_CACHE = {"bitpin": None, "time": 0.0}
_HOST_TTL = 600
_LAST_REQ = {"ts": 0.0}
_MIN_REQ_GAP = float(os.getenv("MIN_REQ_GAP", "0.25"))   # فاصله حداقلی بین درخواست‌ها


def _throttle():
    gap = time.time() - _LAST_REQ["ts"]
    if gap < _MIN_REQ_GAP:
        time.sleep(_MIN_REQ_GAP - gap)
    _LAST_REQ["ts"] = time.time()


def _get_json(path, params=None, timeout=15, retries=2):
    """درخواست GET با چرخش میزبان و دو پروفایل هدر. برمی‌گرداند (data, host)."""
    ordered = list(BITPIN_HOSTS)
    cached = _HOST_CACHE.get("bitpin")
    if cached and (time.time() - _HOST_CACHE["time"] < _HOST_TTL) and cached in ordered:
        ordered.remove(cached)
        ordered.insert(0, cached)

    last_err = None
    for host in ordered:
        for attempt in range(retries):
            hdrs = HEADERS_FULL if attempt == 0 else HEADERS_MIN
            try:
                _throttle()
                r = SESSION.get(host + path, params=params, headers=hdrs, timeout=timeout)
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:
                        last_err = f"invalid JSON from {host}"
                        log(f"[HTTP] {host} -> 200 but invalid JSON", "warning")
                        break
                    _HOST_CACHE["bitpin"] = host
                    _HOST_CACHE["time"] = time.time()
                    return data, host
                last_err = f"HTTP {r.status_code} from {host}"
                log(f"[HTTP] {host}{path} -> {r.status_code}", "warning")
                if r.status_code in (404, 451):
                    break
                time.sleep(0.6)
            except Exception as e:
                last_err = f"{host}: {type(e).__name__}: {e}"
                log(f"[HTTP] {host} failed: {type(e).__name__}", "warning")
                time.sleep(0.6)
    log(f"[HTTP] all hosts failed for {path}: {last_err}", "error")
    return None, None


def normalize_resolution(res):
    res = str(res).strip()
    if res in RES_SECONDS:
        return res
    return RES_ALIASES.get(res, TIMEFRAME)


def fetch_markets():
    data, host = _get_json(MARKETS_PATH, params={"page": 1})
    if data is None:
        return []
    markets = data if isinstance(data, list) else data.get("results", data.get("data", []))
    if not isinstance(markets, list):
        return []
    log(f"[Markets] {len(markets)} markets from {host}")
    return markets


def tradable_symbols():
    """نمادهای مجاز = لیست دستی ∩ نمادهای قابل معامله در بیت‌پین."""
    markets = fetch_markets()
    if not markets:
        log("[Markets] empty -> using default symbol list", "warning")
        return list(SYMBOLS)
    ok = set()
    for m in markets:
        if not isinstance(m, dict):
            continue
        sym = m.get("symbol") or m.get("code")
        if not sym:
            continue
        if m.get("tradable", True) is False or m.get("suspended", False) is True:
            continue
        ok.add(str(sym).upper())
    allowed = [s for s in SYMBOLS if s in ok]
    missing = [s for s in SYMBOLS if s not in ok]
    if missing:
        log(f"[Markets] not tradable / missing: {', '.join(missing[:10])}", "warning")
    log(f"[Markets] {len(allowed)}/{len(SYMBOLS)} symbols active")
    return allowed or list(SYMBOLS)


def fetch_candles(symbol, resolution=TIMEFRAME, count=CANDLE_COUNT, include_forming=False):
    """
    GET /api/v1/mkt/candles/?symbol=...&res=15m&from=<unix>&to=<unix>
    نکته: پارامتر limit پشتیبانی نمی‌شود (HTTP 500) -> بازه از from/to ساخته می‌شود.
    """
    res = normalize_resolution(resolution)
    step = RES_SECONDS[res]
    now = int(time.time())
    params = {"symbol": symbol, "res": res, "from": now - int(count) * step, "to": now}

    data, _ = _get_json(CANDLES_PATH, params=params)
    if data is None:
        return None
    rows = data if isinstance(data, list) else data.get("results", [])
    if not rows:
        log(f"[Candles] empty for {symbol} ({res})", "warning")
        return None

    df = pd.DataFrame(rows)
    # بیت‌پین هم time (ms) و هم ts (s) می‌دهد -> فقط یکی بماند
    if "time" in df.columns and "ts" in df.columns:
        df = df.drop(columns=["ts"])
    df = df.rename(columns={
        "time": "timestamp", "ts": "timestamp",
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })

    need = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in need) or "timestamp" not in df.columns:
        log(f"[Candles] unexpected schema {symbol}: {list(df.columns)}", "error")
        return None

    for c in need + ["timestamp"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if df["timestamp"].max() < 10_000_000_000:      # ثانیه -> میلی‌ثانیه
        df["timestamp"] = df["timestamp"] * 1000

    df = (df.dropna(subset=need + ["timestamp"])
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True))

    if "resolution" in df.columns and not df.empty:
        got = str(df["resolution"].iloc[-1])
        if got != res:
            log(f"[Candles] {symbol}: requested {res}, server returned {got}", "warning")

    # حذف کندل در حال تشکیل (باگ اصلی نسخه قبلی)
    if not include_forming and not df.empty:
        last_ts = int(df["timestamp"].iloc[-1] / 1000)
        if now < last_ts + step:
            df = df.iloc[:-1].reset_index(drop=True)

    if df.empty:
        return None
    return df


# =====================================================================
# 4) اندیکاتورها
# =====================================================================
def add_indicators(df):
    if df is None or len(df) < 30:
        return None
    df = df.copy()
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

    df["EMA21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA50"] = close.ewm(span=50, adjust=False).mean()
    df["EMA200"] = close.ewm(span=200, adjust=False).mean()
    df["SMA20"] = close.rolling(20).mean()
    std20 = close.rolling(20).std(ddof=0)
    df["BB_Upper"] = df["SMA20"] + 2 * std20
    df["BB_Lower"] = df["SMA20"] - 2 * std20
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["SMA20"] * 100

    # RSI (Wilder)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI"] = (100 - 100 / (1 + rs)).fillna(50)

    # ATR (Wilder)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # حجم
    df["Vol_SMA20"] = vol.rolling(20).mean()
    df["Vol_Ratio"] = vol / df["Vol_SMA20"].replace(0, pd.NA)

    # ADX ساده‌شده (Wilder)
    up = high.diff()
    dn = -low.diff()
    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_dm[(up > dn) & (up > 0)] = up
    minus_dm[(dn > up) & (dn > 0)] = dn
    atr = df["ATR"].replace(0, float("nan"))
    plus_di = (100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr).astype(float)
    minus_di = (100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr).astype(float)
    di_sum = (plus_di + minus_di).replace(0, float("nan"))
    dx = ((plus_di - minus_di).abs() / di_sum * 100).astype(float)
    df["ADX"] = dx.ewm(alpha=1 / 14, adjust=False).mean().fillna(0)

    return df


# =====================================================================
# 5) فیلتر رژیم بازار (BTC) از کندل‌های بسته‌شده
# =====================================================================
_BTC_CACHE = {"ts": 0.0, "ok": True, "bias": "neutral"}


def btc_regime(force=False):
    if not force and time.time() - _BTC_CACHE["ts"] < 300:
        return _BTC_CACHE

    ok, bias = True, "neutral"
    df = fetch_candles("BTC_USDT", "1h", 260)
    if df is None:
        df = fetch_candles("BTC_IRT", "1h", 260)
    if df is not None:
        df = add_indicators(df)
        if df is not None and len(df) > 210:
            last = df.iloc[-1]
            if pd.notna(last["EMA50"]) and pd.notna(last["EMA200"]):
                if last["EMA50"] > last["EMA200"] and last["Close"] > last["EMA50"]:
                    bias = "bull"
                elif last["EMA50"] < last["EMA200"] and last["Close"] < last["EMA50"]:
                    bias = "bear"
                ok = bias != "bear"

    _BTC_CACHE.update({"ts": time.time(), "ok": ok, "bias": bias})
    log(f"[Regime] BTC bias={bias} (longs_allowed={ok})")
    return _BTC_CACHE


# =====================================================================
# 6) استراتژی‌ها
# =====================================================================
def _num(v, default=float("nan")):
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def signal_sensi(symbol, df_closed, df_live):
    """خشکی حجم در کف باند بولینگر + برگشت قیمت — فقط در ۲ دقیقه آخر کندل."""
    if df_live is None or len(df_live) < 30:
        return None
    d = add_indicators(df_live)
    if d is None:
        return None
    cur, prev = d.iloc[-1], d.iloc[-2]
    if pd.isna(cur["BB_Lower"]) or pd.isna(cur["Vol_Ratio"]):
        return None
    if cur["Vol_Ratio"] > VOLUME_DRY_RATIO:
        return None
    if not (cur["Low"] <= cur["BB_Lower"]):
        return None
    if not (cur["Close"] > prev["Close"] and cur["Close"] > cur["Open"]):
        return None
    if cur["RSI"] > 55:
        return None
    return {
        "strategy": "sensi",
        "side": "long",
        "entry": _num(cur["Close"]),
        "reason": f"خشکی حجم (نسبت {cur['Vol_Ratio']:.2f}) + لمس باند پایین + کندل صعودی",
        "atr": _num(cur["ATR"]),
        "rsi": _num(cur["RSI"]),
        "adx": _num(cur["ADX"]),
        "bb_width": _num(cur["BB_Width"]),
        "vol_ratio": _num(cur["Vol_Ratio"]),
        "ema_fast": _num(cur["EMA50"]),
        "ema_slow": _num(cur["EMA200"]),
        "candle_ts": int(cur["timestamp"] / 1000),
    }


def signal_pullback(symbol, d):
    """پولبک به SMA20 در جهت روند (بولیش/بیریش) روی کندل بسته‌شده."""
    if d is None or len(d) < 3:
        return None
    cur, prev = d.iloc[-1], d.iloc[-2]
    if pd.isna(cur["SMA20"]) or pd.isna(cur["EMA200"]) or pd.isna(cur["RSI"]):
        return None
    rsi = cur["RSI"]

    # بولیش: روند صعودی، برگشت به SMA20 و بسته‌شدن بالای آن
    if (cur["Close"] > cur["EMA200"] and cur["EMA50"] > cur["EMA200"]
            and prev["Low"] <= cur["SMA20"] and cur["Close"] > cur["SMA20"]
            and 38 <= rsi <= 62 and cur["Close"] > cur["Open"]):
        return {
            "strategy": "pullback_bull", "side": "long", "entry": _num(cur["Close"]),
            "reason": f"پولبک صعودی به SMA20 و بازگشت (RSI {rsi:.1f})",
            "atr": _num(cur["ATR"]), "rsi": rsi, "adx": _num(cur["ADX"]),
            "bb_width": _num(cur["BB_Width"]), "vol_ratio": _num(cur["Vol_Ratio"]),
            "ema_fast": _num(cur["EMA50"]), "ema_slow": _num(cur["EMA200"]),
            "candle_ts": int(cur["timestamp"] / 1000),
        }

    # بیریش: روند نزولی، پولبک به SMA20 و رد شدن
    if (cur["Close"] < cur["EMA200"] and cur["EMA50"] < cur["EMA200"]
            and prev["High"] >= cur["SMA20"] and cur["Close"] < cur["SMA20"]
            and 38 <= rsi <= 62 and cur["Close"] < cur["Open"]):
        return {
            "strategy": "pullback_bear", "side": "short", "entry": _num(cur["Close"]),
            "reason": f"پولبک نزولی به SMA20 و رد شدن (RSI {rsi:.1f})",
            "atr": _num(cur["ATR"]), "rsi": rsi, "adx": _num(cur["ADX"]),
            "bb_width": _num(cur["BB_Width"]), "vol_ratio": _num(cur["Vol_Ratio"]),
            "ema_fast": _num(cur["EMA50"]), "ema_slow": _num(cur["EMA200"]),
            "candle_ts": int(cur["timestamp"] / 1000),
        }
    return None


def signal_break_retest(symbol, d):
    """شکست سطح (سقف/کف ۲۰ کندل) و ریتست موفق روی کندل بسته‌شده."""
    if d is None or len(d) < 25:
        return None
    cur = d.iloc[-1]
    window = d.iloc[-22:-2]
    hi, lo = _num(window["High"].max()), _num(window["Low"].min())
    if not (math.isfinite(hi) and math.isfinite(lo)):
        return None
    if pd.isna(cur["ATR"]) or pd.isna(cur["RSI"]):
        return None
    tol = cur["ATR"] * 0.35

    # بولیش: شکست سقف، ریتست از بالا، بسته‌شدن بالای سطح
    if (cur["Close"] > hi and cur["Low"] <= hi + tol and cur["Close"] > cur["Open"]
            and cur["Vol_Ratio"] >= 1.0 and cur["RSI"] < 75):
        return {
            "strategy": "retest_bull", "side": "long", "entry": _num(cur["Close"]),
            "reason": f"شکست و ریتست سقف {hi:.6g} با حجم {cur['Vol_Ratio']:.2f}x",
            "atr": _num(cur["ATR"]), "rsi": _num(cur["RSI"]), "adx": _num(cur["ADX"]),
            "bb_width": _num(cur["BB_Width"]), "vol_ratio": _num(cur["Vol_Ratio"]),
            "ema_fast": _num(cur["EMA50"]), "ema_slow": _num(cur["EMA200"]),
            "candle_ts": int(cur["timestamp"] / 1000),
        }

    # بیریش: شکست کف، ریتست از پایین، بسته‌شدن زیر سطح
    if (cur["Close"] < lo and cur["High"] >= lo - tol and cur["Close"] < cur["Open"]
            and cur["Vol_Ratio"] >= 1.0 and cur["RSI"] > 25):
        return {
            "strategy": "retest_bear", "side": "short", "entry": _num(cur["Close"]),
            "reason": f"شکست و ریتست کف {lo:.6g} با حجم {cur['Vol_Ratio']:.2f}x",
            "atr": _num(cur["ATR"]), "rsi": _num(cur["RSI"]), "adx": _num(cur["ADX"]),
            "bb_width": _num(cur["BB_Width"]), "vol_ratio": _num(cur["Vol_Ratio"]),
            "ema_fast": _num(cur["EMA50"]), "ema_slow": _num(cur["EMA200"]),
            "candle_ts": int(cur["timestamp"] / 1000),
        }
    return None


# =====================================================================
# 7) اعتبارسنجی، امتیازدهی و مدیریت ریسک
# =====================================================================
def passes_filters(sig):
    if sig is None:
        return False
    entry, atr = sig["entry"], sig["atr"]
    if not (math.isfinite(entry) and entry > 0 and math.isfinite(atr) and atr > 0):
        return False
    bw = sig.get("bb_width", float("nan"))
    if math.isfinite(bw) and not (BB_WIDTH_MIN <= bw <= BB_WIDTH_MAX):
        return False
    if MIN_VOLUME_USDT > 0:
        # حجم کندل به USDT تقریبی
        if sig.get("vol_usdt", 0) < MIN_VOLUME_USDT:
            return False
    return True


def score_signal(sig, regime_bias):
    score = 50.0
    side = sig["side"]
    if regime_bias == "bull" and side == "long":
        score += 12
    if regime_bias == "bear" and side == "short":
        score += 12
    if regime_bias not in ("bull", "bear"):
        score -= 5

    ef, es = sig.get("ema_fast", float("nan")), sig.get("ema_slow", float("nan"))
    if math.isfinite(ef) and math.isfinite(es):
        if (side == "long" and ef > es) or (side == "short" and ef < es):
            score += 10
        else:
            score -= 8

    adx = sig.get("adx", 0)
    if math.isfinite(adx):
        score += min(10, max(-6, (adx - 18) * 0.6))

    vr = sig.get("vol_ratio", 1)
    if math.isfinite(vr):
        if side == "long" and vr >= 1.2:
            score += 6
        if sig["strategy"] == "sensi" and vr <= 0.6:
            score += 6

    score = max(0.0, min(100.0, score))
    grade = "A" if score >= 78 else "B" if score >= 65 else "C"
    return round(score, 1), grade


def build_levels(sig):
    entry, atr, side = sig["entry"], sig["atr"], sig["side"]
    if side == "long":
        sl = entry - ATR_SL_MULT * atr
        tp1 = entry + ATR_TP1_MULT * atr
        tp2 = entry + ATR_TP2_MULT * atr
        risk = entry - sl
    else:
        sl = entry + ATR_SL_MULT * atr
        tp1 = entry - ATR_TP1_MULT * atr
        tp2 = entry - ATR_TP2_MULT * atr
        risk = sl - entry

    if risk <= 0:
        return None
    reward1 = abs(tp1 - entry)
    rr1 = reward1 / risk
    rr2 = abs(tp2 - entry) / risk
    fees = entry * FEE_RATE * 2
    if reward1 < fees * MIN_TP_FEE_MULT:   # TP باید از کارمزد رفت‌وبرگشت بامزه باشد
        return None
    if rr1 < MIN_RR:
        return None

    risk_usdt = ACCOUNT_EQUITY * RISK_PER_TRADE_PCT / 100
    qty_by_risk = risk_usdt / risk
    notional_cap = ACCOUNT_EQUITY * LEVERAGE
    qty = min(qty_by_risk, notional_cap / entry)

    return {
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "rr1": round(rr1, 2), "rr2": round(rr2, 2),
        "risk_pct": round(risk / entry * 100, 2),
        "qty": qty, "notional": qty * entry,
        "risk_usdt": round(qty * risk, 2),
        "fees_usdt": round(qty * entry * FEE_RATE * 2, 2),
    }


# =====================================================================
# 8) تلگرام (HTML + retry + rate limit)
# =====================================================================
_TG = {"ts": 0.0, "lock": threading.Lock()}
TG_MIN_GAP = float(os.getenv("TG_MIN_GAP", "3.0"))


def send_telegram(text):
    if DRY_RUN and os.getenv("TG_IN_DRY_RUN", "1") != "1":
        log("[TG] dry-run, message suppressed")
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("[TG] token/chat_id missing -> printing only")
        print(text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    with _TG["lock"]:
        gap = time.time() - _TG["ts"]
        if gap < TG_MIN_GAP:
            time.sleep(TG_MIN_GAP - gap)
        for attempt in range(3):
            try:
                r = SESSION.post(url, json=payload, timeout=12)
                if r.status_code == 200:
                    _TG["ts"] = time.time()
                    return True
                if r.status_code == 429:
                    wait = int(r.json().get("parameters", {}).get("retry_after", 5))
                    time.sleep(wait)
                    continue
                if r.status_code == 400:
                    log(f"[TG] 400 bad request: {r.text[:200]}", "error")
                    payload.pop("parse_mode", None)   # تلاش دوباره بدون HTML
                    continue
                time.sleep(2)
            except Exception as e:
                log(f"[TG] error {type(e).__name__}: {e}", "warning")
                time.sleep(2)
        _TG["ts"] = time.time()
    return False


def fmt_price(p):
    if not math.isfinite(p):
        return "-"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.8f}".rstrip("0").rstrip(".")


def format_signal(symbol, sig, levels, score, grade):
    icon = "🟢" if sig["side"] == "long" else "🔴"
    side_fa = "LONG / خرید" if sig["side"] == "long" else "SHORT / فروش"
    names = {
        "sensi": "سنسی (خشکی حجم در کف)",
        "pullback_bull": "پولبک صعودی",
        "pullback_bear": "پولبک نزولی",
        "retest_bull": "شکست و ریتست صعودی",
        "retest_bear": "شکست و ریتست نزولی",
    }
    ts = datetime.fromtimestamp(sig["candle_ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"{icon} <b>سیگنال {side_fa}</b>",
        f"<b>نماد:</b> <code>{symbol}</code>",
        f"<b>استراتژی:</b> {names.get(sig['strategy'], sig['strategy'])}",
        f"<b>تایم‌فریم:</b> {TIMEFRAME} | <b>کندل:</b> {ts}",
        f"<b>ورود:</b> <code>{fmt_price(sig['entry'])}</code>",
        f"<b>حد ضرر:</b> <code>{fmt_price(levels['sl'])}</code> ({levels['risk_pct']}%)",
        f"<b>TP1:</b> <code>{fmt_price(levels['tp1'])}</code> (R:R {levels['rr1']})",
        f"<b>TP2:</b> <code>{fmt_price(levels['tp2'])}</code> (R:R {levels['rr2']})",
        f"<b>امتیاز:</b> {score}/100 (درجه {grade})",
        f"<b>حجم پیشنهادی:</b> {levels['qty']:.6g} (~{levels['notional']:.1f} USDT، اهرم {LEVERAGE:g}x)",
        f"<b>ریسک:</b> {levels['risk_usdt']} USDT | <b>کارمزد تقریبی:</b> {levels['fees_usdt']} USDT",
        f"<b>دلیل:</b> {sig['reason']}",
        f"<i>RSI {sig['rsi']:.1f} | ADX {sig['adx']:.1f} | BBW {sig['bb_width']:.2f}% | Vol {sig['vol_ratio']:.2f}x</i>",
    ]
    if DRY_RUN:
        lines.append("⚠️ <i>حالت آزمایشی (DRY_RUN) - بدون اجرای واقعی</i>")
    return "\n".join(lines)


# =====================================================================
# 9) ضدتکرار و پیگیری نتیجه (Paper)
# =====================================================================
_STATE_LOCK = threading.Lock()
_STATE = {"signals": {}, "last_symbol": {}}


def load_state():
    global _STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _STATE = {"signals": data.get("signals", {}), "last_symbol": data.get("last_symbol", {})}
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[State] load failed: {e}", "warning")


def save_state():
    tmp = STATE_FILE + ".tmp"
    try:
        with _STATE_LOCK:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_STATE, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"[State] save failed: {e}", "warning")


def already_signaled(symbol, candle_ts, strategy):
    key = f"{symbol}|{candle_ts}|{strategy}"
    return key in _STATE["signals"]


def mark_signaled(symbol, candle_ts, strategy, sig, levels):
    key = f"{symbol}|{candle_ts}|{strategy}"
    _STATE["signals"][key] = {
        "symbol": symbol, "strategy": strategy, "side": sig["side"],
        "candle_ts": candle_ts, "entry": sig["entry"],
        "sl": levels["sl"], "tp1": levels["tp1"], "tp2": levels["tp2"],
        "created": int(time.time()), "status": "open", "result": "",
    }
    _STATE["last_symbol"][symbol] = int(time.time())
    # جلوگیری از رشد بی‌نهایت فایل
    if len(_STATE["signals"]) > 3000:
        keys = sorted(_STATE["signals"], key=lambda k: _STATE["signals"][k]["created"])
        for k in keys[:1000]:
            _STATE["signals"].pop(k, None)
    save_state()


def symbol_in_cooldown(symbol):
    last = _STATE["last_symbol"].get(symbol, 0)
    return (time.time() - last) < SYMBOL_COOLDOWN


def track_outcomes():
    """بررسی سیگنال‌های باز و ثبت برخورد با TP1/SL در CSV."""
    open_sigs = [s for s in _STATE["signals"].values() if s.get("status") == "open"]
    if not open_sigs:
        return
    by_symbol = {}
    for s in open_sigs:
        by_symbol.setdefault(s["symbol"], []).append(s)

    changed = False
    for symbol, sigs in by_symbol.items():
        df = fetch_candles(symbol, TIMEFRAME, 60)
        if df is None:
            continue
        for s in sigs:
            after = df[df["timestamp"] / 1000 > s["candle_ts"]]
            if after.empty:
                continue
            long = s["side"] == "long"
            hit_tp = (after["High"] >= s["tp1"]).any() if long else (after["Low"] <= s["tp1"]).any()
            hit_sl = (after["Low"] <= s["sl"]).any() if long else (after["High"] >= s["sl"]).any()
            if not hit_tp and not hit_sl:
                if len(after) >= 32:      # ۸ ساعت بدون نتیجه -> منقضی
                    s["status"], s["result"] = "closed", "expired"
                    changed = True
                continue
            # هرکدام اول برخورد کرده باشد
            if hit_tp and hit_sl:
                tp_idx = after.index[(after["High"] >= s["tp1"]) if long else (after["Low"] <= s["tp1"])][0]
                sl_idx = after.index[(after["Low"] <= s["sl"]) if long else (after["High"] >= s["sl"])][0]
                result = "tp1" if tp_idx <= sl_idx else "sl"
            else:
                result = "tp1" if hit_tp else "sl"
            s["status"], s["result"] = "closed", result
            changed = True
            _append_outcome(s, result)

    if changed:
        save_state()


def _append_outcome(s, result):
    new = not os.path.exists(OUTCOME_FILE)
    try:
        with open(OUTCOME_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "symbol", "strategy", "side", "entry", "sl", "tp1", "result"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), s["symbol"],
                        s["strategy"], s["side"], s["entry"], s["sl"], s["tp1"], result])
    except Exception as e:
        log(f"[Outcome] write failed: {e}", "warning")


def winrate_stats():
    if not os.path.exists(OUTCOME_FILE):
        return {"total": 0, "tp1": 0, "sl": 0, "expired": 0, "winrate": None}
    total = tp1 = sl = exp = 0
    try:
        with open(OUTCOME_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total += 1
                if row["result"] == "tp1":
                    tp1 += 1
                elif row["result"] == "sl":
                    sl += 1
                else:
                    exp += 1
    except Exception:
        pass
    decided = tp1 + sl
    return {"total": total, "tp1": tp1, "sl": sl, "expired": exp,
            "winrate": round(tp1 / decided * 100, 1) if decided else None}


# =====================================================================
# 10) سرور سلامت
# =====================================================================
_STATS = {"started": time.time(), "scans": 0, "signals": 0, "errors": 0, "last_scan": 0}


class HealthHandler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body.encode("utf-8") if isinstance(body, str) else body)

    def do_GET(self):
        if self.path.startswith("/stats") or self.path.startswith("/health"):
            payload = {
                "status": "ok",
                "uptime_sec": int(time.time() - _STATS["started"]),
                "scans": _STATS["scans"],
                "signals_sent": _STATS["signals"],
                "errors": _STATS["errors"],
                "last_scan": _STATS["last_scan"],
                "symbols": len(SYMBOLS),
                "timeframe": TIMEFRAME,
                "dry_run": DRY_RUN,
                "btc_bias": _BTC_CACHE.get("bias"),
                "winrate": winrate_stats(),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False))
        else:
            self._send(200, "Bitpin 15m Multi-Strategy Bot is running.", "text/plain; charset=utf-8")

    def do_HEAD(self):
        self._send(200, b"")

    def log_message(self, *a):
        pass


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    try:
        srv = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"[Health] listening on :{port}")
    except Exception as e:
        log(f"[Health] failed to start: {e}", "error")


# =====================================================================
# 11) حلقه اصلی
# =====================================================================
_STOP = {"flag": False}


def _handle_stop(signum, frame):
    log(f"[Main] signal {signum} received -> shutting down")
    _STOP["flag"] = True


def seconds_into_candle():
    return int(time.time()) % PERIOD


def run_cycle(mode):
    """mode: 'close' (دقیقه ۰-۱) یا 'sensi' (۲ دقیقه آخر کندل)."""
    regime = btc_regime()
    symbols = tradable_symbols()
    _STATS["scans"] += 1
    _STATS["last_scan"] = int(time.time())
    sent = 0

    for symbol in symbols:
        if _STOP["flag"]:
            break
        try:
            if mode == "close" and symbol_in_cooldown(symbol):
                continue

            if mode == "sensi":
                df_live = fetch_candles(symbol, TIMEFRAME, CANDLE_COUNT, include_forming=True)
                if df_live is None or len(df_live) < 30:
                    continue
                df_closed = df_live.iloc[:-1].reset_index(drop=True)
                sig = signal_sensi(symbol, df_closed, df_live)
                candidates = [sig] if sig else []
            else:
                df = fetch_candles(symbol, TIMEFRAME, CANDLE_COUNT)
                if df is None or len(df) < 30:
                    continue
                d = add_indicators(df)
                # اولویت: پولبک، بعد ریتست (elif زنجیره‌ای)
                sig = signal_pullback(symbol, d)
                if sig is None:
                    sig = signal_break_retest(symbol, d)
                candidates = [sig] if sig else []

            for sig in candidates:
                if sig is None or not passes_filters(sig):
                    continue
                if sig["side"] == "long" and not regime["ok"]:
                    continue
                if already_signaled(symbol, sig["candle_ts"], sig["strategy"]):
                    continue
                levels = build_levels(sig)
                if levels is None:
                    continue
                score, grade = score_signal(sig, regime["bias"])
                if grade == "C":
                    continue

                ok = send_telegram(format_signal(symbol, sig, levels, score, grade))
                mark_signaled(symbol, sig["candle_ts"], sig["strategy"], sig, levels)
                sent += 1
                _STATS["signals"] += 1
                log(f"[Signal] {symbol} {sig['strategy']} {sig['side']} "
                    f"score={score} grade={grade} tg={'ok' if ok else 'failed'}")
                break   # یک سیگنال در هر نماد در هر چرخه

        except Exception as e:
            _STATS["errors"] += 1
            log(f"[Cycle] {symbol} error: {type(e).__name__}: {e}", "error")

    log(f"[Cycle] mode={mode} symbols={len(symbols)} signals={sent} btc={regime['bias']}")


def startup_selftest():
    log("=" * 62)
    log("Bitpin 15m Multi-Strategy Bot v2 - starting")
    log(f"  timeframe={TIMEFRAME} symbols={len(SYMBOLS)} dry_run={DRY_RUN} "
        f"equity={ACCOUNT_EQUITY} risk={RISK_PER_TRADE_PCT}% lev={LEVERAGE:g}x")
    log("=" * 62)

    mk = fetch_markets()
    log(f"[Selftest] markets: {'OK ' + str(len(mk)) if mk else 'FAILED'}")

    df = fetch_candles("BTC_USDT", TIMEFRAME, 60)
    if df is None:
        df = fetch_candles("BTC_IRT", TIMEFRAME, 60)
    if df is not None:
        d = add_indicators(df)
        last = d.iloc[-1]
        log(f"[Selftest] candles: OK {len(df)} | close={last['Close']} "
            f"RSI={last['RSI']:.1f} ATR={last['ATR']:.6g} BBW={last['BB_Width']:.2f}%")
    else:
        log("[Selftest] candles: FAILED", "error")

    r = btc_regime(force=True)
    log(f"[Selftest] BTC regime: {r['bias']}")
    log(f"[Selftest] winrate: {winrate_stats()}")


def main():
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    load_state()
    start_health_server()
    startup_selftest()

    last_close_cycle = 0
    last_sensi_cycle = 0

    while not _STOP["flag"]:
        try:
            into = seconds_into_candle()

            # پنجره بسته‌شدن کندل: ۰ تا ۹۰ ثانیه بعد از شروع کندل جدید
            if into <= 90 and (time.time() - last_close_cycle) > 300:
                run_cycle("close")
                track_outcomes()
                last_close_cycle = time.time()

            # پنجره سنسی: ۷۸۰ تا ۹۰۰ ثانیه (۲ دقیقه آخر)
            if 780 <= into <= 899 and (time.time() - last_sensi_cycle) > 120:
                run_cycle("sensi")
                last_sensi_cycle = time.time()

            # خواب تا تیک بعدی (حداکثر ۳۰ ثانیه)
            time.sleep(15)

        except Exception as e:
            _STATS["errors"] += 1
            log(f"[Main] loop error: {type(e).__name__}: {e}", "error")
            time.sleep(20)

    save_state()
    log("[Main] stopped cleanly")


if __name__ == "__main__":
    main()
