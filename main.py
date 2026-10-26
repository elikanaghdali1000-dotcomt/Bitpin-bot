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

# دامنه درست بیت‌پین
BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/tv/history/"

BB_PERIOD = 20
BB_STD = 2.0

# حد سود و ضرر مخصوص پولبک
PULLBACK_SL_PC = 2.0
PULLBACK_TP_PC = 4.0

# فواصل زمانی و تایم‌فریم
CHECK_INTERVAL = 300  # هر ۵ دقیقه
TIMEFRAME = "60"      # کندل ۱ ساعته

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BitpinBot/1.0; +https://example.com)"
}

# ================= لیست ارزها =================
SPOT_SYMBOLS = [
    "ZEC_USDT", "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "ADA_USDT", "DOGE_USDT",
    "AVAX_USDT", "LINK_USDT", "TON_USDT", "PEPE_USDT", "WIF_USDT", "NOT_USDT",
    "SUI_USDT", "NEAR_USDT", "ARBITRUM_USDT", "OP_USDT", "MATIC_USDT", "POL_USDT",
    "JUP_USDT", "BMT_USDT", "RENDER_USDT", "FET_USDT", "INJ_USDT", "TIA_USDT",
    "SEI_USDT", "APT_USDT", "ATOM_USDT", "FTM_USDT", "UNI_USDT", "LTC_USDT",
    "SHIB_USDT", "BCH_USDT", "ETC_USDT", "FIL_USDT", "ICP_USDT", "RUNE_USDT",
    "GRT_USDT", "STX_USDT", "IMX_USDT", "ONDO_USDT", "MANA_USDT", "SAND_USDT",
    "AXS_USDT", "DYDX_USDT", "GALA_USDT", "CHZ_USDT", "CRV_USDT", "AAVE_USDT",
    "MKR_USDT", "SNX_USDT", "LDO_USDT", "AR_USDT", "PYTH_USDT", "STRK_USDT",
    "BOME_USDT", "FLOKI_USDT", "BONK_USDT", "ENS_USDT", "PENDLE_USDT",
    "JTO_USDT", "PORTAL_USDT", "PIXEL_USDT", "ALT_USDT", "MANTA_USDT", "XAI_USDT",
    "ACE_USDT", "NFP_USDT", "AI_USDT", "SAVM_USDT", "XMR_USDT", "ALGO_USDT",
    "VET_USDT", "HBAR_USDT", "QNT_USDT", "EGLD_USDT", "THETA_USDT",
    "XTZ_USDT", "EOS_USDT", "FLOW_USDT", "KAS_USDT", "BSV_USDT", "NEO_USDT",
    "CAKE_USDT", "COMP_USDT", "ZRX_USDT", "BAT_USDT", "ENJ_USDT",
    "OCEAN_USDT", "RLC_USDT", "KNC_USDT", "BAL_USDT", "BAND_USDT",
    "SKL_USDT", "CVC_USDT", "STORJ_USDT", "OGN_USDT", "SNT_USDT", "STMX_USDT",
    "CTSI_USDT", "CHR_USDT", "DGB_USDT", "SC_USDT", "ZEN_USDT", "IOST_USDT",
    "ICX_USDT", "ONT_USDT", "ZIL_USDT", "RVN_USDT", "WAN_USDT", "COTI_USDT",
    "LRC_USDT", "ANKR_USDT", "OG_USDT", "ASR_USDT", "ATM_USDT", "BAR_USDT"
]

SPOT_ONLY_MARKETS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "ADA_USDT", "DOGE_USDT",
    "AVAX_USDT", "LINK_USDT", "TON_USDT", "PEPE_USDT", "WIF_USDT", "NOT_USDT",
    "SHIB_USDT", "BCH_USDT", "ETC_USDT", "FIL_USDT", "ICP_USDT", "RUNE_USDT"
]

# ================= وضعیت برای داشبورد و جلوگیری از تکرار =================
BOT_STATE = {
    "started_at": datetime.now(timezone.utc),
    "last_scan_at": None,
    "last_signal_at": None,
    "last_signal_text": None,
    "last_btc_price": None,
    "signals_sent_today": 0,
}

# جلوگیری از ارسال تکراری: key = (symbol, candle_time, strategy, type)
SENT_KEYS = set()
SENT_KEYS_MAX = 5000  # برای جلوگیری از رشد بی‌نهایت حافظه

def cleanup_sent_keys_if_needed():
    # ساده و کم‌هزینه: اگر خیلی بزرگ شد، کل ست را ریست می‌کنیم
    # (به جای LRU پیچیده؛ چون فقط جلوگیری از اسپم روی کندل‌های نزدیک می‌خواهیم)
    global SENT_KEYS
    if len(SENT_KEYS) > SENT_KEYS_MAX:
        SENT_KEYS = set()

# ================= سرور HTTP برای داشبورد =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()

        started = BOT_STATE["started_at"].strftime("%Y-%m-%d %H:%M:%S")
        last_scan = BOT_STATE["last_scan_at"].strftime("%Y-%m-%d %H:%M:%S") if BOT_STATE["last_scan_at"] else "-"
        last_sig = BOT_STATE["last_signal_at"].strftime("%Y-%m-%d %H:%M:%S") if BOT_STATE["last_signal_at"] else "-"
        btc = BOT_STATE["last_btc_price"]
        btc_text = f"${btc:,.2f}" if isinstance(btc, (int, float)) and btc > 0 else "-"
        sig_text = BOT_STATE["last_signal_text"] or "-"

        html = f"""
        <html><head><title>Bitpin Bot Dashboard</title></head>
        <body style="font-family: sans-serif;">
            <h2>Bitpin Trading Bot - Dashboard</h2>
            <p><b>Status:</b> Running</p>
            <p><b>Started (UTC):</b> {started}</p>
            <p><b>Last Scan (UTC):</b> {last_scan}</p>
            <p><b>BTC Price (Last):</b> {btc_text}</p>
            <p><b>Signals Sent Today:</b> {BOT_STATE["signals_sent_today"]}</p>
            <hr/>
            <p><b>Last Signal Time (UTC):</b> {last_sig}</p>
            <pre style="background:#f5f5f5;padding:10px;white-space:pre-wrap;">{sig_text}</pre>
        </body></html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        return

def run_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# ================= توابع ارتباطی و تلگرام =================
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def fetch_ohlcv(symbol):
    try:
        now = int(time.time())
        start = now - (300 * 3600)  # ۳۰۰ کندل قبل (برای تایم‌فریم ۱ساعت)
        url = f"{OHLC_URL}?symbol={symbol}&resolution={TIMEFRAME}&from={start}&to={now}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and "t" in data and len(data["t"]) > 50:
                df = pd.DataFrame({
                    "time": data["t"],
                    "open": data["o"],
                    "high": data["h"],
                    "low": data["l"],
                    "close": data["c"],
                    "volume": data["v"],
                })
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["time"] = pd.to_numeric(df["time"], errors="coerce")
                df.dropna(inplace=True)
                return df
    except Exception as e:
        print(f"OHLC Error for {symbol}: {e}")
    return None

def get_bitcoin_price():
    """دریافت قیمت آخرین کلوز BTC برای نمایش در داشبورد"""
    try:
        now = int(time.time())
        start = now - 7200
        url = f"{OHLC_URL}?symbol=BTC_USDT&resolution=60&from={start}&to={now}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and "c" in data and len(data["c"]) > 0:
                return float(data["c"][-1])
    except Exception:
        pass
    return 0.0

# ================= استراتژی‌ها (بررسی روی کندل بسته شده) =================
def check_sensei_strategy(df, symbol):
    """روش استاد | بازگشتی (S&D + Reversal)"""
    if df is None or len(df) < 30:
        return None

    recent = df.iloc[-26:-4]
    support = recent["low"].min()
    resistance = recent["high"].max()

    last_candle = df.iloc[-2]  # کندل بسته شده آخر
    avg_vol = df["volume"].iloc[-21:-2].mean()

    # ریجکشن کف -> لانگ
    if last_candle["low"] <= support * 1.002 and last_candle["close"] > last_candle["open"]:
        if last_candle["volume"] < avg_vol * 1.2:
            return {
                "type": "LONG",
                "strategy": "🎯 روش استاد | بازگشتی",
                "entry": float(last_candle["close"]),
                "sl": float(support * 0.99),
                "tp1": float(last_candle["close"] + (last_candle["close"] - support) * 1.5),
                "tp2": float(last_candle["close"] + (last_candle["close"] - support) * 2.5),
                "candle_time": int(last_candle["time"]),
            }

    # ریجکشن سقف -> شورت (با محافظت از اسپات)
    if last_candle["high"] >= resistance * 0.998 and last_candle["close"] < last_candle["open"]:
        if symbol in SPOT_ONLY_MARKETS:
            return None
        if last_candle["volume"] < avg_vol * 1.2:
            diff = abs(resistance - last_candle["close"])  # FIX: جلوگیری از TP اشتباه
            return {
                "type": "SHORT",
                "strategy": "🎯 روش استاد | بازگشتی",
                "entry": float(last_candle["close"]),
                "sl": float(resistance * 1.01),
                "tp1": float(last_candle["close"] - diff * 1.5),
                "tp2": float(last_candle["close"] - diff * 2.5),
                "candle_time": int(last_candle["time"]),
            }

    return None

def check_trend_strategy(df, symbol):
    """روش خودمان | روند (Bollinger Pullback)"""
    if df is None or len(df) < 30:
        return None

    close = df["close"]
    sma = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    upper = sma + (BB_STD * std)
    lower = sma - (BB_STD * std)

    last_close = close.iloc[-2]   # کندل بسته شده
    prev_close = close.iloc[-3]   # کندل ماقبل آخر بسته شده
    last_lower = lower.iloc[-2]
    last_upper = upper.iloc[-2]
    last_candle_time = int(df["time"].iloc[-2])

    # پولبک به باند پایین -> لانگ
    if prev_close <= lower.iloc[-3] and last_close > last_lower:
        return {
            "type": "LONG",
            "strategy": "🚀 روش خودمان | روند",
            "entry": float(last_close),
            "sl": float(last_close * (1 - PULLBACK_SL_PC / 100)),
            "tp1": float(last_close * (1 + PULLBACK_TP_PC / 100)),
            "tp2": float(last_close * (1 + (PULLBACK_TP_PC * 2) / 100)),
            "candle_time": last_candle_time,
        }

    # پولبک به باند بالا -> شورت
    if prev_close >= upper.iloc[-3] and last_close < last_upper:
        if symbol in SPOT_ONLY_MARKETS:
            return None
        return {
            "type": "SHORT",
            "strategy": "🚀 روش خودمان | روند",
            "entry": float(last_close),
            "sl": float(last_close * (1 + PULLBACK_SL_PC / 100)),
            "tp1": float(last_close * (1 - PULLBACK_TP_PC / 100)),
            "tp2": float(last_close * (1 - (PULLBACK_TP_PC * 2) / 100)),
            "candle_time": last_candle_time,
        }

    return None

# ================= حلقه اصلی ربات =================
def should_send_signal(symbol, signal):
    # جلوگیری از ارسال تکراری روی همان کندل
    key = (symbol, signal.get("candle_time"), signal.get("strategy"), signal.get("type"))
    if key in SENT_KEYS:
        return False
    SENT_KEYS.add(key)
    cleanup_sent_keys_if_needed()
    return True

def scan_markets():
    BOT_STATE["last_scan_at"] = datetime.now(timezone.utc)

    # قیمت BTC برای داشبورد/پیام
    btc_price = get_bitcoin_price()
    BOT_STATE["last_btc_price"] = btc_price

    print(f"[{BOT_STATE['last_scan_at']}] Scan started... BTC={btc_price}")

    for symbol in SPOT_SYMBOLS:
        df = fetch_ohlcv(symbol)
        if df is not None:
            # ۱. اولویت با روش استاد
            signal = check_sensei_strategy(df, symbol)
            if not signal:
                # ۲. روش خودمان
                signal = check_trend_strategy(df, symbol)

            if signal and should_send_signal(symbol, signal):
                btc_text = f"₿ بیت‌کوین: <b>${btc_price:,.2f}</b>\n" if btc_price > 0 else ""
                msg = (
                    f"🚨 <b>سیگنال جدید معاملاتی</b>\n\n"
                    f"{btc_text}"
                    f" ارز: <b>{symbol}</b>\n"
                    f" استراتژی: <b>{signal['strategy']}</b>\n"
                    f" جهت: <b>{signal['type']}</b>\n"
                    f" نقطه ورود: <code>{signal['entry']:.8f}</code>\n"
                    f" حد ضرر (SL): <code>{signal['sl']:.8f}</code>\n"
                    f" حد سود ۱ (TP1): <code>{signal['tp1']:.8f}</code>\n"
                    f" حد سود ۲ (TP2): <code>{signal['tp2']:.8f}</code>\n"
                    f"🕯 زمان کندل: {datetime.fromtimestamp(signal['candle_time'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                    f"⏰ زمان ارسال: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
                )
                send_telegram_message(msg)

                BOT_STATE["last_signal_at"] = datetime.now(timezone.utc)
                BOT_STATE["last_signal_text"] = msg
                BOT_STATE["signals_sent_today"] += 1

        time.sleep(0.6)

def main_loop():
    while True:
        try:
            scan_markets()
        except Exception as e:
            print(f"Main loop error: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    print("Bitpin Bot Started (fixed duplicates + dashboard BTC)...")
    main_loop()
