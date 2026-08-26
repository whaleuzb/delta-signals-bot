"""Yangi tanga listing e'lonlari — Koreys birjalari (Upbit). Bu birjalar
dunyodagi eng katta savdo hajmiga ega bozorlardan biri: ularda yangi
tanga e'lon qilinishi ko'pincha narxni keskin (ba'zan 2-3 baravar)
o'zgartiradi.

Upbit'ning `notices` API'si RASMIY hujjatlashtirilmagan (ichki,
lekin ochiq — kalit talab qilmaydi, veb-saytining o'zi ishlatadi),
shuning uchun javob shakli TO'LIQ kafolatlanmagan — barcha maydonlar
`.get()` bilan himoyalangan o'qiladi, kutilmagan o'zgarish bo'lsa bo'sh
ro'yxat qaytadi (butun `news_scan_job`ni buzmaydi).

Notice matni odatda KOREYS tilida keladi — buni bu yerda TARJIMA
QILISHGA urinilmaydi: xom sarlavha/matn to'g'ridan-to'g'ri
`newsai.analyze()`ga beriladi (Claude ko'p tilli — tarjima/tahlil/tiker-
taxminni o'zi bajaradi), xuddi SEC hujjatlari qanday ishlansa shunday.
"""
import logging
from datetime import datetime, timezone

import httpx

import config

log = logging.getLogger("listings")

# Yangi listing/savdo qo'llab-quvvatlash e'lonlarida odatda uchraydigan
# so'zlar — koreyscha ("상장"="listing", "거래지원"="trading support") va
# inglizcha (ba'zi e'lonlar ikki tilda birga yoziladi). Boshqa turdagi
# e'lonlar (texnik ishlar, umumiy xabarlar) chiqarib tashlanadi.
LISTING_KEYWORDS = ("상장", "거래지원", "신규", "listing", "market support")


async def upbit_scan(since: datetime) -> list[dict]:
    """`since`dan beri chiqqan, listing/savdo-qo'llab-quvvatlash e'loniga
    o'xshagan Upbit bildirishnomalarini qaytaradi.

    Natija: `{source, external_key, symbol, market, headline_en, body_en,
    event_at, source_url}` — `news.sec_scan()` bilan bir xil shakl,
    `bot.py`ning umumiy quvuriga o'zgarishsiz qo'shiladi. `symbol` doim
    `None` — tiker `newsai.analyze()` bosqichida taxmin qilinadi."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # MUHIM: `thread_name`/boshqa filtr parametrlari HALI TASDIQLANMAGAN
            # (rasmiy hujjat yopiq) — ataylab FAQAT sahifalash beriladi, aks
            # holda noto'g'ri qiymat butun so'rovni 404/400 bilan rad etishi
            # mumkin (production logida `/notices` (search yo'lisiz) 404
            # bergani allaqachon kuzatilgan va shu sabab tuzatilgan edi).
            r = await client.get(config.UPBIT_NOTICES_URL, params={
                "page": 1, "per_page": 20,
            })
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("Upbit e'lonlari olinmadi", exc_info=True)
        return []

    notices = (data.get("data", {}) or {}).get("list", []) or data.get("list", [])
    out: list[dict] = []
    for item in notices:
        title = item.get("title") or ""
        if not any(kw in title for kw in LISTING_KEYWORDS):
            continue
        notice_id = item.get("id")
        if notice_id is None:
            continue
        listed_at = item.get("listed_at") or item.get("first_listed_at")
        try:
            event_at = datetime.fromisoformat(listed_at.replace("Z", "+00:00")) \
                if listed_at else datetime.now(timezone.utc)
        except (ValueError, AttributeError):
            event_at = datetime.now(timezone.utc)
        if event_at < since:
            continue

        out.append({
            "source": "upbit",
            "external_key": f"upbit:{notice_id}",
            "symbol": None,
            "market": None,
            "headline_en": title,
            "body_en": title,
            "event_at": event_at,
            "source_url": f"https://upbit.com/service_center/notice?id={notice_id}",
        })
    return out
