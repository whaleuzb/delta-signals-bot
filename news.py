"""News Trade AI — bozorni qimirlatadigan yangiliklarni avtomatik topish.

Hozircha faqat SEC EDGAR: rasmiy, bepul, kalitsiz full-text qidiruv API'si
(`efts.sec.gov`). Bu kompaniyalar TOPSHIRGAN hujjatlarni (8-K, 10-K va h.k.)
kalit so'z bo'yicha qidiradi — "SEC X kompaniyani sudga berdi" turidagi
alohida bosim-relizlari emas, balki kompaniyaning o'zi e'lon qilgan, muhim
voqealar. Ikki toifa kalit so'z bilan qidiriladi: kripto/raqamli aktivga
oid (masalan katta jarima, tekshiruv haqida xabar) va aksiyaga katta
ta'sir qiladigan yirik korporativ hodisalar (bankrotlik, qo'shilish/
yutib olish, birjadan chiqarib tashlash, hisobotni qayta ko'rib chiqish).
`symbol_hint` orqali qaysi kompaniya/token ekanligi aniqlangach, `bot.py`
uni kripto/aksiya/forex bozorlaridan mos kelganini avtomatik topadi —
shu sabab bitta manba ikkala toifani ham qamrab oladi. Amalda bu SEC
yangiliklarining katta qismini qamrab oladi, lekin hammasini emas —
ishlash sifati production loglarida kuzatilib, kerak bo'lsa kengaytiriladi.

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
SEC_CRYPTO_KEYWORDS = ["cryptocurrency", "digital asset", "digital assets"]

# Aksiyaga (kompaniya qimmatli qog'ozlariga) katta ta'sir qiladigan 8-K
# hodisa turlari — SEC'ning o'z "Item" nomlanishiga mos iboralar: Item 1.03
# (bankrotlik), Item 3.01 (birjadan chiqarib tashlash bildirishnomasi),
# Item 4.02 (moliyaviy hisobotni qayta ko'rib chiqish — jiddiy hisob
# muammosi belgisi), Item 1.01/2.01 (yirik bitim/qo'shilish), moliyaviy
# majburiyatni bajarmaslik. Kundalik/rutin hujjatlar (oddiy chorak
# hisoboti va h.k.) ataylab QOLDIRILGAN — listing/delisting'da bo'lgani
# kabi faqat YIRIK voqealar kerak; amalda production loglarida kuzatilib
# kerak bo'lsa toraytiriladi/kengaytiriladi.
SEC_STOCK_KEYWORDS = [
    "merger agreement",
    "definitive agreement to acquire",
    "chapter 11",
    "going concern",
    "notice of delisting",
    "restatement of previously issued financial statements",
    "material weakness in internal control",
    "event of default",
]

# 204: matnda ibora UCHRASHI yetarli emas edi — "merger agreement" ko'p
# 8-K'larda yo'l-yo'lakay (ilova, eski bitimga havola, rahbar shartnomasi)
# tilga olinadi va kanalga tushunarsiz "WSO: qo'shilish bitimi" postlari
# chiqardi. Endi aksiya hujjati faqat SEC bergan rasmiy 8-K TURI (Item)
# shu voqeaga mos bo'lsa olinadi.
SEC_KEYWORD_ITEMS = {
    "merger agreement": {"1.01", "2.01"},
    "definitive agreement to acquire": {"1.01", "2.01"},
    "chapter 11": {"1.03"},
    "going concern": {"1.03", "2.06", "4.02"},
    "notice of delisting": {"3.01"},
    "restatement of previously issued financial statements": {"4.02"},
    "material weakness in internal control": {"4.02"},
    "event of default": {"2.04"},
}

# 205: foydalanuvchi — aksiya bo'yicha SEC postlari "kerak emas, juda ko'p
# kelyapti". Faqat kripto kalit so'zlari qidiriladi; aksiya ro'yxati va
# Item filtri (204) qayta yoqish uchun kodda qoldirildi.
SEC_KEYWORDS = list(SEC_CRYPTO_KEYWORDS)
_items_missing_logged = False
SEC_FORMS = "8-K"   # eng "yangilik"ga o'xshash forma turi — favqulodda voqealar


async def sec_scan(since: datetime) -> list[dict]:
    """`since`dan beri topshirilgan, kalit so'zlardan birini o'z ichiga
    olgan 8-K hujjatlarini qaytaradi.

    Natija: `{external_key, symbol, market, headline_en, body_en, event_at,
    source_url}`. `symbol` doim `None` — hujjat matnida qaysi tiker
    nazarda tutilgani `newsai.analyze()` bosqichida (`display_names`dagi
    tiker bo'yicha) aniqlanadi, bu yerda faqat kompaniya nomi bor."""
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
                need = SEC_KEYWORD_ITEMS.get(kw)
                items = [str(i) for i in (src.get("items") or [])]
                matched: list[str] = []
                if need is not None:
                    if "items" not in src:
                        # Format kutilganidek bo'lmasa — shovqin postlamaymiz,
                        # logda ko'rinadi (sandboxdan tekshirib bo'lmadi).
                        global _items_missing_logged
                        if not _items_missing_logged:
                            _items_missing_logged = True
                            log.warning("SEC: javobda 'items' maydoni yo'q — aksiya "
                                        "hujjatlari o'tkazib yuboriladi (maydonlar: %s)",
                                        sorted(src.keys()))
                        continue
                    matched = sorted(set(items) & need)
                    if not matched:
                        log.debug("SEC: %s %r — 8-K turi %s mos emas, o'tkazildi",
                                 adsh, kw, items)
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
                                   f"mentioning \"{kw}\""
                                   + (f" [items {','.join(matched)}]" if matched else ""),
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
