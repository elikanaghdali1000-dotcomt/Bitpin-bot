# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo"
TELEGRAM_CHAT_ID = "6643451227"
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/tv/history/"
TICKERS_URL = f"{BASE_API}/v1/mkt/tickers/"

BB_PERIOD = 20
BB_STD = 2.0

CHECK_INTERVAL = 60   # هر ۱ دقیقه چک می‌کند تا به بازه پایانی برسد
TIMEFRAME = "60"      # تایم‌فریم ۱ ساعته

# لیست نمادهای مارجین (۱۰۰ نماد)
MARGIN_SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT", "ADA_USDT", "DOGE_USDT", "AVAX_USDT", "TRX_USDT", "LINK_USDT",
    "DOT_USDT", "MATIC_USDT", "SHIB_USDT", "LTC_USDT", "BCH_USDT", "UNI_USDT", "NEAR_USDT", "ATOM_USDT", "ICP_USDT", "APT_USDT",
    "RENDER_USDT", "INJ_USDT", "OP_USDT", "ARB_USDT", "FIL_USDT", "TIA_USDT", "POL_USDT", "STX_USDT", "IMX_USDT", "GRT_USDT",
    "RUNE_USDT", "SUI_USDT", "SEI_USDT", "FET_USDT", "FLOKI_USDT", "PEPE_USDT", "WIF_USDT", "BONK_USDT", "JUP_USDT", "PENDLE_USDT",
    "PYTH_USDT", "ENA_USDT", "OM_USDT", "ONDO_USDT", "ALT_USDT", "MANTA_USDT", "ZETA_USDT", "DYM_USDT", "PIXEL_USDT", "PORTAL_USDT",
    "AXL_USDT", "SAGA_USDT", "TNSR_USDT", "BOME_USDT", "SLERF_USDT", "AEVO_USDT", "ETHFI_USDT", "REZ_USDT", "BB_USDT", "NOT_USDT",
    "IO_USDT", "ZK_USDT", "LISTA_USDT", "BLUM_USDT", "DOGS_USDT", "CATI_USDT", "HMSTR_USDT", "EIGEN_USDT", "SCR_USDT", "GOAT_USDT",
    "MOODENG_USDT", "PNUT_USDT", "ACT_USDT", "CHILLGUY_USDT", "PENGU_USDT", "VIRTUAL_USDT", "AI_USDT", "XAI_USDT", "ACE_USDT", "NFP_USDT",
    "AI16Z_USDT", "FARTCOIN_USDT", "MELANIA_USDT", "TRUMP_USDT", "VINE_USDT", "BERA_USDT", "KAIA_USDT", "SWELL_USDT", "USUAL_USDT", "COW_USDT",
    "HMSTR_USDT", "CATI_USDT", "DOGS_USDT", "NEIRO_USDT", "TURBO_USDT", "BRETT_USDT", "MEW_USDT", "BENDOG_USDT", "POPCAT_USDT", "MYRO_USDT"
]

# لیست نمادهای اسپات (۲۰ نماد - فقط لانگ)
SPOT_ONLY_MARKETS = [
    "ARPA_USDT", "CHZ_USDT", "CRV_USDT", "ENJ_USDT", "GALA_USDT", "GMT_USDT", "HBAR_USDT", "KAVA_USDT", "LDO_USDT", "MASK_USDT",
    "OCEAN_USDT", "SAND_USDT", "SNX_USDT", "SUSHI_USDT", "THETA_USDT", "WOO_USDT", "ZIL_USDT", "BAT_USDT", "ZRX_USDT", "CKB_USDT"
]

# ترکیب کل نمادها (بدون تکرار)
ALL_SYMBOLS = list(set(MARGIN_SYMBOLS + SPOT_ONLY_MARKETS))

# حافظه برای جلوگیری از ارسال سیگنال تکراری در یک کندل
SENT_KEYS = set()

# ================= سرور HTTP برای زنده نگه داشتن روی Render =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is Running Successfully!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        # غیرفعال کردن لاگ‌های اضافی درخواست HTTP برای تمیز ماندن کنسول
        pass

def run_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# ================= توابع تلگرام و قیمت بیت‌کوین =================
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        return response.json()
    except Exception as e:
        print(f"خطا در ارسال پیام تلگرام: {e}")
        return None

def get_btc_price():
    """دریافت قیمت زنده بیت‌کوین از تیکرهای بیت‌کوین با فال‌بک به OHLC"""
    try:
        res = requests.get(TICKERS_URL, timeout=10)
        if res.status_code == 200:
            data = res.json()
            # فرمت پاسخ بیت‌پین ممکن است لیست یا دیکشنری باشد
            results = data.get("results", data) if isinstance(data, dict) else data
            if isinstance(results, list):
                for item in results:
                    symbol = item.get("title", item.get("code", ""))
                    if symbol in ["BTC_USDT", "BTC/USDT"]:
                        price = item.get("price", item.get("price_info", {}).get("price"))
                        if price:
                            return f"{float(price):,.2f}"
    except Exception:
        pass

    # فال‌بک به کندل‌های تاریخی در صورت خطا در تیکرها
    try:
        df = get_ohlc("BTC_USDT", "60", limit=2)
        if df is not None and not df.empty:
            return f"{df.iloc[-1]['close']:,.2f}"
    except Exception:
        pass

    return "نامشخص"

# ================= توابع پردازش داده و تحلیل تکنیکال =================
def get_ohlc(symbol, resolution="60", limit=250):
    try:
        now_ts = int(time.time())
        # محاسبه بازه زمانی مناسب برای دریافت کندل‌ها
        from_ts = now_ts - (limit * int(resolution) * 60)
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": now_ts
        }
        res = requests.get(OHLC_URL, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "s" in data and data["s"] == "ok":
                df = pd.DataFrame({
                    "time": data.get("t", []),
                    "open": data.get("o", []),
                    "high": data.get("h", []),
                    "low": data.get("l", []),
                    "close": data.get("c", []),
                    "volume": data.get("v", [])
                })
                if not df.empty:
                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    return df.dropna()
    except Exception as e:
        print(f"خطا در دریافت دیتا برای {symbol}: {e}")
    return None

def calculate_indicators(df):
    if df is None or len(df) < BB_PERIOD + 5:
        return None
    
    # میانگین متحرک نمایی ۲۰۰ کندله (روند)
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    
    # باندهای بولینگر
    df["bb_middle"] = df["close"].rolling(window=BB_PERIOD).mean()
    rolling_std = df["close"].rolling(window=BB_PERIOD).std()
    df["bb_upper"] = df["bb_middle"] + (rolling_std * BB_STD)
    df["bb_lower"] = df["bb_middle"] - (rolling_std * BB_STD)
    
    # میانگین متحرک حجم (۲۰ کندل)
    df["vol_sma"] = df["volume"].rolling(window=20).mean()
    
    # شاخص قدرت نسبی RSI (دوره ۱۴)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    loss = loss.replace(0, 0.001)  # محافظت در برابر تقسیم بر صفر
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    
    # میانگین محدوده واقعی ATR (دوره ۱۴)
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=14).mean()
    
    return df

# ================= حلقه اصلی ربات و بررسی بازار =================
def analyze_market():
    global SENT_KEYS
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] شروع اسکن بازار...")
    
    for symbol in ALL_SYMBOLS:
        df = get_ohlc(symbol, TIMEFRAME, limit=250)
        if df is None or len(df) < 205:
            continue
            
        df = calculate_indicators(df)
        if df is None:
            continue
            
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # کلیدتگ یکتا برای جلوگیری از ارسال تکراری سیگنال در این کندل
        candle_time = int(last["time"])
        signal_key_base = f"{symbol}_{candle_time}"
        
        close_p = last["close"]
        ema_200 = last["ema_200"]
        rsi = last["rsi"]
        atr = last["atr"]
        vol = last["volume"]
        vol_sma = last["vol_sma"]
        
        is_margin = symbol in MARGIN_SYMBOLS
        
        # ---------------- 1. سیگنال لانگ (خرید) ----------------
        # شرایط: قیمت بالای EMA200، پولبک با حجم خشک (حجم کمتر یا مساوی ۷۰٪ میانگین حجم)
        if close_p > ema_200 and vol <= (vol_sma * 0.7):
            key = f"LONG_{signal_key_base}"
            if key not in SENT_KEYS:
                sl = close_p - (1.5 * atr)
                tp1 = close_p + (2.0 * atr)
                tp2 = close_p + (3.5 * atr)
                
                msg = (
                    f"🟢 <b>سیگنال لانگ (Long)</b>\n"
                    f"💎 ارز: <code>{symbol}</code>\n"
                    f"📊 قیمت ورود: <code>{close_p}</code>\n"
                    f"📉 حد ضرر (SL): <code>{sl:.4f}</code>\n"
                    f"🎯 هدف اول (TP1): <code>{tp1:.4f}</code>\n"
                    f"🎯 هدف دوم (TP2): <code>{tp2:.4f}</code>\n"
                    f"💧 حجم خشک پولبک: تایید شد ✅"
                )
                send_telegram_message(msg)
                SENT_KEYS.add(key)

        # ---------------- 2. سیگنال شورت (فروش) - فقط برای مارجین ----------------
        if is_margin and close_p < ema_200 and vol <= (vol_sma * 0.7):
            key = f"SHORT_{signal_key_base}"
            if key not in SENT_KEYS:
                sl = close_p + (1.5 * atr)
                tp1 = close_p - (2.0 * atr)
                tp2 = close_p - (3.5 * atr)
                
                msg = (
                    f"🔴 <b>سیگنال شورت (Short)</b>\n"
                    f"💎 ارز: <code>{symbol}</code>\n"
                    f"📊 قیمت ورود: <code>{close_p}</code>\n"
                    f"📈 حد ضرر (SL): <code>{sl:.4f}</code>\n"
                    f"🎯 هدف اول (TP1): <code>{tp1:.4f}</code>\n"
                    f"🎯 هدف دوم (TP2): <code>{tp2:.4f}</code>\n"
                    f"💧 حجم خشک پولبک: تایید شد ✅"
                )
                send_telegram_message(msg)
                SENT_KEYS.add(key)

        # پاکسازی حافظه کلیدهای قدیمی‌تر برای جلوگیری از ازدحام حافظه
        if len(SENT_KEYS) > 1000:
            SENT_KEYS = set(list(SENT_KEYS)[-500:])

def main_loop():
    btc_price = get_btc_price()
    startup_msg = (
        f"🤖 <b>ربات ترید تتری (۱۰۰ تعهدی + ۲۰ اسپات) روشن شد.</b>\n"
        f"📊 قیمت بیت‌کوین (سلامت سنج): <code>{btc_price} USDT</code>\n"
        f"⏱ اسکن بازار فعال در ۵ دقیقه پایانی هر ساعت (با فیلتر حجم خشک در پولبک)."
    )
    send_telegram_message(startup_msg)
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            current_minute = now.minute
            
            # اسکن و تایید سیگنال‌ها صرفاً در ۵ دقیقه پایانی هر ساعت (دقیقه ۵۵ تا ۵۹) جهت تثبیت کندل و حجم
            if 55 <= current_minute <= 59:
                analyze_market()
                # خواب طولانی‌تر تا از اجرای مکرر در بازه پایانی جلوگیری شود
                time.sleep(250)
            else:
                # بررسی زمان هر ۶۰ ثانیه یک‌بار
                time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"خطای غیرمنتظره در حلقه اصلی: {e}")
            time.sleep(60)

if __name__ == "__main__":
    # راه‌اندازی وب‌سرویس keep-alive در یک ترد جداگانه جهت پاسخ به پینگ‌های Render
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # اجرای حلقه اصلی ربات
    main_loop()
