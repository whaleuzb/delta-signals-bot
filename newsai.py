"""Yangilik matnini tahlil qilish — o'zbekchaga tarjima, qisqa xulosa,
"bu bozorni haqiqatan qimirlatadimi" filtri va qaysi tiker nazarda
tutilganini topish.

LLM (Claude) ATAYLAB YO'Q. Foydalanuvchi: "Antropic api kerakmas" — kalit
yaroqsiz bo'lib kanal jim qolgan edi, endi hammasi pulsiz va kalitsiz:
  - tiker — manba matnidan (SEC `display_names` dagi "(MSTR)", Upbit
    sarlavhasidagi "Bitcoin(BTC)") qoida bilan olinadi;
  - filtr — tiker topilmasa yoki e'lon listing/delisting emas bo'lsa
    "muhim emas" (avval Claude qilgan saralashning qoidaviy o'rni);
  - xulosa — shablon (kalit so'z -> o'zbekcha ibora lug'ati);
  - tarjima — `translate.to_uz()` (Azure/MyMemory/Google, bepul), u
    ham yiqilsa shablon matni;
  - iqtisodiy natija — `econcalendar.title_uz()` lug'ati bilan ANIQ
    formatdagi xabar.
Chaqiruvchilar (`bot.py`) uchun interfeys o'zgarmagan: `analyze()` va
`econ_result()` avvalgidek dict yoki `None` qaytaradi."""
import logging
import re
from datetime import datetime

import econcalendar
import translate

log = logging.getLogger("newsai")

# --- SEC 8-K: kalit so'z -> (xulosa, tavsif) ---
SEC_PHRASES = {
    "cryptocurrency": ("kriptovalyuta bo'yicha muhim hujjat",
                       "kriptovalyutaga oid voqea haqida 8-K hisobot topshirdi"),
    "digital asset": ("raqamli aktivlar bo'yicha hujjat",
                      "raqamli aktivlarga oid voqea haqida 8-K hisobot topshirdi"),
    "digital assets": ("raqamli aktivlar bo'yicha hujjat",
                       "raqamli aktivlarga oid voqea haqida 8-K hisobot topshirdi"),
    "merger agreement": ("qo'shilish bitimini e'lon qildi",
                         "qo'shilish (merger) bitimi haqida 8-K hisobot topshirdi"),
    "definitive agreement to acquire": ("yirik xarid bitimi",
                                        "boshqa kompaniyani sotib olish bo'yicha yakuniy "
                                        "bitim haqida 8-K hisobot topshirdi"),
    "chapter 11": ("bankrotlik (Chapter 11)",
                   "Chapter 11 bo'yicha bankrotlik jarayoni haqida 8-K hisobot topshirdi"),
    "going concern": ("faoliyat davomiyligi xavf ostida",
                      "faoliyatini davom ettira olishiga shubha (going concern) "
                      "haqida 8-K hisobot topshirdi"),
    "notice of delisting": ("birjadan chiqarish ogohlantirishi",
                            "birjadan chiqarib tashlash bildirishnomasi haqida "
                            "8-K hisobot topshirdi"),
    "restatement of previously issued financial statements": (
        "hisobotlar qayta ko'rib chiqiladi",
        "avval e'lon qilingan moliyaviy hisobotlarni qayta ko'rib chiqishi haqida "
        "8-K hisobot topshirdi"),
    "material weakness in internal control": (
        "ichki nazoratda jiddiy kamchilik",
        "ichki nazoratdagi jiddiy kamchilik haqida 8-K hisobot topshirdi"),
    "event of default": ("qarz majburiyati buzildi",
                         "qarz majburiyatini bajarmaslik (event of default) haqida "
                         "8-K hisobot topshirdi"),
}

SEC_HEAD_RE = re.compile(r'^(?P<company>.+?) filed a (?P<form>\S+) mentioning "(?P<kw>[^"]+)"')
# EDGAR display_names: "Tesla, Inc.  (TSLA)  (CIK 0001318605)" — bir nechta
# klass bo'lsa "(BRK-A, BRK-B)".
SEC_TICKER_RE = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})(?:,\s*[A-Z0-9.\-]+)*\)")
SEC_CIK_RE = re.compile(r"\s*\(CIK \d+\)")

# --- Upbit ---
# "비트코인(BTC)", "Sapien(SAPIEN)" — qavs ichida bitta katta harfli tiker.
COIN_RE = re.compile(r"\(([A-Z0-9]{2,12})\)")
MARKET_WORDS = {"KRW", "BTC", "USDT"}  # "(KRW, BTC, USDT 마켓)" — tiker emas
DELIST_WORDS = ("거래지원 종료", "상장폐지", "termination", "delist")
NOISE_WORDS = ("유의", "점검", "이벤트", "caution", "maintenance", "event")


def _sec_ticker(company: str) -> str | None:
    m = SEC_TICKER_RE.search(SEC_CIK_RE.sub("", company))
    return m.group(1).replace("-", ".") if m else None


def _sec_company(company: str) -> str:
    name = SEC_CIK_RE.sub("", company)
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() or company


async def _sec(headline: str) -> dict | None:
    m = SEC_HEAD_RE.match(headline)
    if not m:
        return None
    kw = m.group("kw").lower()
    phrase = SEC_PHRASES.get(kw)
    ticker = _sec_ticker(m.group("company"))
    name = _sec_company(m.group("company"))
    if phrase is None or ticker is None:
        # Tiker yo'q = birjada savdo qilinmaydigan (yoki aniqlab bo'lmaydigan)
        # kompaniya — grafik ham, savdo tugmasi ham bo'lmaydi, postlamaymiz.
        return {"is_market_moving": False, "translation_uz": "", "insight_uz": "",
                "symbol_hint": None}
    insight, desc = phrase
    return {
        "is_market_moving": True,
        "insight_uz": f"{ticker}: {insight}",
        "translation_uz": f"{name} ({ticker}) SEC'ga {desc}.",
        "symbol_hint": ticker,
    }


async def _upbit(title: str) -> dict:
    low = title.lower()
    coins = [c for c in COIN_RE.findall(title) if c not in MARKET_WORDS]
    delist = any(w in low for w in DELIST_WORDS)
    # `listings.upbit_scan()` allaqachon LISTING_KEYWORDS bilan saralagan
    # ("디지털 자산 추가" kabi e'lonlar ham shu yerga keladi) — bu yerda
    # faqat tiker borligi va shovqin (ogohlantirish/texnik ish) tekshiriladi.
    if not coins or any(w in low for w in NOISE_WORDS):
        return {"is_market_moving": False, "translation_uz": "", "insight_uz": "",
                "symbol_hint": None}
    coin = coins[0]
    others = f" (+{len(coins) - 1} ta boshqa)" if len(coins) > 1 else ""
    if delist:
        insight = f"Upbit {coin} savdosini to'xtatadi"
        fallback = f"Upbit birjasi {coin}{others} savdosini qo'llab-quvvatlashni tugatishini e'lon qildi."
    else:
        insight = f"Upbit'da yangi listing: {coin}"
        fallback = f"Upbit birjasi {coin}{others} uchun savdo boshlanishini e'lon qildi."
    src = "en" if title.isascii() else "ko"
    tr = await translate.to_uz(title, source=src)
    return {
        "is_market_moving": True,
        "insight_uz": insight,
        "translation_uz": f"{fallback}\n{tr}" if tr and tr != title else fallback,
        "symbol_hint": coin,
    }


async def analyze(headline_en: str, body_en: str) -> dict | None:
    """`None` — matnni tanib bo'lmadi (chaqiruvchi postlamaydi).
    `is_market_moving=False` — tanildi, lekin kanalga arzimaydi."""
    try:
        if SEC_HEAD_RE.match(headline_en or ""):
            return await _sec(headline_en)
        return await _upbit(headline_en or "")
    except Exception:
        log.exception("Yangilik tahlili xato")
        return None


# --- Iqtisodiy taqvim natijasi ---
UZ_MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul",
             "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"]

# (kalit so'z, teg, kategoriya) — birinchi mos kelgani olinadi.
ECON_TOPICS = [
    (("cpi", "ppi", "pce", "inflation"), "inflyatsiya", "INFLYATSIYA"),
    (("federal funds", "fomc", "fed "), "stavka", "FOIZ STAVKASI"),
    (("unemployment", "employment", "payroll", "earnings", "jolts"),
     "mehnat_bozori", "MEHNAT BOZORI"),
    (("gdp",), "yaim", "YAIM"),
    (("retail",), "chakana_savdo", "CHAKANA SAVDO"),
    (("pmi", "manufacturing", "industrial", "durable", "factory", "capacity"),
     "sanoat", "SANOAT"),
    (("home", "housing", "building"), "uy_joy", "UY-JOY BOZORI"),
    (("consumer", "personal"), "istemol", "ISTE'MOL"),
    (("oil", "gas"), "energetika", "ENERGETIKA"),
]
CHANGE_RE = re.compile(r"\b(m/m|q/q|y/y)\s*$", re.I)
NUM_RE = re.compile(r"^-?\d")


def _signed(value: str, change: bool) -> str:
    v = (value or "").strip()
    if not v:
        return "—"
    if change and NUM_RE.match(v) and not v.startswith("-"):
        return "+" + v
    return v


def _topic(title: str) -> tuple[str, str]:
    low = title.lower()
    for words, tag, cat in ECON_TOPICS:
        if any(w in low for w in words):
            return tag, cat
    return "makro", "MAKROIQTISODIYOT"


def _moving(e: dict) -> bool:
    """"High" — har doim; "Medium" — faqat natija kutilganidan farq qilsa."""
    if str(e.get("impact", "")).lower() == "high":
        return True
    return (e.get("actual") or "").strip() != (e.get("forecast") or "").strip()


def econ_message(events: list[dict]) -> str:
    done = [e for e in events if (e.get("actual") or "").strip()]
    if not done:
        return ""
    tag, cat = _topic(done[0]["title"])
    when: datetime = done[0]["when"]
    month = UZ_MONTHS[(when.month - 2) % 12]
    head = econcalendar.title_uz(done[0]["title"])
    head = CHANGE_RE.sub("", head).replace("(oylik)", "").replace(
        "(choraklik)", "").replace("(yillik)", "").strip()
    lines = [f"❗️🇺🇸 #aqsh #{tag} #iqtisodiyot #hisobot",
             f"AQSh - {cat} - {head.upper()} ({month}):", ""]
    for e in done:
        change = bool(CHANGE_RE.search(e["title"]))
        lines.append(f"{econcalendar.title_uz(e['title'])} = {_signed(e['actual'], change)} "
                     f"(kutilgan {_signed(e.get('forecast'), change)} / "
                     f"oldingi ko'rsatkich {_signed(e.get('previous'), change)})")
    return "\n".join(lines)


async def econ_result(events: list[dict]) -> dict | None:
    """`events` — bir vaqtda chiqqan, `actual`si to'ldirilgan ko'rsatkichlar."""
    try:
        msg = econ_message(events)
    except Exception:
        log.exception("Iqtisodiy natija xabari yasalmadi")
        return None
    done = [e for e in events if (e.get("actual") or "").strip()]
    return {"is_market_moving": bool(msg) and any(_moving(e) for e in done),
            "message_uz": msg}
