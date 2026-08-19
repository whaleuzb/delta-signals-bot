"""PostgreSQL qatlami — schema va so'rovlar."""
from decimal import Decimal

import asyncpg
import config


def _d(x):
    """asyncpg NUMERIC ustunga float qabul qilmaydi — Decimal ga o'giramiz."""
    if x is None:
        return None
    return Decimal(str(x))

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id              SERIAL PRIMARY KEY,
    symbol          TEXT        NOT NULL,
    side            TEXT        NOT NULL DEFAULT 'LONG',
    entry           NUMERIC     NOT NULL,
    sl              NUMERIC     NOT NULL,          -- joriy stop (BE ga ko'chishi mumkin)
    sl_initial      NUMERIC     NOT NULL,          -- R hisobi uchun asl stop
    tps             NUMERIC[]   NOT NULL,
    tp_hit          INT         NOT NULL DEFAULT 0,
    filled_pct      NUMERIC     NOT NULL DEFAULT 0,   -- pozitsiyaning sotilgan ulushi (0..1)
    realized_pct    NUMERIC     NOT NULL DEFAULT 0,   -- to'plangan foiz
    status          TEXT        NOT NULL DEFAULT 'PENDING',
    -- PENDING | ACTIVE | TP | SL | BREAKEVEN | EXPIRED | CANCELLED
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    opened_at       TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    exit_price      NUMERIC,
    pnl_pct         NUMERIC,
    r_multiple      NUMERIC,
    last_checked_ms BIGINT,
    ambiguous       BOOLEAN     NOT NULL DEFAULT FALSE,  -- TP va SL bitta shamda
    chart_file_id   TEXT,
    group_msg_id    BIGINT,
    author_id       BIGINT,
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_closed ON signals(closed_at);
"""


async def init() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=5)
    async with _pool.acquire() as c:
        await c.execute(SCHEMA)
    return _pool


def pool() -> asyncpg.Pool:
    assert _pool is not None, "db.init() chaqirilmagan"
    return _pool


async def create_signal(d: dict) -> int:
    q = """
    INSERT INTO signals (symbol, side, entry, sl, sl_initial, tps,
                         chart_file_id, author_id, note)
    VALUES ($1,$2,$3,$4,$4,$5,$6,$7,$8) RETURNING id
    """
    async with pool().acquire() as c:
        return await c.fetchval(
            q, d["symbol"], d["side"], _d(d["entry"]), _d(d["sl"]),
            [_d(t) for t in d["tps"]],
            d.get("chart_file_id"), d.get("author_id"), d.get("note"),
        )


async def set_group_msg(sig_id: int, msg_id: int) -> None:
    async with pool().acquire() as c:
        await c.execute("UPDATE signals SET group_msg_id=$2 WHERE id=$1", sig_id, msg_id)


async def live_signals() -> list[asyncpg.Record]:
    async with pool().acquire() as c:
        return await c.fetch(
            "SELECT * FROM signals WHERE status IN ('PENDING','ACTIVE') ORDER BY id"
        )


async def get_signal(sig_id: int) -> asyncpg.Record | None:
    async with pool().acquire() as c:
        return await c.fetchrow("SELECT * FROM signals WHERE id=$1", sig_id)


async def save_progress(sig_id: int, f: dict) -> None:
    q = """
    UPDATE signals SET
        sl=$2, tp_hit=$3, filled_pct=$4, realized_pct=$5, status=$6,
        opened_at=COALESCE(opened_at,$7), closed_at=$8, exit_price=$9,
        pnl_pct=$10, r_multiple=$11, last_checked_ms=$12, ambiguous=$13
    WHERE id=$1
    """
    async with pool().acquire() as c:
        await c.execute(
            q, sig_id, _d(f["sl"]), f["tp_hit"], _d(f["filled_pct"]), _d(f["realized_pct"]),
            f["status"], f.get("opened_at"), f.get("closed_at"), _d(f.get("exit_price")),
            _d(f.get("pnl_pct")), _d(f.get("r_multiple")), f["last_checked_ms"], f["ambiguous"],
        )


async def cancel_signal(sig_id: int, status: str = "CANCELLED") -> bool:
    async with pool().acquire() as c:
        r = await c.execute(
            "UPDATE signals SET status=$2, closed_at=now() "
            "WHERE id=$1 AND status IN ('PENDING','ACTIVE')",
            sig_id, status,
        )
    return r.endswith("1")


CLOSED = "('TP','SL','BREAKEVEN')"


async def period_stats(since=None, until=None) -> asyncpg.Record:
    q = f"""
    SELECT
        COUNT(*)                                            AS total,
        COUNT(*) FILTER (WHERE pnl_pct > 0)                  AS wins,
        COUNT(*) FILTER (WHERE pnl_pct < 0)                  AS losses,
        COUNT(*) FILTER (WHERE pnl_pct = 0)                  AS be,
        COALESCE(SUM(pnl_pct), 0)                            AS sum_pct,
        COALESCE(AVG(pnl_pct) FILTER (WHERE pnl_pct > 0), 0) AS avg_win,
        COALESCE(AVG(pnl_pct) FILTER (WHERE pnl_pct < 0), 0) AS avg_loss,
        COALESCE(AVG(r_multiple), 0)                         AS avg_r,
        COALESCE(SUM(r_multiple), 0)                         AS sum_r
    FROM signals
    WHERE status IN {CLOSED}
      AND ($1::timestamptz IS NULL OR closed_at >= $1)
      AND ($2::timestamptz IS NULL OR closed_at <  $2)
    """
    async with pool().acquire() as c:
        return await c.fetchrow(q, since, until)


async def monthly_breakdown(limit: int = 12) -> list[asyncpg.Record]:
    q = f"""
    SELECT date_trunc('month', closed_at AT TIME ZONE '{config.TZ}') AS month,
           COUNT(*) AS total,
           COUNT(*) FILTER (WHERE pnl_pct > 0) AS wins,
           ROUND(COALESCE(SUM(pnl_pct),0), 2) AS sum_pct,
           ROUND(COALESCE(AVG(r_multiple),0), 2) AS avg_r
    FROM signals WHERE status IN {CLOSED}
    GROUP BY 1 ORDER BY 1 DESC LIMIT $1
    """
    async with pool().acquire() as c:
        return await c.fetch(q, limit)


async def equity_series() -> list[asyncpg.Record]:
    async with pool().acquire() as c:
        return await c.fetch(
            f"SELECT closed_at, pnl_pct FROM signals "
            f"WHERE status IN {CLOSED} ORDER BY closed_at"
        )


async def top_symbols(since=None, until=None, limit: int | None = None) -> list[asyncpg.Record]:
    """Juftlik bo'yicha yopilgan (TP/SL/BREAKEVEN) signallar kesimi.
    since/until berilsa — faqat shu oraliqda YOPILGAN signallar (closed_at bo'yicha).
    Hali ochiq (PENDING/ACTIVE) signal hech qaysi oraliqqa tushmaydi — u yopilgan
    paytidagi oyga avtomatik o'tadi."""
    where = f"status IN {CLOSED}"
    params = []
    if since is not None:
        params.append(since)
        where += f" AND closed_at >= ${len(params)}"
    if until is not None:
        params.append(until)
        where += f" AND closed_at < ${len(params)}"
    limit_sql = ""
    if limit:
        params.append(limit)
        limit_sql = f"LIMIT ${len(params)}"
    q = f"""
    SELECT symbol, COUNT(*) AS closed,
           COUNT(*) FILTER (WHERE pnl_pct > 0) AS wins,
           ROUND(COALESCE(SUM(pnl_pct),0), 2) AS sum_pct
    FROM signals WHERE {where}
    GROUP BY symbol ORDER BY sum_pct DESC {limit_sql}
    """
    async with pool().acquire() as c:
        return await c.fetch(q, *params)


async def open_symbols_count() -> dict[str, int]:
    """Har bir juftlik bo'yicha hozir ochiq (PENDING/ACTIVE) signallar soni."""
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT symbol, COUNT(*) AS n FROM signals "
            "WHERE status IN ('PENDING','ACTIVE') GROUP BY symbol"
        )
    return {r["symbol"]: r["n"] for r in rows}
