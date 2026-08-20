"""Kuzatuv dvigatelini sintetik shamlarda tekshirish. Baza va birja kerak emas.

Ishga tushirish:  python test_tracker.py
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "x")
os.environ.setdefault("DATABASE_URL", "postgres://x")

import config
import db
import exchange
import tracker

NOW = datetime.now(timezone.utc)
SAVED: dict = {}


def candle(i, o, h, l, c):
    ms = int((NOW + timedelta(minutes=i)).timestamp() * 1000)
    return exchange.Candle(ms, o, h, l, c, ms + 59_999)


def signal(**kw):
    d = {
        "id": 1, "workspace_id": 1, "symbol": "BTCUSDT", "side": "LONG",
        "entry": 100.0, "sl": 96.0, "sl_initial": 96.0, "tps": [104.0, 108.0, 112.0],
        "tp_hit": 0, "filled_pct": 0.0, "realized_pct": 0.0, "status": "PENDING",
        "created_at": NOW, "opened_at": None, "last_checked_ms": None,
        "ambiguous": False,
    }
    d.update(kw)
    return d


async def run(sig, candles):
    exchange.klines = lambda *a, **k: _ret(candles)
    db.save_progress = _save
    events = await tracker.process(sig)
    return SAVED.copy(), events


async def _ret(v):
    return v


async def _save(sig_id, f):
    SAVED.clear()
    SAVED.update(f)


def show(name, saved, events, expect_pnl=None):
    ev = " → ".join(
        e["type"] + (f"{e['n']}" if e["type"] == "TP" else "") for e in events
    ) or "—"
    pnl = saved.get("pnl_pct")
    ok = "  " if expect_pnl is None else ("✅" if abs((pnl or 0) - expect_pnl) < 0.01 else "❌")
    pnl_s = "—" if pnl is None else f"{pnl:+.2f}%"
    print(f"{ok} {name:<34} {saved['status']:<10} pnl={pnl_s:>8}"
          f"  R={saved.get('r_multiple')}  [{ev}]")


async def main():
    print(f"TP ulushlari: {tracker.allocation(3)}  |  BE ko'chirish: {config.MOVE_SL_TO_BE_AFTER_TP1}\n")

    # 1. Barcha TP lar ketma-ket
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),      # entry to'ldi
        candle(1, 100, 104.5, 100, 104),   # TP1
        candle(2, 104, 108.2, 103, 108),   # TP2
        candle(3, 108, 112.5, 107, 112),   # TP3
    ])
    # 0.5*4% + 0.3*8% + 0.2*12% = 2 + 2.4 + 2.4 = 6.8
    show("To'liq TP1+TP2+TP3", saved, ev, 6.8)

    # 2. To'g'ridan-to'g'ri stop
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 100.5, 95.5, 96),   # SL
    ])
    show("Toza stop loss", saved, ev, -4.0)

    # 3. TP1 dan keyin breakeven
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 104.5, 100, 104),   # TP1 -> stop 100 ga ko'chadi
        candle(2, 104, 105, 99.5, 100),    # BE ga qaytdi
    ])
    # 0.5*4% + 0.5*0% = 2.0
    show("TP1 keyin breakeven", saved, ev, 2.0)

    # 4. Bitta shamda TP ham SL ham
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 105, 95, 97),       # ikkalasi ham
    ])
    show("TP+SL bitta shamda (konserv.)", saved, ev, -4.0)
    assert saved["ambiguous"], "ambiguous bayrog'i qo'yilmadi"

    # 5. Entryga tegmadi
    saved, ev = await run(signal(), [
        candle(0, 102, 103, 101, 102),
        candle(1, 102, 104, 101.5, 103),
    ])
    show("Entry to'lmadi", saved, ev)

    # 6. Muddati o'tgan
    saved, ev = await run(signal(created_at=NOW - timedelta(days=10)), [
        candle(0, 102, 103, 101, 102),
    ])
    show("PENDING muddati tugadi", saved, ev)

    # 7. Bitta shamda ikkita TP
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 109, 100, 108),    # TP1 va TP2 birga
    ])
    show("Bitta shamda TP1+TP2", saved, ev)

    # 8. SHORT
    saved, ev = await run(signal(
        side="SHORT", entry=100.0, sl=104.0, sl_initial=104.0, tps=[96.0, 92.0, 88.0]
    ), [
        candle(0, 99, 101, 99, 100),
        candle(1, 100, 100, 95.5, 96),
        candle(2, 96, 97, 91.5, 92),
        candle(3, 92, 93, 87.5, 88),
    ])
    show("SHORT to'liq TP", saved, ev, 6.8)

    # 9. Bir nechta iteratsiya (bot uxlab qolgan holat)
    sig = signal()
    exchange.klines = lambda *a, **k: _ret([candle(0, 101, 101, 99, 100)])
    db.save_progress = _save
    await tracker.process(sig)
    sig.update(SAVED)
    sig["tps"] = [104.0, 108.0, 112.0]
    sig["sl_initial"] = 96.0
    sig["symbol"], sig["side"], sig["entry"], sig["id"] = "BTCUSDT", "LONG", 100.0, 1
    sig["created_at"] = NOW
    exchange.klines = lambda *a, **k: _ret([candle(1, 100, 113, 100, 112)])
    ev = await tracker.process(sig)
    show("Uzilgan sikl (2 bosqich)", SAVED, ev, 6.8)

    print("\nBarcha holatlar tekshirildi.")


asyncio.run(main())
