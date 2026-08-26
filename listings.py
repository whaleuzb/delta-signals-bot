"""Yangi tanga listing e'lonlari — Upbit (Koreys birjasi, dunyodagi eng
katta savdo hajmiga ega bozorlardan biri: yangi tanga e'lon qilinishi
ko'pincha narxni keskin, ba'zan 2-3 baravar o'zgartiradi).

`project-team.upbit.com/api/v1/disclosure` — Upbit'ning rasmiy DISCLOSURE
(rasmiy bildirishnoma) API'si, ochiq/kalitsiz, veb-saytining o'zi
ishlatadi. Rasmiy hujjat yopiq — shakl ochiq-manba crawler namunasidan
tasdiqlangan (`assets`/`text`/`start_date` maydonlari), lekin BOSHQA
maydonlar (masalan `id`) hali tasdiqlanmagan, shuning uchun BARCHA
o'qishlar `.get()` bilan himoyalangan; kutilmagan o'zgarish bo'lsa bo'sh
ro'yxat qaytadi (butun `news_scan_job`ni buzmaydi).

Bildirishnoma matni odatda KOREYS tilida keladi — buni bu yerda TARJIMA
QILISHGA urinilmaydi: xom matn to'g'ridan-to'g'ri `newsai.analyze()`ga
beriladi (Claude ko'p tilli — tarjima/tahlil/tiker-taxminni o'zi
bajaradi), xuddi SEC hujjatlari qanday ishlansa shunday."""
import hashlib
import logging
from datetime import datetime, timezone

import httpx

import config

log = logging.getLogger("listings")

DISCLOSURE_URL = "https://project-team.upbit.com/api/v1/disclosure"
# Ba'zi API'lar standart python/httpx User-Agent'ni rad etadi — brauzerga
# o'xshash sarlavha bilan so'rov yuboriladi.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


async def upbit_scan(since: datetime) -> list[dict]:
    """`since`dan beri chiqqan Upbit rasmiy bildirishnomalarini qaytaradi.

    Natija: `{source, external_key, symbol, market, headline_en, body_en,
    event_at, source_url}` — `news.sec_scan()` bilan bir xil shakl,
    `bot.py`ning umumiy quvuriga o'zgarishsiz qo'shiladi. `symbol` doim
    `None` — tiker `newsai.analyze()` bosqichida taxmin qilinadi (garchi
    `assets` maydoni ko'pincha tiker nomini o'z ichiga olsa ham, buni
    ishonchli deb hisoblab bo'lmaydi — Claude orqali TASDIQLANADI)."""
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=HEADERS) as client:
            r = await client.get(DISCLOSURE_URL, params={"region": "kr", "per_page": 20})
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("Upbit disclosure olinmadi", exc_info=True)
        return []

    posts = (data.get("data", {}) or {}).get("posts", []) or []
    out: list[dict] = []
    for post in posts:
        text = post.get("text") or ""
        assets = post.get("assets") or []
        if not text and not assets:
            continue

        start_date = post.get("start_date")
        try:
            event_at = datetime.fromisoformat(start_date) if start_date else None
            if event_at and event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=timezone.utc)
        except ValueError:
            event_at = None
        if event_at is None:
            event_at = datetime.now(timezone.utc)
        if event_at < since:
            continue

        # `id` maydoni tasdiqlanmagan — bo'lsa ishlatiladi, bo'lmasa
        # matn+sana asosida barqaror (har safar bir xil) hash tuziladi.
        post_id = post.get("id")
        if post_id is None:
            digest = hashlib.sha256(f"{text}|{start_date}".encode()).hexdigest()[:16]
            post_id = digest

        asset_str = ", ".join(str(a) for a in assets) if assets else ""
        headline = f"[{asset_str}] {text}" if asset_str else text

        out.append({
            "source": "upbit",
            "external_key": f"upbit:{post_id}",
            "symbol": None,
            "market": None,
            "headline_en": headline,
            "body_en": text,
            "event_at": event_at,
            "source_url": "https://upbit.com/service_center/notice",
        })
    return out
