"""Bir martalik: qo'llanmani Telegraph'ga chop etadi va havolani chiqaradi.

Bu skript Railway'da ishlatiladi, chunki Telegraph API'siga tarmoq ruxsati
o'sha yerda bor. Natijadagi TELEGRAPH_TOKEN va TELEGRAPH_PATH ni Railway
env'iga qo'shib qo'ysangiz, keyingi chop etish YANGI sahifa yaratmasdan
o'shanisini yangilaydi (havola o'zgarmaydi).
"""
import asyncio

import httpx

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

    # Tekshirish: sahifa haqiqatan mavjudmi va matn to'g'ri joylashganmi.
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{guide.API}/getPage/{path}", params={"return_content": "true"})
        j = r.json()
    if not j.get("ok"):
        print(f"TEKSHIRUV XATO: {j}")
        return
    res = j["result"]
    heads = [n["children"][0] for n in res.get("content", [])
             if isinstance(n, dict) and n.get("tag") in ("h3", "h4")
             and isinstance(n.get("children", [None])[0], str)]
    print(f"TEKSHIRUV: sarlavha = {res['title']!r}")
    print(f"TEKSHIRUV: {len(res.get('content', []))} ta blok, ko'rishlar: {res.get('views')}")
    print("TEKSHIRUV: bo'limlar —")
    for h in heads:
        print(f"   • {h}")


asyncio.run(main())
