# -*- coding: utf-8 -*-
import os
import time
import json
import re
import math
import uuid
import requests
import pandas as pd
import threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==========================================
# 1. تنظیمات و متغیرهای پیکربندی
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = os.getenv("BITPIN_BASE_API", "https://api.bitpin.org/api")
BINANCE_SPOT_BASES = tuple(
    base.rstrip("/") for base in os.getenv(
        "BINANCE_SPOT_BASES",
        "https://data-api.binance.vision,https://api.binance.com,https://www.binance.com"
    ).split(",") if base.strip()
)
PRICE_CHECK_TOLERANCE_PCT = float(os.getenv("PRICE_CHECK_TOLERANCE_PCT", 1.0))
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"

BB_PERIOD = int(os.getenv("BB_PERIOD", 20))
BB_STD = float(os.getenv("BB_STD", 2.0))

BITPIN_ENTRY_FEE_RATE = float(os.getenv("BITPIN_ENTRY_FEE_RATE", 0.001))
BITPIN_EXIT_FEE_RATE = float(os.getenv("BITPIN_EXIT_FEE_RATE", 0.001))
ESTIMATED_ROUND_TRIP_FEE = BITPIN_ENTRY_FEE_RATE + BITPIN_EXIT_FEE_RATE
NET_PROFIT_UNITS = float(os.getenv("NET_PROFIT_UNITS", 1.0))
BOLLINGER_SQUEEZE_THRESHOLD = float(os.getenv("BOLLINGER_SQUEEZE_THRESHOLD", 1.75))
TRACKER_FILE = os.getenv("TRACKER_FILE", "signal_tracker.json")
TIMEFRAME = os.getenv("TIMEFRAME", "15")

PULLBACK_MIN_VOLUME_MULT = float(os.getenv("PULLBACK_MIN_VOLUME_MULT", 1.1))
SENSI_DEAD_VOLUME_STREAK = int(os.getenv("SENSI_DEAD_VOLUME_STREAK", 10))
SENSI_DEAD_VOLUME_RATIO = float(os.getenv("SENSI_DEAD_VOLUME_RATIO", 0.5))
SENSI_SHORT_DEAD_FLOOR_BUFFER = float(os.getenv("SENSI_SHORT_DEAD_FLOOR_BUFFER", 1.10))

tracker_lock = threading.RLock()
signal_tracker = {}

BR_MAX_RETEST_CANDLES = 8
BR_RETEST_TOLERANCE_PCT = 0.0015
BR_BREAKOUT_VOL_MULT = 1.5
BR_MIN_BREAKOUT_BODY_RATIO = 0.55
BR_MIN_REJECTION_BODY_RATIO = 0.30
BR_PENDING_SHORT = {}
BR_LAST_PROCESSED = {}
BR_PENDING_LONG = {}

MARGIN_SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT",
    "ADA_USDT", "AVAX_USDT", "SUI_USDT", "LINK_USDT", "NEAR_USDT",
    "DOT_USDT", "APT_USDT", "LTC_USDT", "BCH_USDT", "UNI_USDT",
    "FET_USDT", "RENDER_USDT", "PEPE_USDT", "SHIB_USDT", "PAXG_USDT",
    "ARB_USDT", "OP_USDT", "INJ_USDT", "TIA_USDT", "ATOM_USDT",
    "FIL_USDT", "ETC_USDT", "AAVE_USDT", "RUNE_USDT", "KAS_USDT",
    "TON_USDT", "GALA_USDT", "FTM_USDT", "SAND_USDT", "MANA_USDT"
]

# وضعیت سلامت سیستم
system_health = {
    "boot_time": datetime.now(timezone.utc),
    "last_successful_scan": None,
    "last_bitpin_status": "Unknown",
    "last_binance_status": "Unknown",
    "scan_count": 0,
    "signals_sent": 0
}

# ==========================================
# 2. وب سرور و پینگ برای زنده نگه‌داشتن در Render
# ==========================================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        uptime_sec = int((datetime.now(timezone.utc) - system_health["boot_time"]).total_seconds())
        resp = {
            "status": "healthy",
            "uptime_seconds": uptime_sec,
            "last_scan": str(system_health["last_successful_scan"]),
            "bitpin": system_health["last_bitpin_status"],
            "binance": system_health["last_binance_status"],
            "signals_sent": system_health["signals_sent"]
        }
        self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

def self_ping():
    while True:
        try:
            time.sleep(600)
            if APP_URL and not APP_URL.startswith("http://localhost"):
                requests.get(APP_URL, timeout=10)
        except Exception:
            pass

# ==========================================
# 3. تلگرام
# ==========================================
def send_telegram(text, parse_mode="HTML"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Token not configured.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as exc:
        print(f"[Telegram Error] {exc}")
        return False

# ==========================================
# 4. واکشی داده‌های بازار (بیت‌پین و بایننس)
# ==========================================
def _binance_get(path, params=None, timeout=8):
    """واکشی از میرورهای اسپات بایننس با امکان فال‌بک."""
    last_err = None
    for base in BINANCE_SPOT_BASES:
        try:
            url = base + path
            r = requests.get(url, params=params or {}, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                system_health["last_binance_status"] = "OK"
                return r.json()
            elif r.status_code in (403, 451):
                last_err = f"Geo-blocked ({r.status_code})"
                continue
        except Exception as e:
            last_err = str(e)
            continue
    system_health["last_binance_status"] = f"Error: {last_err}"
    raise RuntimeError(f"All Binance spot mirrors failed. Last error: {last_err}")

def fetch_bitpin_ticker_price(market_code):
    try:
        url = f"{BASE_API}/v1/mkt/tickers/"
        res = requests.get(url, timeout=7)
        if res.status_code == 200:
            system_health["last_bitpin_status"] = "OK"
            data = res.json()
            for item in data.get("results", []):
                if item.get("code") == market_code:
                    return float(item.get("price"))
    except Exception as e:
        system_health["last_bitpin_status"] = f"Ticker Error: {e}"
    return None

def compare_binance_bitpin_price(market_code, bitpin_price=None, binance_symbol=None):
    market_code = str(market_code).upper()
    if not binance_symbol:
        base = market_code[:-5] if market_code.endswith("_USDT") else market_code.replace("_", "")
        binance_symbol = base + "USDT"

    try:
        bitpin = float(bitpin_price) if bitpin_price is not None else fetch_bitpin_ticker_price(market_code)
        if not bitpin or bitpin <= 0:
            return False, None, None, None

        payload = _binance_get("/api/v3/ticker/price", params={"symbol": binance_symbol}, timeout=6)
        binance = float(payload.get("price", 0))
        if binance <= 0:
            return False, bitpin, None, None

        diff_pct = abs(bitpin - binance) / binance * 100.0
        passed = diff_pct <= PRICE_CHECK_TOLERANCE_PCT
        return passed, bitpin, binance, diff_pct
    except Exception as exc:
        print(f"[Price Check Fallback] {market_code}: {exc}")
        # اگر بایننس کاملاً قطع بود، اجازه عبور محتاطانه با قیمت بیت‌پین
        return True, bitpin, None, 0.0

def fetch_bitpin_candles(symbol, resolution="15", count=300):
    url = f"{OHLC_URL}?symbol={symbol}&resolution={resolution}&count={count}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                cols = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
                for k in cols:
                    if k in df.columns:
                        df[k] = pd.to_numeric(df[k], errors="coerce")
                return df.dropna().reset_index(drop=True)
    except Exception as e:
        print(f"[Candles Error] {symbol}: {e}")
    return None

# ==========================================
# 5. اندیکاتورها و محاسبات تکنیکال
# ==========================================
def calculate_indicators(df):
    if df is None or len(df) < 55:
        return None
    d = df.copy()
    c = d["close"]
    
    # بولینگر
    d["bb_mid"] = c.rolling(BB_PERIOD).mean()
    d["bb_std"] = c.rolling(BB_PERIOD).std()
    d["bb_upper"] = d["bb_mid"] + (BB_STD * d["bb_std"])
    d["bb_lower"] = d["bb_mid"] - (BB_STD * d["bb_std"])
    d["bandwidth"] = ((d["bb_upper"] - d["bb_lower"]) / d["bb_mid"]) * 100.0

    # EMA و Volume MA
    d["ema200"] = c.ewm(span=200, adjust=False).mean()
    d["vol_ma20"] = d["volume"].rolling(20).mean()

    # RSI
    delta = c.diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    d["rsi"] = 100 - (100 / (1 + rs))

    # ATR
    hl = d["high"] - d["low"]
    hc = (d["high"] - c.shift()).abs()
    lc = (d["low"] - c.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()

    return d

def bollinger_stop(direction, row, atr_mult=0.2):
    atr = row.get("atr", 0) or 0
    if direction == "LONG":
        return float(row["bb_lower"] - (atr_mult * atr))
    else:
        return float(row["bb_upper"] + (atr_mult * atr))

def risk_target(entry, sl, direction, rr=1.5):
    risk = abs(entry - sl)
    if direction == "LONG":
        tp = entry + (risk * rr)
    else:
        tp = entry - (risk * rr)
    return tp

def format_price(p):
    if p is None: return "0.00"
    if p >= 100: return f"{p:,.2f}"
    if p >= 1: return f"{p:,.4f}"
    return f"{p:,.6f}"

# ==========================================
# 6. ساخت سیگنال و فیلترها
# ==========================================
def build_signal(symbol, direction, strategy_name, entry, sl, tp1, tp2=None):
    passed, bitpin_p, binance_p, diff = compare_binance_bitpin_price(symbol, bitpin_price=entry)
    if not passed:
        return None

    entry_clean = bitpin_p or entry
    direction_fa = "خرید (LONG) 🟢" if direction == "LONG" else "فروش تعهدی (SHORT) 🔴"
    
    text = (
        f"🚨 <b>سیگنال معاملاتی جدید</b>\n"
        f"نماد: <b>{symbol}</b>\n"
        f"جهت: <b>{direction_fa}</b>\n"
        f"استراتژی: <b>{strategy_name}</b>\n\n"
        f"🔹 نقطه ورود: <code>{format_price(entry_clean)}</code>\n"
        f"🎯 تارگت اول: <code>{format_price(tp1)}</code>\n"
    )
    if tp2:
        text += f"🎯 تارگت دوم: <code>{format_price(tp2)}</code>\n"
    text += (
        f"🛑 حد ضرر: <code>{format_price(sl)}</code>\n"
        f"⏱ تایم‌فریم: <b>{TIMEFRAME} دقیقه</b>\n"
    )
    if binance_p:
        text += f"📊 قیمت بایننس: <code>{format_price(binance_p)}</code> (اختلاف: {diff:.2f}%)\n"

    return text

# ==========================================
# 7. استراتژی‌های معاملاتی
# ==========================================
def check_sensi_strategy(df, symbol, is_margin=True):
    if df is None or len(df) < 55: return None
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    # فیلتر حجم مرده
    recent_vol = df["volume"].iloc[-SENSI_DEAD_VOLUME_STREAK:]
    avg_vol = df["vol_ma20"].iloc[-1]
    if (recent_vol < (avg_vol * SENSI_DEAD_VOLUME_RATIO)).all():
        return None

    c, o, h, l = row["close"], row["open"], row["high"], row["low"]
    
    # بازگشت صعودی
    if prev["close"] <= prev["bb_lower"] and c > o and c > prev["high"]:
        entry = c
        sl = bollinger_stop("LONG", row)
        tp1 = risk_target(entry, sl, "LONG", rr=1.5)
        tp2 = risk_target(entry, sl, "LONG", rr=2.5)
        return "LONG", "بازگشت سنسی", entry, sl, tp1, tp2

    # بازگشت نزولی
    if is_margin and prev["close"] >= prev["bb_upper"] and c < o and c < prev["low"]:
        entry = c
        sl = bollinger_stop("SHORT", row)
        tp1 = risk_target(entry, sl, "SHORT", rr=1.5)
        tp2 = risk_target(entry, sl, "SHORT", rr=2.5)
        return "SHORT", "بازگشت سنسی", entry, sl, tp1, tp2

    return None

def check_trend_strategy(df, symbol, is_margin=True):
    if df is None or len(df) < 55: return None
    row = df.iloc[-1]
    c = row["close"]
    
    if c <= row["bb_lower"] and c > row["ema200"] and row["rsi"] < 35:
        entry = c
        sl = min(row["low"], bollinger_stop("LONG", row))
        tp1 = risk_target(entry, sl, "LONG", rr=1.6)
        return "LONG", "بازگشت روند بولینگر", entry, sl, tp1, None

    if is_margin and c >= row["bb_upper"] and c < row["ema200"] and row["rsi"] > 65:
        entry = c
        sl = max(row["high"], bollinger_stop("SHORT", row))
        tp1 = risk_target(entry, sl, "SHORT", rr=1.6)
        return "SHORT", "بازگشت روند بولینگر", entry, sl, tp1, None

    return None

def check_pullback_strategy(df, symbol, is_margin=True):
    if df is None or len(df) < 55: return None
    row = df.iloc[-1]
    prev = df.iloc[-2]
    c = row["close"]

    if c > row["ema200"] and prev["low"] <= row["bb_mid"] and c > row["bb_mid"] and row["volume"] >= row["vol_ma20"] * PULLBACK_MIN_VOLUME_MULT:
        entry = c
        sl = row["bb_lower"]
        tp1 = risk_target(entry, sl, "LONG", rr=1.8)
        return "LONG", "پولبک روند صعودی", entry, sl, tp1, None

    if is_margin and c < row["ema200"] and prev["high"] >= row["bb_mid"] and c < row["bb_mid"] and row["volume"] >= row["vol_ma20"] * PULLBACK_MIN_VOLUME_MULT:
        entry = c
        sl = row["bb_upper"]
        tp1 = risk_target(entry, sl, "SHORT", rr=1.8)
        return "SHORT", "پولبک روند نزولی", entry, sl, tp1, None

    return None

# ==========================================
# 8. ثبت و ارسال سیگنال
# ==========================================
recent_signals_cache = {}

def register_and_send(symbol, direction, strategy_name, entry, sl, tp1, tp2=None):
    now = datetime.now(timezone.utc)
    dedup_key = f"{symbol}_{direction}_{strategy_name}"
    
    if dedup_key in recent_signals_cache:
        last_time = recent_signals_cache[dedup_key]
        if (now - last_time).total_seconds() < 3600: # جلوگیری از ارسال تکراری تا ۱ ساعت
            return

    msg = build_signal(symbol, direction, strategy_name, entry, sl, tp1, tp2)
    if msg and send_telegram(msg):
        recent_signals_cache[dedup_key] = now
        system_health["signals_sent"] += 1
        print(f"[SIGNAL SENT] {symbol} {direction} via {strategy_name}")

# ==========================================
# 9. بررسی پیام‌ها و دستورات تلگرام (/stats, /ping)
# ==========================================
def telegram_command_handler():
    offset = 0
    while True:
        try:
            if not TELEGRAM_BOT_TOKEN:
                time.sleep(10); continue
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            r = requests.get(url, params={"offset": offset, "timeout": 20}, timeout=30)
            if r.status_code == 200:
                data = r.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "").strip().lower()
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    
                    if chat_id != str(TELEGRAM_CHAT_ID):
                        continue

                    if text in ("/ping", "/health"):
                        uptime = str(datetime.now(timezone.utc) - system_health["boot_time"]).split(".")[0]
                        res = (
                            f"🏓 <b>ربات کاملاً آنلاین و فعال است!</b>\n\n"
                            f"⏱ <b>Uptime:</b> {uptime}\n"
                            f"📡 <b>اتصال بیت‌پین:</b> {system_health['last_bitpin_status']}\n"
                            f"🌐 <b>اتصال بایننس:</b> {system_health['last_binance_status']}\n"
                            f"🔄 <b>تعداد اسکن‌ها:</b> {system_health['scan_count']}\n"
                            f"🎯 <b>سیگنال‌های ارسالی:</b> {system_health['signals_sent']}\n"
                            f"🕒 <b>آخرین اسکن موفق:</b> {system_health['last_successful_scan'] or 'درحال انجام...'}"
                        )
                        send_telegram(res)

                    elif text == "/stats":
                        res = (
                            f"📊 <b>آمار سیگنال‌دهی ربات:</b>\n\n"
                            f"کل سیگنال‌های این اجرا: <b>{system_health['signals_sent']}</b>\n"
                            f"ارزهای تحت نظر: <b>{len(MARGIN_SYMBOLS)} جفت‌ارز مارجین</b>\n"
                            f"تایم فریم تحلیل: <b>{TIMEFRAME} دقیقه</b>"
                        )
                        send_telegram(res)

        except Exception as e:
            time.sleep(5)
        time.sleep(2)

# ==========================================
# 10. گزارش سلامت دوره‌ای (Heartbeat خودکار هر ۱ ساعت)
# ==========================================
def hourly_heartbeat():
    while True:
        try:
            time.sleep(3600)  # هر ۱ ساعت یکبار
            uptime = str(datetime.now(timezone.utc) - system_health["boot_time"]).split(".")[0]
            msg = (
                f"💓 <b>گزارش سلامت خودکار ربات (Heartbeat)</b>\n\n"
                f"✅ سرور و اسکنر فعال هستند.\n"
                f"⏳ مدت زمان روشن بودن: {uptime}\n"
                f"📡 وضعیت وب‌سرویس بیت‌پین: <code>{system_health['last_bitpin_status']}</code>\n"
                f"🌐 وضعیت وب‌سرویس بایننس: <code>{system_health['last_binance_status']}</code>\n"
                f"🎯 مجموع سیگنال‌های صادرشده: <b>{system_health['signals_sent']}</b>"
            )
            send_telegram(msg)
        except Exception:
            pass

# ==========================================
# 11. حلقه اصلی اسکنر بازار
# ==========================================
def run_scanner():
    print("Market scanner started successfully.")
    start_msg = (
        "🚀 <b>ربات تحلیل‌گر بیت‌پین با موفقیت راه‌اندازی شد!</b>\n\n"
        f"✅ پایش {len(MARGIN_SYMBOLS)} جفت‌ارز تعهدی (مارجین)\n"
        "✅ ماژول سلامت و دستورات تلگرام فعال شد.\n"
        "💡 می‌توانید برای اطمینان دستور <code>/ping</code> را ارسال کنید."
    )
    send_telegram(start_msg)

    while True:
        try:
            for symbol in MARGIN_SYMBOLS:
                df = fetch_bitpin_candles(symbol, resolution=TIMEFRAME, count=100)
                if df is not None and not df.empty:
                    df_ind = calculate_indicators(df)
                    if df_ind is not None:
                        # بررسی فشردگی بولینگر
                        if df_ind.iloc[-1]["bandwidth"] < BOLLINGER_SQUEEZE_THRESHOLD:
                            time.sleep(0.2); continue

                        # بررسی استراتژی‌ها
                        res_sensi = check_sensi_strategy(df_ind, symbol, is_margin=True)
                        if res_sensi:
                            d, st, e, sl, tp1, tp2 = res_sensi
                            register_and_send(symbol, d, st, e, sl, tp1, tp2)

                        res_trend = check_trend_strategy(df_ind, symbol, is_margin=True)
                        if res_trend:
                            d, st, e, sl, tp1, tp2 = res_trend
                            register_and_send(symbol, d, st, e, sl, tp1, tp2)

                        res_pullback = check_pullback_strategy(df_ind, symbol, is_margin=True)
                        if res_pullback:
                            d, st, e, sl, tp1, tp2 = res_pullback
                            register_and_send(symbol, d, st, e, sl, tp1, tp2)

                time.sleep(0.25)

            system_health["last_successful_scan"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
            system_health["scan_count"] += 1
            time.sleep(15)  # استراحت کوتاه بین چرخه‌های کامل بازار

        except Exception as e:
            print(f"[Scanner Loop Error] {e}")
            time.sleep(10)

# ==========================================
# 12. نقطه اجرای اصلی برنامه
# ==========================================
if __name__ == "__main__":
    # ۱. وب‌سرور برای Render
    threading.Thread(target=run_http_server, daemon=True).start()
    # ۲. جلوگیری از خاموشی سرور رایگان
    threading.Thread(target=self_ping, daemon=True).start()
    # ۳. مدیریت پیام‌ها و دستورات تلگرام (/ping و /stats)
    threading.Thread(target=telegram_command_handler, daemon=True).start()
    # ۴. ارسال گزارش سلامت ساعتی
    threading.Thread(target=hourly_heartbeat, daemon=True).start()
    
    # ۵. اجرای حلقه اسکن در ریسه اصلی
    run_scanner()
