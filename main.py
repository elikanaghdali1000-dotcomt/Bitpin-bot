# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import numpy as np
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= تنظیمات اصلی =================
TELEGRAM_BOT_TOKEN = "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo"
TELEGRAM_CHAT_ID = "6643451227"
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

API_URL = "https://api.bitpin.ir/v1/mkt/markets/"
OHLC_URL = "https://api.bitpin.ir/v1/mkt/tv/history/"

BB_PERIOD = 20
BB_STD = 2.0
SL_PERCENT = 0.012
TP1_PERCENT = 0.015
TP2_PERCENT = 0.030
MIN_BANDWIDTH = 0.01
VOLUME_MULTIPLIER = 1.3
PULLBACK_VOLUME_MULT = 1.0

MAJOR_SR_BARS = 60
SR_SAFE_DISTANCE = 0.008

TIMEFRAME_15M = "15"
TIMEFRAME_1H = "60"
SCAN_INTERVAL = 30
SYMBOL_SLEEP = 0.65

SPOT_SYMBOLS = [
    "BTC_IRT", "ETH_IRT", "USDT_IRT", "SOL_IRT", "XRP_IRT", "ADA_IRT", "DOGE_IRT",
    "SHIB_IRT", "AVAX_IRT", "LINK_IRT", "DOT_IRT", "TRX_IRT", "MATIC_IRT", "LTC_IRT",
    "BCH_IRT", "NEAR_IRT", "UNI_IRT", "ICP_IRT", "APT_IRT", "FIL_IRT", "ATOM_IRT",
    "ARB_IRT", "OP_IRT", "XLM_IRT", "ETC_IRT", "HBAR_IRT", "INJ_IRT", "SUI_IRT",
    "RNDR_IRT", "TIA_IRT", "GRT_IRT", "ALGO_IRT", "FTM_IRT", "SAND_IRT", "MANA_IRT",
    "AXS_IRT", "THETA_IRT", "EGLD_IRT", "FLOW_IRT", "AAVE_IRT", "EOS_IRT", "KAVA_IRT",
    "GALA_IRT", "CHZ_IRT", "CRV_IRT", "MKR_IRT", "SNX_IRT", "RUNE_IRT", "DYDX_IRT",
    "BLUR_IRT", "WOO_IRT", "LDO_IRT", "APE_IRT", "QNT_IRT", "FET_IRT", "AGIX_IRT",
    "OCEAN_IRT", "ROSE_IRT", "ZIL_IRT", "ENJ_IRT", "1INCH_IRT", "COMP_IRT", "BAT_IRT",
    "LRC_IRT", "TWT_IRT", "MASK_IRT", "HOT_IRT", "JASMY_IRT", "PEPE_IRT", "FLOKI_IRT",
    "BONK_IRT", "WIF_IRT", "NOT_IRT", "TON_IRT", "KAS_IRT", "PENDLE_IRT"
]

MARGIN_SYMBOLS = [
    "BTC_IRT", "ETH_IRT", "USDT_IRT", "SOL_IRT", "XRP_IRT", "ADA_IRT", "DOGE_IRT",
    "SHIB_IRT", "AVAX_IRT", "LINK_IRT", "DOT_IRT", "TRX_IRT", "MATIC_IRT", "LTC_IRT",
    "BCH_IRT", "NEAR_IRT", "UNI_IRT", "ICP_IRT", "APT_IRT", "ARB_IRT", "OP_IRT",
    "TON_IRT", "NOT_IRT", "PEPE_IRT", "SUI_IRT", "FET_IRT", "WIF_IRT"
]

ALL_SYMBOLS = sorted(list(set(SPOT_SYMBOLS + MARGIN_SYMBOLS)))
open_positions = {}

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"OK - Bitpin Robot is Live and Scanning...")

    def log_message(self, format, *args):
        return

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), PingHandler)
    server.serve_forever()

def keep_alive_ping():
    while True:
        try:
            time.sleep(300)
            if APP_URL:
                requests.get(APP_URL, timeout=10)
        except Exception:
            pass

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        print(f"Telegram Error: {e}")

def safe_get_json(url, params=None, retries=3):
    headers = {'User-Agent': 'Mozilla/5.0'}
    for i in range(retries):
        try:
            res = requests.get(url, params=params, headers=headers, timeout=8, verify=False)
            if res.status_code == 200:
                return res.json()
        except requests.exceptions.RequestException:
            time.sleep(1)
    return None

def get_ohlcv(symbol, resolution, count=100):
    to_time = int(time.time())
    from_time = to_time - (count * int(resolution) * 60 * 2)
    params = {'symbol': symbol, 'resolution': resolution, 'from': from_time, 'to': to_time}
    data = safe_get_json(OHLC_URL, params=params)
    
    if not data or data.get('s') != 'ok':
        return None

    df = pd.DataFrame({
        'time': data['t'],
        'open': data['o'],
        'high': data['high'] if 'high' in data else data['h'],
        'low': data['low'] if 'low' in data else data['l'],
        'close': data['close'] if 'close' in data else data['c'],
        'volume': data['volume'] if 'volume' in data else data['v']
    })
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(inplace=True)
    return df

def analyze_symbol(symbol):
    df_15m = get_ohlcv(symbol, TIMEFRAME_15M, count=50)
    if df_15m is None or len(df_15m) < BB_PERIOD + 2:
        return None, None

    current_price = df_15m['close'].iloc[-1]

    current_minute = datetime.now(timezone.utc).minute
    if current_minute % 15 not in [11, 12, 13, 14, 0]:
        return None, current_price

    df_15m['bb_middle'] = df_15m['close'].rolling(window=BB_PERIOD).mean()
    df_15m['bb_std'] = df_15m['close'].rolling(window=BB_PERIOD).std()
    df_15m['bb_upper'] = df_15m['bb_middle'] + (df_15m['bb_std'] * BB_STD)
    df_15m['bb_lower'] = df_15m['bb_middle'] - (df_15m['bb_std'] * BB_STD)
    df_15m['volume_sma'] = df_15m['volume'].rolling(window=BB_PERIOD).mean()

    c_bandwidth = (df_15m['bb_upper'].iloc[-1] - df_15m['bb_lower'].iloc[-1]) / df_15m['bb_middle'].iloc[-1]
    if c_bandwidth < MIN_BANDWIDTH:
        return None, current_price

    df_1h = get_ohlcv(symbol, TIMEFRAME_1H, count=70)
    if df_1h is None or len(df_1h) < 25:
        return None, current_price

    df_1h['ema20'] = df_1h['close'].ewm(span=20, adjust=False).mean()
    h1_ema20 = df_1h['ema20'].iloc[-1]

    c_close = df_15m['close'].iloc[-1]
    c_open = df_15m['open'].iloc[-1]
    c_high = df_15m['high'].iloc[-1]
    c_low = df_15m['low'].iloc[-1]
    c_volume = df_15m['volume'].iloc[-1]
    avg_volume = df_15m['volume_sma'].iloc[-1]
    c_bb_upper = df_15m['bb_upper'].iloc[-1]
    c_bb_lower = df_15m['bb_lower'].iloc[-1]
    c_bb_middle = df_15m['bb_middle'].iloc[-1]

    # سقف و کف از کندل‌های قبلی ۱ ساعته گرفته می‌شود (نه کندل در حال تشکیل)
    past_h1 = df_1h.iloc[-MAJOR_SR_BARS:-1]
    major_resistance = past_h1['high'].max()
    major_support = past_h1['low'].min()

    recent_ranges = (df_15m['high'] - df_15m['low']).iloc[-6:-1]
    avg_candle_range = recent_ranges.mean() if len(recent_ranges) > 0 else 0
    current_range = c_high - c_low
    is_spike_candle = avg_candle_range > 0 and current_range > (avg_candle_range * 3.0)

    # ------------------ LONG ------------------
    long_h1_trend = c_close > h1_ema20
    long_breakout = (c_close > c_bb_upper) and (c_volume >= avg_volume * VOLUME_MULTIPLIER)
    long_pullback = (
        (c_close >= c_bb_middle) and
        (c_low <= c_bb_middle) and
        (c_close > c_open) and
        (c_volume <= avg_volume * PULLBACK_VOLUME_MULT) and
        (abs(c_close - c_open) <= (c_bb_upper - c_bb_lower) * 0.35)
    )

    # برای لانگ: فاصله تا سقف ماژور منفی نباشد (یعنی در آستانه گیر کردن زیر سقف نباشیم)
    distance_to_res = (major_resistance - c_close) / c_close
    safe_from_resistance = not (0 < distance_to_res < SR_SAFE_DISTANCE)

    if long_h1_trend and (long_breakout or long_pullback) and safe_from_resistance and not is_spike_candle:
        return "LONG", c_close

    # ------------------ SHORT ------------------
    short_h1_trend = c_close < h1_ema20
    short_breakout = (c_close < c_bb_lower) and (c_volume >= avg_volume * VOLUME_MULTIPLIER)
    short_pullback = (
        (c_close <= c_bb_middle) and
        (c_high >= c_bb_middle) and
        (c_close < c_open) and
        (c_volume <= avg_volume * PULLBACK_VOLUME_MULT) and
        (abs(c_close - c_open) <= (c_bb_upper - c_bb_lower) * 0.35)
    )

    distance_to_sup = (c_close - major_support) / c_close
    safe_from_support = not (0 < distance_to_sup < SR_SAFE_DISTANCE)

    if short_h1_trend and (short_breakout or short_pullback) and safe_from_support and not is_spike_candle:
        return "SHORT", c_close

    return None, c_close

def manage_open_positions(symbol, current_price):
    if symbol not in open_positions or current_price is None:
        return

    pos = open_positions[symbol]
    p_type = pos['type']
    entry = pos['entry']
    sl = pos['sl']
    tp1 = pos['tp1']

    if p_type == "LONG":
        if current_price <= sl:
            send_telegram_message(f"🚨 <b>حد ضرر خورد (LONG)</b>\nنماد: {symbol}\nقیمت خروج: {current_price:,.0f} تومان")
            del open_positions[symbol]
        elif current_price >= tp1 and not pos['tp1_hit']:
            send_telegram_message(f"🎯 <b>تارگت اول رسید (LONG)</b>\nنماد: {symbol}\nسیو سود کنید و استاپ را روی نقطه ورود بگذارید.")
            pos['tp1_hit'] = True
            pos['sl'] = entry

    elif p_type == "SHORT":
        if current_price >= sl:
            send_telegram_message(f"🚨 <b>حد ضرر خورد (SHORT)</b>\nنماد: {symbol}\nقیمت خروج: {current_price:,.0f} تومان")
            del open_positions[symbol]
        elif current_price <= tp1 and not pos['tp1_hit']:
            send_telegram_message(f"🎯 <b>تارگت اول رسید (SHORT)</b>\nنماد: {symbol}\nسیو سود کنید و استاپ را روی نقطه ورود بگذارید.")
            pos['tp1_hit'] = True
            pos['sl'] = entry

def bot_loop():
    send_telegram_message("🤖 <b>ربات هوشمند معامله‌گر فعال شد.</b>\nدر حال پایش بازار با فیلترهای پیشرفته...")

    while True:
        try:
            for symbol in ALL_SYMBOLS:
                signal, current_price = analyze_symbol(symbol)

                if current_price:
                    manage_open_positions(symbol, current_price)

                if signal and (symbol not in open_positions):
                    c_close = current_price
                    if signal == "LONG":
                        sl = c_close * (1 - SL_PERCENT)
                        tp1 = c_close * (1 + TP1_PERCENT)
                        tp2 = c_close * (1 + TP2_PERCENT)
                        is_margin = "بله (تعهدی)" if symbol in MARGIN_SYMBOLS else "خیر (فقط اسپات)"
                        msg = (
                            f"🟢 <b>سیگنال ورود: خرید (LONG)</b>\n\n"
                            f"🔹 <b>نماد:</b> {symbol}\n"
                            f"🔹 <b>قابلیت تعهدی:</b> {is_margin}\n"
                            f"💵 <b>نقطه ورود:</b> {c_close:,.0f} تومان\n"
                            f"🛑 <b>حد ضرر (SL):</b> {sl:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۱ (TP1):</b> {tp1:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۲ (TP2):</b> {tp2:,.0f} تومان\n\n"
                            f"💡 <i>تایم‌فریم ۱۵ دقیقه همگام با روند ۱ ساعته</i>"
                        )
                    else:
                        if symbol not in MARGIN_SYMBOLS:
                            time.sleep(SYMBOL_SLEEP)
                            continue

                        sl = c_close * (1 + SL_PERCENT)
                        tp1 = c_close * (1 - TP1_PERCENT)
                        tp2 = c_close * (1 - TP2_PERCENT)
                        msg = (
                            f"🔴 <b>سیگنال ورود: فروش (SHORT)</b>\n\n"
                            f"🔹 <b>نماد:</b> {symbol} (معامله تعهدی)\n"
                            f"💵 <b>نقطه ورود:</b> {c_close:,.0f} تومان\n"
                            f"🛑 <b>حد ضرر (SL):</b> {sl:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۱ (TP1):</b> {tp1:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۲ (TP2):</b> {tp2:,.0f} تومان\n\n"
                            f"💡 <i>تایم‌فریم ۱۵ دقیقه همگام با روند ۱ ساعته</i>"
                        )

                    open_positions[symbol] = {
                        'type': signal,
                        'entry': c_close,
                        'sl': sl,
                        'tp1': tp1,
                        'tp1_hit': False
                    }
                    send_telegram_message(msg)

                time.sleep(SYMBOL_SLEEP)

        except Exception as e:
            print(f"Loop Exception: {e}")

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()

    t_ping = threading.Thread(target=keep_alive_ping, daemon=True)
    t_ping.start()

    bot_loop()
