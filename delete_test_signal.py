"""Bir martalik skript: test uchun yuborilgan BTCUSDT signal(lar)ni
bazadan butunlay o'chiradi (CANCELLED emas — to'liq DELETE)."""
import asyncio

import config
import db


async def main():
    pool = await db.init()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT id, symbol, status FROM signals WHERE symbol='BTCUSDT'")
        if not rows:
            print("BTCUSDT topilmadi.")
        else:
            for r in rows:
                print(f"O'chirilmoqda: #{r['id']} {r['symbol']} {r['status']}")
            await c.execute("DELETE FROM signals WHERE symbol='BTCUSDT'")
            print(f"{len(rows)} ta yozuv o'chirildi.")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
