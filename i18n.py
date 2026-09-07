"""Ko'p tillilik — o'zbek, rus, ingliz.

Ikki xil til bor va ular ATAYLAB ajratilgan:

  * `users.lang`      — odamning SHAXSIY menyusi tili (bot bilan yozishma).
  * `workspaces.lang` — GURUHGA ketadigan xabarlar tili. Guruh posti
                        hammaga BITTA ketadi, shuning uchun uni har bir
                        odamga o'z tilida yuborib bo'lmaydi — tilni
                        guruhning o'zi tanlaydi.

Tarjima kalitlari `nuqta.bilan.ajratilgan` — qaysi ekranga tegishli
ekani nomidan ko'rinib tursin. Kalit topilmasa yoki tarjima yozilmagan
bo'lsa o'zbekchaga qaytadi (ekran hech qachon bo'sh qolmaydi), buni
`missing()` bilan tekshirib turish mumkin.
"""
from __future__ import annotations

DEFAULT_LANG = "uz"

# Kod -> menyuda ko'rsatiladigan nom (o'z tilida yozilgan — odam o'z
# tilini tanigan holda tanlashi uchun).
LANGS: dict[str, str] = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}


def normalize(lang: str | None) -> str:
    """Noma'lum/bo'sh qiymat standart tilga tushadi (bazadagi eski
    qatorlarda `lang` NULL bo'ladi — ular o'zbekcha ko'rishda davom
    etadi, hech narsa buzilmaydi)."""
    return lang if lang in LANGS else DEFAULT_LANG


STRINGS: dict[str, dict[str, str]] = {
    # --- Til tanlash ---
    "lang.choose": {
        "uz": "🌐 Tilni tanlang:",
        "ru": "🌐 Выберите язык:",
        "en": "🌐 Choose your language:",
    },
    # Birinchi marta — uchala tilda, chunki odam qaysi tilni tushunishini
    # hali bilmaymiz.
    "lang.choose_first": {
        "uz": "🌐 Tilni tanlang / Выберите язык / Choose language:",
        "ru": "🌐 Tilni tanlang / Выберите язык / Choose language:",
        "en": "🌐 Tilni tanlang / Выберите язык / Choose language:",
    },
    "lang.saved": {
        "uz": "✅ Til o'zgartirildi.",
        "ru": "✅ Язык изменён.",
        "en": "✅ Language changed.",
    },
    "lang.choose_group": {
        "uz": "🌐 Guruhga ketadigan xabarlar tilini tanlang:",
        "ru": "🌐 Выберите язык сообщений для группы:",
        "en": "🌐 Choose the language for group messages:",
    },
    "lang.group_saved": {
        "uz": "✅ Guruh xabarlari tili o'zgartirildi.",
        "ru": "✅ Язык сообщений группы изменён.",
        "en": "✅ Group message language changed.",
    },

    # --- Guruhga ketadigan signal xabarlari (workspaces.lang bo'yicha) ---
    "ev.open": {
        "uz": "▶️ <b>#{sid} {sym}</b> — pozitsiya ochildi @ <b>{p}</b>",
        "ru": "▶️ <b>#{sid} {sym}</b> — позиция открыта @ <b>{p}</b>",
        "en": "▶️ <b>#{sid} {sym}</b> — position opened @ <b>{p}</b>",
    },
    "ev.tp": {
        "uz": "✅ <b>#{sid} {sym}</b> — TP{n} bajarildi @ <b>{p}</b>  ({share:.0%} sotildi)\nJoriy natija: <b>{run:+.2f}%</b>",
        "ru": "✅ <b>#{sid} {sym}</b> — TP{n} исполнен @ <b>{p}</b>  (продано {share:.0%})\nТекущий результат: <b>{run:+.2f}%</b>",
        "en": "✅ <b>#{sid} {sym}</b> — TP{n} filled @ <b>{p}</b>  ({share:.0%} sold)\nRunning result: <b>{run:+.2f}%</b>",
    },
    "ev.be": {
        "uz": "🛡 <b>#{sid} {sym}</b> — stop breakeven'ga ko'chirildi",
        "ru": "🛡 <b>#{sid} {sym}</b> — стоп перенесён в безубыток",
        "en": "🛡 <b>#{sid} {sym}</b> — stop moved to breakeven",
    },
    "ev.expired": {
        "uz": "⌛️ <b>#{sid} {sym}</b> — entryga tegmadi, bekor qilindi",
        "ru": "⌛️ <b>#{sid} {sym}</b> — вход не сработал, отменён",
        "en": "⌛️ <b>#{sid} {sym}</b> — entry never filled, cancelled",
    },
    "ev.tp_closes": {
        "uz": "\n🏁 Signal yopildi: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
        "ru": "\n🏁 Сигнал закрыт: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
        "en": "\n🏁 Signal closed: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
    },
    "ev.stop_be": {
        "uz": "🛡 <b>#{sid} {sym}</b> — breakeven'da yopildi ({pnl:+.2f}%)",
        "ru": "🛡 <b>#{sid} {sym}</b> — закрыт в безубыток ({pnl:+.2f}%)",
        "en": "🛡 <b>#{sid} {sym}</b> — closed at breakeven ({pnl:+.2f}%)",
    },
    "ev.stop_win": {
        "uz": "✅ <b>#{sid} {sym}</b> — stopda yopildi\nYakuniy: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
        "ru": "✅ <b>#{sid} {sym}</b> — закрыт по стопу\nИтог: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
        "en": "✅ <b>#{sid} {sym}</b> — closed at stop\nFinal: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
    },
    "ev.stop_loss": {
        "uz": "❌ <b>#{sid} {sym}</b> — stop loss @ <b>{p}</b>\nYakuniy: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
        "ru": "❌ <b>#{sid} {sym}</b> — стоп-лосс @ <b>{p}</b>\nИтог: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
        "en": "❌ <b>#{sid} {sym}</b> — stop loss @ <b>{p}</b>\nFinal: <b>{pnl:+.2f}%</b> ({r:+.2f}R)",
    },
    "ev.manual_close": {
        "uz": "{icon} <b>#{sid} {sym}</b> — vaqtidan oldin yopildi @ <b>{p}</b>\nYakuniy: <b>{pnl:+.2f}%</b>{rtxt}",
        "ru": "{icon} <b>#{sid} {sym}</b> — закрыт досрочно @ <b>{p}</b>\nИтог: <b>{pnl:+.2f}%</b>{rtxt}",
        "en": "{icon} <b>#{sid} {sym}</b> — closed early @ <b>{p}</b>\nFinal: <b>{pnl:+.2f}%</b>{rtxt}",
    },
    "ev.partial_rest": {
        "uz": "{icon} <b>#{sid} {sym}</b> — qolgan qism yopildi @ <b>{p}</b>\nYakuniy: <b>{pnl:+.2f}%</b>{rtxt}",
        "ru": "{icon} <b>#{sid} {sym}</b> — остаток закрыт @ <b>{p}</b>\nИтог: <b>{pnl:+.2f}%</b>{rtxt}",
        "en": "{icon} <b>#{sid} {sym}</b> — remainder closed @ <b>{p}</b>\nFinal: <b>{pnl:+.2f}%</b>{rtxt}",
    },
    "ev.partial": {
        "uz": "✂️ <b>#{sid} {sym}</b> — pozitsiyaning <b>{pct}%</b> i yopildi @ <b>{p}</b>\nJoriy natija: <b>{run:+.2f}%</b> (qolgan {rest:.0f}%)",
        "ru": "✂️ <b>#{sid} {sym}</b> — закрыто <b>{pct}%</b> позиции @ <b>{p}</b>\nТекущий результат: <b>{run:+.2f}%</b> (осталось {rest:.0f}%)",
        "en": "✂️ <b>#{sid} {sym}</b> — <b>{pct}%</b> of the position closed @ <b>{p}</b>\nRunning result: <b>{run:+.2f}%</b> ({rest:.0f}% left)",
    },
    "ev.stop_moved": {
        "uz": "🛡 <b>#{sid} {sym}</b> — stop <b>{p}</b> ga ko'chirildi",
        "ru": "🛡 <b>#{sid} {sym}</b> — стоп перенесён на <b>{p}</b>",
        "en": "🛡 <b>#{sid} {sym}</b> — stop moved to <b>{p}</b>",
    },
    "ev.be_moved": {
        "uz": "🛡 <b>#{sid} {sym}</b> — stop breakeven'ga ko'chirildi (<b>{p}</b>)",
        "ru": "🛡 <b>#{sid} {sym}</b> — стоп перенесён в безубыток (<b>{p}</b>)",
        "en": "🛡 <b>#{sid} {sym}</b> — stop moved to breakeven (<b>{p}</b>)",
    },
    "ev.tps_changed": {
        "uz": "🎯 <b>#{sid} {sym}</b> — maqsadlar yangilandi: {tps}",
        "ru": "🎯 <b>#{sid} {sym}</b> — цели обновлены: {tps}",
        "en": "🎯 <b>#{sid} {sym}</b> — targets updated: {tps}",
    },
    "ev.tpsl_placed": {
        "uz": "📐 <b>#{sid} {sym}</b> — TP/SL joylashtirildi:\n{body}",
        "ru": "📐 <b>#{sid} {sym}</b> — TP/SL установлены:\n{body}",
        "en": "📐 <b>#{sid} {sym}</b> — TP/SL placed:\n{body}",
    },
    "ev.entry_changed": {
        "uz": "✏️ <b>#{sid} {sym}</b> — kirish narxi <b>{p}</b> ga o'zgartirildi",
        "ru": "✏️ <b>#{sid} {sym}</b> — цена входа изменена на <b>{p}</b>",
        "en": "✏️ <b>#{sid} {sym}</b> — entry price changed to <b>{p}</b>",
    },

    # --- Asosiy menyu ---
    "menu.title": {
        "uz": "Trade Controller — {name} 👇",
        "ru": "Trade Controller — {name} 👇",
        "en": "Trade Controller — {name} 👇",
    },
    "menu.new_signal": {
        "uz": "➕ Yangi signal",
        "ru": "➕ Новый сигнал",
        "en": "➕ New signal",
    },
    "menu.deposit": {
        "uz": "💰 Depozit",
        "ru": "💰 Депозит",
        "en": "💰 Deposit",
    },
    "menu.stats": {
        "uz": "📊 Statistika",
        "ru": "📊 Статистика",
        "en": "📊 Statistics",
    },
    "menu.symbols": {
        "uz": "📉 Juftliklar",
        "ru": "📉 Пары",
        "en": "📉 Pairs",
    },
    "menu.open": {
        "uz": "🔓 Ochiq signallar",
        "ru": "🔓 Открытые сигналы",
        "en": "🔓 Open signals",
    },
    "menu.equity": {
        "uz": "📈 Equity",
        "ru": "📈 Equity",
        "en": "📈 Equity",
    },
    "menu.news": {
        "uz": "📰 News Trade AI",
        "ru": "📰 News Trade AI",
        "en": "📰 News Trade AI",
    },
    "menu.page": {
        "uz": "🌐 Ochiq sahifa",
        "ru": "🌐 Публичная страница",
        "en": "🌐 Public page",
    },
    "menu.help": {
        "uz": "❓ Yordam",
        "ru": "❓ Помощь",
        "en": "❓ Help",
    },
    "menu.switch": {
        "uz": "🔁 Boshqa joyga o'tish",
        "ru": "🔁 Сменить рабочее место",
        "en": "🔁 Switch workspace",
    },
    "menu.home": {
        "uz": "🏠 Bosh menyu",
        "ru": "🏠 Главное меню",
        "en": "🏠 Main menu",
    },
    "menu.lang": {
        "uz": "🌐 Til",
        "ru": "🌐 Язык",
        "en": "🌐 Language",
    },
}


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Tarjima. Kalit yoki tarjima topilmasa — o'zbekchaga, u ham
    bo'lmasa kalitning o'ziga qaytadi (ekran hech qachon bo'sh
    qolmasin). `kwargs` berilsa `str.format` bilan qo'yiladi."""
    lang = normalize(lang)
    row = STRINGS.get(key)
    if not row:
        return key
    text = row.get(lang) or row.get(DEFAULT_LANG) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            # Tarjimada noto'g'ri/yetishmaydigan o'rin qolsa ham xabar
            # YUBORILISHI kerak — xom matn bo'sh ekrandan yaxshiroq.
            return text
    return text


def missing() -> dict[str, list[str]]:
    """Qaysi kalitda qaysi til yozilmaganini qaytaradi — tarjimani
    to'ldirib borishda (va sinovda) tekshirish uchun."""
    out: dict[str, list[str]] = {}
    for key, row in STRINGS.items():
        gaps = [lg for lg in LANGS if not row.get(lg)]
        if gaps:
            out[key] = gaps
    return out
