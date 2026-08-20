"""Bir martalik skript: Mamurjon (uid=1101182189) egalik qilgan guruh
workspace'laridagi yopilgan signallardan alloc_amount (necha pul ishlatilgani)
kiritilmaganlariga 2500 dan belgilaydi. Faqat shu foydalanuvchining guruhlariga
tegadi — boshqa tenant'larga tegilmaydi."""
import asyncio
import db

OWNER_ID = 1101182189
DEFAULT_ALLOC = 2500


async def main():
    await db.init()
    async with db.pool().acquire() as c:
        wss = await c.fetch(
            "SELECT id, name, deposit FROM workspaces WHERE owner_id=$1 AND type='group'",
            OWNER_ID)
        print(f"Workspace'lar: {[(w['id'], w['name'], w['deposit']) for w in wss]}")
        if not wss:
            print("Hech qanday guruh workspace topilmadi.")
            return

        ids = [w["id"] for w in wss]
        before = await c.fetch(
            "SELECT workspace_id, COUNT(*) FILTER (WHERE alloc_amount IS NULL) AS missing, "
            "COUNT(*) AS total FROM signals "
            "WHERE workspace_id = ANY($1::int[]) AND status IN ('TP','SL','BREAKEVEN') "
            "GROUP BY workspace_id", ids)
        print(f"Yopilgan signallar (backfill oldin): {[dict(r) for r in before]}")

        result = await c.execute(
            "UPDATE signals s SET alloc_amount=$2, "
            "deposit_snapshot=COALESCE(s.deposit_snapshot, w.deposit) "
            "FROM workspaces w WHERE s.workspace_id=w.id AND w.id = ANY($1::int[]) "
            "AND s.status IN ('TP','SL','BREAKEVEN') AND s.alloc_amount IS NULL",
            ids, DEFAULT_ALLOC)
        print(f"Backfill natijasi: {result}")

        after = await c.fetch(
            "SELECT workspace_id, COUNT(*) FILTER (WHERE alloc_amount IS NULL) AS missing, "
            "COUNT(*) AS total FROM signals "
            "WHERE workspace_id = ANY($1::int[]) AND status IN ('TP','SL','BREAKEVEN') "
            "GROUP BY workspace_id", ids)
        print(f"Yopilgan signallar (backfill keyin): {[dict(r) for r in after]}")


asyncio.run(main())
