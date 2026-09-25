"""Pay Members platformasi bilan ulanish (whaleuzb/paymembers).

NEGA: foydalanuvchi talabi — "yopiq guruhni botga qo'shish tekin, ammo
unga qo'shilish tugmasini chiqarish uchun faqat Pay Members orqali
yaratilgan bot orqaligina link qo'ya olsin". Ya'ni yopiq guruh/kanalning
ochiq sahifasi va /top reytingidagi "Qo'shilish" havolasi ixtiyoriy
havola emas, shu guruhni boshqaradigan Pay Members to'lov botining
manzili bo'ladi.

Tekshiruv Pay Members'ning `/api/signals/chat-bot` endpointi orqali:
u `chat_id` bo'yicha FAOL (status=active) egasining bot username'ini
qaytaradi. Kalit — `config.PAYMEMBERS_API_KEY` (Pay Members'da
`SIGNALS_API_KEY`).

Ikki xil "yo'q" ATAYLAB ajratilgan: `None` — platforma aniq "bu chat
bizda yo'q" dedi (tugmani olib tashlash mumkin), `Unavailable` — javob
olinmadi (tarmoq, kalit, 5xx). Ikkinchisida hech narsa o'zgartirilmaydi:
platforma bir soat ishlamay qolsa, barcha guruhlarning tugmasi o'chib
ketmasligi kerak.
"""
import re

import httpx

import config

_USERNAME = re.compile(r"[A-Za-z0-9_]{4,32}")


class Unavailable(Exception):
    """Pay Members'dan aniq javob olinmadi — holatni o'zgartirmang."""


async def bot_for_chat(chat_id: int) -> str | None:
    """Shu guruh/kanalni boshqaradigan faol Pay Members botining username'i
    (`@`siz), ro'yxatda bo'lmasa `None`."""
    if not config.PAYMEMBERS_API_KEY:
        raise Unavailable("PAYMEMBERS_API_KEY sozlanmagan")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{config.PAYMEMBERS_URL}/api/signals/chat-bot",
                            params={"chat_id": chat_id},
                            headers={"X-Api-Key": config.PAYMEMBERS_API_KEY})
    except httpx.HTTPError as e:
        raise Unavailable(f"tarmoq xatosi: {e!r}") from e
    if r.status_code != 200:
        raise Unavailable(f"HTTP {r.status_code}")
    try:
        name = r.json().get("bot_username")
    except (ValueError, AttributeError) as e:
        raise Unavailable("javob JSON emas") from e
    if name is None:
        return None
    # Qiymat HTML va havolaga to'g'ridan-to'g'ri tushadi — faqat Telegram
    # username shaklidagisi qabul qilinadi.
    if not isinstance(name, str) or not _USERNAME.fullmatch(name):
        raise Unavailable(f"yaroqsiz username: {name!r}")
    return name


def join_url(ws) -> str | None:
    """Guruh/kanalga qo'shilish havolasi — BITTA joyda (bot va sahifa).

    Ochiq @nik bo'lsa — o'sha (ommaviy guruh/kanal, bepul). Yopiq bo'lsa —
    FAQAT Pay Members tasdiqlagan to'lov boti. Boshqa hech qanday havola
    (eski `invite_link` ham) ishlatilmaydi."""
    if ws["username"]:
        return f"https://t.me/{ws['username']}"
    if ws["pm_bot"]:
        return f"https://t.me/{ws['pm_bot']}"
    return None
