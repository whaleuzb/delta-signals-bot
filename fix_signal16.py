"""Bir martalik tuzatish: signal #16 (ALPINEUSDT) MEXC tarixida TP'ga
tegmagan ko'rsatilgan edi, lekin foydalanuvchi tasdiqladiki u haqiqatda
TP (0.400) ga yetib yopilgan (boshqa birjada kuzatilgan bo'lishi mumkin).
Qo'lda yopiq (TP) holatga o'tkazamiz.
"""
import asyncio
from decimal import Decimal

import config
import db

SIG_ID = 16
ENTRY = Decimal("0.324")
SL_INITIAL = Decimal("0.303")
EXIT_PRICE = Decimal("0.400")


async def main():
    pool = await db.init()
    pnl = (EXIT_PRICE - ENTRY) / ENTRY * 100
    risk = (ENTRY - SL_INITIAL) / ENTRY * 100
    r = pnl / risk
    pnl = round(pnl, 4)
    r = round(r, 3)

    async with pool.acquire() as c:
        row = await c.fetchrow(
            "UPDATE signals SET status='TP', tp_hit=1, filled_pct=1, "
            "realized_pct=$2, exit_price=$3, pnl_pct=$2, r_multiple=$4, "
            "closed_at=now(), "
            "note=COALESCE(note,'') || ' | qo''lda TP deb belgilandi (MEXC "
            "tarixi mos kelmadi, boshqa birjada kuzatilgan)' "
            "WHERE id=$1 RETURNING id, status, pnl_pct, r_multiple, closed_at",
            SIG_ID, pnl, EXIT_PRICE, r,
        )
        print(dict(row) if row else "Signal topilmadi!")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
