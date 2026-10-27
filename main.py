# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = "secret-038f71e1"
TELEGRAM_CHAT_ID = "6643451227"
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/tv/history/"
TICKERS_URL = "https://api.bitpin.org/v1/mkt/tickers/"

BB_PERIOD = 20
BB_STD = 2.0

CHECK_INTERVAL = 60   # هر ۱ دقیقه چک می‌کند تا به بازه پایانی برسد
TIMEFRAME = "60"      # کندل‌های ۱ ساعته

EMA_TREND_PERIOD = 200
ATR_PERIOD = 14
RSI_PERIOD = 14

# -------------------------------------------------------------
# ۱. نمادهای تعهدی (۱۰۰ نماد تتری - امکان لانگ و شورت)
# -------------------------------------------------------------
MARGIN_SYMBOLS = [
    # L1 & Majors
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "BNB_USDT", "XRP_USDT", "ADA_USDT", "AVAX_USDT", 
    "NEAR_USDT", "DOT_USDT", "TRX_USDT", "ETC_USDT", "ICP_USDT", "APT_USDT", "SUI_USDT", 
    "KAS_USDT", "TON_USDT", "FTM_USDT", "ALGO_USDT", "ATOM_USDT", "HBAR_USDT",
    
    # Layer 2 & Scaling
    "MATIC_USDT", "OP_USDT", "ARB_USDT", "IMX_USDT", "MNT_USDT", "STRK_USDT", 
    "MANTA_USDT", "METIS_USDT", "ZETA_USDT", "BOBA_USDT",
    
    # AI & Big Data
    "RENDER_USDT", "FET_USDT", "AGIX_USDT", "OCEAN_USDT", "ARKM_USDT", "WLD_USDT", 
    "IO_USDT", "AI_USDT", "PHB_USDT",
    
    # Memes (High Volatility & Volume)
    "PEPE_USDT", "SHIB_USDT", "DOGE_USDT", "FLOKI_USDT", "BONK_USDT", "WIF_USDT", 
    "MEME_USDT", "BOME_USDT", "SATS_USDT", "ORDI_USDT", "NOT_USDT", "DOGS_USDT", 
    "HMSTR_USDT", "CATI_USDT", "MYRO_USDT", "SLERF_USDT", "BTT_USDT", "PEOPLE_USDT",
    
    # DeFi & DEX
    "UNI_USDT", "AAVE_USDT", "MKR_USDT", "CRV_USDT", "SNX_USDT", "COMP_USDT", 
    "1INCH_USDT", "SUSHI_USDT", "DYDX_USDT", "JUP_USDT", "PENDLE_USDT", "GMX_USDT", 
    "RUNE_USDT", "CAKE_USDT", "LDO_USDT", "ENS_USDT", "BAL_USDT", "FXS_USDT",
    
    # Infrastructure & Storage / Web3
    "FIL_USDT", "AR_USDT", "GRT_USDT", "STX_USDT", "TIA_USDT", "SEI_USDT", "INJ_USDT", 
    "PYTH_USDT", "ZRO_USDT", "BLUR_USDT", "PORTAL_USDT", "ALT_USDT", "PIXEL_USDT", 
    "REZ_USDT", "BB_USDT", "SAGA_USDT", "ZK_USDT", "BLAST_USDT", "CFX_USDT", "FLOW_USDT",
    
    # Others & Classics (ZEC, Privacy & Legacy)
    "ZEC_USDT", "LTC_USDT", "BCH_USDT", "XLM_USDT", "EOS_USDT", "XTZ_USDT", "EGLD_USDT", 
    "THETA_USDT", "CHZ_USDT", "ENJ_USDT", "GMT_USDT", "SAND_USDT", "MANA_USDT", 
    "AXS_USDT", "GALA_USDT", "DYM_USDT", "QNT_USDT", "MINA_USDT", "KLAY_USDT", "ZIL_USDT"
]

# -------------------------------------------------------------
# ۲. نمادهای اسپات تتری (۲۰ نماد - فقط امکان لانگ / خرید)
# -------------------------------------------------------------
SPOT_ONLY_MARKETS = [
    "AVNT_USDT", "POND_USDT", "POL_USDT", "TURBO_USDT", "POLIS_USDT",
    "DEGO_USDT", "STG_USDT", "UMA_USDT", "API3_USDT", "RAD_USDT",
    "RLC_USDT", "CTSI_USDT", "DATA_USDT", "IDEX_USDT", "CREAM_USDT", 
    "PERP_USDT", "UNFI_USDT", "OXT_USDT", "CELO_USDT", "AUDIO_USDT"
]

# تمام ۱۲۰ نمادی که ربات پایش می‌کند
ALL_SYMBOLS = MARGIN_SYMBOLS + SPOT_ONLY_MARKETS

SENT_KEYS = set()

# سشن با قابلیت Retry خودکار
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount("https://", adapter)
session.mount("http://", adapter)

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        response = session.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram Error: {e}")
        return False

def get_btc_price():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    for base in ("https://api.bitpin.ir/v1/mkt/markets/prices/", "https://api.bitpin.org/v1/mkt/markets/prices/"):
        try:
            res = requests.get(base, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list):
                    for t in data:
                        if t.get("symbol") == "BTC_USDT":
                            price = t.get("price")
                            if price not in (None, "", "0"):
                                return f"{float(price):,.2f}"
        except:
            pass
    try:
        res = requests.get("https://api.bitpin.ir/v1/mkt/markets/prices/", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list):
                for t in data:
                    if t.get("symbol") == "BTC_IRT":
                        price = t.get("price")
                        if price not in (None, "", "0"):
                            return f"{float(price):,.2f} تومان"
    except:
        pass
    try:
        df = get_ohlc("BTC_USDT", resolution="60", count=2)
        if df is not None and not df.empty:
            return f"{float(df.iloc[-1]['close']):,.2f}"
    except:
        pass
    return "نامشخص"

def get_ohlc(symbol, resolution="60", count=350):
    try:
        now_ts = int(time.time())
        from_ts = now_ts - (count * int(resolution) * 60)
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": now_ts
        }
        res = session.get(OHLC_URL, params=params, timeout=20)
        if res.status_code == 200:
            data = res.json()
            if data.get("s") == "ok":
                df = pd.DataFrame({
                    "time": data.get("t"),
                    "open": data.get("o"),
                    "high": data.get("h"),
                    "low": data.get("l"),
                    "close": data.get("c"),
                    "volume": data.get("v")
                })
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df.dropna(inplace=True)
                return df
        return None
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

def compute_indicators(df):
    if len(df) < max(EMA_TREND_PERIOD, BB_PERIOD, ATR_PERIOD, RSI_PERIOD) + 10:
        return None
    
    # باندهای بولینگر
    sma = df["close"].rolling(window=BB_PERIOD).mean()
    std = df["close"].rolling(window=BB_PERIOD).std()
    df["bb_upper"] = sma + (std * BB_STD)
    df["bb_lower"] = sma - (std * BB_STD)
    
    # فیلتر روند ماکرو ۲۰۰ ساعته
    df["ema_200"] = df["close"].ewm(span=EMA_TREND_PERIOD, adjust=False).mean()
    
    # میانگین حجم ۲۰ کندل (معیار حجم نرمال)
    df["vol_sma"] = df["volume"].rolling(20).mean()
    
    # ATR برای حد ضرر و سود داینامیک
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=ATR_PERIOD).mean()
    
    # RSI با ایمنی در برابر تقسیم بر صفر
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss.replace(0, 0.001)
    df["rsi"] = 100 - (100 / (1 + rs))
    
    return df

def check_sensei_strategy(symbol, df):
    """روش سنسی / پولبک به حمایت با شرط حجم خشک (Dry Volume)"""
    if len(df) < 30:
        return
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    support = df['low'].iloc[-26:-4].min()
    
    # شرط حجم خشک: حجم کندل پولبک پایین‌تر یا مساوی ۷۰ درصد میانگین حجم باشد
    is_dry_volume = last["volume"] <= (last["vol_sma"] * 0.7)
    
    if prev["close"] <= support * 1.005 and last["close"] > support and is_dry_volume:
        key = f"{symbol}_sensei_long_{int(last['time'])}"
        if key not in SENT_KEYS:
            entry = last["close"]
            sl = support * 0.99
            tp1 = entry + (entry - sl) * 1.5
            tp2 = entry + (entry - sl) * 2.5
            market_type = "اسپات (فقط خرید)" if symbol in SPOT_ONLY_MARKETS else "تعهدی / فیوچرز"
            msg = (f"🎯 *سیگنال پولبک سنسی (حجم خشک) (LONG)*\n"
                   f"▫️ ارز: `{symbol}` ({market_type})\n"
                   f"▫️ قیمت ورود: `{entry}` USDT\n"
                   f"🛡 حد ضرر: `{round(sl, 4)}`\n"
                   f"🎯 حد سود ۱: `{round(tp1, 4)}`\n"
                   f"🎯 حد سود ۲: `{round(tp2, 4)}`")
            if send_telegram(msg):
                SENT_KEYS.add(key)

def check_trend_strategy(symbol, df):
    """روش بولینگر + RSI + تایید حجم نرمال و تفکیک مارکت تعهدی/اسپات"""
    if len(df) < 30:
        return
        
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    ema_val = last["ema_200"]
    atr_val = last["atr"]
    rsi_val = last["rsi"]
    
    vol_normal = last["volume"] >= (last["vol_sma"] * 0.7)
    is_spot_only = symbol in SPOT_ONLY_MARKETS
    
    # --- سیگنال لانگ ---
    if prev["close"] <= prev["bb_lower"] and last["close"] > last["bb_lower"]:
        if last["close"] > ema_val and rsi_val < 45 and vol_normal:
            key = f"{symbol}_trend_long_{int(last['time'])}"
            if key not in SENT_KEYS:
                entry = last["close"]
                sl = entry - (1.5 * atr_val)
                tp1 = entry + (2.0 * atr_val)
                tp2 = entry + (3.5 * atr_val)
                market_type = "اسپات" if is_spot_only else "تعهدی"
                msg = (f"🚀 *سیگنال بولینگر روند (LONG)*\n"
                       f"▫️ ارز: `{symbol}` ({market_type})\n"
                       f"▫️ قیمت ورود: `{entry}` USDT\n"
                       f"🛡 حد ضرر: `{round(sl, 4)}`\n"
                       f"🎯 حد سود ۱: `{round(tp1, 4)}`\n"
                       f"🎯 حد سود ۲: `{round(tp2, 4)}`")
                if send_telegram(msg):
                    SENT_KEYS.add(key)

    # --- سیگنال شورت ---
    elif prev["close"] >= prev["bb_upper"] and last["close"] < prev["bb_upper"] and not is_spot_only:
        if last["close"] < ema_val and rsi_val > 55 and vol_normal:
            key = f"{symbol}_trend_short_{int(last['time'])}"
            if key not in SENT_KEYS:
                entry = last["close"]
                sl = entry + (1.5 * atr_val)
                tp1 = entry - (2.0 * atr_val)
                tp2 = entry - (3.5 * atr_val)
                msg = (f"🔻 *سیگنال فروش تعهدی (SHORT)*\n"
                       f"▫️ ارز: `{symbol}` (تعهدی)\n"
                       f"▫️ قیمت ورود: `{entry}` USDT\n"
                       f"🛡 حد ضرر: `{round(sl, 4)}`\n"
                       f"🎯 حد سود ۱: `{round(tp1, 4)}`\n"
                       f"🎯 حد سود ۲: `{round(tp2, 4)}`")
                if send_telegram(msg):
                    SENT_KEYS.add(key)

def bot_worker():
    print("🤖 ربات ترید تتری بیت‌پین شروع شد...")
    btc_p = get_btc_price()
    send_telegram(f"🤖 *ربات ترید تتری (۱۰۰ تعهدی + ۲۰ اسپات) روشن شد.*\n📊 قیمت بیت‌کوین (سلامت سنج): `{btc_p}` USDT\n⏱ اسکن بازار فعال در ۵ دقیقه پایانی هر ساعت (با فیلتر حجم خشک در پولبک).")
    while True:
        try:
            now = datetime.now(timezone.utc)
            current_minute = now.minute
            
            if 50 <= current_minute <= 59:
                for symbol in ALL_SYMBOLS:
                    df = get_ohlc(symbol, resolution=TIMEFRAME, count=350)
                    if df is not None and not df.empty:
                        df = compute_indicators(df)
                        if df is not None:
                            check_sensei_strategy(symbol, df)
                            check_trend_strategy(symbol, df)
                    time.sleep(0.5)
                time.sleep(300)
            else:
                time.sleep(CHECK_INTERVAL)
                
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(60)

# ================= سرور سلامت برای Render (با پشتیبانی از HEAD برای رفع خطای لاگ) =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bitpin USDT Bot is Active!".encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

if __name__ == "__main__":
    t_bot = threading.Thread(target=bot_worker, daemon=True)
    t_bot.start()
    run_server()
