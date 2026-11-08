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
VERSION = "2.1.0"

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

DRY_RUN          = _env_bool("DRY_RUN", False)
TIMEFRAME        = os.getenv("TIMEFRAME", "4h").strip().lower()
PERIOD           = 14400 if TIMEFRAME == "4h" else 3600

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "*******").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "6643451227").strip()
TG_IN_DRY_RUN    = _env_bool("TG_IN_DRY_RUN", True)

EQUITY_USDT      = _env_float("EQUITY_USDT", 1000.0)
RISK_PCT         = _env_float("RISK_PCT", 1.0)
MAX_NOTIONAL_MULT = _env_float("MAX_NOTIONAL_MULT", 5.0)

# --- پارامترهای استراتژی و حجم ---
DC_LEN             = 55
ADX_MIN            = 18.0
ATR_LEN            = 14
SL_ATR             = 2.5
TP_ATR             = 8.0
MAX_HOLD           = 48
WARMUP             = 260
MIN_RISK_PCT       = 0.25
MAX_RISK_PCT       = 15.0

# پارامترهای ماژول پیشرفته حجم
VOL_WINDOW         = 20
VOL_MIN            = 1.2
VOL_PREV_MIN       = 1.0
BODY_MIN           = 0.6
TURNOVER_WINDOW    = 180
MIN_TURNOVER_USDT  = 2000.0
MAX_SPREAD_PCT     = 0.60
DEPTH_MULT         = 1.5
ZERO_VOL_MAX       = 0.05
STALE_VOL_MAX      = 0.10

DEFAULT_SYMBOLS = [
    "SOL_USDT", "ADA_USDT", "XRP_USDT", "ALGO_USDT", "GALA_USDT", "AAVE_USDT",
    "CRV_USDT", "NEAR_USDT", "ARB_USDT", "UNI_USDT", "SUI_USDT", "VET_USDT",
    "AVAX_USDT", "TRX_USDT", "XLM_USDT",
]
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()] or DEFAULT_SYMBOLS
SYMBOLS = [s if s.endswith("_USDT") else s + "_USDT" for s in SYMBOLS]

SCAN_INTERVAL = _env_int("SCAN_INTERVAL", 300)   
SCAN_MODE     = os.getenv("SCAN_MODE", "candle").strip().lower()  
CANDLE_BUFFER = _env_int("CANDLE_BUFFER", 60)    
RETRY_BACKOFF = _env_int("RETRY_BACKOFF", 900)   
PRICE_POLL    = _env_int("PRICE_POLL", 300)      
CANDLE_COUNT  = _env_int("CANDLE_COUNT", 500)    
REQUEST_GAP   = _env_float("REQUEST_GAP", 0.35)  

STATE_FILE    = os.getenv("STATE_FILE", "donchian_state.json")
LOG_FILE      = os.getenv("LOG_FILE", "donchian_bot.log")

# =====================================================================
# ۲) سیستم لاگ
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
# ۳) لایه HTTP (ارتباط با بیت‌پین)
# =====================================================================
DEFAULT_WORKER_HOST = "https://divine-wildflower-badc.elikanaghdali1000.workers.dev"

env_hosts = os.getenv("BITPIN_HOSTS", "").strip()
if env_hosts:
    BITPIN_HOSTS = [h.strip().rstrip("/") for h in env_hosts.split(",") if h.strip()]
else:
    BITPIN_HOSTS = [DEFAULT_WORKER_HOST]

CANDLES_PATH  = "/api/v1/mkt/candles/"
TICKERS_PATH  = "/api/v1/mkt/tickers/"
ORDERBOOK_PATH = "/api/v1/mkt/depth/"

RES_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Origin": "https://bitpin.ir",
    "Referer": "https://bitpin.ir/",
    "Connection": "keep-alive",
})

_HOST = {"base": None, "ts": 0.0}
_HOST_TTL = 600
_LAST_REQ = {"ts": 0.0}

HTTP_STATE = {"hard_fail": 0, "last_error": "", "ok_streak": 0}

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
                url = host + path
                r = SESSION.get(url, params=params, timeout=timeout)
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:
                        last_err = f"invalid JSON from {host}"
                        break
                    _HOST["base"], _HOST["ts"] = host, time.time()
                    HTTP_STATE["ok_streak"] += 1
                    return data, host
                last_err = f"HTTP {r.status_code} from {host}"
                if r.status_code in (400, 403, 404, 451):
                    break
                time.sleep(1.0)
            except Exception as e:
                last_err = f"{host}: {type(e).__name__}"
                time.sleep(1.0)

    HTTP_STATE["hard_fail"] += 1
    HTTP_STATE["last_error"] = str(last_err)
    HTTP_STATE["ok_streak"] = 0
    return None, None

# =====================================================================
# ۴) مدیریت داده‌ها و اندیکاتورها
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

def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def _rma(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()

# =====================================================================
# ۵) ماژول پیشرفته حجم و کیفیت داده (سه لایه)
# =====================================================================
def data_quality(d: pd.DataFrame, lookback: int = 500) -> dict:
    tail = d.tail(lookback)
    v = tail["Volume"].astype(float)
    zero_share = float((v <= 0).mean())
    stale_share = float((v.diff() == 0).mean())
    flat_share = float((tail["High"] == tail["Low"]).mean())
    ok = (zero_share <= ZERO_VOL_MAX) and (stale_share <= STALE_VOL_MAX)
    return {
        "zero_vol_share": round(zero_share, 4),
        "stale_vol_share": round(stale_share, 4),
        "flat_candle_share": round(flat_share, 4),
        "ok": bool(ok),
    }

def add_volume_features(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    c = d["Close"].astype(float)
    v = d["Volume"].astype(float)
    o = d["Open"].astype(float)
    h = d["High"].astype(float)
    l = d["Low"].astype(float)

    d["turnover"] = c * v
    d["turnover_med"] = d["turnover"].rolling(TURNOVER_WINDOW, min_periods=60).median()
    d["vol_sma"] = v.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).mean()
    d["vol_ratio"] = v / d["vol_sma"].replace(0, np.nan)

    candle_range = (h - l).replace(0, np.nan)
    d["body_ratio"] = (c - o).abs() / candle_range
    return d

def volume_gate(d: pd.DataFrame, min_turnover: float = MIN_TURNOVER_USDT) -> dict:
    if len(d) == 0:
        return {"ok": False, "reason": "داده خالی"}

    last_row = d.iloc[-1]
    prev_vol_ratio = float(d["vol_ratio"].iloc[-2]) if len(d) >= 2 else 0.0

    liq_ok = bool(last_row.get("turnover_med", 0.0) >= min_turnover)
    spike_ok = bool(last_row.get("vol_ratio", 0.0) >= VOL_MIN)
    persist_ok = bool(prev_vol_ratio >= VOL_PREV_MIN)
    body_ok = bool(last_row.get("body_ratio", 0.0) >= BODY_MIN)

    ok = liq_ok and spike_ok and persist_ok and body_ok

    reasons = []
    if not liq_ok:
        reasons.append(f"نقدشوندگی ضعیف ({last_row.get('turnover_med', 0):,.0f} < {min_turnover:,.0f}$)")
    if not spike_ok:
        reasons.append(f"حجم کندل ناکافی ({last_row.get('vol_ratio', 0):.2f} < {VOL_MIN})")
    if not persist_ok:
        reasons.append(f"عدم تداوم حجم کندل قبل ({prev_vol_ratio:.2f} < {VOL_PREV_MIN})")
    if not body_ok:
        reasons.append(f"بدنه کندل ضعیف ({last_row.get('body_ratio', 0):.2f} < {BODY_MIN})")

    return {
        "ok": ok,
        "liq_ok": liq_ok,
        "spike_ok": spike_ok,
        "persist_ok": persist_ok,
        "body_ok": body_ok,
        "reason": " | ".join(reasons) if reasons else "تأیید کامل شروط حجم",
    }

def volume_filter(d: pd.DataFrame, min_turnover: float = MIN_TURNOVER_USDT) -> dict:
    dq = data_quality(d)
    d_feat = add_volume_features(d)
    gate = volume_gate(d_feat, min_turnover=min_turnover)
    ok = bool(gate["ok"] and dq["ok"])
    turnover_val = float(d_feat["turnover_med"].iloc[-1]) if len(d_feat) and pd.notna(d_feat["turnover_med"].iloc[-1]) else 0.0

    reason = gate["reason"]
    if not dq["ok"]:
        reason = f"کیفیت نامناسب داده (کندل فریز/صفر) | {reason}"

    return {
        "ok": ok,
        "dq": dq,
        "gate": gate,
        "turnover_med": turnover_val,
        "reason": reason,
    }

def orderbook_gate(symbol: str, notional_usdt: float) -> dict:
    try:
        data, _ = get_json(f"/api/v1/mkt/depth/{symbol}/")
        if not data:
            return {"ok": True, "reason": "خطای دریافت دفتر سفارش (Fail-open)"}
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        if not bids or not asks:
            return {"ok": True, "reason": "دفتر سفارش خالی (Fail-open)"}

        bb = float(bids[0][0])
        ba = float(asks[0][0])
        if bb <= 0 or ba <= 0:
            return {"ok": True, "reason": "قیمت نامعتبر دفتر سفارش"}

        mid = (bb + ba) / 2.0
        spread_pct = (ba - bb) / mid * 100.0

        need = notional_usdt * DEPTH_MULT
        depth = 0.0
        for px, amt in asks:
            depth += float(px) * float(amt)
            if depth >= need:
                break

        if spread_pct > MAX_SPREAD_PCT:
            return {"ok": False, "reason": f"اسپرد بالا: {spread_pct:.2f}%"}
        if depth < need:
            return {"ok": False, "reason": f"عمق ناکافی: {depth:,.0f}$"}

        return {"ok": True, "reason": ""}
    except Exception:
        return {"ok": True, "reason": "استثنا در دفتر سفارش (Fail-open)"}

# =====================================================================
# ۶) اندیکاتورها و ارزیابی سیگنال
# =====================================================================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = add_volume_features(df)
    h, l, c = d.High, d.Low, d.Close

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
    return d

def evaluate(symbol: str, df: pd.DataFrame) -> dict:
    if df is None or len(df) < WARMUP:
        return {"triggered": False, "reason": "داده کافی نیست"}

    d = add_indicators(df)
    vol_res = volume_filter(df)
    i = len(d) - 1
    row = d.iloc[i]

    if not all(np.isfinite(row[k]) for k in ("atr", "adx", "ema50", "ema200", "dc_hi")):
        return {"triggered": False, "reason": "اندیکاتور ناقص"}

    checks = {
        "breakout": bool(row["Close"] > row["dc_hi"]),
        "volume":   bool(vol_res["ok"]),
        "trend":    bool(row["adx"] >= ADX_MIN),
        "ema":      bool(row["ema50"] > row["ema200"]),
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
        "turnover_med": vol_res["turnover_med"],
        "reason": "شکست سقف ۵۵ با فیلتر حجمی ۳ لایه و روند قوی" if triggered else f"رد شد: {vol_res['reason']}",
    }

# =====================================================================
# ۷) سطوح و حجم پوزیشن
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
        return {"rejected": True, "risk_pct": risk_pct}

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
# ۸) ارسال پیام تلگرام
# =====================================================================
_TG = {"lock": threading.Lock(), "ts": 0.0}
TG_MIN_GAP = 1.2

def send_telegram(text):
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
        "🟢 <b>سیگنال خرید (LONG) - ماژول حجمی جدید</b>",
        f"<b>نماد:</b> <code>{symbol}</code>",
        f"<b>استراتژی:</b> شکست کانال ۵۵ ({TIMEFRAME})",
        f"<b>گردش مالی میانه ۳۰ روزه:</b> <code>~{sig['turnover_med']:,.0f}$</code>",
        f"<b>کندل سیگنال:</b> {ts} UTC",
        "",
        f"<b>ورود (مارکت):</b> <code>{fmt_price(lv['entry'])}</code>",
        f"<b>حد ضرر:</b> <code>{fmt_price(lv['sl'])}</code>  (−{lv['risk_pct']:.1f}%)",
        f"<b>حد سود:</b> <code>{fmt_price(lv['tp'])}</code>  (+{lv['tp_pct']:.1f}%)",
        f"<b>R:R:</b> {lv['rr']:.2f} | <b>حداکثر نگهداری:</b> {MAX_HOLD} کندل",
        "",
        f"<b>حجم پیشنهادی:</b> <code>{lv['qty']:.6g}</code> (~{lv['notional']:.1f} USDT)",
        f"<b>ریسک:</b> {lv['risk_usdt']:.2f} USDT",
    ]
    return "\n".join(lines)

def format_exit(pos, result, price, bars_held):
    icon = {"tp": "✅", "sl": "🛑", "time": "⏳"}.get(result, "⚪")
    title = {"tp": "حد سود خورد", "sl": "حد ضرر خورد", "time": "خروج زمانی"}.get(result, result)
    pnl_pct = (price / pos["entry"] - 1) * 100
    r_mult = (price - pos["entry"]) / (pos["entry"] - pos["sl"]) if pos["entry"] != pos["sl"] else 0
    return f"{icon} <b>{title}</b> — <code>{pos['symbol']}</code> | نتیجه: {pnl_pct:+.2f}% | {r_mult:+.2f}R"

# =====================================================================
# ۹) مدیریت State
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
# ۱۰) پیگیری پوزیشن‌های باز
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
        ct = int(pos.get("candle_ts") or pos.get("opened_at") or 0)
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
# ۱۱) چرخه اسکن ربات
# =====================================================================
def run_cycle():
    STATS["scans"] += 1
    prices = get_prices()
    candles_cache = {}
    found = 0

    if not prices and not _PRICE["data"]:
        return {"ok": False, "data_symbols": 0, "signals": 0}

    for symbol in SYMBOLS:
        try:
            df = fetch_candles(symbol)
            if df is None or len(df) < WARMUP:
                continue
            candles_cache[symbol] = df

            sig = evaluate(symbol, df)
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

            ob_res = orderbook_gate(symbol, lv["notional"])
            if not ob_res["ok"]:
                log(f"[Orderbook] سیگنال {symbol} رد شد: {ob_res['reason']}", "warning")
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
        except Exception:
            STATS["errors"] += 1

    try:
        track_open_positions(candles_cache, prices)
    except Exception:
        pass

    save_state()
    return {"ok": len(candles_cache) > 0, "data_symbols": len(candles_cache), "signals": found}

# =====================================================================
# ۱۲) سرور سلامت
# =====================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        if self.path.startswith(("/health", "/stats", "/")):
            closed = STATE["closed"]
            wins = [c for c in closed if c["r"] > 0]
            payload = {
                "status": "ok",
                "version": VERSION,
                "uptime_sec": int(time.time() - STATS["started"]),
                "scans": STATS["scans"],
                "signals": STATS["signals"],
                "errors": STATS["errors"],
                "open_positions": len(STATE["open"]),
                "closed_trades": len(closed),
                "winrate": round(len(wins) / len(closed) * 100, 1) if closed else None,
            }
            self._send(200, json.dumps(payload, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_HEAD(self):
        self._send(200, "{}")

    def log_message(self, *a):
        pass

def start_health_server():
    port = _env_int("PORT", 10000)
    try:
        srv = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"[Health] سرور سلامت روی پورت {port} با موفقیت فعال شد", "ok")
    except Exception as e:
        log(f"[Health] خطا در فعال‌سازی پورت {port}: {e}", "warning")

# =====================================================================
# ۱۳) اجرای اصلی ربات
# =====================================================================
_STOP = {"flag": False}

def _handle_stop(signum, frame):
    _STOP["flag"] = True

CANDLE_OFFSET = _env_int("CANDLE_OFFSET", 1800)

def seconds_to_next_candle():
    now = int(time.time())
    period = PERIOD
    last_close = ((now - CANDLE_OFFSET) // period) * period + CANDLE_OFFSET
    if last_close > now:
        last_close -= period
    return max(0, last_close + period + CANDLE_BUFFER - now)

def price_only_check():
    if not STATE["open"]:
        return
    try:
        prices = get_prices()
        if prices:
            track_open_positions({}, prices)
    except Exception:
        pass

def _sleep(total):
    total = int(total)
    slept = 0
    next_check = PRICE_POLL
    while slept < total and not _STOP["flag"]:
        step = min(5, total - slept)
        time.sleep(max(1, step))
        slept += max(1, step)
        if STATE["open"] and slept >= next_check and not _STOP["flag"]:
            price_only_check()
            next_check += PRICE_POLL

def main():
    # فوری اجرا کردن سرور برای جلوگیری از تایم‌اوت در Render
    start_health_server()
    time.sleep(1)

    log("=" * 66)
    log(f"ربات سیگنال دانچیان ۵۵ (مجهز به ماژول حجم ۳ لایه) | نسخه {VERSION}")
    log(f"تایم‌فریم {TIMEFRAME} | {len(SYMBOLS)} نماد | DRY_RUN={DRY_RUN}")
    log("=" * 66)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    load_state()

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram(f"🤖 <b>ربات دانچیان ۵۵ (نسخه پیشرفته حجم) روشن شد</b>\nتایم‌فریم: {TIMEFRAME}")

    while not _STOP["flag"]:
        HTTP_STATE["hard_fail"] = 0
        result = {"ok": False, "data_symbols": 0, "signals": 0}
        try:
            result = run_cycle() or result
        except Exception:
            STATS["errors"] += 1

        STATS["last_scan"] = int(time.time())

        if HTTP_STATE["hard_fail"] > 0 or not result.get("ok"):
            _sleep(RETRY_BACKOFF)
        elif SCAN_MODE == "interval":
            _sleep(SCAN_INTERVAL)
        else:
            _sleep(seconds_to_next_candle())

if __name__ == "__main__":
    main()
