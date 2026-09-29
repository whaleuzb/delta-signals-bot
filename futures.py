"""MEXC fyuchers (USDT-M perpetual) narx manbasi (198).

Spot'da YO'Q, lekin fyuchersda savdo qilinadigan juftliklar uchun (masalan
TRBUSDT — MEXC spot'dan chiqarilgan, fyuchersda bor). Bot ichida juftlik
nomi odatdagidek `TRBUSDT`, bozor `futures`; API'da `TRB_USDT`.

Interfeys `exchange`/`forex`/`stocks` bilan bir xil: `resolve`, `klines`,
`last_price`, `close` — `tracker.provider()` shu modulni qaytaradi.

API (contract.mexc.com, kalitsiz):
  /api/v1/contract/detail                 — barcha kontraktlar (state 0 = ochiq)
  /api/v1/contract/ticker?symbol=TRB_USDT — data.lastPrice
  /api/v1/contract/kline/TRB_USDT?interval=Min1&start=<s>&end=<s>
      — data: {time:[s..], open:[..], high:[..], low:[..], close:[..], vol:[..]}
"""
import logging
import time

import httpx

import config
from exchange import Candle, normalize

log = logging.getLogger(__name__)

BASE = "https://contract.mexc.com"
_client = httpx.AsyncClient(base_url=BASE, timeout=15)

_INTERVALS = {"1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30",
              "1h": "Min60", "4h": "Hour4", "1d": "Day1"}
_TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

_symbols: set[str] = set()      # bot ko'rinishida: TRBUSDT
_symbols_ts = 0.0
_price_cache: dict[str, tuple[float, float]] = {}
_PRICE_TTL = 5.0


def api_symbol(symbol: str) -> str:
    """TRBUSDT -> TRB_USDT."""
    q = config.QUOTE
    return f"{symbol[:-len(q)]}_{q}" if symbol.endswith(q) else symbol


async def valid_symbols() -> set[str]:
    """Ochiq (state 0) USDT kontraktlari, 1 soat kesh."""
    global _symbols, _symbols_ts
    if _symbols and time.time() - _symbols_ts < 3600:
        return _symbols
    r = await _client.get("/api/v1/contract/detail")
    r.raise_for_status()
    data = r.json().get("data") or []
    q = "_" + config.QUOTE
    _symbols = {
        d["symbol"].replace("_", "") for d in data
        if isinstance(d, dict) and str(d.get("symbol", "")).endswith(q)
        and d.get("state", 0) == 0
    }
    _symbols_ts = time.time()
    return _symbols


async def resolve(raw: str) -> str | None:
    s = normalize(raw)
    return s if s in await valid_symbols() else None


async def klines(symbol: str, start_ms: int, limit: int = 500,
                 tf: str = "1m", end_ms: int | None = None) -> list[Candle]:
    """`exchange.klines` bilan bir xil shart: [start_ms, end_ms] oynasidan
    BOSHIDAN ko'pi bilan `limit` ta sham. API soniyalarda ishlaydi va bir
    so'rovda 2000 tagacha qaytaradi — oyna shunga qarab cheklanadi."""
    interval = _INTERVALS.get(tf, "Min1")
    dur = _TF_MS.get(tf, 60_000)
    limit = min(limit, 2000)
    last_allowed = start_ms + limit * dur
    end = min(end_ms, last_allowed) if end_ms is not None else last_allowed
    params = {"interval": interval, "start": start_ms // 1000, "end": end // 1000}
    r = await _client.get(f"/api/v1/contract/kline/{api_symbol(symbol)}", params=params)
    if r.status_code == 429:
        log.warning("MEXC fyuchers rate limit — kutamiz")
        return []
    if 400 <= r.status_code < 500:
        log.warning("MEXC fyuchers %s: %s %s uchun ma'lumot yo'q", r.status_code, symbol, interval)
        return []
    r.raise_for_status()
    body = r.json()
    d = body.get("data") or {}
    if not body.get("success", True) or not isinstance(d, dict):
        log.warning("MEXC fyuchers %s: kutilmagan javob (%s)", symbol, str(body)[:200])
        return []
    t, o, h, lo, c = (d.get(k) or [] for k in ("time", "open", "high", "low", "close"))
    vol = d.get("vol") or []
    out = []
    for i in range(min(len(t), len(o), len(h), len(lo), len(c))):
        open_ms = int(t[i]) * 1000
        # Oynadan tashqaridagi (start'dan oldingi) shamni ham tracker o'zi
        # hisobga oladi (birinchi sham qoidasi) — bu yerda faqat tartib.
        out.append(Candle(open_ms, float(o[i]), float(h[i]), float(lo[i]), float(c[i]),
                          open_ms + dur - 1, float(vol[i]) if i < len(vol) else 0.0))
    out.sort(key=lambda x: x.open_ms)
    return out[:limit]


async def last_price(symbol: str, fresh: bool = False) -> float | None:
    if not fresh:
        hit = _price_cache.get(symbol)
        if hit and (time.monotonic() - hit[0]) < _PRICE_TTL:
            return hit[1]
    r = await _client.get("/api/v1/contract/ticker", params={"symbol": api_symbol(symbol)})
    if r.status_code != 200:
        return None
    d = r.json().get("data") or {}
    if isinstance(d, list):
        d = d[0] if d else {}
    p = d.get("lastPrice")
    if p is None:
        return None
    price = float(p)
    _price_cache[symbol] = (time.monotonic(), price)
    return price


async def close() -> None:
    await _client.aclose()
