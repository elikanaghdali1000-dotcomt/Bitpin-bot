# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= تنظیمات اصلی و اطلاعات اختصاصی =================
# 👇 توکن بات تلگرام خود را داخل گیومه دوم بگذارید (مثل "123456789:ABCdefGhI...")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAG-Wfh8j9O5Q2BGXe3BZFJ3jdW8Ow8myVo")

# 👇 چت‌آیدی عددی تلگرام خود را داخل گیومه دوم بگذارید
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6643451227")

# آدرس وب‌سرویس شما در رندر
APP_URL = os.getenv("APP_URL", "https://bitpin-bot.onrender.com")

BASE_API = "https://api.bitpin.org/api"
OHLC_URL = f"{BASE_API}/v1/mkt/candles/"  # 👈 اصلاح شده مطابق مستندات بیت‌پین

BB_PERIOD = 20
BB_STD = 2.0

CHECK_INTERVAL = 60   # هر ۱ دقیقه چک می‌کند تا به بازه پایانی برسد
TIMEFRAME = "15"      # تایم‌فریم رسمی 15 دقیقه

# ----------------- لیست ۱۰۰ ارز مارجین / تعهدی -----------------
MARGIN_SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT",
    "ADA_USDT", "AVAX_USDT", "LINK_USDT", "SUI_USDT", "NEAR_USDT",
    "DOT_USDT", "TRX_USDT", "LTC_USDT", "BCH_USDT", "UNI_USDT",
    "APT_USDT", "ICP_USDT", "SHIB_USDT", "PEPE_USDT", "RENDER_USDT",
    "FET_USDT", "TAO_USDT", "FTM_USDT", "AAVE_USDT", "OP_USDT",
    "ARB_USDT", "INJ_USDT", "TIA_USDT", "SEI_USDT", "STX_USDT",
    "FIL_USDT", "ATOM_USDT", "RUNE_USDT", "GRT_USDT", "LDO_USDT",
    "KAS_USDT", "WIF_USDT", "BONK_USDT", "FLOKI_USDT", "GALA_USDT",
    "SAND_USDT", "MANA_USDT", "AXS_USDT", "THETA_USDT", "EOS_USDT",
    "FLOW_USDT", "DYDX_USDT", "CRV_USDT", "MKR_USDT", "SNX_USDT",
    "ALGO_USDT", "QNT_USDT", "XTZ_USDT", "IMX_USDT", "MINA_USDT",
    "CHZ_USDT", "ZIL_USDT", "ENJ_USDT", "1INCH_USDT", "COMP_USDT",
    "HOT_USDT", "JASMY_USDT", "WOO_USDT", "BLUR_USDT", "PENDLE_USDT",
    "ORDI_USDT", "SATS_USDT", "BEAM_USDT", "PYTH_USDT", "JUP_USDT",
    "WLD_USDT", "STRK_USDT", "ZK_USDT", "NOT_USDT", "TON_USDT",
    "OM_USDT", "CFX_USDT", "NEO_USDT", "IOTA_USDT", "KAVA_USDT",
    "KLAY_USDT", "ROSE_USDT", "MASK_USDT", "AGIX_USDT", "OCEAN_USDT",
    "CELO_USDT", "LRC_USDT", "ANKR_USDT", "AUDIO_USDT", "BAT_USDT",
    "BNT_USDT", "DGB_USDT", "GNO_USDT", "KNC_USDT", "ONT_USDT",
    "SKL_USDT", "SUSHI_USDT", "YFI_USDT", "ZRX_USDT", "VET_USDT"
]

# ----------------- لیست ۲۰ ارز اسپات منتخب -----------------
SPOT_ONLY_MARKETS = [
    "DOGS_USDT", "HMSTR_USDT", "CATI_USDT", "MAJOR_USDT", "MEME_USDT",
    "BOME_USDT", "POPCAT_USDT", "MEW_USDT", "BABYDOGE_USDT", "TURBO_USDT",
    "NEIRO_USDT", "EIGEN_USDT", "ENA_USDT", "ETHFI_USDT", "IO_USDT",
    "SAGA_USDT", "BB_USDT", "REZ_USDT", "NOT_USDT", "ZK_USDT"
]

# ترکیب و حذف موارد تکراری با حفظ وضعیت مارجین
ALL_WATCHLIST = []
for s in MARGIN_SYMBOLS:
    ALL_WATCHLIST.append({"symbol": s, "is_margin": True})

existing = set(MARGIN_SYMBOLS)
for s in SPOT_ONLY_MARKETS:
    if s not in existing:
        ALL_WATCHLIST.append({"symbol": s, "is_margin": False})

# ================= سرور داخلی برای زنده نگه داشتن Render =================
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bitpin Trading Bot is Running!")

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
            if APP_URL:
                requests.get(APP_URL, timeout=10)
        except Exception:
            pass

# ================= ارسال پیام به تلگرام =================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN == "توکن_بات_خودت_را_اینجا_بگذار":
        print("[Telegram] Token not set!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[Telegram Error] status: {r.status_code}, response: {r.text}")
        else:
            print("[Telegram] Message sent successfully.")
    except Exception as e:
        print(f"[Telegram Exception] {e}")

# ================= دریافت کندل‌ها از بیت‌پین (مطابق مستندات) =================
def fetch_bitpin_candles(market_code, resolution=TIMEFRAME, count=100):
    try:
        now_ts = int(time.time())
        res_minutes = int(resolution) if resolution.isdigit() else 15
        from_ts = now_ts - (count * res_minutes * 60 * 2)

        params = {
            "symbol": market_code,
            "res": resolution,  # 👈 پارامتر درست در مستندات بیت‌پین res است
            "from": from_ts,
            "to": now_ts
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(OHLC_URL, params=params, headers=headers, timeout=15)
        
        if r.status_code != 200:
            return None
            
        data = r.json()
        
        # ساختار خروجی اندپوينت candles معمولاً لیستی از کندل‌هاست
        if not data or not isinstance(data, list):
            # اگر به صورت دیکشنری یا فرمت خاصی بود
            if isinstance(data, dict) and "output" in data:
                data = data["output"]
            else:
                return None

        # تبدیل لیست دیکشنری‌های کندل به دیتافریم
        # فرمت خروجی استاندارد بیت‌پین برای candles: [ {time, open, high, low, close, volume}, ... ] یا آرایه‌های جداگانه
        timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
        
        for c in data:
            timestamps.append(int(c.get("time", c.get("t", 0))))
            opens.append(float(c.get("open", c.get("o", 0))))
            highs.append(float(c.get("high", c.get("h", 0))))
            lows.append(float(c.get("low", c.get("l", 0))))
            closes.append(float(c.get("close", c.get("c", 0))))
            volumes.append(float(c.get("volume", c.get("v", 0))))

        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })
        return df
    except Exception as e:
        print(f"Candle fetch error for {market_code}: {e}")
        return None

# ================= محاسبه اندیکاتورها =================
def calculate_indicators(df):
    if df is None or len(df) < 55:
        return None

    df["bb_middle"] = df["close"].rolling(window=BB_PERIOD).mean()
    df["bb_std"] = df["close"].rolling(window=BB_PERIOD).std()
    df["bb_upper"] = df["bb_middle"] + (BB_STD * df["bb_std"])
    df["bb_lower"] = df["bb_middle"] - (BB_STD * df["bb_std"])

    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["vol_ma20"] = df["volume"].rolling(window=20).mean()

    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=14).mean()

    return df

# ================= استراتژی سنسی =================
def check_sensi_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None

    sig_candle = df.iloc[-2]
    lookback_window = df.iloc[-27:-2]
    prior_support = lookback_window["low"].min()
    prior_resistance = lookback_window["high"].max()

    current_vol = sig_candle["volume"]
    vol_ma20 = sig_candle["vol_ma20"]

    if pd.isna(vol_ma20) or vol_ma20 == 0:
        return None

    vol_ratio = current_vol / vol_ma20
    is_volume_dried = vol_ratio < 0.70

    atr = sig_candle.get("atr", (sig_candle["high"] - sig_candle["low"]))
    if pd.isna(atr) or atr == 0:
        atr = sig_candle["close"] * 0.005

    near_support = (
        (sig_candle["low"] <= prior_support * 1.003) and 
        (sig_candle["low"] >= prior_support * 0.992)
    )
    is_bullish_reversal = (
        (sig_candle["close"] > sig_candle["open"]) or 
        (sig_candle["close"] > sig_candle["low"] + 0.6 * (sig_candle["high"] - sig_candle["low"]))
    )

    if near_support and is_volume_dried and is_bullish_reversal:
        entry = sig_candle["close"]
        sl = min(prior_support, sig_candle["low"]) - (0.2 * atr)
        risk = entry - sl
        if risk > 0:
            tp1 = entry + (1.5 * risk)
            tp2 = entry + (2.5 * risk)
            market_type_str = "تعهدی / فیوچرز" if is_margin else "اسپات (فقط خرید)"
            return (
                f"🎯 <b>سیگنال لانگ سنسی (خشکی حجم در کف ۲۵)</b>\n"
                f"▫️ ارز: <code>{market_code}</code> ({market_type_str})\n"
                f"▫️ تایم‌فریم: <b>15 دقیقه</b>\n"
                f"▫️ <b>قیمت ورود:</b> {entry:,.4f}\n"
                f"▫️ کف حمایتی گذشته: {prior_support:,.4f}\n"
                f"▫️ نسبت حجم فعلی به میانگین: <b>%{vol_ratio * 100:.1f}</b> (خشکیده)\n"
                f"🛡 <b>حد ضرر (SL):</b> {sl:,.4f}\n"
                f"🎯 <b>حد سود ۱ (1.5R):</b> {tp1:,.4f}\n"
                f"🎯 <b>حد سود ۲ (2.5R):</b> {tp2:,.4f}"
            )

    if is_margin:
        near_resistance = (
            (sig_candle["high"] >= prior_resistance * 0.997) and 
            (sig_candle["high"] <= prior_resistance * 1.008)
        )
        is_bearish_reversal = (
            (sig_candle["close"] < sig_candle["open"]) or 
            (sig_candle["close"] < sig_candle["high"] - 0.6 * (sig_candle["high"] - sig_candle["low"]))
        )

        if near_resistance and is_volume_dried and is_bearish_reversal:
            entry = sig_candle["close"]
            sl = max(prior_resistance, sig_candle["high"]) + (0.2 * atr)
            risk = sl - entry
            if risk > 0:
                tp1 = entry - (1.5 * risk)
                tp2 = entry - (2.5 * risk)
                return (
                    f"🔻 <b>سیگنال شورت سنسی (خشکی حجم در سقف ۲۵)</b>\n"
                    f"▫️ ارز: <code>{market_code}</code> (تعهدی / مارجین)\n"
                    f"▫️ تایم‌فریم: <b>15 دقیقه</b>\n"
                    f"▫️ <b>قیمت ورود:</b> {entry:,.4f}\n"
                    f"▫️ سقف مقاومتی گذشته: {prior_resistance:,.4f}\n"
                    f"▫️ نسبت حجم فعلی به میانگین: <b>%{vol_ratio * 100:.1f}</b> (خشکیده)\n"
                    f"🛡 <b>حد ضرر (SL):</b> {sl:,.4f}\n"
                    f"🎯 <b>حد سود ۱ (1.5R):</b> {tp1:,.4f}\n"
                    f"🎯 <b>حد سود ۲ (2.5R):</b> {tp2:,.4f}"
                )

    return None

# ================= استراتژی روند =================
def check_trend_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None

    last = df.iloc[-2]
    c = last["close"]
    lower = last["bb_lower"]
    upper = last["bb_upper"]
    ema = last["ema200"]
    rsi = last["rsi"]
    atr = last["atr"] if not pd.isna(last["atr"]) else (c * 0.01)

    if c <= lower and c > ema and rsi < 35:
        tp = c + (2 * atr)
        sl = c - (1.5 * atr)
        market_type_str = "تعهدی / فیوچرز" if is_margin else "اسپات"
        return (
            f"🟢 <b>سیگنال لانگ استراتژی روند (باند بولینگر)</b>\n"
            f"▫️ ارز: <code>{market_code}</code> ({market_type_str})\n"
            f"▫️ قیمت ورود: {c:,.4f}\n"
            f"▫️ مقدار RSI: {rsi:.1f}\n"
            f"🛡 حد ضرر (SL): {sl:,.4f}\n"
            f"🎯 حد سود (TP): {tp:,.4f}"
        )

    if is_margin and c >= upper and c < ema and rsi > 65:
        tp = c - (2 * atr)
        sl = c + (1.5 * atr)
        return (
            f"🔴 <b>سیگنال شورت استراتژی روند (باند بولینگر)</b>\n"
            f"▫️ ارز: <code>{market_code}</code> (تعهدی / مارجین)\n"
            f"▫️ قیمت ورود: {c:,.4f}\n"
            f"▫️ مقدار RSI: {rsi:.1f}\n"
            f"🛡 حد ضرر (SL): {sl:,.4f}\n"
            f"🎯 حد سود (TP): {tp:,.4f}"
        )

    return None

# ================= استراتژی پولبک =================
def check_pullback_strategy(df, market_code, is_margin=True):
    if len(df) < 55:
        return None

    sig_index = len(df) - 2
    sig_candle = df.iloc[sig_index]
    previous_candle = df.iloc[sig_index - 1]
    atr = sig_candle["atr"]

    if pd.isna(atr) or atr <= 0:
        return None

    for breakout_index in range(sig_index - 2, max(24, sig_index - 10), -1):
        prior_25 = df.iloc[breakout_index - 25:breakout_index]
        prior_20_volume = df.iloc[breakout_index - 20:breakout_index]["volume"].mean()
        breakout = df.iloc[breakout_index]
        pullback = df.iloc[breakout_index + 1:sig_index]

        if (
            len(prior_25) != 25
            or len(pullback) < 1
            or len(pullback) > 8
            or pd.isna(prior_20_volume)
            or prior_20_volume <= 0
            or breakout["volume"] <= 1.5 * prior_20_volume
            or pullback["volume"].mean() >= prior_20_volume
        ):
            continue

        ema_now = sig_candle["ema200"]
        ema_five_candles_ago = df.iloc[sig_index - 5]["ema200"]
        if pd.isna(ema_now) or pd.isna(ema_five_candles_ago):
            continue

        tolerance = 0.3 * atr
        resistance = prior_25["high"].max()

        if (
            breakout["close"] > resistance
            and sig_candle["close"] > ema_now > ema_five_candles_ago
            and ((pullback["low"] - resistance).abs() <= tolerance).any()
            and (pullback["close"] >= resistance - tolerance).all()
            and sig_candle["close"] > resistance
            and sig_candle["close"] > previous_candle["high"]
        ):
            entry = sig_candle["close"]
            sl = min(pullback["low"].min(), sig_candle["low"]) - (0.2 * atr)
            risk = entry - sl
            if risk > 0:
                tp = entry + (2 * risk)
                market_type_str = "تعهدی / فیوچرز" if is_margin else "اسپات (فقط خرید)"
                return (
                    f"📈 <b>سیگنال لانگ پولبک پس از شکست</b>\n"
                    f"▫️ ارز: <code>{market_code}</code> ({market_type_str})\n"
                    f"▫️ تایم‌فریم: <b>15 دقیقه</b>\n"
                    f"▫️ قیمت ورود: {entry:,.4f}\n"
                    f"▫️ سطح شکسته‌شده: {resistance:,.4f}\n"
                    f"🛡 حد ضرر (SL): {sl:,.4f}\n"
                    f"🎯 حد سود (2R): {tp:,.4f}"
                )

        support = prior_25["low"].min()
        if (
            is_margin
            and breakout["close"] < support
            and sig_candle["close"] < ema_now < ema_five_candles_ago
            and ((pullback["high"] - support).abs() <= tolerance).any()
            and (pullback["close"] <= support + tolerance).all()
            and sig_candle["close"] < support
            and sig_candle["close"] < previous_candle["low"]
        ):
            entry = sig_candle["close"]
            sl = max(pullback["high"].max(), sig_candle["high"]) + (0.2 * atr)
            risk = sl - entry
            if risk > 0:
                tp = entry - (2 * risk)
                return (
                    f"📉 <b>سیگنال شورت پولبک پس از شکست</b>\n"
                    f"▫️ ارز: <code>{market_code}</code> (تعهدی / مارجین)\n"
                    f"▫️ تایم‌فریم: <b>15 دقیقه</b>\n"
                    f"▫️ قیمت ورود: {entry:,.4f}\n"
                    f"▫️ سطح شکسته‌شده: {support:,.4f}\n"
                    f"🛡 حد ضرر (SL): {sl:,.4f}\n"
                    f"🎯 حد سود (2R): {tp:,.4f}"
                )

    return None

# ================= حلقه اصلی پایش و اسکن بازار =================
def run_scanner():
    print("Market scanner started successfully.")
    
    test_msg = (
        "🚀 <b>ربات اسکنر بیت‌پین روشن شد!</b>\n\n"
        "✅ اتصال به تلگرام برقرار است.\n"
        "🔗 آدرس API کندل‌ها مطابق مستندات به‌روز شد.\n"
        "⏱ تایم‌فریم: <b>15 دقیقه</b>\n"
        "📊 در حال رصد ۱۲۰ ارز..."
    )
    send_telegram(test_msg)

    last_scanned_candle_time = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            current_minute = now.minute
            candle_index = current_minute // 15
            target_start_minute = candle_index * 15 + 1

            if current_minute == target_start_minute:
                current_candle_id = f"{now.strftime('%Y-%m-%d-%H')}-{candle_index}"
                
                if last_scanned_candle_time != current_candle_id:
                    print(f"[{now.strftime('%H:%M:%S')}] Starting full market scan for 15m candle...")
                    
                    for item in ALL_WATCHLIST:
                        symbol = item["symbol"]
                        is_margin = item["is_margin"]

                        df = fetch_bitpin_candles(symbol, resolution=TIMEFRAME, count=100)
                        if df is None:
                            continue

                        df = calculate_indicators(df)
                        if df is None:
                            continue

                        sensi_msg = check_sensi_strategy(df, symbol, is_margin=is_margin)
                        if sensi_msg:
                            send_telegram(sensi_msg)
                            time.sleep(1)
                            continue

                        trend_msg = check_trend_strategy(df, symbol, is_margin=is_margin)
                        if trend_msg:
                            send_telegram(trend_msg)
                            time.sleep(1)

                        if not trend_msg:
                            pullback_msg = check_pullback_strategy(df, symbol, is_margin=is_margin)
                            if pullback_msg:
                                send_telegram(pullback_msg)
                                time.sleep(1)

                        time.sleep(0.4)

                    last_scanned_candle_time = current_candle_id
                    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Scan finished.")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(10)

# ================= نقطه اجرای برنامه =================
if __name__ == "__main__":
    server_thread = threading.Thread(target=run_http_server, daemon=True)
    server_thread.start()

    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()

    run_scanner()
