"""Ruscha matnni o'zbekchaga tarjima qilish — MarketTwits kabi AI'siz
manbalar uchun (Anthropic kredit tugagani sabab AI ishlatilmaydi, bot.py
87-band izohiga qarang).

Google Translate'ning norasmiy endpoint'i (`translate.googleapis.com`)
SINALDI — avtomatlashtirilgan so'rovlarni bloklaydi (429 "Sorry...").
Shu sabab MyMemory (`api.mymemory.translated.net`) ishlatiladi — bu
xuddi shu maqsad uchun MAXSUS qurilgan, RASMIY, kalitsiz bepul API.

MUHIM (production loglarida tasdiqlangan): email'siz so'rov ham tez-tez
429 (juda ko'p so'rov) bilan rad etilardi. MyMemory hujjatiga ko'ra
so'rovga ISTALGAN email qo'shilsa (tasdiqlanishi shart EMAS) kunlik
limit sezilarli ko'tariladi — `config.TRANSLATE_EMAIL` shu maqsadda.
429 kelsa bir marta qisqa kutib qayta urinib ko'riladi (vaqtinchalik
tirbandlikni yengish uchun, doimiy limit tugashini emas).

MUHIM: MyMemory ko'p qatorli matndagi qator ko'chirishlarni ba'zan
HTML SON-ENTITY sifatida (`&#10;`) qaytaradi — natijani `html.unescape()`
qilmasdan ishlatilsa, keyinroq `bot.py`dagi `html.escape()` uni ikki marta
kodlab, foydalanuvchiga xom `&#10;` matni ko'rinib qolardi (production'da
tasdiqlangan xato). Shu sabab natija shu yerning o'zida darhol
`html.unescape()` qilinadi."""
import asyncio
import html
import logging
import re

import httpx

import config

log = logging.getLogger("translate")

BASE_URL = "https://api.mymemory.translated.net/get"
MAX_CHARS = 480   # MyMemory'ning kalitsiz so'rovdagi taxminiy chegarasi

# Timeout 10s edi — production loglarida `httpx.ReadTimeout` MUNTAZAM
# uchradi va har biri ruscha post degani edi. MyMemory sekin javob
# beradigan xizmat, 20s kutish arzon.
TIMEOUT = 20.0
ATTEMPTS = 3      # har qanday xato (timeout/tarmoq/429) uchun

CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


async def _request(text: str, source: str) -> httpx.Response:
    params = {"q": text[:MAX_CHARS], "langpair": f"{source}|uz"}
    if config.TRANSLATE_EMAIL:
        params["de"] = config.TRANSLATE_EMAIL
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await client.get(BASE_URL, params=params)


async def _mymemory(text: str, source: str) -> str | None:
    """Bepul, kalitsiz tarjimon. HAR QANDAY xatoda qayta urinadi —
    avval faqat 429 uchun urinilardi va `ReadTimeout` darhol taslim
    bo'lardi (production'da eng ko'p uchragan sabab aynan shu)."""
    for attempt in range(ATTEMPTS):
        try:
            r = await _request(text, source)
            if r.status_code == 429:
                raise httpx.HTTPStatusError("429", request=r.request, response=r)
            r.raise_for_status()
            data = r.json()
        except Exception:
            if attempt == ATTEMPTS - 1:
                log.warning("MyMemory tarjimasi muvaffaqiyatsiz (%s urinish)",
                            ATTEMPTS, exc_info=True)
                return None
            await asyncio.sleep(2 * (attempt + 1))
            continue

        translated = (data.get("responseData") or {}).get("translatedText")
        if not translated or "MYMEMORY WARNING" in translated.upper():
            log.warning("MyMemory natijasi yaroqsiz: %r", translated)
            return None
        return html.unescape(translated)
    return None


async def _claude(text: str, source: str) -> str | None:
    """Zaxira tarjimon. `ANTHROPIC_API_KEY` bo'lmasa yoki kredit tugagan
    bo'lsa jimgina `None` — chaqiruvchi baribir tekshiradi."""
    try:
        import newsai
    except Exception:
        return None
    client = getattr(newsai, "_client", None)
    if client is None:
        return None
    try:
        msg = await client.messages.create(
            model=config.NEWS_MODEL,
            max_tokens=1000,
            system=("Sen tarjimonsan. Berilgan moliyaviy yangilik matnini "
                    "O'ZBEK tiliga tarjima qil. FAQAT tarjimani qaytar — "
                    "izoh, sarlavha yoki qo'shimcha so'z YOZMA. Tikerlar "
                    "(BTC, AAPL), raqamlar va foizlar o'zgarmasin."),
            messages=[{"role": "user", "content": text}],
        )
        out = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return out.strip() or None
    except Exception:
        log.warning("Claude tarjimasi muvaffaqiyatsiz", exc_info=True)
        return None


async def to_uz(text: str, source: str = "ru") -> str | None:
    """O'zbekcha tarjima yoki `None`.

    `None` = TARJIMA BO'LMADI. News Trade kanaliga FAQAT o'zbekcha post
    ketishi kerak (foydalanuvchi: "News trade kanalida xabar faqat uzbek
    tilida kelishi kerak"), shuning uchun chaqiruvchi `None` kelganda
    asl matnga QAYTMASLIGI, postni butunlay o'tkazib yuborishi kerak.

    Ikki bosqich: avval bepul MyMemory, u ishlamasa Claude (kalit bo'lsa).
    Natijada kirill harflari QOLSA — tarjima bo'lmagan hisoblanadi
    (MyMemory ba'zan matnni o'zgarishsiz qaytaradi)."""
    text = text.strip()
    if not text:
        return text

    for name, fn in (("MyMemory", _mymemory), ("Claude", _claude)):
        got = await fn(text, source)
        if not got:
            continue
        if CYRILLIC_RE.search(got):
            # Tarjima "bo'ldi", lekin natija hamon ruscha — bu tarjima emas.
            log.warning("%s natijasida kirill qoldi, rad etildi: %r",
                        name, got[:80])
            continue
        return got
    return None
