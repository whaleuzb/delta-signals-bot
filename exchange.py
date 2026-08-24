"""MEXC Spot public API. API key kerak emas.

Binance Futures (fapi.binance.com) Railway serverining hududini 451 bilan
bloklagani uchun MEXC'ga o'tildi. MEXC'ning /api/v3 spot API'si Binance
spot API bilan deyarli bir xil shaklda javob beradi (klines, exchangeInfo,
ticker/price) — shu sabab bu fayl tuzilishi saqlanib qoldi.
"""
import time
import logging
from dataclasses import dataclass

import httpx
import config

log = logging.getLogger(__name__)
_client = httpx.AsyncClient(base_url=config.EXCHANGE_BASE, timeout=15)

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


async def valid_symbols() -> set[str]:
    """exchangeInfo 1 soatga keshlanadi."""
    global _symbols, _symbols_ts
    if _symbols and time.time() - _symbols_ts < 3600:
        return _symbols
    r = await _client.get("/api/v3/exchangeInfo")
    r.raise_for_status()
    # status: MEXC "1" qaytaradi, lekin hujjatlarda "ENABLED" ham uchraydi —
    # ikkalasini ham qabul qilamiz. Agar bir kun yozilishi yana o'zgarsa,
    # butun ro'yxat bo'shab qolib BARCHA signallar rad etilishi mumkin edi;
    # asosiy shart baribir isSpotTradingAllowed.
    _symbols = {
        s["symbol"] for s in r.json()["symbols"]
        if s.get("isSpotTradingAllowed")
        and str(s.get("status", "")).upper() in ("1", "ENABLED", "TRADING")
    }
    _symbols_ts = time.time()
    return _symbols


def normalize(raw: str) -> str:
    """btc, Btc, BTC/USDT, "BTC USDT", BTC_USDT, BTCUSDT.P -> BTCUSDT

    Ajratgichlar (bo'sh joy, _, /, -, :) tashlanadi — odamlar juftlikni
    juda xilma-xil yozadi va ularning hammasi bir xil narsani bildiradi."""
    s = raw.upper().strip()
    for ch in ("/", "-", ":", "_", " ", "\t", " "):
        s = s.replace(ch, "")
    for suf in (".P", "PERP"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if not s.endswith(config.QUOTE):
        s += config.QUOTE
    return s


async def resolve(raw: str) -> str | None:
    s = normalize(raw)
    return s if s in await valid_symbols() else None


# Ichki timeframe kodi -> MEXC interval nomi. MEXC 1 soatni "60m" deb ataydi.
_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
              "1h": "60m", "4h": "4h", "1d": "1d"}
# Sham davomiyligi (ms) — close_ms ni hisoblash uchun.
_TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


async def klines(symbol: str, start_ms: int, limit: int = 500,
                  tf: str = "1m") -> list[Candle]:
    """Shamlar. Standart 1m — KUZATUV (tracker.py) aynan shuni ishlatadi va
    o'zgartirilmasligi kerak: 1m'dan yirikroq shamda TP/SL teginishi sham
    ichida yashirinib qolishi mumkin. tf faqat KO'RSATISH (grafik) uchun."""
    interval = _INTERVALS.get(tf, "1m")
    dur = _TF_MS.get(tf, 60_000)
    r = await _client.get(
        "/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "startTime": start_ms,
                "limit": limit},
    )
    if r.status_code == 429:
        log.warning("MEXC rate limit — kutamiz")
        return []
    r.raise_for_status()
    out = []
    for k in r.json():
        open_ms = int(k[0])
        out.append(Candle(open_ms, float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                          open_ms + dur - 1))
    return out


_PRICE_TTL = 5.0
_price_cache: dict[str, tuple[float, float]] = {}


async def last_price(symbol: str, fresh: bool = False) -> float | None:
    """Qisqa muddatli (5 s) kesh. Sabab: /stats, /symbols, /open kabi buyruqlar
    HAR ochiq signal uchun alohida so'rov yuboradi — 20 ta ochiq signal bo'lsa
    bitta tugma bosilishi 20 ta so'rov demak. Foydalanuvchi buyruqni tez-tez
    bossa MEXC IP bo'yicha rate-limit qo'yadi va bu kuzatuv siklini
    (poll_job → klines) ham buzadi. Kesh shu portlashni bitta so'rovga
    yig'adi, ko'rsatiladigan narx esa eng ko'pi bilan 5 s eskiradi.

    fresh=True — keshni chetlab o'tish; qo'lda yopishda (tracker.close_now)
    ishlatiladi, chunki u yerda narx savdoning YAKUNIY natijasiga yoziladi."""
    if not fresh:
        hit = _price_cache.get(symbol)
        if hit and (time.monotonic() - hit[0]) < _PRICE_TTL:
            return hit[1]
    r = await _client.get("/api/v3/ticker/price", params={"symbol": symbol})
    if r.status_code != 200:
        return None
    price = float(r.json()["price"])
    _price_cache[symbol] = (time.monotonic(), price)
    return price


async def close() -> None:
    await _client.aclose()
