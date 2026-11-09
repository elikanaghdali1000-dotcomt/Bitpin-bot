#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=======================================================================
 ربات سیگنال بیت‌پین — استراتژی «شکست کانال دانچیان ۵۵» روی تایم‌فریم ۴ ساعته
=======================================================================
این ربات همان استراتژی‌ای است که در بک‌تست (۲۰۲۳-۰۴ تا ۲۰۲۶-۱۱، ۳۵ نماد)
اعتبارسنجی شد و نتیجه داد:

    • ورود (LONG فقط):  close > بالاترین سقف ۵۵ کندل اخیر (shift شده)
    • فیلترها:          حجم ≥ 1.2 برابر میانگین ۲۰ کندل
                        ADX ≥ 18  (بازار رِنج نباشد)
                        EMA50 > EMA200  (روند بزرگ صعودی)
    • حد ضرر:           2.5 × ATR(14) زیر ورود
    • حد سود:           8.0 × ATR(14) بالای ورود   (R:R ≈ 3.2)
    • تریلینگ:          ندارد (تریلینگ در تست نتیجه را خراب کرد)
    • خروج زمانی:       ۴۸ کندل ۴ساعته ≈ ۸ روز
    • شورت:             ندارد (شورت در تست ضررده بود)
    • سیگنال فقط روی کندلِ بسته‌شده؛ ورود «مارکت» در بازشدن کندل بعد
    • فیلتر «تازگی شکست» ندارد: بک‌تست نشان داد حذف ورودهای مجدد در یک روند،
      سود را از ۵۴۸٪ به ۱۵۷٪ کاهش می‌دهد. برگشت به روند بعد از استاپ، خودش سیگنال است.

نتیجه بک‌تست روی «لیست سفید ۱۵ نمادی» (داده بومی ۴ساعته بیت‌پین،
۲۰۲۳-۰۴-۱۵ تا ۲۰۲۶-۱۱، با کارمزد ۰.۲٪ و اسلیپیج ۰.۱۵٪):
    ۳۳۱ معامله | وین‌ریت ۴۲.۰٪ | PF 1.63 | میانگین +0.31R | مجموع +101.9R
    پورتفوی با ریسک ۱٪ در هر معامله: ۲.۶۴ برابر در ۳.۵ سال، حداکثر افت ۲۹٪
    پورتفوی با ریسک ۰.۵٪:           ۱.۶۴ برابر، حداکثر افت ۱۶٪

    تقسیم سالانه (ریسک ۱٪):  ۲۰۲۳ +۱۲٪ | ۲۰۲۴ +۱۰۶٪ | ۲۰۲۵ −۵٪ | ۲۰۲۶ +۲۱٪
    ⚠️ سال ۲۰۲۵ منفی بود؛ این استراتژی سالِ بد هم دارد.

    برای مقایسه: اگر هر ۳۶ نماد را معامله کنید PF به 1.16 سقوط می‌کند.
    سود از «چند ترید بزرگ» می‌آید نه از دقت بالا (۵٪ برتر معاملات ≈ ۱۸٪ سود).
    پس: بدون مدیریت سرمایه و بدون پایبندی به حد ضرر، این استراتژی ضررده می‌شود.

⚠️ این ربات «سیگنال‌ده» است، نه معامله‌گر خودکار. هیچ سفارشی روی صرافی نمی‌گذارد.
⚠️ خروجی این برنامه توصیه سرمایه‌گذاری نیست. مسئولیت هر معامله با خود شماست.

اجرا:
    export TELEGRAM_BOT_TOKEN="123:ABC"
    export TELEGRAM_CHAT_ID="123456789"
    python3 bitpin_donchian_bot.py

متغیرهای محیطی مهم:
    DRY_RUN=1               حالت آزمایشی (پیش‌فرض ۱): سیگنال‌ها فقط لاگ می‌شوند
    TIMEFRAME=4h            تایم‌فریم (۴h پیشنهادی؛ 1h هم پشتیبانی می‌شود)
    SYMBOLS="SOL_USDT,..."  لیست سفارشی نمادها
    EQUITY_USDT=1000        سرمایه فرضی برای محاسبه حجم
    RISK_PCT=1.0            درصد ریسک هر معامله
    PORT=10000              پورت health-check (برای Render/Railway)

-----------------------------------------------------------------------
 اصلاحات نسخه ۱.۱.۰ — «چهار اصلاح مسیر خروج»
-----------------------------------------------------------------------
۱) کندل در حال تشکیل دیگر دور ریخته نمی‌شود: High/Low همان کندل هم به عنوان
   تریگر داخل‌کندلی تست می‌شود (قبلاً فقط کندل‌های بسته‌شده بررسی می‌شدند و
   یک لمس SL/TP تا ۴ ساعت دیده نمی‌شد).
۲) قیمت کهنه دیگر «تازه» جا زده نمی‌شود: get_prices سن کش را برمی‌گرداند و
   اگر سن از PRICE_MAX_AGE بیشتر باشد، ورود جدید و خروج با قیمت لحظه‌ای
   ممنوع می‌شود (فقط کندل‌ها معتبرند) و یک هشدار تلگرامی می‌رود.
۳) پر شدن گپ‌آگاه: اگر کندل زیر SL باز شده باشد، خروج روی همان بازشدن
   ثبت می‌شود نه روی SL (R واقعی می‌تواند بدتر از −۱ باشد و همان گزارش می‌شود).
۴) بررسی قیمت بین کندل‌ها فقط یک «نمونهٔ نقطه‌ای» نبود؛ حالا از کندل ناقص
   هم استفاده می‌کند (PARTIAL_ON_POLL=1) تا هر عبوری از SL/TP در بازهٔ
   ۵ دقیقه‌ای گرفته شود، نه فقط لحظهٔ نمونه‌برداری.

   توجه: کندل ناقص در چرخهٔ اصلی (۶۰ ثانیه بعد از بسته‌شدن کندل) فقط ~۶۰
   ثانیه از کندل تازه را پوشش می‌دهد؛ برد واقعی «داخل‌کندلی» از
   price_only_check می‌آید که هر PRICE_POLL ثانیه اجرا می‌شود.

-----------------------------------------------------------------------
 اصلاحات نسخه ۱.۲.۰ — «فیلتر حجم سه‌لایه + مسیر درست دفتر سفارش»
-----------------------------------------------------------------------
۱) فیلتر حجم از یک شرط ساده (vol ≥ ۱.۲× میانگین) به سه لایهٔ مستقل تبدیل شد:
   • لایهٔ ۱ — کف نقدشوندگی: میانهٔ گردش مالی هر کندل (Close×Volume به دلار)
     در ۳۰ روز باید ≥ MIN_TURNOVER_USDT باشد. ارزهای مرده حذف می‌شوند.
     ⚠️ با کف پیش‌فرض ۲۰۰۰ دلار، چهار نماد لیست سفید زیر آستانه می‌افتند و
     عملاً معامله نمی‌شوند: ALGO, CRV, GALA, VET. اگر می‌خواهید این‌ها هم
     باشند، MIN_TURNOVER_USDT را پایین بیاورید — ولی بدانید که گردش مالی کم
     یعنی اسلیپیج واقعی بالا؛ کف را با اندازهٔ پوزیشن خودتان تنظیم کنید.
   • لایهٔ ۲ — تأیید بریک‌اوت: حجم کندل ≥ ۱.۲× میانگین ۲۰ کندل، حجم کندل
     قبل ≥ ۱.۰× میانگین (پایداری حجم) و بدنهٔ کندل ≥ ۶۰٪ دامنه.
     بک‌تست: n=160 و PF 2.17؛ با کف ۲۰۰۰$ → n=95 و PF 2.38.
   • لایهٔ ۳ — دفتر سفارش زنده: اسپرد ≤ ۰.۶٪ و عمق ≥ ۱.۵× حجم سفارش.
۲) کیفیت دادهٔ حجمی چک می‌شود: سهم کندل‌های بی‌حجم (>۵٪) و حجم‌های تکراری
   «یخ‌زده» (>۱۰٪) → سیگنال رد می‌شود. دادهٔ حجمی بیت‌پین روی نمادهای کوچک
   نویزی است و بدون این چک، فیلتر حجم روی دادهٔ آشغال تصمیم می‌گیرد.
۳) مسیر دفتر سفارش اصلاح شد: نسخهٔ ۲.۰.۰ از /api/v1/mkt/depth/ استفاده
   می‌کرد که ۴۰۴ می‌داد، پس گیت همیشه fail-open و بی‌اثر بود. مسیر درست
   /api/v1/mth/orderbook/{symbol}/ است (با پاسخ ۲۰۰ تایید شد).
۴) گیت دفتر سفارش در خطای شبکه «رد نمی‌کند» (fail-open)؛ فقط اندازه‌گیری
   واقعی اسپرد/عمق می‌تواند سیگنال را رد کند — و در آن حالت تا کندل بعد
   دوباره تلاش نمی‌شود (ضد اسپم).
=======================================================================
"""

import os
import sys
import json
import time
import math
import signal
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pandas as pd
import requests

# =====================================================================
# ۱) تنظیمات
# =====================================================================
VERSION = "1.3.0"

def _env_bool(name, default=False):
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")

def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default

def _env_int(name, default):
    try:
        return int(float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default

DRY_RUN          = _env_bool("DRY_RUN", True)
TIMEFRAME        = os.getenv("TIMEFRAME", "4h").strip().lower()
PERIOD           = 14400 if TIMEFRAME == "4h" else 3600
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8947033412:AAEPvb8CEn5I_9Bxe8oqPuGD1gNjfY5TrUA").strip()
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "6643451227").strip()
TG_IN_DRY_RUN    = _env_bool("TG_IN_DRY_RUN", True)   # در حالت تست هم پیام بفرست؟

EQUITY_USDT      = _env_float("EQUITY_USDT", 1000.0)
RISK_PCT         = _env_float("RISK_PCT", 1.0)
MAX_NOTIONAL_MULT = _env_float("MAX_NOTIONAL_MULT", 5.0)  # سقف حجم = ۵ برابر سرمایه

# --- پارامترهای استراتژی (دست نزنید مگر با بک‌تست مجدد) ---
DC_LEN       = 55      # طول کانال دانچیان
VOL_MULT     = 1.2     # حداقل نسبت حجم
ADX_MIN      = 18.0    # حداقل ADX
ATR_LEN      = 14
SL_ATR       = 2.5     # حد ضرر = ۲.۵ ATR
TP_ATR       = 8.0     # حد سود  = ۸ ATR
MAX_HOLD     = 48      # حداکثر نگهداری (کندل)
WARMUP       = 260     # کندل لازم برای گرم شدن اندیکاتورها (EMA200 + حاشیه)
MIN_RISK_PCT = 0.25    # اگر فاصله SL کمتر از این درصد باشد، سیگنال رد می‌شود
MAX_RISK_PCT = 15.0    # اگر فاصله SL بیشتر از این درصد باشد (ATR غیرعادی)، سیگنال رد می‌شود

# --- ۱.۳.۰: حالت خروج ---
# fixed   = حد سود ۸ ATR (رفتار ۱.۲.۰)
# donch20 = بدون TP؛ خروج مارکت وقتی کندل *بسته‌شده* زیر کف ۲۰ کندل بسته شود
#           (SL ثابت ۲.۵ ATR سر جایش می‌ماند و ترییل نمی‌شود؛ تایم‌اوت ۴۸ کندل هم فعال است)
EXIT_MODE   = os.getenv("EXIT_MODE", "donch20").strip().lower()
DC_EXIT_LEN = _env_int("DC_EXIT_LEN", 20)     # طول کف خروج (فقط در donch20)

# --- ۱.۳.۰: فیلتر رژیم BTC (فقط برای ورود، fail-open) ---
# اگر BTC زیر EMA200 بسته شود، ورود جدید در هیچ نمادی باز نمی‌شود.
# fail-open: اگر دادهٔ BTC نیاید یا EMA نامعتبر باشد، فیلتر باز است (سیگنال بلاک نمی‌شود).
BTC_FILTER_ON = _env_bool("BTC_FILTER_ON", True)
BTC_EMA_LEN   = _env_int("BTC_EMA_LEN", 200)
BTC_SYMBOL    = "BTC_USDT"          # فقط برای رژیم؛ هرگز معامله نمی‌شود
BTC_CACHE_SEC = _env_int("BTC_CACHE_SEC", 240)   # کش رژیم (کاهش درخواست HTTP)

# --- اصلاح ۱.۲.۰: فیلتر حجم سه‌لایه (از ماژول volume_filter) ---
# لایهٔ ۱ (کف نقدشوندگی): میانهٔ گردش مالی هر کندل (Close×Volume به دلار) در ۳۰ روز.
#   ⚠️ با کف ۲۰۰۰ دلاری، چهار نماد لیست سفید حذف می‌شوند: ALGO, CRV, GALA, VET.
#   بک‌تست: n=160 با PF 2.17 → با کف ۲۰۰۰$ n=95 با PF 2.38. این کف را بر اساس
#   اندازهٔ پوزیشن خودتان تنظیم کنید، نه بر اساس بهینه‌سازی بک‌تست (MIN_TURNOVER_USDT).
# لایهٔ ۲ (تأیید بریک‌اوت): حجم کندل ≥ ۱.۲× میانگین ۲۰ کندل + حجم کندل قبل ≥ ۱.۰×
#   + بدنهٔ کندل ≥ ۶۰٪ دامنه. «پایداری حجم» مهم‌ترین شرط است: پیک تک‌کندلی نویز است.
# لایهٔ ۳ (دفتر سفارش زنده): اسپرد ≤ ۰.۶٪ و عمق ≥ ۱.۵× حجم سفارش.
VOL_WINDOW        = _env_int("VOL_WINDOW", 20)          # پنجرهٔ میانگین/میانهٔ حجم
VOL_MIN           = _env_float("VOL_MIN", VOL_MULT)     # حجم کندل سیگنال / میانگین
VOL_PREV_MIN      = _env_float("VOL_PREV_MIN", 1.0)     # حجم کندل قبل (پایداری)
BODY_MIN          = _env_float("BODY_MIN", 0.6)         # بدنه / دامنهٔ کندل
TURNOVER_WINDOW   = _env_int("TURNOVER_WINDOW", 180)    # ۳۰ روز × ۶ کندل ۴ساعته
MIN_TURNOVER_USDT = _env_float("MIN_TURNOVER_USDT", 2000.0)  # کف گردش مالی هر کندل
MAX_SPREAD_PCT    = _env_float("MAX_SPREAD_PCT", 0.60)  # حداکثر اسپرد مجاز (٪)
DEPTH_MULT        = _env_float("DEPTH_MULT", 1.5)       # عمق لازم = حجم سفارش × این
ZERO_VOL_MAX      = _env_float("ZERO_VOL_MAX", 0.05)    # حداکثر سهم کندل‌های بی‌حجم
STALE_VOL_MAX     = _env_float("STALE_VOL_MAX", 0.10)   # حداکثر سهم حجم‌های تکراری
ORDERBOOK_ON      = _env_bool("ORDERBOOK_ON", True)     # لایهٔ ۳ روشن باشد؟

# --- لیست سفید نمادها: فقط نمادهایی که در بک‌تست سود مثبت داشتند ---
# لیست سفید ۱۵ نمادی — از فیلتر «n>=10 و سود خالص > 0 و PF>=1.10» روی ۳۵ نماد بیرون آمد.
# سود خالص هر نماد (٪، هزینه واقعی بیت‌پین): SOL +322 | ADA +109 | GALA +87 | XRP +85
#   ALGO +72 | AAVE +41 | CRV +41 | NEAR +38 | ARB +38 | UNI +20 | SUI +18 | VET +17
#   AVAX +7 | TRX +1.3 | XLM +0.6
# نمادهای حذف‌شده (ضررده یا کم‌نمونه): ENA, WIF, LINK, BNB, OP, ETC, DOT, ATOM, DOGE,
#   INJ, LTC, FET, FIL, SAND, BCH, MANA, ETH, BTC
DEFAULT_SYMBOLS = [
    "SOL_USDT", "ADA_USDT", "XRP_USDT", "ALGO_USDT", "GALA_USDT", "AAVE_USDT",
    "CRV_USDT", "NEAR_USDT", "ARB_USDT", "UNI_USDT", "SUI_USDT", "VET_USDT",
    "AVAX_USDT", "TRX_USDT", "XLM_USDT",
]
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "").split(",") if s.strip()] or DEFAULT_SYMBOLS
SYMBOLS = [s if s.endswith("_USDT") else s + "_USDT" for s in SYMBOLS]

SCAN_INTERVAL = _env_int("SCAN_INTERVAL", 300)   # فقط برای حالت SCAN_MODE=interval
SCAN_MODE     = os.getenv("SCAN_MODE", "candle").strip().lower()  # candle | interval
CANDLE_BUFFER = _env_int("CANDLE_BUFFER", 60)    # ثانیه صبر بعد از بسته‌شدن کندل
RETRY_BACKOFF = _env_int("RETRY_BACKOFF", 900)   # ۱۵ دقیقه صبر بعد از خطای شبکه/۴۰۳/۵۰۳
PRICE_POLL    = _env_int("PRICE_POLL", 300)      # بین دو کندل، هر ۵ دقیقه چک قیمت (فقط تیکرها)
CANDLE_COUNT  = _env_int("CANDLE_COUNT", 500)    # تعداد کندل دانلودی
REQUEST_GAP   = _env_float("REQUEST_GAP", 0.35)  # فاصله بین درخواست‌ها (ادب به API)

# --- اصلاح ۱.۱.۰: اعتبار قیمت لحظه‌ای و کندل ناقص ---
# PRICE_TTL: چند ثانیه کش تیکرها معتبر است (هرگز بیشتر از PRICE_POLL).
# PRICE_MAX_AGE: اگر سن کش از این بیشتر شد، قیمت «کهنه» است: ورود جدید و
#   خروج با قیمت لحظه‌ای ممنوع؛ فقط کندل‌های بسته‌شده تصمیم می‌گیرند.
PRICE_TTL       = _env_float("PRICE_TTL", 15.0)
PRICE_MAX_AGE   = _env_float("PRICE_MAX_AGE", max(120.0, 2.0 * PRICE_POLL))
PRICE_ALERT_GAP = _env_int("PRICE_ALERT_GAP", 1800)   # فاصله بین دو هشدار «قیمت کهنه»
PARTIAL_ON_POLL = _env_bool("PARTIAL_ON_POLL", True)   # در price_only_check کندل ناقص هم بگیر

# کش تیکر نباید از خودِ فاصلهٔ نمونه‌برداری عمرش بیشتر باشد، وگرنه هر بار
# همان دادهٔ قبلی «تازه» پنداشته می‌شود (باگ نسخه ۱.۰.۰).
PRICE_TTL = max(5.0, min(PRICE_TTL, float(PRICE_POLL)))
PRICE_MAX_AGE = max(float(PRICE_POLL) + 60.0, PRICE_MAX_AGE)

STATE_FILE    = os.getenv("STATE_FILE", "donchian_state.json")
LOG_FILE      = os.getenv("LOG_FILE", "donchian_bot.log")

# =====================================================================
# ۲) لاگ
# =====================================================================
_LOG_LOCK = threading.Lock()

def log(msg, level="info"):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    icons = {"info": "•", "ok": "✓", "warning": "!", "error": "✗", "signal": "★"}
    line = f"{stamp} UTC {icons.get(level, '•')} {msg}"
    with _LOG_LOCK:
        print(line, flush=True)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

# =====================================================================
# ۳) لایه HTTP (با چرخش میزبان)
# =====================================================================
# دامنه‌ها: api.bitpin.com از سرور کاربر در دسترس نیست، پس آخرین گزینه است.
# با متغیر محیطی BITPIN_HOSTS (جدا شده با کاما) قابل بازنویسی است.
BITPIN_HOSTS = [h.strip().rstrip("/") for h in os.getenv(
    "BITPIN_HOSTS", "https://api.bitpin.org,https://api.bitpin.ir,https://api.bitpin.com"
).split(",") if h.strip()]
CANDLES_PATH = "/api/v1/mkt/candles/"
TICKERS_PATH = "/api/v1/mkt/tickers/"
# مسیر درست دفتر سفارش — تایید شده با پاسخ ۲۰۰.
# (نسخهٔ ۲.۰.۰ مسیر اشتباه /api/v1/mkt/depth/ داشت و همیشه ۴۰۴ می‌گرفت،
#  پس گیت دفتر سفارش بی‌صدا fail-open می‌شد و هیچ‌وقت کار نمی‌کرد.)
ORDERBOOK_PATH = "/api/v1/mth/orderbook/{symbol}/"

RES_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://bitpin.ir",
    "Referer": "https://bitpin.ir/",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
})

_HOST = {"base": None, "ts": 0.0}
_HOST_TTL = 600
_LAST_REQ = {"ts": 0.0}

# آمار خطاهای HTTP در این چرخه — برای تصمیم «صبر ۱۵ دقیقه‌ای»
HTTP_STATE = {"hard_fail": 0, "last_error": "", "ok_streak": 0}


def _throttle():
    gap = time.time() - _LAST_REQ["ts"]
    if gap < REQUEST_GAP:
        time.sleep(REQUEST_GAP - gap)
    _LAST_REQ["ts"] = time.time()


def get_json(path, params=None, timeout=25, retries=2):
    """GET با fallback روی دامنه‌ها. برمی‌گرداند (data, host) یا (None, None).

    خطاهای شبکه/۴۰۳/۵۰۳/۵xx باعث کرش نمی‌شوند: فقط None برمی‌گردد و
    شمارندهٔ HTTP_STATE["hard_fail"] بالا می‌رود تا main() ۱۵ دقیقه صبر کند.
    """
    hosts = list(BITPIN_HOSTS)
    if _HOST["base"] and (time.time() - _HOST["ts"] < _HOST_TTL) and _HOST["base"] in hosts:
        hosts.remove(_HOST["base"])
        hosts.insert(0, _HOST["base"])

    last_err = None
    for host in hosts:
        for attempt in range(retries):
            try:
                _throttle()
                r = SESSION.get(host + path, params=params, timeout=timeout)
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:
                        last_err = f"invalid JSON from {host}"
                        break
                    _HOST["base"], _HOST["ts"] = host, time.time()
                    HTTP_STATE["ok_streak"] += 1
                    return data, host
                last_err = f"HTTP {r.status_code} from {host}"
                # ۴۰۳/۴۵۱ = مسدود موقت (تعمیرات/کلادفلر) -> دامنهٔ بعدی، بدون تلاش مجدد
                if r.status_code in (400, 403, 404, 451):
                    break
                time.sleep(1.0)
            except Exception as e:
                last_err = f"{host}: {type(e).__name__}"
                time.sleep(1.0)

    HTTP_STATE["hard_fail"] += 1
    HTTP_STATE["last_error"] = str(last_err)
    HTTP_STATE["ok_streak"] = 0
    log(f"[HTTP] {path} failed: {last_err}", "error")
    return None, None

# =====================================================================
# ۴) داده‌ها
# =====================================================================
def fetch_candles(symbol, count=CANDLE_COUNT, keep_partial=False):
    """کندل‌ها را می‌گیرد.

    keep_partial=False -> فقط کندل‌های بسته‌شده (رفتار قبلی).
    keep_partial=True  -> تاپل (closed_df, partial) که partial یک dict است:
        {timestamp(ms), open, high, low, close, volume, closed_at(sec)}
        اگر کندل ناقصی وجود نداشت، partial=None.

    چرا؟ کندل در حال تشکیل هم High/Low واقعی دارد و لمس SL/TP داخل آن
    باید تریگر شود؛ نسخهٔ ۱.۰.۰ آن را دور می‌ریخت و تا ۴ ساعت لمس را نمی‌دید.
    """
    step = RES_SECONDS[TIMEFRAME]
    now = int(time.time())
    params = {"symbol": symbol, "res": TIMEFRAME,
              "from": now - int(count + 5) * step, "to": now}
    data, _ = get_json(CANDLES_PATH, params=params)
    if not data:
        return (None, None) if keep_partial else None
    rows = data if isinstance(data, list) else data.get("results", [])
    if not rows:
        return (None, None) if keep_partial else None

    df = pd.DataFrame(rows)
    # بیت‌پین هم time (ms) و هم ts (s) می‌دهد -> فقط یکی بماند
    if "time" in df.columns and "ts" in df.columns:
        df = df.drop(columns=["ts"])
    df = df.rename(columns={"time": "timestamp", "ts": "timestamp",
                            "open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    if "timestamp" not in df.columns:
        return (None, None) if keep_partial else None
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            return (None, None) if keep_partial else None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")

    if df["timestamp"].max() < 10_000_000_000:      # ثانیه -> میلی‌ثانیه
        df["timestamp"] = df["timestamp"] * 1000

    df = (df.dropna(subset=["Open", "High", "Low", "Close", "Volume", "timestamp"])
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True))
    if df.empty:
        return (None, None) if keep_partial else None

    # جدا کردن کندل در حال تشکیل (اگر آخرین کندل هنوز بسته نشده)
    partial = None
    last_open_sec = int(df["timestamp"].iloc[-1] / 1000)
    if now < last_open_sec + step:
        r = df.iloc[-1]
        partial = {
            "timestamp": int(r["timestamp"]),
            "open": float(r["Open"]), "high": float(r["High"]),
            "low": float(r["Low"]),   "close": float(r["Close"]),
            "volume": float(r["Volume"]),
            "closed_at": last_open_sec + step,
        }
        df = df.iloc[:-1].reset_index(drop=True)

    if not keep_partial:
        return df if not df.empty else None
    return (df if not df.empty else None), partial

# ---- کش قیمت لحظه‌ای با سن واقعی (اصلاح ۱.۱.۰) ----
# باگ نسخهٔ ۱.۰.۰: در صورت شکست درخواست، همان کش قبلی «تازه» برگردانده
# می‌شد و ربات روی قیمت چند ساعته تصمیم می‌گرفت (خروج کاذب یا خروج جامانده).
_PRICE = {"data": {}, "ts": 0.0, "alerted": 0.0}

def _price_age():
    """سن کش قیمت به ثانیه (اگر هیچ داده‌ای نداریم: بی‌نهایت)."""
    if not _PRICE["data"] or not _PRICE["ts"]:
        return float("inf")
    return max(0.0, time.time() - _PRICE["ts"])

def prices_usable(age=None):
    """آیا می‌توان به قیمت لحظه‌ای اعتماد کرد؟ (تازه‌تر از PRICE_MAX_AGE)"""
    if age is None:
        age = _price_age()
    return age <= PRICE_MAX_AGE

def _alert_stale_price(age, why):
    """هشدار محدودشده دربارهٔ قیمت کهنه (هر PRICE_ALERT_GAP ثانیه یک بار)."""
    now = time.time()
    if now - _PRICE.get("alerted", 0.0) < PRICE_ALERT_GAP:
        return
    _PRICE["alerted"] = now
    age_txt = "نامعلوم" if not math.isfinite(age) else f"{age/60:.0f} دقیقه"
    log(f"[Price] قیمت لحظه‌ای کهنه است (سن {age_txt}) -> {why}", "warning")
    send_telegram("⚠️ <b>قیمت لحظه‌ای در دسترس نیست</b>\n"
                  f"سن آخرین قیمت: {age_txt}\n"
                  f"{why}\n"
                  "<i>ورود جدید متوقف شد؛ بررسی حد ضرر فقط روی کندل‌های بسته‌شده ادامه دارد.</i>")

def get_prices(force=False):
    """قیمت لحظه‌ای همه نمادها با یک درخواست.

    خروجی: (prices, age, fresh)
        age   = سن واقعی داده به ثانیه (حتی وقتی از کش می‌آید)
        fresh = آیا داده تازه است (age <= PRICE_MAX_AGE)

    هرگز کش کهنه را «تازه» جا نمی‌زنیم؛ اگر شبکه خطا داد، همان کش قبلی
    با سن واقعی‌اش و fresh=False برمی‌گردد.
    """
    now = time.time()
    if not force and _PRICE["data"] and (now - _PRICE["ts"]) < PRICE_TTL:
        age = max(0.0, now - _PRICE["ts"])
        return _PRICE["data"], age, age <= PRICE_MAX_AGE

    prev = _PRICE["data"]
    data, _ = get_json(TICKERS_PATH)
    out = {}
    if isinstance(data, list):
        for t in data:
            if not isinstance(t, dict):
                continue
            sym = str(t.get("symbol", "")).upper()
            try:
                p = float(t.get("price"))
            except (TypeError, ValueError):
                continue
            if p > 0:
                out[sym] = p

    # اعتبارسنجی پاسخ: کمتر از ۵ نماد = پاسخ ناقص/خراب، نه قیمت معتبر
    if len(out) >= 5:
        if prev and len(out) < len(prev) * 0.5:
            log(f"[Price] تعداد قیمت‌ها افت کرد: {len(prev)} -> {len(out)}", "warning")
        _PRICE["data"], _PRICE["ts"] = out, now
        return out, 0.0, True

    age = _price_age()
    if prev:
        log(f"[Price] دریافت تیکر ناموفق/ناقص -> استفاده از کش (سن {age/60:.1f} دقیقه)",
            "warning" if age > PRICE_MAX_AGE else "info")
    return (prev or {}), age, False

# =====================================================================
# ۵) فیلتر حجم (سه لایه)
# =====================================================================
# این بخش از ماژول مستقل volume_filter.py وارد شده است. «شرط حجم» به سه
# لایهٔ مستقل شکسته شده تا معلوم باشد کدام لایه «لبه» می‌سازد و کدام فقط
# «قابلیت اجرا» را تضمین می‌کند:
#
#   لایهٔ ۱ — کف نقدشوندگی: ارزهای مرده را قبل از تولید سیگنال حذف می‌کند.
#             معیار: میانهٔ گردش مالی (Close×Volume به دلار) در ۳۰ روز.
#   لایهٔ ۲ — تأیید بریک‌اوت: حجم کندل ≥ VOL_MIN × میانگین ۲۰ کندل
#             + حجم کندل قبل ≥ VOL_PREV_MIN × میانگین + بدنه ≥ BODY_MIN دامنه.
#             شرط «حجم کندل قبل» مهم‌ترین است: پیک حجم تک‌کندلی نویز است؛
#             بریک‌اوت واقعی حداقل دو کندل حجم بالا دارد.
#   لایهٔ ۳ — دفتر سفارش زنده: اسپرد و عمق، تا سیگنالی که در بک‌تست سود
#             داشت با اسلیپیج واقعی هم قابل اجرا باشد.
#
# به‌علاوه «کیفیت داده» چک می‌شود، چون دادهٔ حجمی بیت‌پین نویز دارد:
# حجم صفر، حجم تکراری (یخ‌زده) و کندل‌های بدون حرکت.
#
# ⚠️ نکتهٔ مهم: لایهٔ ۲ لبه می‌سازد؛ لایهٔ ۱ و ۳ فقط قابلیت اجرا را تأمین
# می‌کنند. کف نقدشوندگی را با اندازهٔ پوزیشن خودتان تعیین کنید.

def data_quality(d, lookback=500):
    """نویز دادهٔ حجمی را اندازه می‌گیرد.

    خروجی: سهم هر نوع نویز + پرچم ok. اگر ok=False باشد، فیلتر حجم روی این
    نماد قابل اعتماد نیست و سیگنال تولید نمی‌شود.
    """
    tail = d.tail(lookback)
    v = tail["Volume"].astype(float)
    zero_share = float((v <= 0).mean())
    stale_share = float((v.diff() == 0).mean())          # حجم «یخ‌زده»
    flat_share = float((tail["High"] == tail["Low"]).mean())  # کندل بی‌حرکت
    ok = (zero_share <= ZERO_VOL_MAX) and (stale_share <= STALE_VOL_MAX)
    return {
        "zero_vol_share": round(zero_share, 4),
        "stale_vol_share": round(stale_share, 4),
        "flat_candle_share": round(flat_share, 4),
        "ok": bool(ok),
    }


def add_volume_features(d):
    """ستون‌های حجمی لازم برای گیت را اضافه می‌کند (بدون تغییر ردیف‌ها)."""
    d = d.copy()
    c, v = d["Close"].astype(float), d["Volume"].astype(float)

    # گردش مالی هر کندل به دلار — معیار اصلی «مرده بودن» یک ارز
    d["turnover"] = c * v
    d["turnover_med"] = d["turnover"].rolling(TURNOVER_WINDOW, min_periods=60).median()

    # میانگین ساده (سازگار با vol_ratio فعلی ربات)
    d["vol_sma"] = v.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).mean()
    d["vol_ratio"] = v / d["vol_sma"].replace(0, np.nan)

    # میانه + انحراف مطلق میانه = نسخهٔ مقاوم به پیک (برای دیباگ/لاگ)
    d["vol_med"] = v.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).median()
    mad = (v - d["vol_med"]).abs().rolling(VOL_WINDOW, min_periods=VOL_WINDOW).median()
    d["vol_rz"] = (v - d["vol_med"]) / mad.replace(0, np.nan)

    # قدرت کندل
    rng = (d["High"] - d["Low"]).replace(0, np.nan)
    d["body_ratio"] = (d["Close"] - d["Open"]).abs() / rng
    d["close_pos"] = (d["Close"] - d["Low"]) / rng   # ۱ = بسته‌شدن روی سقف
    return d


def volume_gate(d, min_turnover=MIN_TURNOVER_USDT, prepared=False):
    """ماسک بولی حجم برای هر کندل + ستون دلیل رد شدن.

    prepared=True یعنی ستون‌های حجمی از قبل ساخته شده‌اند (add_volume_features
    قبلاً صدا زده شده) و لازم نیست دوباره محاسبه شوند.
    """
    if not prepared:
        d = add_volume_features(d)

    out = pd.DataFrame(index=d.index)
    out["liq_ok"] = (d["turnover_med"] >= min_turnover).fillna(False)
    out["spike_ok"] = (d["vol_ratio"] >= VOL_MIN).fillna(False)
    out["persist_ok"] = (d["vol_ratio"].shift(1) >= VOL_PREV_MIN).fillna(False)
    out["body_ok"] = (d["body_ratio"] >= BODY_MIN).fillna(False)
    out["vol_ok"] = out.liq_ok & out.spike_ok & out.persist_ok & out.body_ok

    out["reject"] = np.select(
        [~out.liq_ok, ~out.spike_ok, ~out.persist_ok, ~out.body_ok],
        ["کم‌حجم (کف نقدشوندگی)", "حجم کم", "حجم ناپایدار", "بدنهٔ ضعیف"],
        default="",
    )
    return out


def orderbook_gate(bids, asks, notional_usdt,
                   max_spread_pct=MAX_SPREAD_PCT, depth_mult=DEPTH_MULT):
    """لایهٔ ۳: اسپرد و عمق را در لحظهٔ سیگنال چک می‌کند.

    bids/asks: [[price, amount_base], ...] از /api/v1/mth/orderbook/{sym}/
    خروجی: {"ok": bool, "spread_pct": float|None, "reason": str}
    دادهٔ نامعتبر = رد نشدن (fail-open)؛ فقط اندازه‌گیری واقعی می‌تواند رد کند.
    """
    try:
        bb = float(bids[0][0])
        ba = float(asks[0][0])
    except (TypeError, IndexError, ValueError):
        return {"ok": True, "spread_pct": None, "reason": "دفتر سفارش نامعتبر — رد نشد"}
    if bb <= 0 or ba <= 0:
        return {"ok": True, "spread_pct": None, "reason": "قیمت نامعتبر — رد نشد"}

    mid = (bb + ba) / 2.0
    spread_pct = (ba - bb) / mid * 100.0

    need = notional_usdt * depth_mult
    depth = 0.0
    for px, amt in asks:
        try:
            depth += float(px) * float(amt)
        except (TypeError, ValueError):
            continue
        if depth >= need:
            break

    if spread_pct > max_spread_pct:
        return {"ok": False, "spread_pct": round(spread_pct, 3),
                "reason": f"اسپرد {spread_pct:.2f}% > {max_spread_pct}%"}
    if depth < need:
        return {"ok": False, "spread_pct": round(spread_pct, 3),
                "reason": f"عمق {depth:,.0f}$ < نیاز {need:,.0f}$"}
    return {"ok": True, "spread_pct": round(spread_pct, 3), "reason": ""}


def fetch_orderbook(symbol):
    """دفتر سفارش زنده را می‌گیرد؛ در خطای شبکه None (گیت fail-open)."""
    if not ORDERBOOK_ON:
        return None
    data, _ = get_json(ORDERBOOK_PATH.format(symbol=symbol), timeout=15, retries=1)
    if not isinstance(data, dict):
        return None
    bids, asks = data.get("bids"), data.get("asks")
    if not bids or not asks:
        return None
    return {"bids": bids, "asks": asks}


# =====================================================================
# ۶) اندیکاتورها
# =====================================================================
def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def _rma(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()

def add_indicators(df):
    d = df.copy()
    h, l, c, v = d.High, d.Low, d.Close, d.Volume

    d["ema50"] = _ema(c, 50)
    d["ema200"] = _ema(c, 200)

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = _rma(tr, ATR_LEN)

    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=d.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=d.index)
    atr_safe = d["atr"].replace(0, np.nan)
    d["pdi"] = 100 * _rma(pdm, 14) / atr_safe
    d["ndi"] = 100 * _rma(ndm, 14) / atr_safe
    dx = 100 * (d["pdi"] - d["ndi"]).abs() / (d["pdi"] + d["ndi"]).replace(0, np.nan)
    d["adx"] = _rma(dx.fillna(0), 14)

    d["dc_hi"] = h.rolling(DC_LEN).max().shift(1)      # سقف ۵۵ کندل قبل (بدون کندل جاری)
    # ۱.۳.۰: کف ۲۰ کندل برای خروج دانچیان. shift(1) یعنی کف فقط از کندل‌های
    # *قبل* ساخته می‌شود؛ کندل جاری در ساخت کف خودش شرکت نمی‌کند (بدون lookahead).
    d["dc_lo20"] = l.rolling(DC_EXIT_LEN).min().shift(1)

    # ۱.۲.۰: ستون‌های حجمی (turnover_med, vol_ratio, body_ratio, vol_rz, ...)
    # یک‌جا از ماژول فیلتر حجم ساخته می‌شوند تا محاسبه دوباره نداشته باشیم.
    d = add_volume_features(d)
    d["vol_ma"] = d["vol_sma"]                          # سازگاری با کد/لاگ قبلی
    return d

# =====================================================================
# ۷) تشخیص سیگنال (LONG فقط)
# =====================================================================
def evaluate(df):
    """
    آخرین کندل بسته‌شده را ارزیابی می‌کند.
    خروجی: dict با کلیدهای triggered, checks, entry_ref, atr, ...
    """
    if df is None or len(df) < WARMUP:
        return {"triggered": False, "reason": "داده کافی نیست"}

    d = add_indicators(df)
    i = len(d) - 1                       # آخرین کندل بسته‌شده
    row = d.iloc[i]
    prev = d.iloc[i - 1]

    if not all(np.isfinite(row[k]) for k in ("atr", "adx", "ema50", "ema200", "dc_hi", "vol_ratio")):
        return {"triggered": False, "reason": "اندیکاتور ناقص"}

    # --- فیلتر حجم سه‌لایه (لایهٔ ۱ و ۲؛ لایهٔ ۳ در run_cycle با دفتر سفارش) ---
    dq = data_quality(d)
    gate = volume_gate(d, prepared=True)      # ستون‌ها از add_indicators آماده‌اند
    vol_ok = bool(gate["vol_ok"].iloc[i]) and dq["ok"]
    vol_reject = str(gate["reject"].iloc[i]) if not bool(gate["vol_ok"].iloc[i]) else ""
    if not dq["ok"]:
        vol_reject = "کیفیت دادهٔ حجمی پایین"

    checks = {
        "breakout":  bool(row["Close"] > row["dc_hi"]),
        "volume":    bool(row["vol_ratio"] >= VOL_MULT),
        "trend":     bool(row["adx"] >= ADX_MIN),
        "ema":       bool(row["ema50"] > row["ema200"]),
        "vol_gate":  vol_ok,          # کف نقدشوندگی + پایداری حجم + بدنه
    }
    # توجه: فیلتر «تازگی شکست» عمداً حذف شد — بک‌تست نشان داد فیلتر کردن
    # ورودهای مجدد در یک روند، ۷۰٪ سود را از بین می‌برد (۵۴۸٪ → ۱۵۷٪).
    triggered = all(checks.values())

    return {
        "triggered": triggered,
        "checks": checks,
        "candle_ts": int(row["timestamp"] / 1000),
        "close": float(row["Close"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "open": float(row["Open"]),
        "dc_hi": float(row["dc_hi"]),
        "atr": float(row["atr"]),
        "atr_pct": float(row["atr"] / row["Close"] * 100),
        "adx": float(row["adx"]),
        "pdi": float(row["pdi"]),
        "ndi": float(row["ndi"]),
        "vol_ratio": float(row["vol_ratio"]),
        "body_ratio": float(row["body_ratio"]) if np.isfinite(row["body_ratio"]) else None,
        "turnover_med": float(row["turnover_med"]) if np.isfinite(row["turnover_med"]) else 0.0,
        "vol_reject": vol_reject,
        "dq": dq,
        "ema50": float(row["ema50"]),
        "ema200": float(row["ema200"]),
        "bars_above_ema200": int((d["Close"] > d["ema200"]).tail(20).sum()),
        "reason": ("شکست سقف ۵۵ کندل با تأیید حجم/ADX/روند" if triggered
                   else (f"رد فیلتر حجم: {vol_reject}" if vol_reject
                         else "شرط ورود کامل نیست")),
    }

# =====================================================================
# ۸) سطوح و حجم
# =====================================================================
def build_levels(sig, price):
    """ورود = قیمت مارکت فعلی، SL/TP از ATR همان کندل سیگنال."""
    atr = sig["atr"]
    entry = price if price and price > 0 else sig["close"]
    sl = entry - SL_ATR * atr
    tp = entry + TP_ATR * atr
    if sl <= 0 or entry <= 0:
        return None

    risk_pct = (entry - sl) / entry * 100
    if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
        return {"rejected": True, "risk_pct": risk_pct,
                "why": f"فاصله حد ضرر {risk_pct:.1f}% خارج از بازه مجاز "
                       f"({MIN_RISK_PCT}-{MAX_RISK_PCT}%)"}

    risk_usdt = EQUITY_USDT * RISK_PCT / 100.0
    qty = risk_usdt / (entry - sl)
    notional = qty * entry
    cap = EQUITY_USDT * MAX_NOTIONAL_MULT
    if notional > cap:
        notional = cap
        qty = cap / entry

    # کارمزد رفت‌وبرگشت (۰.۲٪ هر طرف) + اسلیپیج تقریبی
    fees = notional * 0.002 * 2
    return {
        "rejected": False,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "risk_pct": risk_pct,
        "rr": (tp - entry) / (entry - sl),
        "qty": qty,
        "notional": notional,
        "risk_usdt": risk_usdt,
        "fees_usdt": fees,
        "tp_pct": (tp - entry) / entry * 100,
    }

# =====================================================================
# ۹) تلگرام
# =====================================================================
_TG = {"lock": threading.Lock(), "ts": 0.0}
TG_MIN_GAP = 1.2

def send_telegram(text):
    if DRY_RUN and not TG_IN_DRY_RUN:
        log("[TG] dry-run -> پیام ارسال نشد")
        print(text)
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("[TG] توکن/چت‌آیدی تنظیم نشده -> فقط چاپ در کنسول")
        print("\n" + text + "\n")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    with _TG["lock"]:
        gap = time.time() - _TG["ts"]
        if gap < TG_MIN_GAP:
            time.sleep(TG_MIN_GAP - gap)
        for attempt in range(3):
            try:
                r = SESSION.post(url, json=payload, timeout=15)
                if r.status_code == 200:
                    _TG["ts"] = time.time()
                    return True
                if r.status_code == 429:
                    wait = 5
                    try:
                        wait = int(r.json().get("parameters", {}).get("retry_after", 5))
                    except Exception:
                        pass
                    time.sleep(wait)
                    continue
                if r.status_code == 400:
                    log(f"[TG] 400: {r.text[:200]}", "error")
                    payload.pop("parse_mode", None)   # تلاش دوباره بدون HTML
                    continue
                time.sleep(2)
            except Exception as e:
                log(f"[TG] {type(e).__name__}: {e}", "warning")
                time.sleep(2)
        _TG["ts"] = time.time()
    return False

def fmt_price(p):
    if p is None or not math.isfinite(p):
        return "-"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.8f}".rstrip("0").rstrip(".")

def format_signal(symbol, sig, lv, ob=None):
    ts = datetime.fromtimestamp(sig["candle_ts"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines = [
        "🟢 <b>سیگنال خرید (LONG)</b>",
        f"<b>نماد:</b> <code>{symbol}</code>",
        f"<b>استراتژی:</b> شکست کانال ۵۵ ({TIMEFRAME})",
        f"<b>کندل سیگنال:</b> {ts} UTC",
        "",
        f"<b>ورود (مارکت):</b> <code>{fmt_price(lv['entry'])}</code>",
        f"<b>حد ضرر:</b> <code>{fmt_price(lv['sl'])}</code>  (−{lv['risk_pct']:.1f}%)",
        (f"<b>حد سود:</b> <code>{fmt_price(lv['tp'])}</code>  (+{lv['tp_pct']:.1f}%)"
         if EXIT_MODE == "fixed" else
         f"<b>خروج:</b> بستن زیر کف {DC_EXIT_LEN} کندل (TP غیرفعال)"),
        (f"<b>R:R:</b> {lv['rr']:.2f} | <b>حداکثر نگهداری:</b> {MAX_HOLD} کندل (~{MAX_HOLD*4//24} روز)"
         if EXIT_MODE == "fixed" else
         f"<b>حداکثر نگهداری:</b> {MAX_HOLD} کندل (~{MAX_HOLD*4//24} روز) | <b>SL:</b> {SL_ATR:g} ATR ثابت"),
        "",
        f"<b>حجم پیشنهادی:</b> <code>{lv['qty']:.6g}</code> (~{lv['notional']:.1f} USDT)",
        f"<b>ریسک:</b> {lv['risk_usdt']:.2f} USDT ({RISK_PCT:g}% از {EQUITY_USDT:g}) | <b>کارمزد تخمینی:</b> {lv['fees_usdt']:.2f} USDT",
        "",
        f"<b>سقف ۵۵ کندل:</b> <code>{fmt_price(sig['dc_hi'])}</code> (شکسته شد)",
        f"<b>ATR:</b> {fmt_price(sig['atr'])} ({sig['atr_pct']:.2f}%) | <b>حجم:</b> {sig['vol_ratio']:.2f}x",
        f"<b>ADX:</b> {sig['adx']:.1f} (DI+ {sig['pdi']:.1f} / DI− {sig['ndi']:.1f}) | EMA50 {'>' if sig['ema50']>sig['ema200'] else '<'} EMA200",
        (f"<b>گردش مالی میانه:</b> {sig['turnover_med']:,.0f} USDT/کندل (کف {MIN_TURNOVER_USDT:,.0f}$)"
         if sig.get("turnover_med") else
         f"<b>گردش مالی میانه:</b> - (کف {MIN_TURNOVER_USDT:,.0f}$)"),
    ]
    if sig.get("body_ratio") is not None:
        lines.append(f"<b>بدنهٔ کندل:</b> {sig['body_ratio']*100:.0f}٪ دامنه (حداقل {BODY_MIN*100:.0f}٪)")
    if ob and ob.get("spread_pct") is not None:
        lines.append(f"<b>اسپرد دفتر سفارش:</b> {ob['spread_pct']:.2f}٪ (حداکثر {MAX_SPREAD_PCT}٪)")
    if DRY_RUN:
        lines += ["", "⚠️ <i>حالت آزمایشی (DRY_RUN) — سیگنال تستی است</i>"]
    lines += ["", "<i>ورود در بازشدن کندل بعدی. این پیام توصیه سرمایه‌گذاری نیست.</i>"]
    return "\n".join(lines)

def format_exit(pos, result, price, bars_held, gap=False):
    icon = {"tp": "✅", "sl": "🛑", "time": "⏳", "manual": "⚪",
            "donch": "🔻"}.get(result, "⚪")
    title = {"tp": "حد سود خورد", "sl": "حد ضرر خورد",
             "time": f"خروج زمانی ({MAX_HOLD} کندل)",
             "donch": f"خروج دانچیان (بستن زیر کف {DC_EXIT_LEN} کندل)",
             "manual": "بسته شد"}.get(result, result)
    entry = pos.get("entry") or 0
    pnl_pct = (price / entry - 1) * 100 if entry else 0.0
    sl = pos.get("sl") or 0
    risk = entry - sl
    r_mult = (price - entry) / risk if risk else 0.0
    pnl_usdt = (price - entry) * pos.get("qty", 0)
    lines = [
        f"{icon} <b>{title}</b> — <code>{pos.get('symbol', '?')}</code>",
        f"<b>ورود:</b> <code>{fmt_price(entry)}</code>",
        f"<b>خروج:</b> <code>{fmt_price(price)}</code>",
        f"<b>نتیجه:</b> {pnl_pct:+.2f}% | {r_mult:+.2f}R | {pnl_usdt:+.2f} USDT",
        f"<b>مدت:</b> {bars_held} کندل ({bars_held*4//24} روز)",
    ]
    if gap:
        lines.append("🕳 <i>گپ قیمتی: کندل پایین‌تر/بالاتر از سطح باز شد؛ "
                     "پر شدن روی همان بازشدن ثبت شد (R بدتر از ۱±).</i>")
    if r_mult < -1.05:
        lines.append(f"⚠️ <i>زیان بیش از ۱R — لغزش گپ یا قیمت لحظه‌ای؛ "
                     f"این ریسک واقعی است نه خطای محاسبه.</i>")
    return "\n".join(lines)

# =====================================================================
# ۱۰) حالت (ضدتکرار سیگنال + پیگیری معاملات باز)
# =====================================================================
_STATE_LOCK = threading.Lock()
STATS = {"scans": 0, "signals": 0, "errors": 0, "started": time.time()}
STATE = {"sent": {}, "open": {}, "closed": [], "stats": STATS}

def load_state():
    global STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            STATE.update({
                "sent": data.get("sent", {}),
                "open": data.get("open", {}),
                "closed": data.get("closed", [])[-300:],
            })
            # شمارنده‌ها را در همان دیکشنری سراسری نگه دار (STATE["stats"] == STATS)
            STATS["scans"] = int(data.get("stats", {}).get("scans", 0))
            STATS["signals"] = int(data.get("stats", {}).get("signals", 0))
            STATS["errors"] = int(data.get("stats", {}).get("errors", 0))
        log(f"[State] بارگذاری شد: {len(STATE['open'])} معامله باز، {len(STATE['sent'])} سیگنال ثبت‌شده")
    except FileNotFoundError:
        log("[State] فایل حالت وجود ندارد -> شروع تازه")
    except Exception as e:
        log(f"[State] خطای بارگذاری: {e}", "warning")

def save_state():
    tmp = STATE_FILE + ".tmp"
    try:
        with _STATE_LOCK:
            STATE["stats"] = STATS
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(STATE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"[State] خطای ذخیره: {e}", "warning")

def already_sent(symbol, candle_ts):
    return f"{symbol}|{candle_ts}" in STATE["sent"]

def mark_sent(symbol, candle_ts, lv):
    STATE["sent"][f"{symbol}|{candle_ts}"] = {"ts": candle_ts, "entry": lv["entry"]}
    # هرس کلیدهای قدیمی‌تر از ۳۰ روز
    cutoff = time.time() - 30 * 86400
    STATE["sent"] = {k: v for k, v in STATE["sent"].items() if v.get("ts", 0) > cutoff}

# =====================================================================
# ۱۱) پیگیری معاملات باز (SL/TP/خروج زمانی)
# =====================================================================
def _exit_fill(level, ref_price, result):
    """قیمت واقعی پر شدن حد ضرر/سود را تخمین می‌زند و گپ را گزارش می‌کند.

    اگر کندل پایین‌تر از SL باز شده باشد (گپ نزولی)، پر شدن روی همان بازشدن
    انجام می‌شود نه روی SL؛ یعنی زیان می‌تواند از ۱R بدتر باشد. همین منطق
    در جهت مثبت برای TP.
    خروجی: (fill, gap)
    """
    try:
        level = float(level)
        ref = float(ref_price)
    except (TypeError, ValueError):
        return level, False
    if ref <= 0:
        return level, False
    if result == "sl":
        fill = min(level, ref)          # هرچه بدتر، واقعی‌تر
        gap = fill < level * 0.995
    elif result == "tp":
        fill = max(level, ref)          # هرچه بهتر، واقعی‌تر
        gap = fill > level * 1.005
    else:
        return ref, False
    return fill, gap

def track_open_positions(candles_cache, partials=None, prices=None,
                         price_age=None, prices_fresh=True):
    """پیگیری معاملات باز در سه مرحله (اصلاح ۱.۱.۰).

    ۱) کندل‌های بسته‌شده بعد از کندل سیگنال -> منطق اصلی و قابل بازتولید
    ۲) کندل در حال تشکیل (High/Low تا این لحظه) -> تریگر داخل کندل
    ۳) قیمت لحظه‌ای -> فقط اگر تازه باشد (نه کهنه)

    ۱.۳.۰: حالت خروج per-position است (pos["exit_mode"]). خروج دانچیان
    (بستن زیر کف ۲۰ کندل) فقط در مرحلهٔ ۱ و فقط روی کندل بسته اعمال می‌شود؛
    در مرحلهٔ ۲ و ۳ عمداً چک نمی‌شود تا خروج روی کندل نیمه‌کاره رخ ندهد.
    """
    if not STATE["open"]:
        return
    partials = partials or {}
    prices = prices or {}
    if price_age is None:
        price_age = _price_age()
    live_ok = bool(prices) and prices_fresh and prices_usable(price_age)

    for symbol in list(STATE["open"].keys()):
        pos = STATE["open"][symbol]
        ct = _signal_ts(pos)
        pos.setdefault("bars", 0)

        # ---------- مرحله ۱: کندل‌های بسته ----------
        df = candles_cache.get(symbol)
        done = False
        if df is not None and not df.empty:
            # «bars» مشتق از داده است، نه انباشتی: هر اسکن همان کندل‌ها را
            # دوباره می‌بیند، پس شمارش تجمعی باعث باد کردن bars و خروج زمانی
            # زودهنگام می‌شد (باگ نسخه ۱.۱.۰ که در تست پیدا شد).
            after = df[df["timestamp"] / 1000 > ct]
            if not after.empty:
                # ۱.۳.۰: کف ۲۰ کندل. اگر ستون آمادهٔ add_indicators هست همان را
                # برمی‌داریم؛ در دادهٔ دستی تست، همین‌جا با همان shift(1) ساخته
                # می‌شود تا کف هرگز کندل جاری را شامل نشود.
                if "dc_lo20" in df.columns:
                    dcl_all = df["dc_lo20"]
                else:
                    dcl_all = df["Low"].rolling(DC_EXIT_LEN).min().shift(1)
                dcl_after = dcl_all.reindex(after.index)
                # حالت خروج مخصوص همین پوزیشن (نه گلوبال): پوزیشن‌های بازِ
                # نسخهٔ ۱.۲.۰ که با TP باز شده‌اند، بعد از ارتقا هم TP خود را
                # نگه می‌دارند و ناگهان به منطق دانچیان پرت نمی‌شوند.
                # پوزیشن بازشده با نسخهٔ ۱.۲.۰ کلید exit_mode ندارد ->
                # پیش‌فرض «fixed» تا TP قول‌داده‌شده در سیگنال تلگرام باطل نشود.
                p_mode = pos.get("exit_mode") or "fixed"
                for k, (row_idx, row) in enumerate(after.iterrows(), start=1):
                    pos["bars"] = k
                    if row["Low"] <= pos["sl"]:
                        fill, gap = _exit_fill(pos["sl"], row["Open"], "sl")
                        _close_position(symbol, pos, fill, "sl", pos["bars"], gap)
                        done = True
                        break
                    if p_mode == "fixed" and row["High"] >= pos["tp"]:
                        fill, gap = _exit_fill(pos["tp"], row["Open"], "tp")
                        _close_position(symbol, pos, fill, "tp", pos["bars"], gap)
                        done = True
                        break
                    # ترتیب عمدی: تایم‌اوت قبل از دانچیان چک می‌شود تا با
                    # موتور بک‌تست (bt2) یکی باشد: آن‌جا حلقه فقط کندل‌های
                    # ۱..۴۷ را ارزیابی می‌کند و کندل ۴۸ همیشه «خروج زمانی»
                    # است. قیمت خروج در هر دو حالت Close همان کندل است،
                    # پس فقط برچسب فرق می‌کند، نه نتیجهٔ مالی.
                    if pos["bars"] >= MAX_HOLD:
                        _close_position(symbol, pos, float(row["Close"]), "time", pos["bars"])
                        done = True
                        break
                    if p_mode == "donch20":
                        # فقط کندل بسته‌شده می‌تواند خروج دانچیان بدهد
                        dcl = dcl_after.loc[row_idx]
                        if pd.notna(dcl) and float(row["Close"]) < float(dcl):
                            _close_position(symbol, pos, float(row["Close"]), "donch",
                                            pos["bars"])
                            done = True
                            break
        if done:
            continue

        # ---------- مرحله ۲: کندل در حال تشکیل ----------
        pt = partials.get(symbol)
        p_mode = pos.get("exit_mode") or "fixed"
        if pt and int(pt["timestamp"] / 1000) > ct:
            if pt["low"] <= pos["sl"]:
                fill, gap = _exit_fill(pos["sl"], pt["open"], "sl")
                _close_position(symbol, pos, fill, "sl", pos["bars"], gap)
                continue
            # در donch20 حد سود غیرفعال است (خروج فقط با بستن زیر کف یا SL/تایم‌اوت)
            if p_mode == "fixed" and pt["high"] >= pos["tp"]:
                fill, gap = _exit_fill(pos["tp"], pt["open"], "tp")
                _close_position(symbol, pos, fill, "tp", pos["bars"], gap)
                continue

        # ---------- مرحله ۳: قیمت لحظه‌ای (فقط تازه) ----------
        live = prices.get(symbol)
        if live and live_ok:
            if live <= pos["sl"]:
                fill, gap = _exit_fill(pos["sl"], live, "sl")
                _close_position(symbol, pos, fill, "sl", pos["bars"], gap)
                continue
            if p_mode == "fixed" and live >= pos["tp"]:
                fill, gap = _exit_fill(pos["tp"], live, "tp")
                _close_position(symbol, pos, fill, "tp", pos["bars"], gap)
                continue

        save_state()

def _signal_ts(pos):
    """زمان کندل سیگنال (با فالبک به زمان باز شدن پوزیشن در حالت‌های قدیمی)."""
    return int(pos.get("candle_ts") or pos.get("opened_at") or 0)

def _close_position(symbol, pos, exit_price, result, bars, gap=False):
    send_telegram(format_exit(pos, result, exit_price, bars, gap))
    risk = pos["entry"] - pos["sl"]
    r_mult = (exit_price - pos["entry"]) / risk if risk else 0.0
    with _STATE_LOCK:
        STATE["closed"].append({
            "symbol": symbol, "entry": pos["entry"], "sl": pos["sl"], "tp": pos["tp"],
            "qty": pos.get("qty", 0), "exit": exit_price,
            "result": result, "r": round(r_mult, 3), "bars": bars,
            "gap": bool(gap), "closed_at": int(time.time()),
        })
        STATE["closed"] = STATE["closed"][-300:]
        STATE["open"].pop(symbol, None)
    log(f"[Exit] {symbol} {result} @ {fmt_price(exit_price)} "
        f"({r_mult:+.2f}R, {bars} کندل{', گپ' if gap else ''})", "ok")
    save_state()

# =====================================================================
# ۱۱.۵) رژیم BTC (فیلتر ورود، fail-open)
# =====================================================================
_BTC_CACHE = {"ts": 0.0, "ok": True, "info": {}}

def btc_regime_ok(force=False):
    """آیا رژیم BTC اجازهٔ ورود می‌دهد؟ (close آخرین کندل بسته > EMA200)

    خروجی: (ok: bool, info: dict)

    نکتهٔ مهم دربارهٔ repainting:
    fetch_candles(keep_partial=True) کندل در حال تشکیل را از df جدا می‌کند،
    پس df["Close"].iloc[-1] همیشه آخرین کندل **بسته‌شده** است. بنابراین
    نیازی به shift(1)/[:-1] نیست و رژیم فقط با بسته‌شدن کندل ۴ساعته عوض
    می‌شود (نه با هر تیک). کش ۲۴۰ ثانیه‌ای هم فقط برای کم‌کردن درخواست
    HTTP است، نه برای پنهان‌کردن flip-flop.

    fail-open: هر خطا/دادهٔ ناکافی/EMA نامعتبر -> (True, ...) تا یک مشکل
    شبکه‌ای باعث توقف کل ربات نشود (همان سیاست گیت دفتر سفارش).
    """
    now = time.time()
    if not force and _BTC_CACHE["info"] and now - _BTC_CACHE["ts"] < BTC_CACHE_SEC:
        return _BTC_CACHE["ok"], _BTC_CACHE["info"]

    info = {"symbol": BTC_SYMBOL, "close": None, "ema": None, "gap_pct": None,
            "ok": True, "fail_open": False, "reason": ""}
    try:
        df = fetch_candles(BTC_SYMBOL, count=max(BTC_EMA_LEN + 60, 260))
        if df is None or len(df) < BTC_EMA_LEN + 5:
            info.update(ok=True, fail_open=True,
                        reason="دادهٔ BTC کافی نبود — فیلتر باز ماند")
        else:
            ema = _ema(df["Close"], BTC_EMA_LEN)
            close = float(df["Close"].iloc[-1])
            ema_v = float(ema.iloc[-1])
            if not (math.isfinite(close) and math.isfinite(ema_v)) or ema_v <= 0:
                info.update(ok=True, fail_open=True,
                            reason="EMA200 نامعتبر — فیلتر باز ماند")
            else:
                info.update(close=close, ema=ema_v,
                            gap_pct=(close / ema_v - 1) * 100,
                            ok=bool(close > ema_v),
                            reason="BTC بالای EMA200" if close > ema_v else "BTC زیر EMA200")
    except Exception as e:
        info.update(ok=True, fail_open=True,
                    reason=f"خطای BTC ({type(e).__name__}) — فیلتر باز ماند")

    _BTC_CACHE.update(ts=now, ok=info["ok"], info=info)
    return info["ok"], info

# =====================================================================
# ۱۲) یک چرخه اسکن
# =====================================================================
def run_cycle():
    STATS["scans"] += 1
    prices, price_age, price_fresh = get_prices()
    # ورود جدید فقط با قیمت تازه مجاز است
    can_enter = bool(prices) and price_fresh and prices_usable(price_age)
    if not can_enter:
        _alert_stale_price(price_age, "چرخهٔ اسکن")
    candles_cache = {}
    partials = {}
    found = 0

    # ۱.۳.۰: رژیم BTC یک‌بار در هر چرخه (کش ۲۴۰ ثانیه‌ای دارد)
    btc_ok, btc_info = (True, {})
    if BTC_FILTER_ON:
        btc_ok, btc_info = btc_regime_ok()
        if not btc_ok:
            log(f"[BTC] رژیم خرسی — ورود جدید مسدود | close {fmt_price(btc_info.get('close'))} "
                f"< EMA{BTC_EMA_LEN} {fmt_price(btc_info.get('ema'))} "
                f"({btc_info.get('gap_pct'):+.2f}%)", "warning")
        elif btc_info.get("fail_open"):
            log(f"[BTC] {btc_info.get('reason')}", "warning")

    # قیمت نداریم؟ چرخه را کامل لغو نمی‌کنیم: بررسی خروج روی کندل‌های بسته
    # باید ادامه پیدا کند. فقط ورود جدید بسته می‌شود. اگر صرافی واقعاً قطع
    # باشد، فیوز سه‌نماد پایین‌تر چرخه را می‌بندد.
    if not prices:
        log("[Scan] قیمت لحظه‌ای نیست -> اسکن فقط روی کندل، ورود جدید مسدود", "warning")

    for idx, symbol in enumerate(SYMBOLS, 1):
        try:
            df, partial = fetch_candles(symbol, keep_partial=True)
            if partial:
                partials[symbol] = partial
            if df is None or len(df) < WARMUP:
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: داده کافی نیست "
                    f"({0 if df is None else len(df)}/{WARMUP})", "warning")
                continue
            candles_cache[symbol] = df

            sig = evaluate(df)
            if not sig.get("triggered"):
                why = sig.get("vol_reject") or sig.get("reason", "")
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: بدون سیگنال | "
                    f"close {fmt_price(sig.get('close'))} vs dc55 {fmt_price(sig.get('dc_hi'))} | "
                    f"vol {sig.get('vol_ratio', 0):.2f}x adx {sig.get('adx', 0):.1f} | {why}")
                continue

            if already_sent(symbol, sig["candle_ts"]):
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: سیگنال این کندل قبلاً ارسال شده")
                continue

            if symbol in STATE["open"]:
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: معامله باز دارد -> سیگنال جدید رد شد")
                continue

            if not can_enter:
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: سیگنال هست ولی قیمت تازه نیست -> ورود رد شد", "warning")
                continue

            # --- فیلتر رژیم BTC ---
            # عمداً mark_sent نمی‌کنیم: اگر BTC وسط همین کندل از EMA200 رد شود،
            # همان سیگنال در اسکن بعدی هنوز قابل ورود است.
            if BTC_FILTER_ON and not btc_ok and symbol != BTC_SYMBOL:
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: سیگنال رد شد — رژیم BTC خرسی "
                    f"(close {fmt_price(btc_info.get('close'))} < EMA{BTC_EMA_LEN})", "warning")
                continue

            lv = build_levels(sig, prices.get(symbol))
            if lv is None:
                continue
            if lv.get("rejected"):
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: سیگنال رد شد — {lv['why']}", "warning")
                mark_sent(symbol, sig["candle_ts"], {"entry": sig["close"]})
                continue

            # --- لایهٔ ۳: دفتر سفارش زنده ---
            # اگر شبکه خطا بدهد گیت fail-open است (سیگنال بلاک نمی‌شود)؛
            # فقط اندازه‌گیری واقعی اسپرد/عمق می‌تواند سیگنال را رد کند.
            ob_raw = fetch_orderbook(symbol)
            if ob_raw:
                ob = orderbook_gate(ob_raw["bids"], ob_raw["asks"], lv["notional"])
            else:
                ob = {"ok": True, "spread_pct": None,
                      "reason": "دفتر سفارش در دسترس نبود — رد نشد"}
            if not ob["ok"]:
                log(f"[{idx}/{len(SYMBOLS)}] {symbol}: سیگنال رد شد — {ob['reason']}", "warning")
                # mark_sent تا این کندل دیگر تلاش/اسپم نشود (ردی که اندازه‌گیری شده)
                if ob.get("spread_pct") is not None:
                    mark_sent(symbol, sig["candle_ts"], {"entry": sig["close"]})
                continue

            send_telegram(format_signal(symbol, sig, lv, ob=ob))
            mark_sent(symbol, sig["candle_ts"], lv)
            with _STATE_LOCK:
                STATE["open"][symbol] = {
                    "symbol": symbol, "entry": lv["entry"], "sl": lv["sl"], "tp": lv["tp"],
                    "qty": lv["qty"], "atr": sig["atr"], "risk_usdt": lv["risk_usdt"],
                    "candle_ts": sig["candle_ts"], "opened_at": int(time.time()),
                    "exit_mode": EXIT_MODE,   # ۱.۳.۰: حالت خروج این پوزیشن
                }
            STATS["signals"] += 1
            found += 1
            log(f"[{idx}/{len(SYMBOLS)}] ★ سیگنال {symbol} | entry {fmt_price(lv['entry'])} "
                f"SL {fmt_price(lv['sl'])} TP {fmt_price(lv['tp'])}", "signal")
            save_state()

        except Exception as e:
            STATS["errors"] += 1
            log(f"[{idx}/{len(SYMBOLS)}] {symbol}: خطا {type(e).__name__}: {e}", "error")

        # اگر چند نماد پشت سر هم داده ندادند، ادامه نده (صرافی قطع است)
        if HTTP_STATE["ok_streak"] == 0 and idx >= 3 and not candles_cache:
            log("[Scan] ۳ نماد اول داده ندادند -> قطعی صرافی، ادامه لغو شد", "warning")
            return {"ok": False, "data_symbols": 0, "signals": found}

    try:
        track_open_positions(candles_cache, partials, prices, price_age, price_fresh)
    except Exception as e:
        log(f"[Track] خطا: {type(e).__name__}: {e}", "error")

    save_state()
    log(f"[Scan] پایان چرخه — {len(SYMBOLS)} نماد، {found} سیگنال جدید، "
        f"{len(STATE['open'])} معامله باز")

    # اگر دادهٔ هیچ نمادی نیامد، یعنی مشکل از صرافی است نه از استراتژی
    return {"ok": len(candles_cache) > 0, "data_symbols": len(candles_cache),
            "signals": found}

# =====================================================================
# ۱۳) Health server (برای Render / Railway / UptimeRobot)
# =====================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        if self.path.startswith(("/health", "/stats", "/")):
            closed = STATE["closed"]
            wins = [c for c in closed if c["r"] > 0]
            payload = {
                "status": "ok",
                "version": VERSION,
                "uptime_sec": int(time.time() - STATS["started"]),
                "scans": STATS["scans"],
                "signals": STATS["signals"],
                "errors": STATS["errors"],
                "timeframe": TIMEFRAME,
                "symbols": len(SYMBOLS),
                "dry_run": DRY_RUN,
                "open_positions": len(STATE["open"]),
                "closed_trades": len(closed),
                "winrate": round(len(wins) / len(closed) * 100, 1) if closed else None,
                "sum_r": round(sum(c["r"] for c in closed), 2) if closed else 0,
                "price_age_sec": (None if not math.isfinite(_price_age())
                                  else round(_price_age(), 1)),
                # ۱.۲.۰: پارامترهای فیلتر حجم، برای اینکه از بیرون معلوم باشد
                # با چه کفی اجرا می‌شود (کف ۲۰۰۰$ چهار نماد را حذف می‌کند).
                "volume_filter": {
                    "min_turnover_usdt": MIN_TURNOVER_USDT,
                    "vol_min": VOL_MIN, "vol_prev_min": VOL_PREV_MIN,
                    "body_min": BODY_MIN, "max_spread_pct": MAX_SPREAD_PCT,
                    "depth_mult": DEPTH_MULT, "orderbook_on": ORDERBOOK_ON,
                },
                # ۱.۳.۰: حالت خروج و وضعیت فیلتر BTC
                "exit_mode": EXIT_MODE,
                "dc_exit_len": DC_EXIT_LEN,
                "btc_filter": {
                    "on": BTC_FILTER_ON, "ema_len": BTC_EMA_LEN,
                    "ok": _BTC_CACHE.get("ok"),
                    "close": (_BTC_CACHE.get("info") or {}).get("close"),
                    "ema": (_BTC_CACHE.get("info") or {}).get("ema"),
                },
                "last_scan_utc": datetime.fromtimestamp(STATS.get("last_scan", time.time()), tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            }
            self._send(200, json.dumps(payload, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_HEAD(self):
        self._send(200, "{}")

    def log_message(self, *a):
        pass

def start_health_server():
    port = _env_int("PORT", 10000)
    try:
        srv = HTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"[Health] روی پورت {port} بالا آمد")
    except Exception as e:
        log(f"[Health] بالا نیامد: {e}", "warning")

# =====================================================================
# ۱۴) حلقه اصلی
# =====================================================================
_STOP = {"flag": False}

def _handle_stop(signum, frame):
    log(f"[Main] سیگنال {signum} -> خروج تمیز")
    _STOP["flag"] = True

# آفست کندل‌های بیت‌پین: ۴ساعته‌ها روی ۰۰:۳۰ UTC بسته می‌شوند (۰۰:۰۰ تهران)،
# نه روی مرزهای ۴ساعتهٔ UTC. اگر این آفست را نادیده بگیریم، ربات ۳۰ دقیقه
# زودتر بیدار می‌شود و کندلِ قبلی را دوباره اسکن می‌کند.
CANDLE_OFFSET = _env_int("CANDLE_OFFSET", 1800)


def seconds_to_next_candle():
    """ثانیه باقی‌مانده تا بسته‌شدن کندل بعدی (با احتساب آفست بیت‌پین + بافر)."""
    now = int(time.time())
    period = PERIOD
    last_close = ((now - CANDLE_OFFSET) // period) * period + CANDLE_OFFSET
    if last_close > now:                 # اگر دقیقاً روی مرز باشیم
        last_close -= period
    return max(0, last_close + period + CANDLE_BUFFER - now)

def price_only_check():
    """بین دو کندل قیمت و کندل در حال تشکیل معاملات باز را چک می‌کند.

    اگر PARTIAL_ON_POLL روشن باشد، برای هر معاملهٔ باز یک درخواست کندل هم
    زده می‌شود (حداکثر ۳ درخواست معمول، ۱۲ در بدترین حالت) و High/Low کندل
    ناتمام هم به‌عنوان تریگر تست می‌شود. این کار نمونه‌گیری نقطه‌ای را به
    پوشش بازه‌ای تبدیل می‌کند: هر لمس بین دو پول، حداکثر PRICE_POLL ثانیه
    دیرتر ولی حتماً دیده می‌شود.
    """
    if not STATE["open"]:
        return
    try:
        prices, age, fresh = get_prices()
        live_ok = bool(prices) and fresh and prices_usable(age)
        if not live_ok:
            _alert_stale_price(age, "بررسی دوره‌ای قیمت")

        cache, partials = {}, {}
        if PARTIAL_ON_POLL:
            for symbol in list(STATE["open"].keys()):
                df, pt = fetch_candles(symbol, keep_partial=True)
                if df is not None:
                    cache[symbol] = df
                if pt:
                    partials[symbol] = pt

        track_open_positions(cache, partials, prices, age, fresh)
    except Exception as e:
        log(f"[Price] خطای بررسی قیمت: {type(e).__name__}: {e}", "warning")

def _sleep(total):
    """خواب قابل‌توقف. اگر معاملهٔ بازی هست، هر PRICE_POLL ثانیه قیمت چک می‌شود.

    هر ۵ ثانیه بیدار می‌شود تا SIGTERM فوراً محترم شمرده شود (نه ۵ دقیقه معطل).
    """
    total = int(total)
    slept = 0
    next_check = PRICE_POLL
    while slept < total and not _STOP["flag"]:
        step = min(5, total - slept)
        time.sleep(max(1, step))
        slept += max(1, step)
        if STATE["open"] and slept >= next_check and not _STOP["flag"]:
            price_only_check()
            next_check += PRICE_POLL

def main():
    log("=" * 66)
    log(f"ربات سیگنال دانچیان ۵۵ | نسخه {VERSION}")
    log(f"تایم‌فریم {TIMEFRAME} | {len(SYMBOLS)} نماد | DRY_RUN={DRY_RUN}")
    log(f"سرمایه فرضی {EQUITY_USDT:g} USDT | ریسک هر معامله {RISK_PCT:g}%")
    log("=" * 66)

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    load_state()
    start_health_server()

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("[TG] توکن تنظیم نشده — سیگنال‌ها فقط در لاگ/کنسول چاپ می‌شوند", "warning")
    else:
        send_telegram(f"🤖 <b>ربات دانچیان ۵۵ روشن شد</b>\n"
                      f"تایم‌فریم: {TIMEFRAME} | نمادها: {len(SYMBOLS)}\n"
                      f"حالت: {'آزمایشی (DRY_RUN)' if DRY_RUN else 'واقعی'}")

    while not _STOP["flag"]:
        HTTP_STATE["hard_fail"] = 0
        result = {"ok": False, "data_symbols": 0, "signals": 0}
        try:
            result = run_cycle() or result
        except Exception as e:
            STATS["errors"] += 1
            log(f"[Main] خطای چرخه: {type(e).__name__}: {e}", "error")
            log(traceback.format_exc()[:800], "error")

        STATS["last_scan"] = int(time.time())

        # ---------- تصمیم خواب ----------
        # ۱) خطای شبکه/۴۰۳/۵۰۳ یا هیچ داده‌ای نیامد -> ۱۵ دقیقه صبر و تلاش مجدد
        if HTTP_STATE["hard_fail"] > 0 or not result.get("ok"):
            sleep_s = RETRY_BACKOFF
            log(f"[Main] صرافی در دسترس نیست ({HTTP_STATE['last_error'] or 'بدون داده'}) "
                f"-> {sleep_s // 60} دقیقه صبر و تلاش مجدد", "warning")
        elif SCAN_MODE == "interval":
            sleep_s = SCAN_INTERVAL
            log(f"[Main] حالت بازه‌ای -> خواب {sleep_s} ثانیه")
        else:
            # ۲) حالت عادی: تا بسته‌شدن کندل بعدی بخواب (نه هر ۵ دقیقه)
            sleep_s = seconds_to_next_candle()
            log(f"[Main] کندل بعدی در {sleep_s // 60} دقیقه و {sleep_s % 60} ثانیه "
                f"-> خواب تا بسته‌شدن کندل")

        _sleep(sleep_s)

    log("[Main] خداحافظ 👋")
    save_state()

if __name__ == "__main__":
    main()
