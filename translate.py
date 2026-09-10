"""Begona tildagi matnni o'zbekchaga tarjima qilish — MarketTwits kabi
manbalar uchun. News Trade kanaliga FAQAT o'zbekcha matn chiqadi
(foydalanuvchi talabi), shuning uchun tarjima ixtiyoriy bezak emas,
quvurning majburiy bosqichi.

UCH MANBA KETMA-KET SINALADI:
  0. Azure Translator (rasmiy, kalitli, `config.AZURE_TRANSLATOR_KEY`
     bo'lsa) — ASOSIY. Bepul rejasi (F0) oyiga 2 million belgi,
     DOIMIY, va o'zbek tilini RASMAN qo'llab-quvvatlaydi. Kalit
     berilmasa bu bosqich butunlay o'tkazib yuboriladi — eski
     xatti-harakat (pastdagi ikkovi) o'zgarishsiz qoladi.
  1. MyMemory (`api.mymemory.translated.net`) — aynan shu maqsad uchun
     qurilgan rasmiy bepul API. `config.TRANSLATE_EMAIL` so'rovga
     qo'shiladi (tasdiqlanishi SHART EMAS) — hujjatga ko'ra kunlik
     limitni sezilarli ko'taradi.
  2. Google'ning `translate_a/single` (gtx) endpointi — norasmiy, ba'zan
     429 qaytaradi, lekin BEPUL va MyMemory yiqilganda ko'pincha
     ishlaydi. Shuning uchun u ZAXIRA: MyMemory ishlaganda umuman
     chaqirilmaydi.

⚠️ MUAMMO (production, 2026-09-10 tasdiqlangan): MyMemory soat 04:19
dan boshlab HAR bir so'rovga 429 berib qoldi (kunlik limit), soat
07:25 dan Google ham 429 bera boshladi — ikkalasi bir vaqtda tugab,
News Trade kanali soatlab matnsiz (faqat havola bilan) post berdi.
Azure shu holatga qarshi zaxira: uning limiti shu ikkovidan necha
o'n barobar katta.

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

AZURE_URL = "https://api.cognitive.microsofttranslator.com/translate"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MAX_CHARS = 480     # MyMemory'ning kalitsiz so'rovdagi taxminiy chegarasi
AZURE_MAX_CHARS = 5000   # Azure so'rov boshiga ~50 000 — bu yerga hech
                         # qachon yetmaydigan katta zaxira bilan

TIMEOUT = 20.0
ATTEMPTS = 3      # har qanday xato (timeout/tarmoq/429) uchun

CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


async def _request(text: str, source: str) -> httpx.Response:
    params = {"q": text[:MAX_CHARS], "langpair": f"{source}|uz"}
    if config.TRANSLATE_EMAIL:
        params["de"] = config.TRANSLATE_EMAIL
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return await client.get(MYMEMORY_URL, params=params)


async def _azure(text: str, source: str) -> str | None:
    """Rasmiy, kalitli tarjimon. `config.AZURE_TRANSLATOR_KEY` bo'sh
    bo'lsa chaqirilmaydi ham (`to_uz()` ichida tekshiriladi).

    So'rov/javob shakli boshqa ikkovidan farqli — JSON MASSIV: bir
    so'rovda bir nechta matn yuborish mumkin, biz esa har doim bitta
    element yuboramiz, shuning uchun javobning birinchi elementi
    olinadi."""
    headers = {"Ocp-Apim-Subscription-Key": config.AZURE_TRANSLATOR_KEY,
              "Content-Type": "application/json"}
    if config.AZURE_TRANSLATOR_REGION:
        headers["Ocp-Apim-Subscription-Region"] = config.AZURE_TRANSLATOR_REGION
    params = {"api-version": "3.0", "from": source, "to": "uz"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(AZURE_URL, params=params, headers=headers,
                                  json=[{"Text": text[:AZURE_MAX_CHARS]}])
        r.raise_for_status()
        data = r.json()
        return data[0]["translations"][0]["text"].strip() or None
    except Exception:
        log.warning("Azure tarjimasi muvaffaqiyatsiz", exc_info=True)
        return None


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

    chain = [("MyMemory", _mymemory), ("Google", _google)]
    if config.AZURE_TRANSLATOR_KEY:
        chain.insert(0, ("Azure", _azure))
    for name, fn in chain:
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
