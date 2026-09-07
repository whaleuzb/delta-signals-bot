"""Bir martalik: qo'llanmani Telegraph'ga UCHALA tilda chop etadi.

Bu skript Railway'da ishlatiladi, chunki Telegraph API'siga tarmoq ruxsati
o'sha yerda bor. Chiqishdagi TELEGRAPH_TOKEN, TELEGRAPH_PATH*, GUIDE_URL*
larni Railway env'iga qo'shib qo'ysangiz, keyingi chop etish YANGI sahifa
yaratmasdan o'shanisini yangilaydi (havolalar o'zgarmaydi).

Bitta til uchun: `python publish_guide.py ru`
"""
import asyncio
import sys

import httpx

import guide


async def one(lang: str) -> None:
    url, token, path = await guide.publish(lang)
    print("=" * 60)
    print(f"QO'LLANMA CHOP ETILDI ({lang}): {url}")
    print("=" * 60)
    print(f"TELEGRAPH_TOKEN={token}")
    print(f"{guide._path_env(lang)}={path}")
    print(f"{'GUIDE_URL' if lang == 'uz' else 'GUIDE_URL_' + lang.upper()}={url}")

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
    print(f"TEKSHIRUV: {len(res.get('content', []))} ta blok, "
          f"ko'rishlar: {res.get('views')}")
    print("TEKSHIRUV: bo'limlar —")
    for h in heads:
        print(f"   • {h}")


async def main():
    langs = sys.argv[1:] or ["uz", "ru", "en"]
    for lang in langs:
        await one(lang)
    print("=" * 60)
    print("Tayyor. Yuqoridagi o'zgaruvchilarni Railway env'iga qo'shing.")


asyncio.run(main())
