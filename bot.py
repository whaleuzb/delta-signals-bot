"""Trade Controller — asosiy fayl.

Multi-tenant: bitta bot bir nechta mustaqil "workspace"ga xizmat qiladi —
har bir yopiq Telegram guruhi o'z workspace'ini (/setup orqali) ochishi,
yoki istalgan odam shaxsiy jurnal sifatida foydalanishi mumkin. Workspace'lar
bir-birining ma'lumotini ko'rmaydi (db.py'dagi workspace_id orqali ajratilgan).
"""
import asyncio
import html
import io
import os
import logging
import secrets
import time
from datetime import datetime, timezone

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
)
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter
from telegram.ext import (
    Application, ApplicationHandlerStop, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, TypeHandler, filters,
)

import chart
import config
import db
import exchange
import forex
import parsing
import stats
import tracker
import vision

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

# token -> {"draft": {...}, "file_id": str, "user": int, "workspace_id": int}
PENDING: dict[str, dict] = {}
# admin id -> token (tahrir kutilmoqda)
AWAITING_EDIT: dict[int, str] = {}
# admin id -> signal_id (yangi yaratilgan signalga pul miqdori kutilmoqda)
AWAITING_ALLOC: dict[int, int] = {}
# super-admin id -> True (majburiy obuna uchun kanal kutilmoqda)
AWAITING_CHANNEL: dict[int, bool] = {}
# Broadcast: admin xabar yuborishini kutamiz -> keyin tasdiqlashni
AWAITING_BROADCAST: dict[int, bool] = {}
PENDING_BROADCAST: dict[int, tuple[int, int]] = {}   # admin -> (chat_id, message_id)


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
        await q.message.reply_text("Bosh menyu:", reply_markup=main_menu_kb(uid, ws))
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
    await q.message.reply_text("Bosh menyu:", reply_markup=main_menu_kb(uid, ws))


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
    await q.message.reply_text("Bosh menyu:", reply_markup=main_menu_kb(uid, ws))


async def on_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("workspace_id", None)
    await send_workspace_switcher(update, ctx)


def provider_for(market: str):
    """market='forex' bo'lsa Twelve Data, aks holda MEXC (kripto)."""
    return forex if market == "forex" else exchange


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
    e, sl, tps = d["entry"], d["sl"], d["tps"]
    risk = abs(e - sl) / e * 100
    reward = abs(tps[-1] - e) / e * 100
    rr = reward / risk if risk else 0
    arrow = "🟢 LONG" if d["side"] == "LONG" else "🔴 SHORT"
    tag = "💱 " if d.get("market") == "forex" else ""
    head = f"{tag}📊 <b>#{d['symbol']}</b>  {arrow}"
    if sig_id:
        head += f"  <code>#{sig_id}</code>"
    entry_note = " <i>(🎯 darhol kirilgan)</i>" if d.get("entry_mode") == "market" else ""
    lines = [head, "", f"Kirish: <b>{fmt_price(e)}</b>{entry_note}"]
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

def main_menu_kb(uid: int, ws) -> InlineKeyboardMarkup:
    rows = []
    if can_manage(uid, ws):
        rows.append([InlineKeyboardButton("➕ Yangi signal", callback_data="newsig"),
                     InlineKeyboardButton("💰 Depozit", callback_data="m:deposit")])
    rows += [
        [InlineKeyboardButton("📊 Statistika", callback_data="m:stats"),
         InlineKeyboardButton("📉 Juftliklar", callback_data="m:symbols")],
        [InlineKeyboardButton("🔓 Ochiq signallar", callback_data="m:open"),
         InlineKeyboardButton("📈 Equity", callback_data="m:equity")],
        [InlineKeyboardButton("❓ Yordam", callback_data="help:home"),
         InlineKeyboardButton("🔁 Boshqa joyga o'tish", callback_data="switch")],
    ]
    return InlineKeyboardMarkup(rows)


MENU_BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")]])


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
        "<b>Yo'l 1 — sehrgar:</b> <code>/new</code> yozing, bot har bir darajani "
        "navbat bilan so'raydi.\n\n"
        "<b>Yo'l 2 — bitta xabar:</b>\n"
        "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
        "Bular ham ishlaydi:\n"
        "<code>ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80</code>\n"
        "<code>eth long 3200 3400 3550 3100</code>\n"
        "  ↳ kalit so'zsiz: birinchi raqam — kirish, oxirgisi — stop, "
        "o'rtadagilari TP.\n\n"
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
        "Sehrgarda esa <b>🎯 Oddiy (darhol)</b> tugmasini tanlaysiz.\n\n"
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
                f"{mark} #{s['id']} {s['symbol']} — vaqtidan oldin yopish",
                callback_data=f"close:{s['id']}")])
    kb = InlineKeyboardMarkup(kb_rows) if kb_rows else None
    return "\n".join(lines), kb


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

    if ws["type"] == "group" and ws["group_chat_id"]:
        try:
            await ctx.bot.send_message(
                ws["group_chat_id"],
                f"{icon} <b>#{sig_id} {ev['symbol']}</b> — vaqtidan oldin yopildi "
                f"@ <b>{fmt_price(ev['price'])}</b>\nYakuniy: <b>{pnl:+.2f}%</b>{rtxt}",
                parse_mode=ParseMode.HTML, reply_to_message_id=sig["group_msg_id"],
                allow_sending_without_reply=True, message_thread_id=ws["group_topic_id"])
        except Exception:
            log.exception("Guruhga yuborilmadi (qo'lda yopish)")


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

    if action == "stats":
        await q.message.reply_text(await stats_view_text(ws, q.from_user.id, "all"), parse_mode=ParseMode.HTML,
                                    reply_markup=stats_nav_kb("all"))
    elif action == "symbols":
        text = await symbols_view_text(ws["id"], None, None)
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=symbols_nav_kb(None, None))
    elif action == "open":
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
    await update.effective_message.reply_text("Bosh menyu:", reply_markup=main_menu_kb(uid, ws))


# ─────────────────────────── Guruhni ro'yxatdan o'tkazish ───────────────────────────

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


# ─────────────────────────── Signal kiritish — sehrgar (wizard) ───────────────────────────

WIZ_PHOTO, WIZ_SYMBOL, WIZ_MODE, WIZ_SIDE, WIZ_ENTRY, WIZ_TP, WIZ_SL = range(7)

WIZ_CANCEL_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ Bekor qilish", callback_data="wiz_cancel")]])
WIZ_PHOTO_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("⏭ Rasmsiz davom etish", callback_data="wiz_skip_photo")],
    [InlineKeyboardButton("❌ Bekor qilish", callback_data="wiz_cancel")],
])
WIZ_MODE_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("🎯 Oddiy (darhol)", callback_data="wiz_mode:market"),
     InlineKeyboardButton("⏳ Limit (narxni kutadi)", callback_data="wiz_mode:limit")],
    [InlineKeyboardButton("❌ Bekor qilish", callback_data="wiz_cancel")],
])


def _parse_price(raw: str) -> float | None:
    try:
        return float(raw.strip().replace(" ", "").replace(",", ""))
    except (ValueError, AttributeError):
        return None


async def wizard_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q:
        await q.answer()
    target = q.message if q else update.effective_message
    if update.effective_chat.type != "private":
        await target.reply_text("Iltimos, botga shaxsiy xabar (DM) yozib, shu yerda qayta urining.")
        return ConversationHandler.END

    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return ConversationHandler.END
    uid = (q.from_user if q else update.effective_user).id
    if not can_manage(uid, ws):
        await target.reply_text("Sizda bu joy uchun signal kiritish huquqi yo'q.")
        return ConversationHandler.END

    ctx.user_data["wiz"] = {"workspace_id": ws["id"]}
    await target.reply_text("1/6 — 📈 Grafik rasmni yuboring.", reply_markup=WIZ_PHOTO_KB)
    return WIZ_PHOTO


async def wizard_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    ctx.user_data["wiz"]["file_id"] = msg.photo[-1].file_id
    await msg.reply_text("2/6 — Juftlik nomini yozing (masalan BTCUSDT):",
                         reply_markup=WIZ_CANCEL_KB)
    return WIZ_SYMBOL


async def wizard_skip_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["wiz"]["file_id"] = None
    await q.edit_message_text("1/6 — Rasmsiz davom etilmoqda.")
    await q.message.reply_text("2/6 — Juftlik nomini yozing (masalan BTCUSDT):",
                               reply_markup=WIZ_CANCEL_KB)
    return WIZ_SYMBOL


async def wizard_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    raw = (msg.text or "").strip()
    market = "crypto"
    sym = await exchange.resolve(raw)
    if not sym and forex.enabled():
        sym = await forex.resolve(raw)
        if sym:
            market = "forex"
    if not sym:
        await msg.reply_text(f"❌ <code>{raw}</code> topilmadi (kripto yoki forex). Qayta yozing:",
                             parse_mode=ParseMode.HTML, reply_markup=WIZ_CANCEL_KB)
        return WIZ_SYMBOL
    ctx.user_data["wiz"]["symbol"] = sym
    ctx.user_data["wiz"]["market"] = market
    await msg.reply_text(
        f"3/6 — {sym}: qanday kirasiz?\n\n"
        "🎯 <b>Oddiy</b> — signal darhol \"ochiq\" deb hisoblanadi (xuddi shu narxda "
        "allaqachon kirgandek).\n"
        "⏳ <b>Limit</b> — narx kirish darajasiga tegmaguncha kutadi (standart).",
        parse_mode=ParseMode.HTML, reply_markup=WIZ_MODE_KB)
    return WIZ_MODE


async def wizard_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    mode = q.data.split(":", 1)[1]
    ctx.user_data["wiz"]["entry_mode"] = mode
    label = "🎯 Oddiy" if mode == "market" else "⏳ Limit"
    await q.edit_message_text(f"3/6 — Kirish rejimi: {label}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 LONG", callback_data="wiz_side:LONG"),
         InlineKeyboardButton("🔴 SHORT", callback_data="wiz_side:SHORT")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="wiz_cancel")],
    ])
    await q.message.reply_text("4/6 — Yo'nalishni tanlang:", reply_markup=kb)
    return WIZ_SIDE


async def wizard_side(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    side = q.data.split(":", 1)[1]
    ctx.user_data["wiz"]["side"] = side
    await q.edit_message_text(f"4/6 — Yo'nalish: {side}")
    await q.message.reply_text("5/6 — Entry (kirish) narxini kiriting:",
                               reply_markup=WIZ_CANCEL_KB)
    return WIZ_ENTRY


async def wizard_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    entry = _parse_price(msg.text or "")
    if entry is None or entry <= 0:
        await msg.reply_text("Noto'g'ri raqam. Qayta kiriting:", reply_markup=WIZ_CANCEL_KB)
        return WIZ_ENTRY
    ctx.user_data["wiz"]["entry"] = entry
    await msg.reply_text(
        "6/6 — TP narx(lar)ini kiriting (bir nechta bo'lsa bo'sh joy bilan ajrating, "
        "masalan: 67000 68500):", reply_markup=WIZ_CANCEL_KB)
    return WIZ_TP


async def wizard_tp(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    tps = [x for x in (_parse_price(x) for x in (msg.text or "").split()) if x and x > 0]
    if not tps:
        await msg.reply_text("Noto'g'ri format. Qayta kiriting:", reply_markup=WIZ_CANCEL_KB)
        return WIZ_TP
    side = ctx.user_data["wiz"]["side"]
    ctx.user_data["wiz"]["tps"] = sorted(set(tps), reverse=(side == "SHORT"))
    await msg.reply_text("SL (stop-loss) narxini kiriting:", reply_markup=WIZ_CANCEL_KB)
    return WIZ_SL


async def wizard_sl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    sl = _parse_price(msg.text or "")
    if sl is None or sl <= 0:
        await msg.reply_text("Noto'g'ri raqam. Qayta kiriting:", reply_markup=WIZ_CANCEL_KB)
        return WIZ_SL
    wiz = ctx.user_data.pop("wiz")
    draft = {"symbol": wiz["symbol"], "side": wiz["side"], "entry": wiz["entry"],
             "sl": sl, "tps": wiz["tps"], "market": wiz.get("market", "crypto"),
             "entry_mode": wiz.get("entry_mode", "limit")}
    await show_preview(msg, ctx, draft, wiz.get("file_id"), "wizard", wiz["workspace_id"])
    return ConversationHandler.END


async def wizard_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    ctx.user_data.pop("wiz", None)
    if q:
        await q.answer()
        await q.edit_message_text("❌ Bekor qilindi.", reply_markup=MENU_BACK_KB)
    else:
        await update.effective_message.reply_text("❌ Bekor qilindi.", reply_markup=MENU_BACK_KB)
    return ConversationHandler.END


# ─────────────────────────── Signal kiritish — tezkor usul ───────────────────────────

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
        await msg.reply_text("🔎 Grafikni o'qiyapman…")
        f = await ctx.bot.get_file(file_id)
        data = bytes(await f.download_as_bytearray())
        draft = await vision.read_chart(data)
        source = "vision"
        if draft is None:
            await msg.reply_text(
                "Darajalarni o'qiy olmadim. Rasm ostiga yozib yuboring, masalan:\n"
                "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>",
                parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB,
            )
            return

    await show_preview(msg, ctx, draft, file_id, source, ws["id"])


async def on_text_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Rasmsiz matnli signal yoki tahrir javobi."""
    uid = update.effective_user.id
    msg = update.effective_message
    text = msg.text or ""

    if AWAITING_CHANNEL.pop(uid, None) and is_admin(uid):
        await handle_channel_add(update, ctx)
        return

    if AWAITING_BROADCAST.pop(uid, None) and is_admin(uid):
        await handle_broadcast_input(update, ctx)
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

    draft = parsing.parse(text)
    if not draft:
        return  # oddiy suhbat — signalga o'xshamaydi, e'tiborsiz qoldiramiz

    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not can_manage(uid, ws):
        return
    await show_preview(msg, ctx, draft, None, "matn", ws["id"])


async def on_group_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Debug: guruh/mavzu ID'larini aniqlash uchun loglaydi (masalan mavjud
    workspace'ga mavzu qo'shish kerak bo'lganda)."""
    chat = update.effective_chat
    msg = update.effective_message
    log.info("DEBUG guruh xabari: chat_id=%s title=%r type=%s thread_id=%s",
              chat.id, chat.title, chat.type, msg.message_thread_id)


async def show_preview(msg, ctx, draft: dict, file_id, source: str, workspace_id: int,
                        token: str | None = None) -> None:
    market = "crypto"
    sym = await exchange.resolve(draft["symbol"])
    if not sym and forex.enabled():
        sym = await forex.resolve(draft["symbol"])
        if sym:
            market = "forex"
    if not sym:
        await msg.reply_text(
            f"❌ <code>{draft['symbol']}</code> topilmadi (kripto yoki forex).",
            parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB,
        )
        return
    draft["symbol"] = sym
    draft["market"] = market
    draft.setdefault("entry_mode", "limit")

    err = parsing.validate(draft)
    if err:
        await msg.reply_text(f"❌ {err}", parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)
        return

    warn = []
    if draft["side"] == "SHORT" and not config.ALLOW_SHORT and market != "forex":
        warn.append("⚠️ SPOT rejimida SHORT savdo qilinmaydi — statistikaga kirmaydi.")
    if draft.get("entry_mode") == "market":
        warn.append("🎯 Oddiy rejim — tasdiqlansa signal darhol \"ochiq\" deb belgilanadi.")
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
    PENDING[token] = {"draft": draft, "file_id": file_id, "user": msg.from_user.id,
                       "workspace_id": workspace_id}

    body = draft_text(draft)
    if warn:
        body += "\n\n" + "\n".join(warn)

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ok:{token}"),
        InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"ed:{token}"),
        InlineKeyboardButton("🗑 Bekor", callback_data=f"no:{token}"),
    ]])
    await msg.reply_text(body, parse_mode=ParseMode.HTML, reply_markup=kb)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    action, _, token = q.data.partition(":")
    item = PENDING.get(token)
    if not item:
        await q.edit_message_text("Bu so'rov eskirgan.", reply_markup=MENU_BACK_KB)
        return
    if q.from_user.id != item["user"]:
        return

    if action == "no":
        PENDING.pop(token, None)
        await q.edit_message_text("🗑 Bekor qilindi.", reply_markup=MENU_BACK_KB)
        return

    if action == "ed":
        AWAITING_EDIT[q.from_user.id] = token
        await q.edit_message_text(
            "✏️ To'g'ri darajalarni yuboring:\n"
            "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # --- tasdiqlash ---
    ws = await db.get_workspace(item["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        await q.edit_message_text("Ruxsat yo'q.")
        return

    d = item["draft"]
    entry_mode = d.get("entry_mode", "limit")
    sig_id = await db.create_signal(ws["id"], {
        "symbol": d["symbol"], "side": d["side"], "entry": d["entry"],
        "sl": d["sl"], "tps": d["tps"], "chart_file_id": item["file_id"],
        "author_id": q.from_user.id, "note": d.get("reasoning"),
        "market": d.get("market", "crypto"), "entry_mode": entry_mode,
    })
    PENDING.pop(token, None)
    await q.edit_message_text(f"✅ Signal <code>#{sig_id}</code> qabul qilindi.",
                              parse_mode=ParseMode.HTML, reply_markup=MENU_BACK_KB)

    group_msg_id = None
    if ws["type"] == "group" and ws["group_chat_id"]:
        body = draft_text(d, sig_id)
        try:
            if item["file_id"]:
                sent = await ctx.bot.send_photo(
                    ws["group_chat_id"], item["file_id"], caption=body,
                    parse_mode=ParseMode.HTML, message_thread_id=ws["group_topic_id"])
            else:
                sent = await ctx.bot.send_message(
                    ws["group_chat_id"], body, parse_mode=ParseMode.HTML,
                    message_thread_id=ws["group_topic_id"])
            group_msg_id = sent.message_id
            await db.set_group_msg(sig_id, group_msg_id)
        except Exception:
            log.exception("Guruhga yuborib bo'lmadi")

    if entry_mode == "market" and ws["type"] == "group" and ws["group_chat_id"]:
        try:
            await ctx.bot.send_message(
                ws["group_chat_id"],
                f"▶️ <b>#{sig_id} {d['symbol']}</b> — pozitsiya ochildi @ <b>{fmt_price(d['entry'])}</b>",
                parse_mode=ParseMode.HTML, reply_to_message_id=group_msg_id,
                allow_sending_without_reply=True, message_thread_id=ws["group_topic_id"])
        except Exception:
            log.exception("Guruhga yuborilmadi (oddiy rejim ochilish xabari)")

    if ws["deposit"] is not None:
        AWAITING_ALLOC[q.from_user.id] = sig_id
        kb2 = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏭ O'tkazib yuborish", callback_data=f"allocskip:{sig_id}")]])
        await q.message.reply_text(
            f"💰 #{sig_id} {d['symbol']} uchun necha pul ishlatasiz? (masalan 100)",
            reply_markup=kb2)


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
            try:
                if photo:
                    await ctx.bot.send_photo(ws["owner_id"], InputFile(photo, "signal.png"),
                                              caption=txt, parse_mode=ParseMode.HTML)
                else:
                    await ctx.bot.send_message(ws["owner_id"], txt, parse_mode=ParseMode.HTML)
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
                await ctx.bot.send_message(ws["owner_id"], txt, parse_mode=ParseMode.HTML)
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

    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    await update.message.reply_text(
        f"Trade Controller — {ws['name']} 👇", reply_markup=main_menu_kb(uid, ws))


async def cmd_bekor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    AWAITING_EDIT.pop(update.effective_user.id, None)
    AWAITING_ALLOC.pop(update.effective_user.id, None)
    AWAITING_BROADCAST.pop(update.effective_user.id, None)
    PENDING_BROADCAST.pop(update.effective_user.id, None)
    ctx.user_data.pop("wiz", None)
    await update.message.reply_text("❌ Bekor qilindi.", reply_markup=MENU_BACK_KB)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    await update.message.reply_text(await stats_view_text(ws, update.effective_user.id, "all"),
                                     parse_mode=ParseMode.HTML, reply_markup=stats_nav_kb("all"))


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
    await update.message.reply_photo(InputFile(buf, "equity.png"), reply_markup=MENU_BACK_KB)


async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
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
        who = _who(u["username"], u["first_name"], u["user_id"])
        lines.append(f"{' '.join(badges) or '·'} {html.escape(who)}")
        kb.append([InlineKeyboardButton(f"{who}"[:40],
                                         callback_data=f"adm:usr:{u['user_id']}")])
    lines += ["", "🧑 shaxsiy jurnal · 👑 guruh egasi · 👥 guruhga ulangan · 🎁 taklif qilgan"]

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


# ─────────────────────────── Ishga tushirish ───────────────────────────

async def post_init(app: Application) -> None:
    await db.init()
    log.info("Baza tayyor. Super-adminlar: %s", config.ADMIN_IDS)
    await app.bot.set_my_commands([
        ("start", "Bosh menyu"),
        ("new", "Yangi signal (sehrgar)"),
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
        ("bekor", "Joriy amalni bekor qilish"),
    ])


async def post_shutdown(app: Application) -> None:
    await exchange.close()
    await forex.close()


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
    app.add_handler(CommandHandler("stats", cmd_stats))
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
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(ok|no|ed):"))
    app.add_handler(CallbackQueryHandler(on_alloc_skip, pattern=r"^allocskip:"))
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(show_menu, pattern=r"^menu$"))
    app.add_handler(CallbackQueryHandler(on_switch, pattern=r"^switch$"))
    app.add_handler(CallbackQueryHandler(on_workspace_pick, pattern=r"^ws:"))
    app.add_handler(CallbackQueryHandler(on_onboard, pattern=r"^onboard:"))
    app.add_handler(CallbackQueryHandler(on_join_group, pattern=r"^joingroup$"))
    app.add_handler(CallbackQueryHandler(on_view_join, pattern=r"^viewjoin:"))
    app.add_handler(CallbackQueryHandler(on_public_decision, pattern=r"^(pubok|pubno):"))
    app.add_handler(CallbackQueryHandler(on_close_request, pattern=r"^close:"))
    app.add_handler(CallbackQueryHandler(on_close_confirm, pattern=r"^closeok:"))
    app.add_handler(CallbackQueryHandler(on_close_cancel, pattern=r"^closeno$"))
    app.add_handler(CallbackQueryHandler(on_symbols_nav, pattern=r"^sym:"))
    app.add_handler(CallbackQueryHandler(on_stats_nav, pattern=r"^st:"))
    app.add_handler(CallbackQueryHandler(on_pdf_button, pattern=r"^pdfrep$"))
    app.add_handler(CallbackQueryHandler(on_help, pattern=r"^help:"))

    app.add_handler(ConversationHandler(
        entry_points=[
            CallbackQueryHandler(wizard_start, pattern=r"^newsig$"),
            CommandHandler("new", wizard_start),
        ],
        states={
            WIZ_PHOTO: [
                MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, wizard_photo),
                CallbackQueryHandler(wizard_skip_photo, pattern=r"^wiz_skip_photo$"),
            ],
            WIZ_SYMBOL: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, wizard_symbol)],
            WIZ_MODE: [CallbackQueryHandler(wizard_mode, pattern=r"^wiz_mode:")],
            WIZ_SIDE: [CallbackQueryHandler(wizard_side, pattern=r"^wiz_side:")],
            WIZ_ENTRY: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, wizard_entry)],
            WIZ_TP: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, wizard_tp)],
            WIZ_SL: [MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, wizard_sl)],
        },
        fallbacks=[CallbackQueryHandler(wizard_cancel, pattern=r"^wiz_cancel$")],
        conversation_timeout=900,
    ))

    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text_signal))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, on_group_message))
    app.add_error_handler(on_error)

    app.job_queue.run_repeating(poll_job, interval=config.POLL_SECONDS, first=10)
    app.job_queue.run_repeating(milestone_job, interval=config.POLL_SECONDS, first=25)

    # MUHIM: drop_pending_updates=False — restart paytida kelgan xabarlar yo'qolmasin
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
