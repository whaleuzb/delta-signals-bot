"""PostgreSQL qatlami — schema va so'rovlar.

Multi-tenant: har bir signal bitta workspace'ga tegishli.
  - type='group'    — Telegram guruhi, /setup orqali ro'yxatdan o'tgan.
                       group_chat_id/group_topic_id'ga signal e'lon qilinadi,
                       shu guruh a'zolari statistikani ko'ra oladi.
  - type='personal' — shaxsiy jurnal, hech qayerga e'lon qilinmaydi,
                       faqat owner_id o'zi ko'ra oladi.
"""
from datetime import datetime, timezone
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
CREATE TABLE IF NOT EXISTS workspaces (
    id              SERIAL PRIMARY KEY,
    type            TEXT        NOT NULL,   -- 'group' | 'personal'
    owner_id        BIGINT      NOT NULL,   -- shu workspace admini (yagona)
    group_chat_id   BIGINT,                 -- faqat type='group'
    group_topic_id  BIGINT,                 -- ixtiyoriy, forum mavzusi
    name            TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_chat_id),
    UNIQUE (owner_id, type)  -- bitta odam — bitta shaxsiy, bitta guruh workspace
);

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

-- Guruh a'zosi (egasi emas) DM'da shu guruhni oddiy ko'ruvchi sifatida tanlagan
-- bo'lsa shu yerda saqlanadi — faqat DM'da qaysi workspace'ni ko'rsatishni
-- ESLAB QOLISH uchun (marshrutlash), haqiqiy ruxsat emas: har safar can_view()
-- baribir guruh a'zoligini jonli tekshiradi, shuning uchun a'zolikdan chiqib
-- ketsa bu yozuv bo'lsa ham ko'rish avtomatik yopiladi.
CREATE TABLE IF NOT EXISTS group_viewers (
    user_id      BIGINT      NOT NULL,
    workspace_id INT         NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, workspace_id)
);

-- /start ref_<uid> deep-link orqali kim kimni taklif qilganini saqlaydi. Bitta
-- odam faqat bitta marta "taklif qilingan" bo'la oladi (birinchi havola g'olib).
CREATE TABLE IF NOT EXISTS referrals (
    referrer_id BIGINT      NOT NULL,
    referred_id BIGINT      NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# signals.workspace_id — ALTER orqali qo'shiladi (yangi ustun eski jadvalga ham,
# yangi jadvalga ham bir xil yo'l bilan qo'shilishi uchun; CREATE TABLE IF NOT
# EXISTS eski (allaqachon mavjud) jadvalni o'zgartira olmaydi). Boshida NULL
# qabul qiladi — mavjud yozuvlar workspace'ga bog'langach, bir martalik
# migratsiya skripti uni NOT NULL qiladi.
MIGRATE = """
ALTER TABLE signals ADD COLUMN IF NOT EXISTS workspace_id INT REFERENCES workspaces(id);
CREATE INDEX IF NOT EXISTS idx_signals_workspace ON signals(workspace_id);

-- Real (kapitalga bog'liq) PnL: workspace o'z umumiy depozitini belgilaydi,
-- har bir signalga necha pul ishlatilgani alohida yoziladi. Ikkalasi ham
-- ixtiyoriy (NULL) — depozit belgilanmagan workspace'larda eski, sof foizli
-- statistika ishlayveradi, hech narsa buzilmaydi.
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS deposit NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS alloc_amount NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS deposit_snapshot NUMERIC;

-- 'crypto' (MEXC, exchange.py) | 'forex' (Twelve Data, forex.py) — tracker.py
-- shunga qarab qaysi narx manbasidan shamlarni olishni tanlaydi.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS market TEXT NOT NULL DEFAULT 'crypto';

-- 'limit' (standart) — narx kirish darajasiga tegmaguncha PENDING qoladi (tracker.py
-- buni o'zi tekshiradi). 'market' — signal DARHOL ACTIVE holatda yaratiladi (status/
-- opened_at pastda create_signal() ichida to'g'ridan-to'g'ri o'rnatiladi) — tracker.py
-- ga tegilmaydi, u faqat SL/TP'ni kuzatishda davom etadi.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS entry_mode TEXT NOT NULL DEFAULT 'limit';

-- Guruh admini o'zi yoqsagina /top reytingida ko'rinadi (standart — YASHIRIN).
-- Shaxsiy workspace'lar reytingga umuman kirmaydi (faqat type='group' hisobga olinadi).
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS public BOOLEAN NOT NULL DEFAULT FALSE;
"""


async def init() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=5)
    async with _pool.acquire() as c:
        await c.execute(SCHEMA)
        await c.execute(MIGRATE)
    return _pool


def pool() -> asyncpg.Pool:
    assert _pool is not None, "db.init() chaqirilmagan"
    return _pool


# ─────────────────────────── Workspace'lar ───────────────────────────

async def create_group_workspace(owner_id: int, chat_id: int, name: str,
                                  topic_id: int | None = None) -> int:
    async with pool().acquire() as c:
        return await c.fetchval(
            "INSERT INTO workspaces (type, owner_id, group_chat_id, group_topic_id, name) "
            "VALUES ('group', $1, $2, $3, $4) RETURNING id",
            owner_id, chat_id, topic_id, name,
        )


async def get_or_create_personal_workspace(owner_id: int, name: str) -> asyncpg.Record:
    async with pool().acquire() as c:
        row = await c.fetchrow(
            "SELECT * FROM workspaces WHERE type='personal' AND owner_id=$1", owner_id)
        if row:
            return row
        wid = await c.fetchval(
            "INSERT INTO workspaces (type, owner_id, name) VALUES ('personal', $1, $2) "
            "RETURNING id", owner_id, name,
        )
        return await c.fetchrow("SELECT * FROM workspaces WHERE id=$1", wid)


async def get_personal_workspace(owner_id: int) -> asyncpg.Record | None:
    """Faqat tekshiradi, yaratmaydi — birinchi murojaatda onboarding ko'rsatish uchun."""
    async with pool().acquire() as c:
        return await c.fetchrow(
            "SELECT * FROM workspaces WHERE type='personal' AND owner_id=$1", owner_id)


async def get_workspace(workspace_id: int) -> asyncpg.Record | None:
    async with pool().acquire() as c:
        return await c.fetchrow("SELECT * FROM workspaces WHERE id=$1", workspace_id)


async def get_workspace_by_group(chat_id: int) -> asyncpg.Record | None:
    async with pool().acquire() as c:
        return await c.fetchrow("SELECT * FROM workspaces WHERE group_chat_id=$1", chat_id)


async def get_group_workspace_by_owner(owner_id: int) -> asyncpg.Record | None:
    async with pool().acquire() as c:
        return await c.fetchrow(
            "SELECT * FROM workspaces WHERE type='group' AND owner_id=$1", owner_id)


async def set_workspace_topic(workspace_id: int, topic_id: int | None) -> None:
    async with pool().acquire() as c:
        await c.execute(
            "UPDATE workspaces SET group_topic_id=$2 WHERE id=$1", workspace_id, topic_id)


async def list_group_workspaces() -> list[asyncpg.Record]:
    """Barcha ro'yxatdan o'tgan guruh workspace'lari — "men a'zoman" tanlovi uchun."""
    async with pool().acquire() as c:
        return await c.fetch("SELECT * FROM workspaces WHERE type='group' ORDER BY name")


async def add_group_viewer(user_id: int, workspace_id: int) -> None:
    async with pool().acquire() as c:
        await c.execute(
            "INSERT INTO group_viewers (user_id, workspace_id) VALUES ($1,$2) "
            "ON CONFLICT DO NOTHING", user_id, workspace_id)


async def get_group_viewer_workspaces(user_id: int) -> list[asyncpg.Record]:
    async with pool().acquire() as c:
        return await c.fetch(
            "SELECT w.* FROM group_viewers v JOIN workspaces w ON w.id = v.workspace_id "
            "WHERE v.user_id=$1 ORDER BY w.name", user_id)


async def is_group_viewer(user_id: int, workspace_id: int) -> bool:
    async with pool().acquire() as c:
        row = await c.fetchval(
            "SELECT 1 FROM group_viewers WHERE user_id=$1 AND workspace_id=$2",
            user_id, workspace_id)
    return row is not None


async def set_deposit(workspace_id: int, amount: float) -> None:
    async with pool().acquire() as c:
        await c.execute(
            "UPDATE workspaces SET deposit=$2 WHERE id=$1", workspace_id, _d(amount))


async def set_public(workspace_id: int, public: bool) -> None:
    async with pool().acquire() as c:
        await c.execute("UPDATE workspaces SET public=$2 WHERE id=$1", workspace_id, public)


# ─────────────────────────── Referrallar ───────────────────────────

async def add_referral(referrer_id: int, referred_id: int) -> None:
    async with pool().acquire() as c:
        await c.execute(
            "INSERT INTO referrals (referrer_id, referred_id) VALUES ($1,$2) "
            "ON CONFLICT (referred_id) DO NOTHING", referrer_id, referred_id)


async def count_referrals(referrer_id: int) -> int:
    async with pool().acquire() as c:
        return await c.fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id=$1", referrer_id)


# ─────────────────────────── Signallar ───────────────────────────

async def create_signal(workspace_id: int, d: dict) -> int:
    """entry_mode='market' bo'lsa signal PENDING emas, DARHOL ACTIVE holatda
    yaratiladi (opened_at=hozir) — tracker.py buni kutmaydi, faqat SL/TP
    kuzatuvini davom ettiradi (BUZILMASIN #14-15 uchun tracker.py o'zgarmagan)."""
    entry_mode = d.get("entry_mode", "limit")
    is_market = entry_mode == "market"
    status = "ACTIVE" if is_market else "PENDING"
    opened_at = datetime.now(timezone.utc) if is_market else None
    q = """
    INSERT INTO signals (workspace_id, symbol, side, entry, sl, sl_initial, tps,
                         chart_file_id, author_id, note, market, entry_mode,
                         status, opened_at)
    VALUES ($1,$2,$3,$4,$5,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id
    """
    async with pool().acquire() as c:
        return await c.fetchval(
            q, workspace_id, d["symbol"], d["side"], _d(d["entry"]), _d(d["sl"]),
            [_d(t) for t in d["tps"]],
            d.get("chart_file_id"), d.get("author_id"), d.get("note"),
            d.get("market", "crypto"), entry_mode, status, opened_at,
        )


async def set_group_msg(sig_id: int, msg_id: int) -> None:
    async with pool().acquire() as c:
        await c.execute("UPDATE signals SET group_msg_id=$2 WHERE id=$1", sig_id, msg_id)


async def set_signal_allocation(sig_id: int, alloc_amount: float, deposit_snapshot: float) -> None:
    """Signal tasdiqlangach, unga necha pul ishlatilganini yozadi. deposit_snapshot —
    o'sha paytdagi umumiy depozit (keyinchalik depozit o'zgarsa ham bu signal real
    hisobi o'zgarmasin uchun)."""
    async with pool().acquire() as c:
        await c.execute(
            "UPDATE signals SET alloc_amount=$2, deposit_snapshot=$3 WHERE id=$1",
            sig_id, _d(alloc_amount), _d(deposit_snapshot))


async def live_signals(workspace_id: int | None = None) -> list[asyncpg.Record]:
    """workspace_id berilmasa — BARCHA workspace'lardagi ochiq signallar (kuzatuv
    sikli uchun; u har birini o'z workspace_id'si bilan qaytaradi)."""
    async with pool().acquire() as c:
        if workspace_id is None:
            return await c.fetch(
                "SELECT * FROM signals WHERE status IN ('PENDING','ACTIVE') ORDER BY id")
        return await c.fetch(
            "SELECT * FROM signals WHERE workspace_id=$1 "
            "AND status IN ('PENDING','ACTIVE') ORDER BY id", workspace_id)


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


async def period_stats(workspace_id: int, since=None, until=None) -> asyncpg.Record:
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
        COALESCE(SUM(r_multiple), 0)                         AS sum_r,
        SUM(pnl_pct / 100 * alloc_amount) FILTER (WHERE alloc_amount IS NOT NULL)
                                                              AS real_pnl_money
    FROM signals
    WHERE workspace_id = $1 AND status IN {CLOSED}
      AND ($2::timestamptz IS NULL OR closed_at >= $2)
      AND ($3::timestamptz IS NULL OR closed_at <  $3)
    """
    async with pool().acquire() as c:
        return await c.fetchrow(q, workspace_id, since, until)


async def monthly_breakdown(workspace_id: int, limit: int = 12) -> list[asyncpg.Record]:
    q = f"""
    SELECT date_trunc('month', closed_at AT TIME ZONE '{config.TZ}') AS month,
           COUNT(*) AS total,
           COUNT(*) FILTER (WHERE pnl_pct > 0) AS wins,
           ROUND(COALESCE(SUM(pnl_pct),0), 2) AS sum_pct,
           ROUND(COALESCE(AVG(r_multiple),0), 2) AS avg_r
    FROM signals WHERE workspace_id=$1 AND status IN {CLOSED}
    GROUP BY 1 ORDER BY 1 DESC LIMIT $2
    """
    async with pool().acquire() as c:
        return await c.fetch(q, workspace_id, limit)


async def equity_series(workspace_id: int) -> list[asyncpg.Record]:
    async with pool().acquire() as c:
        return await c.fetch(
            f"SELECT closed_at, pnl_pct FROM signals "
            f"WHERE workspace_id=$1 AND status IN {CLOSED} ORDER BY closed_at",
            workspace_id,
        )


async def top_symbols(workspace_id: int, since=None, until=None,
                       limit: int | None = None) -> list[asyncpg.Record]:
    """Juftlik bo'yicha yopilgan (TP/SL/BREAKEVEN) signallar kesimi.
    since/until berilsa — faqat shu oraliqda YOPILGAN signallar (closed_at bo'yicha).
    Hali ochiq (PENDING/ACTIVE) signal hech qaysi oraliqqa tushmaydi — u yopilgan
    paytidagi oyga avtomatik o'tadi."""
    where = f"workspace_id = $1 AND status IN {CLOSED}"
    params = [workspace_id]
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


async def top_workspaces(since, until, limit: int = 10) -> list[asyncpg.Record]:
    """/top reytingi uchun — faqat public=TRUE guruh workspace'lari, shu davrda
    yopilgan signallar bo'yicha. Shaxsiy workspace'lar reytingga kirmaydi."""
    q = f"""
    SELECT w.id, w.name, COUNT(*) AS total,
           COUNT(*) FILTER (WHERE s.pnl_pct > 0) AS wins,
           COALESCE(SUM(s.pnl_pct), 0) AS sum_pct
    FROM signals s
    JOIN workspaces w ON w.id = s.workspace_id
    WHERE w.type = 'group' AND w.public = TRUE AND s.status IN {CLOSED}
      AND s.closed_at >= $1 AND s.closed_at < $2
    GROUP BY w.id, w.name
    ORDER BY sum_pct DESC
    LIMIT $3
    """
    async with pool().acquire() as c:
        return await c.fetch(q, since, until, limit)


async def open_signals_summary(workspace_id: int) -> dict[str, dict]:
    """Har bir juftlik bo'yicha ochiq signallar: 'pending' (hali entry/limitga
    bormagan, kutilmoqda) soni va 'active' (allaqachon ochilgan, ishlayotgan)
    ro'yxati — side/entry/market bilan, chaqiruvchi shundan joriy (live) foizni
    hisoblay olishi uchun."""
    async with pool().acquire() as c:
        rows = await c.fetch(
            "SELECT symbol, status, side, entry, market FROM signals "
            "WHERE workspace_id=$1 AND status IN ('PENDING','ACTIVE')",
            workspace_id,
        )
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["symbol"], {"pending": 0, "active": []})
        if r["status"] == "PENDING":
            d["pending"] += 1
        else:
            d["active"].append({"side": r["side"], "entry": float(r["entry"]), "market": r["market"]})
    return out
