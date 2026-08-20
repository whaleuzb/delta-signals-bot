"""Bir martalik skript: Mamurjon (uid=1101182189) egalik qilgan guruh
workspace'ining joriy depozitiga hozirgacha yopilgan signallarning real puldagi
natijasini (pnl_pct/100 * alloc_amount yig'indisi) qo'shadi. Bundan keyin har
yangi signal yopilganda bot.py:poll_job() shu qo'shishni avtomatik qiladi —
bu skript faqat o'tmishdagi (auto-update kodi yozilishidan oldin yopilgan)
signallarni bir martalik moslash uchun."""
import asyncio
import db

OWNER_ID = 1101182189


async def main():
    await db.init()
    async with db.pool().acquire() as c:
        wss = await c.fetch(
            "SELECT id, name, deposit FROM workspaces WHERE owner_id=$1 AND type='group'",
            OWNER_ID)
        print(f"Workspace'lar (oldin): {[(w['id'], w['name'], w['deposit']) for w in wss]}")

        for w in wss:
            row = await c.fetchrow(
                "SELECT COALESCE(SUM(pnl_pct/100*alloc_amount), 0) AS real_pnl, COUNT(*) AS n "
                "FROM signals WHERE workspace_id=$1 AND status IN ('TP','SL','BREAKEVEN') "
                "AND alloc_amount IS NOT NULL", w["id"])
            print(f"  ws={w['id']} real_pnl={row['real_pnl']} ({row['n']} ta signal)")
            if row["real_pnl"]:
                await c.execute(
                    "UPDATE workspaces SET deposit = deposit + $2 WHERE id=$1",
                    w["id"], row["real_pnl"])

        wss_after = await c.fetch(
            "SELECT id, name, deposit FROM workspaces WHERE owner_id=$1 AND type='group'",
            OWNER_ID)
        print(f"Workspace'lar (keyin): {[(w['id'], w['name'], w['deposit']) for w in wss_after]}")


asyncio.run(main())
