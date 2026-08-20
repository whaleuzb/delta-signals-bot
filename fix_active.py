"""Bir martalik: BIDUSDT va PARTIUSDT PENDING'da qolib ketgan (aslida narx
entry darajasidan allaqachon o'tib ketgan) - ACTIVE holatga qo'lda o'tkazish.
Ishga tushirilgach o'chiriladi."""
import asyncio
from datetime import datetime, timezone

import config
import db
import exchange

SYMBOLS = ("BIDUSDT", "PARTIUSDT")


async def main():
    await db.init()
    pool = db.pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            "SELECT id, workspace_id, symbol, side, entry, sl, status, market, created_at "
            "FROM signals WHERE symbol = ANY($1) AND status = 'PENDING' ORDER BY id",
            list(SYMBOLS),
        )
        print(f"Topildi: {len(rows)} ta PENDING signal")
        for r in rows:
            price = await exchange.last_price(r["symbol"]) if r["market"] == "crypto" else None
            print(f"  #{r['id']} ws={r['workspace_id']} {r['symbol']} {r['side']} "
                  f"entry={r['entry']} sl={r['sl']} joriy_narx={price} created_at={r['created_at']}")

        if rows:
            ids = [r["id"] for r in rows]
            now = datetime.now(timezone.utc)
            result = await c.execute(
                "UPDATE signals SET status='ACTIVE', opened_at=COALESCE(opened_at,$2) "
                "WHERE id = ANY($1)",
                ids, now,
            )
            print(f"Yangilandi: {result}  ids={ids}")
        else:
            print("Hech narsa topilmadi.")
    await exchange.close()


asyncio.run(main())
