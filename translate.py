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

import httpx

import config

log = logging.getLogger("translate")

BASE_URL = "https://api.mymemory.translated.net/get"
MAX_CHARS = 480   # MyMemory'ning kalitsiz so'rovdagi taxminiy chegarasi


async def _request(text: str, source: str) -> httpx.Response:
    params = {"q": text[:MAX_CHARS], "langpair": f"{source}|uz"}
    if config.TRANSLATE_EMAIL:
        params["de"] = config.TRANSLATE_EMAIL
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.get(BASE_URL, params=params)


async def to_uz(text: str, source: str = "ru") -> str | None:
    """Muvaffaqiyatsiz bo'lsa (tarmoq xatosi, kunlik limit tugagani va h.k.)
    `None` — chaqiruvchi asl matnga qaytishi kerak (tarjima ixtiyoriy,
    hech narsani bloklamaydi)."""
    text = text.strip()
    if not text:
        return text
    try:
        r = await _request(text, source)
        if r.status_code == 429:
            await asyncio.sleep(3)
            r = await _request(text, source)
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.warning("Tarjima so'rovi muvaffaqiyatsiz", exc_info=True)
        return None

    translated = (data.get("responseData") or {}).get("translatedText")
    if not translated or "MYMEMORY WARNING" in translated.upper():
        log.warning("Tarjima natijasi yaroqsiz: %r", translated)
        return None
    return html.unescape(translated)
