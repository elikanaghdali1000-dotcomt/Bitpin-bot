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

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
TELEGRAM_BOT_TOKEN = "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo"
TELEGRAM_CHAT_ID = "6643451227"
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

API_URL = "https://api.bitpin.ir/v1/mkt/markets/"
OHLC_URL = "https://api.bitpin.ir/v1/mkt/tv/history/"

BB_PERIOD = 20
BB_STD = 2.0

# حد سود و ضرر مخصوص پولبک
PULLBACK_SL_PERCENT = 0.012
PULLBACK_TP1_PERCENT = 0.015
PULLBACK_TP2_PERCENT = 0.025

# حد سود و ضرر مخصوص شکست بولینگر
BREAKOUT_SL_PERCENT = 0.016
BREAKOUT_TP1_PERCENT = 0.020
BREAKOUT_TP2_PERCENT = 0.035

MIN_BANDWIDTH = 0.01
VOLUME_MULTIPLIER = 1.25
PULLBACK_ZONE_FRACTION = 0.25

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

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*'
})

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
                session.get(APP_URL, timeout=10)
        except Exception:
            pass

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        session.post(url, json=payload, timeout=8)
    except Exception as e:
        print(f"Telegram Error: {e}", flush=True)

def safe_get_json(url, params=None, retries=3):
    for i in range(retries):
        try:
            res = session.get(url, params=params, timeout=10, verify=False)
            if res.status_code == 200:
                return res.json()
        except requests.exceptions.RequestException:
            time.sleep(1)
    return None

def get_ohlcv(symbol, resolution, count=100):
    to_time = int(time.time())
    res_minutes = int(resolution)
    # بازه زمانی وسیع‌تر و امن برای جلوگیری از خطای دیتای خالی
    from_time = to_time - (count * res_minutes * 60 * 3)

    params = {
        'symbol': symbol,
        'resolution': resolution,
        'from': from_time,
        'to': to_time
    }

    data = safe_get_json(OHLC_URL, params=params)

    if not data or data.get('s') != 'ok' or not data.get('t') or len(data['t']) == 0:
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

def get_btc_trend():
    df_btc = get_ohlcv("BTC_IRT", TIMEFRAME_1H, count=40)
    log_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # گرفتن قیمت لحظه‌ای تیکر برای اطمینان از نمایش قیمت در هر شرایطی
    fallback_data = safe_get_json(API_URL)
    btc_live_price = 0
    if fallback_data and isinstance(fallback_data, dict):
        for item in fallback_data.get('results', []):
            if item.get('code') == 'BTC_IRT':
                btc_live_price = float(item.get('price', 0))
                break

    if df_btc is None or len(df_btc) < 25:
        price_display = f"{btc_live_price:,.0f} تومان" if btc_live_price > 0 else "در حال دریافت..."
        print(f"[{log_time} UTC] BTC_IRT: {price_display} | وضعیت کندل: در حال همگام‌سازی | روند: NEUTRAL", flush=True)
        return "NEUTRAL"

    ema20 = df_btc['close'].ewm(span=20, adjust=False).mean().iloc[-2]
    btc_close = df_btc['close'].iloc[-2]
    btc_current_price = btc_live_price if btc_live_price > 0 else df_btc['close'].iloc[-1]

    if btc_close > ema20:
        trend = "BULLISH"
    elif btc_close < ema20:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    print(f"[{log_time} UTC] BTC_IRT Price: {btc_current_price:,.0f} تومان | Trend: {trend}", flush=True)
    return trend

def analyze_symbol(symbol, btc_trend):
    df_15m = get_ohlcv(symbol, TIMEFRAME_15M, count=50)

    if df_15m is None or len(df_15m) < BB_PERIOD + 3:
        return None, None

    signal_idx = -2
    current_price = df_15m['close'].iloc[-1]

    df_15m['bb_middle'] = df_15m['close'].rolling(window=BB_PERIOD).mean()
    df_15m['bb_std'] = df_15m['close'].rolling(window=BB_PERIOD).std()
    df_15m['bb_upper'] = df_15m['bb_middle'] + (df_15m['bb_std'] * BB_STD)
    df_15m['bb_lower'] = df_15m['bb_middle'] - (df_15m['bb_std'] * BB_STD)
    df_15m['volume_sma'] = df_15m['volume'].rolling(window=BB_PERIOD).mean()

    c_bandwidth = (df_15m['bb_upper'].iloc[signal_idx] - df_15m['bb_lower'].iloc[signal_idx]) / df_15m['bb_middle'].iloc[signal_idx]

    if pd.isna(c_bandwidth) or c_bandwidth < MIN_BANDWIDTH:
        return None, current_price

    df_1h = get_ohlcv(symbol, TIMEFRAME_1H, count=70)

    if df_1h is None or len(df_1h) < MAJOR_SR_BARS + 2:
        return None, current_price

    df_1h['ema20'] = df_1h['close'].ewm(span=20, adjust=False).mean()
    h1_ema20 = df_1h['ema20'].iloc[-2]

    c_close = df_15m['close'].iloc[signal_idx]
    c_open = df_15m['open'].iloc[signal_idx]
    c_high = df_15m['high'].iloc[signal_idx]
    c_low = df_15m['low'].iloc[signal_idx]
    c_volume = df_15m['volume'].iloc[signal_idx]
    avg_volume = df_15m['volume_sma'].iloc[signal_idx]
    c_bb_upper = df_15m['bb_upper'].iloc[signal_idx]
    c_bb_lower = df_15m['bb_lower'].iloc[signal_idx]
    c_bb_middle = df_15m['bb_middle'].iloc[signal_idx]

    if any(pd.isna(v) for v in [avg_volume, c_bb_upper, c_bb_lower, c_bb_middle]):
        return None, current_price

    past_h1 = df_1h.iloc[-(MAJOR_SR_BARS + 1):-1]
    major_resistance = past_h1['high'].max()
    major_support = past_h1['low'].min()

    recent_ranges = (df_15m['high'] - df_15m['low']).iloc[-7:-2]
    avg_candle_range = recent_ranges.mean() if len(recent_ranges) > 0 else 0
    current_range = c_high - c_low
    is_spike_candle = avg_candle_range > 0 and current_range > (avg_candle_range * 3.5)

    # ------------------ سناریوی صعودی (LONG) ------------------
    long_h1_trend = c_close > h1_ema20
    long_breakout = (c_close > c_bb_upper) and (c_volume >= avg_volume * VOLUME_MULTIPLIER)

    long_zone_lower = c_bb_middle - (c_bb_middle - c_bb_lower) * PULLBACK_ZONE_FRACTION
    long_zone_upper = c_bb_middle + (c_bb_upper - c_bb_middle) * PULLBACK_ZONE_FRACTION

    long_pullback = (
        (long_zone_lower <= c_low <= long_zone_upper)
        and (long_zone_lower <= c_close <= long_zone_upper)
        and (c_close > c_bb_middle)
        and (c_close > c_open)
    )

    distance_to_res = (major_resistance - c_close) / c_close
    safe_from_resistance = not (0 < distance_to_res < SR_SAFE_DISTANCE)

    btc_permits_long = (btc_trend != "BEARISH") or (symbol == "BTC_IRT")

    if (btc_permits_long and long_h1_trend and (long_breakout or long_pullback)
            and safe_from_resistance and not is_spike_candle):
        entry_type = "شکست بولینگر (Breakout)" if long_breakout else "پولبک ناحیه میانی (Pullback Zone)"
        return ("LONG", entry_type), current_price

    # ------------------ سناریوی نزولی (SHORT) ------------------
    short_h1_trend = c_close < h1_ema20
    short_breakout = (c_close < c_bb_lower) and (c_volume >= avg_volume * VOLUME_MULTIPLIER)

    short_zone_lower = c_bb_middle - (c_bb_middle - c_bb_lower) * PULLBACK_ZONE_FRACTION
    short_zone_upper = c_bb_middle + (c_bb_upper - c_bb_middle) * PULLBACK_ZONE_FRACTION

    short_pullback = (
        (short_zone_lower <= c_high <= short_zone_upper)
        and (short_zone_lower <= c_close <= short_zone_upper)
        and (c_close < c_bb_middle)
        and (c_close < c_open)
    )

    distance_to_sup = (c_close - major_support) / c_close
    safe_from_support = not (0 < distance_to_sup < SR_SAFE_DISTANCE)

    btc_permits_short = (btc_trend != "BULLISH") or (symbol == "BTC_IRT")

    if (btc_permits_short and short_h1_trend and (short_breakout or short_pullback)
            and safe_from_support and not is_spike_candle):
        entry_type = "شکست بولینگر (Breakout)" if short_breakout else "پولبک ناحیه میانی (Pullback Zone)"
        return ("SHORT", entry_type), current_price

    return None, current_price

def manage_open_positions(symbol, current_price):
    if symbol not in open_positions or current_price is None:
        return

    pos = open_positions[symbol]
    p_type = pos['type']
    entry = pos['entry']
    sl = pos['sl']
    tp1 = pos['tp1']
    tp2 = pos.get('tp2')

    if p_type == "LONG":
        if current_price <= sl:
            send_telegram_message(
                f"🚨 <b>حد ضرر خورد (LONG)</b>\n"
                f"نماد: {symbol}\n"
                f"قیمت خروج: {current_price:,.0f} تومان"
            )
            del open_positions[symbol]
        elif tp2 and current_price >= tp2:
            send_telegram_message(
                f"✅ <b>تارگت دوم رسید (LONG)</b>\n"
                f"نماد: {symbol}\n"
                f"قیمت خروج: {current_price:,.0f} تومان"
            )
            del open_positions[symbol]
        elif current_price >= tp1 and not pos['tp1_hit']:
            send_telegram_message(
                f"🎯 <b>تارگت اول رسید (LONG)</b>\n"
                f"نماد: {symbol}\n"
                f"سیو سود کنید و استاپ را روی نقطه ورود بگذارید."
            )
            pos['tp1_hit'] = True
            pos['sl'] = entry

    elif p_type == "SHORT":
        if current_price >= sl:
            send_telegram_message(
                f"🚨 <b>حد ضرر خورد (SHORT)</b>\n"
                f"نماد: {symbol}\n"
                f"قیمت خروج: {current_price:,.0f} تومان"
            )
            del open_positions[symbol]
        elif tp2 and current_price <= tp2:
            send_telegram_message(
                f"✅ <b>تارگت دوم رسید (SHORT)</b>\n"
                f"نماد: {symbol}\n"
                f"قیمت خروج: {current_price:,.0f} تومان"
            )
            del open_positions[symbol]
        elif current_price <= tp1 and not pos['tp1_hit']:
            send_telegram_message(
                f"🎯 <b>تارگت اول رسید (SHORT)</b>\n"
                f"نماد: {symbol}\n"
                f"سیو سود کنید و استاپ را روی نقطه ورود بگذارید."
            )
            pos['tp1_hit'] = True
            pos['sl'] = entry

def bot_loop():
    send_telegram_message(
        "🤖 <b>ربات هوشمند معامله‌گر فعال شد.</b>\n"
        "در حال پایش بازار با فیلتر پولبک و لیدر بیت‌کوین..."
    )

    while True:
        try:
            btc_trend = get_btc_trend()

            for symbol in ALL_SYMBOLS:
                sig_res, current_price = analyze_symbol(symbol, btc_trend)

                if current_price:
                    manage_open_positions(symbol, current_price)

                if sig_res and (symbol not in open_positions):
                    signal, setup_name = sig_res
                    c_close = current_price

                    if "Breakout" in setup_name:
                        sl_percent = BREAKOUT_SL_PERCENT
                        tp1_percent = BREAKOUT_TP1_PERCENT
                        tp2_percent = BREAKOUT_TP2_PERCENT
                    else:
                        sl_percent = PULLBACK_SL_PERCENT
                        tp1_percent = PULLBACK_TP1_PERCENT
                        tp2_percent = PULLBACK_TP2_PERCENT

                    if signal == "LONG":
                        sl = c_close * (1 - sl_percent)
                        tp1 = c_close * (1 + tp1_percent)
                        tp2 = c_close * (1 + tp2_percent)
                        is_margin = "بله (تعهدی)" if symbol in MARGIN_SYMBOLS else "خیر (فقط اسپات)"
                        msg = (
                            f"🟢 <b>سیگنال ورود: خرید (LONG)</b>\n\n"
                            f"🔹 <b>نماد:</b> {symbol}\n"
                            f"📌 <b>الگو:</b> {setup_name}\n"
                            f"🔹 <b>قابلیت تعهدی:</b> {is_margin}\n"
                            f"💵 <b>نقطه ورود:</b> {c_close:,.0f} تومان\n"
                            f"🛑 <b>حد ضرر (SL):</b> {sl:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۱ (TP1):</b> {tp1:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۲ (TP2):</b> {tp2:,.0f} تومان\n\n"
                            f"💡 <i>تأیید هم‌راستایی با روند ۱ ساعته و بیت‌کوین</i>"
                        )
                    else:
                        if symbol not in MARGIN_SYMBOLS:
                            time.sleep(SYMBOL_SLEEP)
                            continue

                        sl = c_close * (1 + sl_percent)
                        tp1 = c_close * (1 - tp1_percent)
                        tp2 = c_close * (1 - tp2_percent)
                        msg = (
                            f"🔴 <b>سیگنال ورود: فروش (SHORT)</b>\n\n"
                            f"🔹 <b>نماد:</b> {symbol} (معامله تعهدی)\n"
                            f"📌 <b>الگو:</b> {setup_name}\n"
                            f"💵 <b>نقطه ورود:</b> {c_close:,.0f} تومان\n"
                            f"🛑 <b>حد ضرر (SL):</b> {sl:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۱ (TP1):</b> {tp1:,.0f} تومان\n"
                            f"🎯 <b>تارگت ۲ (TP2):</b> {tp2:,.0f} تومان\n\n"
                            f"💡 <i>تأیید هم‌راستایی با روند ۱ ساعته و بیت‌کوین</i>"
                        )

                    open_positions[symbol] = {
                        'type': signal,
                        'entry': c_close,
                        'sl': sl,
                        'tp1': tp1,
                        'tp2': tp2,
                        'tp1_hit': False
                    }
                    send_telegram_message(msg)

                time.sleep(SYMBOL_SLEEP)

        except Exception as e:
            print(f"Loop Exception: {e}", flush=True)

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()

    t_ping = threading.Thread(target=keep_alive_ping, daemon=True)
    t_ping.start()

    bot_loop()
