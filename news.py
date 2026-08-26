"""News Trade AI — bozorni qimirlatadigan yangiliklarni avtomatik topish.

Hozircha faqat SEC EDGAR: rasmiy, bepul, kalitsiz full-text qidiruv API'si
(`efts.sec.gov`). Bu kompaniyalar TOPSHIRGAN hujjatlarni (8-K, 10-K va h.k.)
kalit so'z bo'yicha qidiradi — "SEC X kompaniyani sudga berdi" turidagi
alohida bosim-relizlari emas, balki kompaniyaning o'zi e'lon qilgan, kripto/
raqamli aktivga oid muhim voqealar (masalan katta jarima, tekshiruv haqida
xabar, yangi tartibga solish ta'siri). Amalda bu SEC yangiliklarining katta
qismini qamrab oladi, lekin hammasini emas — ishlash sifati production
loglarida kuzatilib, kerak bo'lsa kengaytiriladi.

Bu modul Telegram'ga umuman bog'liq emas — faqat toza ma'lumot qaytaradi
(`bot.py` postlaydi). Xato bo'lsa bo'sh ro'yxat qaytaradi, hech qachon
istisno tashlamaydi — bitta manba vaqtincha ishlamay qolishi butun
`news_scan_job`ni to'xtatmasligi kerak.
"""
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("news")

SEC_URL = "https://efts.sec.gov/LATEST/search-index"
# SEC "fair access" qoidalari User-Agent'da aloqa ma'lumotini talab qiladi
# (aks holda so'rovlar rad etilishi mumkin).
SEC_HEADERS = {"User-Agent": "TradeController contact@tradecontroller.bot"}

# Kripto/raqamli aktivga oid hujjatlarni topish uchun kalit so'zlar. Keng
# boshlangan — amalda ortiqcha shovqin chiqsa toraytiriladi.
SEC_KEYWORDS = ["cryptocurrency", "digital asset", "digital assets"]
SEC_FORMS = "8-K"   # eng "yangilik"ga o'xshash forma turi — favqulodda voqealar


async def sec_scan(since: datetime) -> list[dict]:
    """`since`dan beri topshirilgan, kalit so'zlardan birini o'z ichiga
    olgan 8-K hujjatlarini qaytaradi.

    Natija: `{external_key, symbol, market, headline_en, body_en, event_at,
    source_url}`. `symbol` doim `None` — hujjat matnida qaysi tiker
    nazarda tutilgani `newsai.analyze()` bosqichida (LLM orqali) taxmin
    qilinadi, bu yerda faqat kompaniya nomi bor."""
    out: list[dict] = []
    async with httpx.AsyncClient(headers=SEC_HEADERS, timeout=15.0) as client:
        for kw in SEC_KEYWORDS:
            try:
                r = await client.get(SEC_URL, params={
                    "q": f'"{kw}"',
                    "forms": SEC_FORMS,
                    "startdt": since.strftime("%Y-%m-%d"),
                    "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                })
                r.raise_for_status()
                data = r.json()
            except Exception:
                log.warning("SEC qidiruv muvaffaqiyatsiz (%s)", kw, exc_info=True)
                continue

            for hit in data.get("hits", {}).get("hits", []):
                src = hit.get("_source", {})
                adsh = src.get("adsh")           # accession number — dedup kaliti
                if not adsh:
                    continue
                names = src.get("display_names") or []
                company = names[0] if names else "Noma'lum kompaniya"
                file_date = src.get("file_date")
                try:
                    event_at = datetime.strptime(file_date, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    event_at = datetime.now(timezone.utc)

                cik = (src.get("ciks") or [None])[0]
                doc_id = hit.get("_id", "")
                source_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{doc_id}"
                    if cik and doc_id else "https://www.sec.gov/search-filings")

                out.append({
                    "source": "sec",
                    "external_key": f"sec:{adsh}",
                    "symbol": None,
                    "market": None,
                    "headline_en": f"{company} filed a {src.get('form', SEC_FORMS)} "
                                   f"mentioning \"{kw}\"",
                    "body_en": f"Company: {company}. Filed: {file_date}. "
                               f"Matched keyword: {kw}.",
                    "event_at": event_at,
                    "source_url": source_url,
                })

    # Bitta hujjat bir necha kalit so'zga to'g'ri kelishi mumkin (masalan
    # ham "cryptocurrency" ham "digital asset" so'zlarini o'z ichiga olsa) —
    # bazadagi UNIQUE cheklov baribir takrorini rad etardi, lekin shu yerda
    # oldindan tozalash keyingi bosqichda (AI tahlil) bekorga ishlamasligi
    # uchun.
    seen: set[str] = set()
    deduped = []
    for item in out:
        if item["external_key"] in seen:
            continue
        seen.add(item["external_key"])
        deduped.append(item)
    return deduped
