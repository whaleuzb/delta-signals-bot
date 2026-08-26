"""AQSH makroiqtisodiy yangiliklar taqvimi — Forex Factory'ning ochiq,
kalitsiz JSON eksporti orqali (`nfs.faireconomy.media`). Ko'plab MT4/5
indikatorlari shu manbadan foydalanadi, lekin u RASMIY EMAS: maydon
nomlari yoki formati ogohlantirishsiz o'zgarishi mumkin. Shu sabab hamma
narsa ehtiyotkorlik bilan (`.get()`, keng `try/except`) o'qiladi — bitta
kutilmagan maydon butun funksiyani to'xtatmasligi kerak.

Bu modul Telegram'ga bog'liq emas — faqat toza ma'lumot qaytaradi.
"""
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("econcalendar")

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# "Low" (arzimas) va bayramlar chiqarib tashlanadi — "High" va "Medium"
# ikkalasi ham qoladi (PMI, iste'molchi ishonchi kabi ko'p e'tiborli
# hodisalar odatda "Medium" darajada, ular ham foydali).
WANTED_IMPACT = {"High", "Medium", "high", "medium"}


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def fetch_week() -> list[dict]:
    """Joriy haftaning FAQAT AQSH (USD) va YUQORI ta'sirli hodisalari.

    Xato bo'lsa (manba javob bermadi, format o'zgardi) — bo'sh ro'yxat,
    hech qachon istisno tashlamaydi. Natija: `{title, when (tz-aware
    datetime), forecast, previous}`."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(CALENDAR_URL)
            r.raise_for_status()
            raw = r.json()
    except Exception:
        log.warning("Iqtisodiy taqvim olinmadi", exc_info=True)
        return []

    if not isinstance(raw, list):
        log.warning("Iqtisodiy taqvim kutilmagan shaklda keldi: %s", type(raw))
        return []

    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        country = item.get("country") or item.get("currency")
        if country != "USD":
            continue
        if item.get("impact") not in WANTED_IMPACT:
            continue
        when = _parse_dt(item.get("date") or item.get("datetime"))
        if when is None:
            continue
        out.append({
            "title": item.get("title") or item.get("name") or "Noma'lum hodisa",
            "when": when,
            "forecast": item.get("forecast") or "",
            "previous": item.get("previous") or "",
        })
    return out
