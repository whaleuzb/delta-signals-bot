"""Foydalanuvchilar o'rtasidagi turnirlar (185-band).

Foydalanuvchi talabi: "Guruh yoki kanallar emas, userlar orasida turnirlar
uyushtiramiz. Turnirni boshlashni admin panelga joylaysan. Turnir uchun
beriladigan alohida depozit men tomonimdan belgilanadi. Har bir odam
shaxsiy jurnal ichida turnirda qatnashish tugmasi bo'lsin. Men turnirga
start bersamgina bu funksiyalar ishlasin."

Egasi tanlagan qoidalar:
- Hajm: har savdoda turnir depozitidan summa so'raladi, BO'SH summadan
  oshmaydi. Natija = depozit + har savdoning pul natijasi.
- Tugash: boshlashda muddat (kun) belgilanadi, muddat tugagach avtomatik
  yakunlanadi; admin oldinroq ham tugata oladi.
- Yakunda ochiq pozitsiyalar joriy narxda hisoblanadi.
- Qo'shilgandan keyin shaxsiy jurnalda ochilgan HAR BIR signal turnirga
  avtomatik kiradi.

Firibgarlikka qarshi: summa faqat signal hali to'lmagan (PENDING) bo'lsa
yoki ochilganiga `AMOUNT_WINDOW` soniyadan oshmagan bo'lsa belgilanadi va
bir marta belgilangach O'ZGARMAYDI. Aks holda odam foydaga chiqib ketgan
savdoga keyin katta summa yozib qo'yardi. Admin `/tuzat` bilan chiqargan
(`excluded`) savdo turnirda ham sanalmaydi.

Hisob BITTA joyda (`_player_numbers`): bot `refresh()`ni jonli narx bilan
davriy chaqiradi va natijani `tournament_players`ga yozadi; veb va bot
ko'rinishlari faqat shu yozilgan qiymatlarni O'QIYDI.
"""
from datetime import datetime, timedelta, timezone

import db
import tracker

AMOUNT_WINDOW = 120            # soniya — ochilgan savdoga summa kiritish oynasi
OPEN = ("PENDING", "ACTIVE")

# Faol turnir keshi — menyu tugmasi (`main_menu_kb` sinxron) har safar
# bazaga murojaat qilmasligi uchun. `load_active()` ishga tushishda,
# boshlash/yakunlashda va `tournament_job`da yangilanadi.
ACTIVE = None


async def load_active():
    """Faol turnir (yoki None) — keshni ham yangilaydi."""
    global ACTIVE
    async with db.pool().acquire() as c:
        ACTIVE = await c.fetchrow(
            "SELECT * FROM tournaments WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1")
    return ACTIVE


async def start(deposit: float, days: int, admin_id: int):
    """Yangi turnir. Faol turnir bo'lsa None (unikal indeks ham himoya)."""
    if await load_active():
        return None
    ends = datetime.now(timezone.utc) + timedelta(days=days)
    async with db.pool().acquire() as c:
        try:
            await c.execute(
                "INSERT INTO tournaments (deposit, ends_at, created_by) VALUES ($1,$2,$3)",
                db._d(deposit), ends, admin_id)
        except Exception:
            return None
    return await load_active()


async def get(tid: int):
    async with db.pool().acquire() as c:
        return await c.fetchrow("SELECT * FROM tournaments WHERE id=$1", tid)


async def latest():
    """Veb uchun: faol turnir, bo'lmasa oxirgi yakunlangani."""
    async with db.pool().acquire() as c:
        return await c.fetchrow(
            "SELECT * FROM tournaments ORDER BY (status='ACTIVE') DESC, id DESC LIMIT 1")


async def past(limit: int = 12):
    async with db.pool().acquire() as c:
        return await c.fetch(
            "SELECT t.*, (SELECT COUNT(*) FROM tournament_players p "
            "WHERE p.tournament_id=t.id) AS n_players FROM tournaments t "
            "WHERE status='FINISHED' ORDER BY id DESC LIMIT $1", limit)


# ─────────────── Qatnashchilar ───────────────

async def player(tid: int, uid: int):
    async with db.pool().acquire() as c:
        return await c.fetchrow(
            "SELECT * FROM tournament_players WHERE tournament_id=$1 AND user_id=$2",
            tid, uid)


async def join(tid: int, uid: int, workspace_id: int) -> bool:
    """Qo'shiladi (allaqachon qo'shilgan bo'lsa False). Boshlang'ich
    natija = depozit, shunda reytingda darhol ko'rinadi."""
    t = await get(tid)
    if not t or t["status"] != "ACTIVE":
        return False
    async with db.pool().acquire() as c:
        r = await c.execute(
            "INSERT INTO tournament_players (tournament_id, user_id, workspace_id, equity, "
            "updated_at) VALUES ($1,$2,$3,$4,now()) ON CONFLICT DO NOTHING",
            tid, uid, workspace_id, t["deposit"])
    return r.endswith("1")


async def player_count(tid: int) -> int:
    async with db.pool().acquire() as c:
        return await c.fetchval(
            "SELECT COUNT(*) FROM tournament_players WHERE tournament_id=$1", tid)


# ─────────────── Savdolar ───────────────

async def register_signal(sig) -> bool:
    """Shaxsiy jurnalda yangi signal yaratilganda chaqiriladi: egasi faol
    turnir qatnashchisi bo'lsa — turnir savdosi sifatida yoziladi."""
    t = ACTIVE
    if not t:
        return False
    async with db.pool().acquire() as c:
        p = await c.fetchrow(
            "SELECT * FROM tournament_players WHERE tournament_id=$1 AND user_id=$2",
            t["id"], sig["author_id"])
        if not p or p["workspace_id"] != sig["workspace_id"]:
            return False
        await c.execute(
            "INSERT INTO tournament_trades (signal_id, tournament_id, user_id) "
            "VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", sig["id"], t["id"], sig["author_id"])
    return True


async def trade(sig_id: int):
    async with db.pool().acquire() as c:
        return await c.fetchrow(
            "SELECT tt.*, t.status AS t_status, t.deposit FROM tournament_trades tt "
            "JOIN tournaments t ON t.id = tt.tournament_id WHERE tt.signal_id=$1", sig_id)


def can_set_amount(sig, tr, now=None) -> str | None:
    """Summa kiritib bo'lmasa — sabab kaliti (i18n), bo'lsa None."""
    if tr is None or tr["t_status"] != "ACTIVE":
        return "tr.err_closed"
    if tr["amount"] is not None:
        return "tr.err_already"
    if sig["status"] == "PENDING":
        return None
    if sig["status"] != "ACTIVE":
        return "tr.err_late"
    now = now or datetime.now(timezone.utc)
    if (now - sig["created_at"]).total_seconds() > AMOUNT_WINDOW:
        return "tr.err_late"
    return None


async def balance(tid: int, uid: int) -> tuple[float, float, float]:
    """(balans, band, bo'sh). Balans = depozit + yopilgan savdolar natijasi;
    band = ochiq (PENDING/ACTIVE) savdolarga ajratilgan summa."""
    async with db.pool().acquire() as c:
        dep = float(await c.fetchval("SELECT deposit FROM tournaments WHERE id=$1", tid))
        rows = await c.fetch(
            "SELECT tt.amount, s.status, s.pnl_pct, s.excluded "
            "FROM tournament_trades tt JOIN signals s ON s.id = tt.signal_id "
            "WHERE tt.tournament_id=$1 AND tt.user_id=$2 AND tt.amount IS NOT NULL",
            tid, uid)
    realized = busy = 0.0
    for r in rows:
        if r["excluded"]:
            continue
        amt = float(r["amount"])
        if r["status"] in OPEN:
            busy += amt
        elif r["pnl_pct"] is not None and r["status"] not in ("CANCELLED", "EXPIRED"):
            realized += float(r["pnl_pct"]) / 100 * amt
    bal = dep + realized
    return bal, busy, max(0.0, bal - busy)


async def set_amount(sig_id: int, uid: int, amount: float) -> tuple[bool, str | None]:
    """Summani BIR MARTA belgilaydi. (True, None) yoki (False, sabab)."""
    sig = await db.get_signal(sig_id)
    tr = await trade(sig_id)
    if not sig or not tr or tr["user_id"] != uid:
        return False, "tr.err_closed"
    why = can_set_amount(sig, tr)
    if why:
        return False, why
    if amount <= 0:
        return False, "tr.err_amount"
    _, _, free = await balance(tr["tournament_id"], uid)
    if amount > free + 1e-9:
        return False, "tr.err_over"
    async with db.pool().acquire() as c:
        r = await c.execute(
            "UPDATE tournament_trades SET amount=$2 WHERE signal_id=$1 AND amount IS NULL",
            sig_id, db._d(amount))
    return (True, None) if r.endswith("1") else (False, "tr.err_already")


# ─────────────── Reyting ───────────────

def _trade_pct(s, price: float | None) -> float:
    """Bitta savdoning hozirgi (yoki yakuniy) foizi. Yopilgan — `pnl_pct`;
    ochiq — qisman yopilgan qism + qolgan qism jonli narxda (boshqaruv
    ekranidagi `live` bilan AYNI formula); to'lmagan/bekor — 0."""
    if s["status"] in ("CANCELLED", "EXPIRED", "PENDING"):
        return 0.0
    if s["status"] == "ACTIVE":
        realized = float(s["realized_pct"] or 0)
        if price is None:
            return realized
        filled = float(s["filled_pct"] or 0)
        return realized + max(0.0, 1.0 - filled) * tracker.pnl_at(
            s["side"], float(s["entry"]), price)
    return float(s["pnl_pct"] or 0)


async def compute(tid: int, price_fn) -> list[dict]:
    """Barcha qatnashchilar natijasi, reyting tartibida. `price_fn(market,
    symbol)` — async, narx yoki None (bot: `safe_last_price`)."""
    return (await _compute(tid, price_fn))[0]


async def _compute(tid: int, price_fn) -> tuple[list[dict], list[tuple]]:
    """(reyting, ochiq savdolarning jonli holati [(signal_id, foiz, narx)]).
    Ikkalasi BITTA narx to'plamidan — veb ko'rsatadigan pozitsiya foizi
    reytingdagi pul natijasi bilan doim mos keladi."""
    t = await get(tid)
    dep = float(t["deposit"])
    async with db.pool().acquire() as c:
        players = await c.fetch(
            "SELECT user_id, joined_at FROM tournament_players WHERE tournament_id=$1", tid)
        rows = await c.fetch(
            "SELECT tt.user_id, tt.amount, s.* FROM tournament_trades tt "
            "JOIN signals s ON s.id = tt.signal_id "
            "WHERE tt.tournament_id=$1 AND tt.amount IS NOT NULL AND NOT s.excluded", tid)
    prices = {}
    for r in rows:
        if r["status"] == "ACTIVE":
            key = (r["market"], r["symbol"])
            if key not in prices:
                prices[key] = await price_fn(*key)
    acc = {p["user_id"]: {"user_id": p["user_id"], "joined_at": p["joined_at"],
                          "money": 0.0, "trades": 0, "wins": 0} for p in players}
    live = []
    for r in rows:
        a = acc.get(r["user_id"])
        if a is None or r["status"] in ("CANCELLED", "EXPIRED"):
            continue
        price = prices.get((r["market"], r["symbol"]))
        pct = _trade_pct(r, price)
        if r["status"] == "ACTIVE":
            live.append((r["id"], pct, price))
        a["money"] += pct / 100 * float(r["amount"])
        if r["status"] != "PENDING":
            a["trades"] += 1
            if r["status"] not in OPEN and float(r["pnl_pct"] or 0) > 0:
                a["wins"] += 1
    out = sorted(acc.values(), key=lambda a: (-a["money"], a["joined_at"]))
    for i, a in enumerate(out, 1):
        a["equity"] = dep + a["money"]
        a["rank"] = i
    return out, live


async def refresh(tid: int, price_fn) -> list[dict]:
    """`compute` natijasini bazaga yozadi (faqat faol turnirda)."""
    res, live = await _compute(tid, price_fn)
    async with db.pool().acquire() as c:
        async with c.transaction():
            if (await c.fetchval("SELECT status FROM tournaments WHERE id=$1", tid)) != "ACTIVE":
                return res
            for sid, pct, price in live:
                # Narx olinmagan bo'lsa oldingi narx saqlanadi (foiz baribir
                # yangilanadi — unda faqat qisman yopilgan qism bor).
                await c.execute(
                    "UPDATE tournament_trades SET live_pct=$2, "
                    "live_price=COALESCE($3, live_price) WHERE signal_id=$1",
                    sid, db._d(pct), db._d(price) if price is not None else None)
            for a in res:
                await c.execute(
                    "UPDATE tournament_players SET equity=$3, trades=$4, wins=$5, rank=$6, "
                    "updated_at=now() WHERE tournament_id=$1 AND user_id=$2",
                    tid, a["user_id"], db._d(a["equity"]), a["trades"], a["wins"], a["rank"])
    return res


async def finish(tid: int, price_fn) -> list[dict] | None:
    """Yakunlash: oxirgi marta jonli narxda hisoblab QOTIRADI. Allaqachon
    yakunlangan bo'lsa None (ikki marta chaqirilsa ham xavfsiz)."""
    t = await get(tid)
    if not t or t["status"] != "ACTIVE":
        return None
    res = await refresh(tid, price_fn)
    async with db.pool().acquire() as c:
        r = await c.execute(
            "UPDATE tournaments SET status='FINISHED', finished_at=now() "
            "WHERE id=$1 AND status='ACTIVE'", tid)
    await load_active()
    return res if r.endswith("1") else None


async def open_positions(tid: int):
    """Vebdagi "Ochiq pozitsiyalar" (186): turnirga kirgan (summasi
    belgilangan), hali ochiq savdolar — kim, nima, qancha va jonli
    natijasi. Hisobdan chiqarilgan (`excluded`) savdolar ko'rsatilmaydi."""
    async with db.pool().acquire() as c:
        return await c.fetch(
            "SELECT tt.user_id, tt.amount, tt.live_pct, tt.live_price, s.id, s.symbol, "
            "s.side, s.entry, s.sl, s.tps, s.tp_hit, s.status, s.opened_at, s.created_at, "
            "u.username, u.first_name FROM tournament_trades tt "
            "JOIN signals s ON s.id = tt.signal_id "
            "LEFT JOIN users u ON u.user_id = tt.user_id "
            "WHERE tt.tournament_id=$1 AND tt.amount IS NOT NULL AND NOT s.excluded "
            "AND s.status IN ('PENDING','ACTIVE') "
            "ORDER BY (s.status='ACTIVE') DESC, COALESCE(s.opened_at, s.created_at) DESC", tid)


async def standings(tid: int, limit: int | None = None):
    """Yozilgan reyting (veb va bot ko'rinishlari uchun) — ism bilan."""
    q = ("SELECT p.*, u.username, u.first_name FROM tournament_players p "
         "LEFT JOIN users u ON u.user_id = p.user_id WHERE p.tournament_id=$1 "
         "ORDER BY p.rank NULLS LAST, p.equity DESC NULLS LAST, p.joined_at")
    async with db.pool().acquire() as c:
        if limit:
            return await c.fetch(q + " LIMIT $2", tid, limit)
        return await c.fetch(q, tid)


def display_name(r) -> str:
    """Reytingdagi ism: @username, bo'lmasa ism, bo'lmasa qisqartirilgan ID."""
    if r["username"]:
        return "@" + r["username"]
    if r["first_name"]:
        return r["first_name"]
    return f"#{str(r['user_id'])[-4:]}"
