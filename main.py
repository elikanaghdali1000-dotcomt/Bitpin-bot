#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=======================================================================
 ربات سیگنال بیت‌پین — استراتژی «شکست کانال دانچیان ۵۵» روی تایم‌فریم ۴ ساعته
=======================================================================
این ربات همان استراتژی‌ای است که در بک‌تست (۲۰۲۳-۰۴ تا ۲۰۲۶-۱۱، ۳۵ نماد)
اعتبارسنجی شد و نتیجه داد:

    • ورود (LONG فقط):  close > بالاترین سقف ۵۵ کندل اخیر (shift شده)
    • فیلترها:          حجم ≥ 1.2 برابر میانگین ۲۰ کندل
                        ADX ≥ 18  (بازار رِنج نباشد)
                        EMA50 > EMA200  (روند بزرگ صعودی)
    • حد ضرر:           2.5 × ATR(14) زیر ورود
    • حد سود:           8.0 × ATR(14) بالای ورود   (R:R ≈ 3.2)
    • تریلینگ:          ندارد (تریلینگ در تست نتیجه را خراب کرد)
    • خروج زمانی:       ۴۸ کندل ۴ساعته ≈ ۸ روز
    • شورت:             ندارد (شورت در تست ضررده بود)
    • سیگنال فقط روی کندلِ بسته‌شده؛ ورود «مارکت» در بازشدن کندل بعد
    • فیلتر «تازگی شکست» ندارد: بک‌تست نشان داد حذف ورودهای مجدد در یک روند،
      سود را از ۵۴۸٪ به ۱۵۷٪ کاهش می‌دهد. برگشت به روند بعد از استاپ، خودش سیگنال است.

نتیجه بک‌تست روی «لیست سفید ۱۵ نمادی» (داده بومی ۴ساعته بیت‌پین،
۲۰۲۳-۰۴-۱۵ تا ۲۰۲۶-۱۱، با کارمزد ۰.۲٪ و اسلیپیج ۰.۱۵٪):
    ۳۳۱ معامله | وین‌ریت ۴۲.۰٪ | PF 1.63 | میانگین +0.31R | مجموع +101.9R
    پورتفوی با ریسک ۱٪ در هر معامله: ۲.۶۴ برابر در ۳.۵ سال، حداکثر افت ۲۹٪
    پورتفوی با ریسک ۰.۵٪:           ۱.۶۴ برابر، حداکثر افت ۱۶٪

    تقسیم سالانه (ریسک ۱٪):  ۲۰۲۳ +۱۲٪ | ۲۰۲۴ +۱۰۶٪ | ۲۰۲۵ −۵٪ | ۲۰۲۶ +۲۱٪
    ⚠️ سال ۲۰۲۵ منفی بود؛ این استراتژی سالِ بد هم دارد.

    برای مقایسه: اگر هر ۳۶ نماد را معامله کنید PF به 1.16 سقوط می‌کند.
    سود از «چند ترید بزرگ» می‌آید نه از دقت بالا (۵٪ برتر معاملات ≈ ۱۸٪ سود).
    پس: بدون مدیریت سرمایه و بدون پایبندی به حد ضرر، این استراتژی ضررده می‌شود.

⚠️ این ربات «سیگنال‌ده» است، نه معامله‌گر خودکار. هیچ سفارشی روی صرافی نمی‌گذارد.
⚠️ خروجی این برنامه توصیه سرمایه‌گذاری نیست. مسئولیت هر معامله با خود شماست.

اجرا:
    export TELEGRAM_BOT_TOKEN="8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA"
    export TELEGRAM_CHAT_ID="6643451227"
    python3 bitpin_donchian_bot.py

متغیرهای محیطی مهم:
    DRY_RUN=1               حالت آزمایشی (پیش‌فرض ۱): سیگنال‌ها فقط لاگ می‌شوند
    TIMEFRAME=4h            تایم‌فریم (۴h پیشنهادی؛ 1h هم پشتیبانی می‌شود)
    SYMBOLS="SOL_USDT,..."  لیست سفارشی نمادها
    EQUITY_USDT=1000        سرمایه فرضی برای محاسبه حجم
    RISK_PCT=1.0            درصد ریسک هر معامله
    PORT=10000              پورت health-check (برای Render/Railway)
=======================================================================
"""

import os
import sys
import json
import time
import math
import signal
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pandas as pd
import requests

# =====================================================================
# ۱) تنظیمات
# =====================================================================
VERSION = "1.0.0"

def _env_bool(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default

def _env_int(name, default):
    try:
        return int(float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default

DRY_RUN          = _env_bool("DRY_RUN", True)
TIMEFRAME        = os.getenv("TIMEFRAME", "4h").strip().lower()
PERIOD           = 14400 if TIMEFRAME == "4h" else 3600
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TG_IN_DRY_RUN    = _env_bool("TG_IN_DRY_RUN", True)   # در حالت تست هم پیام بفرست؟

EQUITY_USDT      = _env_float("EQUITY_USDT", 1000.0)
RISK_PCT         = _env_float("RISK_PCT", 1.0)
MAX_NOTIONAL_MULT = _env_float("MAX_NOTIONAL_MULT", 5.0)  # سقف حجم = ۵ برابر سرمایه

# --- پارامترهای استراتژی (دست نزنید مگر با بک‌تست مجدد) ---
DC_LEN       = 55      # طول کانال دانچیان
VOL_MULT     = 1.2     # حداقل نسبت حجم
ADX_MIN      = 18.0    # حداقل ADX
ATR_LEN      = 14
SL_ATR       = 2.5     # حد ضرر = ۲.۵ ATR
TP_ATR       = 8.0     # حد سود  = ۸ ATR
MAX_HOLD     = 48      # حداکثر نگهداری (کندل)
WARMUP       = 260     # کندل لازم برای گرم شدن اندیکاتورها (EMA200 + حاشیه)
MIN_RISK_PCT = 0.25    # اگر فاصله SL کمتر از این درصد باشد، سیگنال رد می‌شود
MAX_RISK_PCT = 15.0    # اگر فاصله SL بیشتر از این درصد باشد (ATR غیرعادی)، سیگنال رد می‌شود

# --- لیست سفید نمادها: فقط نمادهایی که در بک‌تست سود مثبت داشتند ---
DEFAULT_SYMBOLS = [
    "SOL_USDT", "ADA_USDT", "XRP_USDT", "ALGO_USDT", "GALA_USDT", "AAVE_USDT",
    "CRV_USDT", "NEAR_USDT", "ARB_USDT", "UNI_USDT", "SUI_USDT", "VET_USDT",
    "AVAX_USDT", "TRX_USDT", "XLM_USDT",
]
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()] or DEFAULT_SYMBOLS
SYMBOLS = [s if s.endswith("_USDT") else s + "_USDT" for s in SYMBOLS]

SCAN_INTERVAL = _env_int("SCAN_INTERVAL", 300)   # هر ۵ دقیقه چک کن
CANDLE_COUNT  = _env_int("CANDLE_COUNT", 500)    # تعداد کندل دانلودی
REQUEST_GAP   = _env_float("REQUEST_GAP", 0.35)  # فاصله بین درخواست‌ها

STATE_FILE    = os.getenv("STATE_FILE", "donchian_state.json")
LOG_FILE      = os.getenv("LOG_FILE", "donchian_bot.log")

# =====================================================================
# ۲) لاگ
# =====================================================================
_LOG_LOCK = threading.Lock()

def log(msg, level="info"):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    icons = {"info": "•", "ok": "✓", "warning": "!", "error": "✗", "signal": "★"}
    line = f"{stamp} UTC {icons.get(level, '•')} {msg}"
    with _LOG_LOCK:
        print(line, flush=True)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

# =====================================================================
# ۳) لایه HTTP (با چرخش میزبان)
# =====================================================================
BITPIN_HOSTS = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org",
    "https://api.bitpin.com",
]

CANDLES_PATH = "/api/v1/mkt/candles/"
TICKERS_PATH = "/api/v1/mkt/tickers/"

RES_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Referer": "https://bitpin.ir/",
})

_HOST = {"base": None, "ts": 0.0}
_HOST_TTL = 600
_LAST_REQ = {"ts": 0.0}

def _throttle():
    gap = time.time() - _LAST_REQ["ts"]
    if gap < REQUEST_GAP:
        time.sleep(REQUEST_GAP - gap)
    _LAST_REQ["ts"] = time.time()

def get_json(path, params=None, timeout=25, retries=2):
    hosts = list(BITPIN_HOSTS)
    if _HOST["base"] and (time.time() - _HOST["ts"] < _HOST_TTL) and _HOST["base"] in hosts:
        hosts.remove(_HOST["base"])
        hosts.insert(0, _HOST["base"])

    last_err = None
    for host in hosts:
        for attempt in range(retries):
            try:
                _throttle()
                r = SESSION.get(host + path, params=params, timeout=timeout)
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:
                        last_err = f"invalid JSON from {host}"
                        break
                    _HOST["base"], _HOST["ts"] = host, time.time()
                    return data, host
                last_err = f"HTTP {r.status_code} from {host}"
                if r.status_code in (400, 404):
                    break
                time.sleep(1.0)
            except Exception as e:
                last_err = f"{host}: {type(e).__name__}"
                time.sleep(1.0)
    log(f"[HTTP] {path} failed: {last_err}", "error")
    return None, None

# =====================================================================
# ۴) داده‌ها
# =====================================================================
def fetch_candles(symbol, count=CANDLE_COUNT):
    step = RES_SECONDS[TIMEFRAME]
    now = int(time.time())
    params = {"symbol": symbol, "res": TIMEFRAME,
              "from": now - int(count + 5) * step, "to": now}
    data, _ = get_json(CANDLES_PATH, params=params)
    if not data:
        return None
    rows = data if isinstance(data, list) else data.get("results", [])
    if not rows:
        return None

    df = pd.DataFrame(rows)
    if "time" in df.columns and "ts" in df.columns:
        df = df.drop(columns=["ts"])
    df = df.rename(columns={"time": "timestamp", "ts": "timestamp",
                            "open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    if "timestamp" not in df.columns:
        return None
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            return None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")

    if df["timestamp"].max() < 10_000_000_000:
        df["timestamp"] = df["timestamp"] * 1000

    df = (df.dropna(subset=["Open", "High", "Low", "Close", "Volume", "timestamp"])
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True))

    if not df.empty:
        last_open_sec = int(df["timestamp"].iloc[-1] / 1000)
        if now < last_open_sec + step:
            df = df.iloc[:-1].reset_index(drop=True)

    return df if not df.empty else None

_PRICE = {"data": {}, "ts": 0.0}
_PRICE_TTL = 45

def get_prices():
    if time.time() - _PRICE["ts"] < _PRICE_TTL and _PRICE["data"]:
        return _PRICE["data"]
    data, _ = get_json(TICKERS_PATH)
    out = {}
    if isinstance(data, list):
        for t in data:
            if not isinstance(t, dict):
                continue
            sym = str(t.get("symbol", "")).upper()
            try:
                p = float(t.get("price"))
            except (TypeError, ValueError):
                continue
            if p > 0:
                out[sym] = p
    if out:
        _PRICE["data"], _PRICE["ts"] = out, time.time()
    return out or _PRICE["data"]

# =====================================================================
# ۵) اندیکاتورها
# =====================================================================
def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def _rma(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()

def add_indicators(df):
    d = df.copy()
    h, l, c, v = d.High, d.Low, d.Close, d.Volume

    d["ema50"] = _ema(c, 50)
    d["ema200"] = _ema(c, 200)

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = _rma(tr, ATR_LEN)

    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)
    atr_safe = d["atr"].replace(0, np.nan)
    d["pdi"] = 100 * _rma(pdm, 14) / atr_safe
    d["ndi"] = 100 * _rma(ndm, 14) / atr_safe
    dx = 100 * (d["pdi"] - d["ndi"]).abs() / (d["pdi"] + d["ndi"]).replace(0, np.nan)
    d["adx"] = _rma(dx.fillna(0), 14)

    d["dc_hi"] = h.rolling(DC_LEN).max().shift(1)
    d["vol_ma"] = v.rolling(20).mean()
    d["vol_ratio"] = v / d["vol_ma"].replace(0, np.nan)
    return d

# =====================================================================
# ۶) تشخیص سیگنال (LONG فقط)
# =====================================================================
def evaluate(df):
    if df is None or len(df) < WARMUP:
        return {"triggered": False, "reason": "داده کافی نیست"}

    d = add_indicators(df)
    i = len(d) - 1
    row = d.iloc[i]

    if not all(np.isfinite(row[k]) for k in ("atr", "adx", "ema50", "ema200", "dc_hi", "vol_ratio")):
        return {"triggered": False, "reason": "اندیکاتور ناقص"}

    checks = {
        "breakout":  bool(row["Close"] > row["dc_hi"]),
        "volume":    bool(row["vol_ratio"] >= VOL_MULT),
        "trend":     bool(row["adx"] >= ADX_MIN),
        "ema":       bool(row["ema50"] > row["ema200"]),
    }
    triggered = all(checks.values())

    return {
        "triggered": triggered,
        "checks": checks,
        "candle_ts": int(row["timestamp"] / 1000),
        "close": float(row["Close"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "open": float(row["Open"]),
        "dc_hi": float(row["dc_hi"]),
        "atr": float(row["atr"]),
        "atr_pct": float(row["atr"] / row["Close"] * 100),
        "adx": float(row["adx"]),
        "pdi": float(row["pdi"]),
        "ndi": float(row["ndi"]),
        "vol_ratio": float(row["vol_ratio"]),
        "ema50": float(row["ema50"]),
        "ema200": float(row["ema200"]),
        "reason": "شکست سقف ۵۵ کندل با تأیید حجم/ADX/روند" if triggered else "شرط ورود کامل نیست",
    }

# =====================================================================
# ۷) سطوح و حجم
# =====================================================================
def build_levels(sig, price):
    atr = sig["atr"]
    entry = price if price and price > 0 else sig["close"]
    sl = entry - SL_ATR * atr
    tp = entry + TP_ATR * atr
    if sl <= 0 or entry <= 0:
        return None

    risk_pct = (entry - sl) / entry * 100
    if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
        return {"rejected": True, "risk_pct": risk_pct,
                "why": f"فاصله حد ضرر {risk_pct:.1f}% خارج از بازه مجاز"}

    risk_usdt = EQUITY_USDT * RISK_PCT / 100.0
    qty = risk_usdt / (entry - sl)
    notional = qty * entry
    cap = EQUITY_USDT * MAX_NOTIONAL_MULT
    if notional > cap:
        notional = cap
        qty = cap / entry

    fees = notional * 0.002 * 2
    return {
        "rejected": False,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": risk_pct,
        "rr": (tp - entry) / (entry - sl),
        "qty": qty,
        "notional": notional,
        "risk_usdt": risk_usdt,
        "fees_usdt": fees,
        "tp_pct": (tp - entry) / entry * 100,
    }

# =====================================================================
# ۸) تلگرام
# =====================================================================
_TG = {"lock": threading.Lock(), "ts": 0.0}
TG_MIN_GAP = 1.2

def send_telegram(text):
    if DRY_RUN and not TG_IN_DRY_RUN:
        print(text)
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n" + text + "\n")
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
                r = SESSION.post(url, json=payload, timeout=15)
                if r.status_code == 200:
                    _TG["ts"] = time.time()
                    return True
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                if r.status_code == 400:
                    payload.pop("parse_mode", None)
                    continue
                time.sleep(2)
            except Exception:
                time.sleep(2)
        _TG["ts"] = time.time()
    return False

def fmt_price(p):
    if p is None or not math.isfinite(p):
        return "-"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.8f}".rstrip("0").rstrip(".")

def format_signal(symbol, sig, lv):
    ts = datetime.fromtimestamp(sig["candle_ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [
        "🟢 <b>سیگنال خرید (LONG)</b>",
        f"<b>نماد:</b> <code>{symbol}</code>",
        f"<b>استراتژی:</b> شکست کانال ۵۵ ({TIMEFRAME})",
        f"<b>کندل سیگنال:</b> {ts} UTC",
        "",
        f"<b>ورود (مارکت):</b> <code>{fmt_price(lv['entry'])}</code>",
        f"<b>حد ضرر:</b> <code>{fmt_price(lv['sl'])}</code>  (−{lv['risk_pct']:.1f}%)",
        f"<b>حد سود:</b> <code>{fmt_price(lv['tp'])}</code>  (+{lv['tp_pct']:.1f}%)",
        f"<b>R:R:</b> {lv['rr']:.2f} | <b>حداکثر نگهداری:</b> {MAX_HOLD} کندل",
        "",
        f"<b>حجم پیشنهادی:</b> <code>{lv['qty']:.6g}</code> (~{lv['notional']:.1f} USDT)",
        f"<b>ریسک:</b> {lv['risk_usdt']:.2f} USDT | <b>کارمزد تخمینی:</b> {lv['fees_usdt']:.2f} USDT",
    ]
    if DRY_RUN:
        lines += ["", "⚠️ <i>حالت آزمایشی (DRY_RUN)</i>"]
    return "\n".join(lines)

def format_exit(pos, result, price, bars_held):
    icon = {"tp": "✅", "sl": "🛑", "time": "⏳", "manual": "⚪"}.get(result, "⚪")
    title = {"tp": "حد سود خورد", "sl": "حد ضرر خورد", "time": "خروج زمانی"}.get(result, result)
    pnl_pct = (price / pos["entry"] - 1) * 100
    r_mult = (price - pos["entry"]) / (pos["entry"] - pos["sl"]) if pos["entry"] != pos["sl"] else 0
    pnl_usdt = (price - pos["entry"]) * pos.get("qty", 0)
    return "\n".join([
        f"{icon} <b>{title}</b> — <code>{pos['symbol']}</code>",
        f"<b>ورود:</b> <code>{fmt_price(pos['entry'])}</code>",
        f"<b>خروج:</b> <code>{fmt_price(price)}</code>",
        f"<b>نتیجه:</b> {pnl_pct:+.2f}% | {r_mult:+.2f}R | {pnl_usdt:+.2f} USDT",
        f"<b>مدت:</b> {bars_held} کندل",
    ])

# =====================================================================
# ۹) حالت و ذخیره‌سازی
# =====================================================================
_STATE_LOCK = threading.Lock()
STATS = {"scans": 0, "signals": 0, "errors": 0, "started": time.time()}
STATE = {"sent": {}, "open": {}, "closed": [], "stats": STATS}

def load_state():
    global STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            STATE.update({
                "sent": data.get("sent", {}),
                "open": data.get("open", {}),
                "closed": data.get("closed", [])[-300:],
            })
            STATS["scans"] = int(data.get("stats", {}).get("scans", 0))
            STATS["signals"] = int(data.get("stats", {}).get("signals", 0))
            STATS["errors"] = int(data.get("stats", {}).get("errors", 0))
    except FileNotFoundError:
        pass
    except Exception:
        pass

def save_state():
    tmp = STATE_FILE + ".tmp"
    try:
        with _STATE_LOCK:
            STATE["stats"] = STATS
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(STATE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass

def already_sent(symbol, candle_ts):
    return f"{symbol}|{candle_ts}" in STATE["sent"]

def mark_sent(symbol, candle_ts, lv):
    STATE["sent"][f"{symbol}|{candle_ts}"] = {"ts": candle_ts, "entry": lv["entry"]}
    cutoff = time.time() - 30 * 86400
    STATE["sent"] = {k: v for k, v in STATE["sent"].items() if v.get("ts", 0) > cutoff}

# =====================================================================
# ۱۰) پیگیری معاملات باز
# =====================================================================
def track_open_positions(candles_cache, prices):
    if not STATE["open"]:
        return
    for symbol in list(STATE["open"].keys()):
        pos = STATE["open"][symbol]
        df = candles_cache.get(symbol)

        live = prices.get(symbol)
        if live:
            if live <= pos["sl"]:
                _close_position(symbol, pos, pos["sl"], "sl", _bars_since(df, pos))
                continue
            if live >= pos["tp"]:
                _close_position(symbol, pos, pos["tp"], "tp", _bars_since(df, pos))
                continue

        if df is None or df.empty:
            continue

        ct = int(pos.get("candle_ts") or pos.get("opened_at") or 0)
        after = df[df["timestamp"] / 1000 > ct]
        if after.empty:
            continue

        exit_price, result, bars = None, None, 0
        for _, row in after.iterrows():
            bars += 1
            if row["Low"] <= pos["sl"]:
                exit_price, result = pos["sl"], "sl"
                break
            if row["High"] >= pos["tp"]:
                exit_price, result = pos["tp"], "tp"
                break
            if bars >= MAX_HOLD:
                exit_price, result = float(row["Close"]), "time"
                break

        if result is None:
            continue

        _close_position(symbol, pos, exit_price, result, bars)

def _bars_since(df, pos):
    try:
        ct = int(pos.get("candle_ts") or 0)
        return int((df["timestamp"] / 1000 > ct).sum())
    except Exception:
        return 0

def _close_position(symbol, pos, exit_price, result, bars):
    send_telegram(format_exit(pos, result, exit_price, bars))
    r_mult = (exit_price - pos["entry"]) / (pos["entry"] - pos["sl"]) if pos["entry"] != pos["sl"] else 0
    with _STATE_LOCK:
        STATE["closed"].append({
            "symbol": symbol, "entry": pos["entry"], "sl": pos["sl"], "tp": pos["tp"],
            "qty": pos.get("qty", 0), "exit": exit_price,
            "result": result, "r": round(r_mult, 3), "bars": bars,
            "closed_at": int(time.time()),
        })
        STATE["closed"] = STATE["closed"][-300:]
        STATE["open"].pop(symbol, None)
    save_state()

# =====================================================================
# ۱۱) چرخه اسکن
# =====================================================================
def run_cycle():
    STATS["scans"] += 1
    prices = get_prices()
    candles_cache = {}
    found = 0

    for idx, symbol in enumerate(SYMBOLS, 1):
        try:
            df = fetch_candles(symbol)
            if df is None or len(df) < WARMUP:
                continue
            candles_cache[symbol] = df

            sig = evaluate(df)
            if not sig.get("triggered"):
                continue

            if already_sent(symbol, sig["candle_ts"]):
                continue

            if symbol in STATE["open"]:
                continue

            lv = build_levels(sig, prices.get(symbol))
            if lv is None or lv.get("rejected"):
                if lv and lv.get("rejected"):
                    mark_sent(symbol, sig["candle_ts"], {"entry": sig["close"]})
                continue

            send_telegram(format_signal(symbol, sig, lv))
            mark_sent(symbol, sig["candle_ts"], lv)
            with _STATE_LOCK:
                STATE["open"][symbol] = {
                    "symbol": symbol, "entry": lv["entry"], "sl": lv["sl"], "tp": lv["tp"],
                    "qty": lv["qty"], "atr": sig["atr"], "risk_usdt": lv["risk_usdt"],
                    "candle_ts": sig["candle_ts"], "opened_at": int(time.time()),
                }
            STATS["signals"] += 1
            found += 1
            save_state()

        except Exception as e:
            STATS["errors"] += 1

    try:
        track_open_positions(candles_cache, prices)
    except Exception:
        pass
    save_state()

# =====================================================================
# ۱۲) وب‌سرور سلامت
# =====================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        closed = STATE["closed"]
        wins = [c for c in closed if c["r"] > 0]
        payload = {
            "status": "ok",
            "version": VERSION,
            "scans": STATS["scans"],
            "signals": STATS["signals"],
            "open_positions": len(STATE["open"]),
            "winrate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        }
        self._send(200, json.dumps(payload, ensure_ascii=False))

    def log_message(self, *a):
        pass

def start_health_server():
    port = _env_int("PORT", 10000)
    try:
        srv = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    except Exception:
        pass

# =====================================================================
# ۱۳) حلقه اصلی
# =====================================================================
_STOP = {"flag": False}

def _handle_stop(signum, frame):
    _STOP["flag"] = True

def seconds_to_next_candle():
    now = int(time.time())
    return PERIOD - (now % PERIOD)

def main():
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    load_state()
    start_health_server()

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram(f"🤖 <b>ربات دانچیان ۵۵ روشن شد</b>\nتایم‌فریم: {TIMEFRAME} | نمادها: {len(SYMBOLS)}")

    while not _STOP["flag"]:
        try:
            run_cycle()
        except Exception:
            STATS["errors"] += 1

        STATS["last_scan"] = int(time.time())
        remain = seconds_to_next_candle()
        sleep_s = min(SCAN_INTERVAL, max(30, remain + 20)) if remain < 900 else SCAN_INTERVAL
        
        slept = 0
        while slept < sleep_s and not _STOP["flag"]:
            time.sleep(min(5, sleep_s - slept))
            slept += 5

    save_state()

if __name__ == "__main__":
    main()
