"""Ruscha matnni o'zbekchaga tarjima qilish — MarketTwits kabi AI'siz
manbalar uchun (Anthropic kredit tugagani sabab AI ishlatilmaydi, bot.py
87-band izohiga qarang).

Google Translate'ning norasmiy endpoint'i (`translate.googleapis.com`)
SINALDI — avtomatlashtirilgan so'rovlarni bloklaydi (429 "Sorry...").
Shu sabab MyMemory (`api.mymemory.translated.net`) ishlatiladi — bu
xuddi shu maqsad uchun MAXSUS qurilgan, RASMIY, kalitsiz bepul API
(kunlik so'rov chegarasi bor, lekin avtomatlashtirishni bloklamaydi)."""
import logging

import httpx

log = logging.getLogger("translate")

BASE_URL = "https://api.mymemory.translated.net/get"
MAX_CHARS = 480   # MyMemory'ning kalitsiz so'rovdagi taxminiy chegarasi


async def to_uz(text: str, source: str = "ru") -> str | None:
    """Muvaffaqiyatsiz bo'lsa (tarmoq xatosi, kunlik limit tugagani va h.k.)
    `None` — chaqiruvchi asl matnga qaytishi kerak (tarjima ixtiyoriy,
    hech narsani bloklamaydi)."""
    text = text.strip()
    if not text:
        return text
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(BASE_URL, params={
                "q": text[:MAX_CHARS], "langpair": f"{source}|uz",
            })
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("Tarjima so'rovi muvaffaqiyatsiz", exc_info=True)
        return None

    translated = (data.get("responseData") or {}).get("translatedText")
    if not translated or "MYMEMORY WARNING" in translated.upper():
        log.warning("Tarjima natijasi yaroqsiz: %r", translated)
        return None
    return translated
