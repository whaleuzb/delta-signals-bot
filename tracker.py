"""Signal kuzatuvchi dvigatel.

Har bir ochiq signal uchun oxirgi tekshiruvdan beri kelgan 1m shamlarni ketma-ket
"qayta o'ynatadi". Shu sabab bot 45 soniya uxlagan bo'lsa ham hech bir teginish
o'tkazib yuborilmaydi.
"""
import logging
from datetime import datetime, timedelta, timezone

import config
import db
import exchange
import forex

log = logging.getLogger(__name__)


def provider(market: str):
    """market='forex' bo'lsa Twelve Data, aks holda MEXC (kripto)."""
    return forex if market == "forex" else exchange


def allocation(n: int) -> list[float]:
    """TP soniga qarab ulushlarni normallashtirish."""
    base = config.TP_ALLOCATION[:n] or [1.0]
    if len(base) < n:
        base = base + [base[-1]] * (n - len(base))
    total = sum(base)
    return [x / total for x in base]


def pnl_at(side: str, entry: float, price: float) -> float:
    """Spot uchun toza foiz (1x, leverage yo'q)."""
    if side == "LONG":
        return (price - entry) / entry * 100
    return (entry - price) / entry * 100


async def process(sig) -> list[dict]:
    """Bitta signalni yangilaydi. Yuz bergan hodisalar ro'yxatini qaytaradi."""
    symbol = sig["symbol"]
    side = sig["side"]
    entry = float(sig["entry"])
    sl = float(sig["sl"])
    sl_init = float(sig["sl_initial"])
    tps = [float(x) for x in sig["tps"]]
    alloc = allocation(len(tps))

    tp_hit = sig["tp_hit"]
    filled = float(sig["filled_pct"])
    realized = float(sig["realized_pct"])
    status = sig["status"]
    ambiguous = sig["ambiguous"]

    start_ms = sig["last_checked_ms"] or int(sig["created_at"].timestamp() * 1000)
    candles = await provider(sig["market"]).klines(symbol, start_ms + 1)
    if not candles:
        return []

    events: list[dict] = []
    opened_at = sig["opened_at"]
    closed_at = None
    exit_price = None
    last_ms = start_ms

    for c in candles:
        last_ms = c.close_ms

        # --- 1. Entryga tegdimi ---
        if status == "PENDING":
            if c.low <= entry <= c.high:
                status = "ACTIVE"
                opened_at = datetime.fromtimestamp(c.open_ms / 1000, timezone.utc)
                events.append({"type": "OPEN", "price": entry})
            else:
                continue  # entry ochilmagan — TP/SL hisoblanmaydi

        if status != "ACTIVE":
            break

        # --- 2. Shu shamda SL va TP holati ---
        sl_touched = (c.low <= sl) if side == "LONG" else (c.high >= sl)
        nxt = tps[tp_hit] if tp_hit < len(tps) else None
        tp_touched = nxt is not None and ((c.high >= nxt) if side == "LONG" else (c.low <= nxt))

        if sl_touched and tp_touched:
            # 1m sham ichida tartibni bilib bo'lmaydi -> konservativ: SL birinchi
            ambiguous = True
            if config.CONSERVATIVE_SAME_CANDLE:
                tp_touched = False

        # --- 3. SL ---
        if sl_touched:
            rest = max(0.0, 1.0 - filled)
            realized += rest * pnl_at(side, entry, sl)
            filled = 1.0
            exit_price = sl
            status = "BREAKEVEN" if abs(sl - entry) < 1e-12 else ("TP" if tp_hit else "SL")
            if tp_hit and status == "TP":
                status = "TP"  # TP1 olingandan keyin BE/stopda yopilgan — foydali yakun
            closed_at = datetime.fromtimestamp(c.close_ms / 1000, timezone.utc)
            events.append({"type": "STOP", "price": sl, "was_be": abs(sl - entry) < 1e-12})
            break

        # --- 4. TP lar (bitta shamda bir nechtasi tegishi mumkin) ---
        while tp_touched:
            price = tps[tp_hit]
            share = alloc[tp_hit]
            realized += share * pnl_at(side, entry, price)
            filled += share
            tp_hit += 1
            events.append({"type": "TP", "n": tp_hit, "price": price,
                           "share": share, "running": realized})

            if tp_hit == 1 and config.MOVE_SL_TO_BE_AFTER_TP1 and sl != entry:
                sl = entry
                events.append({"type": "BE", "price": entry})

            if tp_hit >= len(tps):
                status = "TP"
                filled = 1.0
                exit_price = price
                closed_at = datetime.fromtimestamp(c.close_ms / 1000, timezone.utc)
                break

            nxt = tps[tp_hit]
            tp_touched = (c.high >= nxt) if side == "LONG" else (c.low <= nxt)

        if status == "TP":
            break

    # --- 5. Muddati o'tgan PENDING ---
    if status == "PENDING":
        age = datetime.now(timezone.utc) - sig["created_at"]
        if age > timedelta(days=config.EXPIRE_DAYS):
            status = "EXPIRED"
            closed_at = datetime.now(timezone.utc)
            events.append({"type": "EXPIRED"})

    # --- 6. Yakuniy hisob ---
    pnl = r = None
    if status in ("TP", "SL", "BREAKEVEN"):
        pnl = round(realized, 4)
        risk = abs(entry - sl_init) / entry * 100
        r = round(pnl / risk, 3) if risk > 0 else None

    await db.save_progress(sig["id"], {
        "sl": sl, "tp_hit": tp_hit, "filled_pct": round(filled, 6),
        "realized_pct": round(realized, 4), "status": status,
        "opened_at": opened_at, "closed_at": closed_at, "exit_price": exit_price,
        "pnl_pct": pnl, "r_multiple": r, "last_checked_ms": last_ms,
        "ambiguous": ambiguous,
    })

    for e in events:
        e["signal_id"] = sig["id"]
        e["workspace_id"] = sig["workspace_id"]
        e["symbol"] = symbol
        e["final_pnl"] = pnl
        e["r"] = r
        e["closes"] = False
    if events and status in ("TP", "SL", "BREAKEVEN"):
        events[-1]["closes"] = True
    return events


async def close_now(sig_id: int) -> dict | None:
    """Ochiq signalni joriy bozor narxida qo'lda (TP/SL kutmasdan) yopadi."""
    sig = await db.get_signal(sig_id)
    if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
        return None

    if sig["status"] == "PENDING":
        await db.cancel_signal(sig_id, "CANCELLED")
        return {"type": "MANUAL_CLOSE", "signal_id": sig_id, "workspace_id": sig["workspace_id"],
                "symbol": sig["symbol"], "status": "CANCELLED", "pnl": None, "r": None,
                "price": None}

    # fresh=True — bu narx savdoning YAKUNIY natijasi sifatida bazaga yoziladi,
    # shuning uchun ko'rsatuv uchun mo'ljallangan qisqa keshdan olinmaydi.
    # Xato bo'lsa None qaytaramiz: chaqiruvchi buni allaqachon "narx olinmadi"
    # deb aniq xabar qiladi, umumiy xato ekranidan ko'ra tushunarliroq.
    # Signal ochiqligicha qoladi — hech narsa buzilmaydi, qayta urinsa bo'ladi.
    try:
        price = await provider(sig["market"]).last_price(sig["symbol"], fresh=True)
    except Exception:
        log.warning("Qo'lda yopishda narx olinmadi (#%s %s)", sig_id, sig["symbol"],
                     exc_info=True)
        return None
    if not price:
        return None

    entry = float(sig["entry"])
    sl_init = float(sig["sl_initial"])
    filled = float(sig["filled_pct"])
    realized = float(sig["realized_pct"])
    rest = max(0.0, 1.0 - filled)
    pnl = round(realized + rest * pnl_at(sig["side"], entry, price), 4)
    risk = abs(entry - sl_init) / entry * 100
    r = round(pnl / risk, 3) if risk > 0 else None
    status = "BREAKEVEN" if abs(pnl) < 1e-9 else ("TP" if pnl > 0 else "SL")

    await db.save_progress(sig_id, {
        "sl": float(sig["sl"]), "tp_hit": sig["tp_hit"], "filled_pct": 1.0,
        "realized_pct": pnl, "status": status,
        "opened_at": sig["opened_at"], "closed_at": datetime.now(timezone.utc),
        "exit_price": price, "pnl_pct": pnl, "r_multiple": r,
        "last_checked_ms": sig["last_checked_ms"], "ambiguous": sig["ambiguous"],
    })
    return {"type": "MANUAL_CLOSE", "signal_id": sig_id, "workspace_id": sig["workspace_id"],
            "symbol": sig["symbol"], "status": status, "pnl": pnl, "r": r, "price": price}


async def run_once() -> list[dict]:
    out = []
    for sig in await db.live_signals():  # barcha workspace'lar
        try:
            out += await process(sig)
        except Exception:
            log.exception("Signal #%s kuzatuvida xato", sig["id"])
    return out
