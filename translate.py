"""Begona tildagi matnni o'zbekchaga tarjima qilish — MarketTwits kabi
manbalar uchun. News Trade kanaliga FAQAT o'zbekcha matn chiqadi
(foydalanuvchi talabi), shuning uchun tarjima ixtiyoriy bezak emas,
quvurning majburiy bosqichi.

IKKI TEKIN, KALITSIZ manba ketma-ket sinaladi:
  1. MyMemory (`api.mymemory.translated.net`) — aynan shu maqsad uchun
     qurilgan rasmiy bepul API. `config.TRANSLATE_EMAIL` so'rovga
     qo'shiladi (tasdiqlanishi SHART EMAS) — hujjatga ko'ra kunlik
     limitni sezilarli ko'taradi.
  2. Google'ning `translate_a/single` (gtx) endpointi — norasmiy, ba'zan
     429 qaytaradi, lekin BEPUL va MyMemory yiqilganda ko'pincha
     ishlaydi. Shuning uchun u ZAXIRA: MyMemory ishlaganda umuman
     chaqirilmaydi.

CLAUDE TARJIMONI ATAYLAB YO'Q. Bir muddat zaxira sifatida turgan edi,
foydalanuvchi olib tashlashni so'radi ("claude translate olib tashlash
kerak") — Anthropic krediti tugagan holatda u har bir yiqilishga
bekorga kutish qo'shardi va hech qachon natija bermasdi.

MUHIM (production loglarida tasdiqlangan):
- Kutish 10s edi va `httpx.ReadTimeout` MUNTAZAM uchrardi. Endi 20s.
- Qayta urinish avval FAQAT 429 uchun edi, shuning uchun timeout darhol
  taslim bo'lardi. Endi HAR QANDAY xato uchun qayta urinadi.
- MyMemory ko'p qatorli matndagi qator ko'chirishlarni ba'zan HTML
  SON-ENTITY sifatida (`&#10;`) qaytaradi — natija shu yerning o'zida
  `html.unescape()` qilinadi, aks holda `bot.py` uni ikkinchi marta
  kodlab, foydalanuvchiga xom `&#10;` ko'rinardi.
"""
import asyncio
import html
import json
import logging
import re

import httpx

import config

log = logging.getLogger("translate")

MYMEMORY_URL = "https://api.mymemory.translated.net/get"
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MAX_CHARS = 480   # MyMemory'ning kalitsiz so'rovdagi taxminiy chegarasi

TIMEOUT = 20.0
ATTEMPTS = 3      # har qanday xato (timeout/tarmoq/429) uchun

CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


async def _request(text: str, source: str) -> httpx.Response:
    params = {"q": text[:MAX_CHARS], "langpair": f"{source}|uz"}
    if config.TRANSLATE_EMAIL:
        params["de"] = config.TRANSLATE_EMAIL
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await client.get(MYMEMORY_URL, params=params)


async def _mymemory(text: str, source: str) -> str | None:
    """Asosiy tarjimon. HAR QANDAY xatoda qayta urinadi."""
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


async def _google(text: str, source: str) -> str | None:
    """Zaxira tarjimon — norasmiy gtx endpointi, kalitsiz va bepul.

    Javob ichma-ich massiv: `[[["tarjima","asl",...], ...], ...]` —
    birinchi elementdagi bo'laklar KETMA-KET ulanadi (uzun matn bir
    nechta bo'lakka bo'linadi). Format norasmiy, shuning uchun hamma
    narsa ehtiyotkorlik bilan o'qiladi."""
    params = {"client": "gtx", "sl": source, "tl": "uz", "dt": "t",
              "q": text[:MAX_CHARS]}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(GOOGLE_URL, params=params)
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.warning("Google tarjimasi muvaffaqiyatsiz", exc_info=True)
        return None

    try:
        chunks = [c[0] for c in data[0] if isinstance(c, list) and c and c[0]]
    except (TypeError, IndexError, KeyError):
        log.warning("Google javobi kutilmagan shaklda: %r", str(data)[:120])
        return None
    out = "".join(chunks).strip()
    return out or None


async def to_uz(text: str, source: str = "ru") -> str | None:
    """O'zbekcha tarjima yoki `None`.

    `None` = TARJIMA BO'LMADI. Chaqiruvchi asl (begona tildagi) matnga
    QAYTMASLIGI kerak — News Trade kanaliga faqat o'zbekcha matn
    chiqadi. `bot.py` bunday holatda matnsiz, o'zbekcha qisqa post va
    asl xabarga havola yuboradi (kanal jim qolmasligi uchun).

    Natijada kirill harflari QOLSA — tarjima bo'lmagan hisoblanadi
    (MyMemory ba'zan matnni o'zgarishsiz qaytaradi)."""
    text = text.strip()
    if not text:
        return text

    for name, fn in (("MyMemory", _mymemory), ("Google", _google)):
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
