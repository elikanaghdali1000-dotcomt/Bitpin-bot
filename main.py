import os
import time
import requests
import pandas as pd
import numpy as np
from flask import Flask
from threading import Thread

# --- Flask Web Server برای بیدار نگه داشتن ربات در Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bitpin Leveraged Trading Bot is Running! /ok", 200

@app.route('/ok')
def ok_check():
    return "OK", 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --- تنظیمات و لیست جفت ارزهای اهرم‌دار بیت‌پین ---
LEVERAGED_PAIRS = [
    "BTC_USDT", "XRP_USDT", "PAXG_USDT", "SOL_USDT", "BNB_USDT", "GRAM_USDT", 
    "RENDER_USDT", "PENGU_USDT", "NVDAX_USDT", "PUMP_USDT", "DASH_USDT", "GALA_USDT", 
    "LDO_USDT", "ARB_USDT", "WIF_USDT", "ONDO_USDT", "ENA_USDT", "UNI_USDT", 
    "FIL_USDT", "S_USDT", "CAKE_USDT", "AVAX_USDT", "ALGO_USDT", "DOT_USDT", 
    "NEAR_USDT", "SUI_USDT", "HYPE_USDT", "SLVON_USDT", "XLM_USDT", "TRX_USDT", 
    "ETH_USDT", "ZEC_USDT", "LINK_USDT", "ASTER_USDT", "LTC_USDT", "DOGE_USDT", 
    "ADA_USDT", "XAUT_USDT"
]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram Alert]: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")


def fetch_bitpin_klines(symbol, resolution="15", limit=100):
    url = f"https://api.bitpin.org/v1/mkt/tv/history?symbol={symbol}&resolution={resolution}&count={limit}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "t" in data and len(data["t"]) > 0:
                df = pd.DataFrame({
                    'timestamp': data['t'],
                    'open': data['o'],
                    'high': data['h'],
                    'low': data['l'],
                    'close': data['c'],
                    'volume': data['v']
                })
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
    return None


def calculate_indicators(df):
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    
    # محاسبه دهانه بولینگر (Bollinger Band Width) درصدی
    df['bb_width'] = (df['upper_band'] - df['lower_band']) / df['sma20'] * 100
    
    # میانگین حجم ۲۰ دوره
    df['volume_sma20'] = df['volume'].rolling(window=20).mean()
    return df


def check_btc_trend():
    btc_df = fetch_bitpin_klines("BTC_USDT", resolution="15", limit=5)
    if btc_df is not None and len(btc_df) >= 2:
        last_close = btc_df['close'].iloc[-1]
        prev_close = btc_df['close'].iloc[-2]
        pct_change = (last_close - prev_close) / prev_close * 100
        return pct_change
    return 0.0


def trading_bot_logic():
    print("Bitpin Leveraged Trading Bot Loop Started...")
    while True:
        try:
            current_time = time.time()
            # محاسبه زمان درون کندل ۱۵ دقیقه‌ای
            sec_into_candle = int(current_time) % 900
            
            # بررسی وضعیت بیت‌کوین به عنوان لیدر بازار
            btc_change = check_btc_trend()

            for symbol in LEVERAGED_PAIRS:
                df = fetch_bitpin_klines(symbol, resolution="15", limit=50)
                if df is None or len(df) < 25:
                    continue
                
                df = calculate_indicators(df)
                
                last_row = df.iloc[-2]  # آخرین کندل بسته شده یا در حال بسته شدن
                bb_width = last_row['bb_width']
                
                # شرط سفت و سخت: دهانه بولینگر نباید زیر ۱٪ باشد
                if bb_width < 1.0:
                    continue

                close_price = last_row['close']
                upper = last_row['upper_band']
                lower = last_row['lower_band']
                volume = last_row['volume']
                vol_sma = last_row['volume_sma20']

                # 1) استراتژی سنسی (Sensi): بررسی در ۲ دقیقه پایانی کندل (دقیقه ۱۳ و ۱۴)
                # زمان بین 780 تا 900 ثانیه از شروع کندل 15 دقیقه‌ای
                if 780 <= sec_into_candle < 900:
                    # شرط حجم بی‌رمق نبودن و دوری از چسبیدن مطلق به باند
                    if volume > vol_sma * 0.8:
                        if close_price >= upper * 0.995 and close_price < upper:
                            if btc_change >= -0.5:  # بیت‌کوین نزولی بحرانی نباشد
                                send_telegram_alert(f"🚨 *Sensi LONG Signal*\nSymbol: `{symbol}`\nPrice: `{close_price}`")
                        elif close_price <= lower * 1.005 and close_price > lower:
                            send_telegram_alert(f"🚨 *Sensi SHORT Signal*\nSymbol: `{symbol}`\nPrice: `{close_price}`")

                # 2) استراتژی‌های پولبک و برک‌تست (Pullback & Break & Retest): بررسی در پایان کندل (ثانیه‌های اولیه کندل جدید)
                if sec_into_candle < 30:
                    # شرط حجم قوی (> 1.3 برابر میانگین)
                    if volume > vol_sma * 1.3:
                        # مثال شرط برک‌تست صعودی / پولبک
                        if close_price > upper:
                            if btc_change >= -0.5:
                                send_telegram_alert(f"🚀 *Break & Retest / Pullback LONG*\nSymbol: `{symbol}`\nPrice: `{close_price}`")
                        elif close_price < lower:
                            send_telegram_alert(f"🔻 *Break & Retest / Pullback SHORT*\nSymbol: `{symbol}`\nPrice: `{close_price}`")

            time.sleep(15)  # استراحت کوتاه بین هر اسکن
        except Exception as e:
            print(f"Error in bot loop: {e}")
            time.sleep(10)


if __name__ == "__main__":
    # اجرای سرور Flask در یک ترد جداگانه برای رندر
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # اجرای حلقه اصلی ربات
    trading_bot_logic()
