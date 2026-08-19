"""Bir martalik skript: oy boshidan yopilgan signallarni (faqat yakuniy foiz
ma'lum bo'lganlarni) bazaga kiritadi. Aniq entry/SL/TP/sana noma'lum bo'lgani
uchun bular soddalashtirilgan yozuvlar — R-multiple hisoblanmaydi (risk=0),
faqat win-rate va umumiy foiz statistikasi uchun.

Ishga tushirilgach o'zini o'chirib qo'ymaydi — startCommand qayta tiklangach
qayta ishlamaydi, chunki u faqat shu bir martalik deploy uchun chaqiriladi.
"""
import asyncio
import asyncpg
import config

MARKER = "manual-backfill-2026-08"

# (symbol, pnl_pct)
SIGNALS = [
    ("ARIAUSDT", 14), ("COAIUSDT", 35), ("ZILUSDT", -6), ("TNSRUSDT", 2),
    ("SWARMSUSDT", 47), ("EDUUSDT", 40), ("VIRTUALUSDT", -6), ("VANRYUSDT", -13),
    ("ACUUSDT", 32), ("2ZUSDT", -4), ("HOLOUSDT", 2), ("ENSOUSDT", 60),
    ("SUIUSDT", -5), ("DOSUSDT", -9),
]


async def main():
    pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=2)
    async with pool.acquire() as c:
        await c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id SERIAL PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL DEFAULT 'LONG',
            entry NUMERIC NOT NULL, sl NUMERIC NOT NULL, sl_initial NUMERIC NOT NULL,
            tps NUMERIC[] NOT NULL, tp_hit INT NOT NULL DEFAULT 0,
            filled_pct NUMERIC NOT NULL DEFAULT 0, realized_pct NUMERIC NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'PENDING', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            opened_at TIMESTAMPTZ, closed_at TIMESTAMPTZ, exit_price NUMERIC, pnl_pct NUMERIC,
            r_multiple NUMERIC, last_checked_ms BIGINT, ambiguous BOOLEAN NOT NULL DEFAULT FALSE,
            chart_file_id TEXT, group_msg_id BIGINT, author_id BIGINT, note TEXT
        );
        """)

        already = await c.fetchval("SELECT COUNT(*) FROM signals WHERE note=$1", MARKER)
        if already:
            print(f"Allaqachon kiritilgan ({already} ta) — qayta kiritilmaydi.")
            return

        for symbol, pnl in SIGNALS:
            status = "TP" if pnl > 0 else ("SL" if pnl < 0 else "BREAKEVEN")
            entry = 100
            exit_price = entry * (1 + pnl / 100)
            await c.execute("""
                INSERT INTO signals
                    (symbol, side, entry, sl, sl_initial, tps, tp_hit, filled_pct,
                     realized_pct, status, opened_at, closed_at, exit_price, pnl_pct, note)
                VALUES ($1,'LONG',$2,$2,$2,'{}',0,1,$3,$4, now(), now(), $5, $3, $6)
            """, symbol, entry, pnl, status, exit_price, MARKER)
            print(f"{symbol}: {pnl:+d}% -> {status}")

        print(f"Tayyor — {len(SIGNALS)} ta signal kiritildi.")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
