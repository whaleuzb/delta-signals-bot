"""Yirik likvidatsiyalar — Coinalyze API orqali (Binance kabi fyuchers
birjasidagi majburiy yopilishlarni jamlaydi).

Foydalanuvchi so'rovi: "faqat 500.000$ dan katta likvidatsiyalar
ko'rsatilsin, kichiklari kerak emas" — avvalgi versiya "o'rtachadan necha
marta ko'p" nisbatiga qarardi (chalkash, tushunarsiz edi). Endi mezon
oddiy: oxirgi 5 daqiqalik ustunda long YOKI short tomonning BIRI
`config.LIQUIDATION_MIN_USD`dan katta bo'lsa — post qilinadi.

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
ko'rsatilmagan (`"history": []` — bo'sh namuna). Shu sabab `_bucket_sides()`
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
LOOKBACK_MINUTES = 15   # bir nechta ustun so'raladi, faqat OXIRGISI ishlatiladi


def enabled() -> bool:
    return bool(config.COINALYZE_API_KEY)


@dataclass
class Spike:
    symbol: str
    long_usd: float
    short_usd: float


def _bucket_sides(item: dict) -> tuple[float, float]:
    """Bir ustundagi (long, short) likvidatsiya qiymatlari alohida-alohida
    (`convert_to_usd=true` bo'lgani uchun USD'da). Aniq maydon nomlari
    rasmiy hujjatda ko'rsatilmagani uchun bir nechta ehtimoliy nom
    sinaladi."""
    long_v = item.get("l") or item.get("long") or item.get("buy") or 0
    short_v = item.get("s") or item.get("short") or item.get("sell") or 0
    try:
        return float(long_v), float(short_v)
    except (TypeError, ValueError):
        return 0.0, 0.0


async def liquidation_candidates() -> list[Spike]:
    """Kuzatilayotgan BARCHA instrumentlar uchun BITTA so'rovda (Coinalyze
    20 tagacha instrumentni bir so'rovda qabul qiladi) oxirgi 5-daqiqalik
    likvidatsiya ustunini oladi, long/short tomonlardan BIRI
    `config.LIQUIDATION_MIN_USD`dan katta bo'lgan instrumentlarni
    qaytaradi. Butun so'rov muvaffaqiyatsiz bo'lsa (masalan tarmoq/kalit
    xatosi) bo'sh ro'yxat — chaqiruvchi (`liquidation_scan_job`) shuni
    allaqachon xato sifatida logaydi."""
    if not enabled():
        return []

    now = int(time.time())
    from_ts = now - LOOKBACK_MINUTES * 60
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
        if not symbol or not buckets:
            continue
        long_usd, short_usd = _bucket_sides(buckets[-1])
        if max(long_usd, short_usd) >= config.LIQUIDATION_MIN_USD:
            log.debug("Likvidatsiya xom ustun (%s): %r", symbol, buckets[-1])
            out.append(Spike(symbol=symbol, long_usd=long_usd, short_usd=short_usd))
    return out
