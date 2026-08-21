"""Bir martalik: qo'llanmani Telegraph'ga chop etadi va havolani chiqaradi.

Bu skript Railway'da ishlatiladi, chunki Telegraph API'siga tarmoq ruxsati
o'sha yerda bor. Natijadagi TELEGRAPH_TOKEN va TELEGRAPH_PATH ni Railway
env'iga qo'shib qo'ysangiz, keyingi chop etish YANGI sahifa yaratmasdan
o'shanisini yangilaydi (havola o'zgarmaydi).
"""
import asyncio

import guide


async def main():
    url, token, path = await guide.publish()
    print("=" * 60)
    print(f"QO'LLANMA CHOP ETILDI: {url}")
    print("=" * 60)
    print(f"TELEGRAPH_TOKEN={token}")
    print(f"TELEGRAPH_PATH={path}")
    print(f"GUIDE_URL={url}")
    print("=" * 60)


asyncio.run(main())
