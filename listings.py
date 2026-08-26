"""Yangi tanga listing e'lonlari — Upbit (Koreys birjasi, dunyodagi eng
katta savdo hajmiga ega bozorlardan biri: yangi tanga e'lon qilinishi
ko'pincha narxni keskin, ba'zan 2-3 baravar o'zgartiradi).

`pub-info.upbit.com/api/v1/announcements` — Upbit'ning haqiqiy, ishlab
turgan ochiq API'si. Foydalanuvchi brauzer DevTools (Network) orqali
TASDIQLADI: "공지사항" (Notice) sahifasi ochilganda aynan shu so'rov
ketadi, HTTP 200 qaytaradi. Ikkita oldingi taxmin (`api-manager.upbit.com`
va `project-team.upbit.com`) ESKIRGAN chiqdi — Upbit bu funksiyani
alohida `pub-info.upbit.com` mikroservisiga ko'chirgan ekan.

Javob: `{"success": true, "data": {"notices": [{"id", "uuid", "title",
"category", "listed_at", "first_listed_at", ...}]}}` — barcha o'qishlar
baribir `.get()` bilan himoyalangan (kelajakda yana o'zgarishi mumkin).

Notice sarlavhasi ko'pincha KOREYS tilida keladi — buni bu yerda TARJIMA
QILISHGA urinilmaydi: xom sarlavha to'g'ridan-to'g'ri `newsai.analyze()`ga
beriladi (Claude ko'p tilli — tarjima/tahlil/tiker-taxminni o'zi
bajaradi), xuddi SEC hujjatlari qanday ishlansa shunday."""
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("listings")

ANNOUNCEMENTS_URL = "https://pub-info.upbit.com/api/v1/announcements"

# Yangi listing/savdo qo'llab-quvvatlash e'lonlarida odatda uchraydigan
# so'zlar — koreyscha ("상장"="listing", "거래지원"="trading support") va
# inglizcha (ba'zi e'lonlar ikki tilda birga yoziladi). Boshqa turdagi
# e'lonlar (texnik ishlar, umumiy voqealar) chiqarib tashlanadi. `category`
# maydoni orqali ANIQ filtrlash HALI qo'llanilmadi — Upbit'ning aniq
# kategoriya taksonomiyasi (Trade/Digital Asset/...) tasdiqlanmagan,
# sarlavha bo'yicha kalit so'z filtri ancha ishonchli.
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
            r = await client.get(ANNOUNCEMENTS_URL, params={
                "os": "web", "page": 1, "per_page": 20, "category": "all",
            })
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("Upbit e'lonlari olinmadi", exc_info=True)
        return []

    notices = ((data.get("data") or {}).get("notices")) or []
    out: list[dict] = []
    for notice in notices:
        title = notice.get("title") or ""
        if not any(kw in title for kw in LISTING_KEYWORDS):
            continue
        notice_id = notice.get("id")
        if notice_id is None:
            continue

        listed_at = notice.get("listed_at") or notice.get("first_listed_at")
        event_at = None
        if listed_at:
            try:
                event_at = datetime.fromisoformat(listed_at)
            except ValueError:
                event_at = None
        if event_at is None:
            event_at = datetime.now(timezone.utc)
        elif event_at.tzinfo is not None:
            event_at = event_at.astimezone(timezone.utc)
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
