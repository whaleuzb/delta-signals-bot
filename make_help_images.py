"""Yordam rasmlarini yasaydi — `guide_images/<til>/*.png`.

NEGA SKRIPT: rasmlar avval qo'lda (bir martalik HTML bilan) yasalgan edi
va natijada IKKI muammo chiqdi — (1) faqat o'zbekcha edi, ya'ni rus/ingliz
foydalanuvchi o'zbekcha rasm ko'rardi; (2) mahsulot o'zgargach (kanal
ulash, "bitta guruh VA bitta kanal") rasmdagi matn ESKIRIB qoldi va buni
hech kim sezmadi. Endi rasm KODDAN yasaladi: matn shu yerda, uchala
tilda, va o'zgarish kerak bo'lsa skript qayta ishga tushiriladi.

Ishlatish:  python make_help_images.py
Talab: playwright + Chromium (loyihada allaqachon bor).
"""
import asyncio
import pathlib

OUT = pathlib.Path(__file__).parent / "guide_images"
W = 1000

# ── Mazmun. Uslub bot va ochiq sahifa bilan bir xil (qora-kumush).
CARDS = {
    "01-ulash": {
        "uz": {
            "h": "Guruh yoki kanalni ulash",
            "sub": "Bir marta bajariladi. Shundan keyin mustaqil ishlaydi.",
            "cols": [
                ("👥 Guruh", [
                    ("1", "Botni guruhingizga qo'shing"),
                    ("2", "Admin huquqini bering"),
                    ("3", "Guruh ichida <code>/setup</code> yozing"),
                ]),
                ("📢 Kanal", [
                    ("1", "Botni kanalga admin qilib qo'shing"),
                    ("2", "Bot shaxsiy chatga «Ulash» tugmasini yuboradi — bosing"),
                    ("", "Kanalda <code>/setup</code> yozish shart emas"),
                ]),
            ],
            "foot": "Faqat admin ulay oladi · Bir admin — bitta guruh <b>va</b> bitta kanal",
        },
        "ru": {
            "h": "Подключение группы или канала",
            "sub": "Делается один раз. Дальше работает самостоятельно.",
            "cols": [
                ("👥 Группа", [
                    ("1", "Добавьте бота в свою группу"),
                    ("2", "Дайте права администратора"),
                    ("3", "Напишите <code>/setup</code> внутри группы"),
                ]),
                ("📢 Канал", [
                    ("1", "Добавьте бота в канал администратором"),
                    ("2", "Бот пришлёт в личный чат кнопку «Подключить»"),
                    ("", "Писать <code>/setup</code> в канале не нужно"),
                ]),
            ],
            "foot": "Подключить может только админ · Один админ — одна группа <b>и</b> один канал",
        },
        "en": {
            "h": "Connecting a group or channel",
            "sub": "Done once. After that it runs on its own.",
            "cols": [
                ("👥 Group", [
                    ("1", "Add the bot to your group"),
                    ("2", "Give it admin rights"),
                    ("3", "Type <code>/setup</code> inside the group"),
                ]),
                ("📢 Channel", [
                    ("1", "Add the bot to the channel as an admin"),
                    ("2", "The bot sends a “Connect” button to your private chat"),
                    ("", "No <code>/setup</code> needed in the channel"),
                ]),
            ],
            "foot": "Only an admin can connect · One admin — one group <b>and</b> one channel",
        },
    },
    "02-signal": {
        "uz": {
            "h": "Signal kiritish",
            "sub": "Signal botning SHAXSIY chatiga yoziladi — guruh yoki kanalga emas.",
            "pre": ["BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000",
                    "ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80",
                    "eth long 3200 3400 3550 3100"],
            "note": "Kalit so'zsiz: birinchi raqam — kirish, oxirgisi — stop, "
                    "o'rtadagilari TP. Kamida 3 ta raqam kerak.",
            "foot": "Standart holat — kutish. Darhol ochish uchun <b>market</b> so'zini qo'shing",
        },
        "ru": {
            "h": "Ввод сигнала",
            "sub": "Сигнал пишется в ЛИЧНЫЙ чат бота — не в группу или канал.",
            "pre": ["BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000",
                    "ADAUSDT long вход 0.85 цель 0.92 0.98 стоп 0.80",
                    "eth long 3200 3400 3550 3100"],
            "note": "Без ключевых слов: первое число — вход, последнее — стоп, "
                    "остальные — TP. Нужно минимум 3 числа.",
            "foot": "По умолчанию — ожидание. Чтобы открыть сразу, добавьте <b>market</b>",
        },
        "en": {
            "h": "Sending a signal",
            "sub": "A signal goes into the bot's PRIVATE chat — not the group or channel.",
            "pre": ["BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000",
                    "ADAUSDT long entry 0.85 target 0.92 0.98 stop 0.80",
                    "eth long 3200 3400 3550 3100"],
            "note": "Without keywords: the first number is the entry, the last is the "
                    "stop, the rest are TPs. At least 3 numbers are needed.",
            "foot": "The default is waiting. Add <b>market</b> to open immediately",
        },
    },
    "03-xatolar": {
        "uz": {
            "h": "Ko'p uchraydigan xatolar",
            "sub": "Bot javob bermasa yoki signal qabul qilinmasa — avval shularni tekshiring.",
            "rows": [
                ("Bot javob bermayapti",
                 "Signalni guruhga yozgansiz. Signal faqat shaxsiy chatda qabul qilinadi."),
                ("TP noto'g'ri o'qildi",
                 "<code>tp 172 168</code> — bu ikkita TP. Minglik uchun "
                 "<code>tp 172168</code> yozing."),
                ("«SL entry dan past bo'lishi kerak»",
                 "LONG uchun stop past, TP yuqori. SHORT uchun teskarisi."),
                ("Bot guruh/kanalga yozmayapti",
                 "Admin huquqi yo'q. Guruh yoki kanal sozlamalaridan bering."),
            ],
        },
        "ru": {
            "h": "Частые ошибки",
            "sub": "Если бот не отвечает или сигнал не принят — сначала проверьте это.",
            "rows": [
                ("Бот не отвечает",
                 "Вы написали сигнал в группу. Сигнал принимается только в личном чате."),
                ("TP прочитан неверно",
                 "<code>tp 172 168</code> — это два TP. Для тысяч пишите "
                 "<code>tp 172168</code>."),
                ("«Стоп должен быть ниже входа»",
                 "Для LONG: стоп ниже, TP выше. Для SHORT — наоборот."),
                ("Бот не пишет в группу/канал",
                 "Нет прав администратора. Выдайте их в настройках группы или канала."),
            ],
        },
        "en": {
            "h": "Common mistakes",
            "sub": "If the bot does not answer or the signal is rejected — check these first.",
            "rows": [
                ("The bot is not answering",
                 "You wrote the signal in the group. Signals are only accepted in "
                 "the private chat."),
                ("A TP was read wrong",
                 "<code>tp 172 168</code> reads as two TPs. For thousands write "
                 "<code>tp 172168</code>."),
                ("“The stop must be below the entry”",
                 "For LONG: stop below, TP above. For SHORT the other way round."),
                ("The bot is not posting to the group/channel",
                 "It has no admin rights. Grant them in the group or channel settings."),
            ],
        },
    },
    "04-keyin": {
        "uz": {
            "h": "Keyin nima bo'ladi",
            "sub": "Signal tasdiqlangach bot uni o'zi kuzatadi — sizdan boshqa hech narsa talab qilinmaydi.",
            "rows": [
                ("Natijalar", "Asl signal postiga javob qilib yoziladi — guruh yoki "
                              "kanalda hamma kuzatib boradi."),
                ("Statistika", "Barcha yopilgan signallar o'zi tushadi: "
                               "<code>/stats</code> <code>/month</code> <code>/year</code>."),
                ("Ochiq sahifa", "<code>/sahifa</code> — natijalaringiz ommaviy sahifada "
                                 "ko'rinadi."),
                ("Til", "<code>/til</code> — bot va guruh/kanal posti tili alohida tanlanadi."),
            ],
        },
        "ru": {
            "h": "Что происходит дальше",
            "sub": "После подтверждения бот сам ведёт сигнал — от вас больше ничего не требуется.",
            "rows": [
                ("Результаты", "Пишутся ответом на исходный пост — всем в группе или "
                               "канале видно, что происходит."),
                ("Статистика", "Все закрытые сигналы попадают в неё сами: "
                               "<code>/stats</code> <code>/month</code> <code>/year</code>."),
                ("Публичная страница", "<code>/sahifa</code> — ваши результаты видны на "
                                       "публичной странице."),
                ("Язык", "<code>/til</code> — язык бота и постов группы/канала выбирается отдельно."),
            ],
        },
        "en": {
            "h": "What happens next",
            "sub": "Once confirmed, the bot follows the signal itself — nothing more is needed from you.",
            "rows": [
                ("Results", "Written as replies to the original post — everyone in the "
                            "group or channel can follow along."),
                ("Stats", "Every closed signal enters them by itself: "
                          "<code>/stats</code> <code>/month</code> <code>/year</code>."),
                ("Public page", "<code>/sahifa</code> — your results appear on the "
                                "public page."),
                ("Language", "<code>/til</code> — the bot's and the group/channel's "
                             "post language are chosen separately."),
            ],
        },
    },
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:%dpx;background:#0A0A0C;color:#F3F4F6;font-family:Inter,sans-serif;
     padding:46px 52px;position:relative;overflow:hidden}
body::before{content:"";position:absolute;width:700px;height:700px;left:-220px;top:-330px;
  background:radial-gradient(circle,rgba(218,221,226,.09),transparent 62%%)}
.brand{font-family:"IBM Plex Mono",monospace;font-size:13px;font-weight:600;
       letter-spacing:.26em;color:#84868C;position:relative}
h1{font-size:38px;font-weight:700;letter-spacing:-.02em;margin-top:12px;position:relative}
.sub{font-size:18px;color:#95979E;margin-top:10px;line-height:1.45;position:relative}
.rule{height:2px;width:56px;background:#DADDE2;opacity:.6;margin:22px 0 26px;position:relative}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;position:relative}
.col{background:linear-gradient(155deg,rgba(23,23,27,.92),rgba(16,16,19,.92));
     border:1px solid #28282E;border-radius:16px;padding:20px 22px}
.col h2{font-size:20px;font-weight:600;margin-bottom:14px}
.st{display:grid;grid-template-columns:32px 1fr;gap:12px;margin-bottom:12px;align-items:start}
.st:last-child{margin-bottom:0}
.num{width:32px;height:32px;border-radius:10px;background:#DADDE2;color:#0A0A0C;
     font-family:"IBM Plex Mono",monospace;font-size:14px;font-weight:700;
     display:flex;align-items:center;justify-content:center}
.num.empty{background:transparent;border:1px dashed #3A3A42}
.st p{font-size:16px;color:#C6C8CD;line-height:1.45;padding-top:5px}
pre{background:#141418;border:1px solid #28282E;border-radius:12px;padding:16px 18px;
    font-family:"IBM Plex Mono",monospace;font-size:15px;color:#DADDE2;
    line-height:1.9;position:relative;white-space:pre-wrap;word-break:break-word}
.note{font-size:16px;color:#95979E;margin-top:16px;line-height:1.5;position:relative}
.rows{position:relative;display:flex;flex-direction:column;gap:12px}
.row{background:linear-gradient(155deg,rgba(23,23,27,.92),rgba(16,16,19,.92));
     border:1px solid #28282E;border-radius:14px;padding:16px 20px;position:relative;
     overflow:hidden}
.row::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
             background:#DADDE2;opacity:.45}
.row h3{font-size:18px;font-weight:600;margin-bottom:4px}
.row p{font-size:16px;color:#95979E;line-height:1.45}
.foot{margin-top:26px;padding-top:18px;border-top:1px solid #28282E;
      font-size:15px;color:#84868C;position:relative}
code{font-family:"IBM Plex Mono",monospace;background:rgba(218,221,226,.10);
     border-radius:5px;padding:1px 6px;font-size:.94em;color:#DADDE2}
""" % W


def _card(d: dict) -> str:
    parts = [f'<div class="brand">TRADE CONTROLLER</div><h1>{d["h"]}</h1>',
             f'<div class="sub">{d["sub"]}</div><div class="rule"></div>']
    if "cols" in d:
        cols = []
        for title, steps in d["cols"]:
            st = "".join(
                f'<div class="st"><div class="num{" empty" if not n else ""}">{n}</div>'
                f'<p>{txt}</p></div>' for n, txt in steps)
            cols.append(f'<div class="col"><h2>{title}</h2>{st}</div>')
        parts.append(f'<div class="cols">{"".join(cols)}</div>')
    if "pre" in d:
        parts.append("<pre>" + "\n".join(d["pre"]) + "</pre>")
        parts.append(f'<div class="note">{d["note"]}</div>')
    if "rows" in d:
        rows = "".join(f'<div class="row"><h3>{h}</h3><p>{p}</p></div>'
                       for h, p in d["rows"])
        parts.append(f'<div class="rows">{rows}</div>')
    if d.get("foot"):
        parts.append(f'<div class="foot">{d["foot"]}</div>')
    return "".join(parts)


async def main():
    from playwright.async_api import async_playwright
    fonts = pathlib.Path(__file__).parent / "guide_images" / "fonts" / "fonts.css"
    link = (f'<link rel="stylesheet" href="{fonts.as_uri()}">' if fonts.exists()
            else '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
                 'family=Inter:wght@400;600;700&family=IBM+Plex+Mono:wght@600&display=swap">')
    async with async_playwright() as pw:
        b = await pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        # Bo'yi ATAYLAB kichik: `full_page=True` haqiqiy mazmun balandligini
        # oladi, viewport baland bo'lsa esa pastda bo'sh joy qolib ketardi.
        pg = await b.new_page(viewport={"width": W, "height": 100},
                              device_scale_factor=2)
        for lang in ("uz", "ru", "en"):
            d = OUT / lang
            d.mkdir(parents=True, exist_ok=True)
            for name, per_lang in CARDS.items():
                html = (f'<meta charset="utf-8">{link}<style>{CSS}</style>'
                        + _card(per_lang[lang]))
                tmp = OUT / f"_tmp_{lang}_{name}.html"
                tmp.write_text(html)
                await pg.goto(tmp.as_uri())
                await pg.wait_for_timeout(400)
                out = d / f"{name}.png"
                await pg.screenshot(path=str(out), full_page=True)
                tmp.unlink()
                print(out, out.stat().st_size, "bayt")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
