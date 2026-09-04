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
    "lang.group_saved": {
        "uz": "✅ Guruh xabarlari tili o'zgartirildi.",
        "ru": "✅ Язык сообщений группы изменён.",
        "en": "✅ Group message language changed.",
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
