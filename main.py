# -*- coding: utf-8 -*-
"""
Bitpin Signal Bot (Render Deployment Ready)
- Long Strategy: Sensei (25-candle Lowest Low + Dry Volume Reversal)
- Trend Strategy: Bollinger Bands + EMA200 + RSI + ATR
- Includes Internal HTTP Server for Render Free Tier Keep-Alive
Requirements:
    requests
    pandas
"""

import os
import time
import html
import threading
import logging
from collections import deque
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("bitpin_bot")

# ================= تنظیمات محیطی و امنیتی =================
# برای امنیت حتما این مقادیر را در Environment Variables رندر تنظیم کنید
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227").strip()
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/tv/history/"

# تنظیمات تایم‌فریم و اندیکاتورها (تایم‌فریم روی ۱۵ دقیقه تنظیم شد)
TIMEFRAME = "15"          # کندل‌های ۱۵ دقیقه‌ای
CANDLE_SECONDS = int(TIMEFRAME) * 60
CHECK_INTERVAL = 20       # بررسی وضعیت هر ۲۰ ثانیه

# پارامترهای استراتژی سنسی (Sensie)
SENSI_LOOKBACK = 25       # تعداد کندل‌های گذشته برای کف (بین ۲۰ تا ۳۰)
SENSI_ZONE_TOLERANCE = 0.0035  # تلورانس لمس یا نزدیکی به کف (۰.۳۵ درصد)
SENSI_DRY_RATIO = 0.70    # حداکثر حجم مجاز کندل سیگنال نسبت به میانگین گذشته

# پارامترهای استراتژی روند بولینگر
BB_PERIOD = 20
BB_STD = 2.0
EMA_TREND_PERIOD = 200
ATR_PERIOD = 14
RSI_PERIOD = 14

# -------------------------------------------------------------
# ۱. نمادهای تعهدی (امکان لانگ و شورت)
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
    
    # Memes
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
    
    # Others & Classics
    "ZEC_USDT", "LTC_USDT", "BCH_USDT", "XLM_USDT", "EOS_USDT", "XTZ_USDT", "EGLD_USDT", 
    "THETA_USDT", "CHZ_USDT", "ENJ_USDT", "GMT_USDT", "SAND_USDT", "MANA_USDT", 
    "AXS_USDT", "GALA_USDT", "DYM_USDT", "QNT_USDT", "MINA_USDT", "KLAY_USDT", "ZIL_USDT"
]

# -------------------------------------------------------------
# ۲. نمادهای اسپات (فقط خرید / لانگ)
# -------------------------------------------------------------
SPOT_ONLY_MARKETS = [
    "AVNT_USDT", "POND_USDT", "POL_USDT", "TURBO_USDT", "POLIS_USDT",
    "DEGO_USDT", "STG_USDT", "UMA_USDT", "API3_USDT", "RAD_USDT",
    "RLC_USDT", "CTSI_USDT", "DATA_USDT", "IDEX_USDT", "CREAM_USDT", 
    "PERP_USDT", "UNFI_USDT", "OXT_USDT", "CELO_USDT", "AUDIO_USDT"
]

ALL_SYMBOLS = list(dict.fromkeys(MARGIN_SYMBOLS + SPOT_ONLY_MARKETS))

# حافظه امن برای جلوگیری از ارسال پیام‌های تکراری
SENT_KEYS = deque(maxlen=2000)
SENT_LOCK = threading.Lock()
LAST_SCAN_TIME = "هنوز انجام نشده"
LAST_SCAN_KEY = None
BOT_STATUS = {
    "alive": False,
    "last_scan_utc": "هنوز انجام نشده",
    "scanned_count": 0,
    "signals_sent": 0
}

# تنظیم نشست HTTP پایدار و ریتری
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))


def format_price(val: float) -> str:
    """فرمت‌بندی خوانا برای قیمت رمزارزها حتی برای قیمت‌های بسیار کوچک"""
    if val is None or pd.isna(val):
        return "نامعتبر"
    if val >= 100:
        return f"{val:,.2f}"
    if val >= 1:
        return f"{val:,.4f}"
    return f"{val:.8f}".rstrip("0").rstrip(".")


def send_telegram(message_html: str) -> bool:
    """ارسال اعلان به تلگرام با فرمت امن HTML"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram Bot Token یا Chat ID تنظیم نشده است.")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res = session.post(url, json=payload, timeout=12)
        if res.status_code == 200:
            return True
        logger.error(f"Telegram API Error: {res.status_code} - {res.text}")
        return False
    except Exception as e:
        logger.error(f"Telegram Exception: {e}")
        return False


def get_market_tickers():
    """دریافت قیمت‌های زنده نمادها به صورت یکجا"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = session.get("https://api.bitpin.org/api/v1/mkt/tickers/", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("results", []) if isinstance(data, dict) else data
            mapping = {}
            for m in items:
                sym = m.get("symbol") or m.get("market", {}).get("symbol")
                price = m.get("price") or m.get("last_price") or m.get("market", {}).get("price")
                if sym and price:
                    try:
                        mapping[sym] = float(price)
                    except ValueError:
                        pass
            return mapping
    except Exception as e:
        logger.warning(f"Failed to fetch market tickers: {e}")
    return {}


def get_ohlc(symbol: str, resolution="15", count=350) -> pd.DataFrame | None:
    """دریافت دیتای کندل‌ها و فیلتر کردن کندلِ بسته‌نشده‌ی فعلی"""
    try:
        now_ts = int(time.time())
        from_ts = now_ts - (count * int(resolution) * 60)
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": now_ts
        }
        res = session.get(OHLC_URL, params=params, timeout=15)
        if res.status_code != 200:
            return None
        data = res.json()
        if data.get("s") != "ok":
            return None

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

        if df.empty:
            return None

        if df["time"].iloc[-1] > 1e11:
            df["time"] = (df["time"] / 1000).astype(int)
        else:
            df["time"] = df["time"].astype(int)

        df.sort_values("time", inplace=True)
        df.drop_duplicates(subset=["time"], keep="last", inplace=True)

        # حذف کندل جاری در حال ساخت تا تحلیل فقط روی کندل‌های کاملاً بسته‌شده باشد
        timeframe_seconds = int(resolution) * 60
        latest_candle_time = int(df["time"].iloc[-1])
        if (now_ts - latest_candle_time) < timeframe_seconds:
            df = df.iloc[:-1].copy()

        return df if len(df) >= 70 else None
    except Exception as e:
        logger.error(f"Error fetching OHLC for {symbol}: {e}")
        return None


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame | None:
    """محاسبه اندیکاتورها بر روی کندل‌های بسته‌شده"""
    min_required = max(EMA_TREND_PERIOD, BB_PERIOD, ATR_PERIOD, RSI_PERIOD) + 20
    if len(df) < min_required:
        return None

    sma = df["close"].rolling(window=BB_PERIOD).mean()
    std = df["close"].rolling(window=BB_PERIOD).std()
    df["bb_upper"] = sma + (std * BB_STD)
    df["bb_lower"] = sma - (std * BB_STD)

    df["ema_200"] = df["close"].ewm(span=EMA_TREND_PERIOD, adjust=False).mean()
    df["vol_sma"] = df["volume"].rolling(20).mean()

    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=ATR_PERIOD).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss.replace(0, 1e-6)
    df["rsi"] = 100 - (100 / (1 + rs))

    return df


def _record_sent(key: str):
    with SENT_LOCK:
        SENT_KEYS.append(key)
        BOT_STATUS["signals_sent"] += 1


def check_sensei_strategy(symbol: str, df: pd.DataFrame):
    """
    استراتژی سنسی (کف ۲۵ کندل پیشین + خشکی حجم + تأیید برگشت)
    """
    if len(df) < (SENSI_LOOKBACK + 25):
        return

    sig_candle = df.iloc[-1]
    sig_time = int(sig_candle["time"])
    key = f"{symbol}_sensi_long_{sig_time}"

    with SENT_LOCK:
        if key in SENT_KEYS:
            return

    history_window = df.iloc[-(SENSI_LOOKBACK + 1): -1]
    prior_support = history_window["low"].min()

    prev_vol_window = df["volume"].iloc[-21: -1]
    prev_vol_sma = prev_vol_window.mean()
    if prev_vol_sma <= 0 or pd.isna(prev_vol_sma):
        return

    is_dry_volume = sig_candle["volume"] <= (prev_vol_sma * SENSI_DRY_RATIO)
    zone_upper = prior_support * (1.0 + SENSI_ZONE_TOLERANCE)
    touched_zone = (sig_candle["low"] <= zone_upper)
    not_crushed = (sig_candle["close"] >= prior_support * 0.995)

    body = abs(sig_candle["close"] - sig_candle["open"])
    lower_wick = min(sig_candle["close"], sig_candle["open"]) - sig_candle["low"]
    candle_range = sig_candle["high"] - sig_candle["low"]
    close_in_upper = (sig_candle["close"] - sig_candle["low"]) >= (0.50 * candle_range) if candle_range > 0 else False

    is_reversal = (sig_candle["close"] > sig_candle["open"]) or (lower_wick >= 0.9 * body) or close_in_upper

    if touched_zone and not_crushed and is_dry_volume and is_reversal:
        entry = float(sig_candle["close"])
        atr_val = float(sig_candle["atr"]) if not pd.isna(sig_candle.get("atr")) else (entry * 0.01)

        buffer = max(entry * 0.0025, atr_val * 0.3)
        sl = min(prior_support, sig_candle["low"]) - buffer
        risk = entry - sl

        if risk <= 0:
            return

        tp1 = entry + (risk * 1.5)
        tp2 = entry + (risk * 2.5)

        market_type = "اسپات (فقط خرید)" if symbol in SPOT_ONLY_MARKETS else "تعهدی / فیوچرز"
        vol_pct = int((sig_candle["volume"] / prev_vol_sma) * 100)

        msg = (
            f"🎯 <b>سیگنال لانگ سنسی (خشکی حجم در کف ۲۵)</b>\n"
            f"▫️ ارز: <code>{html.escape(symbol)}</code> ({market_type})\n"
            f"▫️ قیمت ورود: <code>{format_price(entry)}</code> USDT\n"
            f"▫️ کف حمایتی گذشته: <code>{format_price(prior_support)}</code>\n"
            f"▫️ نسبت حجم فعلی به میانگین: <code>%{vol_pct}</code> (خشکیده)\n"
            f"🛡 حد ضرر (SL): <code>{format_price(sl)}</code>\n"
            f"🎯 حد سود ۱ (1.5R): <code>{format_price(tp1)}</code>\n"
            f"🎯 حد سود ۲ (2.5R): <code>{format_price(tp2)}</code>"
        )

        if send_telegram(msg):
            _record_sent(key)
            logger.info(f"Signal sent: {key}")


def check_trend_strategy(symbol: str, df: pd.DataFrame):
    """
    استراتژی کمکی: روند بولینگر + EMA200 + RSI + ATR
    """
    if len(df) < 30:
        return

    last = df.iloc[-1]
    prev = df.iloc[-2]
    sig_time = int(last["time"])

    ema_val = float(last["ema_200"])
    atr_val = float(last["atr"])
    rsi_val = float(last["rsi"])
    vol_sma = float(last["vol_sma"]) if last["vol_sma"] > 0 else 1.0

    if pd.isna(atr_val) or atr_val <= 0:
        return

    vol_normal = last["volume"] >= (vol_sma * 0.6)
    is_spot_only = symbol in SPOT_ONLY_MARKETS

    # لانگ بولینگر
    if (prev["close"] <= prev["bb_lower"]) and (last["close"] > last["bb_lower"]):
        if (last["close"] > ema_val) and (rsi_val < 48) and vol_normal:
            key = f"{symbol}_trend_long_{sig_time}"
            with SENT_LOCK:
                if key in SENT_KEYS:
                    return

            entry = float(last["close"])
            sl = entry - (1.5 * atr_val)
            tp1 = entry + (2.0 * atr_val)
            tp2 = entry + (3.5 * atr_val)
            market_type = "اسپات" if is_spot_only else "تعهدی"

            msg = (
                f"🚀 <b>سیگنال بولینگر روند (LONG)</b>\n"
                f"▫️ ارز: <code>{html.escape(symbol)}</code> ({market_type})\n"
                f"▫️ قیمت ورود: <code>{format_price(entry)}</code> USDT\n"
                f"▫️ شاخص RSI: <code>{rsi_val:.1f}</code>\n"
                f"🛡 حد ضرر: <code>{format_price(sl)}</code>\n"
                f"🎯 حد سود ۱: <code>{format_price(tp1)}</code>\n"
                f"🎯 حد سود ۲: <code>{format_price(tp2)}</code>"
            )
            if send_telegram(msg):
                _record_sent(key)

    # شورت بولینگر (فقط برای نمادهای تعهدی)
    elif (prev["close"] >= prev["bb_upper"]) and (last["close"] < last["bb_upper"]) and not is_spot_only:
        if (last["close"] < ema_val) and (rsi_val > 52) and vol_normal:
            key = f"{symbol}_trend_short_{sig_time}"
            with SENT_LOCK:
                if key in SENT_KEYS:
                    return

            entry = float(last["close"])
            sl = entry + (1.5 * atr_val)
            tp1 = entry - (2.0 * atr_val)
            tp2 = entry - (3.5 * atr_val)

            msg = (
                f"🔻 <b>سیگنال فروش تعهدی بولینگر (SHORT)</b>\n"
                f"▫️ ارز: <code>{html.escape(symbol)}</code> (تعهدی)\n"
                f"▫️ قیمت ورود: <code>{format_price(entry)}</code> USDT\n"
                f"▫️ شاخص RSI: <code>{rsi_val:.1f}</code>\n"
                f"🛡 حد ضرر: <code>{format_price(sl)}</code>\n"
                f"🎯 حد سود ۱: <code>{format_price(tp1)}</code>\n"
                f"🎯 حد سود ۲: <code>{format_price(tp2)}</code>"
            )
            if send_telegram(msg):
                _record_sent(key)


def _current_15m_slot(now=None):
    now = now or datetime.now(timezone.utc)
    return (now.year, now.month, now.day, now.hour, now.minute // 15)


def _scan_market(scan_key):
    global LAST_SCAN_TIME, LAST_SCAN_KEY, BOT_STATUS
    try:
        with SENT_LOCK:
            LAST_SCAN_TIME = datetime.now(timezone.utc).isoformat()
            LAST_SCAN_KEY = scan_key
        logger.info("Starting scan for closed 15-minute candle slot %s (%d symbols)", scan_key, len(ALL_SYMBOLS))
        
        scanned_ok = 0
        for symbol in ALL_SYMBOLS:
            try:
                df = get_ohlc(symbol, resolution=TIMEFRAME, count=350)
                if df is not None:
                    df = compute_indicators(df)
                    if df is not None:
                        check_sensei_strategy(symbol, df)
                        check_trend_strategy(symbol, df)
                        scanned_ok += 1
            except Exception as sym_err:
                logger.warning(f"Error scanning {symbol}: {sym_err}")
            time.sleep(0.25)

        BOT_STATUS["last_scan_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        BOT_STATUS["scanned_count"] = scanned_ok
        logger.info("Finished scan for closed 15-minute candle slot %s. Scanned %d symbols.", scan_key, scanned_ok)
    except Exception:
        logger.exception("Scan market execution failed")


def bot_worker():
    logger.info("ربات ترید بیت‌پین استارت خورد...")
    BOT_STATUS["alive"] = True

    tickers = get_market_tickers()
    btc_p = format_price(tickers.get("BTC_USDT"))
    eth_p = format_price(tickers.get("ETH_USDT"))

    startup_msg = (
        f"🤖 <b>ربات ترید بیت‌پین با موفقیت فعال شد</b>\n"
        f"✅ <b>استراتژی سنسی (تایم‌فریم ۱۵ دقیقه):</b> کف ۲۵ کندل پیشین + حجم خشک + کندل بازگشتی\n"
        f"📊 قیمت فعلی بیت‌کوین: <code>{btc_p}</code> USDT\n"
        f"📊 قیمت فعلی اتریوم: <code>{eth_p}</code> USDT\n"
        f"⏱ <i>اسکن بازار به محض بسته شدن هر کندل ۱۵ دقیقه انجام می‌شود.</i>"
    )
    send_telegram(startup_msg)

    LAST_SCANNED_HOUR = None
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            # بررسی در دقایق ۱ یا ۲ پس از بسته شدن هر کندل ۱۵ دقیقه‌ای (00، 15، 30، 45)
            if now_utc.minute % 15 in (1, 2):
                scan_key = _current_15m_slot(now_utc)
                if scan_key != LAST_SCANNED_HOUR:
                    LAST_SCANNED_HOUR = scan_key
                    try:
                        _scan_market(scan_key)
                    except Exception:
                        logger.exception("15-minute scan failed")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            logger.error(f"Main loop critical error: {e}")
            time.sleep(45)


class SimpleHandler(BaseHTTPRequestHandler):
    """سرور داخلی برای باز نگه داشتن سرویس رایگان Render و بررسی وضعیت سلامت"""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            f"<h3>Bitpin Sensi Bot Status: Active (15m Timeframe)</h3>"
            f"<p>Last Scan: {BOT_STATUS['last_scan_utc']}</p>"
            f"<p>Scanned Symbols: {BOT_STATUS['scanned_count']}</p>"
            f"<p>Signals Sent: {BOT_STATUS['signals_sent']}</p>"
        )
        self.wfile.write(body.encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()


def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    logger.info(f"وب سرور فعال شد روی پورت {port}")
    server.serve_forever()


if __name__ == "__main__":
    t_bot = threading.Thread(target=bot_worker, daemon=True)
    t_bot.start()
    run_server()
