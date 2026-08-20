"""Bir martalik: BTCUSDT va TNSRUSDT ni YOPILGAN signallar ro'yxatidan o'chirish.
Foydalanuvchi so'rovi bo'yicha - qolganini o'zi qayta kiritadi. Ishga tushirilgach
o'chiriladi."""
import asyncio

import config
import db

SYMBOLS = ("BTCUSDT", "TNSRUSDT")
CLOSED = "('TP','SL','BREAKEVEN')"


async def main():
    await db.init()
    pool = db.pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            f"SELECT id, workspace_id, symbol, status, pnl_pct, closed_at FROM signals "
            f"WHERE symbol = ANY($1) AND status IN {CLOSED} ORDER BY id",
            list(SYMBOLS),
        )
        print(f"Topildi: {len(rows)} ta yopilgan signal")
        for r in rows:
            print(f"  #{r['id']} ws={r['workspace_id']} {r['symbol']} {r['status']} "
                  f"{r['pnl_pct']}% closed_at={r['closed_at']}")

        if rows:
            ids = [r["id"] for r in rows]
            result = await c.execute("DELETE FROM signals WHERE id = ANY($1)", ids)
            print(f"O'chirildi: {result}")
        else:
            print("O'chiriladigan narsa topilmadi.")


asyncio.run(main())
