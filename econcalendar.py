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
    datetime), forecast, previous, actual}`. `actual` — hodisa hali
    e'lon qilinmagan bo'lsa bo'sh satr (manba shu haftalik faylni
    natija chiqqach TO'LDIRIB qo'yadi, alohida so'rov shart emas)."""
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
            "actual": item.get("actual") or "",
        })
    return out


# ---------------------------------------------------------------------------
# Sarlavhalarni o'zbekchaga o'girish
#
# Manba (Forex Factory) sarlavhalari INGLIZCHA keladi va ilgari kanalga
# xuddi shu holda chiqardi. Foydalanuvchi talabi: "News trade kanalida
# xabar faqat uzbek tilida kelishi kerak" — shu sabab bu yerda o'giriladi.
#
# Nega tarjimon API emas, LUG'AT? Bu sarlavhalar YOPIQ, kichik va deyarli
# o'zgarmas ro'yxat (haftasiga ~20 ta, doim bir xil nomlar). Lug'at bilan
# natija barqaror va bepul; tarjimon API bo'lsa har hafta xuddi shu
# matnlar uchun so'rov ketardi va "Non-Farm Payrolls" kabi atamalarni
# so'zma-so'z, noto'g'ri o'girardi.
# ---------------------------------------------------------------------------

# Sarlavha oldidagi aniqlovchilar (masalan "Core CPI m/m" -> "asosiy ...").
_PREFIXES = {
    "core": "asosiy",
    "prelim": "dastlabki",
    "preliminary": "dastlabki",
    "flash": "tezkor",
    "advance": "oldindan",
    "revised": "qayta ko'rilgan",
    "final": "yakuniy",
}

# Davr belgilari — sarlavha OXIRIDA keladi.
_PERIODS = {
    "m/m": "(oylik)",
    "q/q": "(choraklik)",
    "y/y": "(yillik)",
}

# Asosiy hodisa nomlari. Kalit — kichik harfda, aniqlovchi va davrsiz.
_TITLES = {
    "cpi": "iste'mol narxlari indeksi (CPI)",
    "ppi": "ishlab chiqaruvchi narxlari indeksi (PPI)",
    "pce price index": "PCE narx indeksi",
    "gdp": "yalpi ichki mahsulot (YaIM)",
    "gdp price index": "YaIM narx indeksi",
    "retail sales": "chakana savdo",
    "non-farm employment change": "qishloq xo'jaligidan tashqari bandlik o'zgarishi",
    "adp non-farm employment change": "ADP bandlik o'zgarishi",
    "unemployment rate": "ishsizlik darajasi",
    "unemployment claims": "ishsizlik nafaqasi arizalari",
    "average hourly earnings": "o'rtacha soatlik ish haqi",
    "employment cost index": "mehnat xarajatlari indeksi",
    "jolts job openings": "ochiq ish o'rinlari (JOLTS)",
    "federal funds rate": "AQSH Fed foiz stavkasi",
    "fomc statement": "FOMC bayonoti",
    "fomc press conference": "FOMC matbuot anjumani",
    "fomc meeting minutes": "FOMC yig'ilishi bayonnomasi",
    "fomc economic projections": "FOMC iqtisodiy prognozlari",
    "beige book": "Fed \"Bej kitob\" hisoboti",
    "fed chair powell speaks": "Fed rahbari Pauell nutqi",
    "fed chair powell testifies": "Fed rahbari Pauell Kongressda",
    "ism manufacturing pmi": "ISM sanoat PMI",
    "ism services pmi": "ISM xizmatlar PMI",
    "manufacturing pmi": "sanoat PMI",
    "services pmi": "xizmatlar PMI",
    "chicago pmi": "Chikago PMI",
    "empire state manufacturing index": "Empire State sanoat indeksi",
    "philly fed manufacturing index": "Philadelphia Fed sanoat indeksi",
    "richmond manufacturing index": "Richmond sanoat indeksi",
    "industrial production": "sanoat ishlab chiqarishi",
    "capacity utilization rate": "quvvatdan foydalanish darajasi",
    "durable goods orders": "uzoq muddatli tovarlarga buyurtmalar",
    "factory orders": "zavod buyurtmalari",
    "trade balance": "savdo balansi",
    "consumer credit": "iste'mol krediti",
    "personal income": "shaxsiy daromad",
    "personal spending": "shaxsiy xarajatlar",
    "cb consumer confidence": "CB iste'molchi ishonchi",
    "uom consumer sentiment": "Michigan universiteti iste'molchi kayfiyati",
    "uom inflation expectations": "Michigan universiteti inflyatsiya kutilmalari",
    "consumer sentiment": "iste'molchi kayfiyati",
    "building permits": "qurilish ruxsatnomalari",
    "housing starts": "yangi uy qurilishi boshlanishi",
    "new home sales": "yangi uy sotuvlari",
    "existing home sales": "ikkilamchi uy sotuvlari",
    "pending home sales": "kutilayotgan uy sotuvlari",
    "crude oil inventories": "neft zaxiralari",
    "natural gas storage": "tabiiy gaz zaxiralari",
    "treasury currency report": "G'aznachilik valyuta hisoboti",
}


def title_uz(title: str) -> str:
    """Inglizcha taqvim sarlavhasini o'zbekchaga o'giradi.

    Lug'atda yo'q bo'lsa — ASL matn qaytariladi. Hodisani butunlay
    yashirgandan ko'ra (foydalanuvchi muhim yangilikni ko'rmay qolardi)
    tanish bo'lmagan nomni asl holda ko'rsatgan afzal; loglarda bunday
    nomlar ko'rinsa yuqoridagi lug'atga qo'shib qo'yiladi."""
    raw = (title or "").strip()
    if not raw:
        return raw

    core = raw.lower()
    period = ""
    for suffix, uz in _PERIODS.items():
        if core.endswith(" " + suffix):
            core = core[: -(len(suffix) + 1)].strip()
            period = " " + uz
            break

    prefix = ""
    changed = True
    while changed:
        changed = False
        for eng, uz in _PREFIXES.items():
            if core.startswith(eng + " "):
                core = core[len(eng) + 1:].strip()
                prefix = (prefix + " " + uz).strip()
                changed = True
                break

    got = _TITLES.get(core)
    if got is None:
        log.info("Taqvimda tanish bo'lmagan sarlavha: %r", raw)
        return raw
    out = f"{prefix} {got}".strip() if prefix else got
    return (out[0].upper() + out[1:] + period).strip()
