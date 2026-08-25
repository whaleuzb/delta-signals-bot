"""Kompaniya aksiyalari (AAPL, TSLA, NVDA ...) — Twelve Data orqali.

Narx manbai forex bilan AYNI: bir xil API, bir xil kalit, bir xil so'rov
chegarasi. Shu sabab bu modul o'z HTTP mijozini ochmaydi — `forex.time_series`
va `forex.price` ni ishlatadi. Farqi ikkitasi:

  1. Tiker API'ga O'ZGARISHSIZ ketadi. Forex tomonida "EURUSD" -> "EUR/USD"
     bo'lib bo'linadi; aksiyada bunday bo'lish 6 harfli tikerni buzardi.
  2. Tiker ro'yxatdan emas, BITTALAB tekshiriladi (pastdagi izohga qarang).

TWELVE_DATA_API_KEY bo'lmasa modul jimgina o'chadi: `resolve()` doim None
qaytaradi, kripto va forex ishlashda davom etadi.
"""
import logging
import time

import forex

log = logging.getLogger(__name__)

Candle = forex.Candle

# Tiker BITTALAB tekshiriladi, ro'yxat yuklab olinmaydi.
#
# Avval `/stocks?country=United States` chaqirilardi — javob bir necha
# megabayt bo'lgani uchun 15 soniyalik chegaraga sig'may `ReadTimeout` bilan
# uzilardi. Natijada ro'yxat DOIM bo'sh qolar, har bir tiker esa o'sha 15
# soniyani kutib "qotib qolgandek" ko'rinardi.
#
# Endi `/price?symbol=TSLA` so'raladi: javob bir necha bayt va u bir yo'la
# ikki savolga javob beradi — tiker bormi VA shu rejada narx keladimi.
# Ikkinchisi muhim: narx kelmasa signal qabul qilinib, keyin PENDING'da
# qotib qolardi.
_OK_TTL = 86_400     # topilgan tiker — bir kun
_FAIL_TTL = 3_600    # topilmagani — bir soat (ro'yxat o'zgarishi mumkin)
_cache: dict[str, tuple[float, bool]] = {}


def enabled() -> bool:
    return forex.enabled()


def normalize(raw: str) -> str:
    """"tsla", "$TSLA", "NASDAQ:TSLA" -> "TSLA".

    Nuqta saqlanadi: ba'zi tikerlarda u sinf belgisi (BRK.B)."""
    s = raw.upper().strip()
    if ":" in s:                       # "NASDAQ:TSLA" — birja prefiksi
        s = s.rsplit(":", 1)[1]
    return "".join(ch for ch in s if ch.isalpha() or ch == ".")


async def _probe(symbol: str) -> bool:
    hit = _cache.get(symbol)
    if hit:
        ok = hit[1]
        if time.time() - hit[0] < (_OK_TTL if ok else _FAIL_TTL):
            return ok
    try:
        ok = await forex.price(symbol, fresh=True) is not None
    except Exception:
        log.warning("Aksiya tekshiruvi bajarilmadi: %s", symbol, exc_info=True)
        return False                   # keshlamaymiz: tarmoq xatosi vaqtinchalik
    _cache[symbol] = (time.time(), ok)
    return ok


async def resolve(raw: str) -> str | None:
    if not enabled():
        return None
    s = normalize(raw)
    # AQSh tikerlari 1-5 belgi (nuqtali sinf bilan 6). Bu chegara "SIGNAL",
    # "ENTRY" kabi tasodifiy so'zlar uchun tarmoqqa chiqmaslik uchun ham.
    if not s or len(s) > 6:
        return None
    return s if await _probe(s) else None


async def klines(symbol: str, start_ms: int, limit: int = 500,
                  tf: str = "1m", end_ms: int | None = None) -> list[Candle]:
    """Shamlar. Tiker o'zgarishsiz uzatiladi.

    Bozor yopiq bo'lsa (kechasi, dam olish kunlari, bayram) Twelve Data yangi
    sham bermaydi — `time_series` bo'sh ro'yxat qaytaradi va kuzatuv keyingi
    ochilishda o'z ishini davom ettiradi. Bu forexdagi dam olish kunlari bilan
    bir xil holat, alohida ishlov talab qilmaydi."""
    return await forex.time_series(symbol, start_ms, limit, tf, end_ms)


async def last_price(symbol: str, fresh: bool = False) -> float | None:
    return await forex.price(symbol, fresh)


async def close() -> None:
    """HTTP mijoz forex moduliniki — u yerda yopiladi."""
    return None
