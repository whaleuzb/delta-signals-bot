"""Twelve Data — forex juftliklari (va oltin/kumush kabi metallar) uchun narx manbai.

API kalit talab qiladi (bepul reja: kuniga 800, daqiqasiga 8 so'rov — bir nechta
ochiq forex signal bo'lsa, POLL_SECONDS bilan birga bu limitga tez yetish mumkin).
TWELVE_DATA_API_KEY bo'sh bo'lsa forex butunlay o'chadi — resolve() doim None
qaytaradi, kripto (exchange.py) ishlashda davom etadi, hech narsa buzilmaydi.
"""
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import config

log = logging.getLogger(__name__)
_client = httpx.AsyncClient(base_url="https://api.twelvedata.com", timeout=15)

_symbols: set[str] = set()
_symbols_ts: float = 0.0


@dataclass
class Candle:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    close_ms: int
    volume: float = 0.0


def enabled() -> bool:
    return bool(config.TWELVE_DATA_API_KEY)


async def valid_symbols() -> set[str]:
    """/forex_pairs ro'yxati 1 soatga keshlanadi. "EUR/USD" -> "EURUSD" holida saqlanadi."""
    global _symbols, _symbols_ts
    if _symbols and time.time() - _symbols_ts < 3600:
        return _symbols
    r = await _client.get("/forex_pairs", params={"apikey": config.TWELVE_DATA_API_KEY})
    r.raise_for_status()
    data = r.json().get("data", [])
    _symbols = {p["symbol"].replace("/", "") for p in data}
    _symbols_ts = time.time()
    return _symbols


def normalize(raw: str) -> str:
    s = raw.upper().strip()
    for ch in ("/", "-", ":", "_", " ", "\t", " "):
        s = s.replace(ch, "")
    return s


# Metallar. Twelve Data'ning /forex_pairs ro'yxati ularni HAR DOIM
# qaytaravermaydi (aynan shu sabab XAUUSD "topilmadi" bo'lardi), lekin
# /time_series va /price "XAU/USD" ni bemalol qabul qiladi. Shuning uchun
# metallar ro'yxatdan tashqari, ALOHIDA tekshiriladi.
_METALS = {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "XAUEUR", "XAGEUR"}

# Neft — xuddi metallar kabi /forex_pairs ro'yxatida YO'Q, lekin Twelve
# Data /time_series va /price "WTI/USD"/"BRENT/USD" shaklini qabul qiladi.
# Foydalanuvchi so'radi: "neft bilan bog'liq aktivlar kiritilmaganmi?" —
# neft KOMPANIYALARI (XOM, CVX kabi aksiyalar) allaqachon `stocks.py`
# orqali avtomatik ishlaydi (istalgan tiker probe qilinadi); bu yerda
# xom neftning O'ZI (tovar narxi) qo'shiladi. Aniq xarita kerak — "BRENTUSD"
# 8 harfli, `_api_symbol()`ning standart 3+3 bo'lish mantig'i uni
# "BRE/NTUSD" deb noto'g'ri bo'lardi.
_OIL_API_SYMBOLS = {"WTIUSD": "WTI/USD", "BRENTUSD": "BRENT/USD"}
_OIL = set(_OIL_API_SYMBOLS)

# Probe natijasi: {symbol: (vaqt, bor_yoki_yo'q)}. Ro'yxatda yo'q metall/neft
# haqiqatan narx berishini BIR MARTA tekshiramiz va javobni 1 soat saqlaymiz.
# Bu muhim: shunchaki "ro'yxatga qo'shib qo'yish" signalni qabul qilib,
# keyin narx kelmasdan uni PENDING'da qotirib qo'yardi.
_probe_cache: dict[str, tuple[float, bool]] = {}
_PROBE_TTL = 3600.0


async def _probe(symbol: str) -> bool:
    hit = _probe_cache.get(symbol)
    if hit and (time.time() - hit[0]) < _PROBE_TTL:
        return hit[1]
    try:
        ok = await price(_api_symbol(symbol), fresh=True) is not None
    except Exception:
        log.warning("Metall/neft tekshiruvi bajarilmadi: %s", symbol, exc_info=True)
        ok = False
    _probe_cache[symbol] = (time.time(), ok)
    return ok


async def resolve(raw: str) -> str | None:
    if not enabled():
        return None
    s = normalize(raw)
    if s in await valid_symbols():
        return s
    if s in _METALS or s in _OIL:
        return s if await _probe(s) else None
    # Kvota valyutasisiz ("XAU", "BRENT", "WTI") — MarketTwits kabi
    # manbalardagi hashtaglar odatda shu qisqa shaklda keladi ("#BRENT",
    # "#XAUUSD" emas). USD qo'shib qayta tekshiriladi.
    su = s + "USD"
    if su in _METALS or su in _OIL:
        return su if await _probe(su) else None
    return None


def _api_symbol(symbol: str) -> str:
    """EURUSD -> EUR/USD — Twelve Data shu shaklni talab qiladi.
    Neft kabi 6 harf bo'lmagan belgilar (`BRENTUSD`) aniq xaritadan olinadi."""
    if symbol in _OIL_API_SYMBOLS:
        return _OIL_API_SYMBOLS[symbol]
    return f"{symbol[:3]}/{symbol[3:]}" if len(symbol) == 6 else symbol


# Ichki timeframe kodi -> Twelve Data interval nomi.
_INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
              "1h": "1h", "4h": "4h", "1d": "1day"}
_TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


async def klines(symbol: str, start_ms: int, limit: int = 500,
                  tf: str = "1m", end_ms: int | None = None) -> list[Candle]:
    """Shamlar. Standart 1m — KUZATUV (tracker.py) aynan shuni ishlatadi.
    tf faqat grafik ko'rsatish uchun (exchange.klines bilan bir xil shart).

    end_ms — oynaning oxiri (grafik uchun). exchange.klines bilan bir xil
    imzo bo'lishi shart: chart._fetch ikkalasini ham bir xil chaqiradi."""
    return await time_series(_api_symbol(symbol), start_ms, limit, tf, end_ms)


async def time_series(api_symbol: str, start_ms: int, limit: int = 500,
                       tf: str = "1m", end_ms: int | None = None) -> list[Candle]:
    """Twelve Data /time_series — forex va AKSIYALAR uchun umumiy.

    `api_symbol` allaqachon API kutgan shaklda ("EUR/USD" yoki "AAPL"):
    juftlikka bo'lish forex tomonida, aksiyada esa tiker o'zgarishsiz ketadi
    (aks holda 6 harfli tiker "ABC/DEF" bo'lib buzilardi)."""
    symbol = api_symbol
    interval = _INTERVALS.get(tf, "1min")
    dur = _TF_MS.get(tf, 60_000)
    start = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    params = {
        "symbol": symbol, "interval": interval, "outputsize": limit,
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"), "order": "ASC",
        "timezone": "UTC", "apikey": config.TWELVE_DATA_API_KEY,
    }
    if end_ms is not None:
        end = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
        params["end_date"] = end.strftime("%Y-%m-%d %H:%M:%S")
    r = await _client.get("/time_series", params=params)
    if r.status_code == 429:
        log.warning("Twelve Data rate limit — kutamiz")
        return []
    data = r.json()
    if not isinstance(data, dict) or data.get("status") == "error":
        # Bozor yopiq (dam olish kuni) yoki boshqa xato bo'lsa ham shu yo'l bilan
        # keladi — bo'sh ro'yxat qaytarish yetarli, tracker keyingi safar davom etadi.
        if isinstance(data, dict) and data.get("code") not in (400, 404):
            log.warning("Twelve Data xato: %s", data.get("message"))
        return []
    out = []
    for row in data.get("values", []):
        raw = row["datetime"]
        # Kunlik shamlarda Twelve Data faqat sanani qaytaradi ("2026-08-24").
        fmt = "%Y-%m-%d %H:%M:%S" if len(raw) > 10 else "%Y-%m-%d"
        ts = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        open_ms = int(ts.timestamp() * 1000)
        if open_ms < start_ms:
            continue
        # "volume" — aksiyada odatda bor, forexda ko'pincha yo'q/0 (markazlashtirilmagan
        # bozor — yagona "hajm" tushunchasi yo'q). Yo'q bo'lsa 0 — Anchored Volume
        # Profile shunda chizilmaydi (pastga qarang), boshqa hech narsa buzilmaydi.
        vol_raw = row.get("volume")
        volume = float(vol_raw) if vol_raw not in (None, "") else 0.0
        out.append(Candle(open_ms, float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"]), open_ms + dur - 1,
                           volume))
    out.sort(key=lambda c: c.open_ms)
    return out


_PRICE_TTL = 5.0
_price_cache: dict[str, tuple[float, float]] = {}


async def last_price(symbol: str, fresh: bool = False) -> float | None:
    """exchange.last_price() bilan bir xil qisqa muddatli kesh — bu yerda undan
    ham muhimroq, chunki Twelve Data bepul rejasi DAQIQASIGA 8 so'rov beradi:
    keshsiz bitta /stats bosilishi limitni yeb qo'yishi va forex signallari
    kuzatuvini to'xtatishi mumkin."""
    return await price(_api_symbol(symbol), fresh)


async def price(api_symbol: str, fresh: bool = False) -> float | None:
    """Twelve Data /price — forex va aksiyalar uchun umumiy (kesh ham bitta)."""
    symbol = api_symbol
    if not fresh:
        hit = _price_cache.get(symbol)
        if hit and (time.monotonic() - hit[0]) < _PRICE_TTL:
            return hit[1]
    r = await _client.get("/price", params={
        "symbol": symbol, "apikey": config.TWELVE_DATA_API_KEY})
    if r.status_code != 200:
        return None
    data = r.json()
    if "price" not in data:
        return None
    price = float(data["price"])
    _price_cache[symbol] = (time.monotonic(), price)
    return price


async def close() -> None:
    await _client.aclose()
