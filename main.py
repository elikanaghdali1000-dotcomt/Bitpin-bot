import os
import math
import time
import requests
import threading
import numpy as np
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- تنظیمات تلگرام (استفاده از متغیرهای محیطی برای امنیت) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PUT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_CHAT_ID_HERE")

# آدرس عمومی رندر برای پینگ Keep-Alive
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

# --- تنظیمات استراتژی و ضد رنج هوشمند ---
SQUEEZE_RATIO = 0.35
MIN_BANDWIDTH = 0.008

SL_PERCENT = 0.012
TP1_PERCENT = 0.010
TP2_PERCENT = 0.020
VOLUME_MULTIPLIER = 1.5

# --- ضد اسپم / ضد تکرار ---
SIGNAL_COOLDOWN_SEC = 45 * 60
REPEAT_SAME_PATTERN_BLOCK = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

session = requests.Session()
session.headers.update(HEADERS)

last_signals = {}
tp1_notified = {}
sl_notified = {}
last_processed_candle_time = {} # جلوگیری از بررسی تکراری یک کندل بسته
resistance_cache_1h = {}        # کش مقاومت‌های ۱ ساعته
last_heartbeat_log = 0          # اصلاح متغیر هرت‌بیت

def format_number(val):
    """
    فرمت کردن اعداد بدون نماد ارزی، برای قرارگیری داخل تگ code تلگرام جهت کپی آسان
    """
    if val is None:
        return "0"
    if val < 0.0001:
        return f"{val:.8f}".rstrip('0').rstrip('.')
    elif val < 1:
        return f"{val:.4f}".rstrip('0').rstrip('.')
    else:
        return f"{val:,.2f}"

def send_telegram_message(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        res = session.post(url, data=payload, timeout=6)
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

def normalize_ts(ts_value):
    try:
        ts_val = int(ts_value)
        if ts_val > 10**12:
            return ts_val / 1000
        return ts_val
    except:
        return 0

def calculate_ema(data, window):
    if len(data) < window:
        return np.mean(data)
    alpha = 2 / (window + 1)
    ema = data[0]
    for price in data[1:]:
        ema = (price * alpha) + (ema * (1 - alpha))
    return ema

def get_candles(symbol, timeframe="15m"):
    now = int(time.time())
    lookback = 60 * 60 * 24 * 3
    url = "https://api.bitpin.org/api/v1/mkt/candles/"
    params = {
        "symbol": symbol,
        "from": now - lookback,
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
                    ts_val = item.get("ts", item.get("time", 0))
                    candles_list.append({
                        "open": float(item["open"]),
                        "close": float(item["close"]),
                        "high": float(item["high"]),
                        "low": float(item["low"]),
                        "volume": float(item.get("volume", 0)),
                        "time": normalize_ts(ts_val)
                    })
                return candles_list
        return []
    except Exception as e:
        print(f"[ERROR] Candle fetch exception for {symbol}: {e}")
        return []

def get_1h_resistance_support(symbol):
    now = time.time()
    cache = resistance_cache_1h.get(symbol)
    if cache and (now - cache["time"] < 600):
        return cache["res"], cache["sup"]

    candles_1h = get_candles(symbol, timeframe="1h")
    if len(candles_1h) < 30:
        return None, None

    highs = np.array([c["high"] for c in candles_1h[:-1]], dtype=float)
    lows = np.array([c["low"] for c in candles_1h[:-1]], dtype=float)

    major_res = np.max(highs[-60:]) if len(highs) >= 60 else np.max(highs)
    major_sup = np.min(lows[-60:]) if len(lows) >= 60 else np.min(lows)

    resistance_cache_1h[symbol] = {
        "res": major_res,
        "sup": major_sup,
        "time": now
    }
    return major_res, major_sup

def check_healthy_pullback(candles, breakout_level, side):
    if len(candles) < 3:
        return False

    sig_candle = candles[-2]
    current_candle = candles[-1]
    
    if side == "LONG":
        breakout_body = max(sig_candle['close'] - sig_candle['open'], 1e-12)
        min_allowed_level = min(breakout_level, sig_candle['close'] - (breakout_body * 0.5))
        closed_well = current_candle['close'] >= min_allowed_level
        not_heavy_dump = current_candle['volume'] <= sig_candle['volume'] * 1.2
        held_structure = current_candle['low'] >= (min_allowed_level * 0.995)
        return closed_well and not_heavy_dump and held_structure

    elif side == "SHORT":
        breakout_body = max(abs(sig_candle['close'] - sig_candle['open']), 1e-12)
        max_allowed_level = max(breakout_level, sig_candle['close'] + (breakout_body * 0.5))
        closed_well = current_candle['close'] <= max_allowed_level
        not_heavy_pump = current_candle['volume'] <= sig_candle['volume'] * 1.2
        held_structure = current_candle['high'] <= (max_allowed_level * 1.005)
        return closed_well and not_heavy_pump and held_structure

    return False

def check_market_condition_and_signal(symbol, candles, tight_volume_multiplier=1.5):
    if len(candles) < 210:
        return "HOLD", 0, 0, f"داده‌های کندل کافی نیست ({len(candles)} کندل)"

    sig_candle = candles[-2]
    current_price_for_eval = sig_candle["close"]

    closes = np.array([c["close"] for c in candles[:-1]], dtype=float)
    highs = np.array([c["high"] for c in candles[:-1]], dtype=float)
    lows = np.array([c["low"] for c in candles[:-1]], dtype=float)
    volumes = np.array([c["volume"] for c in candles[:-1]], dtype=float)

    ema_50 = calculate_ema(closes, 50)
    ema_200 = calculate_ema(closes, 200)

    sma_20_now = np.mean(closes[-20:])
    std_20_now = np.std(closes[-20:])
    upper_band_now = sma_20_now + (2.0 * std_20_now)
    lower_band_now = sma_20_now - (2.0 * std_20_now)
    bandwidth_now = (upper_band_now - lower_band_now) / sma_20_now

    if bandwidth_now < MIN_BANDWIDTH:
        return "HOLD", 0, 0, "سکوت: بازار رنج و بولینگر فشرده (Low Bandwidth)"

    sma_20_prev = np.mean(closes[-21:-1])
    std_20_prev = np.std(closes[-21:-1])
    upper_band_prev = sma_20_prev + (2.0 * std_20_prev)
    lower_band_prev = sma_20_prev - (2.0 * std_20_prev)

    sig_open = sig_candle["open"]
    sig_close = sig_candle["close"]
    sig_high = sig_candle["high"]
    sig_low = sig_candle["low"]
    sig_volume = sig_candle["volume"]
    avg_volume = np.mean(volumes[-21:-1]) if len(volumes) >= 21 else np.mean(volumes[:-1])

    is_candle_green = sig_close > sig_open
    is_candle_red = sig_close < sig_open

    body_size = abs(sig_close - sig_open)
    total_range = sig_high - sig_low
    if total_range == 0:
        total_range = 1e-12

    upper_shadow = sig_high - max(sig_close, sig_open)
    lower_shadow = min(sig_close, sig_open) - sig_low

    clean_bullish_close = (upper_shadow / total_range) <= 0.35
    clean_bearish_close = (lower_shadow / total_range) <= 0.35

    is_wide_mouth_trap = (upper_shadow > body_size * 2.5) or (lower_shadow > body_size * 2.5)
    if is_wide_mouth_trap:
        return "HOLD", 0, 0, "سکوت: شدوی خطرناک و تله رنج"

    major_res_1h, major_sup_1h = get_1h_resistance_support(symbol)
    if major_res_1h and major_sup_1h:
        dist_to_res = (major_res_1h - sig_close) / sig_close
        not_directly_under_resistance = (sig_close >= major_res_1h) or (dist_to_res > 0.008)

        dist_to_sup = (sig_close - major_sup_1h) / sig_close
        not_directly_above_support = (sig_close <= major_sup_1h) or (dist_to_sup > 0.008)
    else:
        not_directly_under_resistance = True
        not_directly_above_support = True

    recent_ranges = highs[-6:] - lows[-6:]
    avg_recent_range = np.mean(recent_ranges)

    has_explosive_volume = (sig_volume >= avg_volume * tight_volume_multiplier)

    is_uptrend = (sig_close > ema_50) and (ema_50 > ema_200)
    is_downtrend = (sig_close < ema_50) and (ema_50 < ema_200)

    prev_close = closes[-2]

    if is_uptrend and has_explosive_volume and not_directly_under_resistance:
        if is_candle_green and (sig_close > upper_band_now) and (total_range > avg_recent_range * 0.9) and clean_bullish_close:
            return "LONG", upper_band_now, current_price_for_eval, "سیگنال بریک‌اوت صعودی معتبر (Momentum Breakout)"
        
        if prev_close > upper_band_prev:
            if check_healthy_pullback(candles, upper_band_now, "LONG"):
                return "LONG", upper_band_now, current_price_for_eval, "سیگنال خرید پولبک تاییدشده (Pullback Confirmation)"

    if is_downtrend and has_explosive_volume and not_directly_above_support:
        if is_candle_red and (sig_close < lower_band_now) and (total_range > avg_recent_range * 0.9) and clean_bearish_close:
            return "SHORT", lower_band_now, current_price_for_eval, "سیگنال بریک‌داون نزولی معتبر (Momentum Breakdown)"

        if prev_close < lower_band_prev:
            if check_healthy_pullback(candles, lower_band_now, "SHORT"):
                return "SHORT", lower_band_now, current_price_for_eval, "سیگنال فروش پولبک تاییدشده (Pullback Confirmation)"

    return "HOLD", 0, 0, "بازار خنثی یا عدم تایید شرایط ورود"

def send_telegram_signal(symbol, market_type, side, price, pattern, btc_trend, entry_min, entry_max, sl, tp1, tp2):
    emoji = "🟢" if side == "LONG" else "🔴"
    side_title = "خرید (لانگ)" if side == "LONG" else "فروش (شورت)"
    market_label = "💎 بازار اسپات (Spot)" if market_type == "SPOT" else "⚡️ بازار تعهدی (Margin)"

    message = (
        f"{emoji} سیگنال {side_title} (<b>#{symbol}</b>)\n"
        f"📌 نوع بازار: {market_label}\n"
        f"💵 قیمت فعلی: <code>{format_number(price)}</code>\n"
        f"📊 الگو: {pattern}\n\n"
        f"🎯 محدوده ورود: <code>{format_number(entry_min)}</code> تا <code>{format_number(entry_max)}</code>\n"
        f"📉 حد سود اول (TP1): <code>{format_number(tp1)}</code>\n"
        f"🚀 حد سود دوم (TP2): <code>{format_number(tp2)}</code>\n"
        f"🛑 حد ضرر (SL): <code>{format_number(sl)}</code>\n"
        f"⚡️ روند بیت‌کوین: {btc_trend}"
    )
    send_telegram_message(message)

def send_tp1_alert(symbol, market_type, side, entry_price, current_price, tp1):
    side_fa = "لانگ (خرید)" if side == "LONG" else "شورت (فروش)"
    market_fa = "اسپات" if market_type == "SPOT" else "مارجین"
    
    if entry_price and entry_price > 0:
        if side == "LONG":
            pnl = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl = ((entry_price - current_price) / entry_price) * 100
        pnl_text = f"+{pnl:.2f}% 🚀"
    else:
        pnl_text = "+1.00% 🚀"

    msg = (
        "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n"
        "🎯 تارگت اول لمس شد! (TP1)\n"
        f"💰 سود ثبت‌شده: <code>{pnl_text}</code>\n"
        "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩\n\n"
        f"💎 نماد: <b>#{symbol}</b>\n"
        f"⚡️ موقعیت: {side_fa} | {market_fa}\n\n"
        f"▫️ قیمت ورود: <code>{format_number(entry_price)}</code>\n"
        f"▫️ قیمت لمس: <code>{format_number(current_price)}</code>\n"
        f"▫️ حد سود ۱: <code>{format_number(tp1)}</code>\n\n"
        "⚠️ پیشنهاد ریسک‌فری: انتقال حد ضرر به نقطه ورود."
    )
    send_telegram_message(msg)

def send_sl_alert(symbol, market_type, side, entry_price, current_price, sl):
    side_fa = "لانگ (خرید)" if side == "LONG" else "شورت (فروش)"
    market_fa = "اسپات" if market_type == "SPOT" else "مارجین"
    
    if entry_price and entry_price > 0:
        if side == "LONG":
            pnl = ((current_price - entry_price) / entry_price) * 100
        else:
            pnl = ((entry_price - current_price) / entry_price) * 100
        pnl_text = f"{pnl:.2f}% ❌"
    else:
        pnl_text = f"-{SL_PERCENT*100:.2f}% ❌"

    msg = (
        "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n"
        "🛑 حد ضرر فعال شد! (STOP)\n"
        f"🔻 برآیند معامله: <code>{pnl_text}</code>\n"
        "🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥\n\n"
        f"💎 نماد: <b>#{symbol}</b>\n"
        f"⚡️ موقعیت: {side_fa} | {market_fa}\n\n"
        f"▫️ قیمت ورود: <code>{format_number(entry_price)}</code>\n"
        f"▫️ قیمت خروج: <code>{format_number(current_price)}</code>\n"
        f"▫️ حد ضرر: <code>{format_number(sl)}</code>\n\n"
        "⛔️ استاپ‌لاس لمس شد."
    )
    send_telegram_message(msg)

def get_market_trend():
    try:
        candles_1h = get_candles("BTC_USDT", timeframe="1h")
        candles_15m = get_candles("BTC_USDT", timeframe="15m")
        
        if len(candles_15m) >= 2:
            btc_last_close = candles_15m[-1]["close"]
            btc_prev_close = candles_15m[-2]["close"]
            if (btc_prev_close - btc_last_close) / btc_prev_close > 0.008:
                return "BTC_DUMPING"

        if len(candles_1h) >= 20:
            closes = [c["close"] for c in candles_1h]
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

    last_closed_candle = candles[-2]
    candle_ts = last_closed_candle["time"]
    state_key = f"{symbol}_{market_type}"
    
    is_new_candle = last_processed_candle_time.get(state_key) != candle_ts
    if is_new_candle:
        last_processed_candle_time[state_key] = candle_ts

    current_price = candles[-1]["close"]

    base_key_long = f"{symbol}_{market_type}_LONG"
    base_key_short = f"{symbol}_{market_type}_SHORT"

    # مدیریت پوزیشن‌های باز در هر دور اجرا می‌شود
    for base_key in (base_key_long, base_key_short):
        saved = last_signals.get(base_key)
        if not saved:
            continue

        side = saved["side"]
        entry_p = saved.get("entry", current_price)
        sl_val = saved.get("sl")
        tp1 = saved["tp1"]

        if not sl_notified.get(base_key, False) and sl_val:
            is_sl_hit = False
            if side == "LONG" and current_price <= sl_val:
                is_sl_hit = True
            elif side == "SHORT" and current_price >= sl_val:
                is_sl_hit = True

            if is_sl_hit:
                send_sl_alert(symbol, market_type, side, entry_p, current_price, sl_val)
                sl_notified[base_key] = True
                last_signals.pop(base_key, None)
                tp1_notified.pop(base_key, None)
                sl_notified.pop(base_key, None)
                continue

        if not tp1_notified.get(base_key, False):
            if side == "LONG" and current_price >= tp1 * 0.998:
                send_tp1_alert(symbol, market_type, "LONG", entry_p, current_price, tp1)
                tp1_notified[base_key] = True
                last_signals[base_key]["sl"] = entry_p
            elif side == "SHORT" and current_price <= tp1 * 1.002:
                send_tp1_alert(symbol, market_type, "SHORT", entry_p, current_price, tp1)
                tp1_notified[base_key] = True
                last_signals[base_key]["sl"] = entry_p

    # تحلیل جدید فقط وقتی کندل جدید بسته شده باشد انجام می‌شود
    if not is_new_candle:
        return

    signal_side, breakout_level, eval_price, reason = check_market_condition_and_signal(symbol, candles, VOLUME_MULTIPLIER)

    if market_trend == "BTC_DUMPING":
        return

    # فیلتر روند (در بازار NEUTRAL اجازه سیگنال با احتیاط داده می‌شود مگر در خلاف جهت روند اصلی)
    if market_trend == "BULLISH" and signal_side == "SHORT":
        return
    if market_trend == "BEARISH" and signal_side == "LONG":
        return

    if signal_side == "LONG":
        base_key = f"{symbol}_{market_type}_LONG"
        now_ts = time.time()

        prev = last_signals.get(base_key)
        if prev:
            if now_ts - prev.get("ts", 0) < SIGNAL_COOLDOWN_SEC:
                return
            if REPEAT_SAME_PATTERN_BLOCK and prev.get("pattern") == reason:
                return

        sl = breakout_level * (1 - SL_PERCENT)
        tp1 = eval_price * (1 + TP1_PERCENT)
        tp2 = eval_price * (1 + TP2_PERCENT)
        in_low = breakout_level * 0.998
        in_high = breakout_level * 1.002

        last_signals[base_key] = {
            "side": "LONG",
            "entry": eval_price,
            "sl": sl,
            "tp1": tp1,
            "pattern": reason,
            "price": eval_price,
            "ts": now_ts,
            "candle_time": candle_ts
        }
        tp1_notified[base_key] = False
        sl_notified[base_key] = False

        send_telegram_signal(symbol, market_type, "LONG", eval_price, reason, market_trend, in_low, in_high, sl, tp1, tp2)
        return

    elif signal_side == "SHORT" and market_type == "MARGIN":
        base_key = f"{symbol}_{market_type}_SHORT"
        now_ts = time.time()

        prev = last_signals.get(base_key)
        if prev:
            if now_ts - prev.get("ts", 0) < SIGNAL_COOLDOWN_SEC:
                return
            if REPEAT_SAME_PATTERN_BLOCK and prev.get("pattern") == reason:
                return

        sl = breakout_level * (1 + SL_PERCENT)
        tp1 = eval_price * (1 - TP1_PERCENT)
        tp2 = eval_price * (1 - TP2_PERCENT)
        in_low = breakout_level * 0.998
        in_high = breakout_level * 1.002

        last_signals[base_key] = {
            "side": "SHORT",
            "entry": eval_price,
            "sl": sl,
            "tp1": tp1,
            "pattern": reason,
            "price": eval_price,
            "ts": now_ts,
            "candle_time": candle_ts
        }
        tp1_notified[base_key] = False
        sl_notified[base_key] = False

        send_telegram_signal(symbol, market_type, "SHORT", eval_price, reason, market_trend, in_low, in_high, sl, tp1, tp2)

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    ping_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    ping_thread.start()

    send_telegram_message("🤖 ربات تحلیل‌گر بیت‌پین با موفقیت و نسخه بهینه‌شده استارت شد! 🚀")

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
        "DOT_IRT", "NEAR_IRT", "SUI_IRT", "ZEC_USDT"
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
    scan_round = 0

    while True:
        try:
            scan_round += 1

            if len(last_signals) > 200:
                last_signals.clear()
                tp1_notified.clear()
                sl_notified.clear()

            if time.time() - last_trend_check >= 900 or last_trend_check == 0:
                market_trend = get_market_trend()
                print(f"[{time.strftime('%H:%M:%S')}] Bitcoin Trend (1H): {market_trend}")
                last_trend_check = time.time()

            now_ts = time.time()
            if now_ts - last_heartbeat_log >= 300:
                print(f"[{time.strftime('%H:%M:%S')}] HEARTBEAT | دور اسکن: #{scan_round}")
                last_heartbeat_log = now_ts

            print(f"[{time.strftime('%H:%M:%S')}] شروع دور اسکن بازار #{scan_round}...")

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

            print(f"[{time.strftime('%H:%M:%S')}] پایان دور اسکن #{scan_round}...")
            time.sleep(15)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)
