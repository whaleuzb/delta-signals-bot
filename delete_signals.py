"""Bir martalik: BTCUSDT va TNSRUSDT qidiruvi (barcha holatlarda), keyin
faqat yopilganlarni o'chirish. Ishga tushirilgach o'chiriladi."""
import asyncio

import config
import db

CLOSED = "('TP','SL','BREAKEVEN')"


async def main():
    await db.init()
    pool = db.pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT id, workspace_id, symbol, status, pnl_pct, closed_at FROM signals "
            "WHERE symbol ILIKE '%BTC%' OR symbol ILIKE '%TNSR%' ORDER BY id"
        )
        print(f"Topildi (barcha holatlar): {len(rows)} ta")
        for r in rows:
            print(f"  #{r['id']} ws={r['workspace_id']} {r['symbol']} {r['status']} "
                  f"{r['pnl_pct']}% closed_at={r['closed_at']}")

        closed_ids = [r["id"] for r in rows if r["status"] in ("TP", "SL", "BREAKEVEN")]
        if closed_ids:
            result = await c.execute("DELETE FROM signals WHERE id = ANY($1)", closed_ids)
            print(f"O'chirildi (faqat yopilganlar): {result}  ids={closed_ids}")
        else:
            print("Yopilgan holatda hech narsa topilmadi, hech narsa o'chirilmadi.")


asyncio.run(main())
