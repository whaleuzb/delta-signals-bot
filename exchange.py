"""Binance USDⓈ-M Futures public API. API key kerak emas."""
import time
import logging
from dataclasses import dataclass

import httpx
import config

log = logging.getLogger(__name__)
_client = httpx.AsyncClient(base_url=config.BINANCE_BASE, timeout=15)

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
    r = await _client.get("/fapi/v1/exchangeInfo")
    r.raise_for_status()
    _symbols = {
        s["symbol"] for s in r.json()["symbols"]
        if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
    }
    _symbols_ts = time.time()
    return _symbols


def normalize(raw: str) -> str:
    """btc, BTC/USDT, BTCUSDT.P -> BTCUSDT"""
    s = raw.upper().strip().replace("/", "").replace("-", "").replace(":", "")
    for suf in (".P", "PERP"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if not s.endswith(config.QUOTE):
        s += config.QUOTE
    return s


async def resolve(raw: str) -> str | None:
    s = normalize(raw)
    return s if s in await valid_symbols() else None


async def klines(symbol: str, start_ms: int, limit: int = 1000) -> list[Candle]:
    """1 daqiqalik shamlar. high/low bo'lgani uchun hech qanday teginish yo'qolmaydi."""
    r = await _client.get(
        "/fapi/v1/klines",
        params={"symbol": symbol, "interval": "1m", "startTime": start_ms, "limit": limit},
    )
    if r.status_code == 429:
        log.warning("Binance rate limit — kutamiz")
        return []
    r.raise_for_status()
    return [
        Candle(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), int(k[6]))
        for k in r.json()
    ]


async def last_price(symbol: str) -> float | None:
    r = await _client.get("/fapi/v1/ticker/price", params={"symbol": symbol})
    if r.status_code != 200:
        return None
    return float(r.json()["price"])


async def close() -> None:
    await _client.aclose()
