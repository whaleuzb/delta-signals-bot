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


async def resolve(raw: str) -> str | None:
    if not enabled():
        return None
    s = normalize(raw)
    return s if s in await valid_symbols() else None


def _api_symbol(symbol: str) -> str:
    """EURUSD -> EUR/USD — Twelve Data shu shaklni talab qiladi."""
    return f"{symbol[:3]}/{symbol[3:]}" if len(symbol) == 6 else symbol


# Ichki timeframe kodi -> Twelve Data interval nomi.
_INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
              "1h": "1h", "4h": "4h", "1d": "1day"}
_TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


async def klines(symbol: str, start_ms: int, limit: int = 500,
                  tf: str = "1m") -> list[Candle]:
    """Shamlar. Standart 1m — KUZATUV (tracker.py) aynan shuni ishlatadi.
    tf faqat grafik ko'rsatish uchun (exchange.klines bilan bir xil shart)."""
    interval = _INTERVALS.get(tf, "1min")
    dur = _TF_MS.get(tf, 60_000)
    start = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    r = await _client.get("/time_series", params={
        "symbol": _api_symbol(symbol), "interval": interval, "outputsize": limit,
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"), "order": "ASC",
        "timezone": "UTC", "apikey": config.TWELVE_DATA_API_KEY,
    })
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
        out.append(Candle(open_ms, float(row["open"]), float(row["high"]),
                           float(row["low"]), float(row["close"]), open_ms + dur - 1))
    out.sort(key=lambda c: c.open_ms)
    return out


_PRICE_TTL = 5.0
_price_cache: dict[str, tuple[float, float]] = {}


async def last_price(symbol: str, fresh: bool = False) -> float | None:
    """exchange.last_price() bilan bir xil qisqa muddatli kesh — bu yerda undan
    ham muhimroq, chunki Twelve Data bepul rejasi DAQIQASIGA 8 so'rov beradi:
    keshsiz bitta /stats bosilishi limitni yeb qo'yishi va forex signallari
    kuzatuvini to'xtatishi mumkin."""
    if not fresh:
        hit = _price_cache.get(symbol)
        if hit and (time.monotonic() - hit[0]) < _PRICE_TTL:
            return hit[1]
    r = await _client.get("/price", params={
        "symbol": _api_symbol(symbol), "apikey": config.TWELVE_DATA_API_KEY})
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
