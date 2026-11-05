# -*- coding: utf-8 -*-
import os
import time
import json
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")

# --- اصلاح ۱: اندپوینت‌های صحیح بیت‌پین (api.bitpin.ir + fallback .org) ---
BITPIN_HOSTS = [
    "https://api.bitpin.ir",
    "https://api.bitpin.org",
]
MARKETS_PATH = "/api/v1/mkt/markets/"
CANDLES_PATH = "/api/v1/mkt/candles/"

# رزولوشن‌های معتبر بیت‌پین (هر مقدار دیگری باعث 500 یا برگشت رزولوشن اشتباه می‌شود)
RES_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
RES_ALIASES = {
    "60": "1h", "1H": "1h", "h1": "1h",
    "240": "4h", "4H": "4h", "h4": "4h",
    "D": "1d", "1D": "1d", "d": "1d", "1D": "1d",
    "2h": "1h", "6h": "4h", "12h": "4h", "1w": "1d",
}

# هدرهای شبیه‌ساز مرورگر برای جلوگیری از خطاهای 403 / 418 / 451
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Referer": "https://bitpin.ir/"
}

# --- اصلاح ۲: سیستم Mirror برای بایننس (فیوچرز + اسپات) ---
BINANCE_FAPI_MIRRORS = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
    "https://fapi4.binance.com",
]
BINANCE_SPOT_MIRRORS = [
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://data-api.binance.vision",
]
BINANCE_TICKER_PATH = "/fapi/v1/ticker/24hr"
BINANCE_SPOT_TICKER_PATH = "/api/v3/ticker/24hr"

# آخرین لایه‌ی Mirror: اگر همه میزبان‌های بایننس بلاک شده باشند (451/403/Proxy)،
# از فید عمومی Bybit (linear/USDT) به عنوان Mirror داده استفاده می‌شود.
BYBIT_MIRRORS = [
    "https://api.bybit.com",
    "https://api.bybit.nl",
    "https://api.bytick.com",
]
BYBIT_TICKER_PATH = "/v5/market/tickers"
BYBIT_TICKER_PARAMS = {"category": "linear"}
# هدر مخصوص Bybit (بدون Referer بیت‌پین، وگرنه Cloudflare خطای 403 می‌دهد)
BYBIT_HEADERS = {
    "User-Agent": BROWSER_HEADERS["User-Agent"],
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# تنظیمات معاملاتی و فیلترها
BOLLINGER_SQUEEZE_THRESHOLD = 2.0
WHALE_VOLUME_THRESHOLD = 500000.0  # ۵۰۰ هزار تتر حجم تجمیعی
SIGNAL_TRACKER_FILE = "signal_tracker.json"

# کش میزبان سالم (برای اینکه هر بار همه Mirror ها تست نشوند)
_HOST_CACHE = {"bitpin": None, "binance": None, "binance_spot": False}
_HOST_CACHE_TTL = 600
_HOST_CACHE_TIME = {"bitpin": 0, "binance": 0}
_BTC_FILTER_CACHE = {"value": False, "ts": 0}


# ================= سرور سلامت رندر (پشتیبانی از متد HEAD و GET) =================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Multi-Strategy & Binance Whale Bot is Running Successfully!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, *args):
        pass


def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


# ================= توابع ارسال تلگرام =================
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send error: {e}")


# ================= ابزار درخواست با چند میزبان (Mirror / Fallback) =================
def _get_json_with_mirrors(hosts, path, params=None, headers=None, timeout=12, cache_key=None):
    """درخواست GET را روی لیست میزبان‌ها امتحان می‌کند و اولین پاسخ سالم را برمی‌گرداند."""
    headers = headers or BROWSER_HEADERS

    # اگر قبلاً میزبان سالمی پیدا شده، اول همان را امتحان کن
    ordered = list(hosts)
    if cache_key and _HOST_CACHE.get(cache_key):
        cached = _HOST_CACHE[cache_key]
        if time.time() - _HOST_CACHE_TIME.get(cache_key, 0) < _HOST_CACHE_TTL and cached in ordered:
            ordered.remove(cached)
            ordered.insert(0, cached)

    last_error = None
    for host in ordered:
        url = host + path
        for attempt in range(2):
            try:
                res = requests.get(url, params=params, headers=headers, timeout=timeout)
                if res.status_code == 200:
                    data = res.json()
                    if cache_key:
                        _HOST_CACHE[cache_key] = host
                        _HOST_CACHE_TIME[cache_key] = time.time()
                    return data, host
                # 451/403/418 یعنی این میزبان در دسترس نیست -> میزبان بعدی
                last_error = f"HTTP {res.status_code} from {host}"
                print(f"[Mirror] {host} -> {res.status_code}")
                break
            except Exception as e:
                last_error = f"{host}: {type(e).__name__}: {e}"
                print(f"[Mirror] {host} failed ({type(e).__name__})")
                time.sleep(0.5)
    print(f"[Mirror] All hosts failed. Last error: {last_error}")
    return None, None


# ================= دریافت داده از بیت‌پین =================
def fetch_bitpin_markets():
    data, host = _get_json_with_mirrors(
        BITPIN_HOSTS, MARKETS_PATH, cache_key="bitpin"
    )
    if data is None:
        return []
    # پاسخ این اندپوینت یک لیست ساده است (نه {"results": ...})
    if isinstance(data, dict):
        markets = data.get("results", data.get("data", []))
    else:
        markets = data
    print(f"[Bitpin Markets] {len(markets)} markets loaded from {host}")
    return markets


def _normalize_resolution(resolution):
    res = str(resolution).strip()
    if res in RES_SECONDS:
        return res
    if res in RES_ALIASES:
        return RES_ALIASES[res]
    return "1h"


def fetch_bitpin_candles(symbol, resolution="1h", limit=100):
    """
    اندپوینت صحیح: GET /api/v1/mkt/candles/?symbol=BTC_IRT&res=1h&from=<unix>&to=<unix>
    نکته: پارامتر limit پشتیبانی نمی‌شود و باعث خطای 500 می‌شود؛ بازه زمانی از from/to ساخته می‌شود.
    """
    res = _normalize_resolution(resolution)
    step = RES_SECONDS[res]

    to_ts = int(time.time())
    from_ts = to_ts - (int(limit) * step)

    params = {
        "symbol": symbol,
        "res": res,
        "from": from_ts,
        "to": to_ts,
    }

    data, host = _get_json_with_mirrors(
        BITPIN_HOSTS, CANDLES_PATH, params=params, cache_key="bitpin"
    )
    if data is None:
        return None

    candles = data if isinstance(data, list) else data.get("results", [])
    if not candles:
        print(f"[Candles] Empty response for {symbol} ({res})")
        return None

    df = pd.DataFrame(candles)
    # بیت‌پین هم "time" (میلی‌ثانیه) و هم "ts" (ثانیه) می‌دهد؛ فقط یکی نگه داشته می‌شود
    if "time" in df.columns and "ts" in df.columns:
        df.drop(columns=["ts"], inplace=True)
    df.rename(columns={
        "time": "timestamp",
        "ts": "timestamp",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }, inplace=True)

    needed = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in needed):
        print(f"[Candles] Unexpected schema for {symbol}: {list(df.columns)}")
        return None

    for col in needed:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
        # اگر timestamp بر حسب ثانیه بود به میلی‌ثانیه تبدیل شود
        if df["timestamp"].max() < 10_000_000_000:
            df["timestamp"] = df["timestamp"] * 1000
        df.sort_values("timestamp", inplace=True)
        df.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)

    df.dropna(subset=needed, inplace=True)
    df.reset_index(drop=True, inplace=True)

    # اعتبارسنجی رزولوشن برگشتی (بیت‌پین برای رزولوشن نامعتبر، رزولوشن دیگری می‌دهد)
    if "resolution" in df.columns and not df.empty:
        returned = str(df["resolution"].iloc[-1])
        if returned != res:
            print(f"[Candles] Warning: requested {res}, server returned {returned} for {symbol}")

    if df.empty:
        return None

    print(f"[Candles] {symbol} | {res} | {len(df)} candles | last close: {df.iloc[-1]['Close']}")
    return df


# ================= موتور رصد نهنگ‌های بایننس (Mirror) =================
def _binance_tickers():
    """تلاش روی Mirror های فیوچرز، سپس اسپات، و در نهایت فید جایگزین Bybit."""
    data, host = _get_json_with_mirrors(
        BINANCE_FAPI_MIRRORS, BINANCE_TICKER_PATH, cache_key="binance"
    )
    if data is not None:
        _HOST_CACHE["binance_spot"] = False
        return data, host, "futures"

    print("[Binance] Futures mirrors unavailable, falling back to SPOT mirrors...")
    data, host = _get_json_with_mirrors(
        BINANCE_SPOT_MIRRORS, BINANCE_SPOT_TICKER_PATH, cache_key="binance"
    )
    if data is not None:
        _HOST_CACHE["binance_spot"] = True
        return data, host, "spot"

    print("[Binance] All Binance mirrors blocked, falling back to BYBIT mirror feed...")
    data, host = _get_json_with_mirrors(
        BYBIT_MIRRORS, BYBIT_TICKER_PATH, params=BYBIT_TICKER_PARAMS,
        headers=BYBIT_HEADERS, cache_key="binance"
    )
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        rows = data["result"].get("list", [])
        # نرمال‌سازی به شکل بایننس
        normalized = [
            {"symbol": r.get("symbol", ""), "quoteVolume": r.get("turnover24h", 0)}
            for r in rows
        ]
        return normalized, host, "bybit"

    return None, None, None


def check_binance_whales():
    data, host, market_type = _binance_tickers()
    if not data:
        print("[Binance Whale] No data from any mirror.")
        return []

    whales = []
    for t in data:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        try:
            quote_volume = float(t.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            continue
        if quote_volume >= WHALE_VOLUME_THRESHOLD:
            whales.append((symbol, quote_volume))

    whales.sort(key=lambda x: x[1], reverse=True)
    print(f"[Binance Whale] {len(whales)} symbols > {WHALE_VOLUME_THRESHOLD:,.0f} USDT "
          f"({market_type} via {host})")
    return whales


# ================= توابع محاسباتی تکنیکال =================
def calculate_indicators(df):
    if df is None or len(df) < 30:
        return None

    close = df["Close"]
    df["EMA200"] = close.ewm(span=200, adjust=False).mean() if len(df) >= 200 else close.ewm(span=len(df), adjust=False).mean()
    df["SMA20"] = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std()

    df["BB_Upper"] = df["SMA20"] + (std20 * 2)
    df["BB_Lower"] = df["SMA20"] - (std20 * 2)
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["SMA20"] * 100

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, pd.NA)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["RSI"] = df["RSI"].fillna(50)

    return df


def check_btc_filter():
    # کش ۵ دقیقه‌ای برای جلوگیری از درخواست تکراری و Rate Limit
    if time.time() - _BTC_FILTER_CACHE["ts"] < 300:
        return _BTC_FILTER_CACHE["value"]

    df_btc = fetch_bitpin_candles("BTC_IRT", "1h", 50)
    result = False
    if df_btc is not None and len(df_btc) > 20:
        df_btc = calculate_indicators(df_btc)
        last = df_btc.iloc[-1]
        if pd.notna(last["SMA20"]) and last["Close"] >= last["SMA20"]:
            result = True

    _BTC_FILTER_CACHE["value"] = result
    _BTC_FILTER_CACHE["ts"] = time.time()
    return result


# ================= استراتژی‌های معاملاتی (۴ گانه) =================
def evaluate_strategies(symbol, df):
    df = calculate_indicators(df)
    if df is None or len(df) < 2:
        return

    last = df.iloc[-1]
    prev = df.iloc[-2]

    vol_mean = df["Volume"].rolling(20).mean().iloc[-1]
    if pd.isna(vol_mean) or pd.isna(last["BB_Lower"]) or pd.isna(last["SMA20"]):
        return

    # ۱. استراتژی سنسی (Sensi)
    if last["Volume"] < (vol_mean * 0.6) and last["Low"] <= last["BB_Lower"] and last["Close"] > prev["Close"]:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (سنسی)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nخشکی حجم در کف و حمایت بولینگر")

    # ۲. استراتژی روند بولینگر (Trend Strategy)
    if last["Close"] <= last["BB_Lower"] and last["Close"] > last["EMA200"] and last["RSI"] < 35:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (روند بولینگر)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nRSI: {last['RSI']:.1f}")

    # ۳. استراتژی پولبک (Pullback Strategy)
    if last["Close"] > last["EMA200"] and prev["Low"] <= last["SMA20"] and last["Close"] > last["SMA20"] and 35 <= last["RSI"] <= 60:
        if check_btc_filter():
            send_telegram_message(f"🟢 <b>سیگنال LONG (پولبک صعودی)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nبرخورد به میانگین متحرک و تایید صعود")

    # ۴. استراتژی شکست و پولبک (Break & Retest - مخصوص SHORT)
    if prev["Close"] < prev["BB_Lower"] and last["Close"] > prev["Close"] and last["Close"] < last["SMA20"] and last["RSI"] > 60:
        send_telegram_message(f"🔴 <b>سیگنال SHORT (شکست و پولبک ناموفق)</b>\nارز: {symbol}\nقیمت: {last['Close']}\nپولبک ناموفق به سطح شکسته شده")


# ================= حلقه اصلی ربات و تست استارت =================
def main_loop():
    print("==================================================")
    print("🚀 Bitpin & Binance Whale Bot Starting Up...")
    print("==================================================")

    threading.Thread(target=run_server, daemon=True).start()

    # --- تست اولیه در لحظه شروع (Startup Test) ---
    print("\n[Startup Test] Running initial connection and data fetch test...")
    test_markets = fetch_bitpin_markets()
    print("[Startup Test] ✅ Bitpin Markets API: SUCCESS" if test_markets
          else "[Startup Test] ❌ Bitpin Markets API: FAILED or Empty")

    test_candles = fetch_bitpin_candles("BTC_IRT", "1h", 30)
    print("[Startup Test] ✅ Bitpin Candles API: SUCCESS" if test_candles is not None
          else "[Startup Test] ❌ Bitpin Candles API: FAILED")

    test_whales = check_binance_whales()
    print(f"[Startup Test] ✅ Binance API: SUCCESS ({len(test_whales)} whales found)" if test_whales
          else "[Startup Test] ⚠️ Binance API: Returned 0 whales or all mirrors blocked.")
    print("==================================================\n")

    while True:
        try:
            whales = check_binance_whales()
            if whales:
                msg = "🐋 <b>گزارش حجم نهنگ‌های بایننس (>500k USDT):</b>\n"
                for sym, vol in whales[:5]:
                    msg += f"- {sym}: {vol:,.0f} USDT\n"
                send_telegram_message(msg)

            markets = fetch_bitpin_markets()
            for m in markets[:15]:
                symbol = m.get("symbol") or m.get("code")
                if symbol and symbol.endswith("_IRT") and m.get("tradable", True):
                    df = fetch_bitpin_candles(symbol, "1h", 100)
                    if df is not None and not df.empty:
                        evaluate_strategies(symbol, df)
                    time.sleep(1)

        except Exception as e:
            print(f"Main loop error: {e}")

        time.sleep(300)


if __name__ == "__main__":
    main_loop()
