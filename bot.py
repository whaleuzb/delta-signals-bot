"""Trade Controller — asosiy fayl.

Multi-tenant: bitta bot bir nechta mustaqil "workspace"ga xizmat qiladi —
har bir yopiq Telegram guruhi o'z workspace'ini (/setup orqali) ochishi,
yoki istalgan odam shaxsiy jurnal sifatida foydalanishi mumkin. Workspace'lar
bir-birining ma'lumotini ko'rmaydi (db.py'dagi workspace_id orqali ajratilgan).
"""
import logging
import secrets
from datetime import datetime, timezone

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)

import config
import db
import exchange
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


def access_denied(ws) -> tuple[str, InlineKeyboardMarkup | None]:
    if ws["type"] == "personal":
        return "🔒 Bu boshqa foydalanuvchining shaxsiy jurnali.", None
    return NOT_SUBSCRIBER_TEXT, NOT_SUBSCRIBER_KB


# ─────────────────────────── Workspace aniqlash ───────────────────────────

async def resolve_workspace(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Joriy update qaysi workspace'ga tegishli ekanini aniqlaydi.
    Guruh ichida — o'sha guruhning workspace'i (agar /setup qilingan bo'lsa, aks
    holda None). Shaxsiy chatda — avval tanlab keshlangan workspace; agar bo'lmasa
    va foydalanuvchida faqat bitta variant bo'lsa (o'z guruhi YOKI shaxsiy jurnal,
    ikkalasi ham emas) — avtomatik shu; agar ikkalasi ham bor — None (switcher);
    agar birortasi ham yo'q (birinchi murojaat) — None (onboarding ko'rsatiladi)."""
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

    if owned_group and not personal:
        ctx.user_data["workspace_id"] = owned_group["id"]
        return owned_group
    if personal and not owned_group:
        ctx.user_data["workspace_id"] = personal["id"]
        return personal

    return None  # ikkalasi ham bor (tanlash kerak) yoki ikkalasi ham yo'q (onboarding)


async def send_workspace_switcher(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    owned_group = await db.get_group_workspace_by_owner(uid)
    personal = await db.get_or_create_personal_workspace(uid, "Shaxsiy jurnal")
    rows = []
    if owned_group:
        rows.append([InlineKeyboardButton(
            f"🏘 {owned_group['name']}", callback_data=f"ws:{owned_group['id']}")])
    rows.append([InlineKeyboardButton("🧑 Shaxsiy jurnal", callback_data=f"ws:{personal['id']}")])
    await update.effective_message.reply_text("Qaysi joy uchun?", reply_markup=InlineKeyboardMarkup(rows))


ONBOARD_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("🧑 Shaxsiy jurnal ochish", callback_data="onboard:personal")],
    [InlineKeyboardButton("🏘 Menda yopiq guruh bor", callback_data="onboard:group")],
])


async def send_onboarding(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "👋 Xush kelibsiz! Botni qanday ishlatmoqchisiz?\n\n"
        "🧑 <b>Shaxsiy jurnal</b> — o'z savdo signallaringizni yozib, statistikangizni "
        "kuzatib borasiz. Faqat sizga ko'rinadi, hech kimga post bo'lmaydi.\n\n"
        "🏘 <b>Guruh</b> — sizda o'z yopiq Telegram guruhingiz bo'lsa, uni ham shu bot "
        "bilan boshqarishingiz mumkin: signallar guruhga post bo'ladi, a'zolaringiz "
        "statistikani ko'radi.",
        parse_mode=ParseMode.HTML, reply_markup=ONBOARD_KB)


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

    bot_username = ctx.bot.username
    mention = f"@{bot_username}" if bot_username else "botni"
    await q.edit_message_text(
        f"🏘 Guruhingizni ulash uchun:\n\n"
        f"1. {mention} o'z guruhingizga qo'shing.\n"
        "2. Botga guruhda <b>admin</b> huquqini bering (xabar yuborish uchun kerak).\n"
        "3. Guruh ichida <code>/setup</code> buyrug'ini yozing.\n\n"
        "Shundan so'ng guruhingiz mustaqil workspace sifatida ishlay boshlaydi va "
        "botga shaxsiy yozganingizda avtomatik o'shani boshqarasiz.",
        parse_mode=ParseMode.HTML)


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
    if owned_group or personal:
        await send_workspace_switcher(update, ctx)
    else:
        await send_onboarding(update, ctx)
    return None


async def on_workspace_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    wid = int(q.data.split(":", 1)[1])
    ws = await db.get_workspace(wid)
    if not ws or (ws["owner_id"] != q.from_user.id and not is_admin(q.from_user.id)):
        await q.edit_message_text("Ruxsat yo'q.")
        return
    ctx.user_data["workspace_id"] = wid
    await q.edit_message_text(f"✅ Tanlandi: {ws['name']}")
    await q.message.reply_text("Bosh menyu:", reply_markup=main_menu_kb(q.from_user.id, ws))


async def on_switch(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ctx.user_data.pop("workspace_id", None)
    await send_workspace_switcher(update, ctx)


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
    head = f"📊 <b>#{d['symbol']}</b>  {arrow}"
    if sig_id:
        head += f"  <code>#{sig_id}</code>"
    lines = [head, "", f"Kirish: <b>{fmt_price(e)}</b>"]
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
        [InlineKeyboardButton("🔁 Boshqa joyga o'tish", callback_data="switch")],
    ]
    return InlineKeyboardMarkup(rows)


MENU_BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")]])


async def open_signals_view(ws, uid: int) -> tuple[str, InlineKeyboardMarkup | None]:
    rows = await db.live_signals(ws["id"])
    if not rows:
        return "Ochiq signal yo'q.", None
    lines = ["<b>Ochiq signallar</b>", ""]
    kb_rows = []
    manage = can_manage(uid, ws)
    for s in rows:
        price = await exchange.last_price(s["symbol"])
        cur = ""
        if price:
            p = tracker.pnl_at(s["side"], float(s["entry"]), price)
            cur = f"  ({p:+.2f}%)"
        mark = "▶️" if s["status"] == "ACTIVE" else "⏳"
        lines.append(
            f"{mark} <code>#{s['id']}</code> {s['symbol']} {s['side']} "
            f"@ {fmt_price(float(s['entry']))} — TP{s['tp_hit']}/{len(s['tps'])}{cur}"
        )
        if manage:
            kb_rows.append([InlineKeyboardButton(
                f"🔻 #{s['id']} {s['symbol']} — vaqtidan oldin yopish",
                callback_data=f"close:{s['id']}")])
    kb = InlineKeyboardMarkup(kb_rows) if kb_rows else None
    return "\n".join(lines), kb


async def on_close_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sig_id = int(q.data.split(":", 1)[1])
    sig = await db.get_signal(sig_id)
    if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
        await q.edit_message_text("Bu signal allaqachon yopilgan yoki topilmadi.")
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        return

    if sig["status"] == "PENDING":
        text = f"#{sig_id} {sig['symbol']} hali entryga tegmagan. Bekor qilinsinmi?"
    else:
        price = await exchange.last_price(sig["symbol"])
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
        await q.edit_message_text("Topilmadi.")
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(q.from_user.id, ws):
        return

    ev = await tracker.close_now(sig_id)
    if not ev:
        await q.edit_message_text("Yopib bo'lmadi (narx olinmadi yoki allaqachon yopilgan).")
        return

    if ev["status"] == "CANCELLED":
        await q.edit_message_text(f"🗑 #{sig_id} {ev['symbol']} bekor qilindi (entryga tegmagan edi).")
        return

    pnl, r = ev["pnl"], ev["r"]
    icon = "✅" if pnl >= 0 else "❌"
    rtxt = f" ({r:+.2f}R)" if r is not None else ""
    await q.edit_message_text(
        f"{icon} #{sig_id} {ev['symbol']} qo'lda yopildi @ {fmt_price(ev['price'])}\n"
        f"Yakuniy: {pnl:+.2f}%{rtxt}")

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
    await q.edit_message_text("↩️ Bekor qilindi, signal ochiq qoldi.")


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

    rows.append(list(MENU_BACK_KB.inline_keyboard[0]))
    return InlineKeyboardMarkup(rows)


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
        now = datetime.now(stats.TZ)
        text = await symbols_view_text(ws["id"], now.year, now.month)
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=symbols_nav_kb(now.year, now.month))
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
        buf = await stats.equity_chart(ws["id"])
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

WIZ_PHOTO, WIZ_SYMBOL, WIZ_SIDE, WIZ_ENTRY, WIZ_TP, WIZ_SL = range(6)

WIZ_CANCEL_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ Bekor qilish", callback_data="wiz_cancel")]])
WIZ_PHOTO_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("⏭ Rasmsiz davom etish", callback_data="wiz_skip_photo")],
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
    await target.reply_text("1/5 — 📈 Grafik rasmni yuboring.", reply_markup=WIZ_PHOTO_KB)
    return WIZ_PHOTO


async def wizard_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    ctx.user_data["wiz"]["file_id"] = msg.photo[-1].file_id
    await msg.reply_text("2/5 — Juftlik nomini yozing (masalan BTCUSDT):",
                         reply_markup=WIZ_CANCEL_KB)
    return WIZ_SYMBOL


async def wizard_skip_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    ctx.user_data["wiz"]["file_id"] = None
    await q.edit_message_text("1/5 — Rasmsiz davom etilmoqda.")
    await q.message.reply_text("2/5 — Juftlik nomini yozing (masalan BTCUSDT):",
                               reply_markup=WIZ_CANCEL_KB)
    return WIZ_SYMBOL


async def wizard_symbol(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.effective_message
    raw = (msg.text or "").strip()
    sym = await exchange.resolve(raw)
    if not sym:
        await msg.reply_text(f"❌ <code>{raw}</code> MEXC'da topilmadi. Qayta yozing:",
                             parse_mode=ParseMode.HTML, reply_markup=WIZ_CANCEL_KB)
        return WIZ_SYMBOL
    ctx.user_data["wiz"]["symbol"] = sym
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 LONG", callback_data="wiz_side:LONG"),
         InlineKeyboardButton("🔴 SHORT", callback_data="wiz_side:SHORT")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="wiz_cancel")],
    ])
    await msg.reply_text(f"3/5 — {sym}: yo'nalishni tanlang:", reply_markup=kb)
    return WIZ_SIDE


async def wizard_side(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    side = q.data.split(":", 1)[1]
    ctx.user_data["wiz"]["side"] = side
    await q.edit_message_text(f"3/5 — Yo'nalish: {side}")
    await q.message.reply_text("4/5 — Entry (kirish) narxini kiriting:",
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
        "5/5 — TP narx(lar)ini kiriting (bir nechta bo'lsa bo'sh joy bilan ajrating, "
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
             "sl": sl, "tps": wiz["tps"]}
    await show_preview(msg, ctx, draft, wiz.get("file_id"), "wizard", wiz["workspace_id"])
    return ConversationHandler.END


async def wizard_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    ctx.user_data.pop("wiz", None)
    if q:
        await q.answer()
        await q.edit_message_text("❌ Bekor qilindi.")
    else:
        await update.effective_message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END


# ─────────────────────────── Signal kiritish — tezkor usul ───────────────────────────

async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
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
                parse_mode=ParseMode.HTML,
            )
            return

    await show_preview(msg, ctx, draft, file_id, source, ws["id"])


async def on_text_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Rasmsiz matnli signal yoki tahrir javobi."""
    uid = update.effective_user.id
    msg = update.effective_message
    text = msg.text or ""

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
                parse_mode=ParseMode.HTML)
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
    sym = await exchange.resolve(draft["symbol"])
    if not sym:
        await msg.reply_text(
            f"❌ <code>{draft['symbol']}</code> MEXC'da topilmadi.",
            parse_mode=ParseMode.HTML,
        )
        return
    draft["symbol"] = sym

    err = parsing.validate(draft)
    if err:
        await msg.reply_text(f"❌ {err}", parse_mode=ParseMode.HTML)
        return

    warn = []
    if draft["side"] == "SHORT" and not config.ALLOW_SHORT:
        warn.append("⚠️ SPOT rejimida SHORT savdo qilinmaydi — statistikaga kirmaydi.")
    if source == "vision":
        conf = draft.get("confidence", 0)
        warn.append(f"🤖 Rasmdan o'qildi (ishonch {conf:.0%}) — darajalarni tekshiring.")
        if draft.get("reasoning"):
            warn.append(f"<i>{draft['reasoning']}</i>")

    price = await exchange.last_price(sym)
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
        await q.edit_message_text("Bu so'rov eskirgan.")
        return
    if q.from_user.id != item["user"]:
        return

    if action == "no":
        PENDING.pop(token, None)
        await q.edit_message_text("🗑 Bekor qilindi.")
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
    sig_id = await db.create_signal(ws["id"], {
        "symbol": d["symbol"], "side": d["side"], "entry": d["entry"],
        "sl": d["sl"], "tps": d["tps"], "chart_file_id": item["file_id"],
        "author_id": q.from_user.id, "note": d.get("reasoning"),
    })
    PENDING.pop(token, None)
    await q.edit_message_text(f"✅ Signal <code>#{sig_id}</code> qabul qilindi.",
                              parse_mode=ParseMode.HTML)

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
            await db.set_group_msg(sig_id, sent.message_id)
        except Exception:
            log.exception("Guruhga yuborib bo'lmadi")

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
    await q.edit_message_text("⏭ O'tkazib yuborildi.")


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

        if not ws or ws["type"] != "group" or not ws["group_chat_id"]:
            continue  # shaxsiy workspace — guruhga hech narsa yuborilmaydi

        sig = await db.get_signal(sid)
        reply_to = sig["group_msg_id"] if sig else None
        try:
            await ctx.bot.send_message(
                ws["group_chat_id"], txt, parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to, allow_sending_without_reply=True,
                message_thread_id=ws["group_topic_id"])
        except Exception:
            log.exception("Xabar yuborilmadi")

        if sig and sig["ambiguous"] and e["type"] == "STOP":
            try:
                await ctx.bot.send_message(
                    ws["owner_id"],
                    f"⚠️ #{sid} — TP va SL bitta 1m shamda tegdi. "
                    f"Konservativ hisob ishlatildi (SL). Qo'lda tekshiring.",
                )
            except Exception:
                pass


# ─────────────────────────── Komandalar ───────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    uid = update.effective_user.id
    if not await can_view(ctx.bot, uid, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    await update.message.reply_text(
        f"Trade Controller — {ws['name']} 👇", reply_markup=main_menu_kb(uid, ws))


async def cmd_bekor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    AWAITING_EDIT.pop(update.effective_user.id, None)
    ctx.user_data.pop("wiz", None)
    await update.message.reply_text("❌ Bekor qilindi.")


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
    now = datetime.now(stats.TZ)
    text = await symbols_view_text(ws["id"], now.year, now.month)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=symbols_nav_kb(now.year, now.month))


async def cmd_equity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    buf = await stats.equity_chart(ws["id"])
    if buf is None:
        await update.message.reply_text("Grafik uchun kamida 2 ta yopilgan signal kerak.")
        return
    await update.message.reply_photo(InputFile(buf, "equity.png"))


async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ws = await get_ws_or_prompt(update, ctx)
    if not ws:
        return
    if not await can_view(ctx.bot, update.effective_user.id, ws):
        text, kb = access_denied(ws)
        await update.message.reply_text(text, reply_markup=kb)
        return
    text, kb = await open_signals_view(ws, update.effective_user.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /cancel 12")
        return
    sig = await db.get_signal(int(ctx.args[0]))
    if not sig:
        await update.message.reply_text("Topilmadi.")
        return
    ws = await db.get_workspace(sig["workspace_id"])
    if not ws or not can_manage(update.effective_user.id, ws):
        return
    ok = await db.cancel_signal(sig["id"])
    await update.message.reply_text("✅ Bekor qilindi." if ok else "Topilmadi yoki allaqachon yopilgan.")


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
            f"Joriy depozit ({ws['name']}): <b>{txt}</b>\n\n"
            "Yangilash uchun: <code>/depozit 1000</code>\n\n"
            "Depozit belgilansa, har bir yangi signal tasdiqlangach \"necha pul "
            "ishlatasiz\" deb so'raladi (ixtiyoriy) — shundan real (pulga bog'liq) "
            "foyda/zarar hisoblanadi.",
            parse_mode=ParseMode.HTML)
        return

    amount = _parse_price(ctx.args[0])
    if amount is None or amount <= 0:
        await update.message.reply_text("Noto'g'ri summa. Masalan: /depozit 1000")
        return
    await db.set_deposit(ws["id"], amount)
    await update.message.reply_text(f"✅ Depozit yangilandi: <b>{amount:,.2f}</b>",
                                     parse_mode=ParseMode.HTML)


# ─────────────────────────── Ishga tushirish ───────────────────────────

async def post_init(app: Application) -> None:
    await db.init()
    log.info("Baza tayyor. Super-adminlar: %s", config.ADMIN_IDS)
    try:
        await app.bot.set_my_name("Trade Controller")
    except Exception:
        log.exception("Bot nomini o'rnatib bo'lmadi")


async def post_shutdown(app: Application) -> None:
    await exchange.close()


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

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
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
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(ok|no|ed):"))
    app.add_handler(CallbackQueryHandler(on_alloc_skip, pattern=r"^allocskip:"))
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(show_menu, pattern=r"^menu$"))
    app.add_handler(CallbackQueryHandler(on_switch, pattern=r"^switch$"))
    app.add_handler(CallbackQueryHandler(on_workspace_pick, pattern=r"^ws:"))
    app.add_handler(CallbackQueryHandler(on_onboard, pattern=r"^onboard:"))
    app.add_handler(CallbackQueryHandler(on_close_request, pattern=r"^close:"))
    app.add_handler(CallbackQueryHandler(on_close_confirm, pattern=r"^closeok:"))
    app.add_handler(CallbackQueryHandler(on_close_cancel, pattern=r"^closeno$"))
    app.add_handler(CallbackQueryHandler(on_symbols_nav, pattern=r"^sym:"))
    app.add_handler(CallbackQueryHandler(on_stats_nav, pattern=r"^st:"))

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

    # MUHIM: drop_pending_updates=False — restart paytida kelgan xabarlar yo'qolmasin
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
