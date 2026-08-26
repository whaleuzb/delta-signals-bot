"""MarketTwits (va shunga o'xshash) Telegram kanallaridan tezkor
yangiliklarni userbot (Telethon, MTProto) orqali jonli tinglaydi.

Nima uchun oddiy Bot API emas: bizning bot faqat O'ZI ADMIN qilib
qo'shilgan kanallarni "eshitadi" — MarketTwits kabi begona ommaviy
kanal bizni admin qilmaydi. Telethon esa oddiy foydalanuvchi (telefon
raqami) sifatida kanalga A'ZO bo'lib, undagi barcha postlarni jonli
o'qiy oladi — aynan Telegram desktop/mobil ilovasi qanday ishlasa shunday.

Bir martalik LOGIN kerak — `bot.py`dagi admin buyruqlari
(`/tg_login`/`/tg_code`/`/tg_password`) orqali. Natijada olingan
sessiya STRING sifatida (`telethon.sessions.StringSession`) Postgres'ga
(`bot_settings` jadvali, `db.get_setting`/`set_setting`) saqlanadi —
FAYL sifatida EMAS, chunki Railway konteyneri qayta ishga tushganda
mahalliy fayl yo'qoladi, baza esa saqlanib qoladi.

MUHIM (rivojlantirish uchun eslatma): MTProto — oddiy HTTPS emas, xom
TCP protokol. Loyihaning boshqa BARCHA tashqi so'rovlari (SEC/Upbit/
Coinalyze/MEXC) HTTPS orqali ishlaydigan rivojlantirish sandbox'ida bu
protokol tarmoq siyosati tomonidan butunlay BLOKLANADI (ulanish
osilib qoladi, xato ham bermaydi) — shuning uchun bu modul FAQAT
production'da (Railway, cheklovsiz internet) sinaladi, mahalliy mock
bilan EMAS."""
import logging

from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

import config
import db

log = logging.getLogger("tgsource")

_client: TelegramClient | None = None
_login_hash: str | None = None
_login_phone: str | None = None


def enabled() -> bool:
    return bool(config.TELETHON_API_ID and config.TELETHON_API_HASH)


async def _get_client() -> TelegramClient:
    global _client
    if _client is None:
        session_str = await db.get_setting("telethon_session") or ""
        _client = TelegramClient(StringSession(session_str),
                                 config.TELETHON_API_ID, config.TELETHON_API_HASH)
    if not _client.is_connected():
        await _client.connect()
    return _client


async def is_authorized() -> bool:
    if not enabled():
        return False
    client = await _get_client()
    return await client.is_user_authorized()


async def login_send_code(phone: str) -> None:
    """/tg_login qadam 1 — Telegram'ga bir martalik kod so'raladi (u
    admin akkountning O'Z Telegram ilovasiga keladi)."""
    global _login_hash, _login_phone
    client = await _get_client()
    sent = await client.send_code_request(phone)
    _login_hash = sent.phone_code_hash
    _login_phone = phone


async def login_submit_code(code: str) -> str:
    """/tg_login qadam 2 — "ok" yoki (2FA yoqilgan bo'lsa) "need_password"
    qaytaradi."""
    if not _login_phone or not _login_hash:
        raise RuntimeError("Avval /tg_login bilan kod so'ralishi kerak")
    client = await _get_client()
    try:
        await client.sign_in(_login_phone, code, phone_code_hash=_login_hash)
    except SessionPasswordNeededError:
        return "need_password"
    await _save_session()
    return "ok"


async def login_submit_password(password: str) -> None:
    """/tg_login qadam 3 (faqat 2FA yoqilgan akkauntlar uchun)."""
    client = await _get_client()
    await client.sign_in(password=password)
    await _save_session()


async def _save_session() -> None:
    client = await _get_client()
    await db.set_setting("telethon_session", client.session.save())


async def start_listener(on_message) -> None:
    """`on_message(channel_username, msg_id, text, event_at)` — har bir
    yangi xabar uchun chaqiriladi (async funksiya bo'lishi kerak).
    Cheksiz ishlaydi (`run_until_disconnected`) — chaqiruvchi buni fon
    vazifasi sifatida (`bot.py`dagi `_spawn_background`) ishga tushiradi."""
    if not enabled():
        return
    client = await _get_client()
    if not await client.is_user_authorized():
        log.warning("Telethon hali login qilinmagan — /tg_login admin "
                   "buyrug'i orqali kiring")
        return

    for ch in config.TELEGRAM_NEWS_CHANNELS:
        try:
            await client(JoinChannelRequest(ch))
        except Exception:
            log.warning("Kanalga a'zo bo'lib bo'lmadi: %s", ch, exc_info=True)

    @client.on(events.NewMessage(chats=config.TELEGRAM_NEWS_CHANNELS))
    async def _handler(event):
        try:
            text = (event.raw_text or "").strip()
            if not text:
                return
            channel = event.chat.username if event.chat else "?"
            await on_message(channel, event.id, text, event.date)
        except Exception:
            log.exception("Telegram-manba xabari ishlanmadi")

    log.info("Telethon userbot tinglashni boshladi: %s",
             ", ".join(config.TELEGRAM_NEWS_CHANNELS))
    await client.run_until_disconnected()
