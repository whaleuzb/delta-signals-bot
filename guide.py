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
# Sarlavha va butun matn uchala tilda. Tuzilma (bo'limlar tartibi,
# rasmlar, misollar) BITTA joyda -- `content()` da; bu jadval faqat
# matnni saqlaydi, ya'ni tarjima qo'shilganda tuzilma takrorlanmaydi.
TITLES = {
    "uz": "Trade Controller — guruh ulash va signal kiritish",
    "ru": "Trade Controller — подключение группы и ввод сигналов",
    "en": "Trade Controller — connecting a group and sending signals",
}
TITLE = TITLES["uz"]      # eski chaqiruvchilar uchun
AUTHOR = "Trade Controller"


# Qo'llanma matni — uchala tilda. Kalit -> {til: matn}.
G = {
"intro": {
 "uz": "Botni ishga tushirishning to'liq yo'riqnomasi. Har bir qadam bot bilan haqiqiy suhbat ko'rinishida ko'rsatilgan.",
 "ru": "Полное руководство по запуску бота. Каждый шаг показан как реальный диалог с ботом.",
 "en": "A complete guide to getting the bot running. Every step is shown as a real conversation with the bot.",
},
"a_head": {"uz": "A. Guruhingizni ulash", "ru": "A. Подключение группы", "en": "A. Connecting your group"},
"a_sub": {
 "uz": "Bu bir marta bajariladi. Shundan keyin guruhingiz mustaqil ishlay boshlaydi.",
 "ru": "Делается один раз. После этого группа работает самостоятельно.",
 "en": "This is done once. After that your group runs on its own.",
},
"a_1a": {"uz": "Botni guruhingizga ", "ru": "", "en": ""},
"a_1b": {"uz": "qo'shing", "ru": "Добавьте", "en": "Add"},
"a_1c": {"uz": ".", "ru": " бота в свою группу.", "en": " the bot to your group."},
"a_2a": {"uz": "Botga guruhda ", "ru": "Дайте боту права ", "en": "Give the bot "},
"a_2b": {"uz": "admin", "ru": "администратора", "en": "admin"},
"a_2c": {
 "uz": " huquqini bering. Bu majburiy — admin huquqisiz bot guruhga signal va natijalarni umuman yubora olmaydi.",
 "ru": " в группе. Это обязательно — без прав администратора бот вообще не сможет отправлять сигналы и результаты.",
 "en": " rights in the group. This is required — without admin rights the bot cannot post signals or results at all.",
},
"a_3a": {"uz": "Guruh ", "ru": "Напишите ", "en": "Type "},
"a_3b": {"uz": "ichida", "ru": "внутри", "en": "inside"},
"a_3c": {"uz": " ", "ru": " группы ", "en": " the group "},
"a_3d": {
 "uz": " yozing. Aynan guruhning o'zida, shaxsiy chatda emas.",
 "ru": ". Именно в самой группе, не в личном чате.",
 "en": ". In the group itself, not in the private chat.",
},
"a_cap": {"uz": "Guruhni ulashning uch qadami", "ru": "Три шага подключения группы", "en": "Three steps to connect a group"},
"a_warn_b": {"uz": "Diqqat: ", "ru": "Внимание: ", "en": "Note: "},
"a_warn": {
 "uz": "Faqat guruh admini /setup qila oladi. Bir admin — bitta guruh: sizda allaqachon ulangan guruh bo'lsa, bot ikkinchisini qabul qilmaydi.",
 "ru": "Команду /setup может выполнить только админ группы. Один админ — одна группа: если у вас уже есть подключённая группа, вторую бот не примет.",
 "en": "Only a group admin can run /setup. One admin — one group: if you already have a connected group, the bot will not accept a second one.",
},
"b_head": {"uz": "B. Signal kiritish", "ru": "B. Ввод сигнала", "en": "B. Sending a signal"},
"b_warn_b": {"uz": "Eng ko'p uchraydigan xato. ", "ru": "Самая частая ошибка. ", "en": "The most common mistake. "},
"b_warn_1": {"uz": "Signal ", "ru": "Сигнал пишется ", "en": "A signal goes into "},
"b_warn_2": {"uz": "botning shaxsiy chatiga", "ru": "в личный чат бота", "en": "the bot's private chat"},
"b_warn_3": {
 "uz": " yoziladi — guruhga emas! Tasdiqlaganingizdan keyin bot uni guruhga o'zi chiqaradi.",
 "ru": ", а не в группу! После вашего подтверждения бот сам опубликует его в группе.",
 "en": ", not the group! After you confirm it, the bot posts it to the group itself.",
},
"b_w1_head": {
 "uz": "Yo'l 1 — sehrgar (yangi boshlovchilar uchun)",
 "ru": "Способ 1 — мастер (для новичков)",
 "en": "Way 1 — the wizard (for beginners)",
},
"b_w1_a": {"uz": "Botga ", "ru": "Напишите боту ", "en": "Send the bot "},
"b_w1_b": {
 "uz": " yozing yoki menyudagi «➕ Yangi signal» tugmasini bosing. Bot har bir darajani navbat bilan so'raydi — hech narsani yodlash shart emas.",
 "ru": " или нажмите в меню «➕ Новый сигнал». Бот спросит каждый уровень по очереди — ничего запоминать не нужно.",
 "en": " or press «➕ New signal» in the menu. The bot asks for each level in turn — nothing to memorise.",
},
"b_w1_pre": {
 "uz": "Siz:  /new\nBot:  1/6 — 📈 Grafik rasmni yuboring.\n      [⏭ Rasmsiz davom etish]\nBot:  Juftlikni yozing (masalan BTCUSDT)\nSiz:  BTCUSDT\nBot:  Kirish turini tanlang\n      [🎯 Oddiy (darhol)] [⏳ Limit (kutadi)]",
 "ru": "Вы:   /new\nБот:  1/6 — 📈 Пришлите картинку графика.\n      [⏭ Продолжить без картинки]\nБот:  Напишите пару (например BTCUSDT)\nВы:   BTCUSDT\nБот:  Выберите тип входа\n      [🎯 Обычный (сразу)] [⏳ Лимит (ждёт)]",
 "en": "You:  /new\nBot:  1/6 — 📈 Send the chart image.\n      [⏭ Continue without an image]\nBot:  Send the pair (for example BTCUSDT)\nYou:  BTCUSDT\nBot:  Choose the entry type\n      [🎯 Market (now)] [⏳ Limit (waits)]",
},
"b_w2_head": {
 "uz": "Yo'l 2 — bitta xabar (tezkor)", "ru": "Способ 2 — одним сообщением (быстро)",
 "en": "Way 2 — one message (fast)",
},
"b_w2_p": {
 "uz": "Barcha darajalarni bitta xabarda yuboring:",
 "ru": "Отправьте все уровни одним сообщением:",
 "en": "Send all the levels in one message:",
},
"b_w2_cap": {
 "uz": "Signal qismlari: juftlik · yo'nalish · kirish · maqsadlar · stop",
 "ru": "Части сигнала: пара · направление · вход · цели · стоп",
 "en": "The parts of a signal: pair · direction · entry · targets · stop",
},
"b_multi": {
 "uz": "Ko'p qatorli ko'rinish ham ishlaydi — odatda kanaldan nusxa olinadigan format:",
 "ru": "Многострочный вид тоже работает — обычно так копируют из канала:",
 "en": "The multi-line form works too — this is how signals are usually copied from a channel:",
},
"b_multi_pre": {
 "uz": "BTC/USDT\nLONG\nEntry: 65 000\nTP1 67 000\nTP2 68 500\nStop: 64 000",
 "ru": "BTC/USDT\nLONG\nEntry: 65 000\nTP1 67 000\nTP2 68 500\nStop: 64 000",
 "en": "BTC/USDT\nLONG\nEntry: 65 000\nTP1 67 000\nTP2 68 500\nStop: 64 000",
},
"b_kw": {
 "uz": "O'zbekcha kalit so'zlar bilan:", "ru": "С русскими ключевыми словами:",
 "en": "With English keywords:",
},
"b_kw_pre": {
 "uz": "ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80",
 "ru": "ADAUSDT long вход 0.85 цель 0.92 0.98 стоп 0.80",
 "en": "ADAUSDT long entry 0.85 target 0.92 0.98 stop 0.80",
},
"b_nokw_1": {"uz": "Kalit so'zsiz ham bo'ladi — ", "ru": "Можно и без ключевых слов — ", "en": "You can skip the keywords — "},
"b_nokw_2": {"uz": "birinchi raqam kirish", "ru": "первое число — вход", "en": "the first number is the entry"},
"b_nokw_3": {"uz": ", ", "ru": ", ", "en": ", "},
"b_nokw_4": {"uz": "oxirgisi stop", "ru": "последнее — стоп", "en": "the last one is the stop"},
"b_nokw_5": {
 "uz": ", o'rtadagilari TP. Kamida 3 ta raqam kerak:",
 "ru": ", остальные — TP. Нужно минимум 3 числа:",
 "en": ", the rest are TPs. At least 3 numbers are needed:",
},
"b_img_head": {"uz": "Rasm bilan yuborish", "ru": "Отправка с картинкой", "en": "Sending with an image"},
"b_img_1": {
 "uz": "Grafik rasmini tashlasangiz, signalni ",
 "ru": "Если вы отправляете картинку графика, напишите сигнал ",
 "en": "If you send a chart image, write the signal ",
},
"b_img_2": {
 "uz": "rasm ostiga izoh (caption) qilib yozing",
 "ru": "в подписи под картинкой (caption)",
 "en": "in the image caption",
},
"b_img_3": {
 "uz": " — bot o'shandan o'qiydi va rasmni signalga biriktiradi. Izohsiz rasm signal deb qabul qilinmaydi.",
 "ru": " — бот прочитает его оттуда и прикрепит картинку к сигналу. Картинка без подписи сигналом не считается.",
 "en": " — the bot reads it from there and attaches the image to the signal. An image with no caption is not treated as a signal.",
},
"b_conf_b": {
 "uz": "Hech narsa tasdiqsiz saqlanmaydi. ", "ru": "Ничего не сохраняется без подтверждения. ",
 "en": "Nothing is saved without confirmation. ",
},
"b_conf": {
 "uz": "Bot o'qigan darajalarni har doim avval ko'rsatadi — siz tasdiqlaguningizcha signal bazaga tushmaydi va guruhga chiqmaydi. Xato o'qilsa, tahrirlash tugmasi bor.",
 "ru": "Бот всегда сначала показывает, что он прочитал — пока вы не подтвердите, сигнал не попадёт ни в базу, ни в группу. Если прочитано неверно, есть кнопка редактирования.",
 "en": "The bot always shows what it read first — until you confirm, the signal reaches neither the database nor the group. If it read something wrong, there is an edit button.",
},
"c_head": {"uz": "C. Kalit so'zlar", "ru": "C. Ключевые слова", "en": "C. Keywords"},
"c_sub": {
 "uz": "Bot matndan quyidagilarni tanib oladi. Katta-kichik harf ahamiyatsiz.",
 "ru": "Бот распознаёт в тексте следующее. Регистр не имеет значения.",
 "en": "The bot recognises the following in your text. Case does not matter.",
},
"c_side": {"uz": "Yo'nalish: ", "ru": "Направление: ", "en": "Direction: "},
"c_side_tail": {
 "uz": " — bo'lmasa LONG deb hisoblanadi.", "ru": " — если ничего нет, считается LONG.",
 "en": " — with none of these it is treated as LONG.",
},
"c_entry": {"uz": "Kirish narxi: ", "ru": "Цена входа: ", "en": "Entry price: "},
"c_tps": {"uz": "Maqsadlar: ", "ru": "Цели: ", "en": "Targets: "},
"c_sl": {"uz": "Stop: ", "ru": "Стоп: ", "en": "Stop: "},
"c_market": {"uz": "Darhol ochish: ", "ru": "Открыть сразу: ", "en": "Open immediately: "},
"c_note_b": {"uz": "Standart holat — kutish. ", "ru": "По умолчанию — ожидание. ", "en": "The default is waiting. "},
"c_note_1": {
 "uz": "market so'zi yozilmasa, signal darhol ochilmaydi: narx kirish darajasiga teggunicha kutib turadi (🕐 belgisi bilan). Pozitsiyaga allaqachon kirgan bo'lsangiz, ",
 "ru": "Если слово market не написано, сигнал не открывается сразу: он ждёт, пока цена дойдёт до уровня входа (значок 🕐). Если вы уже в позиции, не забудьте добавить слово ",
 "en": "Without the word market the signal does not open right away: it waits until the price reaches the entry level (marked 🕐). If you are already in the position, don't forget to add ",
},
"c_note_2": {
 "uz": " so'zini qo'shishni unutmang.", "ru": ".", "en": ".",
},
"d_head": {"uz": "D. Ko'p uchraydigan xatolar", "ru": "D. Частые ошибки", "en": "D. Common mistakes"},
"d_sub": {
 "uz": "Botdan javob kelmasa yoki signal qabul qilinmasa, avval shularni tekshiring.",
 "ru": "Если бот не отвечает или сигнал не принят, сначала проверьте это.",
 "en": "If the bot does not answer or your signal is not accepted, check these first.",
},
"d_cap": {
 "uz": "Eng ko'p uchraydigan uchta xato", "ru": "Три самые частые ошибки",
 "en": "The three most common mistakes",
},
"d_1_head": {"uz": "Bot javob bermayapti", "ru": "Бот не отвечает", "en": "The bot is not answering"},
"d_1_a": {
 "uz": "Signalni guruhga yozgan bo'lishingiz mumkin. Signal faqat ",
 "ru": "Возможно, вы написали сигнал в группу. Сигнал принимается только ",
 "en": "You may have written the signal in the group. Signals are only accepted ",
},
"d_1_b": {"uz": "shaxsiy chatda", "ru": "в личном чате", "en": "in the private chat"},
"d_1_c": {"uz": " qabul qilinadi.", "ru": ".", "en": "."},
"d_2_head": {"uz": "TP noto'g'ri o'qildi", "ru": "TP прочитан неверно", "en": "A TP was read wrong"},
"d_2_a": {"uz": " — bu ", "ru": " читается как ", "en": " reads as "},
"d_2_b": {"uz": "ikkita", "ru": "два", "en": "two"},
"d_2_c": {
 "uz": " TP (172 va 168) deb o'qiladi, chunki TP ro'yxatida bo'sh joy ajratgich hisoblanadi. Minglik yozmoqchi bo'lsangiz: ",
 "ru": " TP (172 и 168), потому что в списке TP пробел считается разделителем. Если нужно число в тысячах: ",
 "en": " TPs (172 and 168), because a space separates values in the TP list. If you mean thousands: ",
},
"d_3_head": {
 "uz": "«SL entry dan past bo'lishi kerak»", "ru": "«Стоп должен быть ниже входа»",
 "en": "\"The SL must be below the entry\"",
},
"d_3_a": {"uz": "LONG uchun: stop ", "ru": "Для LONG: стоп ", "en": "For LONG: the stop is "},
"d_3_b": {"uz": "past", "ru": "ниже", "en": "below"},
"d_3_c": {"uz": ", TP ", "ru": ", TP ", "en": " and the TPs "},
"d_3_d": {"uz": "yuqori", "ru": "выше", "en": "above"},
"d_3_e": {
 "uz": ". SHORT uchun teskarisi. Odatda bu LONG/SHORT adashtirilganini bildiradi.",
 "ru": ". Для SHORT — наоборот. Обычно это значит, что перепутаны LONG и SHORT.",
 "en": ". For SHORT it is the other way round. Usually this means LONG and SHORT got mixed up.",
},
"d_4_head": {
 "uz": "Bot guruhga yozmayapti", "ru": "Бот не пишет в группу",
 "en": "The bot is not posting to the group",
},
"d_4_a": {"uz": "Botda admin huquqi yo'qligidan. ", "ru": "У бота нет прав администратора. ", "en": "The bot has no admin rights. "},
"d_4_b": {
 "uz": " ishlagan bo'lsa ham, admin huquqisiz bot post yubora olmaydi. Guruh sozlamalaridan bering.",
 "ru": " мог сработать, но без прав администратора бот не может отправлять посты. Выдайте их в настройках группы.",
 "en": " may have worked, but without admin rights the bot cannot post. Grant them in the group settings.",
},
"e_head": {"uz": "E. Keyin nima bo'ladi", "ru": "E. Что происходит дальше", "en": "E. What happens next"},
"e_sub": {
 "uz": "Signal tasdiqlangach bot uni o'zi kuzatadi — siz hech narsa qilishingiz shart emas:",
 "ru": "После подтверждения бот сам следит за сигналом — от вас больше ничего не требуется:",
 "en": "Once confirmed, the bot tracks the signal itself — you don't have to do anything:",
},
"e_cap": {
 "uz": "Bot signalni ochilishidan yopilishigacha o'zi kuzatadi",
 "ru": "Бот ведёт сигнал от открытия до закрытия",
 "en": "The bot follows the signal from open to close",
},
"e_1": {"uz": "Natijalar asl signal postiga ", "ru": "Результаты пишутся ", "en": "Results are written as a "},
"e_2": {"uz": "javob", "ru": "ответом", "en": "reply"},
"e_3": {
 "uz": " qilib yoziladi, shuning uchun guruhda hamma nima bo'layotganini kuzatib boradi. Barcha yopilgan signallar statistikaga o'zi tushadi.",
 "ru": " на исходный пост сигнала, поэтому в группе всем видно, что происходит. Все закрытые сигналы попадают в статистику сами.",
 "en": " to the original signal post, so everyone in the group can follow what is happening. Every closed signal enters the stats by itself.",
},
"cmds": {"uz": "Buyruqlar: ", "ru": "Команды: ", "en": "Commands: "},
}


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


def _t(key: str, lang: str) -> str:
    """Qo'llanma matni. Tarjima bo'lmasa o'zbekchaga qaytadi — maqola
    hech qachon bo'sh joy bilan chiqmasin."""
    row = G.get(key) or {}
    return row.get(lang) or row.get("uz") or ""


def content(img: dict | None = None, lang: str = "uz") -> list:
    """Qo'llanma matni Telegraph tugunlari (node) ko'rinishida.

    Telegraph faqat cheklangan teglarni qabul qiladi (h3/h4, p, ul/ol/li, b, i,
    code, pre, blockquote, aside, hr, a, br) — h1/h2 va JADVAL yo'q, shuning
    uchun kalit so'zlar jadvali ro'yxat sifatida berilgan.

    img — {kalit: rasm_url}. Berilmasa yoki biror kalit yetishmasa, o'sha rasm
    tashlab ketiladi va maqola faqat matn bilan chiqadi (rasm yuklanmay qolsa
    ham chop etish buzilmasligi uchun).

    lang — maqola tili. Tuzilma (bo'limlar tartibi, misollar, rasmlar) uchala
    tilda AYNI bir xil; faqat matn almashadi."""
    img = img or {}
    t = lambda k: _t(k, lang)
    return [
        _p(t("intro")),
        {"tag": "hr"},

        # ── A ──
        _h(t("a_head")),
        _p(t("a_sub")),
        _list([
            [t("a_1a"), _b(t("a_1b")), t("a_1c")],
            [t("a_2a"), _b(t("a_2b")), t("a_2c")],
            [t("a_3a"), _b(t("a_3b")), t("a_3c"), _code("/setup"), t("a_3d")],
        ], ordered=True),
        *_fig(img.get("setup"), t("a_cap")),
        {"tag": "blockquote", "children": [_b(t("a_warn_b")), t("a_warn")]},

        # ── B ──
        _h(t("b_head")),
        {"tag": "blockquote", "children": [
            _b(t("b_warn_b")), t("b_warn_1"), _b(t("b_warn_2")), t("b_warn_3"),
        ]},

        _h(t("b_w1_head"), 4),
        _p(t("b_w1_a"), _code("/new"), t("b_w1_b")),
        _pre(t("b_w1_pre")),

        _h(t("b_w2_head"), 4),
        _p(t("b_w2_p")),
        *_fig(img.get("format"), t("b_w2_cap")),
        _pre("BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000"),
        _p(t("b_multi")),
        _pre(t("b_multi_pre")),
        _p(t("b_kw")),
        _pre(t("b_kw_pre")),
        _p(t("b_nokw_1"), _b(t("b_nokw_2")), t("b_nokw_3"), _b(t("b_nokw_4")),
           t("b_nokw_5")),
        _pre("eth long 3200 3400 3550 3100"),

        _h(t("b_img_head"), 4),
        _p(t("b_img_1"), _b(t("b_img_2")), t("b_img_3")),
        {"tag": "blockquote", "children": [_b(t("b_conf_b")), t("b_conf")]},

        # ── C ──
        _h(t("c_head")),
        _p(t("c_sub")),
        _list([
            [_b(t("c_side")), _code("short"), " · ", _code("sell"), " · ",
             _code("sotish"), t("c_side_tail")],
            [_b(t("c_entry")), _code("entry"), " · ", _code("kirish"), " · ",
             _code("narx"), " · ", _code("buy")],
            [_b(t("c_tps")), _code("tp"), " · ", _code("TP1"), " · ",
             _code("maqsad"), " · ", _code("target")],
            [_b(t("c_sl")), _code("sl"), " · ", _code("stop"), " · ", _code("zarar")],
            [_b(t("c_market")), _code("market"), " · ", _code("bozor")],
        ]),
        {"tag": "blockquote", "children": [
            _b(t("c_note_b")), t("c_note_1"), _code("market"), t("c_note_2"),
        ]},

        # ── D ──
        _h(t("d_head")),
        _p(t("d_sub")),
        *_fig(img.get("errors"), t("d_cap")),

        _h(t("d_1_head"), 4),
        _p(t("d_1_a"), _b(t("d_1_b")), t("d_1_c")),

        _h(t("d_2_head"), 4),
        _p(_code("tp 172 168"), t("d_2_a"), _b(t("d_2_b")), t("d_2_c"),
           _code("tp 172168"), " / ", _code("TP1 172 168"), "."),

        _h(t("d_3_head"), 4),
        _p(t("d_3_a"), _b(t("d_3_b")), t("d_3_c"), _b(t("d_3_d")), t("d_3_e")),

        _h(t("d_4_head"), 4),
        _p(t("d_4_a"), _code("/setup"), t("d_4_b")),

        # ── E ──
        _h(t("e_head")),
        _p(t("e_sub")),
        *_fig(img.get("after"), t("e_cap")),
        _p(t("e_1"), _b(t("e_2")), t("e_3")),

        {"tag": "hr"},
        _p(_b(t("cmds")), _code("/stats"), " ", _code("/month"), " ", _code("/year"),
           " ", _code("/symbols"), " ", _code("/equity"), " ", _code("/open"), " ",
           _code("/pdf"), " ", _code("/depozit"), " ", _code("/cancel"), " ",
           _code("/top"), " ", _code("/taklif"), " ", _code("/yordam")),
    ]


def _path_env(lang: str) -> str:
    """Har bir tilning O'Z sahifasi bor, ya'ni o'z path'i ham.
    O'zbekchasi eski `TELEGRAPH_PATH` nomida qoladi — allaqachon chop
    etilgan sahifa va uning havolasi o'zgarmasin."""
    return "TELEGRAPH_PATH" if lang == "uz" else f"TELEGRAPH_PATH_{lang.upper()}"


async def publish(lang: str = "uz") -> tuple[str, str, str]:
    """Qo'llanmani Telegraph'ga chop etadi (yoki mavjudini yangilaydi).

    Qaytaradi: (url, access_token, path). Token va path'ni env'ga saqlab
    qo'ysangiz, keyingi chaqiruv YANGI sahifa yaratmasdan o'shanisini
    tahrirlaydi — guruhga qadalgan havola eskirmaydi. Token UCHALA til
    uchun bitta (bitta Telegraph hisobi), path esa har tilda alohida."""
    token = os.getenv("TELEGRAPH_TOKEN", "").strip()
    path = os.getenv(_path_env(lang), "").strip()

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
            "title": TITLES.get(lang, TITLE),
            "author_name": AUTHOR,
            "content": json.dumps(content(img, lang), ensure_ascii=False),
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
