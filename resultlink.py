"""Eski yopilgan savdolarning natija postini topish (210).

`signals.result_msg_id` 209-banddan beri saqlanadi; undan oldin yopilgan
savdolarda u yo'q. Bot API'da chat tarixini o'qish yo'q, shuning uchun
xabar mazmuni va sanasi uni xizmat chatiga (super-admin DM) JIMGINA
forward qilib bilinadi va forward darhol o'chiriladi.

Qidiruv:
  1. Oraliq: [signal posti + 1, shu workspace'dagi `closed_at`dan kamida
     1 soat keyin yuborilgan istalgan ma'lum post id'si]. Bunday "yuqori
     langar" hali yo'q bo'lsa signal keyinroq olinadi (yangi natijalar
     id'si saqlanadi va langar paydo bo'ladi).
  2. Xabar id'lari vaqt bo'yicha o'sadi — ikkilik qidiruv bilan
     `closed_at - 3 daqiqa`dagi birinchi xabar topiladi.
  3. Undan keyingi ko'pi bilan `SCAN` ta xabardan "#<id> <juftlik>"
     yozuvi bor OXIRGISI — natija posti (yopilish signalning oxirgi
     hodisasi). Rasmli (natija grafigi) xabar ustun.
Topilmasa ham `result_msg_tried` belgilanadi — sahifa signal postiga
olib boradi (natija o'sha postga javob sifatida turibdi).
"""
import asyncio
import logging
from datetime import timedelta

import config
import db

log = logging.getLogger(__name__)

PAUSE = 0.35            # Telegram so'rovlari orasida (xizmat chatiga ~1.5/s)
SCAN = 60               # topilgan nuqtadan keyin ko'rib chiqiladigan xabarlar
PER_RUN = 4             # bir siklda nechta signal
_cache: dict[tuple[int, int], tuple | None] = {}   # (chat, msg) -> (date, text, photo)
_dead_chats: set[int] = set()                       # forward taqiqlangan chatlar
_ok_chats: set[int] = set()                         # kamida bitta forward o'tgan
_fails: dict[int, int] = {}


def _dump_chat() -> int | None:
    # ADMIN_IDS — to'plam; doim bir xil admin tanlansin.
    return min(config.ADMIN_IDS) if config.ADMIN_IDS else None


async def _probe(bot, chat_id: int, mid: int):
    """(sana, matn, rasmmi) yoki None (o'chirilgan / xizmat xabari)."""
    key = (chat_id, mid)
    if key in _cache:
        return _cache[key]
    dump = _dump_chat()
    info = None
    try:
        m = await bot.forward_message(dump, chat_id, mid, disable_notification=True)
        origin = getattr(m, "forward_origin", None)
        date = getattr(origin, "date", None) or m.date
        info = (date, m.caption or m.text or "", bool(m.photo))
        try:
            await bot.delete_message(dump, m.message_id)
        except Exception:
            pass
        _ok_chats.add(chat_id)
    except Exception as ex:
        msg = str(ex).lower()
        if "retry" in msg or "flood" in msg:
            raise
        # Kontent himoyalangan chatda HAR forward rad etiladi. Bitta rad
        # (o'chirilgan/xizmat xabari) yetarli emas — hech biri o'tmagan
        # holda 12 ta ketma-ket rad bo'lsa chat tashlab qo'yiladi.
        if chat_id not in _ok_chats:
            _fails[chat_id] = _fails.get(chat_id, 0) + 1
            if _fails[chat_id] >= 12:
                _dead_chats.add(chat_id)
                log.info("Natija posti qidiruvi: chatdan forward qilib bo'lmaydi (%s)", chat_id)
    _cache[key] = info
    await asyncio.sleep(PAUSE)
    return info


async def _near(bot, chat_id: int, mid: int, hi: int):
    """`mid` yoki undan keyingi (5 tagacha, `hi`dan oshmay) mavjud xabar."""
    for k in range(mid, min(mid + 5, hi + 1)):
        info = await _probe(bot, chat_id, k)
        if info:
            return k, info
    return None, None


async def find_result(bot, chat_id: int, sid: int, sym: str, lo: int, hi: int,
                      closed_at) -> int | None:
    if len(_cache) > 50_000:
        _cache.clear()
    target = closed_at - timedelta(minutes=3)
    # Ikkilik qidiruv: sanasi `target`dan kichik bo'lmagan birinchi xabar.
    while lo < hi and chat_id not in _dead_chats:
        mid = (lo + hi) // 2
        k, info = await _near(bot, chat_id, mid, hi)
        if k is None:
            hi = mid          # bo'sh joy — chapdan qidiramiz
            continue
        if info[0] < target:
            lo = k + 1
        else:
            hi = mid
    if chat_id in _dead_chats:
        return None
    tag = f"#{sid} {sym}"
    best = best_photo = None
    for k in range(lo, lo + SCAN):
        info = await _probe(bot, chat_id, k)
        if not info:
            continue
        if info[0] > closed_at + timedelta(hours=2):
            break
        if tag in info[1]:
            best = k
            if info[2]:
                best_photo = k
    return best_photo or best


async def run(bot) -> int:
    """Bir sikl: bir nechta signal uchun natija postini qidiradi.
    Qaytaradi: topilganlar soni."""
    if not _dump_chat():
        return 0
    found = 0
    for r in await db.result_link_targets(PER_RUN):
        chat = r["group_chat_id"]
        res = None
        if chat not in _dead_chats:
            try:
                res = await find_result(bot, chat, r["id"], r["symbol"],
                                        r["group_msg_id"] + 1, r["hi"], r["closed_at"])
            except Exception as ex:
                log.warning("Natija posti qidiruvi to'xtadi (#%s): %s", r["id"], ex)
                return found       # flood — keyingi siklda davom
        if res is None and not _ok_chats:
            # Hali birorta forward o'tmagan — balki xizmat chati (admin DM)
            # ishlamayapti. Bunda "topilmadi" deb belgilash noto'g'ri bo'lardi.
            log.warning("Natija posti qidiruvi: birorta forward o'tmadi — "
                        "admin botni bloklaganmi? (dump=%s)", _dump_chat())
            return found
        await db.set_result_found(r["id"], res)
        if res:
            found += 1
    if found:
        log.info("Eski natija postlari topildi: %s ta", found)
    return found
