# -*- coding: utf-8 -*-
import os
import time
import requests
import pandas as pd
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ✅ اضافه شد (برای Retry پایدار)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

# ✅ اضافه شد: سشن پایدار با Retry
SESSION = requests.Session()
_retry = Retry(
    total=3,                # 3 بار تلاش مجدد
    connect=3,
    read=3,
    backoff_factor=0.8,     # فاصله بین تلاش‌ها: 0.8s, 1.6s, 3.2s ...
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
_adapter = HTTPAdapter(max_retries=_retry)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)

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
