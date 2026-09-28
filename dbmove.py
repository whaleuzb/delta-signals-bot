"""Bir martalik baza ko'chirish (196).

Eski Postgres 19-avgustdan beri doimiy DISKSIZ ishlagan (disk ulash
Railway'da "staged" holatda qolib ketgan) — konteyner qayta ishga tushsa
barcha ma'lumot yo'qolishi mumkin edi. Yangi, diskli Postgres yaratildi;
bu modul eski bazadagi hamma narsani unga ko'chiradi.

Ishga tushirish: botga `MOVE_DB_TO` o'zgaruvchisi (yangi bazaning URL'i)
qo'yiladi. `post_init` boshida, hech qanday job yoki handler ishlamasdan
oldin `run()` chaqiriladi:
  - yangi bazada `_moved_from_old_db` belgisi bo'lsa — ko'chirilgan,
    qayta ko'chirilmaydi ('already');
  - yangi bazada belgisiz ma'lumot bo'lsa — HECH NARSAGA tegilmaydi
    ('refused'), bot eski bazada qoladi;
  - aks holda hammasi BITTA tranzaksiyada ko'chiriladi, har jadval qator
    soni solishtiriladi; bittasi mos kelmasa — tranzaksiya bekor ('failed').
'moved'/'already' bo'lsa jarayon yangi baza bilan davom etadi.
"""
import logging
import tempfile

import asyncpg

import db

log = logging.getLogger(__name__)

MARKER = "_moved_from_old_db"


async def _tables(c) -> list[str]:
    return [r["table_name"] for r in await c.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")]


async def _cols(c, table: str) -> list[str]:
    return [r["column_name"] for r in await c.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position", table)]


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def run(src_url: str, dst_url: str) -> tuple[str, str]:
    """Qaytaradi: (holat, izoh). Holat: moved | already | refused | failed."""
    if not dst_url or dst_url == src_url:
        return "refused", "MOVE_DB_TO bo'sh yoki joriy baza bilan bir xil"
    try:
        dst = await asyncpg.connect(dst_url, timeout=30)
    except Exception as e:
        log.exception("Yangi bazaga ulanib bo'lmadi")
        return "failed", f"yangi bazaga ulanib bo'lmadi: {type(e).__name__}: {e}"
    try:
        if MARKER in await _tables(dst):
            row = await dst.fetchrow(f"SELECT moved_at, total_rows FROM {MARKER}")
            return "already", f"allaqachon ko'chirilgan ({row['moved_at']:%Y-%m-%d %H:%M} UTC, {row['total_rows']} qator)"
        for t in await _tables(dst):
            if await dst.fetchval(f"SELECT EXISTS (SELECT 1 FROM {_q(t)})"):
                return "refused", f"yangi bazada belgisiz ma'lumot bor ({t}) — tegilmadi"

        # Jadvallar aynan bot yaratadigan ko'rinishda.
        await dst.execute(db.SCHEMA)
        await dst.execute(db.MIGRATE)

        src = await asyncpg.connect(src_url, timeout=30)
        try:
            src_tables = await _tables(src)
            dst_tables = set(await _tables(dst))
            tables = [t for t in src_tables if t in dst_tables]
            skipped = [t for t in src_tables if t not in dst_tables]
            counts: dict[str, int] = {}
            async with dst.transaction():
                # FK tekshiruvi ko'chirish vaqtida o'chiq — jadvallar tartibi
                # muhim emas (ma'lumot allaqachon izchil bazadan keladi).
                await dst.execute("SET LOCAL session_replication_role = replica")
                if tables:
                    # MIGRATE standart qatorlar qo'shgan bo'lishi mumkin.
                    await dst.execute("TRUNCATE " + ", ".join(_q(t) for t in tables))
                for t in tables:
                    dcols = set(await _cols(dst, t))
                    cols = [c for c in await _cols(src, t) if c in dcols]
                    with tempfile.TemporaryFile() as f:
                        await src.copy_from_table(t, columns=cols, output=f, format="csv")
                        f.seek(0)
                        await dst.copy_to_table(t, source=f, columns=cols, format="csv")
                    n_src = await src.fetchval(f"SELECT count(*) FROM {_q(t)}")
                    n_dst = await dst.fetchval(f"SELECT count(*) FROM {_q(t)}")
                    if n_src != n_dst:
                        raise RuntimeError(f"{t}: eski {n_src}, yangi {n_dst} qator")
                    counts[t] = n_dst
                # SERIAL hisoblagichlari — yangi yozuvlar eski id'lar bilan
                # to'qnashmasin.
                for r in await dst.fetch(
                        "SELECT table_name, column_name, column_default "
                        "FROM information_schema.columns WHERE table_schema='public' "
                        "AND column_default LIKE 'nextval(%'"):
                    seq = r["column_default"].split("'")[1]
                    t, c = _q(r["table_name"]), _q(r["column_name"])
                    await dst.execute(
                        f"SELECT setval('{seq}', COALESCE((SELECT max({c}) FROM {t}), 1), "
                        f"(SELECT max({c}) FROM {t}) IS NOT NULL)")
                total = sum(counts.values())
                await dst.execute(
                    f"CREATE TABLE {MARKER} (moved_at TIMESTAMP NOT NULL DEFAULT "
                    f"(now() AT TIME ZONE 'utc'), tables INT NOT NULL, total_rows BIGINT NOT NULL)")
                await dst.execute(f"INSERT INTO {MARKER} (tables, total_rows) VALUES ($1, $2)",
                                  len(counts), total)
        finally:
            await src.close()
    except Exception as e:
        log.exception("Baza ko'chirilmadi")
        return "failed", f"{type(e).__name__}: {e}"
    finally:
        await dst.close()
    big = ", ".join(f"{t} {n}" for t, n in sorted(counts.items(), key=lambda x: -x[1])[:5])
    note = f"{len(counts)} jadval, {total} qator ko'chirildi (eng kattalari: {big})"
    if skipped:
        note += f"; yangi sxemada yo'q, o'tkazib yuborildi: {', '.join(skipped)}"
    return "moved", note


async def copy_legacy(src_url: str, dst_url: str) -> str:
    """Eski bazada bo'lib, kod sxemasida YO'Q jadvallarni (masalan
    `memberships`, `star_payments`) yangi bazaga ARXIV sifatida ko'chiradi —
    eski servis o'chirilishidan oldin, ular abadiy yo'qolmasin. Faqat
    ustunlar va turlar (default/cheklovlarsiz). Yangi bazada allaqachon bor
    jadvalga tegilmaydi — qayta ishga tushsa hech narsa qilmaydi."""
    src = await asyncpg.connect(src_url, timeout=30)
    dst = await asyncpg.connect(dst_url, timeout=30)
    try:
        have = set(await _tables(dst))
        todo = [t for t in await _tables(src) if t not in have]
        if not todo:
            return "arxivlanadigan jadval yo'q"
        done = []
        async with dst.transaction():
            for t in todo:
                cols = await src.fetch(
                    "SELECT attname, format_type(atttypid, atttypmod) AS typ "
                    "FROM pg_attribute WHERE attrelid = $1::regclass "
                    "AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
                    f"public.{_q(t)}")
                await dst.execute(f"CREATE TABLE {_q(t)} (" + ", ".join(
                    f"{_q(c['attname'])} {c['typ']}" for c in cols) + ")")
                names = [c["attname"] for c in cols]
                with tempfile.TemporaryFile() as f:
                    await src.copy_from_table(t, columns=names, output=f, format="csv")
                    f.seek(0)
                    await dst.copy_to_table(t, source=f, columns=names, format="csv")
                n_src = await src.fetchval(f"SELECT count(*) FROM {_q(t)}")
                n_dst = await dst.fetchval(f"SELECT count(*) FROM {_q(t)}")
                if n_src != n_dst:
                    raise RuntimeError(f"{t}: eski {n_src}, yangi {n_dst} qator")
                done.append(f"{t} {n_dst}")
        return "arxivlandi: " + ", ".join(done)
    finally:
        await src.close()
        await dst.close()
