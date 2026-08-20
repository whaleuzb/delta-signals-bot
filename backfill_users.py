"""Bir martalik: users jadvalini bot bazasidagi ESKI izlardan to'ldiradi.

users jadvali yaqinda qo'shilgan, shuning uchun undan oldin botga kelgan
odamlar statistikada yo'q. Telegram "botimni ishlatgan hamma" ro'yxatini
bermaydi, lekin bot bazasida foydalanuvchi ID'lari bir necha joyda saqlangan:

  workspaces.owner_id     — workspace ochganlar
  signals.author_id       — signal kiritganlar
  group_viewers.user_id   — guruh statistikasini ko'rish uchun ulanganlar
  referrals.referrer_id   — kimnidir taklif qilganlar
  referrals.referred_id   — taklif orqali kelganlar

first_seen sifatida o'sha yozuvning eng erta sanasi olinadi (now() emas) —
shunda statistikadagi "yangi foydalanuvchilar" grafigi haqiqatga mos bo'ladi.

DIQQAT: faqat /start bosib boshqa hech narsa qilmagan odamlar hech qayerda
iz qoldirmagan — ularni tiklab bo'lmaydi.
"""
import asyncio
import os

import db

SOURCES = [
    ("workspaces",    "owner_id",    "created_at"),
    ("signals",       "author_id",   "created_at"),
    ("group_viewers", "user_id",     "created_at"),
    ("referrals",     "referrer_id", "created_at"),
    ("referrals",     "referred_id", "created_at"),
]


async def main():
    await db.init()
    async with db.pool().acquire() as c:
        before = await c.fetchval("SELECT COUNT(*) FROM users")
        print(f"users jadvalida hozir: {before} ta")

        found: dict[int, object] = {}
        for table, col, ts in SOURCES:
            rows = await c.fetch(
                f"SELECT {col} AS uid, MIN({ts}) AS seen FROM {table} "
                f"WHERE {col} IS NOT NULL GROUP BY {col}")
            print(f"  {table}.{col}: {len(rows)} ta noyob ID")
            for r in rows:
                uid, seen = r["uid"], r["seen"]
                if uid not in found or (seen and seen < found[uid]):
                    found[uid] = seen

        print(f"Jami noyob foydalanuvchi ID: {len(found)}")

        added = 0
        for uid, seen in found.items():
            res = await c.execute(
                "INSERT INTO users (user_id, first_seen, last_seen) "
                "VALUES ($1, COALESCE($2, now()), COALESCE($2, now())) "
                "ON CONFLICT (user_id) DO NOTHING", uid, seen)
            if res.endswith("1"):
                added += 1

        after = await c.fetchval("SELECT COUNT(*) FROM users")
        print(f"Qo'shildi: {added} ta  |  users jadvalida endi: {after} ta")

    # Ism/username'larni Telegram'dan olishga urinamiz (bot bilan suhbati
    # bo'lganlar uchun ishlaydi; qolganlari uchun jimgina o'tkazib yuboriladi).
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN yo'q — ismlar to'ldirilmadi.")
        return

    from telegram import Bot
    from telegram.error import RetryAfter

    bot = Bot(token)
    async with db.pool().acquire() as c:
        need = await c.fetch(
            "SELECT user_id FROM users WHERE username IS NULL AND first_name IS NULL")
    print(f"Ismi noma'lum: {len(need)} ta — Telegram'dan so'raymiz…")

    ok = 0
    for i, r in enumerate(need):
        uid = r["user_id"]
        try:
            chat = await bot.get_chat(uid)
            async with db.pool().acquire() as c:
                await c.execute(
                    "UPDATE users SET username=$2, first_name=$3 WHERE user_id=$1",
                    uid, chat.username, chat.first_name)
            ok += 1
        except RetryAfter as e:
            # Telegram flood-control — kutamiz va shu ID ni tashlab ketamiz
            print(f"  flood: {e.retry_after}s kutamiz")
            await asyncio.sleep(e.retry_after + 1)
        except Exception:
            pass  # bot bilan suhbati yo'q / bloklagan — ism olinmaydi
        if i % 20 == 19:
            await asyncio.sleep(1)  # yumshoq tezlik cheklovi

    print(f"Ism olindi: {ok} / {len(need)}")


asyncio.run(main())
