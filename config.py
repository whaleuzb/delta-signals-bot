"""Barcha sozlamalar shu yerda. Railway Variables orqali beriladi."""
import os


def _ids(raw: str) -> set[int]:
    return {int(x.strip()) for x in raw.split(",") if x.strip()}


# --- Majburiy ---
# BOT_TOKEN ataylab os.getenv: veb servis (web.py) ham shu config'ni yuklaydi,
# lekin Telegram'ga umuman murojaat qilmaydi — unga token kerak emas va soxta
# qiymat berib qo'yish ham to'g'ri emas. Token bot ishga tushayotganda
# tekshiriladi (bot.main), ya'ni bot baribir tokensiz ishga tushmaydi.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.environ["DATABASE_URL"]

# --- Kim signal qo'sha oladi ---
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", "1101182189"))

# --- Claude vision (caption yozilmagan rasmlarni o'qish uchun). Bo'sh bo'lsa o'chadi ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Grafik o'qish uchun eng kuchli model ishlatiladi: bu yerda xato qilish
# narxi baland (noto'g'ri daraja = noto'g'ri signal), rasm esa kuniga
# bir necha marta o'qiladi — farq pul jihatidan sezilmaydi.
VISION_MODEL = os.getenv("VISION_MODEL", "claude-opus-5")

# --- Narx manbasi: MEXC Spot (Binance Futures AQSH IP'larini 451 bilan bloklagani uchun
#     almashtirildi; MEXC'da kichik altcoinlar ham ko'proq bor) ---
EXCHANGE_BASE = os.getenv("EXCHANGE_BASE", "https://api.mexc.com")
QUOTE = "USDT"

# --- Forex (Twelve Data). Bo'sh bo'lsa forex signal kiritish o'chadi, kripto
#     (yuqoridagi MEXC) ta'sirlanmaydi ---
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

# --- Kuzatuv ---
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "45"))
EXPIRE_DAYS = int(os.getenv("EXPIRE_DAYS", "7"))  # entryga tegmagan signal shuncha kundan keyin bekor

# --- Savdo qoidalari (SPOT) ---
ALLOW_SHORT = os.getenv("ALLOW_SHORT", "false").lower() == "true"
# Har bir TP'da pozitsiyaning qancha qismi sotiladi. TP soni kamroq bo'lsa avtomatik normallashadi.
TP_ALLOCATION = [0.5, 0.3, 0.2]
# TP1'dan keyin stop entry darajasiga ko'chirilsinmi
MOVE_SL_TO_BE_AFTER_TP1 = os.getenv("MOVE_SL_TO_BE", "true").lower() == "true"
# Bitta shamda ham TP ham SL teksa: konservativ = SL birinchi hisoblanadi
CONSERVATIVE_SAME_CANDLE = True

TZ = os.getenv("TZ", "Asia/Tashkent")

# /yordam bo'limidagi "to'liq qo'llanma" havolasi — Telegraph maqolasi.
# Telegraph tanlandi, chunki u Telegram ichida darhol ochiladi va LOGIN
# TALAB QILMAYDI (oddiy veb-sahifa foydalanuvchidan login so'rab to'siq
# bo'lgan edi). guide.py + publish_guide.py bilan qayta chop etiladi.
# Bo'sh qilinsa tugma ko'rsatilmaydi (bot ichidagi yo'riqnoma baribir to'liq).
# Ochiq natijalar sahifasi (web.py alohida servisda ishlaydi). Bo'sh bo'lsa
# botdagi "Ochiq sahifa" tugmasi umuman ko'rsatilmaydi — ya'ni veb servis
# o'chirilgan bo'lsa ham bot hech narsani buzmasdan ishlayveradi.
WEB_URL = os.getenv("WEB_URL", "https://web-production-addc3.up.railway.app").rstrip("/")

GUIDE_URL = os.getenv(
    "GUIDE_URL",
    "https://telegra.ph/Trade-Controller--guruh-ulash-va-signal-kiritish-08-21")

# --- To'lovli kirish (guruh egasi o'z guruhiga obuna sotadi) ---
# Platforma komissiyasi, foizda. Telegram Stars BOT EGASINING hisobiga
# tushadi, ya'ni pulni guruh egasiga qo'lda o'tkazish kerak — bu foiz shu
# hisob-kitobda ishlatiladi va har bir to'lov yozuvida muzlatiladi.
PLATFORM_FEE_PCT = float(os.getenv("PLATFORM_FEE_PCT", "10"))
# Telegram Stars invoysi uchun chegaralar (Bot API talabi: 1..2500 ⭐ oralig'i
# obuna havolalari uchun; oddiy invoysda yuqori chegara yo'q, lekin real
# narxlar shu oraliqda bo'ladi — bu yerda faqat aql bovar qilmaydigan
# qiymatlardan himoya).
MIN_PRICE_STARS = 1
MAX_PRICE_STARS = 100_000
# Muddati tugaydigan obunachiga necha kun oldin eslatiladi.
SUB_REMIND_DAYS = int(os.getenv("SUB_REMIND_DAYS", "3"))
