"""Delta Signals Bot — asosiy fayl."""
import asyncio
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

# token -> {"draft": {...}, "file_id": str, "user": int}
PENDING: dict[str, dict] = {}
# admin id -> token (tahrir kutilmoqda)
AWAITING_EDIT: dict[int, str] = {}


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


NOT_SUBSCRIBER_TEXT = (
    "🔒 Bu ma'lumotlar faqat Whales Uzb obunachilariga ochiq.\n"
    "Obunani faollashtirgach, bot avtomatik ishlay boshlaydi."
)
NOT_SUBSCRIBER_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("💳 Obuna bo'lish", url="https://t.me/mamurjonpaybot")]])


async def is_subscriber(bot, uid: int) -> bool:
    """Kirish nazorati: whale-payment-bot muddati tugagan obunachilarni guruhdan
    avtomatik chiqarib turadi, shuning uchun "hozir guruh a'zosimi" tekshiruvi
    "hozir obunachimi" degani bilan bir xil — alohida DB ulanishi shart emas."""
    if is_admin(uid):
        return True
    if not config.CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(config.CHANNEL_ID, uid)
        return member.status not in ("left", "kicked")
    except Exception:
        log.exception("Obuna tekshiruvida xato (uid=%s)", uid)
        return False


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

def main_menu_kb(uid: int) -> InlineKeyboardMarkup:
    rows = []
    if is_admin(uid):
        rows.append([InlineKeyboardButton("➕ Yangi signal", callback_data="newsig")])
    rows += [
        [InlineKeyboardButton("📊 Statistika", callback_data="m:stats"),
         InlineKeyboardButton("📉 Juftliklar", callback_data="m:symbols")],
        [InlineKeyboardButton("🔓 Ochiq signallar", callback_data="m:open"),
         InlineKeyboardButton("📈 Equity", callback_data="m:equity")],
    ]
    return InlineKeyboardMarkup(rows)


MENU_BACK_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Bosh menyu", callback_data="menu")]])


async def open_signals_view(uid: int) -> tuple[str, InlineKeyboardMarkup | None]:
    rows = await db.live_signals()
    if not rows:
        return "Ochiq signal yo'q.", None
    lines = ["<b>Ochiq signallar</b>", ""]
    kb_rows = []
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
        if is_admin(uid):
            kb_rows.append([InlineKeyboardButton(
                f"🔻 #{s['id']} {s['symbol']} — vaqtidan oldin yopish",
                callback_data=f"close:{s['id']}")])
    kb = InlineKeyboardMarkup(kb_rows) if kb_rows else None
    return "\n".join(lines), kb


async def on_close_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    sig_id = int(q.data.split(":", 1)[1])
    sig = await db.get_signal(sig_id)
    if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
        await q.edit_message_text("Bu signal allaqachon yopilgan yoki topilmadi.")
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
    if not is_admin(q.from_user.id):
        return
    sig_id = int(q.data.split(":", 1)[1])
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

    if config.CHANNEL_ID:
        sig = await db.get_signal(sig_id)
        reply_to = sig["group_msg_id"] if sig else None
        try:
            await ctx.bot.send_message(
                config.CHANNEL_ID,
                f"{icon} <b>#{sig_id} {ev['symbol']}</b> — vaqtidan oldin yopildi "
                f"@ <b>{fmt_price(ev['price'])}</b>\nYakuniy: <b>{pnl:+.2f}%</b>{rtxt}",
                parse_mode=ParseMode.HTML, reply_to_message_id=reply_to,
                allow_sending_without_reply=True)
        except Exception:
            log.exception("Guruhga yuborilmadi (qo'lda yopish)")


async def on_close_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("↩️ Bekor qilindi, signal ochiq qoldi.")


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


async def stats_view_text(mode: str, y: int | None = None, m: int | None = None) -> str:
    if mode == "m":
        a, b = stats.month_bounds(y, m)
        return await stats.summary(a, b, f"{stats.MONTHS_UZ[m - 1]} {y}")
    if mode == "y":
        a, b = stats.year_bounds(y)
        return await stats.summary(a, b, f"{y}-yil natijalari")
    return await stats.summary()


async def on_stats_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not await is_subscriber(ctx.bot, q.from_user.id):
        await q.edit_message_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    parts = q.data.split(":")  # st:all | st:m:Y:M | st:y:Y
    mode = parts[1]
    y = int(parts[2]) if mode in ("m", "y") else None
    m = int(parts[3]) if mode == "m" else None
    text = await stats_view_text(mode, y, m)
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=stats_nav_kb(mode, y, m))


def _shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


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


async def symbols_view_text(y: int | None, m: int | None) -> str:
    if y is None:
        return await stats.symbols_table(title="Barcha davr")
    a, b = stats.month_bounds(y, m)
    return await stats.symbols_table(a, b, title=f"{stats.MONTHS_UZ[m - 1]} {y}")


async def on_symbols_nav(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not await is_subscriber(ctx.bot, q.from_user.id):
        await q.edit_message_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    parts = q.data.split(":")
    y, m = (None, None) if parts[1] == "all" else (int(parts[1]), int(parts[2]))
    text = await symbols_view_text(y, m)
    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=symbols_nav_kb(y, m))


async def on_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not await is_subscriber(ctx.bot, q.from_user.id):
        await q.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    action = q.data.split(":", 1)[1]

    if action == "stats":
        await q.message.reply_text(await stats_view_text("all"), parse_mode=ParseMode.HTML,
                                    reply_markup=stats_nav_kb("all"))
    elif action == "symbols":
        now = datetime.now(stats.TZ)
        text = await symbols_view_text(now.year, now.month)
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=symbols_nav_kb(now.year, now.month))
    elif action == "open":
        text, kb = await open_signals_view(q.from_user.id)
        rows = (list(kb.inline_keyboard) if kb else []) + list(MENU_BACK_KB.inline_keyboard)
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                    reply_markup=InlineKeyboardMarkup(rows))
    elif action == "equity":
        buf = await stats.equity_chart()
        if buf is None:
            await q.message.reply_text("Grafik uchun kamida 2 ta yopilgan signal kerak.",
                                        reply_markup=MENU_BACK_KB)
        else:
            await q.message.reply_photo(InputFile(buf, "equity.png"), reply_markup=MENU_BACK_KB)


async def show_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    uid = q.from_user.id if q else update.effective_user.id
    if q:
        await q.answer()
    if not await is_subscriber(ctx.bot, uid):
        target = q.message if q else update.effective_message
        await target.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    target = q.message if q else update.effective_message
    await target.reply_text("Bosh menyu:", reply_markup=main_menu_kb(uid))


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
    uid = (q.from_user if q else update.effective_user).id
    if not is_admin(uid):
        return ConversationHandler.END
    if q:
        await q.answer()
    target = q.message if q else update.effective_message
    if update.effective_chat.type != "private":
        await target.reply_text("Iltimos, botga shaxsiy xabar (DM) yozib, shu yerda qayta urining.")
        return ConversationHandler.END
    ctx.user_data["wiz"] = {}
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
    await show_preview(msg, ctx, draft, wiz.get("file_id"), "wizard")
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
    if not is_admin(update.effective_user.id):
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

    await show_preview(msg, ctx, draft, file_id, source)


async def on_text_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Rasmsiz matnli signal yoki tahrir javobi."""
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    msg = update.effective_message
    text = msg.text or ""

    token = AWAITING_EDIT.pop(uid, None)
    if token and token in PENDING:
        draft = parsing.parse(text)
        if draft is None:
            AWAITING_EDIT[uid] = token
            await msg.reply_text("O'qiy olmadim. Yana urinib ko'ring yoki /bekor yozing.")
            return
        PENDING[token]["draft"] = draft
        await show_preview(msg, ctx, draft, PENDING[token]["file_id"], "tahrir", token)
        return

    draft = parsing.parse(text)
    if draft:
        await show_preview(msg, ctx, draft, None, "matn")


async def on_group_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Vaqtinchalik debug: guruh/mavzu ID'larini aniqlash uchun loglaydi."""
    chat = update.effective_chat
    msg = update.effective_message
    log.info("DEBUG guruh xabari: chat_id=%s title=%r type=%s thread_id=%s",
              chat.id, chat.title, chat.type, msg.message_thread_id)


async def show_preview(msg, ctx, draft: dict, file_id, source: str, token=None) -> None:
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
    PENDING[token] = {"draft": draft, "file_id": file_id, "user": msg.from_user.id}

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
    d = item["draft"]
    sig_id = await db.create_signal({
        "symbol": d["symbol"], "side": d["side"], "entry": d["entry"],
        "sl": d["sl"], "tps": d["tps"], "chart_file_id": item["file_id"],
        "author_id": q.from_user.id, "note": d.get("reasoning"),
    })
    PENDING.pop(token, None)
    await q.edit_message_text(f"✅ Signal <code>#{sig_id}</code> qabul qilindi.",
                              parse_mode=ParseMode.HTML)

    if config.CHANNEL_ID:
        body = draft_text(d, sig_id)
        try:
            if item["file_id"]:
                sent = await ctx.bot.send_photo(
                    config.CHANNEL_ID, item["file_id"], caption=body,
                    parse_mode=ParseMode.HTML, message_thread_id=config.CHANNEL_TOPIC_ID)
            else:
                sent = await ctx.bot.send_message(
                    config.CHANNEL_ID, body, parse_mode=ParseMode.HTML,
                    message_thread_id=config.CHANNEL_TOPIC_ID)
            await db.set_group_msg(sig_id, sent.message_id)
        except Exception:
            log.exception("Guruhga yuborib bo'lmadi")


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

    for e in events:
        sid, sym = e["signal_id"], e["symbol"]
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

        sig = await db.get_signal(sid)
        reply_to = sig["group_msg_id"] if sig else None
        if config.CHANNEL_ID:
            try:
                await ctx.bot.send_message(
                    config.CHANNEL_ID, txt, parse_mode=ParseMode.HTML,
                    reply_to_message_id=reply_to,
                    allow_sending_without_reply=True)
            except Exception:
                log.exception("Xabar yuborilmadi")

        if sig and sig["ambiguous"] and e["type"] == "STOP":
            for admin in config.ADMIN_IDS:
                try:
                    await ctx.bot.send_message(
                        admin,
                        f"⚠️ #{sid} — TP va SL bitta 1m shamda tegdi. "
                        f"Konservativ hisob ishlatildi (SL). Qo'lda tekshiring.",
                    )
                except Exception:
                    pass


# ─────────────────────────── Komandalar ───────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if not await is_subscriber(ctx.bot, uid):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    await update.message.reply_text(
        "Delta Signals Bot — tugmalardan foydalaning 👇",
        reply_markup=main_menu_kb(uid))


async def cmd_bekor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    AWAITING_EDIT.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Bekor qilindi.")


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_subscriber(ctx.bot, update.effective_user.id):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    await update.message.reply_text(await stats_view_text("all"), parse_mode=ParseMode.HTML,
                                     reply_markup=stats_nav_kb("all"))


async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_subscriber(ctx.bot, update.effective_user.id):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    now = datetime.now(stats.TZ)
    a, b = stats.month_bounds(now.year, now.month)
    cur = await stats.summary(a, b, f"{stats.MONTHS_UZ[now.month - 1]} {now.year}")
    await update.message.reply_text(
        cur + "\n\n" + await stats.monthly_table(), parse_mode=ParseMode.HTML)


async def cmd_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_subscriber(ctx.bot, update.effective_user.id):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    y = datetime.now(stats.TZ).year
    a, b = stats.year_bounds(y)
    await update.message.reply_text(
        await stats.summary(a, b, f"{y}-yil natijalari"), parse_mode=ParseMode.HTML)


async def cmd_symbols(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_subscriber(ctx.bot, update.effective_user.id):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    now = datetime.now(stats.TZ)
    text = await symbols_view_text(now.year, now.month)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML,
                                     reply_markup=symbols_nav_kb(now.year, now.month))


async def cmd_equity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_subscriber(ctx.bot, update.effective_user.id):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    buf = await stats.equity_chart()
    if buf is None:
        await update.message.reply_text("Grafik uchun kamida 2 ta yopilgan signal kerak.")
        return
    await update.message.reply_photo(InputFile(buf, "equity.png"))


async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_subscriber(ctx.bot, update.effective_user.id):
        await update.message.reply_text(NOT_SUBSCRIBER_TEXT, reply_markup=NOT_SUBSCRIBER_KB)
        return
    text, kb = await open_signals_view(update.effective_user.id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Foydalanish: /cancel 12")
        return
    ok = await db.cancel_signal(int(ctx.args[0]))
    await update.message.reply_text("✅ Bekor qilindi." if ok else "Topilmadi yoki allaqachon yopilgan.")


# ─────────────────────────── Ishga tushirish ───────────────────────────

async def post_init(app: Application) -> None:
    await db.init()
    log.info("Baza tayyor. Adminlar: %s", config.ADMIN_IDS)


async def post_shutdown(app: Application) -> None:
    await exchange.close()


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Ishlov berishda xato", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Xatolik yuz berdi (masalan, Binance narx serveriga vaqtincha "
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
    app.add_handler(CommandHandler("bekor", cmd_bekor))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("year", cmd_year))
    app.add_handler(CommandHandler("symbols", cmd_symbols))
    app.add_handler(CommandHandler("equity", cmd_equity))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(ok|no|ed):"))
    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^m:"))
    app.add_handler(CallbackQueryHandler(show_menu, pattern=r"^menu$"))
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
