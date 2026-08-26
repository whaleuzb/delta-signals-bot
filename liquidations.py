"""Yirik likvidatsiyalar — Coinalyze API orqali (Binance/Bybit/OKX kabi
fyuchers birjalaridagi majburiy yopilishlarni jamlaydi).

Yirik likvidatsiya to'lqini ko'pincha keskin narx harakati bilan birga
keladi (kaskadli likvidatsiya) — News Trade AI'ning boshqa hodisalari
(SEC, listing, hajm portlashi) kabi bitta "signal turi".

`COINALYZE_API_KEY` bo'sh bo'lsa butun modul jimgina o'chadi — boshqa
News Trade AI manbalariga (SEC/Upbit/surge) hech qanday ta'siri yo'q.

MUHIM: Coinalyze'ning `/liquidation-history` javob shakli bu yerda
RASMIY hujjatdan emas, umumiy tavsifidan (t/l/s maydonlar — vaqt,
long-likvidatsiya, short-likvidatsiya) olingan — sandbox tarmog'i
`api.coinalyze.net`ni bloklagani uchun to'g'ridan-to'g'ri tekshirib
bo'lmadi. Shu sabab BARCHA maydonlar `.get()` bilan himoyalangan
o'qiladi; aniq shakl production loglarida tasdiqlanadi, kerak bo'lsa
moslashtiriladi (SEC/CryptoPanic/Forex Factory integratsiyalarida
bo'lgani kabi)."""
import logging
from dataclasses import dataclass

import httpx

import config

log = logging.getLogger("liquidations")

BASE_URL = "https://api.coinalyze.net/v1"
INTERVAL = "5min"
LOOKBACK_BUCKETS = 30   # ~2.5 soat (5 daqiqalik ustunlar)


def enabled() -> bool:
    return bool(config.COINALYZE_API_KEY)


@dataclass
class Spike:
    symbol: str
    latest_usd: float
    baseline_usd: float
    ratio: float


async def _fetch_buckets(client: httpx.AsyncClient, symbol: str) -> list[dict]:
    r = await client.get(f"{BASE_URL}/liquidation-history", params={
        "symbols": symbol, "interval": INTERVAL,
        "api_key": config.COINALYZE_API_KEY,
    })
    r.raise_for_status()
    data = r.json()
    # Ko'p instrumentli so'rovlarda Coinalyze ro'yxat ichida ro'yxat
    # qaytaradi ({"symbol": ..., "history": [...]}) — bitta instrument
    # so'ralganda ham shu shaklni hisobga olamiz.
    if isinstance(data, list) and data and isinstance(data[0], dict) and "history" in data[0]:
        return data[0].get("history") or []
    if isinstance(data, list):
        return data
    return []


def _bucket_total(item: dict) -> float:
    """Bir ustundagi jami likvidatsiya (long+short, USD). Aniq maydon
    nomlari tasdiqlanmagani uchun bir nechta ehtimoliy nom sinaladi."""
    long_v = item.get("l") or item.get("long") or item.get("buy") or 0
    short_v = item.get("s") or item.get("short") or item.get("sell") or 0
    try:
        return float(long_v) + float(short_v)
    except (TypeError, ValueError):
        return 0.0


async def liquidation_candidates() -> list[Spike]:
    """Kuzatilayotgan har bir instrument uchun oxirgi ustunni avvalgi
    ustunlar o'rtachasi bilan solishtiradi. Xato bo'lgan/hajmsiz
    instrument shunchaki o'tkazib yuboriladi — bitta instrumentning
    muvaffaqiyatsizligi boshqalarini to'xtatmaydi."""
    if not enabled():
        return []
    out: list[Spike] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for symbol in config.LIQUIDATION_SYMBOLS:
            try:
                buckets = await _fetch_buckets(client, symbol)
            except Exception:
                log.warning("Coinalyze so'rovi muvaffaqiyatsiz (%s)", symbol, exc_info=True)
                continue
            if len(buckets) < 5:
                continue
            buckets = buckets[-LOOKBACK_BUCKETS:]
            totals = [_bucket_total(b) for b in buckets]
            latest = totals[-1]
            baseline = totals[:-1]
            avg = sum(baseline) / len(baseline) if baseline else 0.0
            if avg <= 0 or latest <= 0:
                continue
            ratio = latest / avg
            if ratio >= config.LIQUIDATION_MULTIPLIER:
                out.append(Spike(symbol=symbol, latest_usd=latest, baseline_usd=avg, ratio=ratio))
    return out
