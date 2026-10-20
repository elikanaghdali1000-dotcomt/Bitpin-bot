import os
import math
import time
import requests
import threading
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- تنظیمات تلگرام (ثابت‌شده) ---
TELEGRAM_TOKEN = "*******"
CHAT_ID = "6643451227"

# آدرس عمومی رندر برای پینگ Keep-Alive
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

# --- تنظیمات استراتژی و ضد رنج هوشمند (فقط روند اصلی) ---
SQUEEZE_RATIO = 0.35
MIN_BANDWIDTH = 0.008   # 🚫 فیلتر ضد رنج: جلوگیری از سیگنال در بازارهای مرده و کم‌نوسان

SL_PERCENT = 0.012    # حد ضرر
TP1_PERCENT = 0.010   # حد سود اول
TP2_PERCENT = 0.020   # حد سود دوم
VOLUME_MULTIPLIER = 2.0  # ضریب حجم انفجاری (روی ۲ تنظیم شد)

# --- ضد اسپم / ضد تکرار ---
SIGNAL_COOLDOWN_SEC = 45 * 60   # ۴۵ دقیقه کول‌داون برای هر ارز/جهت
REPEAT_SAME_PATTERN_BLOCK = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

session = requests.Session()
session.headers.update(HEADERS)

last_signals = {}
tp1_notified = {}

def format_price(price):
    if price is None:
        return "0"
    if price < 0.0001:
        return f"{price:.8f}".rstrip('0').rstrip('.')
    elif price < 1:
        return f"{price:.4f}".rstrip('0').rstrip('.')
    else:
        return f"{price:,.2f}"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        res = session.post(url, json=payload, timeout=6)
        return res.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is Active & Running!")

    def log_message(self, format, *args):
        return

def run_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Web server started on 0.0.0.0:{port}")
    server.serve_forever()

def keep_alive_ping():
    time.sleep(30)
    while True:
        try:
            target_url = APP_URL
            if target_url:
                res = requests.get(target_url, timeout=10)
                print(f"[{time.strftime('%H:%M:%S')}] Keep-Alive external ping sent: {res.status_code}")
            else:
                port = int(os.getenv("PORT", 10000))
                requests.get(f"http://127.0.0.1:{port}", timeout=5)
        except Exception as e:
            print(f"Keep-Alive ping warning: {e}")
        time.sleep(480)

def check_market_condition_and_signal(candles, tight_volume_multiplier=2.0):
    if len(candles) < 200:
        return "HOLD", "داده‌های کندل کافی نیست"

    closes = np.array([c["close"] for c in candles])
    highs = np.array([c["high"] for c in candles])
    lows = np.array([c["low"] for c in candles])
    volumes = np.array([c["volume"] for c in candles])

    ema_50 = np.mean(closes[-50:])
    ema_200 = np.mean(closes[-200:])

    current_close = closes[-1]
    current_high = highs[-1]
    current_low = lows[-1]
    current_volume = volumes[-1]
    avg_volume = np.mean(volumes[-21:-1])

    # بررسی شدوهای خطرناک (دهانه‌گشاد / ریدمال‌های بازار رنج)
    body_size = abs(current_close - closes[-2])
    total_range = current_high - current_low
    upper_shadow = current_high - max(current_close, closes[-2])
    lower_shadow = min(current_close, closes[-2]) - current_low

    is_wide_mouth_trap = (upper_shadow > body_size * 1.5) or (lower_shadow > body_size * 1.5)
    if is_wide_mouth_trap:
        return "HOLD", "سکوت: بازار رنج و پرشدوی خطرناک (تله)"

    # بررسی فشردگی و حجم انفجاری
    recent_ranges = highs[-6:-1] - lows[-6:-1]
    avg_recent_range = np.mean(recent_ranges)
    is_tight_compression = avg_recent_range < (np.mean(highs[-20:] - lows[-20:]) * 0.7)
    has_explosive_volume = current_volume >= (avg_volume * tight_volume_multiplier)

    if is_tight_compression and not has_explosive_volume:
        return "HOLD", "در حال تراکم - منتظر حجم انفجاری (۲x)"

    # فیلتر روند EMA
    is_uptrend = (current_close > ema_50) and (ema_50 > ema_200)
    is_downtrend = (current_close < ema_50) and (ema_50 < ema_200)

    # تصمیم نهایی
    if is_uptrend and has_explosive_volume and (total_range > avg_recent_range):
        return "LONG", "سیگنال خرید معتبر"

    if is_downtrend and has_explosive_volume and (total_range > avg_recent_range):
        return "SHORT", "سیگنال فروش معتبر"

    return "HOLD", "بازار خنثی یا فاقد شرایط"

def send_telegram_signal(symbol, market_type, side, price, pattern, btc_trend, entry_min, entry_max, sl, tp1, tp2):
    emoji = "🟢" if side == "LONG" else "🔴"
    side_title = "خرید (لانگ)" if side == "LONG" else "فروش (شورت)"
    market_label = "💎 بازار اسپات (Spot)" if market_type == "SPOT" else "⚡️ بازار تعهدی (Margin)"

    message = (
        f"{emoji} <b>سیگنال {side_title} ({symbol})</b>\n"
        f"📌 <b>نوع بازار:</b> {market_label}\n"
        f"💵 <b>قیمت فعلی:</b> <code>{format_price(price)}</code>\n"
        f"📊 <b>الگو (روند اصلی):</b> {pattern}\n\n"
        f"🎯 <b>محدوده ورود:</b> <code>{format_price(entry_min)}</code> - <code>{format_price(entry_max)}</code>\n"
        f"📉 <b>حد سود اول (TP1):</b> <code>{format_price(tp1)}</code>\n"
        f"🚀 <b>حد سود دوم (TP2):</b> <code>{format_price(tp2)}</code>\n"
        f"🛑 <b>حد ضرر (SL):</b> <code>{format_price(sl)}</code>\n"
        f"⚡️ <b>روند کلی بیت‌کوین:</b> <code>{btc_trend}</code>"
    )
    send_telegram_message(message)

def send_tp1_alert(symbol, market_type, side, current_price, tp1):
    side_fa = "خرید (لانگ)" if side == "LONG" else "فروش (شورت)"
    market_label = "اسپات (Spot)" if market_type == "SPOT" else "تعهدی (Margin)"
    message = (
        f"⚠️ <b>رسیدن به تارگت اول (TP1) و ریسک‌فری! ({symbol})</b>\n"
        f"📌 <b>بازار:</b> {market_label} | <b>جهت:</b> {side_fa}\n"
        f"💵 <b>قیمت فعلی:</b> <code>{format_price(current_price)}</code>\n"
        f"🎯 <b>تارگت TP1:</b> <code>{format_price(tp1)}</code>\n\n"
        f"👉 <i>حد ضرر را روی نقطه ورود (Free Risk) قرار دهید.</i>"
    )
    send_telegram_message(message)

def get_candles(symbol, timeframe="15m"):
    now = int(time.time())
    url = "https://api.bitpin.org/api/v1/mkt/candles/"
    params = {
        "symbol": symbol,
        "from": now - 43200,
        "to": now,
        "res": timeframe
    }
    try:
        res = session.get(url, params=params, timeout=7)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                candles_list = []
                for item in data:
                    candles_list.append({
                        "close": float(item["close"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "volume": float(item.get("volume", 0)),
                        "time": item.get("ts", item.get("time", 0))
                    })
                return candles_list
        return []
    except Exception:
        return []

def get_market_trend():
    try:
        candles = get_candles("BTC_USDT", timeframe="1h")
        if len(candles) >= 20:
            closes = [c["close"] for c in candles]
            sma_20 = sum(closes[-20:]) / 20.0
            if closes[-1] > sma_20 * 1.002:
                return "BULLISH"
            elif closes[-1] < sma_20 * 0.998:
                return "BEARISH"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"

def analyze_market(symbol, market_type, candles, market_trend):
    if len(candles) < 30:
        return

    current_price = candles[-1]["close"]
    last_candle_time = candles[-1]["time"]

    base_key_long = f"{symbol}_{market_type}_LONG"
    base_key_short = f"{symbol}_{market_type}_SHORT"

    for base_key in (base_key_long, base_key_short):
        saved = last_signals.get(base_key)
        if not saved:
            continue

        side = saved["side"]
        tp1 = saved["tp1"]

        if not tp1_notified.get(base_key, False):
            if side == "LONG" and current_price >= tp1 * 0.998:
                send_tp1_alert(symbol, market_type, "LONG", current_price, tp1)
                tp1_notified[base_key] = True
            elif side == "SHORT" and current_price <= tp1 * 1.002:
                send_tp1_alert(symbol, market_type, "SHORT", current_price, tp1)
                tp1_notified[base_key] = True

    # اعمال تابع بررسی بازار، ضد رنج و فیلتر روند
    signal_side, reason = check_market_condition_and_signal(candles, VOLUME_MULTIPLIER)

    if signal_side == "LONG":
        base_key = f"{symbol}_{market_type}_LONG"
        now_ts = time.time()

        prev = last_signals.get(base_key)
        if prev:
            if now_ts - prev.get("ts", 0) < SIGNAL_COOLDOWN_SEC:
                return
            if REPEAT_SAME_PATTERN_BLOCK and prev.get("pattern") == "Explosive Breakout (Trend Follow)":
                return

        sl = current_price * (1 - SL_PERCENT)
        tp1 = current_price * (1 + TP1_PERCENT)
        tp2 = current_price * (1 + TP2_PERCENT)
        in_low = current_price * 0.997
        in_high = current_price * 0.999

        last_signals[base_key] = {
            "side": "LONG",
            "tp1": tp1,
            "pattern": "Explosive Breakout (Trend Follow)",
            "price": current_price,
            "ts": now_ts,
            "candle_time": last_candle_time
        }
        tp1_notified[base_key] = False

        send_telegram_signal(symbol, market_type, "LONG", current_price, "Explosive Breakout (Trend Follow)", market_trend, in_low, in_high, sl, tp1, tp2)
        return

    elif signal_side == "SHORT" and market_type == "MARGIN":
        base_key = f"{symbol}_{market_type}_SHORT"
        now_ts = time.time()

        prev = last_signals.get(base_key)
        if prev:
            if now_ts - prev.get("ts", 0) < SIGNAL_COOLDOWN_SEC:
                return
            if REPEAT_SAME_PATTERN_BLOCK and prev.get("pattern") == "Explosive Breakdown (Trend Follow)":
                return

        sl = current_price * (1 + SL_PERCENT)
        tp1 = current_price * (1 - TP1_PERCENT)
        tp2 = current_price * (1 - TP2_PERCENT)
        in_low = current_price * 1.001
        in_high = current_price * 1.003

        last_signals[base_key] = {
            "side": "SHORT",
            "tp1": tp1,
            "pattern": "Explosive Breakdown (Trend Follow)",
            "price": current_price,
            "ts": now_ts,
            "candle_time": last_candle_time
        }
        tp1_notified[base_key] = False

        send_telegram_signal(symbol, market_type, "SHORT", current_price, "Explosive Breakdown (Trend Follow)", market_trend, in_low, in_high, sl, tp1, tp2)

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    ping_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    ping_thread.start()

    send_telegram_message("🤖 <b>ربات با ضد رنج پیشرفته، روند EMA و حجم ۲ برابری فعال شد!</b> 🚀")

    spot_symbols = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "ADA_USDT",
        "AVAX_USDT", "LINK_USDT", "DOT_USDT", "TRX_USDT", "LTC_USDT", "BCH_USDT",
        "XLM_USDT", "ETC_USDT", "ALGO_USDT", "HBAR_USDT", "ICP_USDT", "NEAR_USDT",
        "UNI_USDT", "ATOM_USDT", "SUI_USDT", "APT_USDT", "ARB_USDT", "OP_USDT",
        "INJ_USDT", "TIA_USDT", "FTM_USDT", "SEI_USDT", "STX_USDT", "FIL_USDT",
        "TON_USDT", "KAS_USDT", "AR_USDT", "PYTH_USDT", "JUP_USDT", "SHIB_USDT",
        "PEPE_USDT", "FLOKI_USDT", "BONK_USDT", "WIF_USDT", "FET_USDT", "RENDER_USDT",
        "ORDI_USDT", "AAVE_USDT", "CRV_USDT", "DYDX_USDT", "SAND_USDT", "MANA_USDT",
        "GALA_USDT", "CHZ_USDT", "AXS_USDT", "ENJ_USDT", "GMT_USDT", "BTC_IRT",
        "ETH_IRT", "SOL_IRT", "XRP_IRT", "DOGE_IRT", "ADA_IRT", "AVAX_IRT",
        "PEPE_IRT", "SHIB_IRT", "TON_IRT", "FLOKI_IRT", "TRX_IRT", "LINK_IRT",
        "DOT_IRT", "NEAR_IRT", "SUI_IRT"
    ]
    
    margin_symbols = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "ADA_USDT",
        "AVAX_USDT", "LINK_USDT", "DOT_USDT", "TRX_USDT", "LTC_USDT", "BCH_USDT",
        "NEAR_USDT", "UNI_USDT", "ATOM_USDT", "SUI_USDT", "APT_USDT", "ARB_USDT",
        "OP_USDT", "INJ_USDT", "TIA_USDT", "FTM_USDT", "SEI_USDT", "STX_USDT",
        "FIL_USDT", "TON_USDT", "PEPE_USDT", "SHIB_USDT", "FET_USDT", "RENDER_USDT"
    ]

    last_trend_check = 0
    market_trend = "NEUTRAL"

    while type(True) is bool:
        try:
            if len(last_signals) > 200:
                last_signals.clear()
                tp1_notified.clear()

            if time.time() - last_trend_check >= 900 or last_trend_check == 0:
                market_trend = get_market_trend()
                print(f"[{time.strftime('%H:%M:%S')}] Bitcoin Trend (1H): {market_trend}")
                last_trend_check = time.time()

            for sym in spot_symbols:
                candles = get_candles(sym)
                if candles:
                    analyze_market(sym, "SPOT", candles, market_trend)
                time.sleep(0.2)

            for sym in margin_symbols:
                candles = get_candles(sym)
                if candles:
                    analyze_market(sym, "MARGIN", candles, market_trend)
                time.sleep(0.2)

            time.sleep(15)
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)
