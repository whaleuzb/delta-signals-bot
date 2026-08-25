"""Kompaniya aksiyalari (AAPL, TSLA, NVDA ...) — Twelve Data orqali.

Narx manbai forex bilan AYNI: bir xil API, bir xil kalit, bir xil so'rov
chegarasi. Shu sabab bu modul o'z HTTP mijozini ochmaydi — `forex.time_series`
va `forex.price` ni ishlatadi. Farqi ikkitasi:

  1. Tiker API'ga O'ZGARISHSIZ ketadi. Forex tomonida "EURUSD" -> "EUR/USD"
     bo'lib bo'linadi; aksiyada bunday bo'lish 6 harfli tikerni buzardi.
  2. Ro'yxat boshqa manbadan — `/stocks` (AQSh birjalari).

TWELVE_DATA_API_KEY bo'lmasa modul jimgina o'chadi: `resolve()` doim None
qaytaradi, kripto va forex ishlashda davom etadi.
"""
import logging
import time

import config
import forex

log = logging.getLogger(__name__)

Candle = forex.Candle

# Tikerlar ro'yxati kuniga bir marta olinadi: u kamdan-kam o'zgaradi, javob
# esa katta (AQSh bo'yicha bir necha ming qator). Soatiga bir marta tortish
# bepul rejadagi kunlik so'rov chegarasini behuda yeb qo'yardi.
_TTL = 86_400
_symbols: set[str] = set()
_symbols_ts: float = 0.0

# Faqat asosiy AQSh birjalari. Boshqa mamlakat birjalarida bir xil tiker
# butunlay boshqa kompaniyani bildirishi mumkin (masalan "AAPL" Meksikada) —
# foydalanuvchi "AAPL" deb yozganda aynan NASDAQ'dagisi tushunilsin.
_EXCHANGES = {"NASDAQ", "NYSE", "NYSE ARCA", "NYSE AMERICAN", "AMEX", "BATS"}


def enabled() -> bool:
    return forex.enabled()


async def valid_symbols() -> set[str]:
    """AQSh aksiyalari tikerlari. Xato bo'lsa — bo'sh to'plam va ogohlantirish:
    aksiya vaqtincha topilmaydi, lekin kripto/forex buzilmaydi."""
    global _symbols, _symbols_ts
    if _symbols and time.time() - _symbols_ts < _TTL:
        return _symbols
    try:
        r = await forex._client.get("/stocks", params={
            "country": "United States", "apikey": config.TWELVE_DATA_API_KEY})
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception:
        log.warning("Aksiyalar ro'yxati olinmadi", exc_info=True)
        return _symbols          # eski kesh bo'lsa — o'shanda ishlaymiz
    found = {
        s["symbol"].upper() for s in data
        if str(s.get("exchange", "")).upper() in _EXCHANGES
        and s.get("symbol")
    }
    if found:
        _symbols, _symbols_ts = found, time.time()
    return _symbols


def normalize(raw: str) -> str:
    """"tsla", "$TSLA", "NASDAQ:TSLA" -> "TSLA".

    Nuqta saqlanadi: ba'zi tikerlarda u sinf belgisi (BRK.B)."""
    s = raw.upper().strip()
    if ":" in s:                       # "NASDAQ:TSLA" — birja prefiksi
        s = s.rsplit(":", 1)[1]
    return "".join(ch for ch in s if ch.isalpha() or ch == ".")


async def resolve(raw: str) -> str | None:
    if not enabled():
        return None
    s = normalize(raw)
    # Bo'sh yoki juda uzun bo'lsa umuman so'ramaymiz: AQSh tikerlari 1-5 belgi
    # (nuqtali sinf bilan 6). Bu, ayniqsa, "SIGNAL", "ENTRY" kabi tasodifiy
    # so'zlarni ro'yxatda qidirmaslik uchun.
    if not s or len(s) > 6:
        return None
    return s if s in await valid_symbols() else None


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
