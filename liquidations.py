"""Yirik likvidatsiyalar — Coinalyze API orqali (Binance/Bybit/OKX kabi
fyuchers birjalaridagi majburiy yopilishlarni jamlaydi).

Yirik likvidatsiya to'lqini ko'pincha keskin narx harakati bilan birga
keladi (kaskadli likvidatsiya) — News Trade AI'ning boshqa hodisalari
(SEC, listing, hajm portlashi) kabi bitta "signal turi".

`COINALYZE_API_KEY` bo'sh bo'lsa butun modul jimgina o'chadi — boshqa
News Trade AI manbalariga (SEC/Upbit/surge) hech qanday ta'siri yo'q.

Endpoint (`GET /liquidation-history`) rasmiy hujjatdan (foydalanuvchi
yuborgan API spetsifikatsiyasi) tasdiqlangan: `symbols` (vergul bilan,
BITTA so'rovda 20 tagacha), `interval`, `from`/`to` (UNIX soniya,
IKKALASI HAM MAJBURIY), `convert_to_usd`. Javob: `[{"symbol": ...,
"history": [...]}, ...]` — bitta so'rov barcha kuzatilayotgan
instrumentlarni qamrab oladi (har biriga alohida so'rov SHART EMAS).

MUHIM: bitta bucket ICHIDAGI aniq maydon nomlari (masalan uzun/qisqa
likvidatsiya alohida-alohida qanday nomlanishi) rasmiy spetsifikatsiyada
ko'rsatilmagan (`"history": []` — bo'sh namuna). Shu sabab `_bucket_total()`
bir nechta ehtimoliy nom bilan himoyalangan o'qiydi; aniq shakl
production loglarida tasdiqlanadi, kerak bo'lsa moslashtiriladi."""
import logging
import time
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
    long_usd: float
    short_usd: float


def _bucket_sides(item: dict) -> tuple[float, float]:
    """Bir ustundagi (long, short) likvidatsiya qiymatlari alohida-alohida
    (`convert_to_usd=true` bo'lgani uchun USD'da). Aniq maydon nomlari
    rasmiy hujjatda ko'rsatilmagani uchun bir nechta ehtimoliy nom
    sinaladi — `log.debug` orqali xom ustun ham yoziladi, production
    logida haqiqiy maydon nomlarini tasdiqlash uchun."""
    long_v = item.get("l") or item.get("long") or item.get("buy") or 0
    short_v = item.get("s") or item.get("short") or item.get("sell") or 0
    try:
        return float(long_v), float(short_v)
    except (TypeError, ValueError):
        return 0.0, 0.0


def _bucket_total(item: dict) -> float:
    long_v, short_v = _bucket_sides(item)
    return long_v + short_v


async def liquidation_candidates() -> list[Spike]:
    """Kuzatilayotgan BARCHA instrumentlar uchun BITTA so'rovda (Coinalyze
    20 tagacha instrumentni bir so'rovda qabul qiladi) 5 daqiqalik
    likvidatsiya ustunlarini oladi, har biri uchun oxirgi ustunni oldingi
    ustunlar o'rtachasi bilan solishtiradi. Butun so'rov muvaffaqiyatsiz
    bo'lsa (masalan tarmoq/kalit xatosi) bo'sh ro'yxat — chaqiruvchi
    (`liquidation_scan_job`) shuni allaqachon xato sifatida logaydi."""
    if not enabled():
        return []

    now = int(time.time())
    from_ts = now - LOOKBACK_BUCKETS * 5 * 60
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{BASE_URL}/liquidation-history", params={
            "symbols": ",".join(config.LIQUIDATION_SYMBOLS),
            "interval": INTERVAL, "from": from_ts, "to": now,
            "convert_to_usd": "true", "api_key": config.COINALYZE_API_KEY,
        })
        r.raise_for_status()
        data = r.json()

    out: list[Spike] = []
    if not isinstance(data, list):
        return out
    for entry in data:
        symbol = entry.get("symbol")
        buckets = entry.get("history") or []
        if not symbol or len(buckets) < 5:
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
            long_usd, short_usd = _bucket_sides(buckets[-1])
            log.debug("Likvidatsiya xom ustun (%s): %r", symbol, buckets[-1])
            out.append(Spike(symbol=symbol, latest_usd=latest, baseline_usd=avg,
                             ratio=ratio, long_usd=long_usd, short_usd=short_usd))
    return out
