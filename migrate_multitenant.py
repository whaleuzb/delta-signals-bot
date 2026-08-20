"""Bir martalik migratsiya: multi-tenant arxitekturaga o'tish.

Mavjud "Whales Uzb" guruhi uchun workspace yaratadi, barcha eski signallarni
shu workspace'ga bog'laydi, so'ngra workspace_id ustunini NOT NULL qiladi.
Ishga tushirish: Railway startCommand'ni vaqtincha
"python migrate_multitenant.py; python bot.py" ga almashtirib, keyin qaytarish.
"""
import asyncio

import asyncpg
import config

OWNER_ID = 1101182189       # "Whales Uzb" guruh admini (Mamurjon)
GROUP_CHAT_ID = -1001804915914
GROUP_TOPIC_ID = 9003
NAME = "Whales Uzb"


async def main():
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        await conn.execute(
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS workspace_id INT "
            "REFERENCES workspaces(id)"
        )

        row = await conn.fetchrow(
            "SELECT id FROM workspaces WHERE group_chat_id=$1", GROUP_CHAT_ID)
        if row:
            wid = row["id"]
            print(f"Workspace allaqachon mavjud: #{wid}")
        else:
            wid = await conn.fetchval(
                "INSERT INTO workspaces (type, owner_id, group_chat_id, group_topic_id, name) "
                "VALUES ('group', $1, $2, $3, $4) RETURNING id",
                OWNER_ID, GROUP_CHAT_ID, GROUP_TOPIC_ID, NAME,
            )
            print(f"Yangi workspace yaratildi: #{wid} {NAME}")

        result = await conn.execute(
            "UPDATE signals SET workspace_id=$1 WHERE workspace_id IS NULL", wid)
        print(f"Backfill: {result}")

        null_left = await conn.fetchval(
            "SELECT COUNT(*) FROM signals WHERE workspace_id IS NULL")
        if null_left:
            print(f"OGOHLANTIRISH: {null_left} ta signal hali workspace_id'siz qoldi, "
                  "NOT NULL qo'yilmadi.")
        else:
            await conn.execute(
                "ALTER TABLE signals ALTER COLUMN workspace_id SET NOT NULL")
            print("workspace_id NOT NULL qilindi.")

        total = await conn.fetchval("SELECT COUNT(*) FROM signals")
        print(f"Jami signallar: {total}")
    finally:
        await conn.close()


asyncio.run(main())
