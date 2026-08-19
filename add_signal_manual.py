"""Bir martalik skript: admin tomonidan qo'lda berilgan bitta signalni bazaga
qo'shib, keyin tracker dvigatel orqali MEXC'ning haqiqiy tarixiy narxlari
bilan to'liq qayta o'ynatadi (entry/TP/SL teginishi, R-multiple va h.k. —
xuddi bot jonli kuzatgandek aniq chiqadi).
"""
import asyncio

import config
import db
import exchange
import tracker

SYMBOL = "ALPINEUSDT"
SIDE = "LONG"
ENTRY = 0.324
SL = 0.303
TPS = [0.400]
CREATED_AT = "2026-08-03T21:00:00+05:00"  # Asia/Tashkent
MARKER = "manual-add-2026-08-03-ALPINEUSDT"


async def main():
    pool = await db.init()
    async with pool.acquire() as c:
        sig_id = await c.fetchval("SELECT id FROM signals WHERE note=$1", MARKER)
        if sig_id:
            print(f"Allaqachon mavjud: #{sig_id}")
        else:
            sig_id = await c.fetchval("""
                INSERT INTO signals (symbol, side, entry, sl, sl_initial, tps, created_at, note)
                VALUES ($1,$2,$3,$4,$4,$5,$6,$7) RETURNING id
            """, SYMBOL, SIDE, db._d(ENTRY), db._d(SL), [db._d(t) for t in TPS],
                CREATED_AT, MARKER)
            print(f"Yaratildi: #{sig_id}")

    for _ in range(100):
        sig = await db.get_signal(sig_id)
        if sig["status"] not in ("PENDING", "ACTIVE"):
            print(f"Yakunlandi -> {sig['status']}  pnl={sig['pnl_pct']}%  R={sig['r_multiple']}")
            break
        events = await tracker.process(sig)
        for e in events:
            print(" ", e["type"], e.get("price"), e.get("share"))
        if not events:
            sig = await db.get_signal(sig_id)
            print(f"Hozircha ochiq holatda: {sig['status']} (joriy vaqtga yetib keldik)")
            break
    else:
        print("100 iteratsiyadan keyin ham tugamadi.")

    await exchange.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
