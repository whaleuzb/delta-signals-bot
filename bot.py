"""Trade Controller — asosiy fayl.

Multi-tenant: bitta bot bir nechta mustaqil "workspace"ga xizmat qiladi —
har bir yopiq Telegram guruhi o'z workspace'ini (/setup orqali) ochishi,
yoki istalgan odam shaxsiy jurnal sifatida foydalanishi mumkin. Workspace'lar
bir-birining ma'lumotini ko'rmaydi (db.py'dagi workspace_id orqali ajratilgan).
"""
import asyncio
import html
import io
import json
import os
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from PIL import Image

from telegram import (
    InputMediaPhoto, Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile, WebAppInfo,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
from telegram.ext import (
    Application, ApplicationHandlerStop, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, TypeHandler, filters,
)

import chart
import config
import cryptonews
import db
import econcalendar
import exchange
import forex
import i18n
import indicators
import liquidations
import listings
import news
import newsai
import stocks
import parsing
import stats
import tgsource
import tracker
import translate
import vision

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

# token -> {"draft": {...}, "file_id": str, "user": int, "workspace_id": int}
PENDING: dict[str, dict] = {}
# Tasdiqlanmagan qoralamalar chegarasi (xotira o'sib ketmasligi uchun).
MAX_PENDING = 500
# admin id -> token (tahrir kutilmoqda)
AWAITING_EDIT: dict[int, str] = {}
# admin id -> signal_id (yangi yaratilgan signalga pul miqdori kutilmoqda)
AWAITING_ALLOC: dict[int, int] = {}
# admin id -> token ("🖼 Rasm yuklash" bosilgan, endi rasm kutilmoqda)
AWAITING_SIGNAL_PHOTO: dict[int, str] = {}
# super-admin id -> True (majburiy obuna uchun kanal kutilmoqda)
AWAITING_CHANNEL: dict[int, bool] = {}
# super-admin id -> True (MarketTwits qo'shimcha #hashtag kutilmoqda)
AWAITING_HASHTAG: dict[int, bool] = {}
# Broadcast: admin xabar yuborishini kutamiz -> keyin tasdiqlashni
AWAITING_BROADCAST: dict[int, bool] = {}
PENDING_BROADCAST: dict[int, tuple[int, int]] = {}   # admin -> (chat_id, message_id)
# News Trade AI/surge post ostidagi "📝 Jurnalga kiritish" tugmasi orqali
# kelgan foydalanuvchi: uid -> (symbol, shaxsiy_workspace_id). Tiker
# allaqachon ma'lum, shuning uchun endi faqat yo'nalish/kirish/TP/SL kutiladi.
AWAITING_JOURNAL_SYMBOL: dict[int, tuple[str, int]] = {}


def is_admin(uid: int) -> bool:
    """Super-admin — barcha workspace'larga kirish (qo'llab-quvvatlash uchun)."""
    return uid in config.ADMIN_IDS


def can_manage(uid: int, ws) -> bool:
    """Shu workspace uchun signal kirita/yopa oladimi (workspace admini yoki super-admin)."""
    return is_admin(uid) or ws["owner_id"] == uid


NOT_SUBSCRIBER_TEXT = (
    "🔒 Bu ma'lumotlar faqat shu guruh obunachilariga ochiq.\n"
    "Obunani faollashtirgach, bot avtomatik ishlay boshlaydi."
)
NOT_SUBSCRIBER_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("💳 Obuna bo'lish", url="https://t.me/mamurjonpaybot")]])


async def can_view(bot, uid: int, ws) -> bool:
    """Guruh workspace — whale-payment-bot muddati tugagan obunachilarni guruhdan
    avtomatik chiqarib turadi, shuning uchun "hozir guruh a'zosimi" tekshiruvi
    "hozir obunachimi" degani bilan bir xil. Shaxsiy workspace — faqat egasi."""
    if can_manage(uid, ws):
        return True
    if ws["type"] == "personal":
        return False
    if not ws["group_chat_id"]:
        return False
    try:
        member = await bot.get_chat_member(ws["group_chat_id"], uid)
        return member.status not in ("left", "kicked")
    except Exception:
        log.exception("Obuna tekshiruvida xato (uid=%s ws=%s)", uid, ws["id"])
        return False


# ─────────────────────── Majburiy obuna (kanallar) ───────────────────────

_SUB_TTL = 300.0                       # to'liq obuna bo'lganlar shuncha soniya keshlanadi
_sub_ok_until: dict[int, float] = {}   # uid -> monotonic deadline


async def missing_subscriptions(bot, uid: int) -> list:
    """Foydalanuvchi obuna BO'LMAGAN majburiy kanallar ro'yxati.

    MUHIM — xatolikda OCHIQ qoladi (kanal o'chirilgan, bot u yerda admin emas
    va h.k.): aks holda bitta noto'g'ri sozlama butun botni hamma uchun
    qulflab qo'yardi. Obuna talabini majburlash foydalanuvchini yo'qotishdan
    ko'ra muhimroq emas."""
    if is_admin(uid):
        return []
    channels = await db.list_required_channels()
    if not channels:
        return []

    deadline = _sub_ok_until.get(uid)
    if deadline and time.monotonic() < deadline:
        return []

    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["chat_id"], uid)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            # Tekshirib bo'lmadi — bu foydalanuvchining aybi emas, o'tkazamiz.
            log.warning("Obuna tekshirilmadi (kanal=%s uid=%s) — o'tkazib yuborildi",
                         ch["chat_id"], uid)
    if not missing:
        _sub_ok_until[uid] = time.monotonic() + _SUB_TTL
    else:
        _sub_ok_until.pop(uid, None)
    return missing


def _channel_url(ch) -> str | None:
    if ch["username"]:
        return f"https://t.me/{ch['username'].lstrip('@')}"
    return None


async def send_subscribe_prompt(update: Update, missing: list) -> None:
    rows = []
    for ch in missing:
        url = _channel_url(ch)
        label = f"📢 {ch['title'] or ch['username'] or ch['chat_id']}"
        if url:
            rows.append([InlineKeyboardButton(label, url=url)])
    rows.append([InlineKeyboardButton("✅ Obuna bo'ldim, tekshirish",
                                       callback_data="subcheck")])
    txt = ("👋 Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling, "
           "so'ng <b>“✅ Obuna bo'ldim”</b> tugmasini bosing.")
    msg = update.effective_message
    if msg:
        await msg.reply_text(txt, parse_mode=ParseMode.HTML,
                             reply_markup=InlineKeyboardMarkup(rows))


async def gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Har bir update'dan OLDIN ishlaydi (group=-1): foydalanuvchini yozib
    qo'yadi va majburiy obunani tekshiradi. Faqat SHAXSIY chat gate qilinadi —
    guruh ichidagi oqimlar (/setup, signal postlari) to'sib qo'yilmaydi."""
    user = update.effective_user
    if not user or user.is_bot:
        return
    try:
        await db.upsert_user(user.id, user.username, user.first_name)
    except Exception:
        log.exception("Foydalanuvchini yozib bo'lmadi (uid=%s)", user.id)

    chat = update.effective_chat
    if not chat or chat.type != "private" or is_admin(user.id):
        return
    q = update.callback_query
    if q and q.data == "subcheck":
        return                      # tekshirish tugmasi doim o'tishi kerak

    missing = await missing_subscriptions(ctx.bot, user.id)
    if missing:
        if q:
            await q.answer("Avval kanalga obuna bo'ling", show_alert=True)
        await send_subscribe_prompt(update, missing)
        raise ApplicationHandlerStop


async def on_subcheck(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    missing = await missing_subscriptions(ctx.bot, q.from_user.id)
    if missing:
        await q.answer("Hali obuna bo'lmagansiz.", show_alert=True)
        return
    await q.answer("Rahmat! ✅")
    await q.edit_message_text("✅ Obuna tasdiqlandi. Botdan foydalanishingiz mumkin.")
    await show_menu(update, ctx)


def access_denied(ws) -> tuple[str, InlineKeyboardMarkup | None]:
    if ws["type"] == "personal":
        return "🔒 Bu boshqa foydalanuvchining shaxsiy jurnali.", None
    return NOT_SUBSCRIBER_TEXT, NOT_SUBSCRIBER_KB


# ─────────────────────────── Workspace aniqlash ───────────────────────────

async def resolve_workspace(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Joriy update qaysi workspace'ga tegishli ekanini aniqlaydi.
    Guruh ichida — o'sha guruhning workspace'i (agar /setup qilingan bo'lsa, aks
    holda None). Shaxsiy chatda — avval tanlab keshlangan workspace; agar bo'lmasa,
    foydalanuvchining barcha variantlari (o'z guruhi, shaxsiy jurnal, a'zo sifatida
    ulangan guruhlar) yig'iladi: aynan bitta bo'lsa avtomatik shu; ikki yoki undan
    ko'p bo'lsa — None (switcher); birortasi ham yo'q bo'lsa — None (onboarding)."""
    chat = update.effective_chat
    uid = update.effective_user.id

    if chat.type in ("group", "supergroup"):
        return await db.get_workspace_by_group(chat.id)

    cached_id = ctx.user_data.get("workspace_id")
    if cached_id:
        ws = await db.get_workspace(cached_id)
        if ws:
            return ws

    owned_group = await db.get_group_workspace_by_owner(uid)
    personal = await db.get_personal_workspace(uid)
    viewer_links = await db.get_group_viewer_workspaces(uid)

    candidates = ([owned_group] if owned_group else []) + ([personal] if personal else []) + list(viewer_links)
    if len(candidates) == 1:
        ws = candidates[0]
        ctx.user_data["workspace_id"] = ws["id"]
        return ws

    return None  # 0 ta — onboarding; 2+ ta — switcher (tanlash kerak)


async def send_workspace_switcher(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    owned_group = await db.get_group_workspace_by_owner(uid)
    personal = await db.get_or_create_personal_workspace(uid, "Shaxsiy jurnal")
    viewer_links = await db.get_group_viewer_workspaces(uid)
    rows = []
    if owned_group:
        rows.append([InlineKeyboardButton(
            f"👑 {owned_group['name']}", callback_data=f"ws:{owned_group['id']}")])
    for vws in viewer_links:
        rows.append([InlineKeyboardButton(
            f"👥 {vws['name']}", callback_data=f"ws:{vws['id']}")])
    rows.append([InlineKeyboardButton("🧑 Shaxsiy jurnal", callback_data=f"ws:{personal['id']}")])
    rows.append([InlineKeyboardButton("➕ Boshqa guruhga a'zo bo'lish", callback_data="joingroup")])
    await update.effective_message.reply_text("Qaysi joy uchun?", reply_markup=InlineKeyboardMarkup(rows))


ONBOARD_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("🧑 Shaxsiy jurnal ochish", callback_data="onboard:personal")],
    [InlineKeyboardButton("🏘 Menda yopiq guruh bor", callback_data="onboard:group")],
])
GROUP_ROLE_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("👥 Men guruh a'zosiman", callback_data="onboard:group_member")],
    [InlineKeyboardButton("👑 Men guruh egasiman", callback_data="onboard:group_owner")],
])


async def send_onboarding(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "👋 Xush kelibsiz! Botni qanday ishlatmoqchisiz?\n\n"
        "🧑 <b>Shaxsiy jurnal</b> — o'z savdo signallaringizni yozib, statistikangizni "
        "kuzatib borasiz. Faqat sizga ko'rinadi, hech kimga post bo'lmaydi.\n\n"
        "🏘 <b>Guruh</b> — sizda o'z yopiq Telegram guruhingiz bo'lsa (yoki allaqachon "
        "biror guruhga a'zo bo'lsangiz), shu bot orqali statistikani ko'rishingiz mumkin.",
        parse_mode=ParseMode.HTML, reply_markup=ONBOARD_KB)


async def send_group_picker(q) -> None:
    """q — CallbackQuery; joriy xabarni tahrirlab guruhlar ro'yxatini ko'rsatadi."""
    groups = await db.list_group_workspaces()
    if not groups:
        await q.edit_message_text("Hozircha hech qanday guruh ro'yxatdan o'tmagan.",
                                   reply_markup=MENU_BACK_KB)
        return
    rows = [[InlineKeyboardButton(f"👥 {g['name']}", callback_data=f"viewjoin:{g['id']}")]
            for g in groups]
    await q.edit_message_text("Qaysi guruh a'zosisiz? Tanlang:",
                               reply_markup=InlineKeyboardMarkup(rows))


async def on_onboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":", 1)[1]
    uid = q.from_user.id

    if choice == "personal":
        ws = await db.get_or_create_personal_workspace(uid, "Shaxsiy jurnal")
        ctx.user_data["workspace_id"] = ws["id"]
        await q.edit_message_text("✅ Shaxsiy jurnal ochildi.")
        await q.message.reply_text(
            "Bosh menyu:",
            reply_markup=main_menu_kb(uid, ws, q.message.chat.type == "private"))
        return

    if choice == "group":
        await q.edit_message_text(
            "🏘 Shu guruh bilan bog'liq siz kimsiz?", reply_markup=GROUP_ROLE_KB)
        return

    if choice == "group_member":
        await send_group_picker(q)
        return

    # choice == "group_owner"
    bot_username = ctx.bot.username
    mention = f"@{bot_username}" if bot_username else "botni"
    await q.edit_message_text(
        f"👑 Guruhingizni ulash uchun:\n\n"
        f"1. {mention} o'z guruhingizga qo'shing.\n"
        "2. Botga guruhda <b>admin</b> huquqini bering (xabar yuborish uchun kerak).\n"
        "3. Guruh ichida <code>/setup</code> buyrug'ini yozing.\n\n"
        "Shundan so'ng guruhingiz mustaqil workspace sifatida ishlay boshlaydi va "
        "botga shaxsiy yozganingizda avtomatik o'shani boshqarasiz.",
        parse_mode=ParseMode.HTML)


async def on_join_group(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await send_group_picker(q)


async def on_view_join(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    wid = int(q.data.split(":", 1)[1])
    uid = q.from_user.id
    ws = await db.get_workspace(wid)
    if not ws or ws["type"] != "group" or not ws["group_chat_id"]:
        await q.edit_message_text("Bu guruh topilmadi.", reply_markup=MENU_BACK_KB)
        return
    try:
        member = await ctx.bot.get_chat_member(ws["group_chat_id"], uid)
        is_member = member.status not in ("left", "kicked")
    except Exception:
        is_member = False
    if not is_member:
        await q.edit_message_text(
            f"🔒 Siz \"{ws['name']}\" guruhi a'zosi emassiz (yoki bot tekshira olmadi).",
            reply_markup=MENU_BACK_KB)
        return
    await db.add_group_viewer(uid, wid)
    ctx.user_data["workspace_id"] = wid
    await q.edit_message_text(f"✅ \"{ws['name']}\" ulandi — endi statistikasini ko'ra olasiz.")
    await q.message.reply_text(
        "Bosh menyu:",
        reply_markup=main_menu_kb(uid, ws, q.message.chat.type == "private"))


async def get_ws_or_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Workspace'ni aniqlaydi. Topilmasa mos xabar/tanlov/onboarding ko'rsatadi va
    None qaytaradi — chaqiruvchi shu holda darhol return qilishi kerak."""
    ws = await resolve_workspace(update, ctx)
    if ws is not None:
        return ws
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        await update.effective_message.reply_text(
            "Bu guruh hali ro'yxatdan o'tmagan. Guruh admini /setup buyrug'ini yozsin.")
        return None

    uid = update.effective_user.id
    owned_group = await db.get_group_workspace_by_owner(uid)
    personal = await db.get_personal_workspace(uid)
    viewer_links = await db.get_group_viewer_workspaces(uid)
    if owned_group or personal or viewer_links:
        await send_workspace_switcher(update, ctx)
    else:
        await send_onboarding(update, ctx)
    return None


async def on_workspace_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    wid = int(q.data.split(":", 1)[1])
    uid = q.from_user.id
    ws = await db.get_workspace(wid)
    allowed = ws and (is_admin(uid) or ws["owner_id"] == uid or await db.is_group_viewer(uid, wid))
    if not allowed:
        await q.edit_message_text("Ruxsat yo'q.")
        return
    ctx.user_data["workspace_id"] = wid
    await q.edit_message_text(f"✅ Tanlandi: {ws['name']}")
    await q.message.reply_text(
        "Bosh menyu:",
        reply_markup=main_menu_kb(uid, ws, q.message.chat.type == "private"))


async def on_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("workspace_id", None)
    await send_workspace_switcher(update, ctx)


def provider_for(market: str):
    """market bo'yicha narx manbai: forex/aksiya — Twelve Data, aks holda MEXC."""
    if market == "forex":
        return forex
    if market == "stock":
        return stocks
    return exchange


async def safe_last_price(market: str, symbol: str, fresh: bool = False):
    """Narx manbasi javob bermasa None qaytaradi, xato ko'tarmaydi —
    aks holda birjadagi bir soniyalik uzilish /open yoki signal ko'rinishini
    butunlay yiqitardi."""
    try:
        return await provider_for(market).last_price(symbol, fresh=fresh)
    except Exception:
        log.warning("Narx olinmadi (%s %s)", market, symbol, exc_info=True)
        return None


def fmt_price(x: float) -> str:
    if x >= 1000:
        return f"{x:,.2f}".rstrip("0").rstrip(".")
    if x >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".")


def draft_text(d: dict, sig_id: int | None = None) -> str:
    e, sl, tps = d["entry"], d.get("sl"), d.get("tps") or []
    arrow = "🟢 LONG" if d["side"] == "LONG" else "🔴 SHORT"
    tag = {"forex": "💱 ", "stock": "📈 "}.get(d.get("market"), "")
    head = f"{tag}📊 <b>#{d['symbol']}</b>  {arrow}"
    if sig_id:
        head += f"  <code>#{sig_id}</code>"
    entry_note = " <i>(🎯 darhol kirilgan)</i>" if d.get("entry_mode") == "market" else ""
    lines = [head, "", f"Kirish: <b>{fmt_price(e)}</b>{entry_note}"]
    if sl is None:
        # TP/SL hali kiritilmagan — limit to'lgach so'raladi (foydalanuvchi:
        # "boshida faqat limitni kiritamiz, TP/SL limit aktivlashgandan
        # keyin so'ralsin"). R:R hali hisoblab bo'lmaydi.
        lines.append("<i>TP/SL — limit to'lgandan keyin so'raladi.</i>")
        return "\n".join(lines)
    risk = abs(e - sl) / e * 100
    reward = abs(tps[-1] - e) / e * 100
    rr = reward / risk if risk else 0
    for i, t in enumerate(tps, 1):
        pct = abs(t - e) / e * 100
        lines.append(f"🎯 TP{i}: <b>{fmt_price(t)}</b>  <i>(+{pct:.2f}%)</i>")
    lines += [
        f"🛑 Stop: <b>{fmt_price(sl)}</b>  <i>(-{risk:.2f}%)</i>",
        "",
        f"Risk/Reward: <b>1:{rr:.2f}</b>",
    ]
    return "\n".join(lines)


# ─────────────────────────── Asosiy menyu ───────────────────────────

def web_page_url(ws) -> str | None:
    """Guruhning ochiq sahifasi havolasi. Sahifa `/top` bilan AYNI darvozadan
    o'tgan guruhlardagina mavjud — aks holda None qaytariladi va tugma umuman
    ko'rsatilmaydi (bosilib 404 olishdan ko'ra shunisi to'g'ri)."""
    if not config.WEB_URL or ws["type"] != "group":
        return None
    if not (ws["public"] and ws["public_approved"] and not ws["archived"]):
        return None
    return f"{config.WEB_URL}/g/{ws['id']}"


def main_menu_kb(uid: int, ws, private: bool = True,
                  lang: str | None = None) -> InlineKeyboardMarkup:
    """`lang` — odamning SHAXSIY tili (`users.lang`). Berilmasa
    o'zbekcha (i18n.normalize) — hali tarjimaga o'tkazilmagan eski
    chaqiruv joylari shu sabab o'zgarishsiz ishlayveradi."""
    rows = []
    if can_manage(uid, ws):
        rows.append([InlineKeyboardButton(i18n.t("menu.new_signal", lang), callback_data="newsig"),
                     InlineKeyboardButton(i18n.t("menu.deposit", lang), callback_data="m:deposit")])
    rows += [
        [InlineKeyboardButton(i18n.t("menu.stats", lang), callback_data="m:stats"),
         InlineKeyboardButton(i18n.t("menu.symbols", lang), callback_data="m:symbols")],
        [InlineKeyboardButton(i18n.t("menu.open", lang), callback_data="m:open"),
         InlineKeyboardButton(i18n.t("menu.equity", lang), callback_data="m:equity")],
    ]
    # News Trade AI kanaliga havola — sozlanmagan bo'lsa (NEWS_CHANNEL_ID
    # bo'sh) butun funksiya o'chiq, tugma ham chiqmaydi.
    if config.NEWS_CHANNEL_ID:
        rows.append([InlineKeyboardButton(i18n.t("menu.news", lang),
                                          url=f"https://t.me/{NEWS_CHANNEL_USERNAME}")])
    url = web_page_url(ws)
    if url:
        # web_app — sahifa Telegram ICHIDA ochiladi (Mini App). Telegram uni
        # FAQAT shaxsiy chatdagi inline tugmada qabul qiladi; guruhda yuborilsa
        # butun xabar BUTTON_TYPE_INVALID bilan rad etiladi va foydalanuvchi
        # "Ishlov berishda xato" ko'radi. Shu sabab guruhda oddiy URL tugmasi
        # ishlatiladi — u sahifani brauzerda ochadi va hamma joyda ishlaydi.
        # Yonida "🔗 Havola" tugmasi ham bor edi — olib tashlandi: ikkalasi
        # ham AYNI sahifaga olib borardi. Havolani ulashish kerak bo'lsa
        # /sahifa buyrug'i bor (u manzilni <code> ichida yuboradi).
        page_label = i18n.t("menu.page", lang)
        page = (InlineKeyboardButton(page_label, web_app=WebAppInfo(url=url))
                if private else InlineKeyboardButton(page_label, url=url))
        rows.append([page])
    rows.append([InlineKeyboardButton(i18n.t("menu.help", lang), callback_data="help:home"),
                 InlineKeyboardButton(i18n.t("menu.switch", lang), callback_data="switch")])
    rows.append([InlineKeyboardButton(i18n.t("menu.lang", lang), callback_data="lang:menu")])
    return InlineKeyboardMarkup(rows)


def menu_back_kb(lang: str | None = None) -> InlineKeyboardMarkup:
    """Tarjimaga o'tkazilgan joylar shuni ishlatadi. Qolgan (hali
    o'zbekcha) joylar `MENU_BACK_KB` konstantasidan foydalanishda davom
    etadi — tarjima bosqichma-bosqich ko'chirilyapti."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(i18n.t("menu.home", lang), callback_data="menu")]])


MENU_BACK_KB = menu_back_kb()


# ─────────────────────────── Til (i18n) ───────────────────────────
# Til deyarli HAR BIR xabarda kerak — har safar bazaga so'rov yuborish
# ortiqcha yuk bo'lardi. Shu sabab kichik kesh: odam tilini o'zgartirsa
# `set_user_lang` orqali darhol yangilanadi, boshqa hech qachon
# eskirmaydi (til faqat shu bot orqali o'zgaradi).
_LANG_CACHE: dict[int, str] = {}


async def user_lang(uid: int) -> str:
    """Odamning shaxsiy menyu tili. Tanlanmagan bo'lsa — o'zbekcha."""
    cached = _LANG_CACHE.get(uid)
    if cached:
        return cached
    try:
        lang = i18n.normalize(await db.get_user_lang(uid))
    except Exception:
        log.warning("Til o'qilmadi (%s)", uid, exc_info=True)
        return i18n.DEFAULT_LANG
    _LANG_CACHE[uid] = lang
    return lang


async def has_chosen_lang(uid: int) -> bool:
    """Odam tilni ATAYLAB tanlaganmi (NULL — hali tanlamagan)."""
    if uid in _LANG_CACHE:
        return True
    try:
        return await db.get_user_lang(uid) is not None
    except Exception:
        return True     # baza xato bersa til so'rab bezovta qilmaymiz


def lang_kb(prefix: str = "lang:set") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(title, callback_data=f"{prefix}:{code}")]
         for code, title in i18n.LANGS.items()])


async def on_lang_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lang = await user_lang(q.from_user.id)
    await q.edit_message_text(i18n.t("lang.choose", lang), reply_markup=lang_kb())


async def on_lang_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    code = i18n.normalize(q.data.rsplit(":", 1)[1])
    uid = q.from_user.id
    await db.set_user_lang(uid, code)
    _LANG_CACHE[uid] = code
    await q.answer(i18n.t("lang.saved", code))
    await q.edit_message_text(i18n.t("lang.saved", code))

    # Til tanlangach DARHOL bosh menyuga o'tkazamiz. `/start`dagi AYNAN
    # o'sha oqim (`get_ws_or_prompt`) ishlatiladi. Avval bu yerda
    # `resolve_workspace()` chaqirilardi va u YANGI odamda `None`
    # qaytarib, ekranda faqat "Til o'zgartirildi" qolib ketardi —
    # tugmasiz, boshi berk ko'cha (foydalanuvchi: "Til o'zgartirildi
    # yozuvidan keyin xechnarsa chiqmayabti"). `get_ws_or_prompt` esa
    # workspace bo'lmasa onboarding/tanlov ekranini O'ZI ko'rsatadi.
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await q.message.reply_text(text, reply_markup=kb)
        return
    await q.message.reply_text(
        i18n.t("menu.title", code, name=ws["name"]),
        reply_markup=main_menu_kb(uid, ws, q.message.chat.type == "private", code))


async def cmd_til(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await user_lang(update.effective_user.id)
    await update.message.reply_text(i18n.t("lang.choose", lang), reply_markup=lang_kb())


# ─────────────────────────── Yordam / yo'riqnoma ───────────────────────────
# Matn ataylab bot ICHIDA to'liq saqlanadi — foydalanuvchi havolani ochmasdan
# ham javobini topishi kerak (ko'pchilik aynan qotib qolgan payt yordam
# qidiradi va tashqi sahifaga o'tishga xohishi bo'lmaydi).

HELP_TOPICS = {
    "setup": (
        "👥 <b>Guruhni ulash</b>\n\n"
        "<b>1.</b> Botni guruhingizga qo'shing.\n"
        "<b>2.</b> Botga guruhda <b>admin</b> huquqini bering.\n"
        "<b>3.</b> Guruh ichida <code>/setup</code> yozing.\n\n"
        "Bot javob bersa — ulanish tugadi.\n\n"
        "⚠️ Diqqat qiling:\n"
        "• <code>/setup</code> ni <b>guruh ichida</b> yozing, shaxsiy chatda emas.\n"
        "• Faqat <b>guruh admini</b> qila oladi.\n"
        "• Bir admin — bitta guruh.\n"
        "• Admin huquqisiz bot guruhga post yubora olmaydi."
    ),
    "signal": (
        "📈 <b>Signal kiritish</b>\n\n"
        "Signal <b>botning shaxsiy chatiga</b> yoziladi — guruhga emas! "
        "Tasdiqlaganingizdan keyin bot uni guruhga o'zi chiqaradi.\n\n"
        "<b>1. To'liq</b> — hamma daraja bitta xabarda:\n"
        "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
        "Bular ham ishlaydi:\n"
        "<code>ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80</code>\n"
        "<code>eth long 3200 3400 3550 3100</code>\n"
        "  ↳ kalit so'zsiz: birinchi raqam — kirish, oxirgisi — stop, "
        "o'rtadagilari TP.\n\n"
        "<b>2. Limit</b> — faqat kirish narxi, TP/SL limit to'lgach so'raladi:\n"
        "<code>BTCUSDT long 65000</code>\n\n"
        "<b>3. Darhol (market)</b> — narxni bot o'zi oladi:\n"
        "<code>BTCUSDT long market</code>\n\n"
        "<b>Rasm bilan:</b> izoh (caption) bo'lsa undan o'qiydi, bo'lmasa "
        "sun'iy intellekt grafikdan topishga urinadi.\n\n"
        "✅ Hech narsa tasdiqsiz saqlanmaydi — bot avval o'qiganini ko'rsatadi."
    ),
    "mode": (
        "⏳ <b>Limit va Market farqi</b>\n\n"
        "<b>Standart holat — kutish (limit).</b> Signal darhol ochilmaydi: "
        "narx kirish darajasiga <b>tegguncha kutadi</b>. Bu vaqtda "
        "🕐 belgisi bilan turadi.\n\n"
        "<b>Darhol ochish uchun</b> matnga <code>market</code> yoki "
        "<code>bozor</code> so'zini qo'shing:\n"
        "<code>BTCUSDT LONG market entry 65000 tp 67000 sl 64000</code>\n\n"
        "Narxni yozmasangiz ham bo'ladi — bot jonli narxni o'zi oladi:\n"
        "<code>BTCUSDT long market</code>\n\n"
        "💡 Pozitsiyaga allaqachon kirgan bo'lsangiz — <code>market</code> "
        "yozishni unutmang, aks holda bot narxni kutib turaveradi."
    ),
    "errors": (
        "🔧 <b>Ko'p uchraydigan xatolar</b>\n\n"
        "<b>Bot javob bermayapti?</b>\n"
        "Signalni guruhga yozgan bo'lishingiz mumkin. Signal faqat "
        "<b>shaxsiy chatda</b> qabul qilinadi.\n\n"
        "<b>TP noto'g'ri o'qildi?</b>\n"
        "<code>tp 172 168</code> — bu <b>ikkita</b> TP (172 va 168) deb o'qiladi. "
        "Minglik uchun <code>tp 172168</code> yoki <code>TP1 172 168</code> yozing.\n\n"
        "<b>\"SL entry dan past bo'lishi kerak\"?</b>\n"
        "LONG uchun: stop <b>past</b>, TP <b>yuqori</b>. SHORT uchun teskarisi. "
        "Odatda bu LONG/SHORT adashtirilganini bildiradi.\n\n"
        "<b>\"Risk juda katta\"?</b>\n"
        "Kirish bilan stop orasi 25% dan ko'p. Raqamlarni tekshiring — "
        "ko'pincha verguldan adashish.\n\n"
        "<b>Bot guruhga yozmayapti?</b>\n"
        "Botda admin huquqi yo'qligidan. Guruh sozlamalaridan bering."
    ),
}


# Mavzuga mos rasm. Telegraph rasm yuklashni qabul qilmagani uchun (upload
# xizmati anonim yuklashni cheklagan) rasmlar botning O'ZI orqali yuboriladi —
# tashqi hosting kerak emas va rasm foydalanuvchi chatida saqlanib qoladi.
HELP_IMAGES = {
    "setup": "guide_images/01-guruh-ulash.png",
    "signal": "guide_images/02-signal-formati.png",
    "errors": "guide_images/03-xatolar.png",
    "after": "guide_images/04-keyin-nima-boladi.png",
}
# Telegram bir marta yuklangan faylni file_id bilan qayta ishlatadi — har
# safar qaytadan yuklamaslik uchun keshlaymiz (rasm ~200 KB).
_photo_ids: dict[str, str] = {}


async def send_help_photo(bot, chat_id: int, key: str, caption: str | None = None) -> bool:
    """Mavzuga mos rasmni yuboradi. Rasm topilmasa/yuborilmasa False —
    chaqiruvchi yordam matnini baribir ko'rsatadi."""
    path = HELP_IMAGES.get(key)
    if not path:
        return False
    try:
        if key in _photo_ids:
            await bot.send_photo(chat_id, _photo_ids[key], caption=caption,
                                  parse_mode=ParseMode.HTML if caption else None)
            return True
        if not os.path.exists(path):
            log.warning("Yordam rasmi topilmadi: %s", path)
            return False
        with open(path, "rb") as f:
            msg = await bot.send_photo(
                chat_id, InputFile(f, os.path.basename(path)), caption=caption,
                parse_mode=ParseMode.HTML if caption else None)
        if msg.photo:
            _photo_ids[key] = msg.photo[-1].file_id
        return True
    except Exception:
        log.exception("Yordam rasmi yuborilmadi (%s)", key)
        return False


def help_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("👥 Guruhni ulash", callback_data="help:setup"),
         InlineKeyboardButton("📈 Signal kiritish", callback_data="help:signal")],
        [InlineKeyboardButton("⏳ Limit / Market", callback_data="help:mode"),
         InlineKeyboardButton("🔧 Xatolar", callback_data="help:errors")],
        [InlineKeyboardButton("🖼 Rasmli yo'riqnoma", callback_data="help:rasm")],
    ]
    if config.GUIDE_URL:
        rows.append([InlineKeyboardButton("📘 To'liq qo'llanma (maqola)",
                                           url=config.GUIDE_URL)])
    rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


HELP_INTRO = ("❓ <b>Yordam</b>\n\n"
              "Qaysi bo'lim bo'yicha yordam kerak?")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        HELP_INTRO, parse_mode=ParseMode.HTML, reply_markup=help_menu_kb())


async def on_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    topic = q.data.split(":", 1)[1]
    chat_id = q.message.chat_id

    if topic == "home":
        await q.edit_message_text(HELP_INTRO, parse_mode=ParseMode.HTML,
                                   reply_markup=help_menu_kb())
        return

    if topic == "rasm":
        # Hamma rasm ketma-ket — yangi boshlovchi bittada ko'rib chiqadi.
        for key in ("setup", "signal", "errors", "after"):
            await send_help_photo(ctx.bot, chat_id, key)
        await ctx.bot.send_message(
            chat_id, "🖼 Yo'riqnoma rasmlari. Batafsil matn uchun bo'limni tanlang.",
            reply_markup=help_menu_kb())
        return

    txt = HELP_TOPICS.get(topic)
    if not txt:
        return
    kb = [[InlineKeyboardButton("◀️ Yordam", callback_data="help:home")]]
    if config.GUIDE_URL:
        kb.insert(0, [InlineKeyboardButton("📘 To'liq qo'llanma (maqola)",
                                            url=config.GUIDE_URL)])
    # Rasm bo'lsa — avval rasm, keyin matn: rasm ko'zga birinchi tashlanadi.
    await send_help_photo(ctx.bot, chat_id, topic)
    await ctx.bot.send_message(chat_id, txt, parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(kb))


async def open_signals_view(ws, uid: int) -> tuple[str, InlineKeyboardMarkup | None]:
    rows = await db.live_signals(ws["id"])
    if not rows:
        return "Ochiq signal yo'q.", None
    lines = ["<b>Ochiq signallar</b>", ""]
    kb_rows = []
    manage = can_manage(uid, ws)
    for s in rows:
        price = await safe_last_price(s["market"], s["symbol"])
        cur = ""
        p = None
        if price:
            p = tracker.pnl_at(s["side"], float(s["entry"]), price)
            cur = f"  ({p:+.2f}%)"
        if s["status"] != "ACTIVE":
            mark = "🕐"  # hali entry/limitga tegmagan (kutilmoqda)
        elif p is None:
            mark = "▶️"  # narx olinmadi — yo'nalishni bilib bo'lmadi
        else:
            mark = "📈" if p >= 0 else "📉"  # joriy foyda/zararga qarab
        lines.append(
            f"{mark} <code>#{s['id']}</code> {s['symbol']} {s['side']} "
            f"@ {fmt_price(float(s['entry']))} — TP{s['tp_hit']}/{len(s['tps'])}{cur}"
        )
        if manage:
            kb_rows.append([InlineKeyboardButton(
                f"⚙️ #{s['id']} {s['symbol']} — boshqarish",
                callback_data=f"mng:{s['id']}")])
    kb = InlineKeyboardMarkup(kb_rows) if kb_rows else None
    return "\n".join(lines), kb


# ─────────────── Ochiq pozitsiyani boshqarish ───────────────
# admin id -> signal_id (yangi stop / yangi maqsadlar kutilmoqda)
AWAITING_SL: dict[int, int] = {}
AWAITING_TPS: dict[int, int] = {}
AWAITING_ENTRY: dict[int, int] = {}
# admin id -> signal_id — Limit rejimida entry to'ldi, lekin TP/SL HALI
# UMUMAN kiritilmagan (`AWAITING_TPS`dan farqli — u ALLAQACHON mavjud
# TP'larni o'zgartirish uchun, bu esa BIRINCHI marta joylashtirish uchun).
AWAITING_TPSL: dict[int, int] = {}


async def manage_view(sig) -> tuple[str, InlineKeyboardMarkup]:
    entry = float(sig["entry"])
    sid = sig["id"]
    # PENDING — signal hali entryga TEGMAGAN (limit hali bajarilmagan).
    # Shu holatda "bekor qilish" (endi urinib ko'rmaymiz) va "entry
    # o'zgartirish" (narx noto'g'ri kiritilgan yoki bozor siljigan bo'lsa)
    # mantiqiy — ACTIVE bo'lgandan keyin esa entry ALLAQACHON bajarilgan
    # hisoblanadi, uni "o'zgartirish" ma'nosiz.
    pending = sig["status"] == "PENDING"
    if sig["sl"] is None:
        # Limit to'ldi (yoki hali kutilmoqda), lekin TP/SL HALI
        # kiritilmagan (limit-keyin-TP/SL oqimi) — pastdagi boshqaruv
        # (stop/maqsad o'zgartirish, qisman yopish) TP/SL borligini
        # kutadi, shuning uchun bu yerda mavjud emas. Foydalanuvchini
        # to'g'ridan-to'g'ri TP/SL kiritishga yo'naltiramiz.
        rows = [[InlineKeyboardButton("📐 TP/SL kiriting", callback_data=f"tpsl:{sid}")]]
        if pending:
            rows.append([
                InlineKeyboardButton("✏️ Entry", callback_data=f"mentry:{sid}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"close:{sid}"),
            ])
        rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")])
        return (f"⚙️ <b>#{sid} {sig['symbol']} {sig['side']}</b>\n"
                f"Kirish: <b>{fmt_price(entry)}</b>\n\n"
                "<i>TP/SL hali kiritilmagan.</i>"), InlineKeyboardMarkup(rows)
    filled = float(sig["filled_pct"])
    realized = float(sig["realized_pct"])
    price = await safe_last_price(sig["market"], sig["symbol"])

    lines = [f"⚙️ <b>#{sig['id']} {sig['symbol']} {sig['side']}</b>",
             f"Kirish: <b>{fmt_price(entry)}</b> · "
             f"Stop: <b>{fmt_price(float(sig['sl']))}</b>"]
    tps = [float(t) for t in sig["tps"]]
    lines.append("Maqsadlar: " + " · ".join(
        f"{'✅' if i < sig['tp_hit'] else '◻️'}{fmt_price(t)}"
        for i, t in enumerate(tps)))
    if filled > 0:
        lines.append(f"Yopilgan ulush: <b>{filled * 100:.0f}%</b> "
                     f"(to'plangan {realized:+.2f}%)")
    if price:
        live = realized + max(0.0, 1.0 - filled) * tracker.pnl_at(
            sig["side"], entry, price)
        lines.append(f"Joriy narx: <b>{fmt_price(price)}</b> → <b>{live:+.2f}%</b>")
    else:
        lines.append("<i>Joriy narx olinmadi</i>")

    be = " ✓" if abs(float(sig["sl"]) - entry) < 1e-12 else ""
    rows = [
        [InlineKeyboardButton(f"🛡 Stop → breakeven{be}", callback_data=f"mbe:{sid}"),
         InlineKeyboardButton("✏️ Stop", callback_data=f"msl:{sid}")],
        [InlineKeyboardButton("🎯 Maqsadlarni o'zgartirish", callback_data=f"mtp:{sid}")],
    ]
    if pending:
        rows.append([InlineKeyboardButton("✏️ Entry", callback_data=f"mentry:{sid}")])
    if sig["status"] == "ACTIVE" and filled < 0.999:
        rows.append([
            InlineKeyboardButton("✂️ 25%", callback_data=f"mpc:{sid}:25"),
            InlineKeyboardButton("✂️ 50%", callback_data=f"mpc:{sid}:50"),
            InlineKeyboardButton("✂️ 75%", callback_data=f"mpc:{sid}:75"),
        ])
    # PENDING'da "yopish" tushunchasi yo'q (pozitsiya hali OCHILMAGAN) —
    # xuddi shu tugma (close:) close_now()da PENDING uchun ALLAQACHON
    # bekor qilish sifatida ishlaydi, faqat matni aniqroq qilib ko'rsatiladi.
    rows.append([InlineKeyboardButton(
        "❌ Bekor qilish" if pending else "🔒 To'liq yopish", callback_data=f"close:{sid}")])
    rows.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _manage_guard(q):
    """Signalni oladi va huquqni tekshiradi. Mos bo'lmasa (None, None)."""
    sig = await db.get_signal(int(q.data.split(":")[1]))
    if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
        await q.edit_message_text("Bu signal allaqachon yopilgan yoki topilmadi.",
                                   reply_markup=MENU_BACK_KB)
        return None, None
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return None, None
    return sig, ws


async def notify_group(ctx, ws, sig, text: str) -> None:
    """O'zgarishni guruhga — asl signal postiga javob qilib yozadi."""
    if ws["type"] == "group" and ws["group_chat_id"]:
        try:
            await ctx.bot.send_message(
                ws["group_chat_id"], text, parse_mode=ParseMode.HTML,
                reply_to_message_id=sig["group_msg_id"],
                allow_sending_without_reply=True,
                message_thread_id=ws["group_topic_id"])
        except Exception:
            log.exception("Guruhga o'zgarish xabari yuborilmadi")


async def _show_manage(q, sig_id: int) -> None:
    sig = await db.get_signal(sig_id)
    if not sig:
        return
    text, kb = await manage_view(sig)
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def on_manage(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig, _ = await _manage_guard(q)
    if sig:
        await _show_manage(q, sig["id"])


async def on_manage_be(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Stopni kirish narxiga ko'chirish — eng ko'p ishlatiladigan amal,
    shuning uchun alohida tugma."""
    q = update.callback_query
    await q.answer()
    sig, ws = await _manage_guard(q)
    if not sig:
        return
    entry = float(sig["entry"])
    if abs(float(sig["sl"]) - entry) < 1e-12:
        await q.answer("Stop allaqachon breakeven'da.", show_alert=True)
        return
    # "✏️ Stop" oqimidagi bilan bir xil ogohlantirish — narx allaqachon
    # kirish narxidan "narigi tomonda" bo'lsa, breakeven'ga ko'chirish
    # signalni DARHOL yopib yuboradi.
    try:
        live_price = await tracker.provider(sig["market"]).last_price(
            sig["symbol"], fresh=True)
    except Exception:
        live_price = None
    if live_price:
        breached = (live_price <= entry) if sig["side"] == "LONG" else (live_price >= entry)
        if breached:
            await q.answer(
                f"Joriy narx ({fmt_price(live_price)}) kirish narxidan "
                f"{'past' if sig['side'] == 'LONG' else 'baland'} — breakeven'ga "
                "ko'chirish signalni DARHOL yopadi. Shuni xohlasangiz \"To'liq "
                "yopish\"ni bosing.", show_alert=True)
            return
    await db.set_stop(sig["id"], entry)
    await notify_group(ctx, ws, sig,
                        f"🛡 <b>#{sig['id']} {sig['symbol']}</b> — stop breakeven'ga "
                        f"ko'chirildi (<b>{fmt_price(entry)}</b>)")
    await _show_manage(q, sig["id"])


async def on_manage_sl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig, _ = await _manage_guard(q)
    if not sig:
        return
    AWAITING_SL[q.from_user.id] = sig["id"]
    await q.edit_message_text(
        f"✏️ #{sig['id']} {sig['symbol']} uchun <b>yangi stop</b> narxini yozing.\n"
        f"Hozirgi: <code>{fmt_price(float(sig['sl']))}</code>\n\n"
        "Bekor qilish uchun /bekor", parse_mode=ParseMode.HTML)


async def on_manage_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig, _ = await _manage_guard(q)
    if not sig:
        return
    if sig["status"] != "PENDING":
        await q.answer("Entry faqat hali tegmagan (PENDING) signalda o'zgartiriladi.",
                       show_alert=True)
        return
    AWAITING_ENTRY[q.from_user.id] = sig["id"]
    await q.edit_message_text(
        f"✏️ #{sig['id']} {sig['symbol']} uchun <b>yangi entry (limit)</b> narxini yozing.\n"
        f"Hozirgi: <code>{fmt_price(float(sig['entry']))}</code>\n\n"
        "Bekor qilish uchun /bekor", parse_mode=ParseMode.HTML)


async def on_manage_tp(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig, _ = await _manage_guard(q)
    if not sig:
        return
    AWAITING_TPS[q.from_user.id] = sig["id"]
    cur = " ".join(fmt_price(float(t)) for t in sig["tps"])
    await q.edit_message_text(
        f"🎯 #{sig['id']} {sig['symbol']} uchun <b>yangi maqsadlar</b>ni yozing "
        f"(bo'sh joy bilan ajrating).\nHozirgi: <code>{cur}</code>\n\n"
        "Bekor qilish uchun /bekor", parse_mode=ParseMode.HTML)


async def on_manage_partial(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig, ws = await _manage_guard(q)
    if not sig:
        return
    pct = int(q.data.split(":")[2])
    ev = await tracker.partial_close(sig["id"], pct / 100)
    if not ev:
        await q.answer("Yopib bo'lmadi (narx olinmadi yoki qism qolmagan).",
                       show_alert=True)
        return

    if ev["closes"]:
        # Depozit avtomatik yopilishdagidek yangilanadi, aks holda u jimgina
        # haqiqatdan uzoqlashib ketardi.
        if sig["alloc_amount"] is not None and ev["pnl"] is not None:
            await db.apply_deposit_delta(
                ws["id"], ev["pnl"] / 100 * float(sig["alloc_amount"]))
        icon = "✅" if (ev["pnl"] or 0) >= 0 else "❌"
        rtxt = f" ({ev['r']:+.2f}R)" if ev["r"] is not None else ""
        await notify_group(ctx, ws, sig,
                            f"{icon} <b>#{sig['id']} {sig['symbol']}</b> — qolgan qism "
                            f"yopildi @ <b>{fmt_price(ev['price'])}</b>\n"
                            f"Yakuniy: <b>{ev['pnl']:+.2f}%</b>{rtxt}")
        await q.edit_message_text(
            f"{icon} #{sig['id']} {sig['symbol']} to'liq yopildi: "
            f"<b>{ev['pnl']:+.2f}%</b>{rtxt}",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    await notify_group(ctx, ws, sig,
                        f"✂️ <b>#{sig['id']} {sig['symbol']}</b> — pozitsiyaning "
                        f"<b>{pct}%</b> i yopildi @ <b>{fmt_price(ev['price'])}</b>\n"
                        f"Joriy natija: <b>{ev['running']:+.2f}%</b> "
                        f"(qolgan {(1 - ev['filled']) * 100:.0f}%)")
    await _show_manage(q, sig["id"])


async def handle_manage_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Yangi stop / yangi maqsadlar matni. Ishlov berilgan bo'lsa True."""
    uid = update.effective_user.id
    msg = update.effective_message
    text = (msg.text or "").strip()

    sig_id = AWAITING_SL.pop(uid, None)
    if sig_id:
        sig = await db.get_signal(sig_id)
        if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
            await msg.reply_text("Signal allaqachon yopilgan.", reply_markup=MENU_BACK_KB)
            return True
        price = _parse_price(text)
        if price is None or price <= 0:
            AWAITING_SL[uid] = sig_id
            await msg.reply_text("Noto'g'ri raqam. Qayta kiriting yoki /bekor.")
            return True
        entry = float(sig["entry"])
        # Kirish narxidan juda uzoq qiymat deyarli doim xato yozuv (masalan
        # nol tushib qolgan) — signalni bejiz yopib yubormaslik uchun to'xtatamiz.
        if not (entry * 0.5 <= price <= entry * 1.5):
            AWAITING_SL[uid] = sig_id
            await msg.reply_text("Bu narx kirish narxidan juda uzoq. "
                                  "Tekshiring yoki /bekor.")
            return True
        # Foydalanuvchi: "stopni ko'tarsam, narx hali yetmagan bo'lsa ham
        # erta yopib yuboryapti". Sabab — agar yangi stop JORIY narxning
        # NARIGI tomonida bo'lsa (LONG: narx allaqachon stopdan PAST;
        # SHORT: allaqachon BALAND), signal KEYINGI tekshiruvda (odatda
        # sekundlar ichida) DARHOL yopiladi — bu texnik jihatdan to'g'ri
        # (stop haqiqatan ham allaqachon "tegilgan"), lekin foydalanuvchiga
        # "narx hali yetmagan" bo'lib tuyuladi, chunki ular buni CHART
        # dagi narx bilan emas, o'z fikridagi narx bilan solishtirishgan.
        # Shu sabab oldindan ANIQ ogohlantiramiz, jimgina qabul qilmaymiz.
        try:
            live_price = await tracker.provider(sig["market"]).last_price(
                sig["symbol"], fresh=True)
        except Exception:
            live_price = None
        if live_price:
            side = sig["side"]
            breached = (live_price <= price) if side == "LONG" else (live_price >= price)
            if breached:
                AWAITING_SL[uid] = sig_id
                await msg.reply_text(
                    f"⚠️ Joriy narx (<code>{fmt_price(live_price)}</code>) bu stopdan "
                    f"{'PAST' if side == 'LONG' else 'BALAND'} — signal KEYINGI "
                    "tekshiruvda DARHOL yopiladi (stop allaqachon tegilgan hisoblanadi). "
                    "Shuni xohlasangiz \"🔒 To'liq yopish\" tugmasidan foydalaning, "
                    "aks holda boshqa narx kiriting yoki /bekor.",
                    parse_mode=ParseMode.HTML)
                return True
        ws = await db.get_workspace(sig["workspace_id"])
        if not ws or not can_manage(uid, ws):
            return True
        await db.set_stop(sig_id, price)
        await notify_group(ctx, ws, sig,
                            f"🛡 <b>#{sig_id} {sig['symbol']}</b> — stop "
                            f"<b>{fmt_price(price)}</b> ga ko'chirildi")
        await msg.reply_text(f"✅ Stop <b>{fmt_price(price)}</b> ga o'rnatildi.",
                              parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return True

    sig_id = AWAITING_TPS.pop(uid, None)
    if sig_id:
        sig = await db.get_signal(sig_id)
        if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
            await msg.reply_text("Signal allaqachon yopilgan.", reply_markup=MENU_BACK_KB)
            return True
        tps = [x for x in (_parse_price(x) for x in text.split()) if x and x > 0]
        if not tps:
            AWAITING_TPS[uid] = sig_id
            await msg.reply_text("Noto'g'ri format. Qayta kiriting yoki /bekor.")
            return True
        # Allaqachon bajarilgan maqsadlardan kam qoldirib bo'lmaydi — tp_hit
        # indeksi ro'yxatdan chiqib ketib, kuzatuv chalkashib qolardi.
        if len(tps) < sig["tp_hit"]:
            AWAITING_TPS[uid] = sig_id
            await msg.reply_text(
                f"Kamida {sig['tp_hit']} ta maqsad kerak — {sig['tp_hit']} tasi "
                "allaqachon bajarilgan. Qayta kiriting yoki /bekor.")
            return True
        ws = await db.get_workspace(sig["workspace_id"])
        if not ws or not can_manage(uid, ws):
            return True
        tps = sorted(set(tps), reverse=(sig["side"] == "SHORT"))
        await db.set_tps(sig_id, tps)
        shown = " · ".join(fmt_price(t) for t in tps)
        await notify_group(ctx, ws, sig,
                            f"🎯 <b>#{sig_id} {sig['symbol']}</b> — maqsadlar "
                            f"yangilandi: <b>{shown}</b>")
        await msg.reply_text(f"✅ Maqsadlar: <b>{shown}</b>",
                              parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return True

    sig_id = AWAITING_ENTRY.pop(uid, None)
    if sig_id:
        sig = await db.get_signal(sig_id)
        if not sig or sig["status"] != "PENDING":
            await msg.reply_text(
                "Signal allaqachon bajarilgan yoki yopilgan — entry endi o'zgarmaydi.",
                reply_markup=MENU_BACK_KB)
            return True
        price = _parse_price(text)
        if price is None or price <= 0:
            AWAITING_ENTRY[uid] = sig_id
            await msg.reply_text("Noto'g'ri raqam. Qayta kiriting yoki /bekor.")
            return True
        old_entry = float(sig["entry"])
        # Eski entrydan juda uzoq qiymat deyarli doim xato yozuv — bejiz
        # noto'g'ri narxda signal "aktivlashtirib" yuborilmasligi uchun.
        if not (old_entry * 0.5 <= price <= old_entry * 1.5):
            AWAITING_ENTRY[uid] = sig_id
            await msg.reply_text("Bu narx eski entrydan juda uzoq. "
                                  "Tekshiring yoki /bekor.")
            return True
        if sig["sl"] is not None:
            err = parsing.validate({
                "entry": price, "sl": float(sig["sl"]),
                "tps": [float(t) for t in sig["tps"]], "side": sig["side"],
            })
            if err:
                AWAITING_ENTRY[uid] = sig_id
                await msg.reply_text(
                    f"❌ {err}\nMavjud stop/maqsadlar bilan mos kelmayapti. "
                    "Boshqa narx kiriting yoki /bekor.")
                return True
        ws = await db.get_workspace(sig["workspace_id"])
        if not ws or not can_manage(uid, ws):
            return True
        await db.set_entry(sig_id, price)
        await notify_group(ctx, ws, sig,
                            f"✏️ <b>#{sig_id} {sig['symbol']}</b> — entry "
                            f"<b>{fmt_price(price)}</b> ga o'zgartirildi")
        await msg.reply_text(f"✅ Entry <b>{fmt_price(price)}</b> ga o'rnatildi.",
                              parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return True

    return False


def _tpsl_prompt(sig_id: int, symbol: str) -> str:
    return (f"📐 <b>#{sig_id} {symbol}</b> — TP va SL kiriting:\n"
            "<code>tp 67000 68500 sl 64000</code>\n"
            "yoki qisqa: <code>67000 68500 64000</code> (oxirgisi — stop).")


async def handle_tpsl_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Limit to'lib, TP/SL HALI kiritilmagan signal uchun birinchi marta
    TP/SL javobi. Ishlov berilgan bo'lsa True (`AWAITING_TPS`dan farqli —
    u ALLAQACHON mavjud TP'larni o'zgartiradi, bu esa birinchi joylashtirish)."""
    uid = update.effective_user.id
    msg = update.effective_message
    text = (msg.text or "").strip()

    sig_id = AWAITING_TPSL.pop(uid, None)
    if not sig_id:
        return False

    sig = await db.get_signal(sig_id)
    if not sig or sig["status"] != "ACTIVE" or sig["sl"] is not None:
        # Signal allaqachon yopilgan, yoki (masalan boshqa yo'l bilan)
        # TP/SL allaqachon o'rnatilgan bo'lsa — bu javob endi ma'nosiz.
        await msg.reply_text("Bu so'rov endi kerak emas.", reply_markup=MENU_BACK_KB)
        return True

    parsed = parsing.parse_tp_sl(text)
    if parsed is None:
        AWAITING_TPSL[uid] = sig_id
        await msg.reply_text(
            "O'qiy olmadim. Namuna: <code>tp 67000 68500 sl 64000</code>\n"
            "yoki qisqa: <code>67000 68500 64000</code> (oxirgisi — stop). "
            "Yoki /bekor yozing.", parse_mode=ParseMode.HTML)
        return True

    entry = float(sig["entry"])
    side = sig["side"]
    tps = sorted(set(parsed["tps"]), reverse=(side == "SHORT"))
    err = parsing.validate({"entry": entry, "sl": parsed["sl"], "tps": tps, "side": side})
    if err:
        AWAITING_TPSL[uid] = sig_id
        await msg.reply_text(f"❌ {err}\nQayta kiriting yoki /bekor.")
        return True

    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(uid, ws):
        return True

    await db.set_tp_sl(sig_id, parsed["sl"], tps)
    body = draft_text({"symbol": sig["symbol"], "side": side, "entry": entry,
                        "sl": parsed["sl"], "tps": tps, "market": sig["market"]},
                       sig_id)
    await msg.reply_text(f"✅ TP/SL joylashtirildi.\n\n{body}", parse_mode=ParseMode.HTML,
                          reply_markup=MENU_BACK_KB)
    await notify_group(ctx, ws, sig,
                        f"📐 <b>#{sig_id} {sig['symbol']}</b> — TP/SL joylashtirildi:\n{body}")
    return True


async def on_tpsl_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """"📐 TP/SL kiriting" tugmasi — dastlabki DM so'rovi o'tkazib
    yuborilgan/kechiktirilgan bo'lsa, AWAITING_TPSL'ni qayta yoqadi."""
    q = update.callback_query
    await q.answer()
    sig_id = int(q.data.split(":", 1)[1])
    sig = await db.get_signal(sig_id)
    if not sig or sig["status"] != "ACTIVE" or sig["sl"] is not None:
        await q.answer("Bu so'rov endi kerak emas.", show_alert=True)
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return
    AWAITING_TPSL[q.from_user.id] = sig_id
    await q.message.reply_text(_tpsl_prompt(sig_id, sig["symbol"]), parse_mode=ParseMode.HTML)


async def on_close_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig_id = int(q.data.split(":", 1)[1])
    sig = await db.get_signal(sig_id)
    if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
        await q.edit_message_text("Bu signal allaqachon yopilgan yoki topilmadi.",
                                   reply_markup=MENU_BACK_KB)
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        return

    if sig["status"] == "PENDING":
        text = f"#{sig_id} {sig['symbol']} hali entryga tegmagan. Bekor qilinsinmi?"
    else:
        price = await safe_last_price(sig["market"], sig["symbol"])
        est_txt = ""
        if price:
            entry = float(sig["entry"])
            filled = float(sig["filled_pct"])
            realized = float(sig["realized_pct"])
            rest = max(0.0, 1.0 - filled)
            est = realized + rest * tracker.pnl_at(sig["side"], entry, price)
            est_txt = f" (~{est:+.2f}%)"
        text = f"#{sig_id} {sig['symbol']} joriy narxda yopilsinmi?{est_txt}"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha, yopish", callback_data=f"closeok:{sig_id}"),
        InlineKeyboardButton("↩️ Yo'q", callback_data="closeno"),
    ]])
    await q.edit_message_text(text, reply_markup=kb)


async def on_close_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig_id = int(q.data.split(":", 1)[1])
    sig = await db.get_signal(sig_id)
    if not sig:
        await q.edit_message_text("Topilmadi.", reply_markup=MENU_BACK_KB)
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        return

    ev = await tracker.close_now(sig_id)
    if not ev:
        await q.edit_message_text("Yopib bo'lmadi (narx olinmadi yoki allaqachon yopilgan).",
                                   reply_markup=MENU_BACK_KB)
        return

    if ev["status"] == "CANCELLED":
        await q.edit_message_text(f"🗑 #{sig_id} {ev['symbol']} bekor qilindi (entryga tegmagan edi).",
                                   reply_markup=MENU_BACK_KB)
        return

    pnl, r = ev["pnl"], ev["r"]

    # poll_job() avtomatik yopilganda depozitni yangilaydi — qo'lda yopish ham
    # xuddi shunday qilishi SHART, aks holda depozit jimgina haqiqatdan uzoqlashadi.
    if sig["alloc_amount"] is not None:
        await db.apply_deposit_delta(ws["id"], pnl / 100 * float(sig["alloc_amount"]))

    icon = "✅" if pnl >= 0 else "❌"
    rtxt = f" ({r:+.2f}R)" if r is not None else ""
    await q.edit_message_text(
        f"{icon} #{sig_id} {ev['symbol']} qo'lda yopildi @ {fmt_price(ev['price'])}\n"
        f"Yakuniy: {pnl:+.2f}%{rtxt}", reply_markup=MENU_BACK_KB)

    if ws["type"] in ("group", "personal"):
        txt = (f"{icon} <b>#{sig_id} {ev['symbol']}</b> — vaqtidan oldin yopildi "
               f"@ <b>{fmt_price(ev['price'])}</b>\nYakuniy: <b>{pnl:+.2f}%</b>{rtxt}")
        # close_now() endi natijani bazaga yozib bo'lgan — yangilangan yozuv
        # (closed_at/exit_price/pnl_pct) bilan xuddi avtomatik TP/SL yopilishidagi
        # kabi grafik chiziladi (chart.py — real shamlar + entry/TP/SL chiziqlari).
        photo = None
        sig2 = await db.get_signal(sig_id)
        if sig2:
            try:
                photo = await chart.signal_chart(sig2, ws["name"], ctx.bot.username)
            except Exception:
                log.warning("Grafik yasalmadi (qo'lda yopish, #%s)", sig_id, exc_info=True)
        if ws["type"] == "group" and ws["group_chat_id"]:
            try:
                if photo:
                    await ctx.bot.send_photo(
                        ws["group_chat_id"], InputFile(photo, "signal.png"), caption=txt,
                        parse_mode=ParseMode.HTML, reply_to_message_id=sig["group_msg_id"],
                        allow_sending_without_reply=True, message_thread_id=ws["group_topic_id"])
                else:
                    await ctx.bot.send_message(
                        ws["group_chat_id"], txt, parse_mode=ParseMode.HTML,
                        reply_to_message_id=sig["group_msg_id"],
                        allow_sending_without_reply=True, message_thread_id=ws["group_topic_id"])
            except Exception:
                log.exception("Guruhga yuborilmadi (qo'lda yopish)")
        elif ws["type"] == "personal":
            # Avtomatik (TP/SL) yopilishda shaxsiy chatga grafik ALLAQACHON
            # yuborilardi (news_scan_job'dagi emas, tracker/poll_job orqali
            # ishlovchi yo'lda) — lekin QO'LDA yopishda bu shoxcha umuman
            # yozilmagan edi (faqat matn tahrirlanardi, qo'shimcha xabar/
            # grafik yo'q). Foydalanuvchi: "shaxsiy kabinetda natija grafik
            # bilan kelmayabti" — aynan shu qo'lda yopish yo'li edi.
            try:
                if photo:
                    await ctx.bot.send_photo(
                        ws["owner_id"], InputFile(photo, "signal.png"), caption=txt,
                        parse_mode=ParseMode.HTML, reply_to_message_id=sig["group_msg_id"],
                        allow_sending_without_reply=True)
                else:
                    await ctx.bot.send_message(
                        ws["owner_id"], txt, parse_mode=ParseMode.HTML,
                        reply_to_message_id=sig["group_msg_id"],
                        allow_sending_without_reply=True)
            except Exception:
                log.exception("Shaxsiy xabar yuborilmadi (qo'lda yopish)")


async def on_close_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("↩️ Bekor qilindi, signal ochiq qoldi.", reply_markup=MENU_BACK_KB)


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def stats_nav_kb(mode: str, y: int | None = None, m: int | None = None) -> InlineKeyboardMarkup:
    now = datetime.now(stats.TZ)
    tabs = [
        InlineKeyboardButton("• Barchasi" if mode == "all" else "Barchasi", callback_data="st:all"),
        InlineKeyboardButton(
            "• Oy" if mode == "m" else "Oy",
            callback_data=f"st:m:{y}:{m}" if mode == "m" else f"st:m:{now.year}:{now.month}"),
        InlineKeyboardButton(
            "• Yil" if mode == "y" else "Yil",
            callback_data=f"st:y:{y}" if mode == "y" else f"st:y:{now.year}"),
    ]
    rows = [tabs]

    if mode == "m":
        py, pm = _shift_month(y, m, -1)
        nav = [InlineKeyboardButton(f"◀ {stats.MONTHS_UZ[pm - 1][:3]}", callback_data=f"st:m:{py}:{pm}")]
        ny, nm = _shift_month(y, m, 1)
        if (ny, nm) <= (now.year, now.month):
            nav.append(InlineKeyboardButton(f"{stats.MONTHS_UZ[nm - 1][:3]} ▶", callback_data=f"st:m:{ny}:{nm}"))
        rows.append(nav)
    elif mode == "y":
        nav = [InlineKeyboardButton(f"◀ {y - 1}", callback_data=f"st:y:{y - 1}")]
        if y < now.year:
            nav.append(InlineKeyboardButton(f"{y + 1} ▶", callback_data=f"st:y:{y + 1}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton("📄 PDF hisobot", callback_data="pdfrep")])
    rows.append(list(MENU_BACK_KB.inline_keyboard[0]))
    return InlineKeyboardMarkup(rows)


async def send_pdf_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """PDF — har doim BUTUN davr bo'yicha (davr tugmalari faqat ekrandagi
    matnga tegishli; hisobot to'liq tarixni beradi)."""
    msg = update.effective_message
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await msg.reply_text(text, reply_markup=kb)
        return

    note = await msg.reply_text("📄 Hisobot tayyorlanmoqda…")
    deposit = float(ws["deposit"]) if ws["deposit"] is not None else None
    try:
        buf = await stats.pdf_report(ws["id"], ws["name"], deposit, can_manage(uid, ws))
    finally:
        try:
            await note.delete()
        except Exception:
            pass
    if buf is None:
        await msg.reply_text("Hali yopilgan signal yo'q — hisobot bo'sh bo'lardi.",
                              reply_markup=MENU_BACK_KB)
        return
    fname = f"hisobot-{datetime.now(stats.TZ):%Y-%m-%d}.pdf"
    await msg.reply_document(InputFile(buf, fname), reply_markup=MENU_BACK_KB)


async def cmd_pdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_pdf_report(update, ctx)


async def on_pdf_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await send_pdf_report(update, ctx)


async def stats_view_text(ws, uid: int, mode: str, y: int | None = None, m: int | None = None) -> str:
    deposit = float(ws["deposit"]) if ws["deposit"] is not None else None
    show_money = can_manage(uid, ws)
    if mode == "m":
        a, b = stats.month_bounds(y, m)
        return await stats.summary(ws["id"], a, b, f"{stats.MONTHS_UZ[m - 1]} {y}",
                                    deposit=deposit, show_money=show_money)
    if mode == "y":
        a, b = stats.year_bounds(y)
        return await stats.summary(ws["id"], a, b, f"{y}-yil natijalari",
                                    deposit=deposit, show_money=show_money)
    return await stats.summary(ws["id"], deposit=deposit, show_money=show_money)


async def on_stats_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, q.from_user.id, ws):
        text, kb = access_denied(ws)
        await q.edit_message_text(text, reply_markup=kb)
        return
    parts = q.data.split(":")  # st:all | st:m:Y:M | st:y:Y
    mode = parts[1]
    y = int(parts[2]) if mode in ("m", "y") else None
    m = int(parts[3]) if mode == "m" else None
    text = await stats_view_text(ws, q.from_user.id, mode, y, m)
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=stats_nav_kb(mode, y, m))


def symbols_nav_kb(y: int | None, m: int | None) -> InlineKeyboardMarkup:
    now = datetime.now(stats.TZ)
    if y is None:  # "Barchasi" ko'rinishidan — orqaga joriy oyga
        py, pm = now.year, now.month
        ny, nm = None, None
    else:
        py, pm = _shift_month(y, m, -1)
        ny_, nm_ = _shift_month(y, m, 1)
        ny, nm = (ny_, nm_) if (ny_, nm_) <= (now.year, now.month) else (None, None)

    row = [InlineKeyboardButton(f"◀ {stats.MONTHS_UZ[pm - 1][:3]}", callback_data=f"sym:{py}:{pm}")]
    if y is not None:
        row.append(InlineKeyboardButton("Barchasi", callback_data="sym:all"))
    if ny is not None:
        row.append(InlineKeyboardButton(f"{stats.MONTHS_UZ[nm - 1][:3]} ▶", callback_data=f"sym:{ny}:{nm}"))
    return InlineKeyboardMarkup([row, list(MENU_BACK_KB.inline_keyboard[0])])


async def symbols_view_text(ws_id: int, y: int | None, m: int | None) -> str:
    if y is None:
        return await stats.symbols_table(ws_id, title="Barcha davr")
    a, b = stats.month_bounds(y, m)
    return await stats.symbols_table(ws_id, a, b, title=f"{stats.MONTHS_UZ[m - 1]} {y}")


async def on_symbols_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, q.from_user.id, ws):
        text, kb = access_denied(ws)
        await q.edit_message_text(text, reply_markup=kb)
        return
    parts = q.data.split(":")
    y, m = (None, None) if parts[1] == "all" else (int(parts[1]), int(parts[2]))
    text = await symbols_view_text(ws["id"], y, m)
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=symbols_nav_kb(y, m))


async def send_web_link(target, ws) -> None:
    """Ochiq sahifa havolasi — ulashish uchun. Havola ALOHIDA qatorda va
    <code> ichida: shunda uzun manzil ko'chirishga qulay bo'ladi va Telegram
    uni oldindan ko'rish rasmiga aylantirib yubormaydi."""
    url = web_page_url(ws)
    if not url:
        await target.reply_text(
            "🌐 Ochiq sahifa hali yoqilmagan.\n\n"
            "Yoqish uchun: <code>/public on</code> yozing — so'rov moderatorga "
            "boradi. Tasdiqlangach guruhingiz uchun jonli havola paydo bo'ladi: "
            "unda statistika, equity grafigi va savdolar tarixi ko'rinadi.",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return
    await target.reply_text(
        f"🌐 <b>{html.escape(ws['name'])}</b> — ochiq natijalar sahifasi:\n\n"
        f"<code>{html.escape(url)}</code>\n\n"
        "Bu havolani guruhga pin qilib qo'ysangiz yoki reklamada ulashsangiz "
        "bo'ladi. Sahifa bazadan jonli o'qiladi — har yangi natija o'zi "
        "qo'shiladi, qo'lda yangilash shart emas.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            # Mini App tugmasi faqat shaxsiy chatda ishlaydi; guruhda oddiy
            # URL tugmasi (main_menu_kb dagi bilan bir xil sabab).
            [InlineKeyboardButton("🌐 Sahifani ochish", web_app=WebAppInfo(url=url))
             if target.chat.type == "private"
             else InlineKeyboardButton("🌐 Sahifani ochish", url=url)],
            [InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")],
        ]))


async def cmd_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/sahifa — guruhning ochiq natijalar havolasi."""
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    await send_web_link(update.message, ws)


async def on_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, q.from_user.id, ws):
        text, kb = access_denied(ws)
        await q.message.reply_text(text, reply_markup=kb)
        return
    action = q.data.split(":", 1)[1]

    if action == "weblink":
        await send_web_link(q.message, ws)
    elif action == "stats":
        # Statistika ochiq signallar uchun jonli narx so'raydi — sekin bo'lishi
        # mumkin, shuning uchun "yozmoqda" belgisi ko'rsatiladi.
        async with busy(ctx.bot, q.message.chat_id):
            text = await stats_view_text(ws, q.from_user.id, "all")
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=stats_nav_kb("all"))
    elif action == "symbols":
        async with busy(ctx.bot, q.message.chat_id):
            text = await symbols_view_text(ws["id"], None, None)
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=symbols_nav_kb(None, None))
    elif action == "open":
        async with busy(ctx.bot, q.message.chat_id):
            text, kb = await open_signals_view(ws, q.from_user.id)
        rows = (list(kb.inline_keyboard) if kb else []) + list(MENU_BACK_KB.inline_keyboard)
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(rows))
    elif action == "deposit":
        if not can_manage(q.from_user.id, ws):
            return
        cur = ws["deposit"]
        txt = f"{float(cur):,.2f}" if cur is not None else "belgilanmagan"
        await q.message.reply_text(
            f"Joriy depozit ({ws['name']}): <b>{txt}</b>\n\n"
            "Yangilash uchun: <code>/depozit 1000</code>", parse_mode=ParseMode.HTML,
            reply_markup=MENU_BACK_KB)
    elif action == "equity":
        deposit = float(ws["deposit"]) if ws["deposit"] is not None else None
        buf = await stats.equity_chart(ws["id"], deposit)
        if buf is None:
            await q.message.reply_text("Grafik uchun kamida 2 ta yopilgan signal kerak.",
                                        reply_markup=MENU_BACK_KB)
        else:
            await q.message.reply_photo(InputFile(buf, "equity.png"), reply_markup=MENU_BACK_KB)


async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await update.effective_message.reply_text(text, reply_markup=kb)
        return
    await update.effective_message.reply_text(
        "Bosh menyu:",
        reply_markup=main_menu_kb(uid, ws, update.effective_chat.type == "private"))


# ─────────────────────────── Guruhni ro'yxatdan o'tkazish ───────────────────────────

async def refresh_logo(bot, ws_id: int, chat_id: int) -> bool:
    """Guruh AVATARINI olib, bazaga 256x256 PNG qilib yozadi.

    Nega file_id emas, BAYT? Veb servis alohida jarayon va unda BOT_TOKEN
    yo'q — file_id bilan rasmni yuklab ololmaydi. Bayt bazada tursa, veb uni
    to'g'ridan to'g'ri beradi va Telegram'ga umuman murojaat qilmaydi.

    Rasm yo'q bo'lsa (guruhda avatar qo'yilmagan) — bazadagi eskisi tozalanadi
    va veb harf-avatarga qaytadi."""
    try:
        chat = await bot.get_chat(chat_id)
    except Exception:
        log.warning("Logotip: #%s guruh ma'lumoti olinmadi", ws_id, exc_info=True)
        return False

    photo = getattr(chat, "photo", None)
    if not photo:
        await db.set_workspace_logo(ws_id, None)
        return False
    try:
        f = await bot.get_file(photo.big_file_id)
        raw = bytes(await f.download_as_bytearray())
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        # Kvadratga qirqib, keyin kichraytiramiz: Telegram avatari kvadrat
        # bo'lsa ham, kelajakda boshqacha bo'lib qolsa sahifa buzilmasin.
        side = min(img.size)
        left, top = (img.width - side) // 2, (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((256, 256))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        await db.set_workspace_logo(ws_id, buf.getvalue())
        return True
    except Exception:
        log.warning("Logotip: #%s rasmi yuklanmadi", ws_id, exc_info=True)
        return False


async def logo_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Logotiplarni sutkada bir marta yangilaydi — guruh avatarini o'zgartirsa
    sahifada ham o'zgarsin. Bir siklda ko'pi bilan 25 ta guruh."""
    try:
        rows = await db.logo_targets(24)
    except Exception:
        log.exception("Logotip siklida xato (bazadan o'qishda)")
        return
    for r in rows:
        await refresh_logo(ctx.bot, r["id"], r["group_chat_id"])


async def cmd_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("Bu buyruq faqat guruh ichida ishlaydi.")
        return

    uid = update.effective_user.id
    try:
        member = await ctx.bot.get_chat_member(chat.id, uid)
    except Exception:
        await update.message.reply_text("Guruh a'zoligini tekshirib bo'lmadi.")
        return
    if member.status not in ("creator", "administrator") and not is_admin(uid):
        await update.message.reply_text("Faqat guruh admini /setup qila oladi.")
        return

    existing = await db.get_workspace_by_group(chat.id)
    if existing:
        await update.message.reply_text(f"Bu guruh allaqachon ro'yxatdan o'tgan: {existing['name']}")
        return

    if not is_admin(uid):
        owned = await db.get_group_workspace_by_owner(uid)
        if owned:
            await update.message.reply_text(
                f"Sizda allaqachon boshqa guruh bor: \"{owned['name']}\". "
                "Har bir admin faqat bitta guruhni boshqara oladi.")
            return

    topic_id = update.message.message_thread_id
    name = chat.title or "Guruh"
    wid = await db.create_group_workspace(uid, chat.id, name, topic_id)
    log.info("Yangi workspace: #%s %s (owner=%s chat=%s topic=%s)",
              wid, name, uid, chat.id, topic_id)
    await update.message.reply_text(
        f"✅ \"{name}\" workspace sifatida ro'yxatdan o'tdi!\n"
        "Endi botga shaxsiy xabar yozib (/start) signal kirita olasiz."
    )
    # Guruh avatari darhol olinadi — ochiq sahifada logotip bo'lib turadi.
    await refresh_logo(ctx.bot, wid, chat.id)


# ─────────────────────────── Narx matnini o'qish ───────────────────────────
# (Ilgari sehrgar blokining ichida edi — sehrgar OLIB TASHLANDI, lekin bu
#  yordamchi stop/entry/maqsad tahririda va depozitda ham ishlatiladi.)

def _parse_price(raw: str) -> float | None:
    try:
        return float(raw.strip().replace(" ", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


# ─────────────────────────── Signal kiritish — yo'riqnoma ───────────────────────────
# Sehrgar olib tashlangach "➕ Yangi signal" tugmasi endi FORMATNI
# ko'rsatadi — odam signalni to'g'ridan-to'g'ri yozadi. Uchala usul
# (to'liq / limit / market) bitta ekranda, chunki eng ko'p beriladigan
# savol aynan "qanday yozaman?" edi.
NEW_SIGNAL_HELP = (
    "✍️ <b>Signalni shunchaki yozib yuboring.</b>\n\n"
    "<b>1. To'liq</b> — hamma daraja birga:\n"
    "<code>BTCUSDT long entry 65000 tp 67000 68500 sl 64000</code>\n"
    "yoki qisqa: <code>BTCUSDT long 65000 67000 68500 64000</code>\n\n"
    "<b>2. Limit</b> — faqat kirish narxi, TP/SL limit to'lgach so'raladi:\n"
    "<code>BTCUSDT long 65000</code>\n\n"
    "<b>3. Darhol (market)</b> — narxni bot o'zi oladi:\n"
    "<code>BTCUSDT long market</code>\n\n"
    "<i>SHORT uchun \"long\" o'rniga \"short\" yozing. "
    "Grafik rasmini yuborsangiz ham o'qiyman.</i>"
)


async def on_new_signal_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(NEW_SIGNAL_HELP, parse_mode=ParseMode.HTML,
                              reply_markup=menu_back_kb(await user_lang(q.from_user.id)))


async def cmd_new_signal_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        NEW_SIGNAL_HELP, parse_mode=ParseMode.HTML,
        reply_markup=menu_back_kb(await user_lang(update.effective_user.id)))


# ─────────────────────────── Signal kiritish — tezkor usul ───────────────────────────

def _vision_symbols(draft: dict) -> None:
    """Grafikdan o'qilgan juftlik nomidan nomzodlar ro'yxatini yasaydi.

    TradingView skrinshotida nom ko'pincha "BINANCE:BTCUSDT.P" yoki
    "MEXC:BTCUSDT" ko'rinishida bo'ladi. Bunday satr birjaga to'g'ridan-to'g'ri
    berilsa topilmaydi (birja prefiksi qo'shilib ketadi), shuning uchun undan
    ajratilgan so'zlar ham nomzod sifatida qo'shiladi — resolve_symbol
    ularni birma-bir sinab ko'radi."""
    raw = (draft.get("symbol") or "").strip()
    if not raw:
        return
    cands = [raw]
    if ":" in raw:
        cands.append(raw.rsplit(":", 1)[1])
    for c in parsing.symbol_candidates(raw):
        if c not in cands:
            cands.append(c)
    draft["symbol"] = cands[0]
    draft["symbols"] = cands


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    uid = update.effective_user.id
    # Kanaldan forward qilingan post rasm bo'lishi mumkin — signal deb
    # o'qilmasin, kanal qo'shish oqimiga yo'naltiramiz.
    if AWAITING_CHANNEL.pop(uid, None) and is_admin(uid):
        await handle_channel_add(update, ctx)
        return
    if AWAITING_BROADCAST.pop(uid, None) and is_admin(uid):
        await handle_broadcast_input(update, ctx)
        return

    # "🖼 Rasm yuklash" bosilgandan keyingi rasm — yangi signal deb o'qilmaydi,
    # tayyor qoralamaga biriktiriladi va yakuniy ko'rishga o'tiladi.
    token = AWAITING_SIGNAL_PHOTO.pop(uid, None)
    if token:
        item = PENDING.get(token)
        if not item:
            await msg.reply_text("Bu so'rov eskirgan.", reply_markup=MENU_BACK_KB)
            return
        item["file_id"] = msg.photo[-1].file_id
        item["gen"] = None
        item["want_bot_chart"] = False
        await msg.reply_text(
            "📈 Yopilgandagi natija grafigi qaysi taym freymda chizilsin?",
            reply_markup=tf_kb(token))
        return

    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not can_manage(update.effective_user.id, ws):
        return

    caption = msg.caption or ""
    file_id = msg.photo[-1].file_id
    draft = parsing.parse(caption)
    source = "caption"

    if draft is None:
        note = await msg.reply_text("🔎 Grafikni o'qiyapman…")
        f = await ctx.bot.get_file(file_id)
        data = bytes(await f.download_as_bytearray())
        # Rasm ostidagi yozuv modelga MASLAHAT sifatida beriladi: ko'pincha
        # juftlik nomi yoki tomon aynan shu yerda bo'ladi, garchi to'liq
        # signal sifatida o'qib bo'lmagan bo'lsa ham.
        async with busy(ctx.bot, msg.chat_id):
            draft = await vision.read_chart(data, hint=caption.strip())
        try:
            await note.delete()      # o'qish tugadi — kutish xabari kerak emas
        except Exception:
            pass
        source = "vision"
        if draft is None:
            await msg.reply_text(
                "Darajalarni o'qiy olmadim. Rasm ostiga yozib yuboring, masalan:\n"
                "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>",
                parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB,
            )
            return
        _vision_symbols(draft)

    await show_preview(msg, ctx, draft, file_id, source, ws["id"])


async def on_text_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Rasmsiz matnli signal yoki tahrir javobi."""
    uid = update.effective_user.id
    msg = update.effective_message
    text = msg.text or ""

    if AWAITING_CHANNEL.pop(uid, None) and is_admin(uid):
        await handle_channel_add(update, ctx)
        return

    if AWAITING_HASHTAG.pop(uid, None) and is_admin(uid):
        await handle_hashtag_add(update, ctx)
        return

    if AWAITING_BROADCAST.pop(uid, None) and is_admin(uid):
        await handle_broadcast_input(update, ctx)
        return

    # News Trade AI/surge posti ostidagi "📝 Jurnalga kiritish" tugmasidan
    # kelgan — tiker allaqachon ma'lum, xabarga QO'SHIB parsing.parse()ga
    # beriladi (parse() tikersiz ishlamaydi, shuning uchun bu yerda oddiy
    # matn birlashtiriladi — parsing.py'ga tegilmaydi).
    pending_journal = AWAITING_JOURNAL_SYMBOL.get(uid)
    if pending_journal:
        symbol, journal_ws_id = pending_journal
        AWAITING_JOURNAL_SYMBOL.pop(uid, None)
        draft = parsing.parse(f"{symbol} {text}")
        if draft is None:
            AWAITING_JOURNAL_SYMBOL[uid] = pending_journal
            await msg.reply_text(
                "O'qiy olmadim. Namuna: <code>LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
                "Yoki /bekor yozing.", parse_mode=ParseMode.HTML)
            return
        ws = await db.get_workspace(journal_ws_id)
        if not ws:
            return
        await show_preview(msg, ctx, draft, None, "jurnal", ws["id"])
        return

    # Limit to'lib, TP/SL HALI kiritilmagan signal uchun birinchi javob.
    if await handle_tpsl_input(update, ctx):
        return

    # Ochiq pozitsiyani boshqarish: yangi stop / yangi maqsadlar.
    if await handle_manage_input(update, ctx):
        return

    alloc_sig_id = AWAITING_ALLOC.get(uid)
    if alloc_sig_id:
        amount = _parse_price(text)
        if amount is None or amount <= 0:
            await msg.reply_text("Noto'g'ri summa. Qayta kiriting yoki ⏭ tugmasini bosing.")
            return
        AWAITING_ALLOC.pop(uid, None)
        sig = await db.get_signal(alloc_sig_id)
        ws = await db.get_workspace(sig["workspace_id"]) if sig else None
        if sig and ws and ws["deposit"] is not None:
            await db.set_signal_allocation(alloc_sig_id, amount, float(ws["deposit"]))
            await msg.reply_text(
                f"✅ Belgilandi: <b>{amount:,.2f}</b> (depozit: {float(ws['deposit']):,.2f})",
                parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    token = AWAITING_EDIT.get(uid)
    if token and token in PENDING:
        AWAITING_EDIT.pop(uid, None)
        draft = parsing.parse(text)
        if draft is None:
            AWAITING_EDIT[uid] = token
            await msg.reply_text("O'qiy olmadim. Yana urinib ko'ring yoki /bekor yozing.")
            return
        item = PENDING[token]
        ws = await db.get_workspace(item["workspace_id"])
        if not ws or not can_manage(uid, ws):
            PENDING.pop(token, None)
            return
        item["draft"] = draft
        await show_preview(msg, ctx, draft, item["file_id"], "tahrir", ws["id"], token)
        return

    # `allow_partial=True` — sehrgar olib tashlangani sabab uning ikki
    # imkoniyati shu yerga ko'chirildi: "BTC long market" (narx jonli
    # olinadi) va "BTC long 65000" (TP/SL limit to'lgach so'raladi).
    # Oddiy suhbatni signal deb o'qib yubormaslik uchun bu formatlarda
    # long/short so'zi majburiy (parsing.parse izohiga qarang).
    draft = parsing.parse(text, allow_partial=True)
    if not draft:
        return  # oddiy suhbat — signalga o'xshamaydi, e'tiborsiz qoldiramiz

    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not can_manage(uid, ws):
        return

    # "market" yozilgan, lekin narx ko'rsatilmagan — jonli narxni O'ZIMIZ
    # olamiz (avval sehrgarning "Darhol" tugmasi shuni qilardi).
    # Tasdiqlash lahzasida narx yana bir marta yangilanadi (#128) — bu
    # yerdagi narx ko'rikda ko'rsatish uchun.
    if draft.get("entry") is None:
        sym, market = await resolve_symbol(draft.get("symbols") or [draft["symbol"]])
        if not sym:
            await msg.reply_text(
                f"❌ <code>{html.escape(draft['symbol'])}</code> topilmadi.",
                parse_mode=ParseMode.HTML, reply_markup=menu_back_kb(await user_lang(uid)))
            return
        price = await safe_last_price(market, sym)
        if not price:
            await msg.reply_text(
                "Narx olinmadi — narxni o'zingiz yozing, masalan:\n"
                f"<code>{html.escape(sym)} long 65000</code>",
                parse_mode=ParseMode.HTML)
            return
        draft["symbol"], draft["symbols"], draft["market"] = sym, [sym], market
        draft["entry"] = price

    await show_preview(msg, ctx, draft, None, "matn", ws["id"])


async def on_group_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Debug: guruh/mavzu ID'larini aniqlash uchun loglaydi (masalan mavjud
    workspace'ga mavzu qo'shish kerak bo'lganda)."""
    chat = update.effective_chat
    msg = update.effective_message
    log.info("DEBUG guruh xabari: chat_id=%s title=%r type=%s thread_id=%s",
              chat.id, chat.title, chat.type, msg.message_thread_id)


async def resolve_symbol(cands: list[str]) -> tuple[str | None, str]:
    """Juftlik nomzodlarini birjada birma-bir tekshiradi.

    Matndan qaysi so'z juftlik ekanini aniq bilib bo'lmaydi ("Yangi signal:
    btc long..." — qaysi biri?), shuning uchun tanlovni BIRJAGA qoldiramiz:
    ro'yxatda topilgani — o'sha. Avval hamma nomzod kripto bo'yicha, keyin
    forex bo'yicha tekshiriladi (kripto — keng tarqalgan holat).

    Qimmat emas: ikkala manba ham juftliklar ro'yxatini 1 soatga keshlaydi,
    ya'ni bu oddiy to'plamda qidiruv, tarmoq so'rovi emas."""
    for raw in cands:
        try:
            sym = await exchange.resolve(raw)
        except Exception:
            log.warning("Kripto juftliklar ro'yxati olinmadi", exc_info=True)
            break
        if sym:
            return sym, "crypto"
    if forex.enabled():
        for raw in cands:
            try:
                sym = await forex.resolve(raw)
            except Exception:
                log.warning("Forex juftliklar ro'yxati olinmadi", exc_info=True)
                break
            if sym:
                return sym, "forex"
    # Aksiyalar — ENG OXIRIDA. Sabab: "BTC" kabi so'z tasodifan biror tiker
    # bilan to'qnashib qolsa, kripto ustun bo'lib qolsin (bot asosan kripto
    # uchun ishlatiladi).
    if stocks.enabled():
        # Faqat DASTLABKI ikkita nomzod: aksiya tekshiruvi — tarmoq so'rovi
        # (kripto va forex esa keshdagi ro'yxatda qidiruv). Twelve Data bepul
        # rejasi daqiqasiga 8 so'rov beradi, oltita nomzodni sinash uni bir
        # xabarda yeb qo'yishi mumkin edi.
        for raw in cands[:2]:
            try:
                sym = await stocks.resolve(raw)
            except Exception:
                log.warning("Aksiyalar ro'yxati olinmadi", exc_info=True)
                break
            if sym:
                return sym, "stock"
    return None, "crypto"


async def show_preview(msg, ctx, draft: dict, file_id, source: str, workspace_id: int,
                        token: str | None = None) -> None:
    cands = draft.get("symbols") or [draft["symbol"]]
    async with busy(ctx.bot, msg.chat_id, "🔎 Juftlikni tekshiryapman…"):
        sym, market = await resolve_symbol(cands)
    if not sym:
        shown = html.escape(", ".join(cands[:3]))
        await msg.reply_text(
            f"❌ <code>{shown}</code> topilmadi (kripto, forex yoki aksiya).\n"
            "Nomni tekshiring — masalan <code>BTCUSDT</code>, <code>btc</code>, "
            "<code>EURUSD</code>, <code>TSLA</code>.",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB,
        )
        return
    draft["symbol"] = sym
    draft["market"] = market
    draft.setdefault("entry_mode", "limit")

    # TP/SL hali kiritilmagan (limit-keyin-so'ralsin oqimi) — `validate()`
    # ularni MAJBURIY deb kutadi (solishtiruv None bilan xato beradi),
    # bu yerda hali tekshirishning o'zi ma'nosiz: TP/SL foydalanuvchi
    # limit to'lgach kiritganida (`handle_tpsl_input()`) tekshiriladi.
    if draft.get("sl") is not None:
        err = parsing.validate(draft)
        if err:
            await msg.reply_text(f"❌ {err}", parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
            return

    warn = []
    # SPOT cheklovi faqat KRIPTOGA tegishli: forex va aksiyalarda short
    # oddiy hol (CFD/margin), shuning uchun ogohlantirish ko'rsatilmaydi.
    if draft["side"] == "SHORT" and not config.ALLOW_SHORT and market == "crypto":
        warn.append("⚠️ SPOT rejimida SHORT savdo qilinmaydi — statistikaga kirmaydi.")
    if draft.get("entry_mode") == "market":
        warn.append("🎯 Oddiy rejim — tasdiqlansa signal darhol \"ochiq\" deb belgilanadi.")
    if draft.get("entry_mode") == "limit" and draft.get("sl") is None:
        warn.append("📐 Limit to'lganda TP/SL kiritishingiz so'raladi.")
    if source == "vision":
        conf = draft.get("confidence", 0)
        warn.append(f"🤖 Rasmdan o'qildi (ishonch {conf:.0%}) — darajalarni tekshiring.")
        if draft.get("reasoning"):
            warn.append(f"<i>{draft['reasoning']}</i>")

    price = await safe_last_price(market, sym)
    if price:
        d = (price - draft["entry"]) / draft["entry"] * 100
        warn.append(f"Joriy narx: <b>{fmt_price(price)}</b> (entrydan {d:+.2f}%)")

    token = token or secrets.token_urlsafe(8)
    # Tasdiqlanmagan qoralamalar cheksiz to'planmasin: tasdiqlamay tashlab
    # ketilgan yozuv PENDING'da abadiy qolardi. Eng eskisini chiqarib
    # yuboramiz (dict Python'da qo'shilish tartibini saqlaydi).
    while len(PENDING) >= MAX_PENDING:
        PENDING.pop(next(iter(PENDING)), None)
    PENDING[token] = {"draft": draft, "file_id": file_id, "user": msg.from_user.id,
                       "workspace_id": workspace_id, "warn": warn,
                       "chart_tf": None, "ready_file_id": None, "want_bot_chart": False}

    body = draft_text(draft)
    if warn:
        body += "\n\n" + "\n".join(warn)
    body += "\n\n<b>Rasm qanday bo'lsin?</b>"

    await msg.reply_text(body, parse_mode=ParseMode.HTML,
                          reply_markup=preview_kb(token, file_id))


def preview_kb(token: str, file_id) -> InlineKeyboardMarkup:
    """Uchta tanlov. Rasm HECH QACHON majburiy emas — uchinchi tugma har doim bor.

    "📈 Bot grafikni aniqlasin" TP/SL hali kiritilmagan (limit-keyin-
    so'ralsin oqimi) qoralamalarda ham ishlaydi — `chart._render()` endi
    `sl=None`/`tps=[]` bilan xavfsiz (faqat entry chizig'i bilan, stop/
    maqsad chiziqlarisiz chiziladi)."""
    first = ("🖼 Yuborgan rasmim bilan" if file_id else "🖼 Rasm yuklash")
    rows = [
        [InlineKeyboardButton(first, callback_data=f"pic:{token}")],
        [InlineKeyboardButton("📈 Bot grafikni aniqlasin", callback_data=f"okc:{token}")],
        [InlineKeyboardButton("📝 Rasmsiz davom etish", callback_data=f"nopic:{token}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"ed:{token}"),
         InlineKeyboardButton("🗑 Bekor", callback_data=f"no:{token}")],
    ]
    return InlineKeyboardMarkup(rows)


async def send_final_preview(target, ctx, token: str) -> None:
    """Yakuniy tekshiruv: signal guruhga QANDAY chiqishini AYNAN shu ko'rinishda
    avval foydalanuvchining o'ziga yuboradi. Tasdiqlansagina guruhga ketadi.

    Rasm Telegram'ga shu yerda bir marta yuklanadi va qaytgan file_id saqlanadi —
    guruhga o'sha file_id yuboriladi. Ya'ni guruh AYNAN ko'rilgan rasmni oladi
    va fayl ikki marta yuklanmaydi."""
    item = PENDING.get(token)
    if not item:
        return
    d = item["draft"]
    caption = draft_text(d)
    if item["warn"]:
        caption += "\n\n" + "\n".join(item["warn"])
    caption += "\n\n✅ Tasdiqlasangiz guruhga shu ko'rinishda yuboriladi."
    # Telegram rasm sarlavhasi 1024 belgi bilan cheklangan. Uzun bo'lsa
    # send_photo YIQILADI va rasm butunlay yo'qolardi (bot grafigi ham) —
    # shuning uchun oldindan qisqartiramiz.
    if len(caption) > 1024:
        caption = caption[:1000].rsplit("\n", 1)[0] + "\n…"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Tasdiqlash va yuborish", callback_data=f"go:{token}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"ed:{token}"),
         InlineKeyboardButton("🗑 Bekor", callback_data=f"no:{token}")],
    ])

    photo = item.get("gen") or item.get("file_id")
    if photo is None:
        await target.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        return
    try:
        if item.get("gen"):
            sent = await target.reply_photo(
                InputFile(io.BytesIO(item["gen"]), "signal.png"), caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            sent = await target.reply_photo(
                item["file_id"], caption=caption, parse_mode=ParseMode.HTML,
                reply_markup=kb)
        item["ready_file_id"] = sent.photo[-1].file_id
        # Baytlar endi kerak emas — Telegram'da file_id bor. Qoralama tasdiqsiz
        # tashlab ketilsa ham yuzlab kilobayt osilib qolmaydi.
        item["gen"] = None
    except Exception:
        log.exception("Ko'rish uchun rasm yuborilmadi")
        await target.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)


# Tanlov uchun timeframe'lar. chart.TF_MINUTES dagilarning ichidan eng ko'p
# ishlatiladiganlari — ro'yxat uzun bo'lsa tugmalar o'qilmay qoladi.
TF_CHOICES = ["1m", "5m", "15m", "1h", "4h", "1d"]


def tf_kb(token: str) -> InlineKeyboardMarkup:
    rows, cur = [], []
    for tf in TF_CHOICES:
        cur.append(InlineKeyboardButton(tf, callback_data=f"tf:{token}:{tf}"))
        if len(cur) == 3:
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    rows.append([InlineKeyboardButton("↩️ Orqaga", callback_data=f"bk:{token}")])
    return InlineKeyboardMarkup(rows)


@asynccontextmanager
async def busy(bot, chat_id: int, note: str | None = None, after: float = 1.2):
    """Uzoq ish paytida foydalanuvchi bot qotib qolgan deb o'ylamasin.

    Ikki bosqichli, ataylab:
      1. DARHOL "yozmoqda…" belgisi chiqadi (Telegram uni ~5 soniya ushlaydi,
         shuning uchun har 4 soniyada yangilanadi). Ish tez tugasa chatda
         hech qanday ortiqcha xabar qolmaydi.
      2. Ish `after` soniyadan cho'zilsa — matnli xabar ham yuboriladi
         ("⏳ ..."), va ish tugagach O'CHIRILADI. Shu sabab tez javoblarda
         chat toza qoladi, sekinlarida esa nima bo'layotgani ko'rinadi.

    Xabar yuborish yoki o'chirish yiqilsa jimgina o'tkazib yuboriladi: bu
    faqat ko'rsatkich, asosiy ishga xalaqit bermasligi kerak."""
    holder: dict = {}

    async def ticker():
        # Sikl QISQA qadam bilan aylanadi, lekin tarmoqqa kamdan-kam chiqadi:
        # "yozmoqda" belgisi 4 soniyada bir marta yangilanadi, kutish xabari
        # esa aynan `after` soniyada yuboriladi. Avval qadam ham 4 soniya edi
        # va, masalan, 2.5 soniyalik ishda xabar umuman chiqmasdi.
        started = time.monotonic()
        next_action = 0.0
        try:
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= next_action:
                    try:
                        await bot.send_chat_action(chat_id, ChatAction.TYPING)
                    except Exception:
                        pass
                    next_action = elapsed + 4
                if note and "msg" not in holder and elapsed >= after:
                    try:
                        holder["msg"] = await bot.send_message(chat_id, note)
                    except Exception:
                        holder["msg"] = None
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(ticker())
    try:
        yield
    finally:
        task.cancel()
        msg = holder.get("msg")
        if msg is not None:
            try:
                await msg.delete()
            except Exception:
                pass


async def _clear_kb(q) -> None:
    """Tugmalarni olib tashlaydi. Telefonda tugma ikki marta bosilishi juda
    tez-tez uchraydi: ikkinchi bosishda Telegram "message is not modified"
    xatosini beradi va foydalanuvchi bekorga qo'rqinchli xato xabarini
    ko'rardi. Bu yerda u jimgina yutiladi."""
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def _edit(q, text: str, reply_markup=None, parse_mode=None) -> None:
    """Tugma bosilgan xabarni tahrirlaydi.

    Signal ko'rigi RASM bo'lib yuboriladi (send_final_preview) — rasmli
    xabarda `edit_message_text` Telegram tomonidan RAD ETILADI ("there is no
    text in the message to edit") va foydalanuvchi "Ishlov berishda xato"
    ko'radi. Aynan shu sabab "Tahrirlash" va "Bekor qilish" tugmalari
    ishlamay qolgandi. Rasm bo'lsa izoh (caption) tahrirlanadi, matn bo'lsa —
    matn. Ikkalasi ham bo'lmasa, oxirgi chora sifatida yangi xabar yoziladi."""
    try:
        if q.message is not None and q.message.photo:
            await q.edit_message_caption(caption=text, reply_markup=reply_markup,
                                          parse_mode=parse_mode)
        else:
            await q.edit_message_text(text, reply_markup=reply_markup,
                                       parse_mode=parse_mode)
    except BadRequest:
        log.warning("Xabarni tahrirlab bo'lmadi, yangisini yozamiz", exc_info=True)
        if q.message is not None:
            await q.message.reply_text(text, reply_markup=reply_markup,
                                        parse_mode=parse_mode)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    action, _, rest = q.data.partition(":")
    # "tf:<token>:<15m>" — timeframe tanlangan holat, qolganlarida faqat token.
    chart_tf = None
    if action == "tf":
        token, _, chart_tf = rest.partition(":")
    else:
        token = rest
    item = PENDING.get(token)
    if not item:
        await _edit(q, "Bu so'rov eskirgan.", reply_markup=MENU_BACK_KB)
        return
    if q.from_user.id != item["user"]:
        return

    if action == "no":
        PENDING.pop(token, None)
        await _edit(q, "🗑 Bekor qilindi.", reply_markup=MENU_BACK_KB)
        return

    if action == "okc":
        # Grafik qaysi masshtabda chizilishini so'raymiz. Tanlangan timeframe
        # signalga saqlanadi va YOPILGANDAGI natija grafigi ham aynan shunda
        # chiziladi — signal qaysi masshtabda rejalashtirilgan bo'lsa, natija
        # ham shunda ko'rinsin.
        item["want_bot_chart"] = True
        await q.edit_message_reply_markup(reply_markup=tf_kb(token))
        return

    if action == "bk":
        await q.edit_message_reply_markup(
            reply_markup=preview_kb(token, item["file_id"]))
        return

    if action == "pic":
        # Rasm allaqachon biriktirilgan bo'lsa qayta so'ramaymiz — LEKIN
        # taym freym baribir so'raladi: signal YOPILGANDA natija grafigi
        # (chart.signal_chart()) doim BOT tomonidan avtomatik chiziladi,
        # foydalanuvchi ochilishda o'z rasmini tanlagan bo'lsa ham. Bu
        # taym freym so'ralmasa `chart_tf` NULL qolib, yopilish grafigi
        # standart 15m'da chiqib, tez/keskin savdolarda (masalan portlash-
        # qulash) chalkash ko'rinishi mumkin edi (foydalanuvchi ARIAUSDT
        # misolida ko'rsatdi).
        if item["file_id"]:
            item["want_bot_chart"] = False
            await _edit(q, "📈 Yopilgandagi natija grafigi qaysi taym freymda chizilsin?",
                       reply_markup=tf_kb(token))
        else:
            AWAITING_SIGNAL_PHOTO[q.from_user.id] = token
            await _clear_kb(q)
            await q.message.reply_text(
                "🖼 Grafik rasmni yuboring.\n"
                "Fikringizdan qaytsangiz /bekor yozing.")
        return

    if action == "nopic":
        # "pic" (yuqorida) bilan bir xil sabab — yopilish grafigi baribir
        # avtomatik chiziladi, shuning uchun taym freym baribir kerak.
        item["gen"] = None
        item["want_bot_chart"] = False
        await _edit(q, "📈 Yopilgandagi natija grafigi qaysi taym freymda chizilsin?",
                   reply_markup=tf_kb(token))
        return

    if action == "tf":
        item["chart_tf"] = chart_tf
        await _clear_kb(q)
        # `want_bot_chart` — faqat "📈 Bot grafikni aniqlasin" yo'lida True:
        # o'sha holatda OCHILISH posti uchun ham bot grafigi chiziladi.
        # "pic"/"nopic"/rasm-yuklash yo'llarida foydalanuvchi ochilishda
        # o'z rasmini yoki rasmsiz variantni tanlagan — bu yerda faqat
        # `chart_tf` saqlanadi (YOPILGANDAGI natija grafigi uchun kerak,
        # u har doim avtomatik chiziladi), OCHILISH posti uchun qayta
        # bot grafigi CHIZILMAYDI.
        if item.get("want_bot_chart"):
            note = await q.message.reply_text(f"📈 {chart_tf} grafigi chizilmoqda…")
            ws_row = await db.get_workspace(item["workspace_id"])
            try:
                buf = await chart.setup_chart(item["draft"], ws_row["name"] if ws_row else "",
                                               ctx.bot.username, tf=chart_tf)
            except Exception:
                log.warning("Signal grafigi yasalmadi", exc_info=True)
                buf = None
            item["gen"] = buf.getvalue() if buf else None
            try:
                await note.delete()
            except Exception:
                pass
            if not item["gen"]:
                await q.message.reply_text(
                    "⚠️ Grafik chizilmadi (birja javob bermadi). "
                    "Signal rasmsiz yuboriladi.")
        await send_final_preview(q.message, ctx, token)
        return

    if action == "ed":
        AWAITING_EDIT[q.from_user.id] = token
        await _edit(
            q,
            "✏️ To'g'ri darajalarni yuboring:\n"
            "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>",
            parse_mode=ParseMode.HTML,
        )
        # Eski ko'rikning tugmalari olib tashlanadi: tahrirdan keyin YANGI
        # ko'rik yuboriladi, eskisidan "Tasdiqlash" bosilsa foydalanuvchi
        # ekranda ko'rib turgan narsa bilan yuboriladigan signal mos
        # kelmasligi mumkin edi.
        await _clear_kb(q)
        return

    # --- tasdiqlash ---
    ws = await db.get_workspace(item["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        await _edit(q, "Ruxsat yo'q.")
        return

    d = item["draft"]
    entry_mode = d.get("entry_mode", "limit")

    if entry_mode == "market":
        # Entry sehrgarda ANCHA OLDIN (yo'nalish tanlangandan keyin) yoki
        # matn kiritilganda ushlangan bo'lishi mumkin — keyin TP/SL
        # kiritish, ko'rib chiqish, tasdiqlash bosqichlari VAQT OLADI. Shu
        # oraliqda (ayniqsa uchuvchan kichik tangalarda) haqiqiy narx
        # sezilarli o'zgarib ketishi mumkin — natijada TP "hali limitga
        # kelmasdan" darrov "tegib qolgandek" ko'rinardi, aslida saqlangan
        # entry ESKIRGAN edi. Shu sabab TASDIQLASH lahzasida (signal DB'ga
        # yozilishidan OLDIN) narx QAYTA, eng so'nggi (keshsiz) holda
        # olinadi — kechikish endi faqat tarmoq javobi bilan chegaralanadi.
        fresh_price = await safe_last_price(d.get("market", "crypto"), d["symbol"], fresh=True)
        if fresh_price:
            refreshed = dict(d, entry=fresh_price)
            err = parsing.validate(refreshed)
            if err:
                # Narx shu qadar siljiganki, avval tanlangan TP/SL endi
                # mantiqsiz (masalan TP allaqachon o'tib ketgan) — signalni
                # SHUNDAY yaratish o'rniga (darrov "yopilgan" holatda
                # tug'iladi) to'xtatib, foydalanuvchiga aniq xabar beramiz.
                await _edit(
                    q, f"❌ Narx yangilandi (<b>{fmt_price(fresh_price)}</b>), lekin endi "
                    f"darajalar mantiqan to'g'ri kelmaydi: {err}\n"
                    "✏️ Tahrirlash orqali qayta kiriting.",
                    parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
                return
            d = refreshed
            item["draft"] = d
        # Narx olinmasa (tarmoq xatosi) — xavfsiz DAVOM ETAMIZ, eski (ko'rib
        # chiqilgan) narx bilan — signal umuman yaratilmay qolishidan yaxshi.

    # Guruhga yuboriladigan rasm — foydalanuvchi KO'RGANINING AYNI o'zi.
    # send_final_preview() uni Telegram'ga yuklab, file_id'ni saqlab qo'ygan.
    post_file_id = item.get("ready_file_id") or item.get("file_id")
    sig_id = await db.create_signal(ws["id"], {
        "symbol": d["symbol"], "side": d["side"], "entry": d["entry"],
        "sl": d["sl"], "tps": d["tps"], "chart_file_id": post_file_id,
        "author_id": q.from_user.id, "note": d.get("reasoning"),
        "market": d.get("market", "crypto"), "entry_mode": entry_mode,
        "chart_tf": item.get("chart_tf"),
    })
    PENDING.pop(token, None)
    await _clear_kb(q)
    await q.message.reply_text(f"✅ Signal <code>#{sig_id}</code> qabul qilindi.",
                                parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)

    group_msg_id = None
    if ws["type"] == "group" and ws["group_chat_id"]:
        body = draft_text(d, sig_id)
        try:
            if post_file_id:
                sent = await ctx.bot.send_photo(
                    ws["group_chat_id"], post_file_id, caption=body,
                    parse_mode=ParseMode.HTML, message_thread_id=ws["group_topic_id"])
            else:
                sent = await ctx.bot.send_message(
                    ws["group_chat_id"], body, parse_mode=ParseMode.HTML,
                    message_thread_id=ws["group_topic_id"])
            group_msg_id = sent.message_id
            await db.set_group_msg(sig_id, group_msg_id)
        except Exception:
            log.exception("Guruhga yuborib bo'lmadi")

    elif ws["type"] == "personal":
        # Shaxsiy jurnalda signal kartasi AVVAL umuman yuborilmasdi — faqat
        # "qabul qilindi" tasdig'i chiqardi. Natijada keyingi xabarlar (TP,
        # stop, ±5%) javob beradigan asosiy xabar ham bo'lmasdi. Endi karta
        # egasining shaxsiy chatiga yuboriladi va uning id'si saqlanadi —
        # guruhdagi bilan bir xil tartib.
        body = draft_text(d, sig_id)
        try:
            if post_file_id:
                sent = await ctx.bot.send_photo(ws["owner_id"], post_file_id,
                                                 caption=body, parse_mode=ParseMode.HTML)
            else:
                sent = await ctx.bot.send_message(ws["owner_id"], body,
                                                   parse_mode=ParseMode.HTML)
            group_msg_id = sent.message_id
            await db.set_group_msg(sig_id, group_msg_id)
        except Exception:
            log.exception("Shaxsiy jurnalga yuborib bo'lmadi")

    if entry_mode == "market":
        chat_id = (ws["group_chat_id"] if ws["type"] == "group" else ws["owner_id"])
        try:
            await ctx.bot.send_message(
                chat_id,
                f"▶️ <b>#{sig_id} {d['symbol']}</b> — pozitsiya ochildi @ <b>{fmt_price(d['entry'])}</b>",
                parse_mode=ParseMode.HTML, reply_to_message_id=group_msg_id,
                allow_sending_without_reply=True,
                message_thread_id=ws["group_topic_id"] if ws["type"] == "group" else None)
        except Exception:
            log.exception("Ochilish xabari yuborilmadi")

    if ws["deposit"] is not None:
        AWAITING_ALLOC[q.from_user.id] = sig_id
        text, kb2 = alloc_prompt(sig_id, d, float(ws["deposit"]))
        await q.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb2)


# ─────────────── Risk kalkulyatori ───────────────
RISK_CHOICES = (1, 2, 3)


def risk_amount(deposit: float, entry: float, sl: float, risk_pct: float) -> float | None:
    """Depozitning `risk_pct` foizini yo'qotish uchun kerak bo'ladigan hajm.

    Stopgacha masofa: d = |entry - sl| / entry. Stop tegsa pozitsiyaning aynan
    shu ulushi yo'qoladi, ya'ni kerakli hajm = (depozit * risk%) / d.

    SPOT uchun hajm depozitdan oshmaydi (leverage yo'q) — juda tor stopda
    formula depozitdan katta son berardi, shuning uchun cheklanadi."""
    if entry <= 0:
        return None
    d = abs(entry - sl) / entry
    if d <= 0:
        return None
    return min(deposit * (risk_pct / 100) / d, deposit)


def alloc_prompt(sig_id: int, d: dict, deposit: float) -> tuple[str, InlineKeyboardMarkup]:
    """Pozitsiya hajmini so'rash — risk bo'yicha tayyor variantlar bilan.
    Avval faqat "necha pul ishlatasiz?" deb so'rardi va hisobni odam o'zi
    qilishi kerak edi.

    `d["sl"]` NULL bo'lishi mumkin (limit-keyin-TP/SL oqimi — stop hali
    kiritilmagan) — bunday holda risk% ga asoslangan tugmalar hisoblab
    bo'lmaydi (stopgacha masofa hali noma'lum), shuning uchun faqat
    "summani o'zingiz yozing" varianti ko'rsatiladi."""
    entry = float(d["entry"])
    sl = float(d["sl"]) if d.get("sl") is not None else None
    dist = abs(entry - sl) / entry * 100 if (sl is not None and entry > 0) else 0

    t = [f"💰 <b>#{sig_id} {html.escape(str(d['symbol']))}</b> — pozitsiya hajmi",
         f"Depozit: <b>{deposit:,.2f}</b>" + (f" · Stopgacha: <b>{dist:.2f}%</b>" if sl is not None else "")]
    rows, capped = [], False
    if sl is not None and dist > 0:
        btns = []
        for rp in RISK_CHOICES:
            amt = risk_amount(deposit, entry, sl, rp)
            if amt is None:
                continue
            if amt >= deposit - 1e-9:
                capped = True
            btns.append(InlineKeyboardButton(
                f"{rp}% → {amt:,.0f}", callback_data=f"alloc:{sig_id}:{amt:.2f}"))
        if btns:
            t += ["", "Xavf darajasini tanlang — hajm o'zi hisoblanadi:"]
            rows.append(btns)
    if capped:
        t.append("<i>Hajm depozitdan oshmaydi (spot, leverage yo'q) — cheklandi.</i>")
    t += ["", "Yoki summani o'zingiz yozing (masalan <code>100</code>)."]
    rows.append([InlineKeyboardButton("⏭ O'tkazib yuborish",
                                       callback_data=f"allocskip:{sig_id}")])
    return "\n".join(t), InlineKeyboardMarkup(rows)


async def on_alloc_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Risk tugmasi bosildi — hajm allaqachon hisoblangan, shuni saqlaymiz."""
    q = update.callback_query
    await q.answer()
    _, sid_s, amt_s = q.data.split(":", 2)
    sig_id, amount = int(sid_s), float(amt_s)
    sig = await db.get_signal(sig_id)
    ws = await db.get_workspace(sig["workspace_id"]) if sig else None
    if not sig or not ws or not can_manage(q.from_user.id, ws):
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return
    if ws["deposit"] is None:
        await q.answer("Depozit belgilanmagan.", show_alert=True)
        return
    AWAITING_ALLOC.pop(q.from_user.id, None)
    dep = float(ws["deposit"])
    await db.set_signal_allocation(sig_id, amount, dep)
    entry, sl = float(sig["entry"]), float(sig["sl_initial"])
    risk_money = amount * abs(entry - sl) / entry
    await q.edit_message_text(
        f"✅ #{sig_id} {html.escape(sig['symbol'])} — hajm: <b>{amount:,.2f}</b>\n"
        f"Stop tegsa yo'qotish: <b>{risk_money:,.2f}</b> "
        f"(depozitning {risk_money / dep * 100:.2f}%)",
        parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)


async def on_alloc_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    AWAITING_ALLOC.pop(q.from_user.id, None)
    await q.edit_message_text("⏭ O'tkazib yuborildi.", reply_markup=MENU_BACK_KB)


# ─────────────────────────── Kuzatuv sikli ───────────────────────────

EVENT_TEXT = {
    "OPEN": "▶️ <b>#{sid} {sym}</b> — pozitsiya ochildi @ <b>{p}</b>",
    "TP": "✅ <b>#{sid} {sym}</b> — TP{n} bajarildi @ <b>{p}</b>  ({share:.0%} sotildi)\nJoriy natija: <b>{run:+.2f}%</b>",
    "BE": "🛡 <b>#{sid} {sym}</b> — stop breakeven'ga ko'chirildi",
    "EXPIRED": "⌛️ <b>#{sid} {sym}</b> — entryga tegmadi, bekor qilindi",
}


async def poll_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        events = await tracker.run_once()
    except Exception:
        log.exception("Kuzatuv siklida xato")
        return

    ws_cache: dict[int, object] = {}

    async def get_ws(wid: int):
        if wid not in ws_cache:
            ws_cache[wid] = await db.get_workspace(wid)
        return ws_cache[wid]

    for e in events:
        sid, sym = e["signal_id"], e["symbol"]
        ws = await get_ws(e["workspace_id"])

        if e["type"] == "STOP":
            pnl = e["final_pnl"] or 0
            if e["was_be"]:
                txt = f"🛡 <b>#{sid} {sym}</b> — breakeven'da yopildi ({pnl:+.2f}%)"
            elif pnl >= 0:
                txt = f"✅ <b>#{sid} {sym}</b> — stopda yopildi\nYakuniy: <b>{pnl:+.2f}%</b> ({e['r']:+.2f}R)"
            else:
                txt = f"❌ <b>#{sid} {sym}</b> — stop loss @ <b>{fmt_price(e['price'])}</b>\nYakuniy: <b>{pnl:+.2f}%</b> ({e['r']:+.2f}R)"
        elif e["type"] == "TP":
            txt = EVENT_TEXT["TP"].format(
                sid=sid, sym=sym, n=e["n"], p=fmt_price(e["price"]),
                share=e["share"], run=e["running"])
            if e.get("closes") and e.get("final_pnl") is not None:
                txt += f"\n🏁 Signal yopildi: <b>{e['final_pnl']:+.2f}%</b> ({e['r']:+.2f}R)"
        elif e["type"] == "OPEN":
            txt = EVENT_TEXT["OPEN"].format(sid=sid, sym=sym, p=fmt_price(e["price"]))
        else:
            txt = EVENT_TEXT.get(e["type"], "").format(sid=sid, sym=sym)
        if not txt:
            continue

        if not ws:
            continue

        sig = await db.get_signal(sid)

        closed_pnl = None
        if e["type"] == "STOP":
            closed_pnl = e.get("final_pnl")
        elif e["type"] == "TP" and e.get("closes"):
            closed_pnl = e.get("final_pnl")
        if closed_pnl is not None and sig and sig["alloc_amount"] is not None:
            money_delta = float(closed_pnl) / 100 * float(sig["alloc_amount"])
            await db.apply_deposit_delta(ws["id"], money_delta)

        # Signal shu hodisada yopilgan bo'lsa (STOP yoki yakuniy TP) — matn bilan
        # birga real narx grafigi (entry/TP/SL chiziqlari + chiqish nuqtasi)
        # yuboriladi. Grafik ishlab chiqarilmasa (birja javob bermasa va h.k.)
        # jim tarzda oddiy matn xabariga qaytiladi — hech narsa buzilmaydi.
        photo = None
        if closed_pnl is not None and sig:
            try:
                photo = await chart.signal_chart(sig, ws["name"], ctx.bot.username)
            except Exception:
                log.warning("Grafik yasalmadi (#%s)", sid, exc_info=True)

        if ws["type"] == "group" and ws["group_chat_id"]:
            reply_to = sig["group_msg_id"] if sig else None
            try:
                if photo:
                    await ctx.bot.send_photo(
                        ws["group_chat_id"], InputFile(photo, "signal.png"), caption=txt,
                        parse_mode=ParseMode.HTML, reply_to_message_id=reply_to,
                        allow_sending_without_reply=True, message_thread_id=ws["group_topic_id"])
                else:
                    await ctx.bot.send_message(
                        ws["group_chat_id"], txt, parse_mode=ParseMode.HTML,
                        reply_to_message_id=reply_to, allow_sending_without_reply=True,
                        message_thread_id=ws["group_topic_id"])
            except Exception:
                log.exception("Xabar yuborilmadi")
        elif ws["type"] == "personal":
            # Guruhdagi kabi — natija signal kartasiga javob bo'lib keladi,
            # shunda qaysi signal haqida ekani darrov ko'rinadi.
            reply_to = sig["group_msg_id"] if sig else None
            try:
                if photo:
                    await ctx.bot.send_photo(ws["owner_id"], InputFile(photo, "signal.png"),
                                              caption=txt, parse_mode=ParseMode.HTML,
                                              reply_to_message_id=reply_to,
                                              allow_sending_without_reply=True)
                else:
                    await ctx.bot.send_message(ws["owner_id"], txt, parse_mode=ParseMode.HTML,
                                                reply_to_message_id=reply_to,
                                                allow_sending_without_reply=True)
            except Exception:
                log.exception("Shaxsiy xabar yuborilmadi")

        if sig and sig["ambiguous"] and e["type"] == "STOP":
            try:
                await ctx.bot.send_message(
                    ws["owner_id"],
                    f"⚠️ #{sid} — TP va SL bitta 1m shamda tegdi. "
                    f"Konservativ hisob ishlatildi (SL). Qo'lda tekshiring.",
                )
            except Exception:
                pass

        # Limit to'ldi, lekin TP/SL HALI kiritilmagan (foydalanuvchi "avval
        # faqat limit, TP/SL keyin" so'ragan oqim) — signal yaratgan odamga
        # DM orqali so'rov yuboriladi (signal boshqaruvi shu botda doim
        # shaxsiy chatda, guruhda emas). AWAITING_TPSL shu odamga o'rnatiladi
        # — u DIREKT javob yozishi mumkin, yoki keyinroq tugmani bossa ham
        # bo'ladi (agar bu xabarni o'tkazib yuborgan/kechiktirgan bo'lsa).
        if e["type"] == "OPEN" and e.get("needs_tpsl") and sig and sig["author_id"]:
            author_id = sig["author_id"]
            AWAITING_TPSL[author_id] = sid
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                "📐 TP/SL kiriting", callback_data=f"tpsl:{sid}")]])
            try:
                await ctx.bot.send_message(author_id, _tpsl_prompt(sid, sym),
                                            parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                log.exception("TP/SL so'rovi yuborilmadi (#%s)", sid)


# ─────────────── Avtomatik kunlik hisobot ───────────────

async def build_digest(ws) -> str | None:
    """Bugun YOPILGAN signallar bo'yicha qisqa yakun. Yopilgani bo'lmasa None —
    guruhga bo'sh post ketmasin (bu spam bo'lib qolardi)."""
    now = datetime.now(stats.TZ)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = await db.equity_series(ws["id"], since, None)
    if not rows:
        return None

    deposit = ws["deposit"]
    pnls = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
    if not pnls:
        return None
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    be = len(pnls) - wins - losses

    # /stats bilan AYNI hisob: depozit belgilangan bo'lsa har savdo o'z
    # pozitsiya hajmiga qarab tortiladi, aks holda sof foizlar yig'indisi.
    weighted = None
    if deposit:
        weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                    for r in rows
                    if r["pnl_pct"] is not None and r["alloc_amount"] is not None]
    total = sum(weighted) if weighted else sum(pnls)
    label = "depozitga nisbatan" if weighted else "yig'indi"

    icon = "🟢" if total > 0 else ("🔴" if total < 0 else "⚪")
    wr = wins / len(pnls) * 100
    t = [f"📊 <b>Kun yakuni — {now:%d.%m.%Y}</b>", "",
         f"Yopilgan signallar: <b>{len(pnls)}</b>  ({wins}✅ / {losses}❌"
         + (f" / {be}⚪" if be else "") + ")",
         f"Winrate: <b>{wr:.0f}%</b>",
         f"{icon} Natija ({label}): <b>{total:+.2f}%</b>"]

    syms = await db.top_symbols(ws["id"], since, None)
    if syms:
        best = syms[0]
        if float(best["sum_pct"]) > 0:
            t.append(f"Eng yaxshi: <b>{html.escape(best['symbol'])}</b> "
                     f"{float(best['sum_pct']):+.2f}%")
        worst = syms[-1]
        if float(worst["sum_pct"]) < 0 and worst["symbol"] != best["symbol"]:
            t.append(f"Eng yomon: <b>{html.escape(worst['symbol'])}</b> "
                     f"{float(worst['sum_pct']):+.2f}%")

    live = await db.live_signals(ws["id"])
    if live:
        act = sum(1 for s in live if s["status"] == "ACTIVE")
        pend = len(live) - act
        parts = ([f"{act} ta ochiq"] if act else []) + \
                ([f"{pend} ta kutilmoqda"] if pend else [])
        t += ["", "⏳ " + ", ".join(parts)]
    return "\n".join(t)


async def digest_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Har 15 daqiqada aylanadi va belgilangan soat kelgan guruhlarga kun
    yakunini yuboradi. `digest_last` kuniga bir marta yuborilishini
    kafolatlaydi — bot qayta ishga tushsa ham takrorlanmaydi."""
    try:
        rows = await db.digest_workspaces()
    except Exception:
        log.exception("Kunlik hisobot: bazadan o'qishda xato")
        return
    now = datetime.now(stats.TZ)
    today = now.date()
    for ws in rows:
        if ws["digest_hour"] != now.hour or ws["digest_last"] == today:
            continue
        # Kunni AVVAL belgilaymiz: matn tayyorlash yoki yuborish yiqilsa ham
        # keyingi aylanishda qayta urinib guruhni bezovta qilmasin.
        await db.mark_digest_sent(ws["id"], today)
        try:
            text = await build_digest(ws)
            if not text:
                continue
            await ctx.bot.send_message(
                ws["group_chat_id"] if ws["type"] == "group" else ws["owner_id"],
                text, parse_mode=ParseMode.HTML,
                message_thread_id=ws["group_topic_id"] if ws["type"] == "group" else None)
        except Exception:
            log.exception("Kunlik hisobot yuborilmadi (ws=%s)", ws["id"])


async def cmd_digest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/hisobot 21 — har kuni 21:00 da guruhga kun yakuni. /hisobot off — o'chirish."""
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not can_manage(update.effective_user.id, ws):
        await update.message.reply_text("Bu sozlamani faqat egasi o'zgartira oladi.")
        return

    if not ctx.args:
        cur = ws["digest_hour"]
        state = f"yoqilgan, har kuni <b>{cur:02d}:00</b>" if cur is not None else "o'chirilgan"
        await update.message.reply_text(
            f"📊 Kunlik hisobot: {state}\n\n"
            "Yoqish: <code>/hisobot 21</code> (mahalliy vaqt, 0–23)\n"
            "O'chirish: <code>/hisobot off</code>\n\n"
            f"Belgilangan soatda {'guruhga' if ws['type'] == 'group' else 'shu yerga'} "
            "kun yakuni chiqadi: nechta signal yopildi, winrate, umumiy natija, "
            "eng yaxshi juftlik.",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    arg = ctx.args[0].lower()
    if arg in ("off", "o'chir", "ochir"):
        await db.set_digest_hour(ws["id"], None)
        await update.message.reply_text("📊 Kunlik hisobot o'chirildi.",
                                         reply_markup=MENU_BACK_KB)
        return
    try:
        hour = int(arg)
    except ValueError:
        hour = -1
    if not 0 <= hour <= 23:
        await update.message.reply_text("Soat 0 dan 23 gacha bo'lishi kerak. "
                                         "Masalan: /hisobot 21")
        return
    await db.set_digest_hour(ws["id"], hour)
    await update.message.reply_text(
        f"✅ Kunlik hisobot yoqildi — har kuni <b>{hour:02d}:00</b> da "
        f"({config.TZ}) {'guruhga' if ws['type'] == 'group' else 'shu yerga'} chiqadi.\n\n"
        "<i>Bugun yopilgan signal bo'lmasa post yuborilmaydi.</i>",
        parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)


MILESTONE_STEP = 5


def milestone_band(pnl: float) -> int:
    """pnl foizini MILESTONE_STEP'ga karrali bosqichga aylantiradi:
    +12.3% -> 10, -7.1% -> -5. |pnl| < STEP bo'lsa 0."""
    mag = int(abs(pnl) // MILESTONE_STEP) * MILESTONE_STEP
    return mag if pnl >= 0 else -mag


def milestone_should_notify(last: int, band: int) -> bool:
    """Faqat NOLDAN UZOQROQ yangi bosqichga birinchi marta yetganda xabar
    beriladi ("храповик"/ratchet).

    Avval bosqich har o'zgarganda xabar ketardi va narx chegara atrofida
    tebranganda (+5.35% → +4.98% → +5.01%) bir xil bosqich uchun cheksiz
    takroriy xabar yuborilardi — jonli guruhda bu spam bo'lib chiqdi.

    Endi: +5 e'lon qilingach, yana +5 e'lon qilinmaydi; faqat +10 (yoki
    zararga o'tsa -5) yangi xabar beradi. Ishora almashsa hisob qaytadan
    boshlanadi — bu haqiqiy katta o'zgarish (kamida 2 bosqichlik yurish),
    shuning uchun xabar berishga arziydi."""
    if band > 0:
        return band > max(last, 0)
    if band < 0:
        return band < min(last, 0)
    return False  # 0 — bosqich yo'q, xabar ham yo'q


async def milestone_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Ochiq (ACTIVE) pozitsiyalar joriy foizi har ±5% bosqichni bosib
    o'tganda (foydada ham, zararda ham) bildirishnoma yuboradi — pozitsiyani
    kuzatib borishga yordam beradi. TP/SL kuzatuvidan (poll_job) mustaqil —
    faqat joriy narxdan hisoblanadi, signal holatini o'zgartirmaydi."""
    try:
        rows = await db.live_signals()
    except Exception:
        log.exception("Milestone siklida xato (bazadan o'qishda)")
        return

    active = [s for s in rows if s["status"] == "ACTIVE"]
    if not active:
        return

    price_cache: dict[tuple[str, str], float | None] = {}
    ws_cache: dict[int, object] = {}

    async def get_price(market: str, symbol: str):
        key = (market, symbol)
        if key not in price_cache:
            try:
                price_cache[key] = await provider_for(market).last_price(symbol)
            except Exception:
                price_cache[key] = None
        return price_cache[key]

    async def get_ws(wid: int):
        if wid not in ws_cache:
            ws_cache[wid] = await db.get_workspace(wid)
        return ws_cache[wid]

    for s in active:
        price = await get_price(s["market"], s["symbol"])
        if price is None:
            continue
        pnl = tracker.pnl_at(s["side"], float(s["entry"]), price)
        band = milestone_band(pnl)
        if not milestone_should_notify(s["milestone_pct"], band):
            continue
        # Faqat XABAR YUBORILGANDA saqlanadi. Avval bosqich har o'zgarganda
        # (0 ga tushganda ham) yozilardi — aynan shu tebranish spamiga
        # sabab bo'lgan edi.
        await db.set_milestone(s["id"], band)

        ws = await get_ws(s["workspace_id"])
        if not ws:
            continue

        mark = "📈" if band > 0 else "📉"
        txt = (f"{mark} <b>#{s['id']} {s['symbol']}</b> — joriy natija: "
               f"<b>{pnl:+.2f}%</b> ({band:+d}% bosqichi)")

        if ws["type"] == "group" and ws["group_chat_id"]:
            try:
                await ctx.bot.send_message(
                    ws["group_chat_id"], txt, parse_mode=ParseMode.HTML,
                    reply_to_message_id=s["group_msg_id"], allow_sending_without_reply=True,
                    message_thread_id=ws["group_topic_id"])
            except Exception:
                log.exception("Milestone xabari yuborilmadi")
        elif ws["type"] == "personal":
            try:
                await ctx.bot.send_message(ws["owner_id"], txt, parse_mode=ParseMode.HTML,
                                            reply_to_message_id=s["group_msg_id"],
                                            allow_sending_without_reply=True)
            except Exception:
                log.exception("Milestone shaxsiy xabar yuborilmadi")


# ─────────────────────────── Komandalar ───────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if ctx.args and ctx.args[0].startswith("ref_"):
        try:
            referrer_id = int(ctx.args[0][4:])
            if referrer_id != uid:
                await db.add_referral(referrer_id, uid)
        except ValueError:
            pass

    # News Trade AI/surge posti ostidagi "📝 Jurnalga kiritish" tugmasi —
    # tiker allaqachon ma'lum (postdan), shuning uchun bu yerda tikerni
    # QAYTA SO'RAMAYMIZ: darhol tasdiqlab, keyingi xabarda faqat
    # yo'nalish/kirish/TP/SL kutiladi (on_text_signal shu holatni tekshiradi).
    if ctx.args and ctx.args[0].startswith("journal_"):
        raw = ctx.args[0][len("journal_"):]
        sym, market = await resolve_symbol([raw])
        if not sym:
            await update.message.reply_text(
                f"❌ <code>{html.escape(raw)}</code> topilmadi. Signalni qo'lda yozing, masalan:\n<code>BTCUSDT long 65000</code>",
                parse_mode=ParseMode.HTML)
            return
        personal = await db.get_or_create_personal_workspace(uid, "Shaxsiy jurnal")
        AWAITING_JOURNAL_SYMBOL[uid] = (sym, personal["id"])
        await update.message.reply_text(
            f"✅ <b>{html.escape(sym)}</b> — endi yo'nalish va narxlarni yozing "
            "(tiker yozish shart emas), masalan:\n\n"
            "<code>LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
            "Yoki qisqa: <code>long 65000 67000 68500 64000</code>\n\n"
            "Bekor qilish uchun /bekor yozing.",
            parse_mode=ParseMode.HTML)
        return

    # Birinchi marta kelgan odamdan tilni SO'RAYMIZ (uchala tilda yozilgan
    # savol bilan — qaysi tilni tushunishini hali bilmaymiz). Tanlagach
    # `on_lang_set` darhol menyuni ko'rsatadi. Guruhda so'ralmaydi: u
    # yerda til guruh sozlamasi.
    if update.effective_chat.type == "private" and not await has_chosen_lang(uid):
        await update.message.reply_text(
            i18n.t("lang.choose_first"), reply_markup=lang_kb())
        return

    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    lang = await user_lang(uid)
    await update.message.reply_text(
        i18n.t("menu.title", lang, name=ws["name"]),
        reply_markup=main_menu_kb(uid, ws, update.effective_chat.type == "private", lang))


async def cmd_bekor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    AWAITING_EDIT.pop(update.effective_user.id, None)
    AWAITING_ALLOC.pop(update.effective_user.id, None)
    AWAITING_SIGNAL_PHOTO.pop(update.effective_user.id, None)
    AWAITING_SL.pop(update.effective_user.id, None)
    AWAITING_ENTRY.pop(update.effective_user.id, None)
    AWAITING_TPS.pop(update.effective_user.id, None)
    AWAITING_TPSL.pop(update.effective_user.id, None)
    AWAITING_BROADCAST.pop(update.effective_user.id, None)
    PENDING_BROADCAST.pop(update.effective_user.id, None)
    AWAITING_JOURNAL_SYMBOL.pop(update.effective_user.id, None)
    ctx.user_data.pop("wiz", None)
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=MENU_BACK_KB)


FIX_LIMIT = 30


def _fix_row(s) -> str:
    """Tuzatish ro'yxatidagi bitta qator."""
    mark = "🚫" if s["excluded"] else ("⏳" if s["status"] in ("PENDING", "ACTIVE") else "")
    pnl = f"{float(s['pnl_pct']):+.2f}%" if s["pnl_pct"] is not None else s["status"].lower()
    when = f"{s['closed_at'].astimezone(stats.TZ):%d.%m}" if s["closed_at"] else \
           f"{s['created_at'].astimezone(stats.TZ):%d.%m}"
    return f"{mark}#{s['id']} {s['symbol']} {pnl} · {when}"


async def _fix_view(ws, symbol: str | None):
    """Matn + tugmalar. Har bir signal uchun bitta tugma: bosilsa hisobdan
    chiqariladi yoki qaytariladi."""
    rows = await db.admin_list_signals(ws["id"], symbol, FIX_LIMIT)
    if not rows:
        what = f" <code>{html.escape(symbol)}</code> bo'yicha" if symbol else ""
        return f"Signal topilmadi{what}.", MENU_BACK_KB

    n_off = sum(1 for s in rows if s["excluded"])
    head = (f"🛠 <b>Signallarni tuzatish</b> — {html.escape(ws['name'])}\n"
            f"Oxirgi {len(rows)} ta"
            + (f", <code>{html.escape(symbol)}</code>" if symbol else "")
            + (f" · {n_off} tasi hisobdan chiqarilgan" if n_off else "") + "\n\n"
            "Tugmani bosing — signal statistikadan olib tashlanadi. "
            "Qayta bossangiz qaytariladi. Hech narsa o'chirilmaydi.")

    kb = []
    for s in rows:
        icon = "↩️ qaytarish" if s["excluded"] else "🚫 chiqarish"
        kb.append([InlineKeyboardButton(f"{_fix_row(s)}  →  {icon}",
                                         callback_data=f"fix:{s['id']}:{symbol or '-'}")])
    kb.append([InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")])
    return head, InlineKeyboardMarkup(kb)


async def cmd_tuzat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Xato kiritilgan signalni statistikadan olib tashlash (faqat super-admin).

    Raqamlarni QO'LDA tahrirlash ataylab qilinmadi — u statistikani hech kim
    tekshira olmaydigan qo'lyozmaga aylantirardi. Buning o'rniga noto'g'ri
    signalning o'zi hisobdan chiqariladi: qolgan hamma raqam haqiqiy savdo
    ma'lumotidan hisoblanaveradi."""
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    symbol = None
    if ctx.args:
        raw = ctx.args[0]
        found, _ = await resolve_symbol([raw])
        symbol = found or raw.upper()
    text, kb = await _fix_view(ws, symbol)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def on_fix(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await q.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, sid_s, sym = q.data.split(":", 2)
    sig = await db.get_signal(int(sid_s))
    if not sig:
        await q.answer("Topilmadi.", show_alert=True)
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws:
        await q.answer("Workspace topilmadi.", show_alert=True)
        return

    new_state = not sig["excluded"]
    await db.set_signal_excluded(sig["id"], new_state)

    # Depozit ham to'g'rilanadi: yopilganda unga qo'shilgan pul hisobdan
    # chiqarilganda qaytarib olinadi (aks holda depozit jimgina noto'g'ri
    # bo'lib qolardi), qaytarilganda esa yana qo'shiladi.
    if sig["status"] in ("TP", "SL", "BREAKEVEN") and sig["alloc_amount"] is not None \
            and sig["pnl_pct"] is not None:
        money = float(sig["pnl_pct"]) / 100 * float(sig["alloc_amount"])
        await db.apply_deposit_delta(ws["id"], -money if new_state else money)

    await q.answer("Hisobdan chiqarildi." if new_state else "Qaytarildi.")
    text, kb = await _fix_view(ws, None if sym == "-" else sym)
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        pass  # matn o'zgarmasa Telegram xato beradi — muhim emas


async def cmd_qaytar(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Xato sabab (masalan #121'dagi kabi, jonli narxni tekshirmasdan
    qo'lda kiritilgan allaqachon "tegilgan" stop) bir zumda yopilib qolgan
    signalni ACTIVE holatiga qaytaradi (faqat super-admin).
    `tracker.reopen_signal()`ga qarang — raqamlar qo'lda kiritilmaydi,
    hammasi saqlangan tp_hit/tps'dan qat'iy qayta hisoblanadi."""
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /qaytar <signal ID>")
        return
    try:
        sig_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Signal ID raqam bo'lishi kerak.")
        return
    ev = await tracker.reopen_signal(sig_id)
    if not ev:
        await update.message.reply_text(
            f"#{sig_id} topilmadi yoki allaqachon ochiq (faqat YOPILGAN "
            "signalni qaytarish mumkin).")
        return
    # Depozit ham to'g'rilanadi — `cmd_tuzat`dagi bilan bir xil mantiq:
    # yopilganda unga qo'shilgan/ayirilgan pul endi qaytarib olinadi.
    if ev["alloc_amount"] is not None and ev["prev_pnl"] is not None:
        money = ev["prev_pnl"] / 100 * ev["alloc_amount"]
        await db.apply_deposit_delta(ev["workspace_id"], -money)
    await update.message.reply_text(
        f"↩️ <b>#{sig_id} {html.escape(ev['symbol'])}</b> — ACTIVE holatiga "
        "qaytarildi.\nStop xavfsiz boshlang'ich qiymatga tushirildi, TP/SL "
        "kuzatuvi hozirdan davom etadi.", parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    async with busy(ctx.bot, update.effective_chat.id):
        text = await stats_view_text(ws, update.effective_user.id, "all")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=stats_nav_kb("all"))


async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    now = datetime.now(stats.TZ)
    deposit = float(ws["deposit"]) if ws["deposit"] is not None else None
    show_money = can_manage(uid, ws)
    a, b = stats.month_bounds(now.year, now.month)
    cur = await stats.summary(ws["id"], a, b, f"{stats.MONTHS_UZ[now.month - 1]} {now.year}",
                               deposit=deposit, show_money=show_money)
    await update.message.reply_text(
        cur + "\n\n" + await stats.monthly_table(ws["id"]), parse_mode=ParseMode.HTML)


async def cmd_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    y = datetime.now(stats.TZ).year
    deposit = float(ws["deposit"]) if ws["deposit"] is not None else None
    show_money = can_manage(uid, ws)
    a, b = stats.year_bounds(y)
    await update.message.reply_text(
        await stats.summary(ws["id"], a, b, f"{y}-yil natijalari",
                             deposit=deposit, show_money=show_money),
        parse_mode=ParseMode.HTML)


async def cmd_symbols(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    text = await symbols_view_text(ws["id"], None, None)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=symbols_nav_kb(None, None))


async def cmd_equity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    deposit = float(ws["deposit"]) if ws["deposit"] is not None else None
    buf = await stats.equity_chart(ws["id"], deposit)
    if buf is None:
        await update.message.reply_text("Grafik uchun kamida 2 ta yopilgan signal kerak.",
                                         reply_markup=MENU_BACK_KB)
        return
    async with busy(ctx.bot, update.effective_chat.id):
        await update.message.reply_photo(InputFile(buf, "equity.png"),
                                          reply_markup=MENU_BACK_KB)


async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    async with busy(ctx.bot, update.effective_chat.id):
        text, kb = await open_signals_view(ws, update.effective_user.id)
    rows = (list(kb.inline_keyboard) if kb else []) + list(MENU_BACK_KB.inline_keyboard)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=InlineKeyboardMarkup(rows))


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /cancel 12")
        return
    sig = await db.get_signal(int(ctx.args[0]))
    if not sig:
        await update.message.reply_text("Topilmadi.", reply_markup=MENU_BACK_KB)
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(update.effective_user.id, ws):
        return
    ok = await db.cancel_signal(sig["id"])
    await update.message.reply_text(
        "✅ Bekor qilindi." if ok else "Topilmadi yoki allaqachon yopilgan.",
        reply_markup=MENU_BACK_KB)


async def cmd_deposit(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not can_manage(uid, ws):
        await update.message.reply_text("Ruxsat yo'q.")
        return

    if not ctx.args:
        cur = ws["deposit"]
        txt = f"{float(cur):,.2f}" if cur is not None else "belgilanmagan"
        await update.message.reply_text(
            f"Joriy depozit ({html.escape(ws['name'])}): <b>{txt}</b>\n\n"
            "Yangilash uchun: <code>/depozit 1000</code>\n\n"
            "Depozit belgilansa, har bir yangi signal tasdiqlangach \"necha pul "
            "ishlatasiz\" deb so'raladi (ixtiyoriy) — shundan real (pulga bog'liq) "
            "foyda/zarar hisoblanadi.",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    amount = _parse_price(ctx.args[0])
    if amount is None or amount <= 0:
        await update.message.reply_text("Noto'g'ri summa. Masalan: /depozit 1000")
        return
    await db.set_deposit(ws["id"], amount)
    await update.message.reply_text(f"✅ Depozit yangilandi: <b>{amount:,.2f}</b>",
                                     parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)


async def cmd_public(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not can_manage(uid, ws):
        await update.message.reply_text("Ruxsat yo'q.")
        return
    if ws["type"] != "group":
        await update.message.reply_text("Bu buyruq faqat guruh workspace uchun ishlaydi.")
        return

    if not ctx.args:
        if not ws["public"]:
            cur = "o'chirilgan 🔒"
        elif ws["public_approved"]:
            cur = "yoqilgan ✅"
        else:
            cur = "tasdiqlanishi kutilmoqda ⏳"
        await update.message.reply_text(
            f"\"{html.escape(ws['name'])}\" guruhingizning <code>/top</code> reytingida "
            f"ko'rinishi: <b>{cur}</b>\n\n"
            "Yoqish: <code>/public on</code>\nO'chirish: <code>/public off</code>",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    arg = ctx.args[0].lower()
    if arg not in ("on", "off"):
        await update.message.reply_text("Foydalanish: /public on  yoki  /public off")
        return

    if arg == "off":
        await db.set_public(ws["id"], False)
        await update.message.reply_text(
            "🔒 Guruhingiz reytingdan olib tashlandi.", reply_markup=MENU_BACK_KB)
        return

    await db.set_public(ws["id"], True)
    if ws["public_approved"]:
        await update.message.reply_text(
            "✅ Guruhingiz endi /top reytingida ko'rinadi.", reply_markup=MENU_BACK_KB)
        return
    await request_public_approval(ctx, ws["id"])
    await update.message.reply_text(
        "⏳ So'rov yuborildi. Guruhingiz moderator tasdig'idan keyin "
        "<code>/top</code> reytingida ko'rinadi — tayyor bo'lganda xabar beramiz.",
        parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)


# ── /top moderatsiyasi (reytingdagi guruh nomi va havolasi hammaga ko'rinadi) ──

async def request_public_approval(ctx: ContextTypes.DEFAULT_TYPE, wid: int) -> None:
    """Super-adminlarga tasdiq so'rovini yuboradi."""
    ws = await db.get_workspace(wid)
    if not ws:
        return
    link = ws["invite_link"] or "— (belgilanmagan)"
    txt = ("🛡 <b>/top reytingiga so'rov</b>\n\n"
           f"Guruh: <b>{html.escape(ws['name'])}</b>\n"
           f"Havola: <code>{html.escape(link)}</code>\n\n"
           "Tasdiqlansa, bu nom va havola BARCHA bot foydalanuvchilariga ko'rinadi.")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"pubok:{wid}"),
        InlineKeyboardButton("🚫 Rad etish", callback_data=f"pubno:{wid}"),
    ]])
    for admin_id in config.ADMIN_IDS:
        try:
            await ctx.bot.send_message(admin_id, txt, parse_mode=ParseMode.HTML,
                                        reply_markup=kb)
        except Exception:
            log.exception("Tasdiq so'rovi yuborilmadi (admin=%s)", admin_id)


async def on_public_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    action, _, raw = q.data.partition(":")
    ws = await db.get_workspace(int(raw))
    if not ws:
        await q.edit_message_text("Workspace topilmadi.")
        return

    approved = action == "pubok"
    await db.set_public_approved(ws["id"], approved)
    if not approved:
        await db.set_public(ws["id"], False)

    name = html.escape(ws["name"])
    await q.edit_message_text(
        (f"✅ <b>{name}</b> tasdiqlandi — reytingda ko'rinadi."
         if approved else
         f"🚫 <b>{name}</b> rad etildi — reytingga chiqmaydi."),
        parse_mode=ParseMode.HTML)

    try:
        await ctx.bot.send_message(
            ws["owner_id"],
            ("✅ Guruhingiz <code>/top</code> reytingida ko'rina boshladi."
             if approved else
             "🚫 Guruhingiz <code>/top</code> reytingiga qo'shilmadi. "
             "Guruh nomi yoki havolasini to'g'rilab, qayta urinib ko'ring."),
            parse_mode=ParseMode.HTML)
    except Exception:
        log.exception("Egaga qaror yuborilmadi (ws=%s)", ws["id"])


async def cmd_pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Super-admin: tasdiq kutayotgan guruhlar ro'yxati."""
    if not is_admin(update.effective_user.id):
        return
    rows = await db.list_pending_public()
    if not rows:
        await update.message.reply_text("Tasdiq kutayotgan guruh yo'q. ✅",
                                         reply_markup=MENU_BACK_KB)
        return
    await update.message.reply_text(f"Tasdiq kutmoqda: {len(rows)} ta")
    for ws in rows:
        await request_public_approval(ctx, ws["id"])


# ─────────────────────────── Admin panel ───────────────────────────

ADMIN_BACK_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("◀️ Admin panel", callback_data="adm:home")]])


def admin_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistika", callback_data="adm:stats"),
         InlineKeyboardButton("🎁 Referrallar", callback_data="adm:refs")],
        [InlineKeyboardButton("👥 Guruhlar", callback_data="adm:groups"),
         InlineKeyboardButton("🙍 Foydalanuvchilar", callback_data="adm:users:0")],
        [InlineKeyboardButton("📢 Majburiy obuna", callback_data="adm:ch"),
         InlineKeyboardButton("🛡 Tasdiqlar", callback_data="adm:pend")],
        [InlineKeyboardButton("📰 MarketTwits hashtaglar", callback_data="adm:mth")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="adm:bc")],
        [InlineKeyboardButton("📄 Guruhlar PDF", callback_data="adm:pdfg"),
         InlineKeyboardButton("📄 Userlar PDF", callback_data="adm:pdfu")],
    ])


def _who(username, first_name, uid) -> str:
    """Foydalanuvchini ko'rsatish uchun eng ma'lumotli nom."""
    if username:
        return f"@{username}"
    return first_name or str(uid)


async def group_health(bot, ws) -> tuple[str, str]:
    """Bot guruhda hali bormi va admin'mi — "bloklash holati" shu yerda
    ko'rinadi. Har bir chaqiruv Telegram'ga so'rov yuboradi, shuning uchun
    faqat admin so'raganda (ro'yxat/karta ochilganda) bajariladi."""
    cid = ws["group_chat_id"]
    if not cid:
        return "⚪", "guruh biriktirilmagan"
    try:
        me = await bot.get_chat_member(cid, bot.id)
    except Exception as e:
        return "🚫", f"bog'lanib bo'lmadi ({type(e).__name__})"
    if me.status in ("left", "kicked"):
        return "🚫", "bot guruhdan chiqarilgan"
    if me.status != "administrator":
        return "⚠️", "bot admin emas — post/reply ishlamaydi"
    try:
        n = await bot.get_chat_member_count(cid)
        return "✅", f"admin • {n} a'zo"
    except Exception:
        return "✅", "admin"


async def _admin_groups_view(bot) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.admin_list_groups()
    if not rows:
        return "👥 Hali birorta guruh ulanmagan.", ADMIN_BACK_KB

    lines = ["👥 <b>Ulangan guruhlar</b>", ""]
    kb = []
    for ws in rows:
        icon, _ = await group_health(bot, ws)
        arch = " 📦" if ws["archived"] else ""
        name = html.escape(ws["name"])[:28]
        lines.append(
            f"{icon}{arch} <b>{name}</b> — {ws['n_signals']} signal, "
            f"{ws['n_viewers']} kuzatuvchi")
        kb.append([InlineKeyboardButton(f"{icon} {ws['name']}"[:40],
                                         callback_data=f"adm:grp:{ws['id']}")])
    lines += ["", "✅ ishlayapti · ⚠️ admin emas · 🚫 chiqarilgan · 📦 arxivlangan"]
    kb.append([InlineKeyboardButton("◀️ Admin panel", callback_data="adm:home")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def _admin_group_card(bot, wid: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.admin_list_groups()
    ws = next((r for r in rows if r["id"] == wid), None)
    if not ws:
        return "Topilmadi.", ADMIN_BACK_KB
    icon, health = await group_health(bot, ws)
    owner = _who(ws["owner_username"], ws["owner_name"], ws["owner_id"])
    dep = f"{float(ws['deposit']):,.2f}" if ws["deposit"] is not None else "—"
    pub = ("✅ reytingda" if ws["public"] and ws["public_approved"]
           else "⏳ tasdiq kutmoqda" if ws["public"] else "🔒 yashirin")
    txt = (
        f"{icon} <b>{html.escape(ws['name'])}</b>\n\n"
        f"Holat: <b>{health}</b>\n"
        f"Egasi: {html.escape(owner)} (<code>{ws['owner_id']}</code>)\n"
        f"Chat ID: <code>{ws['group_chat_id']}</code>\n"
        f"Signallar: <b>{ws['n_signals']}</b> (yopilgan {ws['n_closed']})\n"
        f"Kuzatuvchilar: {ws['n_viewers']}\n"
        f"Depozit: {dep}\n"
        f"Reyting: {pub}\n"
        f"Ochilgan: {ws['created_at']:%d.%m.%Y}"
        + ("\n\n📦 <b>Arxivlangan</b> — reytingda va tanlovda ko'rinmaydi."
           if ws["archived"] else "")
    )
    act = ("♻️ Arxivdan chiqarish", f"adm:unarch:{wid}") if ws["archived"] \
        else ("📦 Arxivlash", f"adm:arch:{wid}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Holatni tekshirish", callback_data=f"adm:grp:{wid}")],
        [InlineKeyboardButton(act[0], callback_data=act[1])],
        [InlineKeyboardButton("◀️ Guruhlar", callback_data="adm:groups")],
    ])
    return txt, kb


async def _admin_users_view(offset: int) -> tuple[str, InlineKeyboardMarkup]:
    PER = 8
    total = await db.count_users()
    rows = await db.admin_list_users(PER, offset)
    lines = [f"🙍 <b>Foydalanuvchilar</b> — jami {total} ta", ""]
    kb = []
    for u in rows:
        badges = []
        if u["has_personal"]:
            badges.append("🧑")
        if u["owned_groups"]:
            badges.append(f"👑{u['owned_groups']}")
        if u["viewer_links"]:
            badges.append(f"👥{u['viewer_links']}")
        if u["invited"]:
            badges.append(f"🎁{u['invited']}")
        if u["blocked"]:
            badges.append("🚫")
        who = _who(u["username"], u["first_name"], u["user_id"])
        lines.append(f"{' '.join(badges) or '·'} {html.escape(who)}")
        kb.append([InlineKeyboardButton(f"{who}"[:40],
                                         callback_data=f"adm:usr:{u['user_id']}")])
    lines += ["", "🧑 shaxsiy jurnal · 👑 guruh egasi · 👥 guruhga ulangan · "
              "🎁 taklif qilgan · 🚫 botni bloklagan"]

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"adm:users:{max(0, offset - PER)}"))
    if offset + PER < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"adm:users:{offset + PER}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("◀️ Admin panel", callback_data="adm:home")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def _admin_user_card(bot, uid: int, live: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    d = await db.admin_user_detail(uid)
    u = d["user"]
    if not u:
        return "Topilmadi.", ADMIN_BACK_KB
    who = _who(u["username"], u["first_name"], uid)
    t = [f"🙍 <b>{html.escape(who)}</b>", f"ID: <code>{uid}</code>", ""]

    personal = [w for w in d["owned"] if w["type"] == "personal"]
    groups = [w for w in d["owned"] if w["type"] == "group"]
    t.append(f"Shaxsiy jurnal: {'bor 🧑' if personal else 'yo‘q'}")
    if groups:
        t.append("Egalik qiladigan guruhlar 👑:")
        for w in groups:
            t.append(f"  • {html.escape(w['name'])}" + (" 📦" if w["archived"] else ""))
    else:
        t.append("Guruh egasi: yo‘q")

    if d["viewing"]:
        t.append("")
        t.append("Ulangan yopiq guruhlar 👥:")
        for w in d["viewing"]:
            mark = ""
            if live:
                # Jonli a'zolik tekshiruvi — group_viewers faqat "ulanган"ligini
                # bildiradi, hozir haqiqatan a'zomi yo'qmi Telegram aytadi.
                try:
                    m = await bot.get_chat_member(w["group_chat_id"], uid)
                    mark = " ✅" if m.status not in ("left", "kicked") else " 🚫 a'zo emas"
                except Exception:
                    mark = " ❔ tekshirib bo'lmadi"
            t.append(f"  • {html.escape(w['name'])}{mark}")
    else:
        t.append("")
        t.append("Ulangan yopiq guruhlar: yo‘q")

    t += ["", f"Taklif qilgan: <b>{d['invited']}</b> ta"]
    if d["invited_by"]:
        t.append(f"Kim taklif qilgan: <code>{d['invited_by']}</code>")
    t += [f"Birinchi: {u['first_seen']:%d.%m.%Y}",
          f"Oxirgi faollik: {u['last_seen']:%d.%m.%Y %H:%M}"]

    kb = [[InlineKeyboardButton("🔍 A'zolikni jonli tekshirish",
                                 callback_data=f"adm:usrchk:{uid}")]] if d["viewing"] else []
    kb.append([InlineKeyboardButton("◀️ Foydalanuvchilar", callback_data="adm:users:0")])
    return "\n".join(t), InlineKeyboardMarkup(kb)


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🛠 <b>Admin panel</b>", parse_mode=ParseMode.HTML,
                                     reply_markup=admin_home_kb())


async def _admin_stats_text() -> str:
    u = await db.user_stats()
    p = await db.platform_stats()
    return (
        "📊 <b>Statistika</b>\n\n"
        "<b>Foydalanuvchilar</b>\n"
        f"Jami: <b>{u['total']}</b>\n"
        f"Yangi: {u['new_1d']} (24s)  •  {u['new_7d']} (7 kun)\n"
        f"Faol: {u['act_1d']} (24s)  •  {u['act_7d']} (7 kun)\n\n"
        "<b>Workspace'lar</b>\n"
        f"Guruhlar: <b>{p['groups']}</b>  •  Shaxsiy: <b>{p['personals']}</b>\n"
        f"Guruh kuzatuvchilari: {p['viewers']}\n"
        f"Reytingda: {p['public_ok']} ta (so'rov: {p['public_req']})\n\n"
        "<b>Signallar</b>\n"
        f"Jami: <b>{p['signals_all']}</b>\n"
        f"Ochiq: {p['signals_open']}  •  Yopilgan: {p['signals_closed']}"
    )


async def _admin_refs_text() -> str:
    total, top = await db.referral_stats()
    lines = ["🎁 <b>Referrallar</b>", "", f"Jami taklif qilinganlar: <b>{total}</b>", ""]
    if not top:
        lines.append("Hali hech kim taklif qilmagan.")
    else:
        lines.append("<b>Eng faol takliflovchilar:</b>")
        for i, r in enumerate(top, 1):
            who = r["username"] and f"@{r['username']}" or (r["first_name"] or str(r["referrer_id"]))
            lines.append(f"{i}. {html.escape(str(who))} — <b>{r['n']}</b> ta")
    return "\n".join(lines)


async def _admin_channels_view() -> tuple[str, InlineKeyboardMarkup]:
    chans = await db.list_required_channels()
    if chans:
        lines = ["📢 <b>Majburiy obuna kanallari</b>", "",
                 "Botga /start bosgan har bir foydalanuvchi shu kanallarga "
                 "obuna bo'lishi shart (adminlar bundan mustasno).", ""]
        for ch in chans:
            name = ch["title"] or ch["username"] or str(ch["chat_id"])
            lines.append(f"• {html.escape(str(name))}")
    else:
        lines = ["📢 <b>Majburiy obuna kanallari</b>", "",
                 "Hozircha kanal yo'q — majburiy obuna <b>o'chirilgan</b>."]
    rows = [[InlineKeyboardButton(
        f"❌ {(ch['title'] or ch['username'] or ch['chat_id'])}"[:40],
        callback_data=f"adm:chdel:{ch['chat_id']}")] for ch in chans]
    rows.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="adm:chadd")])
    rows.append([InlineKeyboardButton("◀️ Admin panel", callback_data="adm:home")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _admin_hashtags_view() -> tuple[str, InlineKeyboardMarkup]:
    """MarketTwits'da tikersiz ham "muhim" deb hisoblanadigan qo'shimcha
    #hashtag ro'yxati (masalan #geopolitika) — `_markettwits_symbol()`
    hech qanday tiker topmasa, shu ro'yxat orqali TEXT-ONLY post qilinadi
    (grafiksiz, chunki tiker yo'q)."""
    tags = await db.list_market_hashtags()
    if tags:
        lines = ["📰 <b>MarketTwits — qo'shimcha #hashtaglar</b>", "",
                 "Bu hashtaglardan biri postda bo'lsa — tiker topilmasa ham "
                 "(matn-only) kanalga postlanadi.", ""]
        for t in tags:
            lines.append(f"• #{html.escape(t)}")
    else:
        lines = ["📰 <b>MarketTwits — qo'shimcha #hashtaglar</b>", "",
                 "Hozircha yo'q — faqat RESOLVE bo'ladigan tikerli postlar "
                 "(masalan #BTC, #AAPL) o'tadi."]
    rows = [[InlineKeyboardButton(f"❌ #{t}"[:40], callback_data=f"adm:mthdel:{t}")]
            for t in tags]
    rows.append([InlineKeyboardButton("➕ Hashtag qo'shish", callback_data="adm:mthadd")])
    rows.append([InlineKeyboardButton("◀️ Admin panel", callback_data="adm:home")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def handle_hashtag_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin yuborgan matndagi HAR BIR so'zni (bo'shliq/vergul bilan
    ajratilgan, boshidagi # ixtiyoriy) alohida hashtag sifatida qo'shadi —
    bir martada bir nechtasini qo'shish uchun."""
    msg = update.effective_message
    raw = (msg.text or "").strip()
    tags = [t.lstrip("#").strip() for t in re.split(r"[,\s]+", raw) if t.strip("#, ")]
    if not tags:
        await msg.reply_text("Hashtag topilmadi. Masalan: geopolitika, hisobot",
                             reply_markup=ADMIN_BACK_KB)
        return
    for t in tags:
        await db.add_market_hashtag(t.lower())
    txt, kb = await _admin_hashtags_view()
    await msg.reply_text(f"✅ Qo'shildi: {', '.join('#'+t for t in tags)}\n\n{txt}",
                         parse_mode=ParseMode.HTML, reply_markup=kb)


async def on_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer()
        return
    await q.answer()
    action = q.data.split(":", 1)[1]

    if action == "home":
        await q.edit_message_text("🛠 <b>Admin panel</b>", parse_mode=ParseMode.HTML,
                                   reply_markup=admin_home_kb())
    elif action == "stats":
        await q.edit_message_text(await _admin_stats_text(), parse_mode=ParseMode.HTML,
                                   reply_markup=ADMIN_BACK_KB)
    elif action == "refs":
        await q.edit_message_text(await _admin_refs_text(), parse_mode=ParseMode.HTML,
                                   reply_markup=ADMIN_BACK_KB)
    elif action == "ch":
        txt, kb = await _admin_channels_view()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action == "chadd":
        AWAITING_CHANNEL[q.from_user.id] = True
        await q.edit_message_text(
            "➕ <b>Kanal qo'shish</b>\n\n"
            "Kanal <code>@usernameni</code> yuboring, yoki o'sha kanaldan "
            "istalgan postni shu yerga <b>forward</b> qiling.\n\n"
            "⚠️ Bot o'sha kanalda <b>admin</b> bo'lishi shart — aks holda "
            "obunani tekshirib bo'lmaydi.",
            parse_mode=ParseMode.HTML, reply_markup=ADMIN_BACK_KB)
    elif action.startswith("chdel:"):
        await db.remove_required_channel(int(action.split(":", 1)[1]))
        _sub_ok_until.clear()
        txt, kb = await _admin_channels_view()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action == "mth":
        txt, kb = await _admin_hashtags_view()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action == "mthadd":
        AWAITING_HASHTAG[q.from_user.id] = True
        await q.edit_message_text(
            "➕ <b>Hashtag qo'shish</b>\n\n"
            "Bitta yoki bir nechta so'z yuboring (# bilan yoki #siz, "
            "bo'shliq/vergul bilan ajratib) — masalan:\n"
            "<code>geopolitika, hisobot, ETF</code>",
            parse_mode=ParseMode.HTML, reply_markup=ADMIN_BACK_KB)
    elif action.startswith("mthdel:"):
        await db.remove_market_hashtag(action.split(":", 1)[1])
        txt, kb = await _admin_hashtags_view()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action == "pend":
        rows = await db.list_pending_public()
        if not rows:
            await q.edit_message_text("🛡 Tasdiq kutayotgan guruh yo'q. ✅",
                                       reply_markup=ADMIN_BACK_KB)
            return
        await q.edit_message_text(f"🛡 Tasdiq kutmoqda: <b>{len(rows)}</b> ta",
                                   parse_mode=ParseMode.HTML, reply_markup=ADMIN_BACK_KB)
        for ws in rows:
            await request_public_approval(ctx, ws["id"])

    # ── Guruhlar ──
    elif action == "groups":
        await q.edit_message_text("👥 Guruhlar holati tekshirilmoqda…")
        txt, kb = await _admin_groups_view(ctx.bot)
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action.startswith("grp:"):
        txt, kb = await _admin_group_card(ctx.bot, int(action.split(":", 1)[1]))
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action.startswith(("arch:", "unarch:")):
        wid = int(action.split(":", 1)[1])
        await db.set_archived(wid, action.startswith("arch:"))
        txt, kb = await _admin_group_card(ctx.bot, wid)
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

    # ── Foydalanuvchilar ──
    elif action.startswith("users:"):
        txt, kb = await _admin_users_view(int(action.split(":", 1)[1]))
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action.startswith("usr:"):
        txt, kb = await _admin_user_card(ctx.bot, int(action.split(":", 1)[1]))
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action.startswith("usrchk:"):
        await q.edit_message_text("🔍 A'zolik tekshirilmoqda…")
        txt, kb = await _admin_user_card(ctx.bot, int(action.split(":", 1)[1]), live=True)
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

    # ── Broadcast ──
    elif action == "bc":
        await _admin_broadcast_prompt(q)
    elif action == "bcgo":
        pend = PENDING_BROADCAST.pop(q.from_user.id, None)
        AWAITING_BROADCAST.pop(q.from_user.id, None)
        if not pend:
            await q.edit_message_text("Yuboriladigan xabar topilmadi — qaytadan boshlang.",
                                       reply_markup=ADMIN_BACK_KB)
            return
        from_chat, msg_id = pend
        ctx.job_queue.run_once(
            run_broadcast, when=0,
            data={"admin": q.from_user.id, "from_chat": from_chat, "msg_id": msg_id})
        await q.edit_message_text("📣 Yuborish boshlandi — tugagach hisobot keladi.",
                                   reply_markup=ADMIN_BACK_KB)

    # ── PDF eksport ──
    elif action in ("pdfg", "pdfu"):
        await q.message.reply_text("📄 Tayyorlanmoqda…")
        if action == "pdfg":
            buf, fname = await _admin_groups_pdf(ctx.bot)
        else:
            buf, fname = await _admin_users_pdf()
        await q.message.reply_document(InputFile(buf, fname), reply_markup=ADMIN_BACK_KB)


async def _admin_groups_pdf(bot) -> tuple[io.BytesIO, str]:
    rows = await db.admin_list_groups()
    header = f"{'Guruh':<26}{'Signal':>8}{'Yopilgan':>10}{'Kuzatuv':>9}  {'Holat':<16}"
    lines = []
    n_bad = 0
    for ws in rows:
        # Har guruh uchun BIR marta so'raladi — natija ham qatorga, ham
        # sarlavhadagi hisobga ishlatiladi (ikki marta chaqirilsa Telegram
        # so'rovlari bekorga ikki barobar bo'lardi).
        icon, health = await group_health(bot, ws)
        if icon == "🚫":
            n_bad += 1
        state = {"✅": "ishlayapti", "⚠️": "admin emas",
                 "🚫": "chiqarilgan", "⚪": "biriktirilmagan"}.get(icon, health)
        if ws["archived"]:
            state += " (arxiv)"
        col = stats.P_GREEN if icon == "✅" and not ws["archived"] else (
            stats.P_RED if icon == "🚫" else stats.P_TXT)
        lines.append((
            f"{ws['name'][:26]:<26}{ws['n_signals']:>8}{ws['n_closed']:>10}"
            f"{ws['n_viewers']:>9}  {state:<16}", col))
    buf = stats.pdf_table_report(
        "Ulangan guruhlar", f"Jami {len(rows)} ta guruh · {n_bad} tasida muammo",
        header, lines)
    return buf, f"guruhlar-{datetime.now(stats.TZ):%Y-%m-%d}.pdf"


async def _admin_users_pdf() -> tuple[io.BytesIO, str]:
    total = await db.count_users()
    rows = await db.admin_list_users(limit=10000, offset=0)
    header = f"{'Foydalanuvchi':<24}{'ID':>12}  {'Rol':<20}{'Taklif':>7}  {'Oxirgi':<10}"
    lines = []
    for u in rows:
        roles = []
        if u["has_personal"]:
            roles.append("shaxsiy")
        if u["owned_groups"]:
            roles.append(f"egasi×{u['owned_groups']}")
        if u["viewer_links"]:
            roles.append(f"a'zo×{u['viewer_links']}")
        who = _who(u["username"], u["first_name"], u["user_id"])
        lines.append((
            f"{who[:24]:<24}{u['user_id']:>12}  {', '.join(roles)[:20]:<20}"
            f"{u['invited']:>7}  {u['last_seen']:%d.%m.%y}", stats.P_TXT))
    buf = stats.pdf_table_report(
        "Foydalanuvchilar", f"Jami {total} ta", header, lines)
    return buf, f"userlar-{datetime.now(stats.TZ):%Y-%m-%d}.pdf"


# ─────────────────────────── Broadcast ───────────────────────────
# Telegram bir botdan turli odamlarga ~30 xabar/sekund ruxsat beradi. Undan
# tez yuborilsa flood-limit tushadi va bot vaqtincha jazolanadi — shuning
# uchun ataylab sekinroq (20/sek) yuboriladi.
BROADCAST_PER_SEC = 20
_BC_DELAY = 1.0 / BROADCAST_PER_SEC


async def _admin_broadcast_prompt(q) -> None:
    AWAITING_BROADCAST[q.from_user.id] = True
    PENDING_BROADCAST.pop(q.from_user.id, None)
    n = len(await db.broadcast_targets())
    await q.edit_message_text(
        "📣 <b>Broadcast</b>\n\n"
        f"Xabar <b>{n}</b> ta foydalanuvchiga yuboriladi.\n\n"
        "Yubormoqchi bo'lgan xabaringizni shu yerga yuboring — matn, rasm, "
        "video, nima bo'lsa ham. Qanday yuborsangiz, xuddi shundayligicha "
        "yetkaziladi.\n\n"
        "Bekor qilish uchun /bekor yozing.",
        parse_mode=ParseMode.HTML, reply_markup=ADMIN_BACK_KB)


async def handle_broadcast_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin yuborgan xabarni eslab qolib, tasdiqlashni so'raydi.

    Xabar NUSXALANADI (copy_message) — shuning uchun matn ham, rasm ham,
    formatlash ham o'zgarmasdan boradi va "forwarded from" yozuvi chiqmaydi.
    Tasdiqlash bosqichi ataylab: hammaga yuborilgan xabarni qaytarib
    bo'lmaydi."""
    msg = update.effective_message
    uid = update.effective_user.id
    PENDING_BROADCAST[uid] = (msg.chat_id, msg.message_id)
    n = len(await db.broadcast_targets())
    await msg.reply_text(
        f"⬆️ Shu xabar <b>{n}</b> ta foydalanuvchiga yuboriladi.\n"
        f"Taxminiy vaqt: ~{max(1, round(n * _BC_DELAY))} soniya.\n\n"
        "Tasdiqlaysizmi?",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ha, yuborilsin", callback_data="adm:bcgo")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="adm:home")],
        ]))


async def run_broadcast(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Job sifatida ishlaydi — yuborish uzoq davom etsa ham bot javob
    berishda davom etadi."""
    d = ctx.job.data
    admin_id, from_chat, msg_id = d["admin"], d["from_chat"], d["msg_id"]
    targets = await db.broadcast_targets()
    sent = blocked = failed = 0

    for uid in targets:
        try:
            await ctx.bot.copy_message(uid, from_chat, msg_id)
            sent += 1
        except Forbidden:
            # Bot bloklangan yoki chat o'chirilgan — belgilab qo'yamiz, keyingi
            # broadcast'da bekorga urinilmaydi.
            blocked += 1
            await db.mark_blocked(uid)
        except RetryAfter as e:
            # Flood-limit: kutamiz va SHU odamga qayta urinamiz (tashlab
            # ketmaymiz — aks holda xabar unga yetmay qolardi).
            log.warning("Broadcast flood-limit: %s s", e.retry_after)
            await asyncio.sleep(e.retry_after + 1)
            try:
                await ctx.bot.copy_message(uid, from_chat, msg_id)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
            log.exception("Broadcast xatosi (uid=%s)", uid)
        await asyncio.sleep(_BC_DELAY)

    try:
        await ctx.bot.send_message(
            admin_id,
            "📣 <b>Broadcast tugadi</b>\n\n"
            f"✅ Yuborildi: <b>{sent}</b>\n"
            f"🚫 Bloklaganlar: {blocked}\n"
            f"⚠️ Xato: {failed}\n\n"
            f"Jami: {len(targets)}",
            parse_mode=ParseMode.HTML, reply_markup=ADMIN_BACK_KB)
    except Exception:
        log.exception("Broadcast hisoboti yuborilmadi")


async def handle_channel_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin @username yuborgan yoki kanaldan post forward qilgan holat."""
    msg = update.effective_message
    target = None
    origin = getattr(msg, "forward_origin", None)
    origin_chat = getattr(origin, "chat", None) if origin else None
    if origin_chat is not None:
        target = origin_chat.id
    else:
        raw = (msg.text or msg.caption or "").strip().split()
        if raw:
            target = raw[0]

    if not target:
        await msg.reply_text("Kanalni aniqlab bo'lmadi. @username yuboring yoki "
                             "kanaldan post forward qiling.", reply_markup=ADMIN_BACK_KB)
        return

    try:
        chat = await ctx.bot.get_chat(target)
    except Exception:
        await msg.reply_text(
            "❌ Kanal topilmadi. @username to'g'riligini va botning o'sha kanalda "
            "admin ekanini tekshiring.", reply_markup=ADMIN_BACK_KB)
        return

    # Bot kanalda admin bo'lmasa obunani tekshirib bo'lmaydi va tekshiruv
    # (ataylab) OCHIQ qoladi — ya'ni talab jimgina ishlamaydi. Admin buni
    # bilishi shart, shuning uchun ochiq ogohlantiramiz.
    warn = ""
    try:
        me = await ctx.bot.get_me()
        m = await ctx.bot.get_chat_member(chat.id, me.id)
        if m.status not in ("administrator", "creator"):
            warn = ("\n\n⚠️ <b>Diqqat:</b> bot bu kanalda admin emas — obuna "
                    "tekshiruvi ishlamaydi. Botni kanalga admin qilib qo'shing.")
    except Exception:
        warn = ("\n\n⚠️ <b>Diqqat:</b> botning kanaldagi holatini tekshirib "
                "bo'lmadi. Bot kanalda admin ekaniga ishonch hosil qiling.")

    await db.add_required_channel(chat.id, chat.title, chat.username)
    _sub_ok_until.clear()
    await msg.reply_text(
        f"✅ Qo'shildi: <b>{html.escape(chat.title or str(chat.id))}</b>{warn}",
        parse_mode=ParseMode.HTML, reply_markup=ADMIN_BACK_KB)


async def cmd_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not can_manage(uid, ws):
        await update.message.reply_text("Ruxsat yo'q.")
        return
    if ws["type"] != "group":
        await update.message.reply_text("Bu buyruq faqat guruh workspace uchun ishlaydi.")
        return

    if not ctx.args:
        cur = ws["invite_link"] or "belgilanmagan"
        await update.message.reply_text(
            f"\"{html.escape(ws['name'])}\" guruhingizning taklif havolasi: "
            f"<b>{html.escape(cur)}</b>\n\n"
            "<code>/top</code> reytingida guruh nomi shu havolaga link qilinadi.\n\n"
            "Belgilash: <code>/havola https://t.me/+abc123</code>\n"
            "O'chirish: <code>/havola off</code>",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    arg = ctx.args[0].strip()
    if arg.lower() == "off":
        await db.set_invite_link(ws["id"], None)
        await update.message.reply_text(
            "🔒 Taklif havolasi o'chirildi.", reply_markup=MENU_BACK_KB)
        return

    if not arg.startswith(("http://", "https://")):
        arg = "https://" + arg
    changed = arg != ws["invite_link"]
    await db.set_invite_link(ws["id"], arg)
    txt = f"✅ Taklif havolasi saqlandi:\n<code>{html.escape(arg)}</code>"

    # Havola o'zgarsa db.set_invite_link() tasdiqni bekor qiladi — reytingda
    # turgan guruh yangi havola bilan qayta tasdiqdan o'tishi kerak.
    if changed and ws["public"] and ws["public_approved"]:
        await request_public_approval(ctx, ws["id"])
        txt += ("\n\n⏳ Havola o'zgargani uchun <code>/top</code> reytingidagi "
                "tasdiq yangilanishi kerak — moderator ko'rib chiqmaguncha "
                "guruhingiz reytingda ko'rinmaydi.")
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML,
                                     reply_markup=MENU_BACK_KB)


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(stats.TZ)
    a, b = stats.month_bounds(now.year, now.month)
    rows = await db.top_workspaces(a, b, limit=10)
    if not rows:
        await update.message.reply_text(
            "Hali hech qanday ochiq guruh reytingda yo'q.\n\n"
            "Guruh admini bo'lsangiz, guruhingizni ko'rsatish uchun "
            "<code>/public on</code> yozing.",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>Eng yaxshi guruhlar — {stats.MONTHS_UZ[now.month - 1]} {now.year}</b>", ""]
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i + 1}."
        wr = r["wins"] / r["total"] * 100 if r["total"] else 0
        name = html.escape(r["name"])
        if r["invite_link"]:
            name_txt = f'<a href="{html.escape(r["invite_link"], quote=True)}">{name}</a>'
        else:
            name_txt = name
        lines.append(
            f"{medal} <b>{name_txt}</b> — <b>{float(r['sum_pct']):+.2f}%</b> "
            f"({r['total']} savdo, {wr:.0f}% WR)")
    lines += ["", "Guruhingizni shu reytingda ko'rsatish uchun admin <code>/public on</code> yozsin.",
              "Guruh nomini bosilganda o'z guruhingizga yo'naltirish uchun: <code>/havola &lt;link&gt;</code>"]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML,
                                     reply_markup=MENU_BACK_KB)


async def cmd_invite(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    bot_username = ctx.bot.username
    count = await db.count_referrals(uid)
    link = f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else None
    link_txt = f"<code>{link}</code>" if link else "(havola olinmadi, birozdan so'ng qayta urining)"
    await update.message.reply_text(
        f"🎁 Do'stlaringizni taklif qiling!\n\n"
        f"Sizning shaxsiy havolangiz:\n{link_txt}\n\n"
        f"Siz orqali botga kelganlar: <b>{count}</b>",
        parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)


# ─────────────────────────── News Trade AI ───────────────────────────
# Bozorni qimirlatadigan yangilikni avtomatik topib (news.py), tahlil qilib
# (newsai.py — tarjima/xulosa/filtr/tiker-taxmin), grafik chizib (chart.py)
# alohida kanalga joylaydi. `config.NEWS_CHANNEL_ID` bo'sh bo'lsa butun
# funksiya jimgina o'chiq — job hech narsa qilmaydi.

# Tiker taxmin qilinganda qaysi bozor turida qidirilishi — mavjud resolve()
# funksiyalari orqali TASDIQLANADI (modelning o'zi noto'g'ri taxmin qilishi
# mumkin, shu sabab bu yerda ham xuddi vision.py'dagi kabi ikkinchi bosqich
# bor). Kripto birinchi — News Trade AI'ning asosiy auditoriyasi shu.
NEWS_MARKETS = (("crypto", exchange), ("stock", stocks), ("forex", forex))

# Kanalning ochiq (public) username'i — "Do'stlarga yuborish" tugmasi va
# bosh menyudagi "News Trade AI" havolasi shundan foydalanadi. `NEWS_CHANNEL_ID`
# (Railway o'zgaruvchisi) faqat RAQAMLI chat id — postlash uchun yetarli,
# lekin `t.me/...` ochiq havola qurish uchun username kerak (u o'zgarmasa
# kerak, shuning uchun qattiq yozilgan — `mexc_ref_url`dan farqli, bu
# botning o'z identifikatori, tashqi referal havolasi emas).
NEWS_CHANNEL_USERNAME = "newstradeuz"


def _share_button(message_id: int) -> InlineKeyboardButton:
    """Telegram'ning rasmiy "share" chuqur-havolasi (`t.me/share/url?url=...`)
    — bosilganda foydalanuvchiga ICHKI Telegram chat tanlash oynasi ochiladi,
    o'sha aynan shu postni istalgan chatga/do'stiga OLDINGA yuboradi. Bot
    tomonidan qo'shimcha kod YOZILMAYDI — Telegram'ning o'zi bajaradi,
    faqat postning ochiq havolasi (`t.me/<kanal>/<message_id>`) kerak."""
    post_url = f"https://t.me/{NEWS_CHANNEL_USERNAME}/{message_id}"
    share_url = "https://t.me/share/url?" + urlencode({"url": post_url})
    return InlineKeyboardButton("↗️ Do'stlarga yuborish", url=share_url)


async def _add_share_button(bot_, chat_id, message_id: int,
                            buttons: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup:
    """Postni yuborgandan KEYIN chaqiriladi — havola `message_id`ga
    bog'liq, u esa faqat `send_photo`/`send_message` qaytargandan so'ng
    ma'lum bo'ladi (tugmani boshidanoq qo'shib bo'lmaydi). Shuning uchun
    avval ODDIY tugmalar bilan postlanadi, so'ng shu funksiya "Do'stlarga
    yuborish"ni qo'shib, xabarni DARHOL tahrirlaydi — foydalanuvchi buni
    sezmaydi (bir necha soniya ham o'tmaydi)."""
    rows = list(buttons.inline_keyboard) if buttons else []
    rows.append([_share_button(message_id)])
    full = InlineKeyboardMarkup(rows)
    try:
        await bot_.edit_message_reply_markup(chat_id, message_id, reply_markup=full)
    except Exception:
        log.warning("Do'stlarga yuborish tugmasi qo'shilmadi (msg=%s)", message_id,
                    exc_info=True)
        return buttons if buttons else InlineKeyboardMarkup([])
    return full


async def cmd_ref_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/refhavola — FAQAT super-admin. News Trade AI/surge postlaridagi
    "💹 Savdo qilish" tugmasi uchun MEXC referal havolasini belgilaydi.
    Belgilanmagan bo'lsa tugma umuman ko'rsatilmaydi (referalsiz oddiy
    havola bexosdan postlanib qolmasin)."""
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not ctx.args:
        cur = await db.get_setting("mexc_ref_url")
        await update.message.reply_text(
            f"Joriy MEXC referal havola: {html.escape(cur) if cur else '(belgilanmagan)'}\n\n"
            "Belgilash: <code>/refhavola https://www.mexc.com/register?inviteCode=XXX</code>\n"
            "Agar havolada <code>{symbol}</code> bo'lsa, u postdagi juftlik bilan "
            "(masalan BTC_USDT) almashtiriladi.\n"
            "O'chirish: <code>/refhavola off</code>",
            parse_mode=ParseMode.HTML)
        return
    arg = ctx.args[0]
    if arg.lower() == "off":
        await db.set_setting("mexc_ref_url", None)
        await update.message.reply_text("🔒 Referal havola o'chirildi.")
        return
    await db.set_setting("mexc_ref_url", arg)
    await update.message.reply_text(f"✅ Saqlandi:\n{html.escape(arg)}",
                                    parse_mode=ParseMode.HTML)


async def _resolve_news_symbol(hint: str | None) -> tuple[str | None, str | None]:
    if not hint:
        return None, None
    for market, provider in NEWS_MARKETS:
        try:
            resolved = await provider.resolve(hint)
        except Exception:
            resolved = None
        if resolved:
            return resolved, market
    return None, None


async def _signal_buttons(symbol: str, market: str,
                          bot_username: str | None) -> InlineKeyboardMarkup | None:
    """News Trade AI / surge posti ostidagi tugmalar:
      1. "💹 Savdo qilish" — MEXC referal havolasi (`/refhavola` bilan
         admin belgilaydi; belgilanmagan bo'lsa tugma UMUMAN chiqmaydi —
         referalsiz oddiy havola postlanmaydi). Havolada `{symbol}` bo'lsa
         "BAZA_QUOTE" shaklidagi juftlik bilan almashtiriladi (masalan
         BTC_USDT), bo'lmasa havola o'zgarishsiz ishlatiladi.
      2. "📝 Jurnalga kiritish" — `/start journal_<SYMBOL>` deep-link.
         Bosilganda foydalanuvchi botning shaxsiy chatiga o'tadi va
         tikerni QAYTA YOZMASDAN faqat yo'nalish/narxlarni kiritadi."""
    rows = []
    if market == "crypto":
        ref = await db.get_setting("mexc_ref_url")
        if ref:
            base = symbol[:-len(config.QUOTE)] if symbol.endswith(config.QUOTE) else symbol
            pair = f"{base}_{config.QUOTE}"
            url = ref.replace("{symbol}", pair) if "{symbol}" in ref else ref
            rows.append([InlineKeyboardButton("💹 Savdo qilish", url=url)])
    if bot_username:
        rows.append([InlineKeyboardButton(
            "📝 Jurnalga kiritish", url=f"https://t.me/{bot_username}?start=journal_{symbol}")])
    return InlineKeyboardMarkup(rows) if rows else None


async def _process_news_event(ctx: ContextTypes.DEFAULT_TYPE, item: dict) -> None:
    """Bitta topilgan hodisani AI tahlildan o'tkazadi va (loyiqligicha)
    kanalga postlaydi. Har doim bazaga yozadi (post qilinmasa ham) — aks
    holda keyingi skaner siklida xuddi shu hodisa qayta topilib, Claude
    qayta chaqirilardi (bekorga xarajat)."""
    analysis = await newsai.analyze(item["headline_en"], item.get("body_en", ""))
    if analysis is None or not analysis.get("is_market_moving"):
        await db.insert_news_event(
            source=item["source"], external_key=item["external_key"],
            symbol=None, market=None, headline_en=item["headline_en"],
            translation_uz=None, insight_uz=None, event_at=item["event_at"],
            posted=True)
        return

    symbol, market = await _resolve_news_symbol(analysis.get("symbol_hint"))

    eid = await db.insert_news_event(
        source=item["source"], external_key=item["external_key"],
        symbol=symbol, market=market, headline_en=item["headline_en"],
        translation_uz=analysis.get("translation_uz"),
        insight_uz=analysis.get("insight_uz"), event_at=item["event_at"],
        posted=False)
    if eid is None:
        return   # boshqa parallel chaqiruv bu hodisani bizdan oldin yozgan

    caption = (f"📰 <b>{html.escape(analysis.get('insight_uz') or '')}</b>\n\n"
               f"{html.escape(analysis.get('translation_uz') or '')}\n\n"
               f"🔗 <a href=\"{html.escape(item.get('source_url', ''))}\">Asl manba</a>")

    photo, live_pct = None, None
    if symbol:
        try:
            rendered = await _news_render(symbol, market, item["event_at"])
        except Exception:
            log.warning("Yangilik grafigi yasalmadi (%s)", symbol, exc_info=True)
            rendered = None
        if rendered:
            photo, live_pct = rendered

    buttons = await _signal_buttons(symbol, market, ctx.bot.username) if symbol else None
    try:
        if photo:
            sent = await ctx.bot.send_photo(
                config.NEWS_CHANNEL_ID, InputFile(photo, "news.png"),
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            sent = await ctx.bot.send_message(
                config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True, reply_markup=buttons)
    except Exception:
        log.exception("Yangilik kanalga postlanmadi (%s)", item["external_key"])
        return
    # Faqat grafikli xabar jonli yangilanadi (`render_tf` to'ldirilgan bo'lsa
    # `news_live_job` uni "aktiv" deb topadi) — matn-only xabarda yangilanadigan
    # narsa yo'q (tiker topilmagan, ya'ni narx ham kuzatib bo'lmaydi).
    await db.set_news_message(
        eid, sent.message_id, caption,
        render_tf="1m" if (photo and symbol) else None,
        render_label="News" if (photo and symbol) else None)
    await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


async def _news_candles(symbol: str, market: str, event_at: datetime,
                        end_ms: int | None = None, tf: str = "1m",
                        before_ms: int | None = None
                        ) -> tuple[list, int, float] | None:
    """`_news_render()`/hajm portlashi (surge) profilli grafigi uchun
    UMUMIY — shamlarni olib, `news_idx`/`live_pct`ni hisoblaydi, LEKIN
    rasm CHIZMAYDI (chaqiruvchi o'zi `chart.news_chart()` yoki
    `chart.surge_profile_chart()`ni tanlaydi). Sham topilmasa `None`.

    `end_ms=None` — hozirgacha (jonli yangilanishda har safar o'sib
    boradigan oyna)."""
    if before_ms is None:
        before_ms = 60 * chart.TF_MINUTES[tf] * 60_000   # hodisadan OLDIN 60 sham
    event_ms = int(event_at.timestamp() * 1000)
    start_ms = chart.align(event_ms - before_ms, tf)
    if end_ms is None:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # `limit` butun [start_ms, end_ms] oynasini qamrab olishi SHART — MEXC
    # startTime+endTime ikkalasi berilganda ham natijani `limit`ga qarab
    # START tomondan kesadi (oxirigacha YETMASDAN). Qattiq "200" liq_before_ms
    # kabi keng (4 soat = 240x1m) oynalarda buzilardi: 200 < 240 bo'lgani
    # uchun qaytgan shamlar doim start_ms'dan boshlab, event_at'gacha ham
    # YETMAY qolardi — natija HAR safar bir xil (eskirgan) chiqib, Telegram
    # "message is not modified" deb rad etardi (jonli yangilanish "muzlab
    # qolgan" ko'rinardi). Live oyna (NEWS_LIVE_MINUTES) davomida yana
    # o'sishi mumkinligi uchun ozgina zaxira ham qo'shiladi.
    needed = (end_ms - start_ms) // (chart.TF_MINUTES[tf] * 60_000) \
        + config.NEWS_LIVE_MINUTES // chart.TF_MINUTES[tf] + 10
    limit = min(chart.MAX_CANDLES, max(200, needed))
    candles = await tracker.provider(market).klines(symbol, start_ms, limit=limit,
                                                     tf=tf, end_ms=end_ms)
    if not candles or len(candles) < 3:
        return None
    # `event_ms` va `start_ms` har chaqiriqda BIR XIL bo'lgani uchun
    # (`event_at` o'zgarmaydi), news_idx — demak "kirish" narxi — butun jonli
    # oyna davomida barqaror qoladi: foiz doim aynan shu ONdan hisoblanadi.
    #
    # MUHIM: avval `close_ms`ga ENG YAQIN shamni izlardik — lekin HALI
    # TUGAMAGAN (joriy) sham uchun `close_ms` davr OXIRINI bildiradi (masalan
    # "1d"da BUGUNGI kun oxiri, hali kelmagan — kelajakdagi vaqt), `event_ms`
    # esa deyarli doim HOZIR. Kunning ilk soatlarida "bugun oxiri"gacha bo'lgan
    # masofa "kecha oxiri"gacha bo'lgan masofadan KATTA chiqib, `news_idx`
    # NOTO'G'RI — bir sham OLDINGI (kechagi) sham deb tanlanardi (foydalanuvchi:
    # "bu kechagi kunni xisoblayabtiyu?" — portlash belgisi TACUSDT'ning eng
    # oxirgi emas, undan OLDINGI shamida chiqqan edi). Endi TO'G'RI: `event_ms`
    # qaysi shamning [open_ms, close_ms) oynasiga tushishini qidiramiz — joriy
    # (hali tugamagan) sham uchun ham bu TO'G'RI ishlaydi, chunki `open_ms` allaqachon
    # o'tgan, `close_ms` esa hali kelmagan bo'lsa ham `event_ms` shu oraliqda.
    news_idx = next((i for i, c in enumerate(candles) if c.open_ms <= event_ms < c.close_ms), None)
    if news_idx is None:
        news_idx = min(range(len(candles)), key=lambda i: abs(candles[i].close_ms - event_ms))
    anchor_price = candles[news_idx].close
    live_price = candles[-1].close
    live_pct = (live_price - anchor_price) / anchor_price * 100
    return candles, news_idx, live_pct


async def _news_render(symbol: str, market: str, event_at: datetime,
                       end_ms: int | None = None, tf: str = "1m",
                       before_ms: int | None = None,
                       label: str = "News",
                       marker_color: str | None = None) -> tuple[io.BytesIO, float] | None:
    """`_news_candles()`ning oddiy shamli grafik (`chart.news_chart()`)
    chizuvchi qatlami — News Trade AI (SEC), listing, likvidatsiya kabi
    barcha standart post turlari shuni ishlatadi. `tf`/`before_ms`/`label` —
    standart qiymatlarda ishlatadi (1m, 60 daqiqa oldin, "News");
    `marker_color` — likvidatsiya uchun long/short ustunligiga qarab
    RED/GREEN. Hajm portlashi (surge) esa PROFILLI grafik uchun
    `_news_candles()`ni TO'G'RIDAN-TO'G'RI chaqiradi (bu funksiyani
    chetlab o'tadi) — pastdagi `_process_surge_candidate()`ga qarang."""
    result = await _news_candles(symbol, market, event_at, end_ms=end_ms, tf=tf,
                                 before_ms=before_ms)
    if result is None:
        return None
    candles, news_idx, live_pct = result
    return chart.news_chart(candles, news_idx, symbol, live_pct, label=label,
                            marker_color=marker_color, tf=tf), live_pct


# `asyncio.create_task()` event loop'da faqat KUCHSIZ (weak) referens
# saqlaydi — qaytgan Task obyekti hech qayerda ushlab turilmasa, Python
# uni ISHLASH DAVOMIDA, hech qanday xatosiz, kutilmagan payt yig'ib
# tashlashi (garbage collect) mumkin. Aynan shu sabab jonli yangilanish
# "bitta xabar keldi-yu, keyin umuman yangilanmadi" holatiga tushgan —
# Railway qayta deploy qilinishi emas (bu ham bo'lishi mumkin, lekin
# alohida muammo). Rasmiy tavsiya: qaytgan Task'ni biror joyda kuchli
# referens sifatida saqlash. `_background_tasks` shu maqsadda — vazifa
# tugagach `add_done_callback` orqali o'zi to'plamdan chiqib ketadi.
_background_tasks: set[asyncio.Task] = set()


def _spawn_background(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# Butun kanal uchun UMUMIY tezlik cheklovi: bir nechta hodisa parallel
# jonli yangilansa ham, tahrirlashlar orasida kamida NEWS_MIN_EDIT_GAP
# oraliq saqlanadi — aks holda Telegram "flood control" bilan bloklab
# qo'yishi mumkin. Bitta hodisa yolg'iz bo'lsa amalda NEWS_REFRESH_SECONDS
# bilan yangilanadi (foydalanuvchi so'ragan 3-4s), bir nechtasi bo'lsa
# avtomatik ravishda ular orasida almashib-sekinlashadi.
_news_edit_lock = asyncio.Lock()
_news_last_edit = 0.0


async def _paced_media_edit(bot_, chat_id, message_id: int, photo: io.BytesIO,
                            reply_markup: InlineKeyboardMarkup | None = None,
                            caption: str | None = None) -> bool:
    global _news_last_edit
    async with _news_edit_lock:
        wait = _news_last_edit + config.NEWS_MIN_EDIT_GAP - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            # MUHIM: bu yerga tayyor InputFile emas, XOM BytesIO uzatiladi.
            # InputMediaPhoto o'zi ichida parse_file_input(..., attach=True)
            # chaqirib, faylni "attach://" havolasi bilan to'g'ri bog'laydi —
            # lekin FAQAT o'zi bytes/file obyektini o'rasa. Agar oldindan
            # InputFile() bilan o'ralgan bo'lsa, parse_file_input uni
            # o'zgarishsiz qaytaradi va `attach=True` HECH QACHON qo'llanmaydi
            # — natijada Telegram "Can't parse inputmedia: media not found"
            # deb rad etadi (send_photo'da muammo yo'q, chunki u butunlay
            # boshqa yo'l bilan yuklaydi).
            # MUHIM #2: `reply_markup` bermasak, Telegram edit_message_media
            # tugmalarni O'CHIRIB TASHLAYDI (editMessageCaption'dan farqli,
            # bu metodda mavjud klaviatura avtomatik saqlanmaydi) — shuning
            # uchun postdagi tugmalar har safar qayta uzatiladi.
            # MUHIM #3: xuddi shu sabab — `caption` ham `InputMediaPhoto`ning
            # O'ZIGA berilishi kerak, aks holda tagidagi matn (izoh)
            # HAR TAHRIRLASHDA O'CHIRILADI (edit_message_media butun media
            # obyektini — rasm+izoh — YANGISI bilan ALMASHTIRADI, eskisidan
            # HECH NARSA "meros" qilib olinmaydi).
            await bot_.edit_message_media(
                chat_id=chat_id, message_id=message_id,
                media=InputMediaPhoto(photo, filename="news.png",
                                      caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=reply_markup)
            ok = True
        except RetryAfter as e:
            log.info("News jonli yangilanish RetryAfter=%s", e.retry_after)
            await asyncio.sleep(e.retry_after)
            ok = False
        except BadRequest as e:
            # Narx (demak grafik) oxirgi tekshiruvdan beri o'zgarmagan
            # bo'lsa, yangi rasm avvalgisi bilan BAYT-BAYT bir xil chiqadi
            # — Telegram bunday "hech narsa o'zgarmagan" tahrirlashni
            # RAD ETADI. Bu xato emas, ko'rsatilgan tarkib ALLAQACHON
            # yangi — shuning uchun ogohlantirish/traceback bilan
            # loglarni to'ldirmasdan jimgina o'tkazib yuboriladi.
            if "message is not modified" in str(e).lower():
                ok = True
            else:
                log.warning("News xabari tahrirlanmadi (chat=%s msg=%s)",
                           chat_id, message_id, exc_info=True)
                ok = False
        except Exception:
            log.warning("News xabari tahrirlanmadi (chat=%s msg=%s)",
                       chat_id, message_id, exc_info=True)
            ok = False
        _news_last_edit = time.monotonic()
        return ok


# Avvalgi versiya: HAR HODISAGA bitta fon vazifasi (`_live_update`,
# `asyncio.sleep()` sikli bilan) — foydalanuvchi "deploy vaqtida jonli
# yangilanish to'xtab qolyapti, bot ham ishlamayabti" deb xabar berdi.
# Sabab: Railway deploy qilinganda konteyner qayta ishga tushadi — barcha
# XOTIRADAGI fon vazifalari (shu jumladan bu davomida yasalgan
# `_background_tasks`dagi kuchli referenslar ham) YO'QOLADI, chunki
# butun jarayon o'zi qayta boshlanadi.
#
# Yechim: `poll_job`/`tracker.run_once()` signal-kuzatuvi qanday ishlasa
# xuddi shunday — HECH QANDAY holat xotirada saqlanmaydi, hammasi
# `news_events` jadvalida (`caption`/`render_*` ustunlari). Bitta umumiy
# `job_queue` vazifasi (`news_live_job`) har safar bazadan "hali jonli
# oynasi tugamagan" hodisalarni qayta o'qib yangilaydi — konteyner qayta
# ishga tushsa ham, yangi konteyner shunchaki keyingi tikda xuddi shu
# so'rovni bazadan qayta qiladi va DAVOM ETADI (hech narsa yo'qolmaydi).

async def news_live_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    now = datetime.now(timezone.utc)
    try:
        rows = await db.active_live_events(config.NEWS_LIVE_MINUTES)
    except Exception:
        log.exception("Jonli hodisalar ro'yxati olinmadi")
        return

    for row in rows:
        # Hajm portlashi (surge) uchun bir marta (post vaqtida) hisoblangan
        # Volume/Volume Delta profili bo'lsa — QAYTA SO'RALMAYDI (MEXC
        # tezlik chegarasiga xavf), bazadan o'qilib qayta ishlatiladi,
        # faqat shamlar/narx yangilanadi.
        profile = None
        if row["profile_data"]:
            try:
                profile = json.loads(row["profile_data"])
            except (TypeError, ValueError):
                log.warning("profile_data o'qib bo'lmadi (%s)", row["symbol"], exc_info=True)
                profile = None

        try:
            if profile:
                result = await _news_candles(
                    row["symbol"], row["market"], row["event_at"],
                    tf=row["render_tf"] or "1d", before_ms=row["render_before_ms"])
                if result is None:
                    continue
                candles, news_idx, live_pct = result
                photo = chart.surge_profile_chart(
                    candles, news_idx, row["symbol"], live_pct,
                    profile["vol_bins"], profile["delta_bins"],
                    profile["bin_lo"], profile["bin_size"],
                    label=row["render_label"] or "Portlash", tf=row["render_tf"])
            else:
                rendered = await _news_render(
                    row["symbol"], row["market"], row["event_at"],
                    tf=row["render_tf"] or "1m", before_ms=row["render_before_ms"],
                    label=row["render_label"] or "News",
                    marker_color=row["render_marker_color"])
                if rendered is None:
                    continue
                photo, live_pct = rendered
        except Exception:
            log.warning("Jonli grafik yasalmadi (%s)", row["symbol"], exc_info=True)
            continue

        buttons = await _signal_buttons(row["symbol"], row["market"], ctx.bot.username)
        kb_rows = list(buttons.inline_keyboard) if buttons else []
        kb_rows.append([_share_button(row["message_id"])])
        buttons = InlineKeyboardMarkup(kb_rows)

        await _paced_media_edit(ctx.bot, config.NEWS_CHANNEL_ID, row["message_id"],
                                photo, buttons, row["caption"])

        deadline = row["event_at"] + timedelta(minutes=config.NEWS_LIVE_MINUTES)
        if now >= deadline:
            await db.finalize_news_outcome(row["id"], live_pct)


async def news_scan_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    # Har bir manba ALOHIDA try/except ichida — bittasi vaqtincha ishlamay
    # qolsa (masalan SEC EDGAR javob bermasa) ikkinchisi (Upbit) baribir
    # ishlashda davom etadi, va aksincha.
    items: list[dict] = []
    try:
        items += await news.sec_scan(since)
    except Exception:
        log.exception("SEC skaneri xato")
    try:
        items += await listings.upbit_scan(since)
    except Exception:
        log.exception("Upbit skaneri xato")

    for item in items:
        if await db.news_event_exists(item["external_key"]):
            continue
        try:
            await _process_news_event(ctx, item)
        except Exception:
            log.exception("Yangilik ishlanmadi (%s)", item.get("external_key"))


# ─────────────────────────── Yirik birjalarning yangi listinglari ───────────────────────────
# `listings.exchange_listing_scan()` orqali (cryptocurrencyalerting.com'ning
# haqiqiy JSON API'si, foydalanuvchi topib berdi — avval faqat Binance uchun
# tasdiqlangan, keyin "coinbase va kreken ham shu sayt orqali olish imkoni
# bormi?" so'ralgach, saytning bir xil naqshiga tayanib Coinbase/Kraken ham
# qo'shildi — bular HALI production'da alohida tasdiqlanmagan). AI
# ISHLATILMAYDI — MarketTwits qanday AI'siz bo'lsa xuddi shunday: ma'lumot
# allaqachon tuzilgan (tiker/nom/vaqt), "muhimmi-yo'qmi" filtri kerak emas
# (yangi listing o'zi allaqachon signal), tarjima ham shart emas (shablon
# matn yetarli). Shu sabab `_process_news_event()`dan MUSTAQIL, alohida
# ishlanadi.

EXCHANGE_LISTING_SCANNERS = {
    "Binance": listings.binance_scan,
}


async def _process_exchange_listing(bot_, item: dict) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    external_key = item["external_key"]
    if await db.news_event_exists(external_key):
        return

    exchange_name, code, name = item["exchange"], item["code"], item["name"]
    symbol, market = await _resolve_news_symbol(code)

    headline = f"{name} ({code}) {exchange_name}'da yangi ro'yxatga olindi"
    eid = await db.insert_news_event(
        source=f"{exchange_name.lower()}_listing", external_key=external_key,
        symbol=symbol, market=market, headline_en=headline,
        translation_uz=None, insight_uz=None,
        event_at=item["event_at"], posted=False)
    if eid is None:
        return   # boshqa parallel chaqiruv bu hodisani bizdan oldin yozgan

    title = symbol or code
    caption = (f"🆕 <b>{html.escape(title, quote=False)}</b>\n\n"
              f"{html.escape(name, quote=False)} ({html.escape(code, quote=False)}) "
              f"{html.escape(exchange_name, quote=False)}'da yangi ro'yxatga olindi.")

    # Yangi listing ko'pincha bizning kuzatuvimizdagi birjada (MEXC)
    # HALI yo'q — shunda symbol=None, matn-only post (grafiksiz).
    photo = None
    if symbol:
        try:
            rendered = await _news_render(symbol, market, item["event_at"])
        except Exception:
            log.warning("%s listing grafigi yasalmadi (%s)", exchange_name, symbol, exc_info=True)
            rendered = None
        if rendered:
            photo, _ = rendered

    buttons = await _signal_buttons(symbol, market, bot_.username) if symbol else None
    try:
        if photo:
            sent = await bot_.send_photo(
                config.NEWS_CHANNEL_ID, InputFile(photo, "news.png"),
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            sent = await bot_.send_message(
                config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True, reply_markup=buttons)
    except Exception:
        log.exception("%s listing postlanmadi (%s)", exchange_name, external_key)
        return
    # Faqat grafikli xabar jonli yangilanadi (`render_tf` to'ldirilgan bo'lsa
    # `news_live_job` uni "aktiv" deb topadi va o'zi davriy yangilab turadi —
    # bu yerda alohida fon vazifasi YARATILMAYDI, restart-chidamli DB-asosli
    # mexanizm, `_process_news_event()` bilan bir xil andoza).
    await db.set_news_message(
        eid, sent.message_id, caption,
        render_tf="1m" if (photo and symbol) else None,
        render_label="Listing" if (photo and symbol) else None)
    await _add_share_button(bot_, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


async def binance_listing_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    # Har bir birja ALOHIDA try/except ichida — Coinbase/Kraken
    # endpoint'lari (hali tasdiqlanmagan taxmin) ishlamasa ham, Binance
    # (tasdiqlangan) baribir ishlashda davom etadi.
    items: list[dict] = []
    for exchange_name, scanner in EXCHANGE_LISTING_SCANNERS.items():
        try:
            items += await scanner(since)
        except Exception:
            log.exception("%s listing skaneri xato", exchange_name)
    for item in items:
        try:
            await _process_exchange_listing(ctx.bot, item)
        except Exception:
            log.exception("Listing ishlanmadi (%s)", item.get("external_key"))


# ─────────────────────────── MarketTwits (Telegram userbot) ───────────────────────────
# `tgsource.py` orqali — SEC/Upbit kabi PULL emas, real-vaqtli PUSH manba
# (Telethon userbot yangi xabarni darhol yetkazadi).
#
# AI ISHLATILMAYDI (Anthropic kredit tugagach, foydalanuvchi so'ragan
# arzon/bepul muqobil): filtr o'rniga MarketTwits o'zi deyarli har bir
# postga qo'yadigan #HASHTAG'lardan foydalaniladi — har bir hashtag
# `_resolve_news_symbol()` bilan (xuddi shu funksiya, avval AI symbol_hint
# uchun ishlatilgan) sinaladi; birinchi RESOLVE bo'ladigan tiker "bu post
# savdo-tegishli" mezoni sifatida ishlatiladi. Tikersiz hashtag (masalan
# #geopolitika) ham `db.market_hashtags` orqali admin panelda qo'shilsa —
# grafiksiz, matn-only post qilinadi (chunki chizadigan tiker yo'q).
# Tarjima — AI'siz, `translate.py` (MyMemory, bepul/kalitsiz) orqali.
# Faqat matnda KIRILL harflar bo'lsa tarjima qilinadi (kanal aralash —
# ba'zan inglizcha/o'zbekcha postlar ham bo'ladi, ularni "ru->uz" juftligi
# orqali qayta tarjima qilish natijani buzardi). Bu SEC/Upbit quvuridan
# (`_process_news_event`, AI tahlilga bog'liq) butunlay MUSTAQIL — ular
# hali ham AI kerak, faqat MarketTwits AI'siz.
_HASHTAG_RE = re.compile(r"#(\w+)")
_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")


async def _markettwits_symbol(text: str) -> tuple[str | None, str | None]:
    """Faqat BIRINCHI hashtag tekshiriladi — MarketTwits doim asosiy
    tikerni birinchi qo'yadi, keyingilari mavzu-teglar (masalan
    "#hisobot", "#geopolitika"). Avval HAMMA hashtagni ketma-ket sinash
    xato chiqargan edi: birinchi tiker (masalan "#BE" — Bloom Energy)
    vaqtinchalik xato (Twelve Data tezlik chegarasi) sabab RESOLVE
    bo'lmay qolsa, ikkinchi, ALOQASIZ hashtag ("#cot") tasodifan boshqa
    (kripto) tikerga to'g'ri kelib, NOTO'G'RI grafik chizilardi
    (foydalanuvchi production'da tasdiqladi: "COTUSDT" chiqqan, aslida
    Bloom Energy haqida edi). Endi mos kelmasa — post umuman
    qilinmaydi, noto'g'ri grafik chizilishidan ko'ra shu yaxshiroq."""
    tags = _HASHTAG_RE.findall(text)
    if not tags:
        return None, None
    return await _resolve_news_symbol(tags[0])


async def _markettwits_matches_topic(text: str) -> bool:
    """Tikerga bog'liq bo'lmagan, lekin admin panelda "muhim" deb
    belgilangan #hashtaglardan biri postda bormi (masalan #geopolitika)."""
    tags = {t.lower() for t in _HASHTAG_RE.findall(text)}
    if not tags:
        return False
    curated = await db.list_market_hashtags()
    return any(c.lower() in tags for c in curated)


async def _process_markettwits_message(bot_, channel: str, msg_id: int,
                                       text: str, event_at: datetime) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    if event_at.tzinfo is None:
        event_at = event_at.replace(tzinfo=timezone.utc)
    external_key = f"markettwits:{channel}:{msg_id}"
    if await db.news_event_exists(external_key):
        return

    if "🇷🇺" in text:
        # Foydalanuvchi: "Rossiya bayrog'i bor xabarlar kelmasin" — Rossiya
        # iqtisodiyoti bilan bog'liq postlar butunlay o'tkazib yuboriladi
        # (tiker/hashtag mos kelsa ham — masalan "#T" MOEX'dagi rus
        # kompaniyasi bo'lsa ham, tasodifan AT&T (NYSE: T)ga o'xshab
        # RESOLVE bo'lib qolgan holatlar shu bilan ham oldi olinadi).
        await db.insert_news_event(
            source="markettwits", external_key=external_key, symbol=None, market=None,
            headline_en=text[:2000], translation_uz=None, insight_uz=None,
            event_at=event_at, posted=True)
        return

    symbol, market = await _markettwits_symbol(text)
    if not symbol and not await _markettwits_matches_topic(text):
        # Tanish (RESOLVE bo'ladigan) hashtag YO'Q va admin belgilagan
        # qo'shimcha #hashtaglardan biri ham YO'Q — bu bizning AI'siz
        # filtr: faqat shu ikkisidan biriga mos postlar o'tadi.
        await db.insert_news_event(
            source="markettwits", external_key=external_key, symbol=None, market=None,
            headline_en=text[:2000], translation_uz=None, insight_uz=None,
            event_at=event_at, posted=True)
        return

    # Hashtaglar matndan ajratib olinadi — ikki sabab: (1) TARJIMA
    # QILINMAYDI, birga tarjima qilinsa (masalan "#новости" so'z bilan
    # aralashib) natija chalkash chiqardi (foydalanuvchi tasdiqladi:
    # "#xabar berish" kabi noto'g'ri chiqqan); (2) captionga UMUMAN
    # QAYTARILMAYDI — sarlavhada aktiv nomi (masalan "BTCUSDT") allaqachon
    # ko'rinadi, hashtaglar shunchaki ortiqcha/qatorni to'ldirar edi
    # (foydalanuvchi: "hashtaglar ham bor ko'payib ketyabti").
    body = _HASHTAG_RE.sub("", text).strip()
    display_body = body
    if _CYRILLIC_RE.search(body):
        translated = await translate.to_uz(body)
        if translated:
            display_body = translated

    eid = await db.insert_news_event(
        source="markettwits", external_key=external_key, symbol=symbol, market=market,
        headline_en=text[:2000],
        translation_uz=display_body[:2000] if display_body != body else None,
        insight_uz=None, event_at=event_at, posted=False)
    if eid is None:
        return   # boshqa parallel chaqiruv bu hodisani bizdan oldin yozgan

    title = symbol or "MarketTwits"
    # `quote=False` — Telegram HTML rejimida bu oddiy matn (atribut emas),
    # standart `html.escape()` esa '/" belgilarni ham `&#x27;`/`&quot;`ga
    # aylantirardi — Telegram buni ORQAGA parafrazamaydi (xuddi `&#10;`
    # xatosi kabi, foydalanuvchi production'da tasdiqladi), xom holda
    # ko'rinib qolardi.
    caption = (f"📰 <b>{html.escape(title, quote=False)}</b>\n\n"
              f"{html.escape(display_body[:1000], quote=False)}")

    # Tiker topilmasa (faqat mavzu-hashtag orqali o'tgan bo'lsa) chizadigan
    # narsa yo'q — matn-only post, jonli yangilanishsiz (narx kuzatilmaydi).
    photo, live_pct = None, None
    if symbol:
        try:
            rendered = await _news_render(symbol, market, event_at)
        except Exception:
            log.warning("MarketTwits grafigi yasalmadi (%s)", symbol, exc_info=True)
            rendered = None
        if rendered:
            photo, live_pct = rendered

    buttons = await _signal_buttons(symbol, market, bot_.username) if symbol else None
    try:
        if photo:
            sent = await bot_.send_photo(
                config.NEWS_CHANNEL_ID, InputFile(photo, "news.png"),
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            sent = await bot_.send_message(
                config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True, reply_markup=buttons)
    except Exception:
        log.exception("MarketTwits postlanmadi (%s)", external_key)
        return
    await db.set_news_message(
        eid, sent.message_id, caption,
        render_tf="1m" if (photo and symbol) else None,
        render_label="News" if (photo and symbol) else None)
    await _add_share_button(bot_, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


_markettwits_started = False


async def _start_markettwits_listener(bot_) -> None:
    """Login qilingan bo'lsa (`/tg_login` orqali) tinglovchini fon
    vazifasi sifatida ishga tushiradi. Idempotent — ikki marta
    chaqirilsa (masalan `/tg_code` muvaffaqiyatli bo'lgach QAYTA
    chaqirilganda) ikkinchi marta hech narsa qilmaydi."""
    global _markettwits_started
    if _markettwits_started or not tgsource.enabled():
        return
    if not await tgsource.is_authorized():
        return
    _markettwits_started = True
    _spawn_background(tgsource.start_listener(
        lambda ch, mid, text, dt: _process_markettwits_message(bot_, ch, mid, text, dt)))


# ─────────────────────────── Iqtisodiy taqvim ───────────────────────────
# Har kuni `ECON_DIGEST_HOUR`da AQSH makro yangiliklari ro'yxati, har bir
# hodisadan `ECON_REMIND_MINUTES` oldin eslatma. Xuddi News Trade AI kabi
# NEWS_CHANNEL_ID kanaliga postlanadi.

# Manba (Forex Factory) kuniga bir necha marta so'raladigan darajada
# tez-tez o'zgarmaydi (haftalik jadval), shuning uchun natija bir muddat
# keshlanadi — bu ham manbaning o'zi qo'ygan tezlik chegarasini
# hurmat qiladi (5 daqiqada 2 so'rov), ham har 60 soniyalik `econ_job`
# tsiklida bekorga tarmoqqa chiqmaydi.
_econ_cache: list[dict] = []
_econ_cache_at = 0.0
_econ_cache_ok = True
ECON_CACHE_TTL = 1800          # 30 daqiqa — MUVAFFAQIYATLI yangilanishdan keyin
# Manba vaqti-vaqti bilan 429 (tezlik chegarasi) qaytarishi mumkin (Railway'ning
# umumiy IP hududi sababli, boshqa bepul manbalarda ham ko'rilgan — CLAUDE.md
# #107ga qarang). Bunday holatda TO'LIQ 30 daqiqa kutish xavfli: aynan
# "actual" natija chiqqan payt shu muvaffaqiyatsiz tsiklga to'g'ri kelib
# qolsa, keyingi tekshiruv yarim soatgacha kechikardi. Shu sabab
# muvaffaqiyatsizlikdan keyin ANCHA qisqaroq (5 daqiqa) kutib qayta uriniladi.
ECON_CACHE_RETRY_TTL = 300     # 5 daqiqa — MUVAFFAQIYATSIZLIKDAN keyin


async def _econ_events_cached() -> list[dict]:
    global _econ_cache, _econ_cache_at, _econ_cache_ok
    ttl = ECON_CACHE_TTL if _econ_cache_ok else ECON_CACHE_RETRY_TTL
    if time.monotonic() - _econ_cache_at > ttl:
        fresh = await econcalendar.fetch_week()
        _econ_cache_ok = bool(fresh)
        if fresh:
            _econ_cache = fresh
        # Bo'sh javob ESKI keshni O'CHIRMAYDI — manba vaqtincha ishlamay
        # qolsa ham eslatmalar butunlay yo'qolib qolmasin.
        _econ_cache_at = time.monotonic()
    return _econ_cache


def _flag_country(code: str) -> str:
    return "🇺🇸" if code == "USD" else code


def _econ_digest_text(events: list[dict], now_local: datetime) -> str:
    off_h = int(now_local.utcoffset().total_seconds() // 3600)
    head = (f"📅 <b>Iqtisodiy taqvim {now_local:%d.%m.%Y}</b>\n"
            f"Hozirgi vaqt: {now_local:%H:%M} (GMT{off_h:+d})\n")
    if not events:
        return head + "\nBugun AQSH bo'yicha muhim iqtisodiy yangilik yo'q."
    lines = [head]
    for e in sorted(events, key=lambda e: e["when"]):
        t = e["when"].astimezone(stats.TZ)
        lines.append(f"\n{t:%H:%M}: {_flag_country('USD')} {html.escape(e['title'])}")
    return "".join(lines)


def _econ_remind_text(group: list[dict]) -> str:
    lines = [f"⏰ <b>Diqqat, {config.ECON_REMIND_MINUTES} daqiqa keyin:</b>"]
    for e in group:
        lines.append(f"{_flag_country('USD')} {html.escape(e['title'])}")
    return "\n".join(lines)


async def econ_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    events = await _econ_events_cached()
    now = datetime.now(timezone.utc)
    now_local = now.astimezone(stats.TZ)

    # 1) Kunlik ro'yxat — soat ECON_DIGEST_HOUR bo'lgan har bir tekshiruvda
    # urinadi, lekin `econ_mark_sent` bir kunda faqat BIRINCHISIGA ruxsat
    # beradi (digest_job'dagi digest_hour/digest_last andozasi bilan bir xil).
    today_key = now_local.strftime("%Y-%m-%d")
    if now_local.hour == config.ECON_DIGEST_HOUR and not await db.econ_sent("digest", today_key):
        # Kunni AVVAL belgilaymiz — yuborish yiqilsa ham keyingi tsiklda
        # qayta urinib kanalni ikki marta bezovta qilmasin.
        await db.econ_mark_sent("digest", today_key)
        todays = [e for e in events if e["when"].astimezone(stats.TZ).date() == now_local.date()]
        try:
            await ctx.bot.send_message(
                config.NEWS_CHANNEL_ID, _econ_digest_text(todays, now_local),
                parse_mode=ParseMode.HTML)
        except Exception:
            log.exception("Iqtisodiy taqvim digest yuborilmadi")

    # 2) Eslatmalar — bir xil vaqtdagi hodisalar BITTA xabarda birlashadi
    # (masalan ikkita PMI bir vaqtda chiqsa, ikkita alohida xabar emas).
    due: dict[datetime, list[dict]] = {}
    for e in events:
        delta = (e["when"] - now).total_seconds()
        if 0 <= delta <= config.ECON_REMIND_MINUTES * 60:
            due.setdefault(e["when"], []).append(e)

    for when, group in due.items():
        key = when.isoformat()
        if await db.econ_sent("reminder", key):
            continue
        await db.econ_mark_sent("reminder", key)
        try:
            await ctx.bot.send_message(
                config.NEWS_CHANNEL_ID, _econ_remind_text(group),
                parse_mode=ParseMode.HTML)
        except Exception:
            log.exception("Iqtisodiy taqvim eslatmasi yuborilmadi")

    # 3) Natijalar — hodisa allaqachon chiqqan (`actual` to'ldirilgan) bo'lsa,
    # Claude orqali batafsil o'zbekcha xabar yasab, BTC grafigi bilan
    # postlanadi (keyin `news_live_job` uni avtomatik jonli yangilaydi —
    # xuddi SEC/surge hodisalari kabi, alohida infratuzilma shart emas).
    # Bir xil vaqtda chiqqan ko'rsatkichlar (masalan oylik+yillik PCE)
    # BITTA xabarda birlashadi.
    result_due: dict[datetime, list[dict]] = {}
    for e in events:
        if not e.get("actual"):
            continue
        age = (now - e["when"]).total_seconds()
        if 0 <= age <= config.ECON_RESULT_LOOKBACK_MINUTES * 60:
            result_due.setdefault(e["when"], []).append(e)

    for when, group in result_due.items():
        key = when.isoformat()
        if await db.econ_sent("result", key):
            continue
        # Bu guruh QAYTA baholanmasligi uchun AVVAL belgilaymiz — Claude
        # chaqiruvi/post muvaffaqiyatsiz bo'lsa ham, keyingi tsiklda
        # bekorga qayta urinilmaydi (natija o'zgarmaydi).
        await db.econ_mark_sent("result", key)
        try:
            analysis = await newsai.econ_result(group)
        except Exception:
            log.exception("Iqtisodiy natija tahlili xato")
            continue
        if not analysis or not analysis.get("is_market_moving") or not analysis.get("message_uz"):
            # Nima uchun postlanmagani keyinchalik loglardan aniq bo'lishi
            # uchun (masalan foydalanuvchi "natija kelmadi" deb so'rasa) —
            # Claude ATAYLAB "kam ta'sirli" deb topgan bo'lishi mumkin,
            # bu XATO emas.
            log.info("Iqtisodiy natija postlanmadi (kam ta'sirli yoki tahlil "
                    "muvaffaqiyatsiz): %s", ", ".join(e["title"] for e in group))
            continue

        external_key = f"econ:{key}"
        eid = await db.insert_news_event(
            source="econ", external_key=external_key, symbol="BTCUSDT",
            market="crypto", headline_en="; ".join(e["title"] for e in group),
            translation_uz=analysis["message_uz"], insight_uz=None,
            event_at=when, posted=False)
        if eid is None:
            continue

        caption = html.escape(analysis["message_uz"])
        try:
            rendered = await _news_render("BTCUSDT", "crypto", when, label="BTC")
        except Exception:
            log.warning("Iqtisodiy natija grafigi yasalmadi", exc_info=True)
            rendered = None
        photo = rendered[0] if rendered else None

        buttons = await _signal_buttons("BTCUSDT", "crypto", ctx.bot.username)
        try:
            if photo:
                sent = await ctx.bot.send_photo(
                    config.NEWS_CHANNEL_ID, InputFile(photo, "econ.png"),
                    caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
            else:
                sent = await ctx.bot.send_message(
                    config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                    reply_markup=buttons)
        except Exception:
            log.exception("Iqtisodiy natija kanalga postlanmadi (%s)", external_key)
            continue
        await db.set_news_message(
            eid, sent.message_id, caption,
            render_tf="1m" if photo else None,
            render_label="BTC" if photo else None)
        await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


# ─────────────────────────── Hajm portlashi (surge) ───────────────────────────
# Uzoq muddat pasaygan, keyin savdo hajmi keskin oshgan tangalarni topib,
# CryptoPanic'dan sababini qidiradi va NEWS_CHANNEL_ID kanaliga postlaydi.
# Ikki alohida job: `volume_snapshot_job` faqat bazaga hajm yozib boradi
# (tarix to'planishi uchun — bot yangi ishga tushgan bo'lsa dastlabki
# kun-ikki kunda hech narsa aniqlanmaydi, bu KUTILGAN holat), `surge_scan_job`
# esa shu tarixdan nomzod qidiradi.

async def volume_snapshot_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    try:
        volumes = await exchange.volume_ticker_24hr()
    except Exception:
        log.exception("Hajm suratini olishda xato")
        return
    try:
        await db.insert_volume_snapshots(list(volumes.items()))
    except Exception:
        log.exception("Hajm surati bazaga yozilmadi")


async def _process_surge_candidate(ctx: ContextTypes.DEFAULT_TYPE, symbol: str,
                                   latest_vol: float, avg_vol: float) -> None:
    """Bitta nomzodni tekshiradi: uzoq muddatli pasayish TASDIQLANMASA
    (masalan bu shunchaki davom etayotgan o'sish, pasayish emas) —
    hech narsa qilinmaydi, dedup yozuvi ham qo'yilmaydi (keyingi
    siklda, yangi hajm ma'lumoti bilan qayta tekshirilishi mumkin)."""
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    start_ms = now_ms - config.SURGE_DECLINE_DAYS * 86_400_000
    daily = await exchange.klines(symbol, start_ms, limit=config.SURGE_DECLINE_DAYS + 5, tf="1d")
    if len(daily) < 5:
        return   # yetarli tarix yo'q (yangi listing va h.k.) — baholab bo'lmaydi
    decline_pct = (daily[-1].close - daily[0].close) / daily[0].close * 100
    if decline_pct > -config.SURGE_DECLINE_PCT:
        return   # uzoq muddatli pasayish tasdiqlanmadi

    # Dedup — kuniga bitta tanga uchun bitta post (`news_events.external_key`
    # UNIQUE cheklovi orqali, xuddi SEC hodisalaridagi kabi).
    ratio = latest_vol / avg_vol if avg_vol else 0.0
    external_key = f"surge:{symbol}:{now:%Y-%m-%d}"
    headline = (f"{symbol}: {config.SURGE_DECLINE_DAYS} kunlik pasayishdan "
               f"keyin hajm {ratio:.1f}x oshdi")
    eid = await db.insert_news_event(
        source="surge", external_key=external_key, symbol=symbol, market="crypto",
        headline_en=headline, translation_uz=None, insight_uz=None,
        event_at=now, posted=False)
    if eid is None:
        return   # bugun bu tanga uchun allaqachon post qilingan

    ticker = symbol[:-len(config.QUOTE)] if symbol.endswith(config.QUOTE) else symbol
    try:
        news_items = await cryptonews.search(ticker)
    except Exception:
        log.warning("CryptoPanic qidiruvi xato (%s)", ticker, exc_info=True)
        news_items = []

    lines = [f"🚀 <b>{html.escape(symbol)}</b> — savdo hajmi keskin oshdi",
            f"\n{config.SURGE_DECLINE_DAYS} kunlik narx: <b>{decline_pct:+.1f}%</b>",
            f"\nHajm: o'rtachadan <b>{ratio:.1f}x</b> ko'p"]
    if news_items:
        lines.append("\n\n📰 Bog'liq yangiliklar:")
        for item in news_items[:3]:
            title = html.escape(item["title"] or ticker)
            url = html.escape(item["url"] or "")
            lines.append(f"\n• <a href=\"{url}\">{title}</a>" if url else f"\n• {title}")
    else:
        lines.append("\n\n<i>Aniq sabab topilmadi — bozor spekulyatsiyasi bo'lishi mumkin.</i>")
    caption = "".join(lines)

    # Grafik: kunlik shamlar, `SURGE_DECLINE_DAYS` (matn ham shu son bilan
    # "N kunlik pasayish" deydi — grafik oynasi endi shu bilan MOS) davri
    # to'liq ko'rinadi, oxirgi sham "Portlash" nuqtasi bilan belgilanadi.
    # Foydalanuvchi so'rovi (Hyblock Capital veb-sahifasi uslubi) bilan
    # endi HAQIQIY MEXC savdolaridan Volume/Volume Delta panellari ham
    # qo'shiladi — faqat BIR MARTA (post vaqtida) hisoblanadi va bazaga
    # saqlanadi (`db.set_news_profile`), jonli yangilanish uni QAYTA
    # SO'RAMASDAN qayta ishlatadi (`news_live_job`ga qarang) — MEXC
    # tezlik chegarasiga xavf tug'dirmasligi uchun.
    photo, live_pct = None, None
    profile_bins: tuple[list[float], list[float], float, float] | None = None
    surge_before_ms = config.SURGE_DECLINE_DAYS * 86_400_000
    try:
        result = await _news_candles(symbol, "crypto", now, tf="1d", before_ms=surge_before_ms)
    except Exception:
        log.warning("Hajm portlashi grafigi yasalmadi (%s)", symbol, exc_info=True)
        result = None
    if result:
        candles, news_idx, live_pct = result
        p_lo = min(c.low for c in candles)
        p_hi = max(c.high for c in candles)
        delta_result = None
        try:
            delta_result = await exchange.volume_delta_profile(
                symbol, now_ms - chart.DELTA_WINDOW_MS, now_ms, p_lo, p_hi,
                n_bins=chart.DELTA_BINS)
        except Exception:
            log.warning("Portlash uchun volume delta profili olinmadi (%s)", symbol, exc_info=True)
        if delta_result:
            vol_bins, delta_bins = delta_result
            bin_size = (p_hi - p_lo) / chart.DELTA_BINS
            profile_bins = (vol_bins, delta_bins, p_lo, bin_size)
            photo = chart.surge_profile_chart(candles, news_idx, symbol, live_pct,
                                              vol_bins, delta_bins, p_lo, bin_size,
                                              label="Portlash", tf="1d")
        else:
            photo = chart.news_chart(candles, news_idx, symbol, live_pct,
                                     label="Portlash", tf="1d")

    buttons = await _signal_buttons(symbol, "crypto", ctx.bot.username)
    try:
        if photo:
            sent = await ctx.bot.send_photo(
                config.NEWS_CHANNEL_ID, InputFile(photo, "surge.png"),
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            sent = await ctx.bot.send_message(
                config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True, reply_markup=buttons)
    except Exception:
        log.exception("Hajm portlashi postlanmadi (%s)", symbol)
        return
    await db.set_news_message(
        eid, sent.message_id, caption,
        render_tf="1d" if photo else None,
        render_before_ms=surge_before_ms if photo else None,
        render_label="Portlash" if photo else None)
    if profile_bins:
        await db.set_news_profile(eid, *profile_bins)
    await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


# ─────────────────────────── MACD kesishmasi ───────────────────────────
# Foydalanuvchi so'rovi (Bulltard.com kanali namunasi: "$CATI/USDT (1d)
# MACD Bearish crossover, Last price: 0.05176" + sham grafigi va MACD
# paneli): top hajmli juftliklarda MACD(12,26,9) chizig'i signal
# chizig'ini kesib o'tsa — grafik bilan alohida xabar.
#
# TEZLIK CHEGARASI bo'yicha asosiy qaror: 4h shami har 4 soatda, 1d shami
# kuniga bir marta YOPILADI. Yopilmagan sham bo'yicha qayta-qayta
# skanerlash 250 ta juftlikka yuzlab keraksiz so'rov degani. Shu sabab
# job tez-tez uyg'onadi, lekin har timeframe uchun OXIRGI SKANERLANGAN
# sham chegarasi (`bot_settings`da) saqlanadi — yangi sham yopilmagan
# bo'lsa job HECH QANDAY so'rov yubormasdan darhol qaytadi.

def _last_closed_open_ms(tf: str, now_ms: int) -> int:
    """Shu paytda TO'LIQ YOPILGAN oxirgi shamning ochilish vaqti.
    Hali shakllanayotgan (joriy) sham ATAYLAB hisobga olinmaydi — uning
    low/high/close'i hali yakuniy emas, MACD ham o'zgarib turadi (bu
    signal #134'dagi bilan bir xil tamoyil)."""
    step = chart.TF_MINUTES[tf] * 60_000
    return (now_ms // step) * step - step


async def _macd_symbols() -> list[str]:
    """Skanerlanadigan juftliklar — 24 soatlik hajmi bo'yicha yuqoridan
    `MACD_MAX_SYMBOLS` tagacha, `MACD_MIN_VOLUME_USD` chegarasidan
    yuqorilari. Hajm surati BITTA so'rovda olinadi."""
    vols = await exchange.volume_ticker_24hr()
    rows = [(s, v) for s, v in vols.items()
            if s.endswith(config.QUOTE) and v >= config.MACD_MIN_VOLUME_USD]
    rows.sort(key=lambda r: r[1], reverse=True)
    # Diagnostika: birinchi ishga tushirishda kutilganidan (200) ANCHA kam
    # (12 ta) juftlik chiqdi — manba ma'lumoti qanaqaligini ko'rish uchun.
    top = ", ".join(f"{s}={v/1e6:.1f}M" for s, v in rows[:5])
    log.info("MACD juftliklari: ticker %d ta qaytardi, %.0fM$ chegarasidan "
              "%d tasi o'tdi (eng yiriklari: %s)",
              len(vols), config.MACD_MIN_VOLUME_USD / 1e6, len(rows), top or "—")
    return [s for s, _ in rows[:config.MACD_MAX_SYMBOLS]]


async def _macd_check_symbol(symbol: str, tf: str, expected_open_ms: int):
    """Bitta juftlik/timeframe — kesishma bo'lsa ma'lumot qaytaradi.

    `expected_open_ms` — kutilayotgan OXIRGI YOPILGAN sham. Birjadan
    kelgan oxirgi sham undan boshqa bo'lsa (masalan hali yopilmagan
    sham qaytgan, yoki juftlikda savdo bo'lmagan) — bu juftlik jimgina
    o'tkazib yuboriladi."""
    step = chart.TF_MINUTES[tf] * 60_000
    start_ms = expected_open_ms - step * (config.MACD_CANDLES - 1)
    candles = await exchange.klines(symbol, start_ms, limit=config.MACD_CANDLES,
                                     tf=tf, end_ms=expected_open_ms + step - 1)
    # Hali yopilmagan shamlar tashlab yuboriladi (#134 tamoyili).
    candles = [c for c in candles if c.open_ms <= expected_open_ms]
    if len(candles) < 40 or candles[-1].open_ms != expected_open_ms:
        return None

    closes = [c.close for c in candles]
    line, sig, hist = indicators.macd(closes)
    direction = indicators.crossover(line, sig, -1)
    if not direction:
        return None
    strong = indicators.is_strong(line, sig, hist, direction, -1)
    if config.MACD_ONLY_STRONG and not strong:
        return None
    return {"symbol": symbol, "tf": tf, "direction": direction, "strong": strong,
            "candles": candles, "line": line, "sig": sig, "hist": hist,
            "open_ms": expected_open_ms, "price": candles[-1].close}


async def _post_macd_alert(ctx: ContextTypes.DEFAULT_TYPE, hit: dict) -> None:
    symbol, tf = hit["symbol"], hit["tf"]
    # Dedup ATOMAR: xabar yuborishdan OLDIN band qilinadi — aks holda
    # deploy paytida ikkita jarayon ustma-ust kelsa bir xil xabar ikki
    # marta ketishi mumkin edi.
    if not await db.claim_macd_alert(symbol, tf, hit["open_ms"], hit["direction"]):
        return

    # To'rt ko'rinish — kuchli (super) kesishmalar ALOHIDA ajralib tursin
    # (foydalanuvchi namunasi: "Super bearish crossover 💀" / "Super
    # bullish crossover 🔥", oddiylari esa belgisiz). Oddiy kesishmalarda
    # 🟢/🔴 qoladi — yo'nalish bir qarashda ko'rinishi uchun.
    bullish = hit["direction"] == "bullish"
    if hit["strong"]:
        arrow = "🔥" if bullish else "💀"
        kind = "Super bullish" if bullish else "Super bearish"
    else:
        arrow = "🟢" if bullish else "🔴"
        kind = "Bullish" if bullish else "Bearish"
    caption = (f"{arrow} <b>{html.escape(symbol)}</b> ({tf}) — MACD {kind} crossover\n"
               f"Joriy narx: <b>{fmt_price(hit['price'])}</b>")

    photo = None
    try:
        photo = chart.macd_chart(hit["candles"], symbol, tf, hit["direction"],
                                 hit["line"], hit["sig"], hit["hist"], hit["strong"])
    except Exception:
        log.warning("MACD grafigi yasalmadi (%s %s)", symbol, tf, exc_info=True)

    buttons = await _signal_buttons(symbol, "crypto", ctx.bot.username)

    async def _send():
        if photo:
            photo.seek(0)
            return await ctx.bot.send_photo(
                config.NEWS_CHANNEL_ID, InputFile(photo, "macd.png"),
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
        return await ctx.bot.send_message(
            config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True, reply_markup=buttons)

    # Bitta skanerda o'nlab kesishma topilishi mumkin (ayniqsa keskin
    # bozorda yoki bot birinchi marta ishga tushganda) — Telegram esa
    # bitta kanalga daqiqasiga ~20 ta xabarni o'tkazadi. Flood-limitga
    # urilganda xabarni TASHLAB YUBORISH mumkin emas: dedup yozuvi
    # ALLAQACHON band qilingan, ya'ni bu kesishma boshqa hech qachon
    # qayta postlanmasdi. Shu sabab `broadcast`dagi bilan bir xil
    # yondashuv — kutamiz va qayta urinamiz.
    try:
        sent = await _send()
    except RetryAfter as e:
        log.warning("MACD flood-limit: %s s kutilmoqda (%s %s)",
                     e.retry_after, symbol, tf)
        await asyncio.sleep(e.retry_after + 1)
        try:
            sent = await _send()
        except Exception:
            log.exception("MACD xabari qayta urinishda ham postlanmadi (%s %s)",
                          symbol, tf)
            return
    except Exception:
        log.exception("MACD xabari postlanmadi (%s %s)", symbol, tf)
        return
    await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


async def macd_scan_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID or not config.MACD_TIMEFRAMES:
        return
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Qaysi timeframe'larda YANGI sham yopilgan — faqat o'shalar ishlanadi.
    todo: list[tuple[str, int]] = []
    for tf in config.MACD_TIMEFRAMES:
        if tf not in chart.TF_MINUTES:
            log.warning("MACD: noma'lum timeframe o'tkazib yuborildi: %s", tf)
            continue
        open_ms = _last_closed_open_ms(tf, now_ms)
        try:
            seen = await db.get_setting(f"macd_last_scan_{tf}")
        except Exception:
            log.exception("MACD: oxirgi skaner belgisi o'qilmadi (%s)", tf)
            continue
        if seen and int(seen) >= open_ms:
            continue          # bu sham allaqachon skanerlangan
        todo.append((tf, open_ms))
    if not todo:
        return

    try:
        symbols = await _macd_symbols()
    except Exception:
        log.exception("MACD: juftliklar ro'yxati olinmadi")
        return
    if not symbols:
        return

    sem = asyncio.Semaphore(max(1, config.MACD_CONCURRENCY))

    for tf, open_ms in todo:
        async def one(sym: str, _tf=tf, _open=open_ms):
            async with sem:
                try:
                    return await _macd_check_symbol(sym, _tf, _open)
                except Exception:
                    log.debug("MACD tekshiruvi xato (%s %s)", sym, _tf, exc_info=True)
                    return None

        results = await asyncio.gather(*[one(s) for s in symbols])
        hits = [h for h in results if h]
        log.info("MACD skaner: %s — %d juftlikdan %d ta kesishma (sham=%s)",
                  tf, len(symbols), len(hits), open_ms)

        for i, hit in enumerate(hits):
            # Telegram bitta kanalga daqiqasiga ~20 xabar o'tkazadi —
            # xabarlar orasida kichik oraliq flood-limitga UMUMAN
            # urilmaslikni ta'minlaydi (urilib qolsa `_post_macd_alert`
            # ichida kutib qayta urinish ham bor, bu esa oldini oladi).
            if i:
                await asyncio.sleep(config.MACD_POST_DELAY)
            try:
                await _post_macd_alert(ctx, hit)
            except Exception:
                log.exception("MACD xabari ishlanmadi (%s %s)", hit["symbol"], tf)

        # Belgi FAQAT muvaffaqiyatli o'tgandan keyin yoziladi — xato
        # bo'lsa keyingi chaqiruvda qaytadan urinadi.
        try:
            await db.set_setting(f"macd_last_scan_{tf}", str(open_ms))
        except Exception:
            log.exception("MACD: oxirgi skaner belgisi yozilmadi (%s)", tf)

    try:
        await db.purge_old_macd_alerts()
    except Exception:
        log.warning("MACD: eski yozuvlar tozalanmadi", exc_info=True)


async def surge_scan_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    try:
        candidates = await db.volume_surge_candidates(
            config.SURGE_VOLUME_MULTIPLIER, config.SURGE_BASELINE_EXCLUDE_HOURS,
            min_volume_usd=config.SURGE_MIN_VOLUME_USD)
    except Exception:
        log.exception("Hajm portlashi nomzodlarini olishda xato")
        return

    for row in candidates:
        try:
            await _process_surge_candidate(
                ctx, row["symbol"], float(row["latest_volume"]), float(row["avg_volume"]))
        except Exception:
            log.exception("Hajm portlashi ishlanmadi (%s)", row["symbol"])


# ─────────────────────────── Kit (whale) faolligi ───────────────────────────
# Foydalanuvchi so'rovi (namuna: "KERNEL/USDT ... Big Whales Buy Activity ...
# 1.12M KERNEL have been bought ... Order Size: 46.5K USDT (5.13%) ...
# Duration: 8 minutes ... 24h Vol: 906.29K USDT"): FAQAT portlash
# nomzodlarida (butun bozorni HAR individual savdo darajasida kuzatish
# MEXC'ga yuzlab alohida so'rov talab qiladi — tezlik chegarasiga zarba
# beradi; portlash nomzodlari esa odatda bir vaqtda bitta-ikkita bo'ladi,
# shu bois xavfsiz) — so'nggi `WHALE_WINDOW_MINUTES` ichidagi xarid YOKI
# sotuv hajmi 24 soatlik hajmning `WHALE_MIN_PCT` foizidan oshsa,
# ALOHIDA (grafiksiz, matn) xabar. `db.active_live_events()` (`news_
# live_job` ham ishlatadigan, `source`ga qaramaydigan so'rov) orqali
# "hozir jonli kuzatilayotgan portlash hodisalari" ro'yxati olinadi —
# yangi so'rov shart emas.

async def whale_scan_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID:
        return
    try:
        rows = await db.active_live_events(config.NEWS_LIVE_MINUTES)
    except Exception:
        log.exception("Kit faolligi uchun aktiv hodisalar olinmadi")
        return
    surge_rows = {r["symbol"]: r for r in rows if r["source"] == "surge" and r["symbol"]}
    if not surge_rows:
        return

    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    window_ms = config.WHALE_WINDOW_MINUTES * 60_000

    for symbol, surge_row in surge_rows.items():
        try:
            vol24h = await db.latest_volume_snapshot(symbol)
        except Exception:
            log.warning("Kit faolligi uchun 24s hajm olinmadi (%s)", symbol, exc_info=True)
            continue
        if not vol24h:
            continue
        try:
            trades = await exchange._agg_trades(symbol, now_ms - window_ms, now_ms)
        except Exception:
            log.warning("Kit faolligi uchun savdolar olinmadi (%s)", symbol, exc_info=True)
            continue
        if not trades:
            continue

        buys, sells = [], []
        for t in trades:
            try:
                price = float(t["p"]); qty = float(t["q"]); ts = int(t["T"])
                is_sell = bool(t["m"])
            except (KeyError, TypeError, ValueError):
                continue
            (sells if is_sell else buys).append((ts, price, qty))

        threshold_usd = vol24h * config.WHALE_MIN_PCT / 100
        for side_label, side_trades, emoji, verb_head, verb in (
            ("buy", buys, "✳", "Yirik xaridorlar faolligi", "sotib olindi"),
            ("sell", sells, "🔻", "Yirik sotuvchilar faolligi", "sotildi"),
        ):
            if not side_trades:
                continue
            usd = sum(p * q for _, p, q in side_trades)
            if usd < threshold_usd:
                continue

            today_key = now.strftime("%Y-%m-%d")
            external_key = f"whale:{symbol}:{today_key}:{side_label}"
            eid = await db.insert_news_event(
                source="whale", external_key=external_key, symbol=symbol, market="crypto",
                headline_en=f"{symbol}: whale {side_label} {usd:.0f} USDT",
                translation_uz=None, insight_uz=None, event_at=now, posted=True)
            if eid is None:
                continue   # shu tanga/tomon uchun bugun allaqachon xabar berilgan

            base_qty = sum(q for _, _, q in side_trades)
            first_ts, first_price, _ = min(side_trades, key=lambda x: x[0])
            last_ts, last_price, _ = max(side_trades, key=lambda x: x[0])
            duration_min = max(1, round((last_ts - first_ts) / 60_000))
            price_chg = (last_price - first_price) / first_price * 100 if first_price else 0.0
            ticker = symbol[:-len(config.QUOTE)] if symbol.endswith(config.QUOTE) else symbol

            caption = (
                f"<b>{html.escape(symbol)}</b> [MEXC]\n"
                f"{emoji} {html.escape(verb_head)}\n"
                f"{_fmt_usd_k(base_qty)} {html.escape(ticker)} {verb}\n"
                f"💰Narx: {_fmt_price(last_price)} USDT ({price_chg:+.2f}%)\n"
                f"🚨Hajm: {_fmt_usd_k(usd)} USDT ({usd / vol24h * 100:.2f}%)\n"
                f"⏳Davomiyligi: {duration_min} daqiqa\n"
                f"📊24 soatlik hajm: {_fmt_usd_k(vol24h)} USDT"
            )

            # Grafik: foydalanuvchi so'rovi — "Portlash habaridagi grafik bilan
            # bir xil bo'lsin, Volume+Delta". Shu tanga PORTLASH sifatida
            # ALLAQACHON kuzatilayotgani uchun (`surge_row`), o'sha hodisa
            # UCHUN ALLAQACHON hisoblangan Volume/Volume Delta profili
            # (`db.set_news_profile`, 48 soatlik haqiqiy MEXC savdolaridan)
            # bo'lsa — QAYTA SO'RALMAYDI, to'g'ridan-to'g'ri qayta ishlatiladi
            # (MEXC'ga qo'shimcha yuk yo'q, ikkala xabar aynan BIR XIL
            # ma'lumotni ko'rsatadi). Profil yo'q bo'lsa (masalan portlash
            # chizilganda xato bo'lgan) — oddiy (profilsiz) grafikka xavfsiz
            # qaytadi, xuddi `news_live_job()`ning surge yo'lidagi kabi.
            profile = None
            if surge_row["profile_data"]:
                try:
                    profile = json.loads(surge_row["profile_data"])
                except (TypeError, ValueError):
                    log.warning("Kit faolligi: profile_data o'qib bo'lmadi (%s)", symbol,
                               exc_info=True)
                    profile = None

            whale_before_ms = config.SURGE_DECLINE_DAYS * 86_400_000
            marker_color = chart.GREEN if side_label == "buy" else chart.RED
            chart_label = "Xarid" if side_label == "buy" else "Sotuv"
            photo = None
            profile_bins = None
            try:
                result = await _news_candles(symbol, "crypto", now, tf="1d",
                                             before_ms=whale_before_ms)
            except Exception:
                log.warning("Kit faolligi grafigi yasalmadi (%s)", symbol, exc_info=True)
                result = None
            if result:
                candles, news_idx, live_pct = result
                if profile:
                    profile_bins = (profile["vol_bins"], profile["delta_bins"],
                                    profile["bin_lo"], profile["bin_size"])
                    photo = chart.surge_profile_chart(
                        candles, news_idx, symbol, live_pct, *profile_bins,
                        label=chart_label, tf="1d")
                else:
                    photo = chart.news_chart(candles, news_idx, symbol, live_pct,
                                             label=chart_label, marker_color=marker_color, tf="1d")

            buttons = await _signal_buttons(symbol, "crypto", ctx.bot.username)
            try:
                if photo:
                    sent = await ctx.bot.send_photo(
                        config.NEWS_CHANNEL_ID, InputFile(photo, "whale.png"),
                        caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
                else:
                    sent = await ctx.bot.send_message(
                        config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                        reply_markup=buttons)
            except Exception:
                log.exception("Kit faolligi postlanmadi (%s)", external_key)
                continue
            await db.set_news_message(
                eid, sent.message_id, caption,
                render_tf="1d" if photo else None,
                render_before_ms=whale_before_ms if photo else None,
                render_label=chart_label if photo else None,
                render_marker_color=(None if profile_bins else marker_color) if photo else None)
            if profile_bins:
                await db.set_news_profile(eid, *profile_bins)
            await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


# ─────────────────────────── Yirik likvidatsiyalar ───────────────────────────
# Coinalyze orqali (liquidations.py) — fyuchers birjalaridagi kaskadli
# majburiy yopilishlarni kuzatadi. `COINALYZE_API_KEY` bo'sh bo'lsa
# `liquidations.enabled()` False qaytaradi, job hech narsa qilmaydi.

def _eu_decimal(s: str) -> str:
    """AQSH uslubi ("1,234.56") -> Yevropa/rus uslubi ("1.234,56") —
    foydalanuvchi so'ragan aynan shu ko'rinish uchun."""
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_usd_k(value_usd: float) -> str:
    """533890 -> "533,89K" (mingda), 1123640 -> "1,12M" (millionda) — 1
    million va undan katta bo'lsa "K" o'rniga "M" ishlatiladi, aks holda
    "1.123,64K" kabi chalkash (million miqdorini ming deb o'qitadigan)
    ko'rinish chiqardi."""
    if value_usd >= 1_000_000:
        return _eu_decimal(f"{value_usd / 1_000_000:,.2f}") + "M"
    return _eu_decimal(f"{value_usd / 1000:,.2f}") + "K"


def _fmt_price(price: float) -> str:
    """Narxni moslashuvchan aniqlik bilan chiqaradi — arzon tangalarda
    (masalan $0,0045581) ko'proq, qimmatlarida kamroq kasr xonasi,
    ortiqcha nollar kesib tashlanadi."""
    s = f"{price:,.8f}"
    int_part, frac = s.split(".")
    frac = frac.rstrip("0")
    s = int_part if not frac else f"{int_part}.{frac}"
    return _eu_decimal(s)


async def _process_liquidation_spike(ctx: ContextTypes.DEFAULT_TYPE,
                                     spike: liquidations.Spike) -> None:
    now = datetime.now(timezone.utc)
    # "BTCUSDT_PERP.A" -> "BTC" — Coinalyze belgisidan baza aktivni ajratish.
    base = spike.symbol.split(config.QUOTE)[0].split("_")[0].split(".")[0]
    symbol = await exchange.resolve(base)
    if not symbol:
        return   # kuzatilayotgan instrument MEXC'da yo'q — chizib bo'lmaydi

    # Dedup — bitta 5-daqiqalik ustun uchun bitta post (`news_events.
    # external_key` UNIQUE orqali, boshqa manbalar kabi). Skan joyi ham
    # har 5 daqiqada ishlaydi (`liquidation_scan_job`), shuning uchun
    # bucket granularligi = skan granularligi.
    bucket = now.minute - (now.minute % 5)
    external_key = f"liq:{spike.symbol}:{now:%Y-%m-%d %H}:{bucket:02d}"

    # Long ko'p yopilsa narx PASAYGANDA (longlar majburan sotilgan), short
    # ko'p yopilsa narx KO'TARILGANDA (shortlar majburan sotib olingan)
    # likvidatsiya bo'ladi — shuning uchun DOMINANT tomon ko'rsatiladi.
    if spike.long_usd >= spike.short_usd:
        side_label, side_usd, emoji, marker_color = "Long", spike.long_usd, "🔴", chart.RED
    else:
        side_label, side_usd, emoji, marker_color = "Short", spike.short_usd, "🟢", chart.GREEN

    headline = f"{base}: {side_label} likvidatsiya ${side_usd:,.0f}"
    eid = await db.insert_news_event(
        source="liquidation", external_key=external_key, symbol=symbol, market="crypto",
        headline_en=headline, translation_uz=None, insight_uz=None,
        event_at=now, posted=False)
    if eid is None:
        return   # shu 5 daqiqalik ustun uchun allaqachon postlangan

    price = await exchange.last_price(symbol, fresh=True)
    price_part = f" narx: ${_fmt_price(price)}" if price else ""
    caption = (f"{emoji} #{html.escape(base)} Likvidlanish {side_label}: "
              f"${_fmt_usd_k(side_usd)}{price_part} Binance")

    photo, live_pct = None, None
    liq_before_ms = 4 * 3_600_000   # 4 soat, 1m shamlarda
    try:
        rendered = await _news_render(symbol, "crypto", now, tf="1m",
                                      before_ms=liq_before_ms, label="Likvidatsiya",
                                      marker_color=marker_color)
    except Exception:
        log.warning("Likvidatsiya grafigi yasalmadi (%s)", symbol, exc_info=True)
        rendered = None
    if rendered:
        photo, live_pct = rendered

    buttons = await _signal_buttons(symbol, "crypto", ctx.bot.username)
    try:
        if photo:
            sent = await ctx.bot.send_photo(
                config.NEWS_CHANNEL_ID, InputFile(photo, "liq.png"),
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
        else:
            sent = await ctx.bot.send_message(
                config.NEWS_CHANNEL_ID, caption, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True, reply_markup=buttons)
    except Exception:
        log.exception("Likvidatsiya postlanmadi (%s)", symbol)
        return
    await db.set_news_message(
        eid, sent.message_id, caption,
        render_tf="1m" if photo else None,
        render_before_ms=liq_before_ms if photo else None,
        render_label="Likvidatsiya" if photo else None,
        render_marker_color=marker_color if photo else None)
    await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


async def liquidation_scan_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not config.NEWS_CHANNEL_ID or not liquidations.enabled():
        return
    try:
        spikes = await liquidations.liquidation_candidates()
    except Exception:
        log.exception("Likvidatsiya nomzodlarini olishda xato")
        return

    for spike in spikes:
        try:
            await _process_liquidation_spike(ctx, spike)
        except Exception:
            log.exception("Likvidatsiya hodisasi ishlanmadi (%s)", spike.symbol)


async def cmd_charttest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """/charttest TLM (yoki TSLA, EURUSD) — FAQAT super-admin. News Trade AI
    jonli grafik mexanizmini (post + har necha soniyada qayta chizish)
    haqiqiy tiker bilan sinaydi — surge (hajm/pasayish) yoki SEC mantig'i
    ISHTIROKISIZ. Tiker `NEWS_MARKETS` bo'yicha kripto/aksiya/forex
    orasida avtomatik topiladi (xuddi haqiqiy yangilik pipeline'idagi
    kabi `_resolve_news_symbol` orqali) — faqat kriptoga cheklanmagan.
    Doimiy diagnostika vositasi sifatida qoldirildi, foydalanuvchilar
    ro'yxatiga (set_my_commands) ataylab qo'shilmagan."""
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /charttest TLM")
        return
    if not config.NEWS_CHANNEL_ID:
        await update.message.reply_text("NEWS_CHANNEL_ID sozlanmagan.")
        return

    raw = ctx.args[0]
    symbol, market = await _resolve_news_symbol(raw)
    if not symbol:
        await update.message.reply_text(
            f"Tiker topilmadi (kripto/aksiya/forex — hech birida): {html.escape(raw)}")
        return

    # Kripto 24/7 savdo qiladi — oxirgi 60 daqiqa yetarli. Aksiya/forex
    # bozori yopiq bo'lishi mumkin (kecha/dam olish kuni) — 1m sham
    # oxirgi 60 daqiqada umuman bo'lmasligi mumkin, shuning uchun
    # surge_scan_job'dagi kabi kengroq oyna (1h, 4 kun) ishlatiladi —
    # bu oxirgi savdo sessiyasini deyarli har doim qamrab oladi.
    tf, before_ms = ("1m", 60 * 60_000) if market == "crypto" else ("1h", 4 * 86_400_000)

    now = datetime.now(timezone.utc)
    await update.message.reply_text(f"⏳ {symbol} ({market}) — grafik chizilyapti...")
    try:
        rendered = await _news_render(symbol, market, now, tf=tf,
                                      before_ms=before_ms, label="Sinov")
    except Exception:
        log.exception("charttest render xato (%s)", symbol)
        rendered = None
    if rendered is None:
        await update.message.reply_text(
            "Grafik chizib bo'lmadi — bu tikerda so'nggi shamlar topilmadi "
            "(bozor yopiq bo'lishi ham mumkin).")
        return
    photo, live_pct = rendered

    external_key = f"test:{symbol}:{now.isoformat()}"
    eid = await db.insert_news_event(
        source="test", external_key=external_key, symbol=symbol, market=market,
        headline_en=f"Manual chart test: {symbol}", translation_uz=None,
        insight_uz=None, event_at=now, posted=False)

    caption = f"🧪 <b>Sinov</b> — {html.escape(symbol)}\nHar {config.NEWS_REFRESH_SECONDS}s yangilanadi."
    buttons = await _signal_buttons(symbol, market, ctx.bot.username)
    try:
        sent = await ctx.bot.send_photo(
            config.NEWS_CHANNEL_ID, InputFile(photo, "test.png"),
            caption=caption, parse_mode=ParseMode.HTML, reply_markup=buttons)
    except (TimedOut, NetworkError):
        log.exception("charttest post qilinmadi — tarmoq (%s)", symbol)
        await update.message.reply_text(
            "⏱ Tarmoq vaqtincha javob bermadi (Telegram/Railway orasida uzilish). "
            "Qayta urinib ko'ring: /charttest " + raw)
        return
    except Exception:
        log.exception("charttest post qilinmadi (%s)", symbol)
        await update.message.reply_text("Kanalga postlab bo'lmadi (bot admin emasmi?).")
        return
    if eid is not None:
        await db.set_news_message(
            eid, sent.message_id, caption,
            render_tf=tf, render_before_ms=before_ms, render_label="Sinov")
        await _add_share_button(ctx.bot, config.NEWS_CHANNEL_ID, sent.message_id, buttons)


# ─────────────────────────── Telethon login (admin) ───────────────────────────
# MarketTwits kabi begona kanallarni tinglash uchun userbot bir martalik
# telefon-kod bilan login qilinishi kerak — buni admin shu uchta buyruq
# bilan, TO'G'RIDAN-TO'G'RI shu botga yozib amalga oshiradi (kod
# rivojlantirish muhitida emas, jonli serverda ishlaydi — tgsource.py
# yuqoridagi izohiga qarang).

async def cmd_tg_login(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not tgsource.enabled():
        await update.message.reply_text(
            "TELETHON_API_ID/TELETHON_API_HASH sozlanmagan (Railway o'zgaruvchisi).")
        return
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /tg_login +998901234567")
        return
    phone = ctx.args[0]
    try:
        await tgsource.login_send_code(phone)
    except Exception:
        log.exception("Telethon kod so'ralmadi")
        await update.message.reply_text("Kod so'rashda xato — loglarni tekshiring.")
        return
    await update.message.reply_text(
        "Kod yuborildi, Telegram ilovangizni tekshiring. Keyin: /tg_code 12345")


async def cmd_tg_code(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /tg_code 12345")
        return
    try:
        result = await tgsource.login_submit_code(ctx.args[0])
    except Exception:
        log.exception("Telethon kod tasdiqlanmadi")
        await update.message.reply_text(
            "Kod xato yoki muddati tugagan — /tg_login bilan qayta boshlang.")
        return
    if result == "need_password":
        await update.message.reply_text(
            "Akkauntda 2FA parol bor. Yuboring: /tg_password <parol>")
        return
    await _start_markettwits_listener(ctx.bot)
    await update.message.reply_text("✅ Login muvaffaqiyatli! MarketTwits endi tinglanmoqda.")


async def cmd_tg_password(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /tg_password <parol>")
        return
    password = " ".join(ctx.args)
    try:
        await tgsource.login_submit_password(password)
    except Exception:
        log.exception("Telethon parol tasdiqlanmadi")
        await update.message.reply_text("Parol xato — qayta urinib ko'ring.")
        return
    await _start_markettwits_listener(ctx.bot)
    await update.message.reply_text("✅ Login muvaffaqiyatli! MarketTwits endi tinglanmoqda.")


async def cmd_tg_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Haqiqiy kanal postini kutmasdan, xohlagan matnni to'g'ridan-to'g'ri
    MarketTwits quvuridan (hashtag -> tiker -> grafik -> post) o'tkazib
    ko'radi — /tg_login/koda muvaffaqiyatli kirilganini kutmasdan ham
    ishlaydi (bu buyruq listener'ga bog'liq emas). Matnda RESOLVE
    bo'ladigan #hashtag bo'lishi shart (masalan #BTC, #SUI, #AAPL)."""
    if not is_admin(update.effective_user.id):
        return
    text = " ".join(ctx.args) if ctx.args else ""
    if not text:
        await update.message.reply_text(
            "Foydalanish: /tg_test <matn>\n"
            "Matnda tanish #hashtag bo'lsin, masalan:\n"
            "/tg_test #BTC ETF arizasi tasdiqlandi")
        return
    await update.message.reply_text("Tekshirilmoqda…")
    fake_msg_id = int(datetime.now(timezone.utc).timestamp())
    await _process_markettwits_message(
        ctx.bot, "sinov", fake_msg_id, text, datetime.now(timezone.utc))
    await update.message.reply_text(
        "Tayyor. Matndagi #hashtaglardan biri tanish tikerga to'g'ri kelsa — "
        "kanalga postlangan bo'lishi kerak; hech biri topilmasa — hech narsa "
        "chiqmaydi (bu normal, filtr shunday ishlaydi).")


# ─────────────────────────── Ishga tushirish ───────────────────────────

# Bir martalik tuzatishlar — `bot_settings`da o'z belgisini qo'yadi, qayta
# ishlamaydi (konteyner qayta tushsa ham). Foydalanuvchi so'rovi: "#121'dagi
# kabi (allaqachon 'tegilgan' stop) xato bilan yopilgan signallar Madrimov
# guruhining ommaviy statistikasini buzgan — buni 1 marta 0'ga qaytarib
# ber, keyingi safar o'zim /tuzat orqali qilaman". Bitta workspace aniq
# TOPILMASA (0 yoki bir nechta mos keladigan nom) — HECH NARSA qilinmaydi,
# faqat aniq loglanadi (noto'g'ri workspace'ga tegib ketmaslik uchun).
async def _run_one_time_fixes() -> None:
    flag = "onetime_reset_madrimov_stats"
    if await db.get_setting(flag):
        return
    try:
        matches = await db.find_workspaces_by_name("madrimov")
        if len(matches) != 1:
            log.warning(
                "Bir martalik tuzatish: 'madrimov' bo'yicha %d ta workspace topildi "
                "(aniq 1 ta kutilgan edi) — HECH NARSA qilinmadi: %s",
                len(matches), [(m["id"], m["name"]) for m in matches])
        else:
            ws = matches[0]
            result = await db.reset_workspace_stats(ws["id"])
            log.info(
                "Bir martalik tuzatish: '%s' (id=%s) statistikasi 0'ga qaytarildi — "
                "%d ta signal hisobdan chiqarildi, depozit %+.2f o'zgardi",
                ws["name"], ws["id"], result["excluded_count"], result["deposit_delta"])
    except Exception:
        log.exception("Bir martalik tuzatish xato bilan tugadi")
    await db.set_setting(flag, "done")


async def post_init(app: Application) -> None:
    await db.init()
    log.info("Baza tayyor. Super-adminlar: %s", config.ADMIN_IDS)
    await _run_one_time_fixes()
    await app.bot.set_my_commands([
        ("start", "Bosh menyu"),
        ("new", "Signal qanday yoziladi"),
        ("stats", "Statistika"),
        ("symbols", "Juftliklar"),
        ("open", "Ochiq signallar"),
        ("equity", "Equity grafigi"),
        ("pdf", "Statistikani PDF hisobot sifatida olish"),
        ("yordam", "Yo'riqnoma: guruh ulash, signal kiritish"),
        ("month", "Oylik natijalar"),
        ("year", "Yillik natijalar"),
        ("depozit", "Depozitni ko'rish/belgilash"),
        ("cancel", "Signalni bekor qilish (masalan: /cancel 12)"),
        ("setup", "Guruhni ro'yxatdan o'tkazish (faqat guruhda)"),
        ("top", "Eng yaxshi guruhlar reytingi"),
        ("public", "Guruhni /top reytingida ko'rsatish (admin)"),
        ("havola", "Guruhning taklif havolasini belgilash (admin)"),
        ("taklif", "Do'stlaringizni taklif qilish havolasi"),
        ("sahifa", "Guruhning ochiq natijalar sahifasi"),
        ("hisobot", "Avtomatik kunlik hisobot (guruh admini)"),
        ("bekor", "Joriy amalni bekor qilish"),
        ("til", "Til / Язык / Language"),
    ])
    # Avvalgi ishga tushirishda /tg_login bilan allaqachon login qilingan
    # bo'lsa (sessiya Postgres'da saqlangan) — qayta login talab qilinmasdan
    # darhol tinglashni boshlaydi.
    await _start_markettwits_listener(app.bot)


async def post_shutdown(app: Application) -> None:
    await exchange.close()
    await forex.close()
    await stocks.close()


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Ishlov berishda xato", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Xatolik yuz berdi (masalan, narx serveriga vaqtincha "
                "ulanib bo'lmadi). Birozdan so'ng qayta urinib ko'ring."
            )
        except Exception:
            pass


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN o'rnatilmagan — bot ishga tusha olmaydi.")
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # group=-1 — hamma narsadan OLDIN: foydalanuvchini yozadi va majburiy
    # obunani tekshiradi (obuna bo'lmasa ApplicationHandlerStop bilan to'xtatadi).
    app.add_handler(TypeHandler(Update, gate), group=-1)
    app.add_handler(CallbackQueryHandler(on_subcheck, pattern=r"^subcheck$"))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(on_admin, pattern=r"^adm:"))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("bekor", cmd_bekor))
    app.add_handler(CommandHandler("til", cmd_til))
    # `lang:set:<kod>` AVVAL kelishi kerak — `lang:menu` bilan bir xil
    # prefiksda, aniqrog'i birinchi tekshirilsin.
    app.add_handler(CallbackQueryHandler(on_lang_set, pattern=r"^lang:set:"))
    app.add_handler(CallbackQueryHandler(on_lang_menu, pattern=r"^lang:menu$"))
    app.add_handler(CommandHandler("stats", cmd_stats))
    # Faqat super-admin uchun — set_my_commands ro'yxatiga ataylab qo'shilmadi
    # (oddiy foydalanuvchi menyusida ko'rinmasin).
    app.add_handler(CommandHandler("tuzat", cmd_tuzat))
    app.add_handler(CommandHandler("qaytar", cmd_qaytar))
    app.add_handler(CommandHandler("charttest", cmd_charttest))
    app.add_handler(CommandHandler("tg_login", cmd_tg_login))
    app.add_handler(CommandHandler("tg_code", cmd_tg_code))
    app.add_handler(CommandHandler("tg_password", cmd_tg_password))
    app.add_handler(CommandHandler("tg_test", cmd_tg_test))
    app.add_handler(CommandHandler("refhavola", cmd_ref_link))
    app.add_handler(CommandHandler("hisobot", cmd_digest))
    app.add_handler(CommandHandler("sahifa", cmd_page))
    app.add_handler(CallbackQueryHandler(on_fix, pattern=r"^fix:"))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("year", cmd_year))
    app.add_handler(CommandHandler("symbols", cmd_symbols))
    app.add_handler(CommandHandler("equity", cmd_equity))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("depozit", cmd_deposit))
    app.add_handler(CommandHandler("public", cmd_public))
    app.add_handler(CommandHandler("havola", cmd_link))
    app.add_handler(CommandHandler("tasdiq", cmd_pending))
    app.add_handler(CommandHandler("pdf", cmd_pdf))
    app.add_handler(CommandHandler("yordam", cmd_help))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("taklif", cmd_invite))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(okc|nopic|pic|go|no|ed|tf|bk):"))
    app.add_handler(CallbackQueryHandler(on_alloc_skip, pattern=r"^allocskip:"))
    app.add_handler(CallbackQueryHandler(on_alloc_pick, pattern=r"^alloc:"))
    app.add_handler(CallbackQueryHandler(on_tpsl_button, pattern=r"^tpsl:"))
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(show_menu, pattern=r"^menu$"))
    app.add_handler(CallbackQueryHandler(on_switch, pattern=r"^switch$"))
    app.add_handler(CallbackQueryHandler(on_workspace_pick, pattern=r"^ws:"))
    app.add_handler(CallbackQueryHandler(on_onboard, pattern=r"^onboard:"))
    app.add_handler(CallbackQueryHandler(on_join_group, pattern=r"^joingroup$"))
    app.add_handler(CallbackQueryHandler(on_view_join, pattern=r"^viewjoin:"))
    app.add_handler(CallbackQueryHandler(on_public_decision, pattern=r"^(pubok|pubno):"))
    app.add_handler(CallbackQueryHandler(on_close_request, pattern=r"^close:"))
    app.add_handler(CallbackQueryHandler(on_manage, pattern=r"^mng:"))
    app.add_handler(CallbackQueryHandler(on_manage_be, pattern=r"^mbe:"))
    app.add_handler(CallbackQueryHandler(on_manage_sl, pattern=r"^msl:"))
    app.add_handler(CallbackQueryHandler(on_manage_entry, pattern=r"^mentry:"))
    app.add_handler(CallbackQueryHandler(on_manage_tp, pattern=r"^mtp:"))
    app.add_handler(CallbackQueryHandler(on_manage_partial, pattern=r"^mpc:"))
    app.add_handler(CallbackQueryHandler(on_close_confirm, pattern=r"^closeok:"))
    app.add_handler(CallbackQueryHandler(on_close_cancel, pattern=r"^closeno$"))
    app.add_handler(CallbackQueryHandler(on_symbols_nav, pattern=r"^sym:"))
    app.add_handler(CallbackQueryHandler(on_stats_nav, pattern=r"^st:"))
    app.add_handler(CallbackQueryHandler(on_pdf_button, pattern=r"^pdfrep$"))
    app.add_handler(CallbackQueryHandler(on_help, pattern=r"^help:"))

    # Sehrgar (ConversationHandler) OLIB TASHLANDI — foydalanuvchi qarori:
    # "Shu sehrgar kerak emas... Hamma signallarni birma bir qo'lda
    # kiritishsa qulayroq bo'ladi." Uning ikki imkoniyati matn usuliga
    # ko'chirildi (parsing.parse(allow_partial=True) izohiga qarang):
    # "BTC long market" va "BTC long 65000".
    app.add_handler(CallbackQueryHandler(on_new_signal_help, pattern=r"^newsig$"))
    app.add_handler(CommandHandler("new", cmd_new_signal_help))

    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text_signal))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, on_group_message))
    app.add_error_handler(on_error)

    app.job_queue.run_repeating(poll_job, interval=config.POLL_SECONDS, first=10)
    app.job_queue.run_repeating(milestone_job, interval=config.POLL_SECONDS, first=25)
    # Kunlik hisobot: soatni o'tkazib yubormaslik uchun 15 daqiqada bir
    # aylanadi, lekin har guruhga kuniga faqat BIR marta yuboriladi.
    app.job_queue.run_repeating(digest_job, interval=900, first=60)
    # Logotip: sutkada bir marta yetarli — guruh avatari kamdan-kam o'zgaradi.
    app.job_queue.run_repeating(logo_job, interval=86400, first=90)
    # News Trade AI: NEWS_CHANNEL_ID bo'sh bo'lsa job o'zi hech narsa qilmaydi.
    app.job_queue.run_repeating(news_scan_job, interval=90, first=45)
    app.job_queue.run_repeating(binance_listing_job, interval=90, first=60)
    # Jonli yangilanish — bazadan qayta o'qib yangilaydi (Railway deploy
    # qilsa ham davom etadi, `news_live_job` yuqoridagi izohiga qarang).
    app.job_queue.run_repeating(news_live_job, interval=config.NEWS_REFRESH_SECONDS, first=15)
    # Iqtisodiy taqvim: 15 daqiqalik eslatma oynasini o'tkazib yubormaslik
    # uchun 60 soniyada bir tekshiradi (digest kunda bir marta, eslatma
    # dedup orqali — tez-tez tekshirish takror yuborishga olib kelmaydi).
    app.job_queue.run_repeating(econ_job, interval=60, first=20)
    # Hajm portlashi: hajm suratini SURGE_SNAPSHOT_HOURS soatda bir (bazaga
    # tarix yig'ish), nomzodlarni esa SURGE_SCAN_SECONDS'da bir tekshiradi.
    app.job_queue.run_repeating(volume_snapshot_job,
                                interval=config.SURGE_SNAPSHOT_HOURS * 3600, first=30)
    app.job_queue.run_repeating(surge_scan_job,
                                interval=config.SURGE_SCAN_SECONDS, first=120)
    # MACD kesishmasi — job tez-tez uyg'onadi, lekin YANGI sham yopilmagan
    # bo'lsa hech qanday so'rov yubormaydi (macd_scan_job izohiga qarang).
    app.job_queue.run_repeating(macd_scan_job,
                                interval=config.MACD_SCAN_SECONDS, first=150)
    # Kit (whale) faolligi — faqat portlash nomzodlarida (WHALE_SCAN_SECONDS).
    app.job_queue.run_repeating(whale_scan_job,
                                interval=config.WHALE_SCAN_SECONDS, first=100)
    # Yirik likvidatsiyalar: Coinalyze 5 daqiqalik ustunlarga mos interval
    # (COINALYZE_API_KEY bo'sh bo'lsa job o'zi hech narsa qilmaydi).
    app.job_queue.run_repeating(liquidation_scan_job, interval=300, first=150)

    # MUHIM: drop_pending_updates=False — restart paytida kelgan xabarlar yo'qolmasin
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
