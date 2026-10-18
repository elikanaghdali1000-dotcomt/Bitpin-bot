import math
import time
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- تنظیمات تلگرام ---
TELEGRAM_TOKEN = "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo"  # توکن واقعی خودتان
CHAT_ID = "6643451227"

# --- تنظیمات استراتژی و ضد رنج هوشمند ---
PULLBACK_TOLERANCE = 0.003
LEVEL_TOLERANCE = 0.004
PULLBACK_LOOKBACK = 10
SQUEEZE_RATIO = 0.65

# تنظیمات حد سود و ضرر برای بازارها
SL_PERCENT = 0.015   # ۱.۵ درصد حد ضرر
TP1_PERCENT = 0.0225 # ۲.۲۵ درصد حد سود اول
TP2_PERCENT = 0.0375 # ۳.۷۵ درصد حد سود دوم

HEADERS = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}

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
        response = requests.post(url, json=payload, timeout=5)
        print("Telegram Startup Message Code:", response.status_code)
    except Exception as e:
        print(f"Telegram Startup Error: {e}")


# --- وب‌سرور برای زنده ماندن 24 ساعته در رندر ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bitpin Anti-Range Pro Trading Bot with Spot & Margin is running!")

def run_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHTTPRequestHandler)
    server.serve_forever()


def calculate_adx_array(highs, lows, closes, period=14):
    adx_list = [0.0] * len(closes)
    if len(closes) < period + 1:
        return adx_list
    
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        tr_list.append(tr)
        
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        
    for i in range(period, len(tr_list)):
        sub_tr = tr_list[i-period:i]
        sub_p = plus_dm_list[i-period:i]
        sub_m = minus_dm_list[i-period:i]
        
        atr = sum(sub_tr) / period
        if atr == 0:
            continue
        plus_di = 100 * (sum(sub_p) / period) / atr
        minus_di = 100 * (sum(sub_m) / period) / atr
        
        dx_den = plus_di + minus_di
        dx = 100 * (abs(plus_di - minus_di) / dx_den) if dx_den > 0 else 0
        if i + 1 < len(adx_list):
            adx_list[i+1] = dx

    if len(adx_list) > 1 and adx_list[-1] == 0.0:
        adx_list[-1] = adx_list[-2]
        
    return adx_list


def validate_trend_and_volume(adx_array, volumes, index=-1, min_adx=20.0, dynamic_min_adx=16.0, volume_multiplier=.85):
    try:
        current_adx = adx_array[index]
        current_volume = volumes[index]
        avg_volume = sum(volumes[index-5:index]) / 5.0 if index >= 5 else current_volume
        
        if current_adx >= min_adx:
            return True
        if (current_adx >= dynamic_min_adx) and (current_volume >= (avg_volume * volume_multiplier)):
            return True
        return False
    except Exception as e:
        print(f"Error in validate_trend_and_volume: {e}")
        return False


def send_telegram_signal(symbol, market_type, side, price, pattern, btc_trend, entry_min, entry_max, sl, tp1, tp2):
    emoji = "🟢" if side == "LONG" else "🔴"
    side_title = "خرید (لانگ)" if side == "LONG" else "فروش (شورت)"
    market_label = "💎 بازار اسپات (Spot)" if market_type == "SPOT" else "⚡️ بازار تعهدی (Margin)"

    message = (
        f"{emoji} <b>سیگنال {side_title} ({symbol})</b>\n"
        f"📌 <b>نوع بازار:</b> {market_label}\n"
        f"💵 <b>قیمت فعلی:</b> <code>{format_price(price)}</code>\n"
        f"📊 <b>الگو:</b> {pattern}\n\n"
        f"🎯 <b>محدوده ورود:</b> <code>{format_price(entry_min)}</code> - <code>{format_price(entry_max)}</code>\n"
        f"📉 <b>حد سود اول (TP1):</b> <code>{format_price(tp1)}</code>\n"
        f"🚀 <b>حد سود دوم (TP2):</b> <code>{format_price(tp2)}</code>\n"
        f"🛑 <b>حد ضرر (SL):</b> <code>{format_price(sl)}</code>\n"
        f"⚡️ <b>روند کل بازار:</b> <code>{btc_trend}</code>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram Error: {e}")


def send_tp1_alert(symbol, market_type, side, current_price, tp1):
    side_fa = "خرید (لانگ)" if side == "LONG" else "فروش (شورت)"
    message = (
        f"⚠️ <b>رسیدن به حد سود اول (TP1)! ({symbol})</b>\n"
        f"📌 <b>بازار:</b> {market_type} | <b>جهت:</b> {side_fa}\n"
        f"💵 <b>قیمت فعلی:</b> <code>{format_price(current_price)}</code>\n"
        f"🎯 <b>تارگت TP1:</b> <code>{format_price(tp1)}</code>\n\n"
        f"👉 <b>برو صرافی و حد ضرر را ریسک‌فری کن!</b>"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram TP1 Alert Error: {e}")


def get_market_trend():
    try:
        url = "https://api.bitpin.ir/v1/mkt/tv/history"
        params = {
            "symbol": "BTC_USDT",
            "from": int(time.time()) - 86400,
            "to": int(time.time()),
            "resolution": "60",
        }
        res = requests.get(url, params=params, headers=HEADERS, timeout=7)
        data = res.json()
        if not data or "c" not in data or len(data["c"]) < 20:
            return "NEUTRAL"

        closes = [float(x) for x in data["c"]]
        sma_20 = sum(closes[-20:]) / 20.0
        if closes[-1] > sma_20 * 1.002:
            return "BULLISH"
        elif closes[-1] < sma_20 * 0.998:
            return "BEARISH"
        else:
            return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


def get_candles(symbol):
    try:
        url = "https://api.bitpin.ir/v1/mkt/tv/history"
        params = {
            "symbol": symbol,
            "from": int(time.time()) - 43200,
            "to": int(time.time()),
            "resolution": "15",
        }
        res = requests.get(url, params=params, headers=HEADERS, timeout=7)
        data = res.json()
        if data and "c" in data and len(data["c"]) > 0:
            candles_list = []
            for i in range(len(data["c"])):
                candles_list.append({
                    "close": data["c"][i],
                    "high": data["h"][i],
                    "low": data["l"][i],
                    "volume": data["v"][i] if "v" in data and i < len(data["v"]) else 1.0,
                    "time": i
                })
            return candles_list
        return []
    except Exception:
        return []


def check_orderbook_pressure(symbol, side):
    try:
        url = f"https://api.bitpin.org/api/v1/mkt/markets/{symbol}/orderbook/"
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if bids and asks:
                total_bid_volume = sum(float(item[1]) for item in bids[:10] if len(item) >= 2)
                total_ask_volume = sum(float(item[1]) for item in asks[:10] if len(item) >= 2)
                if total_bid_volume > 0 and total_ask_volume > 0:
                    if side == "LONG" and total_bid_volume < (total_ask_volume * 0.4):
                        return False
                    if side == "SHORT" and total_ask_volume < (total_bid_volume * 0.4):
                        return False
    except Exception:
        pass
    return True


def analyze_market(symbol, market_type, candles, market_trend):
    if len(candles) < 30:
        return

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    volumes = [float(c["volume"]) for c in candles]
    last_candle_time = candles[-1].get("time", 0)
    current_price = closes[-1]

    for sig_key in list(last_signals.keys()):
        if sig_key.startswith(f"{symbol}_{market_type}"):
            saved_data = last_signals[sig_key]
            side = saved_data["side"]
            tp1 = saved_data["tp1"]

            if not tp1_notified.get(sig_key, False):
                if side == "LONG" and current_price >= tp1 * 0.998:
                    send_tp1_alert(symbol, market_type, "LONG", current_price, tp1)
                    tp1_notified[sig_key] = True
                elif side == "SHORT" and current_price <= tp1 * 1.002:
                    send_tp1_alert(symbol, market_type, "SHORT", current_price, tp1)
                    tp1_notified[sig_key] = True

    sma20 = sum(closes[-20:]) / 20.0
    variance = sum((x - sma20) ** 2 for x in closes[-20:]) / 20.0
    std_dev = math.sqrt(variance)
    upper_band = sma20 + (2 * std_dev)
    lower_band = sma20 - (2 * std_dev)

    adx_array = calculate_adx_array(highs, lows, closes)
    if not validate_trend_and_volume(adx_array, volumes):
        return

    bandwidths = []
    for i in range(15, 0, -1):
        idx = -i
        sub_closes = closes[idx - 20 : idx]
        if len(sub_closes) == 20:
            m = sum(sub_closes) / 20.0
            v = sum((x - m) ** 2 for x in sub_closes) / 20.0
            s = math.sqrt(v)
            bandwidths.append(((m + 2 * s) - (m - 2 * s)) / m if m > 0 else 0)

    current_bandwidth = (upper_band - lower_band) / sma20 if sma20 > 0 else 0
    max_recent_bw = max(bandwidths) if bandwidths else current_bandwidth
    is_squeeze = current_bandwidth <= (max_recent_bw * SQUEEZE_RATIO)

    dist_to_sma = abs(current_price - sma20) / sma20
    recent_high = max(highs[-PULLBACK_LOOKBACK:-1])
    recent_low = min(lows[-PULLBACK_LOOKBACK:-1])

    # ۱. سناریوی خرید (LONG) - برای هر دو بازار اسپات و تعهدی
    long_pattern = None
    if current_price > sma20:
        if is_squeeze and current_price > upper_band * 0.998:
            long_pattern = "Explosive Breakout"
        elif abs(current_price - recent_high) / recent_high <= LEVEL_TOLERANCE:
            long_pattern = "Pullback to Res"
        elif dist_to_sma <= PULLBACK_TOLERANCE:
            long_pattern = "Pullback to SMA20"

    if long_pattern:
        if check_orderbook_pressure(symbol, "LONG"):
            sig_id = f"{symbol}_{market_type}_LONG_{last_candle_time}"
            if sig_id not in last_signals:
                sl = current_price * (1 - SL_PERCENT)
                tp1 = current_price * (1 + TP1_PERCENT)
                tp2 = current_price * (1 + TP2_PERCENT)
                in_low = current_price * 0.997
                in_high = current_price * 0.999

                last_signals[sig_id] = {"side": "LONG", "tp1": tp1}
                tp1_notified[sig_id] = False

                send_telegram_signal(symbol, market_type, "LONG", current_price, long_pattern, market_trend, in_low, in_high, sl, tp1, tp2)
                return

    # ۲. سناریوی فروش شورت (SHORT) - فقط برای بازار تعهدی (Margin)
    if market_type == "MARGIN":
        short_pattern = None
        if current_price < sma20:
            if is_squeeze and current_price < lower_band * 1.002:
                short_pattern = "Explosive Breakdown"
            elif abs(current_price - recent_low) / recent_low <= LEVEL_TOLERANCE:
                short_pattern = "Pullback to Sup"
            elif dist_to_sma <= PULLBACK_TOLERANCE:
                short_pattern = "Pullback to SMA20"

        if short_pattern:
            if check_orderbook_pressure(symbol, "SHORT"):
                sig_id = f"{symbol}_{market_type}_SHORT_{last_candle_time}"
                if sig_id not in last_signals:
                    sl = current_price * (1 + SL_PERCENT)
                    tp1 = current_price * (1 - TP1_PERCENT)
                    tp2 = current_price * (1 - TP2_PERCENT)
                    in_low = current_price * 1.001
                    in_high = current_price * 1.003

                    last_signals[sig_id] = {"side": "SHORT", "tp1": tp1}
                    tp1_notified[sig_id] = False

                    send_telegram_signal(symbol, market_type, "SHORT", current_price, short_pattern, market_trend, in_low, in_high, sl, tp1, tp2)


if __name__ == "__main__":
    # استارت وب‌سرور برای پایداری در رندر
    server_thread = threading.Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    print("Web server started on port 10000.")
    send_telegram_message("🤖 <b>ربات جامع بیت‌پین (اسپات و تعهدی) با موفقیت روشن شد!</b> 🚀")

    # لیست گسترده و جامع تمام ارزهای عالی و پرحجم اسپات بیت‌پین (USDT و IRT)
    spot_symbols = [
        # ارزهای اصلی و سنگین اسپات
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "ADA_USDT",
        "AVAX_USDT", "LINK_USDT", "DOT_USDT", "TRX_USDT", "LTC_USDT", "BCH_USDT",
        "XLM_USDT", "ETC_USDT", "ALGO_USDT", "HBAR_USDT", "ICP_USDT",
        
        # ارزهای پرپتانسیل و داغ لایه یک و لایه دو
        "NEAR_USDT", "UNI_USDT", "ATOM_USDT", "SUI_USDT", "APT_USDT", "ARB_USDT",
        "OP_USDT", "INJ_USDT", "TIA_USDT", "FTM_USDT", "SEI_USDT", "STX_USDT",
        "FIL_USDT", "TON_USDT", "KAS_USDT", "AR_USDT", "PYTH_USDT", "JUP_USDT",
        
        # میم‌کوین‌ها و هوش مصنوعی پرحجم اسپات
        "SHIB_USDT", "PEPE_USDT", "FLOKI_USDT", "BONK_USDT", "WIF_USDT", "FET_USDT",
        "RNDR_USDT", "ORDI_USDT",
        
        # دیفای، وب۳ و متاورس
        "AAVE_USDT", "CRV_USDT", "DYDX_USDT", "SAND_USDT", "MANA_USDT", "GALA_USDT",
        "CHZ_USDT", "AXS_USDT", "ENJ_USDT", "GMT_USDT",
        
        # جفت‌های تومانی برتر و پرحجم اسپات بیت‌پین (IRT)
        "BTC_IRT", "ETH_IRT", "SOL_IRT", "XRP_IRT", "DOGE_IRT", "ADA_IRT",
        "AVAX_IRT", "PEPE_IRT", "SHIB_IRT", "TON_IRT", "FLOKI_IRT", "TRX_IRT",
        "LINK_IRT", "DOT_IRT", "NEAR_IRT", "SUI_IRT"
    ]
    
    # ارزهای معامله تعهدی (مارجین) بیت‌پین با قابلیت لانگ و شورت
    margin_symbols = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "ADA_USDT",
        "AVAX_USDT", "LINK_USDT", "DOT_USDT", "TRX_USDT", "LTC_USDT", "BCH_USDT",
        "NEAR_USDT", "UNI_USDT", "ATOM_USDT", "SUI_USDT", "APT_USDT", "ARB_USDT",
        "OP_USDT", "INJ_USDT", "TIA_USDT", "FTM_USDT", "SEI_USDT", "STX_USDT",
        "FIL_USDT", "TON_USDT", "PEPE_USDT", "SHIB_USDT", "FET_USDT", "RNDR_USDT"
    ]

    print(f"تعداد ارزهای اسپات: {len(spot_symbols)} | تعداد ارزهای تعهدی: {len(margin_symbols)}")

    last_trend_check = 0
    market_trend = "NEUTRAL"

    while True:
        try:
            if time.time() - last_trend_check >= 900 or last_trend_check == 0:
                market_trend = get_market_trend()
                print(f"Market Trend (1H): {market_trend}")
                last_trend_check = time.time()

            # بررسی بازار اسپات (فقط لانگ)
            for sym in spot_symbols:
                candles = get_candles(sym)
                if candles:
                    analyze_market(sym, "SPOT", candles, market_trend)
                time.sleep(0.3)

            # بررسی بازار تعهدی (لانگ و شورت)
            for sym in margin_symbols:
                candles = get_candles(sym)
                if candles:
                    analyze_market(sym, "MARGIN", candles, market_trend)
                time.sleep(0.3)

            time.sleep(20)
        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(10)
