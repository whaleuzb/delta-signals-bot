"""Foydalanuvchi qo'llanmasi va uni Telegraph'ga chop etish.

Nega Telegraph: maqola Telegram ichida darhol ochiladi, hech qanday login
talab qilmaydi va guruhga qadab qo'yish mumkin. Oddiy veb-sahifa (masalan
Claude artifact) foydalanuvchidan login so'raydi — bu to'siq bo'lgan edi.

Sahifa BIR MARTA yaratiladi, keyingi chaqiruvlar o'sha sahifani tahrirlaydi
(TELEGRAPH_TOKEN + TELEGRAPH_PATH env orqali) — havola o'zgarmaydi, ya'ni
guruhga qadalgan xabar eskirmaydi.
"""
import json
import os

import httpx

API = "https://api.telegra.ph"
# Rasm yuklash api. prefiksisiz boshqa hostda — api.telegra.ph/upload
# UNKNOWN_METHOD qaytaradi.
UPLOAD = "https://telegra.ph/upload"
TITLE = "Trade Controller — guruh ulash va signal kiritish"
AUTHOR = "Trade Controller"


def _p(*kids):
    return {"tag": "p", "children": list(kids)}


def _b(t):
    return {"tag": "b", "children": [t]}


def _code(t):
    return {"tag": "code", "children": [t]}


def _list(items, ordered=False):
    return {"tag": "ol" if ordered else "ul",
            "children": [{"tag": "li", "children": it if isinstance(it, list) else [it]}
                         for it in items]}


def _pre(t):
    return {"tag": "pre", "children": [t]}


def _h(t, level=3):
    return {"tag": f"h{level}", "children": [t]}


def _fig(url, caption=None):
    """Rasm + izoh. url bo'lmasa bo'sh ro'yxat qaytaradi — rasm yuklanmay
    qolsa ham maqola matni to'liq chiqaveradi."""
    if not url:
        return []
    kids = [{"tag": "img", "attrs": {"src": url}}]
    if caption:
        kids.append({"tag": "figcaption", "children": [caption]})
    return [{"tag": "figure", "children": kids}]


# Rasm fayllari (guide_images/) — Telegraph'ga yuklanadi va maqolaga qo'yiladi.
IMAGES = {
    "setup": "guide_images/01-guruh-ulash.png",
    "format": "guide_images/02-signal-formati.png",
    "errors": "guide_images/03-xatolar.png",
    "after": "guide_images/04-keyin-nima-boladi.png",
}


async def upload_images(client) -> dict:
    """Rasmlarni telegra.ph ga yuklaydi va {kalit: url} qaytaradi.
    Yuklanmagani jimgina tashlab ketiladi — maqola baribir chop etiladi."""
    urls = {}
    for key, path in IMAGES.items():
        if not os.path.exists(path):
            print(f"  rasm topilmadi, o'tkazib yuborildi: {path}")
            continue
        try:
            with open(path, "rb") as f:
                r = await client.post(UPLOAD,
                                       files={"file": (os.path.basename(path), f, "image/png")})
            j = r.json()
            src = j[0]["src"] if isinstance(j, list) and j and "src" in j[0] else None
            if src:
                urls[key] = "https://telegra.ph" + src
                print(f"  yuklandi: {key} -> {urls[key]}")
            else:
                print(f"  yuklanmadi ({key}): {j}")
        except Exception as e:
            print(f"  yuklashda xato ({key}): {e}")
    return urls


def content(img: dict | None = None) -> list:
    """Qo'llanma matni Telegraph tugunlari (node) ko'rinishida.

    Telegraph faqat cheklangan teglarni qabul qiladi (h3/h4, p, ul/ol/li, b, i,
    code, pre, blockquote, aside, hr, a, br) — h1/h2 va JADVAL yo'q, shuning
    uchun kalit so'zlar jadvali ro'yxat sifatida berilgan.

    img — {kalit: rasm_url}. Berilmasa yoki biror kalit yetishmasa, o'sha rasm
    tashlab ketiladi va maqola faqat matn bilan chiqadi (rasm yuklanmay qolsa
    ham chop etish buzilmasligi uchun)."""
    img = img or {}
    return [
        _p("Botni ishga tushirishning to'liq yo'riqnomasi. Har bir qadam bot bilan "
           "haqiqiy suhbat ko'rinishida ko'rsatilgan."),
        {"tag": "hr"},

        # ── A ──
        _h("A. Guruhingizni ulash"),
        _p("Bu bir marta bajariladi. Shundan keyin guruhingiz mustaqil ishlay boshlaydi."),
        _list([
            ["Botni guruhingizga ", _b("qo'shing"), "."],
            ["Botga guruhda ", _b("admin"), " huquqini bering. Bu majburiy — admin "
             "huquqisiz bot guruhga signal va natijalarni umuman yubora olmaydi."],
            ["Guruh ", _b("ichida"), " ", _code("/setup"), " yozing. Aynan guruhning "
             "o'zida, shaxsiy chatda emas."],
        ], ordered=True),
        *_fig(img.get("setup"), "Guruhni ulashning uch qadami"),
        {"tag": "blockquote", "children": [
            _b("Diqqat: "),
            "Faqat guruh admini /setup qila oladi. Bir admin — bitta guruh: "
            "sizda allaqachon ulangan guruh bo'lsa, bot ikkinchisini qabul qilmaydi.",
        ]},

        # ── B ──
        _h("B. Signal kiritish"),
        {"tag": "blockquote", "children": [
            _b("Eng ko'p uchraydigan xato. "),
            "Signal ", _b("botning shaxsiy chatiga"), " yoziladi — guruhga emas! "
            "Tasdiqlaganingizdan keyin bot uni guruhga o'zi chiqaradi.",
        ]},

        _h("Yo'l 1 — sehrgar (yangi boshlovchilar uchun)", 4),
        _p("Botga ", _code("/new"), " yozing yoki menyudagi «➕ Yangi signal» tugmasini "
           "bosing. Bot har bir darajani navbat bilan so'raydi — hech narsani yodlash "
           "shart emas."),
        _pre("Siz:  /new\n"
             "Bot:  1/6 — 📈 Grafik rasmni yuboring.\n"
             "      [⏭ Rasmsiz davom etish]\n"
             "Bot:  Juftlikni yozing (masalan BTCUSDT)\n"
             "Siz:  BTCUSDT\n"
             "Bot:  Kirish turini tanlang\n"
             "      [🎯 Oddiy (darhol)] [⏳ Limit (kutadi)]"),

        _h("Yo'l 2 — bitta xabar (tezkor)", 4),
        _p("Barcha darajalarni bitta xabarda yuboring:"),
        *_fig(img.get("format"), "Signal qismlari: juftlik · yo'nalish · kirish · maqsadlar · stop"),
        _pre("BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000"),
        _p("Ko'p qatorli ko'rinish ham ishlaydi — odatda kanaldan nusxa olinadigan format:"),
        _pre("BTC/USDT\nLONG\nEntry: 65 000\nTP1 67 000\nTP2 68 500\nStop: 64 000"),
        _p("O'zbekcha kalit so'zlar bilan:"),
        _pre("ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80"),
        _p("Kalit so'zsiz ham bo'ladi — ", _b("birinchi raqam kirish"), ", ",
           _b("oxirgisi stop"), ", o'rtadagilari TP. Kamida 3 ta raqam kerak:"),
        _pre("eth long 3200 3400 3550 3100"),

        _h("Rasm bilan yuborish", 4),
        _p("Grafik rasmini tashlasangiz: izoh (caption) bo'lsa — bot o'shandan o'qiydi. "
           "Izoh bo'lmasa — sun'iy intellekt grafikning o'zidan darajalarni topishga urinadi."),
        {"tag": "blockquote", "children": [
            _b("Hech narsa tasdiqsiz saqlanmaydi. "),
            "Bot o'qigan darajalarni har doim avval ko'rsatadi — siz tasdiqlaguningizcha "
            "signal bazaga tushmaydi va guruhga chiqmaydi. Xato o'qilsa, tahrirlash tugmasi bor.",
        ]},

        # ── C ──
        _h("C. Kalit so'zlar"),
        _p("Bot matndan quyidagilarni tanib oladi. Katta-kichik harf ahamiyatsiz."),
        _list([
            [_b("Yo'nalish: "), _code("short"), " · ", _code("sell"), " · ",
             _code("sotish"), " — bo'lmasa LONG deb hisoblanadi."],
            [_b("Kirish narxi: "), _code("entry"), " · ", _code("kirish"), " · ",
             _code("narx"), " · ", _code("buy")],
            [_b("Maqsadlar: "), _code("tp"), " · ", _code("TP1"), " · ",
             _code("maqsad"), " · ", _code("target")],
            [_b("Stop: "), _code("sl"), " · ", _code("stop"), " · ", _code("zarar")],
            [_b("Darhol ochish: "), _code("market"), " · ", _code("bozor")],
        ]),
        {"tag": "blockquote", "children": [
            _b("Standart holat — kutish. "),
            "market so'zi yozilmasa, signal darhol ochilmaydi: narx kirish darajasiga "
            "teggunicha kutib turadi (🕐 belgisi bilan). Pozitsiyaga allaqachon kirgan "
            "bo'lsangiz, ", _code("market"), " so'zini qo'shishni unutmang.",
        ]},

        # ── D ──
        _h("D. Ko'p uchraydigan xatolar"),
        _p("Botdan javob kelmasa yoki signal qabul qilinmasa, avval shularni tekshiring."),
        *_fig(img.get("errors"), "Eng ko'p uchraydigan uchta xato"),

        _h("Bot javob bermayapti", 4),
        _p("Signalni guruhga yozgan bo'lishingiz mumkin. Signal faqat ", _b("shaxsiy chatda"),
           " qabul qilinadi."),

        _h("TP noto'g'ri o'qildi", 4),
        _p(_code("tp 172 168"), " — bu ", _b("ikkita"), " TP (172 va 168) deb o'qiladi, "
           "chunki TP ro'yxatida bo'sh joy ajratgich hisoblanadi. Minglik yozmoqchi "
           "bo'lsangiz: ", _code("tp 172168"), " yoki ", _code("TP1 172 168"), "."),

        _h("«SL entry dan past bo'lishi kerak»", 4),
        _p("LONG uchun: stop ", _b("past"), ", TP ", _b("yuqori"), ". SHORT uchun teskarisi. "
           "Odatda bu LONG/SHORT adashtirilganini bildiradi."),

        _h("«Risk juda katta»", 4),
        _p("Kirish bilan stop orasi 25% dan ko'p. Raqamlarni tekshiring — ko'pincha "
           "verguldan yoki nuqtadan adashish."),

        _h("Bot guruhga yozmayapti", 4),
        _p("Botda admin huquqi yo'qligidan. ", _code("/setup"), " ishlagan bo'lsa ham, "
           "admin huquqisiz bot post yubora olmaydi. Guruh sozlamalaridan bering."),

        # ── E ──
        _h("E. Keyin nima bo'ladi"),
        _p("Signal tasdiqlangach bot uni o'zi kuzatadi — siz hech narsa qilishingiz shart emas:"),
        *_fig(img.get("after"), "Bot signalni ochilishidan yopilishigacha o'zi kuzatadi"),
        _p("Natijalar asl signal postiga ", _b("javob"), " qilib yoziladi, shuning uchun "
           "guruhda hamma nima bo'layotganini kuzatib boradi. Barcha yopilgan signallar "
           "statistikaga o'zi tushadi."),

        {"tag": "hr"},
        _p(_b("Buyruqlar: "), _code("/stats"), " ", _code("/month"), " ", _code("/year"),
           " ", _code("/symbols"), " ", _code("/equity"), " ", _code("/open"), " ",
           _code("/pdf"), " ", _code("/depozit"), " ", _code("/cancel"), " ",
           _code("/top"), " ", _code("/taklif"), " ", _code("/yordam")),
    ]


async def publish() -> tuple[str, str, str]:
    """Qo'llanmani Telegraph'ga chop etadi (yoki mavjudini yangilaydi).

    Qaytaradi: (url, access_token, path). Token va path'ni env'ga saqlab
    qo'ysangiz, keyingi chaqiruv YANGI sahifa yaratmasdan o'shanisini
    tahrirlaydi — guruhga qadalgan havola eskirmaydi."""
    token = os.getenv("TELEGRAPH_TOKEN", "").strip()
    path = os.getenv("TELEGRAPH_PATH", "").strip()

    async with httpx.AsyncClient(timeout=30) as c:
        if not token:
            r = await c.post(f"{API}/createAccount", data={
                "short_name": "TradeCtrl", "author_name": AUTHOR})
            j = r.json()
            if not j.get("ok"):
                raise RuntimeError(f"createAccount: {j}")
            token = j["result"]["access_token"]
            path = ""

        print("Rasmlar yuklanmoqda…")
        img = await upload_images(c)
        payload = {
            "access_token": token,
            "title": TITLE,
            "author_name": AUTHOR,
            "content": json.dumps(content(img), ensure_ascii=False),
        }
        if path:
            payload["path"] = path
            r = await c.post(f"{API}/editPage", data=payload)
            j = r.json()
            if not j.get("ok"):  # sahifa yo'qolgan bo'lsa yangisini yaratamiz
                r = await c.post(f"{API}/createPage", data=payload)
                j = r.json()
        else:
            r = await c.post(f"{API}/createPage", data=payload)
            j = r.json()

        if not j.get("ok"):
            raise RuntimeError(f"createPage/editPage: {j}")
        res = j["result"]
        return res["url"], token, res["path"]
