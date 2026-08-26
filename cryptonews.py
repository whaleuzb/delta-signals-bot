"""CryptoPanic orqali muayyan tanga uchun yangilik qidirish.

Faqat surge.py (uzoq pasaygan, keyin hajmi keskin oshgan tangalar)
uchun ishlatiladi — "nega bu tanga portladi" degan savolga javob
qidirish. `CRYPTOPANIC_TOKEN` bo'sh bo'lsa funksiya jimgina o'chadi.

Ko'p kichik tangalarning portlashi ortida HECH QANDAY yangilik
bo'lmaydi (sof spekulyatsiya) — bo'sh natija bu XATO emas, kutilgan
holat."""
import logging

import httpx

import config

log = logging.getLogger("cryptonews")

BASE_URL = "https://cryptopanic.com/api/v1/posts/"


def enabled() -> bool:
    return bool(config.CRYPTOPANIC_TOKEN)


async def search(ticker: str) -> list[dict]:
    """`ticker` — masalan "DOGE" (USDT qo'shimchasiz). Natija: `{title, url,
    published_at}`, eng yangisi birinchi. Xato yoki natija yo'q — bo'sh
    ro'yxat, hech qachon istisno tashlamaydi."""
    if not enabled():
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(BASE_URL, params={
                "auth_token": config.CRYPTOPANIC_TOKEN,
                "currencies": ticker,
                "public": "true",
            })
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("CryptoPanic so'rovi muvaffaqiyatsiz (%s)", ticker, exc_info=True)
        return []

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []

    out = []
    for item in results:
        if not isinstance(item, dict):
            continue
        out.append({
            "title": item.get("title") or "",
            "url": item.get("url") or item.get("original_url") or "",
            "published_at": item.get("published_at"),
        })
    return out
