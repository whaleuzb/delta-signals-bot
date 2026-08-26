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
bajaradi), xuddi SEC hujjatlari qanday ishlansa shunday.

Bundan tashqari `binance_scan()` — Binance yangi listinglari, pastga
qarang."""
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

# Sarlavhasiz (standart httpx) so'rov 403 bilan rad etildi (production
# logida tasdiqlangan) — Upbit'ning bu mikroservisi so'rov brauzerdan
# kelayotganini (User-Agent) va manba sahifasidan (Referer/Origin)
# tekshiradi shekilli. Haqiqiy brauzer sarlavhalari bilan ishlatiladi.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                 "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://upbit.com/service_center/notice",
    "Origin": "https://upbit.com",
}


async def upbit_scan(since: datetime) -> list[dict]:
    """`since`dan beri chiqqan, listing/savdo-qo'llab-quvvatlash e'loniga
    o'xshagan Upbit bildirishnomalarini qaytaradi.

    Natija: `{source, external_key, symbol, market, headline_en, body_en,
    event_at, source_url}` — `news.sec_scan()` bilan bir xil shakl,
    `bot.py`ning umumiy quvuriga o'zgarishsiz qo'shiladi. `symbol` doim
    `None` — tiker `newsai.analyze()` bosqichida taxmin qilinadi."""
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=HEADERS) as client:
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


# --- Yirik birjalarning yangi listing e'lonlari ---
# Foydalanuvchi cryptocurrencyalerting.com'ning "New Binance Listings"
# sahifasi ORTIDAGI haqiqiy JSON API'ni topdi (sahifaning main.min.js
# fayli `$.getJSON(CONSTANTS.apiHost + "/binance-new-coins")` chaqiradi).
# Kalitsiz, bepul, tayyor tuzilgan (tiker+nom+vaqt) — shu sabab bu manba
# Upbit'dan farqli AI orqali O'TMAYDI (bot.py'da alohida, AI'siz
# ishlanadi — MarketTwits qanday AI'siz bo'lsa xuddi shunday, chunki
# "yangi listing"ning o'zi ALLAQACHON aniq signal, "muhimmi-yo'qmi"
# filtri kerak emas, tarjima ham shart emas — shablon matn yetarli).
#
# Foydalanuvchi so'radi: "coinbase va kreken ham shu sayt orqali olish
# imkoni bormi?" — SINALDI (production, Railway loglari): `/coinbase-
# new-coins` va `/kraken-new-coins` bunday manzillar UMUMAN MAVJUD EMAS,
# saytning o'zi ularni `/404` (Rails standart xato sahifasi)ga redirect
# qiladi. Faqat Binance uchun shu naqshda haqiqiy endpoint bor —
# Coinbase/Kraken shu sayt orqali OLINMAYDI.
EXCHANGE_LISTING_URLS = {
    "Binance": "https://api.cryptocurrencyalerting.com/binance-new-coins",
}


async def exchange_listing_scan(exchange: str, since: datetime) -> list[dict]:
    """`since`dan beri qo'shilgan `exchange` (EXCHANGE_LISTING_URLS'dagi
    kalit) listinglarini qaytaradi.

    Natija shakli Upbit/SEC bilan BIR XIL EMAS — bu yerda AI kerak
    emasligi uchun `_process_exchange_listing()` (bot.py) o'ziga xos
    maydonlarni (`code`/`name`/`exchange`/`market_url`) kutadi,
    `_process_news_event()` orqali o'TMAYDI."""
    url = EXCHANGE_LISTING_URLS[exchange]
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            r = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; TradeControllerBot/1.0)",
                "Accept": "application/json",
            })
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("%s listinglari olinmadi", exchange, exc_info=True)
        return []

    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for item in data:
        alert_id = item.get("alert_id")
        code = item.get("code")
        if not alert_id or not code:
            continue

        created_at = item.get("created_at") or ""
        event_at = None
        if created_at:
            try:
                event_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                event_at = None
        if event_at is None:
            event_at = datetime.now(timezone.utc)
        elif event_at.tzinfo is not None:
            event_at = event_at.astimezone(timezone.utc)
        if event_at < since:
            continue

        out.append({
            "external_key": f"{exchange.lower()}list:{alert_id}",
            "exchange": exchange,
            "code": code,
            "name": item.get("name") or code,
            "event_at": event_at,
            "market_url": item.get("market_url") or "",
        })
    return out


async def binance_scan(since: datetime) -> list[dict]:
    return await exchange_listing_scan("Binance", since)
