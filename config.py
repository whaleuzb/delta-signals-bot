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

# --- News Trade AI: bozorni qimirlatadigan yangiliklarni avtomatik topib,
#     grafik bilan alohida kanalga joylaydigan funksiya. NEWS_CHANNEL_ID
#     bo'sh bo'lsa butun funksiya o'chiq (news_scan_job hech narsa qilmaydi) ---
NEWS_CHANNEL_ID = os.getenv("NEWS_CHANNEL_ID", "")
# Matn-yangilikni tahlil qilish (tarjima/xulosa/filtr) uchun model — rasm
# emas, shuning uchun VISION_MODEL'dan alohida (kelajakda arzonroq modelga
# almashtirish mumkin bo'lishi uchun).
NEWS_MODEL = os.getenv("NEWS_MODEL", "claude-opus-5")
# Jonli yangilanish: har necha soniyada narx qayta tekshiriladi va bir
# nechta hodisa parallel bo'lganda barchasi uchun umumiy minimal oraliq
# (Telegram "flood control"ga urilmaslik uchun — bot.py'dagi _live_update
# shu ikkalasidan kattasini ishlatadi).
NEWS_REFRESH_SECONDS = int(os.getenv("NEWS_REFRESH_SECONDS", "4"))
NEWS_MIN_EDIT_GAP = float(os.getenv("NEWS_MIN_EDIT_GAP", "3"))
# Postdan keyin necha daqiqa jonli yangilanadi — bundan keyin narx harakati
# odatda tinchiydi, xabar oddiy statik holatda qoladi.
NEWS_LIVE_MINUTES = int(os.getenv("NEWS_LIVE_MINUTES", "20"))

# --- Iqtisodiy taqvim: har kuni belgilangan mahalliy soatda AQSH makro
#     yangiliklari ro'yxati + hodisadan oldin eslatma. Xuddi News Trade AI
#     kabi NEWS_CHANNEL_ID kanaliga postlanadi (alohida kanal kerak emas) ---
ECON_DIGEST_HOUR = int(os.getenv("ECON_DIGEST_HOUR", "12"))    # mahalliy vaqt (TZ)
ECON_REMIND_MINUTES = int(os.getenv("ECON_REMIND_MINUTES", "15"))
# Natija (actual) e'lon qilingach, BTC'ga ta'sirini tasvirlab post qilish —
# faqat shu daqiqalar ICHIDA chiqqan natijalar ko'rib chiqiladi (funksiya
# birinchi marta ishga tushganda haftaning ESKI natijalarini birdaniga
# postlab tashlamasligi uchun).
ECON_RESULT_LOOKBACK_MINUTES = int(os.getenv("ECON_RESULT_LOOKBACK_MINUTES", "180"))

# --- Hajm portlashi (volume surge): uzoq pasaygan, keyin savdo hajmi
#     keskin oshgan tangalarni topib, CryptoPanic'dan sababini qidiradi ---
# CryptoPanic — tanga bo'yicha yangilik qidirish. Bo'sh bo'lsa qidiruv
# o'chadi, lekin portlash SIGNALI o'zi baribir postlanadi (sababsiz).
CRYPTOPANIC_TOKEN = os.getenv("CRYPTOPANIC_TOKEN", "")
# Oxirgi hajm bazaviy o'rtachadan necha marta katta bo'lsa "portlash".
# 3 -> 2.2: foydalanuvchi "kanalda ko'proq xabar kelishi" so'ragach
# yumshatildi — ko'proq signal, ozroq "kuchlilik" kafolati (tabiiy savdo).
SURGE_VOLUME_MULTIPLIER = float(os.getenv("SURGE_VOLUME_MULTIPLIER", "2.2"))
# Oxirgi 24 soatlik hajm (USDT) shundan KICHIK tangalar butunlay chetlab
# o'tiladi — foydalanuvchi: "kapitallashuvi juda past va yaroqsiz" tangalar
# kelayotganini topib, mutlaq hajm chegarasi qo'yishni so'radi (bozor
# kapitallashuvi ma'lumoti bepul/ishonchli manbada yo'q, lekin 24s savdo
# hajmi — likvidlik va "yaroqlilik"ning to'g'ridan-to'g'ri o'lchovi —
# ALLAQACHON bazada bor, `volume_snapshots`). Bu chegara PORTLASH VA kit
# (whale) kuzatuvining IKKALASIGA ham ta'sir qiladi — kit kuzatuvi faqat
# portlash nomzodlarida ishlaydi (#116).
SURGE_MIN_VOLUME_USD = float(os.getenv("SURGE_MIN_VOLUME_USD", "10000000"))
# Bazaviy o'rtacha shu soatdan OLDINGI yozuvlardan hisoblanadi (oxirgi
# hajmning o'zi bazaga aralashib ketmasin).
SURGE_BASELINE_EXCLUDE_HOURS = float(os.getenv("SURGE_BASELINE_EXCLUDE_HOURS", "12"))
# Uzoq muddatli pasayish tasdig'i: shuncha kun ichida kamida shuncha % pasaygan
# bo'lishi kerak (aks holda "portlash" oddiy davom etayotgan o'sish bo'lishi mumkin).
# 25 -> 15: xuddi shu sabab bilan yumshatildi.
SURGE_DECLINE_DAYS = int(os.getenv("SURGE_DECLINE_DAYS", "30"))
SURGE_DECLINE_PCT = float(os.getenv("SURGE_DECLINE_PCT", "15"))
# Hajm suratga olish — har necha soatda (bazaga yozib borish). Bitta
# YAGONA bulk so'rov (barcha juftliklar birdaniga) bo'lgani uchun
# tez-tez chaqirish tezlik chegarasiga xavf solmaydi — 4 -> 1 -> 0.25 (15
# daqiqa): foydalanuvchi "portlash kech aniqlanyapti, kech kelgan xabar
# hech kimga foyda bermaydi" deb ikkinchi marta topgach yana qisqartirildi.
# `surge_scan_job`ning tsikli ham shu bilan MOS ravishda qisqartirildi
# (pastdagi `SURGE_SCAN_SECONDS`) — ikkalasi birga eng yomon holatda
# ~20 daqiqagacha kechikish beradi (avvalgi ~4.5 soat -> ~1.5 soat -> endi
# ~20 daqiqa).
SURGE_SNAPSHOT_HOURS = float(os.getenv("SURGE_SNAPSHOT_HOURS", "0.25"))
SURGE_SCAN_SECONDS = int(os.getenv("SURGE_SCAN_SECONDS", "300"))

# --- Kit (whale) faolligi: FAQAT portlash nomzodlarida (foydalanuvchi
#     qarori — butun bozorni HAR individual savdo darajasida kuzatish
#     MEXC tezlik chegarasiga zarba beradi, portlash nomzodlari esa
#     odatda bir vaqtda bittа-ikkitа bo'ladi) — so'nggi WHALE_WINDOW_
#     MINUTES ichida xarid YOKI sotuv hajmi 24 soatlik hajmning
#     WHALE_MIN_PCT foizidan oshsa, alohida xabar (grafiksiz) ---
WHALE_MIN_PCT = float(os.getenv("WHALE_MIN_PCT", "10"))
WHALE_WINDOW_MINUTES = int(os.getenv("WHALE_WINDOW_MINUTES", "15"))
WHALE_SCAN_SECONDS = int(os.getenv("WHALE_SCAN_SECONDS", "120"))

# --- Yangi tanga listing e'lonlari: Koreys birjalari (Upbit) — kalitsiz,
#     bepul, manzili listings.py'da (DISCLOSURE_URL). Bithumb HALI
#     QO'SHILMAGAN — rasmiy notices manzili sandbox tarmog'ida
#     tasdiqlanmadi (apidocs.bithumb.com bloklangan edi), keyinroq
#     production loglaridan aniqlab qo'shiladi ---

# --- Yirik likvidatsiyalar: Coinalyze (bepul, lekin coinalyze.net'da
#     ro'yxatdan o'tib olinadigan kalit kerak). Bo'sh bo'lsa funksiya
#     jimgina o'chadi — boshqa hech narsa ta'sirlanmaydi ---
COINALYZE_API_KEY = os.getenv("COINALYZE_API_KEY", "")
# Kuzatiladigan instrumentlar — Coinalyze'ning o'z belgilash uslubi
# (BINANCE bozori, ".A" — Coinalyze'dagi Binance kodi). Faqat top-5 emas,
# kengroq ro'yxat — foydalanuvchi kichikroq tangalardagi (masalan PUMP)
# yirik likvidatsiyalarni ham ko'rishni so'radi. Coinalyze bitta so'rovda
# 20 tagacha instrumentni qabul qiladi.
LIQUIDATION_SYMBOLS = os.getenv(
    "LIQUIDATION_SYMBOLS",
    "BTCUSDT_PERP.A,ETHUSDT_PERP.A,SOLUSDT_PERP.A,BNBUSDT_PERP.A,XRPUSDT_PERP.A,"
    "DOGEUSDT_PERP.A,ADAUSDT_PERP.A,AVAXUSDT_PERP.A,LINKUSDT_PERP.A,LTCUSDT_PERP.A,"
    "TRXUSDT_PERP.A,DOTUSDT_PERP.A,SUIUSDT_PERP.A,APTUSDT_PERP.A,ARBUSDT_PERP.A,"
    "OPUSDT_PERP.A,NEARUSDT_PERP.A,INJUSDT_PERP.A,WIFUSDT_PERP.A,PUMPUSDT_PERP.A",
).split(",")
# Oxirgi 5-daqiqalik ustunda (long yoki short tomonning biri) qancha
# dollardan katta bo'lsa post qilinadi — foydalanuvchi "faqat 500.000$dan
# katta likvidatsiyalar" so'radi (avvalgi o'rtachaga nisbatan ko'plik
# mezoni chalkash edi, endi oddiy chegara).
LIQUIDATION_MIN_USD = float(os.getenv("LIQUIDATION_MIN_USD", "500000"))

# --- MarketTwits (va shunga o'xshash) Telegram kanallari — Telethon
#     userbot orqali (oddiy Bot API bunday begona kanallarni "eshita"
#     olmaydi, faqat o'zi ADMIN qilingan kanallarni). my.telegram.org'da
#     ro'yxatdan o'tib olinadigan api_id/api_hash kerak; ikkalasi ham
#     bo'sh bo'lsa funksiya butunlay o'chiq. Login (bir martalik, telefon
#     kodi bilan) tgsource.py orqali admin buyruqlari bilan (/tg_login
#     /tg_code /tg_password) amalga oshiriladi, sessiya keyin Postgres'da
#     saqlanadi (fayl emas — Railway konteyneri qayta ishga tushganda
#     fayl yo'qoladi).
TELETHON_API_ID = int(os.getenv("TELETHON_API_ID", "0") or "0")
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "")
TELEGRAM_NEWS_CHANNELS = [
    c.strip() for c in os.getenv("TELEGRAM_NEWS_CHANNELS", "markettwits").split(",") if c.strip()
]

# `translate.py` (MyMemory) — kalitsiz so'rov tez-tez 429 (juda ko'p
# so'rov) bilan rad etilardi (production loglarida tasdiqlangan). MyMemory
# hujjatiga ko'ra so'rovga ISTALGAN email qo'shilsa (tasdiqlanishi shart
# EMAS) kunlik limit ~50,000 so'zgacha ko'tariladi. Shaxsiy email emas —
# faqat shu loyiha uchun umumiy/tasodifiy manzil.
TRANSLATE_EMAIL = os.getenv("TRANSLATE_EMAIL", "newstradeai.bot@tradecontroller.app")

# --- MACD kesishmasi skaneri (foydalanuvchi so'rovi — Bulltard.com
#     kanali namunasi: "$CATI/USDT (1d) MACD Bearish crossover") ---
#     Top hajmli juftliklar bo'yicha 4h va 1d shamlarida MACD(12,26,9)
#     kesishmasi topilsa, grafik bilan NEWS_CHANNEL_ID kanaliga post.
#     NEWS_CHANNEL_ID bo'sh bo'lsa butun funksiya o'chiq (boshqa
#     skanerlar bilan bir xil qoida).
#
#     MUHIM — TEZLIK CHEGARASI: skaner har chaqirilganda YUZLAB juftlikni
#     so'ramaydi. 4h shami har 4 soatda, 1d shami kuniga bir marta
#     YOPILADI — yopilmagan sham uchun qayta skanerlashning ma'nosi yo'q.
#     Shu sabab job tez-tez (MACD_SCAN_SECONDS) uyg'onadi, lekin haqiqiy
#     so'rovlarni FAQAT yangi sham yopilgan bo'lsa yuboradi (oxirgi
#     skanerlangan sham chegarasi `bot_settings`da saqlanadi).
MACD_TIMEFRAMES = [t.strip() for t in
                    os.getenv("MACD_TIMEFRAMES", "4h,1d").split(",") if t.strip()]
MACD_SCAN_SECONDS = int(os.getenv("MACD_SCAN_SECONDS", "300"))
# Foydalanuvchi qarori: "Top 500 ta" — ya'ni tanlovni CHEGARA emas, HAJM
# REYTINGI hal qiladi. Avval $10M chegarasi qo'yilgan edi, jonli logda
# undan ATIGI 12 ta juftlik o'tgani ko'rindi (SKHYB kabi o'rta tangalar
# butunlay tushib qolardi). Chegara endi faqat mutlaqo o'lik juftliklarni
# (savdo deyarli yo'q -> sham ma'lumoti ishonchsiz, MACD ma'nosiz)
# chetlab o'tish uchun past qiymatda qoldirildi.
MACD_MIN_VOLUME_USD = float(os.getenv("MACD_MIN_VOLUME_USD", "100000"))
# Eng ko'p nechta juftlik skanerlanadi (hajm bo'yicha yuqoridan).
MACD_MAX_SYMBOLS = int(os.getenv("MACD_MAX_SYMBOLS", "500"))
# Bir vaqtda nechta klines so'rovi (sekin, lekin xavfsiz).
MACD_CONCURRENCY = int(os.getenv("MACD_CONCURRENCY", "5"))
# Grafikda ko'rsatiladigan sham soni (MACD 26+9 shamdan keyin ishonchli
# bo'lgani uchun kamida 60 kerak).
MACD_CANDLES = int(os.getenv("MACD_CANDLES", "120"))
# TRUE bo'lsa faqat "super" (trend yo'nalishi bo'yicha, kuchli
# gistogramma) kesishmalar postlanadi — xabar sonini keskin kamaytiradi.
MACD_ONLY_STRONG = os.getenv("MACD_ONLY_STRONG", "0") == "1"
# Kanalga ketma-ket xabarlar orasidagi oraliq (soniya) — Telegram bitta
# kanalga daqiqasiga ~20 ta xabarni o'tkazadi. 3.5s ~ daqiqasiga 17 ta.
MACD_POST_DELAY = float(os.getenv("MACD_POST_DELAY", "3.5"))
