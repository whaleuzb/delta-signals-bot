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
    ContextTypes, filters,
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


# ─────────────────────────── Signal kiritish ───────────────────────────

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


async def show_preview(msg, ctx, draft: dict, file_id, source: str, token=None) -> None:
    sym = await exchange.resolve(draft["symbol"])
    if not sym:
        await msg.reply_text(
            f"❌ <code>{draft['symbol']}</code> Binance Futures'da topilmadi.",
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
                    parse_mode=ParseMode.HTML)
            else:
                sent = await ctx.bot.send_message(
                    config.CHANNEL_ID, body, parse_mode=ParseMode.HTML)
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
    await update.message.reply_text(
        "Delta Signals Bot.\n\n"
        "/stats — umumiy statistika\n"
        "/month — oylik jadval\n"
        "/year — joriy yil\n"
        "/open — ochiq signallar\n"
        "/symbols — juftliklar kesimi\n"
        "/equity — equity curve\n"
        "/cancel <id> — signalni bekor qilish"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(await stats.summary(), parse_mode=ParseMode.HTML)


async def cmd_month(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(stats.TZ)
    a, b = stats.month_bounds(now.year, now.month)
    cur = await stats.summary(a, b, f"{stats.MONTHS_UZ[now.month - 1]} {now.year}")
    await update.message.reply_text(
        cur + "\n\n" + await stats.monthly_table(), parse_mode=ParseMode.HTML)


async def cmd_year(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    y = datetime.now(stats.TZ).year
    a, b = stats.year_bounds(y)
    await update.message.reply_text(
        await stats.summary(a, b, f"{y}-yil natijalari"), parse_mode=ParseMode.HTML)


async def cmd_symbols(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(await stats.symbols_table(), parse_mode=ParseMode.HTML)


async def cmd_equity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    buf = await stats.equity_chart()
    if buf is None:
        await update.message.reply_text("Grafik uchun kamida 2 ta yopilgan signal kerak.")
        return
    await update.message.reply_photo(InputFile(buf, "equity.png"))


async def cmd_open(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows = await db.live_signals()
    if not rows:
        await update.message.reply_text("Ochiq signal yo'q.")
        return
    lines = ["<b>Ochiq signallar</b>", ""]
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
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


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
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("month", cmd_month))
    app.add_handler(CommandHandler("year", cmd_year))
    app.add_handler(CommandHandler("symbols", cmd_symbols))
    app.add_handler(CommandHandler("equity", cmd_equity))
    app.add_handler(CommandHandler("open", cmd_open))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(ok|no|ed):"))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, on_photo))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, on_text_signal))
    app.add_error_handler(on_error)

    app.job_queue.run_repeating(poll_job, interval=config.POLL_SECONDS, first=10)

    # MUHIM: drop_pending_updates=False — restart paytida kelgan xabarlar yo'qolmasin
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
