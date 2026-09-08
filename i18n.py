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

    # --- Sehrgar (yangi signal) ---
    "wiz.cancel_btn": {
        "uz": "❌ Bekor qilish", "ru": "❌ Отмена", "en": "❌ Cancel",
    },
    "wiz.mode_market": {
        "uz": "🎯 Oddiy (darhol)", "ru": "🎯 Обычный (сразу)", "en": "🎯 Market (now)",
    },
    "wiz.mode_limit": {
        "uz": "⏳ Limit (narxni kutadi)", "ru": "⏳ Лимит (ждёт цену)",
        "en": "⏳ Limit (waits for price)",
    },
    "wiz.dm_only": {
        "uz": "Iltimos, botga shaxsiy xabar (DM) yozib, shu yerda qayta urining.",
        "ru": "Напишите боту в личные сообщения и повторите там.",
        "en": "Please message the bot privately (DM) and try again there.",
    },
    "wiz.no_right": {
        "uz": "Sizda bu joy uchun signal kiritish huquqi yo'q.",
        "ru": "У вас нет прав добавлять сигналы в этом рабочем месте.",
        "en": "You don't have permission to add signals here.",
    },
    "wiz.step_symbol": {
        "uz": "1/6 — Juftlik nomini yozing (masalan BTCUSDT):",
        "ru": "1/6 — Напишите название пары (например BTCUSDT):",
        "en": "1/6 — Type the pair name (e.g. BTCUSDT):",
    },
    "wiz.lost": {
        "uz": "Sehrgar bekor qilingan. Qaytadan boshlash uchun /new yozing.",
        "ru": "Мастер отменён. Чтобы начать заново, напишите /new.",
        "en": "The wizard was cancelled. Type /new to start again.",
    },
    "wiz.symbol_not_found": {
        "uz": "❌ <code>{raw}</code> topilmadi (kripto, forex yoki aksiya). Qayta yozing:",
        "ru": "❌ <code>{raw}</code> не найдено (крипто, форекс или акции). Напишите ещё раз:",
        "en": "❌ <code>{raw}</code> not found (crypto, forex or stocks). Type it again:",
    },
    "wiz.checking": {
        "uz": "🔎 Juftlikni tekshiryapman…", "ru": "🔎 Проверяю пару…",
        "en": "🔎 Checking the pair…",
    },
    "wiz.step_mode": {
        "uz": "2/6 — {sym}: qanday kirasiz?\n\n🎯 <b>Oddiy</b> — signal darhol \"ochiq\" deb hisoblanadi (xuddi shu narxda allaqachon kirgandek).\n⏳ <b>Limit</b> — narx kirish darajasiga tegmaguncha kutadi (standart).",
        "ru": "2/6 — {sym}: как входите?\n\n🎯 <b>Обычный</b> — сигнал сразу считается \"открытым\" (как будто вы уже вошли по этой цене).\n⏳ <b>Лимит</b> — ждёт, пока цена дойдёт до уровня входа (по умолчанию).",
        "en": "2/6 — {sym}: how do you enter?\n\n🎯 <b>Market</b> — the signal counts as \"open\" right away (as if you already entered at this price).\n⏳ <b>Limit</b> — waits until price reaches the entry level (default).",
    },
    "wiz.mode_picked": {
        "uz": "2/6 — Kirish rejimi: {label}", "ru": "2/6 — Режим входа: {label}",
        "en": "2/6 — Entry mode: {label}",
    },
    "wiz.step_side": {
        "uz": "3/6 — Yo'nalishni tanlang:", "ru": "3/6 — Выберите направление:",
        "en": "3/6 — Choose the direction:",
    },
    "wiz.side_picked": {
        "uz": "3/6 — Yo'nalish: {side}", "ru": "3/6 — Направление: {side}",
        "en": "3/6 — Direction: {side}",
    },
    "wiz.entry_auto": {
        "uz": "4/6 — Entry avtomatik: <b>{p}</b> (joriy bozor narxi)\n\n5/6 — TP narx(lar)ini kiriting (bir nechta bo'lsa bo'sh joy bilan ajrating, masalan: 67000 68500):",
        "ru": "4/6 — Вход автоматически: <b>{p}</b> (текущая рыночная цена)\n\n5/6 — Введите цену(ы) TP (несколько — через пробел, например: 67000 68500):",
        "en": "4/6 — Entry set automatically: <b>{p}</b> (current market price)\n\n5/6 — Enter the TP price(s) (separate several with spaces, e.g. 67000 68500):",
    },
    "wiz.entry_auto_failed": {
        "uz": "⚠️ Joriy bozor narxini olib bo'lmadi — entryni qo'lda kiriting:",
        "ru": "⚠️ Не удалось получить рыночную цену — введите вход вручную:",
        "en": "⚠️ Couldn't fetch the market price — enter the entry manually:",
    },
    "wiz.step_entry": {
        "uz": "4/6 — Entry (limit) narxini kiriting.\nTP/SL narx to'lgach so'raladi:",
        "ru": "4/6 — Введите цену входа (лимит).\nTP/SL спросим после исполнения:",
        "en": "4/6 — Enter the (limit) entry price.\nTP/SL will be asked once it fills:",
    },
    "wiz.step_tp": {
        "uz": "5/6 — TP narx(lar)ini kiriting (bir nechta bo'lsa bo'sh joy bilan ajrating, masalan: 67000 68500):",
        "ru": "5/6 — Введите цену(ы) TP (несколько — через пробел, например: 67000 68500):",
        "en": "5/6 — Enter the TP price(s) (separate several with spaces, e.g. 67000 68500):",
    },
    "wiz.step_sl": {
        "uz": "6/6 — SL (stop-loss) narxini kiriting:",
        "ru": "6/6 — Введите цену SL (стоп-лосс):",
        "en": "6/6 — Enter the SL (stop-loss) price:",
    },
    "wiz.bad_number": {
        "uz": "Noto'g'ri raqam. Qayta kiriting:", "ru": "Неверное число. Введите ещё раз:",
        "en": "Invalid number. Enter it again:",
    },
    "wiz.bad_format": {
        "uz": "Noto'g'ri format. Qayta kiriting:", "ru": "Неверный формат. Введите ещё раз:",
        "en": "Invalid format. Enter it again:",
    },
    "wiz.cancelled": {
        "uz": "❌ Bekor qilindi.", "ru": "❌ Отменено.", "en": "❌ Cancelled.",
    },
    "side.long": {"uz": "🟢 LONG", "ru": "🟢 LONG", "en": "🟢 LONG"},
    "side.short": {"uz": "🔴 SHORT", "ru": "🔴 SHORT", "en": "🔴 SHORT"},

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

    # --- Signal kartasi (guruhga ham, shaxsiy ko'rikka ham shu matn ketadi) ---
    "sig.entry": {
        "uz": "Kirish", "ru": "Вход", "en": "Entry",
    },
    "sig.entry_now": {
        "uz": " <i>(🎯 darhol kirilgan)</i>",
        "ru": " <i>(🎯 вход сразу)</i>",
        "en": " <i>(🎯 entered at market)</i>",
    },
    "sig.tpsl_later": {
        "uz": "<i>TP/SL — limit to'lgandan keyin so'raladi.</i>",
        "ru": "<i>TP/SL — спросим после исполнения лимита.</i>",
        "en": "<i>TP/SL will be asked once the limit fills.</i>",
    },
    "sig.stop": {
        "uz": "Stop", "ru": "Стоп", "en": "Stop",
    },
    "sig.rr": {
        "uz": "Risk/Reward", "ru": "Риск/Прибыль", "en": "Risk/Reward",
    },
    "sig.accepted": {
        "uz": "✅ Signal <code>#{sid}</code> qabul qilindi.",
        "ru": "✅ Сигнал <code>#{sid}</code> принят.",
        "en": "✅ Signal <code>#{sid}</code> accepted.",
    },

    # --- Ko'rik (preview) ---
    "prev.checking": {
        "uz": "🔎 Juftlikni tekshiryapman…",
        "ru": "🔎 Проверяю пару…",
        "en": "🔎 Checking the pair…",
    },
    "prev.not_found": {
        "uz": ("❌ <code>{sym}</code> topilmadi (kripto, forex yoki aksiya).\n"
               "Nomni tekshiring — masalan <code>BTCUSDT</code>, <code>btc</code>, "
               "<code>EURUSD</code>, <code>TSLA</code>."),
        "ru": ("❌ <code>{sym}</code> не найден (крипто, форекс или акции).\n"
               "Проверьте название — например <code>BTCUSDT</code>, <code>btc</code>, "
               "<code>EURUSD</code>, <code>TSLA</code>."),
        "en": ("❌ <code>{sym}</code> not found (crypto, forex or stocks).\n"
               "Check the name — e.g. <code>BTCUSDT</code>, <code>btc</code>, "
               "<code>EURUSD</code>, <code>TSLA</code>."),
    },
    "prev.warn_short_spot": {
        "uz": "⚠️ SPOT rejimida SHORT savdo qilinmaydi — statistikaga kirmaydi.",
        "ru": "⚠️ В режиме SPOT шорт не торгуется — в статистику не войдёт.",
        "en": "⚠️ SHORT is not traded in SPOT mode — it will not count in the stats.",
    },
    "prev.warn_market": {
        "uz": "🎯 Oddiy rejim — tasdiqlansa signal darhol \"ochiq\" deb belgilanadi.",
        "ru": "🎯 Обычный режим — после подтверждения сигнал сразу станет «открытым».",
        "en": "🎯 Market mode — once confirmed the signal is marked \"open\" right away.",
    },
    "prev.warn_limit_tpsl": {
        "uz": "📐 Limit to'lganda TP/SL kiritishingiz so'raladi.",
        "ru": "📐 После исполнения лимита попросим ввести TP/SL.",
        "en": "📐 You will be asked for TP/SL once the limit fills.",
    },
    "prev.cur_price": {
        "uz": "Joriy narx: <b>{p}</b> (entrydan {d:+.2f}%)",
        "ru": "Текущая цена: <b>{p}</b> ({d:+.2f}% от входа)",
        "en": "Current price: <b>{p}</b> ({d:+.2f}% from entry)",
    },
    "prev.pic_q": {
        "uz": "<b>Rasm qanday bo'lsin?</b>",
        "ru": "<b>Какую картинку поставить?</b>",
        "en": "<b>Which image should be used?</b>",
    },
    "prev.btn_own_pic": {
        "uz": "🖼 Yuborgan rasmim bilan",
        "ru": "🖼 С моей картинкой",
        "en": "🖼 Use my image",
    },
    "prev.btn_upload_pic": {
        "uz": "🖼 Rasm yuklash", "ru": "🖼 Загрузить картинку", "en": "🖼 Upload an image",
    },
    "prev.btn_bot_chart": {
        "uz": "📈 Bot grafikni aniqlasin",
        "ru": "📈 Пусть бот построит график",
        "en": "📈 Let the bot draw the chart",
    },
    "prev.btn_no_pic": {
        "uz": "📝 Rasmsiz davom etish",
        "ru": "📝 Продолжить без картинки",
        "en": "📝 Continue without an image",
    },
    "prev.btn_edit": {
        "uz": "✏️ Tahrirlash", "ru": "✏️ Изменить", "en": "✏️ Edit",
    },
    "prev.btn_cancel": {
        "uz": "🗑 Bekor", "ru": "🗑 Отмена", "en": "🗑 Cancel",
    },
    "prev.confirm_note": {
        "uz": "✅ Tasdiqlasangiz guruhga shu ko'rinishda yuboriladi.",
        "ru": "✅ После подтверждения в группу уйдёт именно в таком виде.",
        "en": "✅ Once confirmed, it goes to the group exactly like this.",
    },
    "prev.btn_confirm": {
        "uz": "✅ Tasdiqlash va yuborish",
        "ru": "✅ Подтвердить и отправить",
        "en": "✅ Confirm and send",
    },

    # --- Darajalarni tekshirish xatolari (parsing.validate) ---
    "err.positive": {
        "uz": "Narxlar musbat bo'lishi kerak.",
        "ru": "Цены должны быть положительными.",
        "en": "Prices must be positive.",
    },
    "err.sl_long": {
        "uz": "LONG uchun SL ({sl}) entry ({e}) dan past bo'lishi kerak.",
        "ru": "Для LONG стоп ({sl}) должен быть ниже входа ({e}).",
        "en": "For LONG the SL ({sl}) must be below the entry ({e}).",
    },
    "err.tp_long": {
        "uz": "LONG uchun barcha TP entry ({e}) dan yuqori bo'lishi kerak.",
        "ru": "Для LONG все TP должны быть выше входа ({e}).",
        "en": "For LONG every TP must be above the entry ({e}).",
    },
    "err.sl_short": {
        "uz": "SHORT uchun SL ({sl}) entry ({e}) dan yuqori bo'lishi kerak.",
        "ru": "Для SHORT стоп ({sl}) должен быть выше входа ({e}).",
        "en": "For SHORT the SL ({sl}) must be above the entry ({e}).",
    },
    "err.tp_short": {
        "uz": "SHORT uchun barcha TP entry ({e}) dan past bo'lishi kerak.",
        "ru": "Для SHORT все TP должны быть ниже входа ({e}).",
        "en": "For SHORT every TP must be below the entry ({e}).",
    },

    # --- Boshqaruv ekrani (ochiq signal) ---
    "man.entry": {"uz": "Kirish", "ru": "Вход", "en": "Entry"},
    "man.stop": {"uz": "Stop", "ru": "Стоп", "en": "Stop"},
    "man.targets": {"uz": "Maqsadlar", "ru": "Цели", "en": "Targets"},
    "man.closed_share": {
        "uz": "Yopilgan ulush: <b>{pct:.0f}%</b> (to'plangan {run:+.2f}%)",
        "ru": "Закрытая доля: <b>{pct:.0f}%</b> (накоплено {run:+.2f}%)",
        "en": "Closed share: <b>{pct:.0f}%</b> (accrued {run:+.2f}%)",
    },
    "man.live": {
        "uz": "Joriy narx: <b>{p}</b> → <b>{live:+.2f}%</b>",
        "ru": "Текущая цена: <b>{p}</b> → <b>{live:+.2f}%</b>",
        "en": "Current price: <b>{p}</b> → <b>{live:+.2f}%</b>",
    },
    "man.no_price": {
        "uz": "<i>Joriy narx olinmadi</i>",
        "ru": "<i>Текущая цена недоступна</i>",
        "en": "<i>Current price unavailable</i>",
    },
    "man.no_tpsl": {
        "uz": "<i>TP/SL hali kiritilmagan.</i>",
        "ru": "<i>TP/SL ещё не заданы.</i>",
        "en": "<i>TP/SL not set yet.</i>",
    },
    "man.btn_tpsl": {
        "uz": "📐 TP/SL kiriting", "ru": "📐 Задать TP/SL", "en": "📐 Set TP/SL",
    },
    "man.btn_entry": {"uz": "✏️ Entry", "ru": "✏️ Вход", "en": "✏️ Entry"},
    "man.btn_cancel": {
        "uz": "❌ Bekor qilish", "ru": "❌ Отменить", "en": "❌ Cancel",
    },
    "man.btn_close": {
        "uz": "🔒 To'liq yopish", "ru": "🔒 Закрыть полностью", "en": "🔒 Close fully",
    },
    "man.btn_be": {
        "uz": "🛡 Stop → breakeven{be}", "ru": "🛡 Стоп → безубыток{be}",
        "en": "🛡 Stop → breakeven{be}",
    },
    "man.btn_sl": {"uz": "✏️ Stop", "ru": "✏️ Стоп", "en": "✏️ Stop"},
    "man.btn_tp": {
        "uz": "🎯 Maqsadlarni o'zgartirish", "ru": "🎯 Изменить цели",
        "en": "🎯 Change targets",
    },
    "man.gone": {
        "uz": "Bu signal allaqachon yopilgan yoki topilmadi.",
        "ru": "Этот сигнал уже закрыт или не найден.",
        "en": "This signal is already closed or was not found.",
    },
    "man.no_right": {
        "uz": "Ruxsat yo'q.", "ru": "Нет доступа.", "en": "No permission.",
    },
    "man.be_already": {
        "uz": "Stop allaqachon breakeven'da.",
        "ru": "Стоп уже в безубытке.",
        "en": "The stop is already at breakeven.",
    },
    "man.be_breached": {
        "uz": ("Joriy narx ({p}) kirish narxidan {dir} — breakeven'ga ko'chirish "
               "signalni DARHOL yopadi. Shuni xohlasangiz \"To'liq yopish\"ni bosing."),
        "ru": ("Текущая цена ({p}) {dir} цены входа — перенос в безубыток ЗАКРОЕТ "
               "сигнал СРАЗУ. Если вы этого хотите, нажмите «Закрыть полностью»."),
        "en": ("The current price ({p}) is {dir} the entry — moving to breakeven "
               "will close the signal IMMEDIATELY. If that is what you want, press "
               "\"Close fully\"."),
    },
    "man.dir_below": {"uz": "past", "ru": "ниже", "en": "below"},
    "man.dir_above": {"uz": "baland", "ru": "выше", "en": "above"},
    "man.ask_sl": {
        "uz": ("✏️ #{sid} {sym} uchun <b>yangi stop</b> narxini yozing.\n"
               "Hozirgi: <code>{cur}</code>\n\nBekor qilish uchun /bekor"),
        "ru": ("✏️ Введите <b>новый стоп</b> для #{sid} {sym}.\n"
               "Сейчас: <code>{cur}</code>\n\nДля отмены — /bekor"),
        "en": ("✏️ Send the <b>new stop</b> price for #{sid} {sym}.\n"
               "Current: <code>{cur}</code>\n\nSend /bekor to cancel"),
    },
    "man.ask_entry": {
        "uz": ("✏️ #{sid} {sym} uchun <b>yangi entry (limit)</b> narxini yozing.\n"
               "Hozirgi: <code>{cur}</code>\n\nBekor qilish uchun /bekor"),
        "ru": ("✏️ Введите <b>новую цену входа (лимит)</b> для #{sid} {sym}.\n"
               "Сейчас: <code>{cur}</code>\n\nДля отмены — /bekor"),
        "en": ("✏️ Send the <b>new entry (limit)</b> price for #{sid} {sym}.\n"
               "Current: <code>{cur}</code>\n\nSend /bekor to cancel"),
    },
    "man.ask_tps": {
        "uz": ("🎯 #{sid} {sym} uchun <b>yangi maqsadlar</b>ni yozing (bo'sh joy "
               "bilan ajrating).\nHozirgi: <code>{cur}</code>\n\n"
               "Bekor qilish uchun /bekor"),
        "ru": ("🎯 Введите <b>новые цели</b> для #{sid} {sym} (через пробел).\n"
               "Сейчас: <code>{cur}</code>\n\nДля отмены — /bekor"),
        "en": ("🎯 Send the <b>new targets</b> for #{sid} {sym} (space separated).\n"
               "Current: <code>{cur}</code>\n\nSend /bekor to cancel"),
    },
    "man.entry_pending_only": {
        "uz": "Entry faqat hali tegmagan (PENDING) signalda o'zgartiriladi.",
        "ru": "Вход меняется только у сигнала, который ещё не исполнен (PENDING).",
        "en": "The entry can only be changed while the signal is still PENDING.",
    },
    "man.partial_failed": {
        "uz": "Yopib bo'lmadi (narx olinmadi yoki qism qolmagan).",
        "ru": "Не удалось закрыть (нет цены или не осталось доли).",
        "en": "Could not close (no price, or no share left).",
    },
    "man.closed_full": {
        "uz": "{icon} #{sid} {sym} to'liq yopildi: <b>{pnl:+.2f}%</b>{rtxt}",
        "ru": "{icon} #{sid} {sym} закрыт полностью: <b>{pnl:+.2f}%</b>{rtxt}",
        "en": "{icon} #{sid} {sym} fully closed: <b>{pnl:+.2f}%</b>{rtxt}",
    },
    "man.sig_closed": {
        "uz": "Signal allaqachon yopilgan.",
        "ru": "Сигнал уже закрыт.",
        "en": "The signal is already closed.",
    },
    "man.bad_number": {
        "uz": "Noto'g'ri raqam. Qayta kiriting yoki /bekor.",
        "ru": "Неверное число. Введите снова или /bekor.",
        "en": "Invalid number. Try again or /bekor.",
    },
    "man.bad_format": {
        "uz": "Noto'g'ri format. Qayta kiriting yoki /bekor.",
        "ru": "Неверный формат. Введите снова или /bekor.",
        "en": "Invalid format. Try again or /bekor.",
    },
    "man.sl_breached": {
        "uz": ("⚠️ Joriy narx (<code>{p}</code>) bu stopdan {dir} — signal KEYINGI "
               "tekshiruvda DARHOL yopiladi (stop allaqachon tegilgan hisoblanadi). "
               "Shuni xohlasangiz \"🔒 To'liq yopish\" tugmasidan foydalaning, "
               "aks holda boshqa narx kiriting yoki /bekor."),
        "ru": ("⚠️ Текущая цена (<code>{p}</code>) {dir} этого стопа — сигнал будет "
               "закрыт СРАЗУ на следующей проверке (стоп считается уже задетым). "
               "Если вы этого хотите, нажмите «🔒 Закрыть полностью», иначе введите "
               "другую цену или /bekor."),
        "en": ("⚠️ The current price (<code>{p}</code>) is {dir} this stop — the signal "
               "will be closed IMMEDIATELY on the next check (the stop counts as already "
               "hit). If that is what you want, use \"🔒 Close fully\"; otherwise send "
               "another price or /bekor."),
    },
    "man.dir_below_caps": {"uz": "PAST", "ru": "НИЖЕ", "en": "BELOW"},
    "man.dir_above_caps": {"uz": "BALAND", "ru": "ВЫШЕ", "en": "ABOVE"},
    "man.stop_set": {
        "uz": "✅ Stop <b>{p}</b> ga o'rnatildi.",
        "ru": "✅ Стоп установлен на <b>{p}</b>.",
        "en": "✅ Stop set to <b>{p}</b>.",
    },
    "man.entry_set": {
        "uz": "✅ Entry <b>{p}</b> ga o'rnatildi.",
        "ru": "✅ Вход установлен на <b>{p}</b>.",
        "en": "✅ Entry set to <b>{p}</b>.",
    },
    "man.tps_set": {
        "uz": "✅ Maqsadlar: <b>{tps}</b>",
        "ru": "✅ Цели: <b>{tps}</b>",
        "en": "✅ Targets: <b>{tps}</b>",
    },
    "man.tps_too_few": {
        "uz": ("Kamida {n} ta maqsad kerak — {n} tasi allaqachon bajarilgan. "
               "Qayta kiriting yoki /bekor."),
        "ru": ("Нужно минимум {n} целей — {n} уже исполнено. Введите снова или /bekor."),
        "en": ("At least {n} targets are required — {n} are already filled. "
               "Try again or /bekor."),
    },
    "man.entry_locked": {
        "uz": "Signal allaqachon bajarilgan yoki yopilgan — entry endi o'zgarmaydi.",
        "ru": "Сигнал уже исполнен или закрыт — вход больше не меняется.",
        "en": "The signal is already filled or closed — the entry can no longer change.",
    },
    "man.entry_far": {
        "uz": "Bu narx eski entrydan juda uzoq. Tekshiring yoki /bekor.",
        "ru": "Эта цена слишком далека от прежнего входа. Проверьте или /bekor.",
        "en": "This price is too far from the previous entry. Check it or /bekor.",
    },
    "man.entry_conflict": {
        "uz": "❌ {err}\nMavjud stop/maqsadlar bilan mos kelmayapti. Boshqa narx kiriting yoki /bekor.",
        "ru": "❌ {err}\nНе согласуется с текущим стопом/целями. Введите другую цену или /bekor.",
        "en": "❌ {err}\nDoes not fit the current stop/targets. Send another price or /bekor.",
    },

    # --- Birinchi TP/SL joylashtirish ---
    "tpsl.prompt": {
        "uz": ("📐 <b>#{sid} {sym}</b> — TP va SL kiriting:\n"
               "<code>tp 67000 68500 sl 64000</code>\n"
               "yoki qisqa: <code>67000 68500 64000</code> (oxirgisi — stop)."),
        "ru": ("📐 <b>#{sid} {sym}</b> — введите TP и SL:\n"
               "<code>tp 67000 68500 sl 64000</code>\n"
               "или коротко: <code>67000 68500 64000</code> (последнее — стоп)."),
        "en": ("📐 <b>#{sid} {sym}</b> — send the TP and SL:\n"
               "<code>tp 67000 68500 sl 64000</code>\n"
               "or short: <code>67000 68500 64000</code> (the last one is the stop)."),
    },
    "tpsl.not_needed": {
        "uz": "Bu so'rov endi kerak emas.",
        "ru": "Этот запрос больше не нужен.",
        "en": "This request is no longer needed.",
    },
    "tpsl.unreadable": {
        "uz": ("O'qiy olmadim. Namuna: <code>tp 67000 68500 sl 64000</code>\n"
               "yoki qisqa: <code>67000 68500 64000</code> (oxirgisi — stop). "
               "Yoki /bekor yozing."),
        "ru": ("Не смог прочитать. Пример: <code>tp 67000 68500 sl 64000</code>\n"
               "или коротко: <code>67000 68500 64000</code> (последнее — стоп). "
               "Или напишите /bekor."),
        "en": ("Could not read that. Example: <code>tp 67000 68500 sl 64000</code>\n"
               "or short: <code>67000 68500 64000</code> (the last one is the stop). "
               "Or send /bekor."),
    },
    "tpsl.retry": {
        "uz": "❌ {err}\nQayta kiriting yoki /bekor.",
        "ru": "❌ {err}\nВведите снова или /bekor.",
        "en": "❌ {err}\nTry again or /bekor.",
    },
    "tpsl.placed": {
        "uz": "✅ TP/SL joylashtirildi.\n\n{body}",
        "ru": "✅ TP/SL установлены.\n\n{body}",
        "en": "✅ TP/SL placed.\n\n{body}",
    },

    # --- Qo'lda yopish ---
    "close.ask_pending": {
        "uz": "#{sid} {sym} hali entryga tegmagan. Bekor qilinsinmi?",
        "ru": "#{sid} {sym} ещё не дошёл до входа. Отменить?",
        "en": "#{sid} {sym} has not reached the entry yet. Cancel it?",
    },
    "close.ask_active": {
        "uz": "#{sid} {sym} joriy narxda yopilsinmi?{est}",
        "ru": "Закрыть #{sid} {sym} по текущей цене?{est}",
        "en": "Close #{sid} {sym} at the current price?{est}",
    },
    "close.btn_yes": {
        "uz": "✅ Ha, yopish", "ru": "✅ Да, закрыть", "en": "✅ Yes, close",
    },
    "close.btn_no": {"uz": "↩️ Yo'q", "ru": "↩️ Нет", "en": "↩️ No"},
    "close.not_found": {"uz": "Topilmadi.", "ru": "Не найдено.", "en": "Not found."},
    "close.failed": {
        "uz": "Yopib bo'lmadi (narx olinmadi yoki allaqachon yopilgan).",
        "ru": "Не удалось закрыть (нет цены или уже закрыт).",
        "en": "Could not close (no price, or already closed).",
    },
    "close.cancelled_sig": {
        "uz": "🗑 #{sid} {sym} bekor qilindi (entryga tegmagan edi).",
        "ru": "🗑 #{sid} {sym} отменён (вход не был достигнут).",
        "en": "🗑 #{sid} {sym} cancelled (the entry was never reached).",
    },
    "close.done": {
        "uz": "{icon} #{sid} {sym} qo'lda yopildi @ {p}\nYakuniy: {pnl:+.2f}%{rtxt}",
        "ru": "{icon} #{sid} {sym} закрыт вручную @ {p}\nИтог: {pnl:+.2f}%{rtxt}",
        "en": "{icon} #{sid} {sym} closed manually @ {p}\nFinal: {pnl:+.2f}%{rtxt}",
    },
    "close.kept": {
        "uz": "↩️ Bekor qilindi, signal ochiq qoldi.",
        "ru": "↩️ Отменено, сигнал остался открытым.",
        "en": "↩️ Cancelled — the signal stays open.",
    },
    "prev.price_moved": {
        "uz": ("❌ Narx yangilandi (<b>{p}</b>), lekin endi darajalar mantiqan to'g'ri "
               "kelmaydi: {err}\n✏️ Tahrirlash orqali qayta kiriting."),
        "ru": ("❌ Цена обновилась (<b>{p}</b>), и уровни больше не согласуются: {err}\n"
               "✏️ Измените их через «Изменить»."),
        "en": ("❌ The price refreshed (<b>{p}</b>) and the levels no longer line up: "
               "{err}\n✏️ Use Edit to enter them again."),
    },

    # --- Ko'rik tugmalaridan keyingi qadamlar ---
    "prev.expired": {
        "uz": "Bu so'rov eskirgan.", "ru": "Этот запрос устарел.",
        "en": "This request has expired.",
    },
    "prev.cancelled": {
        "uz": "🗑 Bekor qilindi.", "ru": "🗑 Отменено.", "en": "🗑 Cancelled.",
    },
    "prev.ask_tf": {
        "uz": "📈 Yopilgandagi natija grafigi qaysi taym freymda chizilsin?",
        "ru": "📈 В каком таймфрейме рисовать график итогового результата?",
        "en": "📈 Which timeframe should the closing result chart use?",
    },
    "prev.send_photo": {
        "uz": "🖼 Grafik rasmni yuboring.\nFikringizdan qaytsangiz /bekor yozing.",
        "ru": "🖼 Пришлите картинку графика.\nПередумали — напишите /bekor.",
        "en": "🖼 Send the chart image.\nChanged your mind — send /bekor.",
    },
    "prev.drawing": {
        "uz": "📈 {tf} grafigi chizilmoqda…",
        "ru": "📈 Рисую график {tf}…",
        "en": "📈 Drawing the {tf} chart…",
    },
    "prev.draw_failed": {
        "uz": "⚠️ Grafik chizilmadi (birja javob bermadi). Signal rasmsiz yuboriladi.",
        "ru": "⚠️ График не построен (биржа не ответила). Сигнал уйдёт без картинки.",
        "en": "⚠️ The chart could not be drawn (the exchange did not answer). "
              "The signal will be sent without an image.",
    },
    "prev.ask_edit": {
        "uz": ("✏️ To'g'ri darajalarni yuboring:\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>"),
        "ru": ("✏️ Пришлите правильные уровни:\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>"),
        "en": ("✏️ Send the correct levels:\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>"),
    },

    # --- Statistika ---
    "st.title_all": {
        "uz": "Umumiy statistika", "ru": "Общая статистика", "en": "Overall stats",
    },
    "st.title_year": {
        "uz": "{y}-yil natijalari", "ru": "Итоги {y} года", "en": "{y} results",
    },
    "st.no_closed": {
        "uz": "Hali yopilgan signal yo'q.",
        "ru": "Закрытых сигналов пока нет.",
        "en": "No closed signals yet.",
    },
    "st.signals": {
        "uz": "Signallar: <b>{n}</b>  ({w}✅ / {l}❌ / {b}⚪)",
        "ru": "Сигналов: <b>{n}</b>  ({w}✅ / {l}❌ / {b}⚪)",
        "en": "Signals: <b>{n}</b>  ({w}✅ / {l}❌ / {b}⚪)",
    },
    "st.winrate": {
        "uz": "Winrate: <b>{wr:.1f}%</b>", "ru": "Винрейт: <b>{wr:.1f}%</b>",
        "en": "Win rate: <b>{wr:.1f}%</b>",
    },
    "st.total_dep": {
        "uz": "Jami natija (depozitga nisbatan): <b>{p:+.2f}%</b>",
        "ru": "Общий результат (к депозиту): <b>{p:+.2f}%</b>",
        "en": "Total result (vs deposit): <b>{p:+.2f}%</b>",
    },
    "st.total_raw": {
        "uz": "Jami foiz (pozitsiya hajmisiz): <b>{p:+.2f}%</b>",
        "ru": "Общий процент (без размера позиции): <b>{p:+.2f}%</b>",
        "en": "Total percent (position size ignored): <b>{p:+.2f}%</b>",
    },
    "st.compound": {
        "uz": "Kompaund: <b>{p:+.2f}%</b>", "ru": "Сложный процент: <b>{p:+.2f}%</b>",
        "en": "Compounded: <b>{p:+.2f}%</b>",
    },
    "st.real_money": {
        "uz": "💰 Real natija: <b>{m:+,.2f}</b>",
        "ru": "💰 Реальный результат: <b>{m:+,.2f}</b>",
        "en": "💰 Real result: <b>{m:+,.2f}</b>",
    },
    "st.avg_r": {
        "uz": "O'rtacha R: <b>{avg:+.2f}R</b>   |   Jami: <b>{tot:+.1f}R</b>",
        "ru": "Средний R: <b>{avg:+.2f}R</b>   |   Всего: <b>{tot:+.1f}R</b>",
        "en": "Average R: <b>{avg:+.2f}R</b>   |   Total: <b>{tot:+.1f}R</b>",
    },
    "st.avg_win_loss": {
        "uz": "O'rt. foyda: {w:+.2f}%   |   O'rt. zarar: {l:+.2f}%",
        "ru": "Ср. прибыль: {w:+.2f}%   |   Ср. убыток: {l:+.2f}%",
        "en": "Avg win: {w:+.2f}%   |   Avg loss: {l:+.2f}%",
    },
    "st.profit_factor": {
        "uz": "Profit factor: <b>{pf:.2f}</b>", "ru": "Профит-фактор: <b>{pf:.2f}</b>",
        "en": "Profit factor: <b>{pf:.2f}</b>",
    },
    "st.open_head": {
        "uz": "<b>Jarayondagi pozitsiyalar</b>", "ru": "<b>Позиции в работе</b>",
        "en": "<b>Positions in progress</b>",
    },
    "st.open_pending": {
        "uz": "🕐 Kutilmoqda: <b>{n}</b> ta (hali limitga yetmagan)",
        "ru": "🕐 Ожидают: <b>{n}</b> (лимит ещё не достигнут)",
        "en": "🕐 Waiting: <b>{n}</b> (the limit has not been reached)",
    },
    "st.open_noprice": {
        "uz": "⏳ Jarayonda: <b>{n}</b> ta ochiq (narx olinmadi)",
        "ru": "⏳ В работе: <b>{n}</b> открытых (цена недоступна)",
        "en": "⏳ In progress: <b>{n}</b> open (price unavailable)",
    },
    "st.open_live": {
        "uz": "⏳ Jarayonda: <b>{n}</b> ta ochiq — joriy: <b>{p:+.2f}%</b>",
        "ru": "⏳ В работе: <b>{n}</b> открытых — текущий: <b>{p:+.2f}%</b>",
        "en": "⏳ In progress: <b>{n}</b> open — current: <b>{p:+.2f}%</b>",
    },
    "st.open_no_dep": {
        "uz": "⏳ Jarayonda: <b>{n}</b> ta ochiq (joriy foiz uchun /depozit belgilang)",
        "ru": "⏳ В работе: <b>{n}</b> открытых (для текущего процента задайте /depozit)",
        "en": "⏳ In progress: <b>{n}</b> open (set /depozit to see the running percent)",
    },
    "st.no_data": {
        "uz": "Ma'lumot yo'q.", "ru": "Нет данных.", "en": "No data.",
    },
    "st.monthly_head": {
        "uz": "<b>Oylik natijalar</b>", "ru": "<b>Результаты по месяцам</b>",
        "en": "<b>Monthly results</b>",
    },
    "st.col_month": {"uz": "Oy", "ru": "Мес", "en": "Mon"},
    "st.col_pct": {"uz": "Foiz", "ru": "Проц", "en": "Pct"},
    "st.symbols_head": {
        "uz": "<b>Juftliklar — {title}</b>", "ru": "<b>Пары — {title}</b>",
        "en": "<b>Pairs — {title}</b>",
    },
    "st.all_period": {
        "uz": "Barcha davr", "ru": "Весь период", "en": "All time",
    },
    "st.running": {
        "uz": "<i>{p:+.2f}% jarayonda</i>", "ru": "<i>{p:+.2f}% в работе</i>",
        "en": "<i>{p:+.2f}% running</i>",
    },
    "st.open_word": {
        "uz": "<i>ochiq</i>", "ru": "<i>открыт</i>", "en": "<i>open</i>",
    },
    "st.tab_all": {"uz": "Barchasi", "ru": "Всё", "en": "All"},
    "st.tab_month": {"uz": "Oy", "ru": "Месяц", "en": "Month"},
    "st.tab_year": {"uz": "Yil", "ru": "Год", "en": "Year"},
    "st.btn_pdf": {
        "uz": "📄 PDF hisobot", "ru": "📄 PDF-отчёт", "en": "📄 PDF report",
    },
    "st.pdf_making": {
        "uz": "📄 Hisobot tayyorlanmoqda…", "ru": "📄 Готовлю отчёт…",
        "en": "📄 Preparing the report…",
    },
    "st.pdf_empty": {
        "uz": "Hali yopilgan signal yo'q — hisobot bo'sh bo'lardi.",
        "ru": "Закрытых сигналов пока нет — отчёт был бы пустым.",
        "en": "No closed signals yet — the report would be empty.",
    },

    # --- Ochiq signallar ro'yxati ---
    "op.none": {
        "uz": "Ochiq signal yo'q.", "ru": "Открытых сигналов нет.",
        "en": "No open signals.",
    },
    "op.head": {
        "uz": "<b>Ochiq signallar</b>", "ru": "<b>Открытые сигналы</b>",
        "en": "<b>Open signals</b>",
    },
    "op.btn_manage": {
        "uz": "⚙️ #{sid} {sym} — boshqarish",
        "ru": "⚙️ #{sid} {sym} — управление",
        "en": "⚙️ #{sid} {sym} — manage",
    },
    "eq.too_few": {
        "uz": "Grafik uchun kamida 2 ta yopilgan signal kerak.",
        "ru": "Для графика нужно минимум 2 закрытых сигнала.",
        "en": "The chart needs at least 2 closed signals.",
    },

    # --- Depozit ---
    "dep.unset": {
        "uz": "belgilanmagan", "ru": "не задан", "en": "not set",
    },
    "dep.current": {
        "uz": "Joriy depozit ({name}): <b>{v}</b>\n\nYangilash uchun: <code>/depozit 1000</code>",
        "ru": "Текущий депозит ({name}): <b>{v}</b>\n\nИзменить: <code>/depozit 1000</code>",
        "en": "Current deposit ({name}): <b>{v}</b>\n\nTo change it: <code>/depozit 1000</code>",
    },
    "menu.open_title": {
        "uz": "Bosh menyu:", "ru": "Главное меню:", "en": "Main menu:",
    },

    "dep.help": {
        "uz": ("Joriy depozit ({name}): <b>{v}</b>\n\n"
               "Yangilash uchun: <code>/depozit 1000</code>\n\n"
               "Depozit belgilansa, har bir yangi signal tasdiqlangach \"necha pul "
               "ishlatasiz\" deb so'raladi (ixtiyoriy) — shundan real (pulga bog'liq) "
               "foyda/zarar hisoblanadi."),
        "ru": ("Текущий депозит ({name}): <b>{v}</b>\n\n"
               "Изменить: <code>/depozit 1000</code>\n\n"
               "Если депозит задан, после подтверждения каждого сигнала бот спросит "
               "«сколько денег вы вкладываете» (по желанию) — из этого считается "
               "реальная прибыль/убыток в деньгах."),
        "en": ("Current deposit ({name}): <b>{v}</b>\n\n"
               "To change it: <code>/depozit 1000</code>\n\n"
               "With a deposit set, each confirmed signal asks how much money you "
               "are putting in (optional) — the real money profit/loss is computed "
               "from that."),
    },
    "dep.bad_amount": {
        "uz": "Noto'g'ri summa. Masalan: /depozit 1000",
        "ru": "Неверная сумма. Например: /depozit 1000",
        "en": "Invalid amount. For example: /depozit 1000",
    },
    "dep.updated": {
        "uz": "✅ Depozit yangilandi: <b>{v:,.2f}</b>",
        "ru": "✅ Депозит обновлён: <b>{v:,.2f}</b>",
        "en": "✅ Deposit updated: <b>{v:,.2f}</b>",
    },

    # --- Kun yakuni (guruhga ketadi -> guruh tili) ---
    "dg.head": {
        "uz": "📊 <b>Kun yakuni — {d}</b>", "ru": "📊 <b>Итоги дня — {d}</b>",
        "en": "📊 <b>Daily wrap-up — {d}</b>",
    },
    "dg.closed": {
        "uz": "Yopilgan signallar: <b>{n}</b>  ({w}✅ / {l}❌{be})",
        "ru": "Закрытых сигналов: <b>{n}</b>  ({w}✅ / {l}❌{be})",
        "en": "Closed signals: <b>{n}</b>  ({w}✅ / {l}❌{be})",
    },
    "dg.winrate": {
        "uz": "Winrate: <b>{wr:.0f}%</b>", "ru": "Винрейт: <b>{wr:.0f}%</b>",
        "en": "Win rate: <b>{wr:.0f}%</b>",
    },
    "dg.result": {
        "uz": "{icon} Natija ({label}): <b>{p:+.2f}%</b>",
        "ru": "{icon} Результат ({label}): <b>{p:+.2f}%</b>",
        "en": "{icon} Result ({label}): <b>{p:+.2f}%</b>",
    },
    "dg.label_dep": {
        "uz": "depozitga nisbatan", "ru": "к депозиту", "en": "vs deposit",
    },
    "dg.label_sum": {
        "uz": "yig'indi", "ru": "сумма", "en": "sum",
    },
    "dg.best": {
        "uz": "Eng yaxshi: <b>{sym}</b> {p:+.2f}%",
        "ru": "Лучшая: <b>{sym}</b> {p:+.2f}%",
        "en": "Best: <b>{sym}</b> {p:+.2f}%",
    },
    "dg.worst": {
        "uz": "Eng yomon: <b>{sym}</b> {p:+.2f}%",
        "ru": "Худшая: <b>{sym}</b> {p:+.2f}%",
        "en": "Worst: <b>{sym}</b> {p:+.2f}%",
    },
    "dg.open_n": {
        "uz": "{n} ta ochiq", "ru": "{n} открытых", "en": "{n} open",
    },
    "dg.pending_n": {
        "uz": "{n} ta kutilmoqda", "ru": "{n} ожидают", "en": "{n} waiting",
    },

    # --- Yordam ---
    "help.intro": {
        "uz": "❓ <b>Yordam</b>\n\nQaysi bo'lim bo'yicha yordam kerak?",
        "ru": "❓ <b>Помощь</b>\n\nПо какому разделу нужна помощь?",
        "en": "❓ <b>Help</b>\n\nWhich section do you need help with?",
    },
    "help.btn_setup": {
        "uz": "👥 Guruhni ulash", "ru": "👥 Подключить группу",
        "en": "👥 Connect a group",
    },
    "help.btn_signal": {
        "uz": "📈 Signal kiritish", "ru": "📈 Как отправить сигнал",
        "en": "📈 Sending a signal",
    },
    "help.btn_mode": {
        "uz": "⏳ Limit / Market", "ru": "⏳ Лимит / Маркет",
        "en": "⏳ Limit / Market",
    },
    "help.btn_errors": {
        "uz": "🔧 Xatolar", "ru": "🔧 Ошибки", "en": "🔧 Common errors",
    },
    "help.btn_images": {
        "uz": "🖼 Rasmli yo'riqnoma", "ru": "🖼 Инструкция в картинках",
        "en": "🖼 Illustrated guide",
    },
    "help.btn_guide": {
        "uz": "📘 To'liq qo'llanma (maqola)", "ru": "📘 Полное руководство (статья)",
        "en": "📘 Full guide (article)",
    },
    "help.btn_back": {
        "uz": "◀️ Yordam", "ru": "◀️ Помощь", "en": "◀️ Help",
    },
    "help.images_note": {
        "uz": "🖼 Yo'riqnoma rasmlari. Batafsil matn uchun bo'limni tanlang.",
        "ru": "🖼 Картинки инструкции. Для подробного текста выберите раздел.",
        "en": "🖼 Guide images. Pick a section for the full text.",
    },
    "help.setup": {
        "uz": ("👥 <b>Guruhni ulash</b>\n\n"
               "<b>1.</b> Botni guruhingizga qo'shing.\n"
               "<b>2.</b> Botga guruhda <b>admin</b> huquqini bering.\n"
               "<b>3.</b> Guruh ichida <code>/setup</code> yozing.\n\n"
               "Bot javob bersa — ulanish tugadi.\n\n"
               "⚠️ Diqqat qiling:\n"
               "• <code>/setup</code> ni <b>guruh ichida</b> yozing, shaxsiy chatda emas.\n"
               "• Faqat <b>guruh admini</b> qila oladi.\n"
               "• Bir admin — bitta guruh.\n"
               "• Admin huquqisiz bot guruhga post yubora olmaydi."),
        "ru": ("👥 <b>Подключение группы</b>\n\n"
               "<b>1.</b> Добавьте бота в свою группу.\n"
               "<b>2.</b> Дайте боту права <b>администратора</b>.\n"
               "<b>3.</b> Напишите <code>/setup</code> внутри группы.\n\n"
               "Бот ответил — подключение завершено.\n\n"
               "⚠️ Обратите внимание:\n"
               "• <code>/setup</code> пишите <b>в группе</b>, не в личном чате.\n"
               "• Это может сделать только <b>админ группы</b>.\n"
               "• Один админ — одна группа.\n"
               "• Без прав администратора бот не сможет писать в группу."),
        "en": ("👥 <b>Connecting a group</b>\n\n"
               "<b>1.</b> Add the bot to your group.\n"
               "<b>2.</b> Give the bot <b>admin</b> rights there.\n"
               "<b>3.</b> Type <code>/setup</code> inside the group.\n\n"
               "Once the bot replies, the group is connected.\n\n"
               "⚠️ Note:\n"
               "• Type <code>/setup</code> <b>in the group</b>, not in the private chat.\n"
               "• Only a <b>group admin</b> can do it.\n"
               "• One admin — one group.\n"
               "• Without admin rights the bot cannot post to the group."),
    },
    "help.signal": {
        "uz": ("📈 <b>Signal kiritish</b>\n\n"
               "Signal <b>botning shaxsiy chatiga</b> yoziladi — guruhga emas! "
               "Tasdiqlaganingizdan keyin bot uni guruhga o'zi chiqaradi.\n\n"
               "<b>Yo'l 1 — sehrgar:</b> <code>/new</code> yozing, bot har bir darajani "
               "navbat bilan so'raydi.\n\n"
               "<b>Yo'l 2 — bitta xabar:</b>\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
               "Bular ham ishlaydi:\n"
               "<code>ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80</code>\n"
               "<code>eth long 3200 3400 3550 3100</code>\n"
               "  ↳ kalit so'zsiz: birinchi raqam — kirish, oxirgisi — stop, "
               "o'rtadagilari TP.\n\n"
               "<b>Rasm bilan:</b> darajalar rasm ostidagi <b>izohdan</b> (caption) "
               "o'qiladi — rasmning o'zi guruhga signal bilan birga ketadi.\n\n"
               "✅ Hech narsa tasdiqsiz saqlanmaydi — bot avval o'qiganini ko'rsatadi."),
        "ru": ("📈 <b>Как отправить сигнал</b>\n\n"
               "Сигнал пишется <b>в личный чат бота</b>, а не в группу! "
               "После вашего подтверждения бот сам опубликует его в группе.\n\n"
               "<b>Способ 1 — мастер:</b> напишите <code>/new</code>, бот спросит "
               "каждый уровень по очереди.\n\n"
               "<b>Способ 2 — одним сообщением:</b>\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
               "Это тоже работает:\n"
               "<code>ADAUSDT long вход 0.85 цель 0.92 0.98 стоп 0.80</code>\n"
               "<code>eth long 3200 3400 3550 3100</code>\n"
               "  ↳ без ключевых слов: первое число — вход, последнее — стоп, "
               "остальные — TP.\n\n"
               "<b>С картинкой:</b> уровни читаются из <b>подписи</b> под картинкой, "
               "а сама картинка уходит в группу вместе с сигналом.\n\n"
               "✅ Ничего не сохраняется без подтверждения — бот сначала покажет, "
               "что он понял."),
        "en": ("📈 <b>Sending a signal</b>\n\n"
               "A signal goes into the <b>bot's private chat</b>, not the group. "
               "After you confirm it, the bot posts it to the group itself.\n\n"
               "<b>Way 1 — the wizard:</b> type <code>/new</code> and the bot asks "
               "for each level in turn.\n\n"
               "<b>Way 2 — one message:</b>\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
               "These work too:\n"
               "<code>ADAUSDT long entry 0.85 target 0.92 0.98 stop 0.80</code>\n"
               "<code>eth long 3200 3400 3550 3100</code>\n"
               "  ↳ with no keywords: the first number is the entry, the last one "
               "the stop, the rest are TPs.\n\n"
               "<b>With an image:</b> the levels are read from the <b>caption</b> "
               "under it — the image itself goes to the group with the signal.\n\n"
               "✅ Nothing is saved without confirmation — the bot shows what it "
               "understood first."),
    },
    "help.mode": {
        "uz": ("⏳ <b>Limit va Market farqi</b>\n\n"
               "<b>Standart holat — kutish (limit).</b> Signal darhol ochilmaydi: "
               "narx kirish darajasiga <b>tegguncha kutadi</b>. Bu vaqtda "
               "🕐 belgisi bilan turadi.\n\n"
               "<b>Darhol ochish uchun</b> matnga <code>market</code> yoki "
               "<code>bozor</code> so'zini qo'shing:\n"
               "<code>BTCUSDT LONG market entry 65000 tp 67000 sl 64000</code>\n\n"
               "Sehrgarda esa <b>🎯 Oddiy (darhol)</b> tugmasini tanlaysiz.\n\n"
               "💡 Pozitsiyaga allaqachon kirgan bo'lsangiz — <code>market</code> "
               "yozishni unutmang, aks holda bot narxni kutib turaveradi."),
        "ru": ("⏳ <b>Разница между лимитом и маркетом</b>\n\n"
               "<b>По умолчанию — ожидание (лимит).</b> Сигнал не открывается сразу: "
               "он <b>ждёт</b>, пока цена дойдёт до уровня входа. В это время он "
               "помечен значком 🕐.\n\n"
               "<b>Чтобы открыть сразу</b>, добавьте в текст слово <code>market</code> "
               "или <code>рынок</code>:\n"
               "<code>BTCUSDT LONG market entry 65000 tp 67000 sl 64000</code>\n\n"
               "В мастере для этого есть кнопка <b>🎯 Обычный (сразу)</b>.\n\n"
               "💡 Если вы уже в позиции — не забудьте про <code>market</code>, иначе "
               "бот так и будет ждать цену."),
        "en": ("⏳ <b>Limit vs Market</b>\n\n"
               "<b>The default is waiting (limit).</b> The signal does not open right "
               "away: it <b>waits</b> until the price reaches the entry level. Until "
               "then it is marked 🕐.\n\n"
               "<b>To open immediately</b>, add the word <code>market</code> to the "
               "text:\n"
               "<code>BTCUSDT LONG market entry 65000 tp 67000 sl 64000</code>\n\n"
               "In the wizard, pick <b>🎯 Market (now)</b>.\n\n"
               "💡 If you are already in the position, don't forget "
               "<code>market</code> — otherwise the bot keeps waiting for the price."),
    },
    "help.errors": {
        "uz": ("🔧 <b>Ko'p uchraydigan xatolar</b>\n\n"
               "<b>Bot javob bermayapti?</b>\n"
               "Signalni guruhga yozgan bo'lishingiz mumkin. Signal faqat "
               "<b>shaxsiy chatda</b> qabul qilinadi.\n\n"
               "<b>TP noto'g'ri o'qildi?</b>\n"
               "<code>tp 172 168</code> — bu <b>ikkita</b> TP (172 va 168) deb o'qiladi. "
               "Minglik uchun <code>tp 172168</code> yoki <code>TP1 172 168</code> yozing.\n\n"
               "<b>\"SL entry dan past bo'lishi kerak\"?</b>\n"
               "LONG uchun: stop <b>past</b>, TP <b>yuqori</b>. SHORT uchun teskarisi. "
               "Odatda bu LONG/SHORT adashtirilganini bildiradi.\n\n"
               "<b>Bot guruhga yozmayapti?</b>\n"
               "Botda admin huquqi yo'qligidan. Guruh sozlamalaridan bering."),
        "ru": ("🔧 <b>Частые ошибки</b>\n\n"
               "<b>Бот не отвечает?</b>\n"
               "Возможно, вы написали сигнал в группу. Сигнал принимается только "
               "<b>в личном чате</b>.\n\n"
               "<b>TP прочитан неправильно?</b>\n"
               "<code>tp 172 168</code> читается как <b>два</b> TP (172 и 168). Для "
               "тысяч пишите <code>tp 172168</code> или <code>TP1 172 168</code>.\n\n"
               "<b>«Стоп должен быть ниже входа»?</b>\n"
               "Для LONG: стоп <b>ниже</b>, TP <b>выше</b>. Для SHORT — наоборот. "
               "Обычно это значит, что перепутаны LONG и SHORT.\n\n"
               "<b>Бот не пишет в группу?</b>\n"
               "У него нет прав администратора. Выдайте их в настройках группы."),
        "en": ("🔧 <b>Common errors</b>\n\n"
               "<b>The bot is not answering?</b>\n"
               "You may have written the signal in the group. Signals are only "
               "accepted <b>in the private chat</b>.\n\n"
               "<b>A TP was read wrong?</b>\n"
               "<code>tp 172 168</code> reads as <b>two</b> TPs (172 and 168). For "
               "thousands write <code>tp 172168</code> or <code>TP1 172 168</code>.\n\n"
               "<b>\"The SL must be below the entry\"?</b>\n"
               "For LONG: the stop is <b>below</b> and the TPs <b>above</b>. For SHORT "
               "it is the other way round. Usually this means LONG and SHORT got "
               "mixed up.\n\n"
               "<b>The bot is not posting to the group?</b>\n"
               "It has no admin rights. Grant them in the group settings."),
    },

    # --- Kirish, obuna va workspace tanlash ---
    "acc.personal_other": {
        "uz": "🔒 Bu boshqa foydalanuvchining shaxsiy jurnali.",
        "ru": "🔒 Это личный журнал другого пользователя.",
        "en": "🔒 This is another user's personal journal.",
    },
    "acc.not_subscriber": {
        "uz": ("🔒 Bu ma'lumotlar faqat shu guruh obunachilariga ochiq.\n"
               "Obunani faollashtirgach, bot avtomatik ishlay boshlaydi."),
        "ru": ("🔒 Эти данные доступны только подписчикам этой группы.\n"
               "После активации подписки бот заработает автоматически."),
        "en": ("🔒 This data is only open to subscribers of this group.\n"
               "Once the subscription is active, the bot starts working automatically."),
    },
    "acc.btn_subscribe": {
        "uz": "💳 Obuna bo'lish", "ru": "💳 Оформить подписку", "en": "💳 Subscribe",
    },
    "sub.prompt": {
        "uz": ("👋 Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling, "
               "so'ng <b>“✅ Obuna bo'ldim”</b> tugmasini bosing."),
        "ru": ("👋 Чтобы пользоваться ботом, подпишитесь на канал(ы) ниже, "
               "затем нажмите <b>«✅ Я подписался»</b>."),
        "en": ("👋 To use the bot, subscribe to the channel(s) below, then press "
               "<b>\"✅ I subscribed\"</b>."),
    },
    "sub.btn_check": {
        "uz": "✅ Obuna bo'ldim, tekshirish", "ru": "✅ Я подписался, проверить",
        "en": "✅ I subscribed, check",
    },
    "sub.first": {
        "uz": "Avval kanalga obuna bo'ling", "ru": "Сначала подпишитесь на канал",
        "en": "Subscribe to the channel first",
    },
    "sub.not_yet": {
        "uz": "Hali obuna bo'lmagansiz.", "ru": "Вы ещё не подписались.",
        "en": "You have not subscribed yet.",
    },
    "sub.thanks": {"uz": "Rahmat! ✅", "ru": "Спасибо! ✅", "en": "Thank you! ✅"},
    "sub.ok": {
        "uz": "✅ Obuna tasdiqlandi. Botdan foydalanishingiz mumkin.",
        "ru": "✅ Подписка подтверждена. Можете пользоваться ботом.",
        "en": "✅ Subscription confirmed. You can use the bot now.",
    },
    "ws.personal_name": {
        "uz": "Shaxsiy jurnal", "ru": "Личный журнал", "en": "Personal journal",
    },
    "ws.btn_personal": {
        "uz": "🧑 Shaxsiy jurnal", "ru": "🧑 Личный журнал", "en": "🧑 Personal journal",
    },
    "ws.btn_join": {
        "uz": "➕ Boshqa guruhga a'zo bo'lish", "ru": "➕ Присоединиться к другой группе",
        "en": "➕ Join another group",
    },
    "ws.pick": {
        "uz": "Qaysi joy uchun?", "ru": "Для какого места?", "en": "Which workspace?",
    },
    "ws.picked": {
        "uz": "✅ Tanlandi: {name}", "ru": "✅ Выбрано: {name}", "en": "✅ Selected: {name}",
    },
    "ws.no_groups": {
        "uz": "Hozircha hech qanday guruh ro'yxatdan o'tmagan.",
        "ru": "Пока ни одна группа не зарегистрирована.",
        "en": "No group has been registered yet.",
    },
    "ws.which_group": {
        "uz": "Qaysi guruh a'zosisiz? Tanlang:",
        "ru": "В какой группе вы состоите? Выберите:",
        "en": "Which group are you in? Pick one:",
    },
    "ws.group_not_found": {
        "uz": "Bu guruh topilmadi.", "ru": "Эта группа не найдена.",
        "en": "This group was not found.",
    },
    "ws.not_member": {
        "uz": "🔒 Siz \"{name}\" guruhi a'zosi emassiz (yoki bot tekshira olmadi).",
        "ru": "🔒 Вы не состоите в группе «{name}» (или бот не смог проверить).",
        "en": "🔒 You are not a member of \"{name}\" (or the bot could not check).",
    },
    "ws.joined": {
        "uz": "✅ \"{name}\" ulandi — endi statistikasini ko'ra olasiz.",
        "ru": "✅ «{name}» подключена — теперь вам видна её статистика.",
        "en": "✅ \"{name}\" connected — you can see its stats now.",
    },
    "ws.not_registered": {
        "uz": "Bu guruh hali ro'yxatdan o'tmagan. Guruh admini /setup buyrug'ini yozsin.",
        "ru": "Эта группа ещё не зарегистрирована. Пусть админ группы напишет /setup.",
        "en": "This group is not registered yet. A group admin should type /setup.",
    },

    # --- Onboarding ---
    "onb.welcome": {
        "uz": ("👋 Xush kelibsiz! Botni qanday ishlatmoqchisiz?\n\n"
               "🧑 <b>Shaxsiy jurnal</b> — o'z savdo signallaringizni yozib, "
               "statistikangizni kuzatib borasiz. Faqat sizga ko'rinadi, hech kimga "
               "post bo'lmaydi.\n\n"
               "🏘 <b>Guruh</b> — sizda o'z yopiq Telegram guruhingiz bo'lsa (yoki "
               "allaqachon biror guruhga a'zo bo'lsangiz), shu bot orqali "
               "statistikani ko'rishingiz mumkin."),
        "ru": ("👋 Добро пожаловать! Как вы хотите пользоваться ботом?\n\n"
               "🧑 <b>Личный журнал</b> — записываете свои сигналы и следите за своей "
               "статистикой. Виден только вам, никуда не публикуется.\n\n"
               "🏘 <b>Группа</b> — если у вас есть своя закрытая группа в Telegram "
               "(или вы уже состоите в какой-то), через этого бота можно смотреть "
               "её статистику."),
        "en": ("👋 Welcome! How do you want to use the bot?\n\n"
               "🧑 <b>Personal journal</b> — record your own trade signals and follow "
               "your stats. Visible only to you, nothing is posted anywhere.\n\n"
               "🏘 <b>Group</b> — if you have your own private Telegram group (or are "
               "already a member of one), you can follow its stats through this bot."),
    },
    "onb.btn_personal": {
        "uz": "🧑 Shaxsiy jurnal ochish", "ru": "🧑 Завести личный журнал",
        "en": "🧑 Start a personal journal",
    },
    "onb.btn_group": {
        "uz": "🏘 Menda yopiq guruh bor", "ru": "🏘 У меня есть закрытая группа",
        "en": "🏘 I have a private group",
    },
    "onb.btn_member": {
        "uz": "👥 Men guruh a'zosiman", "ru": "👥 Я участник группы",
        "en": "👥 I am a group member",
    },
    "onb.btn_owner": {
        "uz": "👑 Men guruh egasiman", "ru": "👑 Я владелец группы",
        "en": "👑 I own the group",
    },
    "onb.personal_ok": {
        "uz": "✅ Shaxsiy jurnal ochildi.", "ru": "✅ Личный журнал создан.",
        "en": "✅ Personal journal created.",
    },
    "onb.who": {
        "uz": "🏘 Shu guruh bilan bog'liq siz kimsiz?",
        "ru": "🏘 Кто вы в этой группе?",
        "en": "🏘 Who are you in that group?",
    },
    "onb.owner_steps": {
        "uz": ("👑 Guruhingizni ulash uchun:\n\n"
               "1. {mention} o'z guruhingizga qo'shing.\n"
               "2. Botga guruhda <b>admin</b> huquqini bering (xabar yuborish uchun "
               "kerak).\n"
               "3. Guruh ichida <code>/setup</code> buyrug'ini yozing.\n\n"
               "Shundan so'ng guruhingiz mustaqil workspace sifatida ishlay boshlaydi "
               "va botga shaxsiy yozganingizda avtomatik o'shani boshqarasiz."),
        "ru": ("👑 Чтобы подключить свою группу:\n\n"
               "1. Добавьте {mention} в свою группу.\n"
               "2. Дайте боту права <b>администратора</b> (нужны для отправки "
               "сообщений).\n"
               "3. Напишите в группе команду <code>/setup</code>.\n\n"
               "После этого ваша группа станет отдельным рабочим пространством, и в "
               "личном чате с ботом вы будете управлять именно ею."),
        "en": ("👑 To connect your group:\n\n"
               "1. Add {mention} to your group.\n"
               "2. Give the bot <b>admin</b> rights there (needed to post).\n"
               "3. Type <code>/setup</code> inside the group.\n\n"
               "After that your group becomes its own workspace, and writing to the "
               "bot privately manages exactly that group."),
    },

    # --- Taklif (referal) ---
    "ref.head": {
        "uz": "🎁 Do'stlaringizni taklif qiling!",
        "ru": "🎁 Приглашайте друзей!",
        "en": "🎁 Invite your friends!",
    },
    "ref.code_line": {
        "uz": "Taklif kodingiz: <code>{code}</code>",
        "ru": "Ваш код приглашения: <code>{code}</code>",
        "en": "Your invite code: <code>{code}</code>",
    },
    "ref.link_line": {
        "uz": "Sizning shaxsiy havolangiz:\n{link}",
        "ru": "Ваша личная ссылка:\n{link}",
        "en": "Your personal link:\n{link}",
    },
    "ref.no_link": {
        "uz": "(havola olinmadi, birozdan so'ng qayta urining)",
        "ru": "(ссылку получить не удалось, попробуйте позже)",
        "en": "(the link could not be built, try again shortly)",
    },
    "ref.count": {
        "uz": "Siz orqali botga kelganlar: <b>{n}</b>",
        "ru": "Пришли по вашей ссылке: <b>{n}</b>",
        "en": "Joined through you: <b>{n}</b>",
    },
    "ref.unlock_hint": {
        "uz": ("✨ Yana <b>{left}</b> ta odam taklif qilsangiz, o'zingizga chiroyli "
               "kod tanlay olasiz (masalan <code>WHALES</code>)."),
        "ru": ("✨ Пригласите ещё <b>{left}</b> человек — и сможете выбрать себе "
               "красивый код (например <code>WHALES</code>)."),
        "en": ("✨ Invite <b>{left}</b> more people and you can pick your own "
               "nice code (for example <code>WHALES</code>)."),
    },
    "ref.btn_pick": {
        "uz": "✏️ O'z kodimni tanlash", "ru": "✏️ Выбрать свой код",
        "en": "✏️ Pick my own code",
    },
    "ref.locked": {
        "uz": "Bu imkoniyat hali ochilmagan.", "ru": "Эта возможность пока закрыта.",
        "en": "This is not unlocked yet.",
    },
    "ref.ask_code": {
        "uz": ("✏️ Yangi kodingizni yozing.\n\n"
               "• {mn}–{mx} ta belgi\n"
               "• Lotin harflari va raqamlar (masalan <code>WHALES</code>)\n"
               "• Faqat raqamdan iborat bo'lmasin\n\n"
               "⚠️ Kodni o'zgartirsangiz, ESKI kod bilan tarqatilgan havolalar "
               "ishlamay qoladi.\n\nBekor qilish: /bekor"),
        "ru": ("✏️ Напишите свой новый код.\n\n"
               "• от {mn} до {mx} символов\n"
               "• латинские буквы и цифры (например <code>WHALES</code>)\n"
               "• не только из цифр\n\n"
               "⚠️ Если сменить код, СТАРЫЕ разосланные ссылки перестанут "
               "работать.\n\nОтмена: /bekor"),
        "en": ("✏️ Send your new code.\n\n"
               "• {mn}–{mx} characters\n"
               "• Latin letters and digits (for example <code>WHALES</code>)\n"
               "• not digits only\n\n"
               "⚠️ If you change the code, links already shared with the OLD one "
               "stop working.\n\nCancel: /bekor"),
    },
    "ref.err_charset": {
        "uz": "Faqat lotin harflari va raqamlar bo'lishi mumkin (bo'sh joysiz).",
        "ru": "Только латинские буквы и цифры (без пробелов).",
        "en": "Latin letters and digits only (no spaces).",
    },
    "ref.err_len": {
        "uz": "Uzunligi {mn} dan {mx} tagacha bo'lsin.",
        "ru": "Длина должна быть от {mn} до {mx} символов.",
        "en": "The length must be between {mn} and {mx}.",
    },
    "ref.err_digits": {
        "uz": "Faqat raqamdan iborat bo'lmasin — kamida bitta harf qo'shing.",
        "ru": "Код не может состоять только из цифр — добавьте хотя бы одну букву.",
        "en": "It cannot be digits only — add at least one letter.",
    },
    "ref.err_banned": {
        "uz": "Bu so'z band. Boshqasini tanlang.",
        "ru": "Это слово занято. Выберите другое.",
        "en": "That word is reserved. Pick another one.",
    },
    "ref.retry": {
        "uz": "❌ {err}\n\nQayta yozing yoki /bekor.",
        "ru": "❌ {err}\n\nНапишите ещё раз или /bekor.",
        "en": "❌ {err}\n\nSend it again or /bekor.",
    },
    "ref.save_failed": {
        "uz": "Saqlab bo'lmadi, birozdan so'ng qayta urining.",
        "ru": "Не удалось сохранить, попробуйте чуть позже.",
        "en": "Could not save it, try again shortly.",
    },
    "ref.taken": {
        "uz": "❌ Bu kod band. Boshqasini yozing yoki /bekor.",
        "ru": "❌ Этот код занят. Напишите другой или /bekor.",
        "en": "❌ That code is taken. Send another one or /bekor.",
    },
    "ref.changed": {
        "uz": "✅ Kodingiz o'zgartirildi: <code>{code}</code>\n\nYangi havolangiz:\n<code>{link}</code>",
        "ru": "✅ Код изменён: <code>{code}</code>\n\nВаша новая ссылка:\n<code>{link}</code>",
        "en": "✅ Your code is now: <code>{code}</code>\n\nYour new link:\n<code>{link}</code>",
    },
    "cmd.cancelled": {
        "uz": "❌ Bekor qilindi.", "ru": "❌ Отменено.", "en": "❌ Cancelled.",
    },

    # --- /setup (guruhni ro'yxatdan o'tkazish) ---
    "su.group_only": {
        "uz": "Bu buyruq faqat guruh ichida ishlaydi.",
        "ru": "Эта команда работает только внутри группы.",
        "en": "This command only works inside a group.",
    },
    "su.check_failed": {
        "uz": "Guruh a'zoligini tekshirib bo'lmadi.",
        "ru": "Не удалось проверить членство в группе.",
        "en": "Could not check the group membership.",
    },
    "su.admin_only": {
        "uz": "Faqat guruh admini /setup qila oladi.",
        "ru": "Команду /setup может выполнить только админ группы.",
        "en": "Only a group admin can run /setup.",
    },
    "su.already": {
        "uz": "Bu guruh allaqachon ro'yxatdan o'tgan: {name}",
        "ru": "Эта группа уже зарегистрирована: {name}",
        "en": "This group is already registered: {name}",
    },
    "su.have_other": {
        "uz": ("Sizda allaqachon boshqa guruh bor: \"{name}\". "
               "Har bir admin faqat bitta guruhni boshqara oladi."),
        "ru": ("У вас уже есть другая группа: «{name}». "
               "Один админ может вести только одну группу."),
        "en": ("You already have another group: \"{name}\". "
               "Each admin can run only one group."),
    },
    "su.done": {
        "uz": ("✅ \"{name}\" workspace sifatida ro'yxatdan o'tdi!\n"
               "Endi botga shaxsiy xabar yozib (/start) signal kirita olasiz."),
        "ru": ("✅ «{name}» зарегистрирована как рабочее пространство!\n"
               "Теперь можно писать сигналы боту в личном чате (/start)."),
        "en": ("✅ \"{name}\" is registered as a workspace!\n"
               "You can now send signals to the bot in private (/start)."),
    },
    "su.group_ws_only": {
        "uz": "Bu buyruq faqat guruh workspace uchun ishlaydi.",
        "ru": "Эта команда работает только для группового рабочего пространства.",
        "en": "This command only works for a group workspace.",
    },
    "su.not_registered": {
        "uz": "Bu guruh hali ro'yxatdan o'tmagan — /setup yozing.",
        "ru": "Эта группа ещё не зарегистрирована — напишите /setup.",
        "en": "This group is not registered yet — type /setup.",
    },
    "su.group_admin_only": {
        "uz": "Faqat guruh admini o'zgartira oladi.",
        "ru": "Изменить может только админ группы.",
        "en": "Only a group admin can change this.",
    },

    # --- Ochiq sahifa (/sahifa) ---
    "web.off": {
        "uz": ("🌐 Ochiq sahifa hali yoqilmagan.\n\n"
               "Yoqish uchun: <code>/public on</code> yozing — so'rov moderatorga "
               "boradi. Tasdiqlangach guruhingiz uchun jonli havola paydo bo'ladi: "
               "unda statistika, equity grafigi va savdolar tarixi ko'rinadi."),
        "ru": ("🌐 Публичная страница ещё не включена.\n\n"
               "Чтобы включить, напишите <code>/public on</code> — запрос уйдёт "
               "модератору. После одобрения у группы появится живая ссылка со "
               "статистикой, графиком эквити и историей сделок."),
        "en": ("🌐 The public page is not enabled yet.\n\n"
               "To enable it, type <code>/public on</code> — the request goes to a "
               "moderator. Once approved your group gets a live link with the stats, "
               "the equity chart and the trade history."),
    },
    "web.link": {
        "uz": ("🌐 <b>{name}</b> — ochiq natijalar sahifasi:\n\n<code>{url}</code>\n\n"
               "Bu havolani guruhga pin qilib qo'ysangiz yoki reklamada ulashsangiz "
               "bo'ladi. Sahifa bazadan jonli o'qiladi — har yangi natija o'zi "
               "qo'shiladi, qo'lda yangilash shart emas."),
        "ru": ("🌐 <b>{name}</b> — публичная страница результатов:\n\n"
               "<code>{url}</code>\n\n"
               "Ссылку можно закрепить в группе или использовать в рекламе. Страница "
               "читает данные вживую — каждый новый результат добавляется сам, "
               "обновлять вручную не нужно."),
        "en": ("🌐 <b>{name}</b> — public results page:\n\n<code>{url}</code>\n\n"
               "You can pin this link in the group or share it in ads. The page reads "
               "live from the database — every new result is added by itself, no "
               "manual refresh needed."),
    },
    "web.btn_open": {
        "uz": "🌐 Sahifani ochish", "ru": "🌐 Открыть страницу", "en": "🌐 Open the page",
    },

    # --- /public (reytingda ko'rinish) ---
    "pub.state_off": {"uz": "o'chirilgan 🔒", "ru": "выключено 🔒", "en": "off 🔒"},
    "pub.state_on": {"uz": "yoqilgan ✅", "ru": "включено ✅", "en": "on ✅"},
    "pub.state_wait": {
        "uz": "tasdiqlanishi kutilmoqda ⏳", "ru": "ожидает одобрения ⏳",
        "en": "waiting for approval ⏳",
    },
    "pub.current": {
        "uz": ("\"{name}\" guruhingizning <code>/top</code> reytingida ko'rinishi: "
               "<b>{state}</b>\n\nYoqish: <code>/public on</code>\n"
               "O'chirish: <code>/public off</code>"),
        "ru": ("Показ группы «{name}» в рейтинге <code>/top</code>: <b>{state}</b>\n\n"
               "Включить: <code>/public on</code>\nВыключить: <code>/public off</code>"),
        "en": ("Your group \"{name}\" in the <code>/top</code> ranking: "
               "<b>{state}</b>\n\nEnable: <code>/public on</code>\n"
               "Disable: <code>/public off</code>"),
    },
    "pub.usage": {
        "uz": "Foydalanish: /public on  yoki  /public off",
        "ru": "Использование: /public on  или  /public off",
        "en": "Usage: /public on  or  /public off",
    },
    "pub.off_done": {
        "uz": "🔒 Guruhingiz reytingdan olib tashlandi.",
        "ru": "🔒 Группа убрана из рейтинга.",
        "en": "🔒 Your group was removed from the ranking.",
    },
    "pub.on_done": {
        "uz": "✅ Guruhingiz endi /top reytingida ko'rinadi.",
        "ru": "✅ Ваша группа теперь видна в рейтинге /top.",
        "en": "✅ Your group now shows in the /top ranking.",
    },
    "pub.requested": {
        "uz": ("⏳ So'rov yuborildi. Guruhingiz moderator tasdig'idan keyin "
               "<code>/top</code> reytingida ko'rinadi."),
        "ru": ("⏳ Запрос отправлен. Группа появится в рейтинге <code>/top</code> "
               "после одобрения модератором."),
        "en": ("⏳ Request sent. Your group appears in the <code>/top</code> ranking "
               "once a moderator approves it."),
    },
    "pub.approved_dm": {
        "uz": "✅ Guruhingiz <code>/top</code> reytingida ko'rina boshladi.",
        "ru": "✅ Ваша группа появилась в рейтинге <code>/top</code>.",
        "en": "✅ Your group is now visible in the <code>/top</code> ranking.",
    },
    "pub.rejected_dm": {
        "uz": ("🚫 Guruhingiz <code>/top</code> reytingiga qo'shilmadi. "
               "Guruh nomi yoki havolasini to'g'rilab, qayta urinib ko'ring."),
        "ru": ("🚫 Группа не добавлена в рейтинг <code>/top</code>. Исправьте название "
               "или ссылку группы и попробуйте снова."),
        "en": ("🚫 Your group was not added to the <code>/top</code> ranking. Fix the "
               "group name or link and try again."),
    },
    "top.empty": {
        "uz": ("Hali hech qanday ochiq guruh reytingda yo'q.\n\n"
               "Guruh admini bo'lsangiz, guruhingizni ko'rsatish uchun "
               "<code>/public on</code> yozing."),
        "ru": ("В рейтинге пока нет ни одной публичной группы.\n\n"
               "Если вы админ группы, напишите <code>/public on</code>, чтобы "
               "показать её."),
        "en": ("No public group is in the ranking yet.\n\n"
               "If you are a group admin, type <code>/public on</code> to show yours."),
    },

    # --- /havola (guruh taklif havolasi) ---
    "inv.current": {
        "uz": ("\"{name}\" guruhingizning taklif havolasi: <b>{link}</b>\n\n"
               "<code>/top</code> reytingida guruh nomi shu havolaga link qilinadi.\n\n"
               "Belgilash: <code>/havola https://t.me/+abc123</code>\n"
               "O'chirish: <code>/havola off</code>"),
        "ru": ("Пригласительная ссылка группы «{name}»: <b>{link}</b>\n\n"
               "В рейтинге <code>/top</code> название группы ведёт на эту ссылку.\n\n"
               "Задать: <code>/havola https://t.me/+abc123</code>\n"
               "Убрать: <code>/havola off</code>"),
        "en": ("The invite link of \"{name}\": <b>{link}</b>\n\n"
               "In the <code>/top</code> ranking the group name links here.\n\n"
               "Set it: <code>/havola https://t.me/+abc123</code>\n"
               "Remove it: <code>/havola off</code>"),
    },
    "inv.off_done": {
        "uz": "🔒 Taklif havolasi o'chirildi.", "ru": "🔒 Пригласительная ссылка убрана.",
        "en": "🔒 The invite link was removed.",
    },

    # --- /hisobot (kunlik yakun sozlamasi) ---
    "dg.owner_only": {
        "uz": "Bu sozlamani faqat egasi o'zgartira oladi.",
        "ru": "Эту настройку может менять только владелец.",
        "en": "Only the owner can change this setting.",
    },
    "dg.state_on": {
        "uz": "yoqilgan, har kuni <b>{h:02d}:00</b>",
        "ru": "включён, каждый день в <b>{h:02d}:00</b>",
        "en": "on, every day at <b>{h:02d}:00</b>",
    },
    "dg.state_off": {"uz": "o'chirilgan", "ru": "выключен", "en": "off"},
    "dg.where_group": {"uz": "guruhga", "ru": "в группу", "en": "to the group"},
    "dg.where_here": {"uz": "shu yerga", "ru": "сюда", "en": "here"},
    "dg.settings": {
        "uz": ("📊 Kunlik hisobot: {state}\n\n"
               "Yoqish: <code>/hisobot 21</code> (mahalliy vaqt, 0–23)\n"
               "O'chirish: <code>/hisobot off</code>\n\n"
               "Belgilangan soatda {where} kun yakuni chiqadi: nechta signal "
               "yopildi, winrate, umumiy natija, eng yaxshi juftlik."),
        "ru": ("📊 Ежедневный отчёт: {state}\n\n"
               "Включить: <code>/hisobot 21</code> (местное время, 0–23)\n"
               "Выключить: <code>/hisobot off</code>\n\n"
               "В указанный час {where} придут итоги дня: сколько сигналов "
               "закрыто, винрейт, общий результат, лучшая пара."),
        "en": ("📊 Daily report: {state}\n\n"
               "Enable: <code>/hisobot 21</code> (local time, 0–23)\n"
               "Disable: <code>/hisobot off</code>\n\n"
               "At that hour the wrap-up goes {where}: how many signals closed, "
               "the win rate, the overall result and the best pair."),
    },
    "dg.turned_off": {
        "uz": "📊 Kunlik hisobot o'chirildi.", "ru": "📊 Ежедневный отчёт выключен.",
        "en": "📊 The daily report is off.",
    },
    "dg.bad_hour": {
        "uz": "Soat 0 dan 23 gacha bo'lishi kerak. Masalan: /hisobot 21",
        "ru": "Час должен быть от 0 до 23. Например: /hisobot 21",
        "en": "The hour must be between 0 and 23. For example: /hisobot 21",
    },
    "dg.turned_on": {
        "uz": ("✅ Kunlik hisobot yoqildi — har kuni <b>{h:02d}:00</b> da ({tz}) "
               "{where} chiqadi.\n\n"
               "<i>Bugun yopilgan signal bo'lmasa post yuborilmaydi.</i>"),
        "ru": ("✅ Ежедневный отчёт включён — каждый день в <b>{h:02d}:00</b> ({tz}) "
               "{where}.\n\n"
               "<i>Если за день не закрыт ни один сигнал, пост не отправляется.</i>"),
        "en": ("✅ Daily report enabled — every day at <b>{h:02d}:00</b> ({tz}) it goes "
               "{where}.\n\n"
               "<i>If no signal closed that day, nothing is posted.</i>"),
    },

    # --- Pozitsiya hajmi (alloc) ---
    "al.no_deposit": {
        "uz": "Depozit belgilanmagan.", "ru": "Депозит не задан.",
        "en": "No deposit is set.",
    },
    "al.set": {
        "uz": ("✅ #{sid} {sym} — hajm: <b>{amt:,.2f}</b>\n"
               "Stop tegsa yo'qotish: <b>{risk:,.2f}</b> (depozitning {pct:.2f}%)"),
        "ru": ("✅ #{sid} {sym} — объём: <b>{amt:,.2f}</b>\n"
               "Потеря при стопе: <b>{risk:,.2f}</b> ({pct:.2f}% депозита)"),
        "en": ("✅ #{sid} {sym} — size: <b>{amt:,.2f}</b>\n"
               "Loss if the stop hits: <b>{risk:,.2f}</b> ({pct:.2f}% of the deposit)"),
    },
    "al.skipped": {
        "uz": "⏭ O'tkazib yuborildi.", "ru": "⏭ Пропущено.", "en": "⏭ Skipped.",
    },
    "al.bad_amount": {
        "uz": "Noto'g'ri summa. Qayta kiriting yoki ⏭ tugmasini bosing.",
        "ru": "Неверная сумма. Введите снова или нажмите ⏭.",
        "en": "Invalid amount. Enter it again or press ⏭.",
    },
    "al.saved": {
        "uz": "✅ Belgilandi: <b>{amt:,.2f}</b>",
        "ru": "✅ Записано: <b>{amt:,.2f}</b>",
        "en": "✅ Saved: <b>{amt:,.2f}</b>",
    },

    # --- Jurnalga kiritish (post ostidagi tugmadan) ---
    "jr.not_found": {
        "uz": "❌ <code>{sym}</code> topilmadi. /new yozib qo'lda kiriting.",
        "ru": "❌ <code>{sym}</code> не найден. Введите вручную через /new.",
        "en": "❌ <code>{sym}</code> not found. Use /new to enter it manually.",
    },
    "jr.ask_levels": {
        "uz": ("✅ <b>{sym}</b> — endi yo'nalish va narxlarni yozing (tiker yozish "
               "shart emas), masalan:\n\n"
               "<code>LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
               "Yoki qisqa: <code>long 65000 67000 68500 64000</code>\n\n"
               "Bekor qilish uchun /bekor yozing."),
        "ru": ("✅ <b>{sym}</b> — теперь напишите направление и цены (тикер писать не "
               "нужно), например:\n\n"
               "<code>LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
               "Или коротко: <code>long 65000 67000 68500 64000</code>\n\n"
               "Для отмены напишите /bekor."),
        "en": ("✅ <b>{sym}</b> — now send the direction and the prices (no ticker "
               "needed), for example:\n\n"
               "<code>LONG entry 65000 tp 67000 68500 sl 64000</code>\n\n"
               "Or short: <code>long 65000 67000 68500 64000</code>\n\n"
               "Send /bekor to cancel."),
    },
    "jr.unreadable": {
        "uz": ("O'qiy olmadim. Namuna: <code>LONG entry 65000 tp 67000 68500 "
               "sl 64000</code>\n\nYoki /bekor yozing."),
        "ru": ("Не смог прочитать. Пример: <code>LONG entry 65000 tp 67000 68500 "
               "sl 64000</code>\n\nИли напишите /bekor."),
        "en": ("Could not read that. Example: <code>LONG entry 65000 tp 67000 68500 "
               "sl 64000</code>\n\nOr send /bekor."),
    },
    "ed.unreadable": {
        "uz": "O'qiy olmadim. Yana urinib ko'ring yoki /bekor yozing.",
        "ru": "Не смог прочитать. Попробуйте ещё раз или напишите /bekor.",
        "en": "Could not read that. Try again or send /bekor.",
    },

    # --- Rasm ostidagi signal ---
    "ph.need_caption": {
        "uz": ("Rasm ostiga signalni yozib yuboring, masalan:\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>"),
        "ru": ("Напишите сигнал в подписи к картинке, например:\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>"),
        "en": ("Put the signal in the image caption, for example:\n"
               "<code>BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000</code>"),
    },

    # --- Umumiy ---
    "cmd.cancel_usage": {
        "uz": "Foydalanish: /cancel 12", "ru": "Использование: /cancel 12",
        "en": "Usage: /cancel 12",
    },
    "cmd.cancel_done": {
        "uz": "✅ Bekor qilindi.", "ru": "✅ Отменено.", "en": "✅ Cancelled.",
    },
    "cmd.cancel_gone": {
        "uz": "Topilmadi yoki allaqachon yopilgan.",
        "ru": "Не найдено или уже закрыто.",
        "en": "Not found, or already closed.",
    },
    "err.generic": {
        "uz": ("⚠️ Xatolik yuz berdi (masalan, narx serveriga vaqtincha ulanib "
               "bo'lmadi). Birozdan so'ng qayta urinib ko'ring."),
        "ru": ("⚠️ Произошла ошибка (например, временно нет связи с сервером цен). "
               "Попробуйте чуть позже."),
        "en": ("⚠️ Something went wrong (for example the price server was briefly "
               "unreachable). Please try again shortly."),
    },

    # --- Bosqich (milestone) va noaniq sham (guruhga/egasiga) ---
    "ms.step": {
        "uz": "{mark} <b>#{sid} {sym}</b> — joriy natija: <b>{pnl:+.2f}%</b> ({band:+d}% bosqichi)",
        "ru": "{mark} <b>#{sid} {sym}</b> — текущий результат: <b>{pnl:+.2f}%</b> (рубеж {band:+d}%)",
        "en": "{mark} <b>#{sid} {sym}</b> — running result: <b>{pnl:+.2f}%</b> ({band:+d}% step)",
    },
    "ev.ambiguous": {
        "uz": ("⚠️ #{sid} — TP va SL bitta 1m shamda tegdi. Konservativ hisob "
               "ishlatildi (SL). Qo'lda tekshiring."),
        "ru": ("⚠️ #{sid} — TP и SL задеты в одной 1m свече. Взят консервативный "
               "вариант (SL). Проверьте вручную."),
        "en": ("⚠️ #{sid} — TP and SL were both hit in the same 1m candle. The "
               "conservative result (SL) was used. Please check manually."),
    },

    "al.saved_dep": {
        "uz": "✅ Belgilandi: <b>{amt:,.2f}</b> (depozit: {dep:,.2f})",
        "ru": "✅ Записано: <b>{amt:,.2f}</b> (депозит: {dep:,.2f})",
        "en": "✅ Saved: <b>{amt:,.2f}</b> (deposit: {dep:,.2f})",
    },
    "top.footer": {
        "uz": ("Guruhingizni shu reytingda ko'rsatish uchun admin "
               "<code>/public on</code> yozsin.\nGuruh nomini bosilganda o'z "
               "guruhingizga yo'naltirish uchun: <code>/havola &lt;link&gt;</code>"),
        "ru": ("Чтобы группа попала в этот рейтинг, админ должен написать "
               "<code>/public on</code>.\nЧтобы клик по названию вёл в вашу "
               "группу: <code>/havola &lt;link&gt;</code>"),
        "en": ("To show your group in this ranking, its admin should type "
               "<code>/public on</code>.\nTo make the group name link to your "
               "group: <code>/havola &lt;link&gt;</code>"),
    },
    "top.trades": {
        "uz": "{n} savdo", "ru": "{n} сделок", "en": "{n} trades",
    },
    "top.head": {
        "uz": "🏆 <b>Eng yaxshi guruhlar — {month} {y}</b>",
        "ru": "🏆 <b>Лучшие группы — {month} {y}</b>",
        "en": "🏆 <b>Top groups — {month} {y}</b>",
    },

    # --- Ochiq veb sahifa (web.py) ---
    "w.index_title": {
        "uz": "Ochiq natijalar — Trade Controller",
        "ru": "Открытые результаты — Trade Controller",
        "en": "Public results — Trade Controller",
    },
    "w.index_h1": {
        "uz": "Ochiq natijalar", "ru": "Открытые результаты", "en": "Public results",
    },
    "w.index_sub": {
        "uz": ("Bu guruhlar o'z savdo statistikasini ommaga ochgan. Har bir raqam "
               "bazadan jonli o'qiladi — signal kiritilganda yoziladi, bozor TP yoki "
               "stopga tekkanda avtomatik yopiladi. Qo'lda tahrirlab bo'lmaydi."),
        "ru": ("Эти группы открыли свою торговую статистику публично. Каждое число "
               "читается из базы вживую — записывается при вводе сигнала и "
               "закрывается автоматически, когда рынок доходит до TP или стопа. "
               "Вручную это не изменить."),
        "en": ("These groups have made their trading stats public. Every number is "
               "read live from the database — written when a signal is entered and "
               "closed automatically when the market hits a TP or the stop. It "
               "cannot be edited by hand."),
    },
    "w.index_top": {
        "uz": "Top daromad beruvchi guruhlar", "ru": "Самые прибыльные группы",
        "en": "Top performing groups",
    },
    "w.index_empty": {
        "uz": "Hozircha ochiq guruh yo'q.", "ru": "Пока нет ни одной публичной группы.",
        "en": "No public group yet.",
    },
    "w.index_note": {
        "uz": ("Reyting joriy umumiy natija bo'yicha tartiblangan. O'tmishdagi "
               "natija kelajakni kafolatlamaydi."),
        "ru": ("Рейтинг отсортирован по текущему общему результату. Прошлые "
               "результаты не гарантируют будущих."),
        "en": ("The ranking is sorted by the current overall result. Past results "
               "do not guarantee future ones."),
    },
    "w.signal_word": {"uz": "signal", "ru": "сигналов", "en": "signals"},
    "w.winrate_word": {"uz": "winrate", "ru": "винрейт", "en": "win rate"},
    "w.open_chip": {
        "uz": "{n} ta ochiq", "ru": "{n} открытых", "en": "{n} open",
    },
    "w.more": {"uz": "Batafsil →", "ru": "Подробнее →", "en": "Details →"},
    "w.cta_h3": {
        "uz": "O'z guruhingizni shu yerda ko'rmoqchimisiz?",
        "ru": "Хотите видеть здесь свою группу?",
        "en": "Want to see your own group here?",
    },
    "w.cta_p": {
        "uz": ("Bot signallaringizni avtomatik kuzatadi va statistikani o'zi yig'adi. "
               "Sahifani ochish uchun uch qadam:"),
        "ru": ("Бот сам отслеживает ваши сигналы и собирает статистику. Чтобы "
               "открыть страницу — три шага:"),
        "en": ("The bot tracks your signals automatically and collects the stats "
               "itself. Three steps to open your page:"),
    },
    "w.cta_1": {
        "uz": ("Botni guruhingizga qo'shib, admin qiling va guruhda "
               "<code>/setup</code> yozing"),
        "ru": ("Добавьте бота в группу, дайте права админа и напишите в группе "
               "<code>/setup</code>"),
        "en": ("Add the bot to your group, make it an admin and type "
               "<code>/setup</code> in the group"),
    },
    "w.cta_2": {
        "uz": "Signallaringizni bot orqali kiriting — u qolganini o'zi bajaradi",
        "ru": "Вводите сигналы через бота — остальное он сделает сам",
        "en": "Enter your signals through the bot — it does the rest itself",
    },
    "w.cta_3": {
        "uz": ("Tayyor bo'lgach <code>/public on</code> yozing; moderator tasdiqlagach "
               "guruhingiz shu ro'yxatda paydo bo'ladi"),
        "ru": ("Когда будете готовы, напишите <code>/public on</code>; после одобрения "
               "модератором группа появится в этом списке"),
        "en": ("When ready, type <code>/public on</code>; once a moderator approves "
               "it your group appears in this list"),
    },
    "w.cta_btn": {
        "uz": "Botni ochish", "ru": "Открыть бота", "en": "Open the bot",
    },
    "w.tile_closed": {
        "uz": "Yopilgan signallar", "ru": "Закрытых сигналов", "en": "Closed signals",
    },
    "w.tile_winrate": {"uz": "Winrate", "ru": "Винрейт", "en": "Win rate"},
    "w.tile_net_dep": {
        "uz": "Jami natija (depozitga nisbatan)", "ru": "Общий результат (к депозиту)",
        "en": "Total result (vs deposit)",
    },
    "w.tile_net": {
        "uz": "Jami natija", "ru": "Общий результат", "en": "Total result",
    },
    "w.tile_avg_r": {
        "uz": "O'rtacha R", "ru": "Средний R", "en": "Average R",
    },
    "w.not_public": {
        "uz": "Bunday sahifa yo'q yoki u ochiq emas.",
        "ru": "Такой страницы нет или она не публичная.",
        "en": "No such page, or it is not public.",
    },
    "w.group_title": {
        "uz": "{name} — natijalar", "ru": "{name} — результаты", "en": "{name} — results",
    },
    "w.back_all": {
        "uz": "← Barcha guruhlar", "ru": "← Все группы", "en": "← All groups",
    },
    "w.join_btn": {
        "uz": "Guruhga qo'shilish →", "ru": "Вступить в группу →", "en": "Join the group →",
    },
    "w.equity_h2": {
        "uz": "Balans o'zgarishi", "ru": "Изменение баланса", "en": "Balance over time",
    },
    "w.monthly_h2": {
        "uz": "Oylik natijalar", "ru": "Результаты по месяцам", "en": "Monthly results",
    },
    "w.col_month": {"uz": "Oy", "ru": "Месяц", "en": "Month"},
    "w.col_trades": {"uz": "Savdo", "ru": "Сделки", "en": "Trades"},
    "w.col_winrate": {"uz": "Winrate", "ru": "Винрейт", "en": "Win rate"},
    "w.col_result": {"uz": "Natija", "ru": "Результат", "en": "Result"},
    "w.open_h2": {
        "uz": "Hozir ochiq", "ru": "Открыто сейчас", "en": "Open right now",
    },
    "w.position_n": {
        "uz": "Pozitsiya {i}", "ru": "Позиция {i}", "en": "Position {i}",
    },
    "w.since": {
        "uz": "{d} dan beri", "ru": "с {d}", "en": "since {d}",
    },
    "w.open_note": {
        "uz": ("Juftlik nomi ko'rsatilmaydi — ochiq savdo guruh a'zolari uchun. "
               "Foiz joriy bozor narxidan hisoblanadi."),
        "ru": ("Название пары не показывается — открытая сделка для участников "
               "группы. Процент считается по текущей рыночной цене."),
        "en": ("The pair is not shown — an open trade belongs to the group members. "
               "The percentage is computed from the current market price."),
    },
    "w.recent_h2": {
        "uz": "Oxirgi savdolar", "ru": "Последние сделки", "en": "Recent trades",
    },
    "w.no_closed": {
        "uz": "Hali yopilgan signal yo'q.", "ru": "Закрытых сигналов пока нет.",
        "en": "No closed signals yet.",
    },
    "w.footer_live": {
        "uz": "Ma'lumot bazadan jonli o'qiladi",
        "ru": "Данные читаются из базы вживую",
        "en": "The data is read live from the database",
    },

    # --- Admin panel (faqat super-adminlar ko'radi) ---
    "adm.home": {
        "uz": "🛠 <b>Admin panel</b>", "ru": "🛠 <b>Админ-панель</b>",
        "en": "🛠 <b>Admin panel</b>",
    },
    "adm.back": {
        "uz": "◀️ Admin panel", "ru": "◀️ Админ-панель", "en": "◀️ Admin panel",
    },
    "adm.btn_stats": {"uz": "📊 Statistika", "ru": "📊 Статистика", "en": "📊 Stats"},
    "adm.btn_refs": {"uz": "🎁 Referrallar", "ru": "🎁 Рефералы", "en": "🎁 Referrals"},
    "adm.btn_groups": {"uz": "👥 Guruhlar", "ru": "👥 Группы", "en": "👥 Groups"},
    "adm.btn_users": {
        "uz": "🙍 Foydalanuvchilar", "ru": "🙍 Пользователи", "en": "🙍 Users",
    },
    "adm.btn_channels": {
        "uz": "📢 Majburiy obuna", "ru": "📢 Обязательная подписка",
        "en": "📢 Required subscription",
    },
    "adm.btn_pending": {
        "uz": "🛡 Tasdiqlar", "ru": "🛡 Заявки", "en": "🛡 Approvals",
    },
    "adm.btn_hashtags": {
        "uz": "📰 MarketTwits hashtaglar", "ru": "📰 Хэштеги MarketTwits",
        "en": "📰 MarketTwits hashtags",
    },
    "adm.btn_broadcast": {
        "uz": "📣 Broadcast", "ru": "📣 Рассылка", "en": "📣 Broadcast",
    },
    "adm.btn_pdf_groups": {
        "uz": "📄 Guruhlar PDF", "ru": "📄 PDF по группам", "en": "📄 Groups PDF",
    },
    "adm.btn_pdf_users": {
        "uz": "📄 Userlar PDF", "ru": "📄 PDF по юзерам", "en": "📄 Users PDF",
    },
    "adm.not_found": {"uz": "Topilmadi.", "ru": "Не найдено.", "en": "Not found."},

    # guruh holati
    "adm.h_no_group": {
        "uz": "guruh biriktirilmagan", "ru": "группа не привязана",
        "en": "no group attached",
    },
    "adm.h_unreachable": {
        "uz": "bog'lanib bo'lmadi ({err})", "ru": "не удалось связаться ({err})",
        "en": "could not reach it ({err})",
    },
    "adm.h_kicked": {
        "uz": "bot guruhdan chiqarilgan", "ru": "бот удалён из группы",
        "en": "the bot was removed from the group",
    },
    "adm.h_not_admin": {
        "uz": "bot admin emas — post/reply ishlamaydi",
        "ru": "бот не админ — посты и ответы не работают",
        "en": "the bot is not an admin — posting and replies do not work",
    },
    "adm.h_ok_n": {
        "uz": "admin • {n} a'zo", "ru": "админ • {n} участн.", "en": "admin • {n} members",
    },
    "adm.h_ok": {"uz": "admin", "ru": "админ", "en": "admin"},

    # guruhlar ro'yxati / kartasi
    "adm.groups_none": {
        "uz": "👥 Hali birorta guruh ulanmagan.", "ru": "👥 Пока не подключена ни одна группа.",
        "en": "👥 No group is connected yet.",
    },
    "adm.groups_head": {
        "uz": "👥 <b>Ulangan guruhlar</b>", "ru": "👥 <b>Подключённые группы</b>",
        "en": "👥 <b>Connected groups</b>",
    },
    "adm.groups_row": {
        "uz": "{n_sig} signal, {n_view} kuzatuvchi",
        "ru": "{n_sig} сигналов, {n_view} наблюдателей",
        "en": "{n_sig} signals, {n_view} watchers",
    },
    "adm.groups_legend": {
        "uz": "✅ ishlayapti · ⚠️ admin emas · 🚫 chiqarilgan · 📦 arxivlangan",
        "ru": "✅ работает · ⚠️ не админ · 🚫 удалён · 📦 в архиве",
        "en": "✅ working · ⚠️ not admin · 🚫 removed · 📦 archived",
    },
    "adm.pub_ranked": {
        "uz": "✅ reytingda", "ru": "✅ в рейтинге", "en": "✅ in the ranking",
    },
    "adm.pub_waiting": {
        "uz": "⏳ tasdiq kutmoqda", "ru": "⏳ ждёт одобрения", "en": "⏳ awaiting approval",
    },
    "adm.pub_hidden": {"uz": "🔒 yashirin", "ru": "🔒 скрыта", "en": "🔒 hidden"},
    "adm.card_state": {"uz": "Holat", "ru": "Состояние", "en": "State"},
    "adm.card_owner": {"uz": "Egasi", "ru": "Владелец", "en": "Owner"},
    "adm.card_signals": {"uz": "Signallar", "ru": "Сигналов", "en": "Signals"},
    "adm.card_closed_n": {"uz": "yopilgan {n}", "ru": "закрыто {n}", "en": "{n} closed"},
    "adm.card_viewers": {"uz": "Kuzatuvchilar", "ru": "Наблюдатели", "en": "Watchers"},
    "adm.card_deposit": {"uz": "Depozit", "ru": "Депозит", "en": "Deposit"},
    "adm.card_ranking": {"uz": "Reyting", "ru": "Рейтинг", "en": "Ranking"},
    "adm.card_created": {"uz": "Ochilgan", "ru": "Создана", "en": "Created"},
    "adm.card_archived": {
        "uz": "📦 <b>Arxivlangan</b> — reytingda va tanlovda ko'rinmaydi.",
        "ru": "📦 <b>В архиве</b> — не видна в рейтинге и в выборе.",
        "en": "📦 <b>Archived</b> — hidden from the ranking and the switcher.",
    },
    "adm.btn_unarchive": {
        "uz": "♻️ Arxivdan chiqarish", "ru": "♻️ Вернуть из архива",
        "en": "♻️ Unarchive",
    },
    "adm.btn_archive": {
        "uz": "📦 Arxivlash", "ru": "📦 В архив", "en": "📦 Archive",
    },
    "adm.btn_recheck": {
        "uz": "🔄 Holatni tekshirish", "ru": "🔄 Проверить состояние",
        "en": "🔄 Re-check the state",
    },
    "adm.back_groups": {
        "uz": "◀️ Guruhlar", "ru": "◀️ Группы", "en": "◀️ Groups",
    },
    "adm.checking_groups": {
        "uz": "👥 Guruhlar holati tekshirilmoqda…", "ru": "👥 Проверяю состояние групп…",
        "en": "👥 Checking the groups…",
    },

    # foydalanuvchilar
    "adm.users_head": {
        "uz": "🙍 <b>Foydalanuvchilar</b> — jami {n} ta",
        "ru": "🙍 <b>Пользователи</b> — всего {n}",
        "en": "🙍 <b>Users</b> — {n} in total",
    },
    "adm.users_legend": {
        "uz": ("🧑 shaxsiy jurnal · 👑 guruh egasi · 👥 guruhga ulangan · "
               "🎁 taklif qilgan · 🚫 botni bloklagan"),
        "ru": ("🧑 личный журнал · 👑 владелец группы · 👥 подключён к группе · "
               "🎁 приглашал · 🚫 заблокировал бота"),
        "en": ("🧑 personal journal · 👑 group owner · 👥 joined a group · "
               "🎁 invited others · 🚫 blocked the bot"),
    },
    "adm.back_users": {
        "uz": "◀️ Foydalanuvchilar", "ru": "◀️ Пользователи", "en": "◀️ Users",
    },
    "adm.u_personal": {
        "uz": "Shaxsiy jurnal", "ru": "Личный журнал", "en": "Personal journal",
    },
    "adm.u_yes": {"uz": "bor 🧑", "ru": "есть 🧑", "en": "yes 🧑"},
    "adm.u_no": {"uz": "yo'q", "ru": "нет", "en": "no"},
    "adm.u_owns": {
        "uz": "Egalik qiladigan guruhlar 👑:", "ru": "Группы во владении 👑:",
        "en": "Groups they own 👑:",
    },
    "adm.u_owns_no": {
        "uz": "Guruh egasi: yo'q", "ru": "Владелец группы: нет", "en": "Group owner: no",
    },
    "adm.u_joined": {
        "uz": "Ulangan yopiq guruhlar 👥:", "ru": "Подключённые закрытые группы 👥:",
        "en": "Private groups joined 👥:",
    },
    "adm.u_joined_no": {
        "uz": "Ulangan yopiq guruhlar: yo'q",
        "ru": "Подключённые закрытые группы: нет",
        "en": "Private groups joined: none",
    },
    "adm.u_not_member": {
        "uz": " 🚫 a'zo emas", "ru": " 🚫 не участник", "en": " 🚫 not a member",
    },
    "adm.u_uncheckable": {
        "uz": " ❔ tekshirib bo'lmadi", "ru": " ❔ проверить не удалось",
        "en": " ❔ could not check",
    },
    "adm.u_invited": {
        "uz": "Taklif qilgan: <b>{n}</b> ta", "ru": "Пригласил: <b>{n}</b>",
        "en": "Invited: <b>{n}</b>",
    },
    "adm.u_invited_by": {
        "uz": "Kim taklif qilgan: <code>{id}</code>",
        "ru": "Кто пригласил: <code>{id}</code>",
        "en": "Invited by: <code>{id}</code>",
    },
    "adm.u_first": {"uz": "Birinchi", "ru": "Первый раз", "en": "First seen"},
    "adm.u_last": {"uz": "Oxirgi faollik", "ru": "Последняя активность", "en": "Last seen"},
    "adm.btn_live_check": {
        "uz": "🔍 A'zolikni jonli tekshirish", "ru": "🔍 Проверить членство вживую",
        "en": "🔍 Check membership live",
    },
    "adm.checking_member": {
        "uz": "🔍 A'zolik tekshirilmoqda…", "ru": "🔍 Проверяю членство…",
        "en": "🔍 Checking membership…",
    },

    # statistika
    "adm.stats": {
        "uz": ("📊 <b>Statistika</b>\n\n<b>Foydalanuvchilar</b>\n"
               "Jami: <b>{u_total}</b>\n"
               "Yangi: {new1} (24s)  •  {new7} (7 kun)\n"
               "Faol: {act1} (24s)  •  {act7} (7 kun)\n\n"
               "<b>Workspace'lar</b>\n"
               "Guruhlar: <b>{groups}</b>  •  Shaxsiy: <b>{personals}</b>\n"
               "Guruh kuzatuvchilari: {viewers}\n"
               "Reytingda: {pub_ok} ta (so'rov: {pub_req})\n\n"
               "<b>Signallar</b>\nJami: <b>{s_all}</b>\n"
               "Ochiq: {s_open}  •  Yopilgan: {s_closed}"),
        "ru": ("📊 <b>Статистика</b>\n\n<b>Пользователи</b>\n"
               "Всего: <b>{u_total}</b>\n"
               "Новых: {new1} (24ч)  •  {new7} (7 дней)\n"
               "Активных: {act1} (24ч)  •  {act7} (7 дней)\n\n"
               "<b>Рабочие пространства</b>\n"
               "Групп: <b>{groups}</b>  •  Личных: <b>{personals}</b>\n"
               "Наблюдателей групп: {viewers}\n"
               "В рейтинге: {pub_ok} (заявок: {pub_req})\n\n"
               "<b>Сигналы</b>\nВсего: <b>{s_all}</b>\n"
               "Открытых: {s_open}  •  Закрытых: {s_closed}"),
        "en": ("📊 <b>Stats</b>\n\n<b>Users</b>\n"
               "Total: <b>{u_total}</b>\n"
               "New: {new1} (24h)  •  {new7} (7 days)\n"
               "Active: {act1} (24h)  •  {act7} (7 days)\n\n"
               "<b>Workspaces</b>\n"
               "Groups: <b>{groups}</b>  •  Personal: <b>{personals}</b>\n"
               "Group watchers: {viewers}\n"
               "In the ranking: {pub_ok} (requests: {pub_req})\n\n"
               "<b>Signals</b>\nTotal: <b>{s_all}</b>\n"
               "Open: {s_open}  •  Closed: {s_closed}"),
    },
    "adm.refs_head": {
        "uz": "🎁 <b>Referrallar</b>", "ru": "🎁 <b>Рефералы</b>", "en": "🎁 <b>Referrals</b>",
    },
    "adm.refs_total": {
        "uz": "Jami taklif qilinganlar: <b>{n}</b>", "ru": "Всего приглашено: <b>{n}</b>",
        "en": "Invited in total: <b>{n}</b>",
    },
    "adm.refs_none": {
        "uz": "Hali hech kim taklif qilmagan.", "ru": "Пока никто никого не пригласил.",
        "en": "Nobody has invited anyone yet.",
    },
    "adm.refs_top": {
        "uz": "<b>Eng faol takliflovchilar:</b>", "ru": "<b>Самые активные пригласившие:</b>",
        "en": "<b>Most active inviters:</b>",
    },
    "adm.refs_n": {"uz": "{n} ta", "ru": "{n}", "en": "{n}"},

    # majburiy obuna
    "adm.ch_head": {
        "uz": "📢 <b>Majburiy obuna kanallari</b>",
        "ru": "📢 <b>Каналы обязательной подписки</b>",
        "en": "📢 <b>Required subscription channels</b>",
    },
    "adm.ch_note": {
        "uz": ("Botga /start bosgan har bir foydalanuvchi shu kanallarga obuna "
               "bo'lishi shart (adminlar bundan mustasno)."),
        "ru": ("Каждый, кто нажал /start, должен быть подписан на эти каналы "
               "(кроме админов)."),
        "en": ("Everyone who presses /start must be subscribed to these channels "
               "(admins excepted)."),
    },
    "adm.ch_none": {
        "uz": "Hozircha kanal yo'q — majburiy obuna <b>o'chirilgan</b>.",
        "ru": "Каналов пока нет — обязательная подписка <b>выключена</b>.",
        "en": "No channels yet — the required subscription is <b>off</b>.",
    },
    "adm.ch_add_btn": {
        "uz": "➕ Kanal qo'shish", "ru": "➕ Добавить канал", "en": "➕ Add a channel",
    },
    "adm.ch_add": {
        "uz": ("➕ <b>Kanal qo'shish</b>\n\n"
               "Kanal <code>@usernameni</code> yuboring, yoki o'sha kanaldan "
               "istalgan postni shu yerga <b>forward</b> qiling.\n\n"
               "⚠️ Bot o'sha kanalda <b>admin</b> bo'lishi shart — aks holda "
               "obunani tekshirib bo'lmaydi."),
        "ru": ("➕ <b>Добавление канала</b>\n\n"
               "Пришлите <code>@username</code> канала или <b>перешлите</b> сюда "
               "любой пост из него.\n\n"
               "⚠️ Бот должен быть <b>админом</b> в этом канале — иначе подписку "
               "не проверить."),
        "en": ("➕ <b>Add a channel</b>\n\n"
               "Send the channel's <code>@username</code>, or <b>forward</b> any "
               "post from it here.\n\n"
               "⚠️ The bot must be an <b>admin</b> in that channel — otherwise the "
               "subscription cannot be checked."),
    },

    # hashtaglar
    "adm.mth_head": {
        "uz": "📰 <b>MarketTwits — qo'shimcha #hashtaglar</b>",
        "ru": "📰 <b>MarketTwits — дополнительные #хэштеги</b>",
        "en": "📰 <b>MarketTwits — extra #hashtags</b>",
    },
    "adm.mth_note": {
        "uz": ("Bu hashtaglardan biri postda bo'lsa — tiker topilmasa ham "
               "(matn-only) kanalga postlanadi."),
        "ru": ("Если в посте есть один из этих хэштегов — он уйдёт в канал даже "
               "без тикера (только текстом)."),
        "en": ("If a post carries one of these hashtags, it goes to the channel "
               "even with no ticker (text only)."),
    },
    "adm.mth_none": {
        "uz": ("Hozircha yo'q — faqat RESOLVE bo'ladigan tikerli postlar "
               "(masalan #BTC, #AAPL) o'tadi."),
        "ru": ("Пока пусто — проходят только посты с распознаваемым тикером "
               "(например #BTC, #AAPL)."),
        "en": ("Empty for now — only posts with a resolvable ticker (for example "
               "#BTC, #AAPL) pass."),
    },
    "adm.mth_add_btn": {
        "uz": "➕ Hashtag qo'shish", "ru": "➕ Добавить хэштег", "en": "➕ Add a hashtag",
    },
    "adm.mth_add": {
        "uz": ("➕ <b>Hashtag qo'shish</b>\n\n"
               "Bitta yoki bir nechta so'z yuboring (# bilan yoki #siz, "
               "bo'shliq/vergul bilan ajratib) — masalan:\n"
               "<code>geopolitika, hisobot, ETF</code>"),
        "ru": ("➕ <b>Добавление хэштега</b>\n\n"
               "Пришлите одно или несколько слов (с # или без, через пробел или "
               "запятую) — например:\n<code>геополитика, отчёт, ETF</code>"),
        "en": ("➕ <b>Add a hashtag</b>\n\n"
               "Send one or several words (with or without #, separated by spaces "
               "or commas) — for example:\n<code>geopolitics, earnings, ETF</code>"),
    },
    "adm.mth_empty": {
        "uz": "Hashtag topilmadi. Masalan: geopolitika, hisobot",
        "ru": "Хэштег не найден. Например: геополитика, отчёт",
        "en": "No hashtag found. For example: geopolitics, earnings",
    },
    "adm.mth_added": {
        "uz": "✅ Qo'shildi: {tags}", "ru": "✅ Добавлено: {tags}", "en": "✅ Added: {tags}",
    },

    # tasdiqlar
    "adm.pend_none": {
        "uz": "🛡 Tasdiq kutayotgan guruh yo'q. ✅",
        "ru": "🛡 Групп, ждущих одобрения, нет. ✅",
        "en": "🛡 No group is waiting for approval. ✅",
    },
    "adm.pend_n": {
        "uz": "🛡 Tasdiq kutmoqda: <b>{n}</b> ta",
        "ru": "🛡 Ждут одобрения: <b>{n}</b>",
        "en": "🛡 Waiting for approval: <b>{n}</b>",
    },

    # --- Broadcast, PDF, kanal qo'shish ---
    "adm.bc_prompt": {
        "uz": ("📣 <b>Broadcast</b>\n\nXabar <b>{n}</b> ta foydalanuvchiga "
               "yuboriladi.\n\nYubormoqchi bo'lgan xabaringizni shu yerga yuboring "
               "— matn, rasm, video, nima bo'lsa ham. Qanday yuborsangiz, xuddi "
               "shundayligicha yetkaziladi.\n\nBekor qilish uchun /bekor yozing."),
        "ru": ("📣 <b>Рассылка</b>\n\nСообщение уйдёт <b>{n}</b> "
               "пользователям.\n\nПришлите сюда то, что хотите разослать — текст, "
               "картинку, видео, что угодно. Доставится ровно в том же виде.\n\n"
               "Для отмены напишите /bekor."),
        "en": ("📣 <b>Broadcast</b>\n\nThe message goes to <b>{n}</b> users.\n\n"
               "Send here whatever you want to broadcast — text, an image, a video, "
               "anything. It is delivered exactly as you sent it.\n\n"
               "Send /bekor to cancel."),
    },
    "adm.bc_confirm": {
        "uz": ("⬆️ Shu xabar <b>{n}</b> ta foydalanuvchiga yuboriladi.\n"
               "Taxminiy vaqt: ~{sec} soniya.\n\nTasdiqlaysizmi?"),
        "ru": ("⬆️ Это сообщение уйдёт <b>{n}</b> пользователям.\n"
               "Примерное время: ~{sec} секунд.\n\nПодтверждаете?"),
        "en": ("⬆️ This message goes to <b>{n}</b> users.\n"
               "Estimated time: ~{sec} seconds.\n\nConfirm?"),
    },
    "adm.bc_yes": {
        "uz": "✅ Ha, yuborilsin", "ru": "✅ Да, отправить", "en": "✅ Yes, send it",
    },
    "adm.bc_no": {
        "uz": "❌ Bekor qilish", "ru": "❌ Отменить", "en": "❌ Cancel",
    },
    "adm.bc_lost": {
        "uz": "Yuboriladigan xabar topilmadi — qaytadan boshlang.",
        "ru": "Сообщение для рассылки не найдено — начните заново.",
        "en": "The message to broadcast was not found — start again.",
    },
    "adm.bc_started": {
        "uz": "📣 Yuborish boshlandi — tugagach hisobot keladi.",
        "ru": "📣 Рассылка началась — по завершении придёт отчёт.",
        "en": "📣 The broadcast started — a report arrives when it finishes.",
    },
    "adm.bc_done": {
        "uz": ("📣 <b>Broadcast tugadi</b>\n\n✅ Yuborildi: <b>{sent}</b>\n"
               "🚫 Bloklaganlar: {blocked}\n⚠️ Xato: {failed}\n\nJami: {total}"),
        "ru": ("📣 <b>Рассылка завершена</b>\n\n✅ Отправлено: <b>{sent}</b>\n"
               "🚫 Заблокировали: {blocked}\n⚠️ Ошибок: {failed}\n\nВсего: {total}"),
        "en": ("📣 <b>Broadcast finished</b>\n\n✅ Sent: <b>{sent}</b>\n"
               "🚫 Blocked the bot: {blocked}\n⚠️ Errors: {failed}\n\nTotal: {total}"),
    },
    "adm.pdf_making": {
        "uz": "📄 Tayyorlanmoqda…", "ru": "📄 Готовлю…", "en": "📄 Preparing…",
    },

    # --- Kanal qo'shish, /tuzat, /qaytar, /pending ---
    "adm.ch_unknown": {
        "uz": "Kanalni aniqlab bo'lmadi. @username yuboring yoki kanaldan post forward qiling.",
        "ru": "Не удалось определить канал. Пришлите @username или перешлите пост из канала.",
        "en": "Could not identify the channel. Send its @username or forward a post from it.",
    },
    "adm.ch_notfound": {
        "uz": ("❌ Kanal topilmadi. @username to'g'riligini va botning o'sha kanalda "
               "admin ekanini tekshiring."),
        "ru": ("❌ Канал не найден. Проверьте @username и то, что бот админ в этом "
               "канале."),
        "en": ("❌ Channel not found. Check the @username and that the bot is an admin "
               "there."),
    },
    "adm.ch_warn_notadmin": {
        "uz": ("\n\n⚠️ <b>Diqqat:</b> bot bu kanalda admin emas — obuna tekshiruvi "
               "ishlamaydi. Botni kanalga admin qilib qo'shing."),
        "ru": ("\n\n⚠️ <b>Внимание:</b> бот не админ в этом канале — проверка "
               "подписки работать не будет. Сделайте бота админом."),
        "en": ("\n\n⚠️ <b>Note:</b> the bot is not an admin in this channel — the "
               "subscription check will not work. Make the bot an admin there."),
    },
    "adm.ch_warn_unknown": {
        "uz": ("\n\n⚠️ <b>Diqqat:</b> botning kanaldagi holatini tekshirib bo'lmadi. "
               "Bot kanalda admin ekaniga ishonch hosil qiling."),
        "ru": ("\n\n⚠️ <b>Внимание:</b> не удалось проверить статус бота в канале. "
               "Убедитесь, что бот там админ."),
        "en": ("\n\n⚠️ <b>Note:</b> the bot's status in the channel could not be "
               "checked. Make sure it is an admin there."),
    },
    "adm.ch_added": {
        "uz": "✅ Qo'shildi: <b>{name}</b>", "ru": "✅ Добавлен: <b>{name}</b>",
        "en": "✅ Added: <b>{name}</b>",
    },
    "adm.fix_head": {
        "uz": "🛠 <b>Signallarni tuzatish</b> — {name}",
        "ru": "🛠 <b>Правка сигналов</b> — {name}",
        "en": "🛠 <b>Fixing signals</b> — {name}",
    },
    "adm.fix_last_n": {
        "uz": "Oxirgi {n} ta", "ru": "Последние {n}", "en": "Last {n}",
    },
    "adm.fix_off_n": {
        "uz": " · {n} tasi hisobdan chiqarilgan", "ru": " · {n} исключено из статистики",
        "en": " · {n} excluded from the stats",
    },
    "adm.fix_note": {
        "uz": ("Tugmani bosing — signal statistikadan olib tashlanadi. Qayta bossangiz "
               "qaytariladi. Hech narsa o'chirilmaydi."),
        "ru": ("Нажмите кнопку — сигнал уйдёт из статистики. Нажмёте ещё раз — "
               "вернётся. Ничего не удаляется."),
        "en": ("Press a button — the signal leaves the stats. Press again and it comes "
               "back. Nothing is deleted."),
    },
    "adm.fix_none": {
        "uz": "Signal topilmadi{what}.", "ru": "Сигналы не найдены{what}.",
        "en": "No signal found{what}.",
    },
    "adm.fix_by": {
        "uz": " <code>{sym}</code> bo'yicha", "ru": " по <code>{sym}</code>",
        "en": " for <code>{sym}</code>",
    },
    "adm.fix_btn_off": {
        "uz": "🚫 chiqarish", "ru": "🚫 исключить", "en": "🚫 exclude",
    },
    "adm.fix_btn_on": {
        "uz": "↩️ qaytarish", "ru": "↩️ вернуть", "en": "↩️ restore",
    },
    "adm.fix_done_off": {
        "uz": "Hisobdan chiqarildi.", "ru": "Исключено из статистики.",
        "en": "Excluded from the stats.",
    },
    "adm.fix_done_on": {
        "uz": "Qaytarildi.", "ru": "Возвращено.", "en": "Restored.",
    },
    "adm.ws_not_found": {
        "uz": "Workspace topilmadi.", "ru": "Рабочее пространство не найдено.",
        "en": "Workspace not found.",
    },
    "adm.reopen_usage": {
        "uz": "Foydalanish: /qaytar <signal ID>", "ru": "Использование: /qaytar <ID сигнала>",
        "en": "Usage: /qaytar <signal ID>",
    },
    "adm.reopen_nan": {
        "uz": "Signal ID raqam bo'lishi kerak.", "ru": "ID сигнала должен быть числом.",
        "en": "The signal ID must be a number.",
    },
    "adm.reopen_gone": {
        "uz": ("#{sid} topilmadi yoki allaqachon ochiq (faqat YOPILGAN signalni "
               "qaytarish mumkin)."),
        "ru": ("#{sid} не найден или уже открыт (вернуть можно только ЗАКРЫТЫЙ "
               "сигнал)."),
        "en": ("#{sid} was not found, or it is already open (only a CLOSED signal can "
               "be reopened)."),
    },
    "adm.reopen_done": {
        "uz": ("↩️ <b>#{sid} {sym}</b> — ACTIVE holatiga qaytarildi.\nStop xavfsiz "
               "boshlang'ich qiymatga tushirildi, TP/SL kuzatuvi hozirdan davom etadi."),
        "ru": ("↩️ <b>#{sid} {sym}</b> — возвращён в ACTIVE.\nСтоп сброшен к "
               "безопасному начальному значению, отслеживание TP/SL продолжается."),
        "en": ("↩️ <b>#{sid} {sym}</b> — reopened as ACTIVE.\nThe stop was reset to its "
               "safe initial value; TP/SL tracking continues from now."),
    },

    # --- /karta, /charttest, /refhavola, Telethon login (hammasi admin) ---
    "adm.card_usage": {
        "uz": "Foydalanish: <code>/karta 142</code> — signal raqami.",
        "ru": "Использование: <code>/karta 142</code> — номер сигнала.",
        "en": "Usage: <code>/karta 142</code> — the signal number.",
    },
    "adm.card_no_sig": {
        "uz": "#{sid} topilmadi.", "ru": "#{sid} не найден.", "en": "#{sid} not found.",
    },
    "adm.card_not_yours": {
        "uz": "Bu signal sizniki emas.", "ru": "Этот сигнал не ваш.",
        "en": "This signal is not yours.",
    },
    "adm.card_open": {
        "uz": "#{sid} hali yopilmagan — karta yopilgandan keyin tayyor bo'ladi.",
        "ru": "#{sid} ещё не закрыт — карточка появится после закрытия.",
        "en": "#{sid} is not closed yet — the card is ready once it closes.",
    },
    "adm.card_drawing": {
        "uz": "🎨 Karta chizilyapti…", "ru": "🎨 Рисую карточку…",
        "en": "🎨 Drawing the card…",
    },
    "adm.card_failed": {
        "uz": "Kartani yasab bo'lmadi.", "ru": "Не удалось собрать карточку.",
        "en": "The card could not be built.",
    },
    "adm.card_caption": {
        "uz": "#{sid} {sym} — ulashish uchun", "ru": "#{sid} {sym} — чтобы поделиться",
        "en": "#{sid} {sym} — for sharing",
    },
    "adm.ct_no_channel": {
        "uz": "NEWS_CHANNEL_ID sozlanmagan.", "ru": "NEWS_CHANNEL_ID не задан.",
        "en": "NEWS_CHANNEL_ID is not set.",
    },
    "adm.ct_usage": {
        "uz": "Foydalanish: /charttest TLM", "ru": "Использование: /charttest TLM",
        "en": "Usage: /charttest TLM",
    },
    "adm.ct_no_symbol": {
        "uz": "Tiker topilmadi (kripto/aksiya/forex — hech birida): {sym}",
        "ru": "Тикер не найден (ни в крипто, ни в акциях, ни в форекс): {sym}",
        "en": "Ticker not found (neither crypto, stocks nor forex): {sym}",
    },
    "adm.ct_drawing": {
        "uz": "⏳ {sym} ({market}) — grafik chizilyapti...",
        "ru": "⏳ {sym} ({market}) — рисую график...",
        "en": "⏳ {sym} ({market}) — drawing the chart...",
    },
    "adm.ct_failed": {
        "uz": ("Grafik chizib bo'lmadi — bu tikerda so'nggi shamlar topilmadi "
               "(bozor yopiq bo'lishi ham mumkin)."),
        "ru": ("Не удалось построить график — свежих свечей по тикеру нет "
               "(рынок может быть закрыт)."),
        "en": ("The chart could not be drawn — no recent candles for this ticker "
               "(the market may be closed)."),
    },
    "adm.rl_current": {
        "uz": ("Joriy MEXC referal havola: {cur}\n\n"
               "Belgilash: <code>/refhavola https://www.mexc.com/register?inviteCode=XXX</code>\n"
               "Agar havolada <code>{{symbol}}</code> bo'lsa, u postdagi juftlik bilan "
               "(masalan BTC_USDT) almashtiriladi.\nO'chirish: <code>/refhavola off</code>"),
        "ru": ("Текущая реферальная ссылка MEXC: {cur}\n\n"
               "Задать: <code>/refhavola https://www.mexc.com/register?inviteCode=XXX</code>\n"
               "Если в ссылке есть <code>{{symbol}}</code>, он заменяется парой из поста "
               "(например BTC_USDT).\nУбрать: <code>/refhavola off</code>"),
        "en": ("Current MEXC referral link: {cur}\n\n"
               "Set it: <code>/refhavola https://www.mexc.com/register?inviteCode=XXX</code>\n"
               "If the link contains <code>{{symbol}}</code>, it is replaced with the pair "
               "from the post (for example BTC_USDT).\nRemove it: <code>/refhavola off</code>"),
    },
    "adm.rl_unset": {
        "uz": "(belgilanmagan)", "ru": "(не задана)", "en": "(not set)",
    },
    "adm.rl_off": {
        "uz": "🔒 Referal havola o'chirildi.", "ru": "🔒 Реферальная ссылка убрана.",
        "en": "🔒 The referral link was removed.",
    },
    "adm.rl_saved": {
        "uz": "✅ Saqlandi:\n{url}", "ru": "✅ Сохранено:\n{url}", "en": "✅ Saved:\n{url}",
    },
    "adm.tg_no_keys": {
        "uz": "TELETHON_API_ID/TELETHON_API_HASH sozlanmagan (Railway o'zgaruvchisi).",
        "ru": "TELETHON_API_ID/TELETHON_API_HASH не заданы (переменные Railway).",
        "en": "TELETHON_API_ID/TELETHON_API_HASH are not set (Railway variables).",
    },
    "adm.tg_login_usage": {
        "uz": "Foydalanish: /tg_login +998901234567",
        "ru": "Использование: /tg_login +998901234567",
        "en": "Usage: /tg_login +998901234567",
    },
    "adm.tg_code_err": {
        "uz": "Kod so'rashda xato — loglarni tekshiring.",
        "ru": "Ошибка при запросе кода — проверьте логи.",
        "en": "Error requesting the code — check the logs.",
    },
    "adm.tg_code_sent": {
        "uz": "Kod yuborildi, Telegram ilovangizni tekshiring. Keyin: /tg_code 12345",
        "ru": "Код отправлен, проверьте приложение Telegram. Затем: /tg_code 12345",
        "en": "The code was sent, check your Telegram app. Then: /tg_code 12345",
    },
    "adm.tg_code_usage": {
        "uz": "Foydalanish: /tg_code 12345", "ru": "Использование: /tg_code 12345",
        "en": "Usage: /tg_code 12345",
    },
    "adm.tg_code_bad": {
        "uz": "Kod xato yoki muddati tugagan — /tg_login bilan qayta boshlang.",
        "ru": "Код неверный или истёк — начните заново с /tg_login.",
        "en": "The code is wrong or expired — start again with /tg_login.",
    },
    "adm.tg_need_pw": {
        "uz": "Akkauntda 2FA parol bor. Yuboring: /tg_password <parol>",
        "ru": "На аккаунте включён 2FA. Пришлите: /tg_password <пароль>",
        "en": "The account has 2FA. Send: /tg_password <password>",
    },
    "adm.tg_pw_usage": {
        "uz": "Foydalanish: /tg_password <parol>", "ru": "Использование: /tg_password <пароль>",
        "en": "Usage: /tg_password <password>",
    },
    "adm.tg_pw_bad": {
        "uz": "Parol xato — qayta urinib ko'ring.", "ru": "Неверный пароль — попробуйте снова.",
        "en": "Wrong password — try again.",
    },
    "adm.tg_ok": {
        "uz": "✅ Login muvaffaqiyatli! MarketTwits endi tinglanmoqda.",
        "ru": "✅ Вход выполнен! MarketTwits теперь прослушивается.",
        "en": "✅ Logged in! MarketTwits is now being listened to.",
    },

    "adm.pub_approved": {
        "uz": "✅ <b>{name}</b> tasdiqlandi — reytingda ko'rinadi.",
        "ru": "✅ <b>{name}</b> одобрена — попадёт в рейтинг.",
        "en": "✅ <b>{name}</b> approved — it shows in the ranking.",
    },
    "adm.pub_rejected": {
        "uz": "🚫 <b>{name}</b> rad etildi — reytingga chiqmaydi.",
        "ru": "🚫 <b>{name}</b> отклонена — в рейтинг не попадёт.",
        "en": "🚫 <b>{name}</b> rejected — it stays out of the ranking.",
    },
    "adm.ct_network": {
        "uz": ("⏱ Tarmoq vaqtincha javob bermadi (Telegram/Railway orasida uzilish). "
               "Qayta urinib ko'ring: /charttest {sym}"),
        "ru": ("⏱ Сеть временно не ответила (обрыв между Telegram и Railway). "
               "Попробуйте снова: /charttest {sym}"),
        "en": ("⏱ The network did not answer (a hiccup between Telegram and Railway). "
               "Try again: /charttest {sym}"),
    },
    "adm.ct_post_failed": {
        "uz": "Kanalga postlab bo'lmadi (bot admin emasmi?).",
        "ru": "Не удалось опубликовать в канал (бот не админ?).",
        "en": "Could not post to the channel (is the bot an admin?).",
    },
    "adm.tgt_usage": {
        "uz": ("Foydalanish: /tg_test <matn>\nMatnda tanish #hashtag bo'lsin, masalan:\n"
               "/tg_test #BTC ETF arizasi tasdiqlandi"),
        "ru": ("Использование: /tg_test <текст>\nВ тексте должен быть знакомый "
               "#хэштег, например:\n/tg_test #BTC заявка на ETF одобрена"),
        "en": ("Usage: /tg_test <text>\nThe text must contain a known #hashtag, for "
               "example:\n/tg_test #BTC the ETF filing was approved"),
    },
    "adm.tgt_running": {
        "uz": "Tekshirilmoqda…", "ru": "Проверяю…", "en": "Checking…",
    },
    "adm.tgt_done": {
        "uz": ("Tayyor. Matndagi #hashtaglardan biri tanish tikerga to'g'ri kelsa — "
               "kanalga postlangan bo'lishi kerak; hech biri topilmasa — hech narsa "
               "chiqmaydi (bu normal, filtr shunday ishlaydi)."),
        "ru": ("Готово. Если один из #хэштегов совпал с известным тикером — пост "
               "должен уйти в канал; если ни один не совпал — ничего не выйдет "
               "(это нормально, так работает фильтр)."),
        "en": ("Done. If one of the #hashtags matched a known ticker, a post should "
               "have gone to the channel; if none matched, nothing is posted (that is "
               "normal — this is how the filter works)."),
    },

    # --- Admin PDF hisobotlari ---
    "adm.pdfg_title": {
        "uz": "Ulangan guruhlar", "ru": "Подключённые группы", "en": "Connected groups",
    },
    "adm.pdfg_sub": {
        "uz": "Jami {n} ta guruh · {bad} tasida muammo",
        "ru": "Всего групп: {n} · с проблемами: {bad}",
        "en": "{n} groups in total · {bad} with problems",
    },
    "adm.pdfg_col_group": {"uz": "Guruh", "ru": "Группа", "en": "Group"},
    "adm.pdfg_col_sig": {"uz": "Signal", "ru": "Сигн.", "en": "Signals"},
    "adm.pdfg_col_closed": {"uz": "Yopilgan", "ru": "Закрыто", "en": "Closed"},
    "adm.pdfg_col_view": {"uz": "Kuzatuv", "ru": "Набл.", "en": "Watch"},
    "adm.pdfg_col_state": {"uz": "Holat", "ru": "Состояние", "en": "State"},
    "adm.st_ok": {"uz": "ishlayapti", "ru": "работает", "en": "working"},
    "adm.st_notadmin": {"uz": "admin emas", "ru": "не админ", "en": "not admin"},
    "adm.st_kicked": {"uz": "chiqarilgan", "ru": "удалён", "en": "removed"},
    "adm.st_none": {"uz": "biriktirilmagan", "ru": "не привязана", "en": "not attached"},
    "adm.st_archived": {"uz": " (arxiv)", "ru": " (архив)", "en": " (archived)"},
    "adm.pdfu_title": {
        "uz": "Foydalanuvchilar", "ru": "Пользователи", "en": "Users",
    },
    "adm.pdfu_sub": {"uz": "Jami {n} ta", "ru": "Всего: {n}", "en": "{n} in total"},
    "adm.pdfu_col_user": {"uz": "Foydalanuvchi", "ru": "Пользователь", "en": "User"},
    "adm.pdfu_col_role": {"uz": "Rol", "ru": "Роль", "en": "Role"},
    "adm.pdfu_col_inv": {"uz": "Taklif", "ru": "Пригл.", "en": "Invited"},
    "adm.pdfu_col_last": {"uz": "Oxirgi", "ru": "Последний", "en": "Last"},
    "adm.role_personal": {"uz": "shaxsiy", "ru": "личный", "en": "personal"},
    "adm.role_owner": {"uz": "egasi×{n}", "ru": "владелец×{n}", "en": "owner×{n}"},
    "adm.role_member": {"uz": "a'zo×{n}", "ru": "участник×{n}", "en": "member×{n}"},

    # --- Ulashish kartasi (card.py) — GURUHGA ketadi, ws_lang bilan ---
    "card.subtitle": {
        "uz": "Savdo jurnali", "ru": "Журнал сделок", "en": "Trading journal",
    },
    "card.closed": {
        "uz": "YOPILGAN SAVDO", "ru": "СДЕЛКА ЗАКРЫТА", "en": "CLOSED TRADE",
    },
    "card.entry": {
        "uz": "Kirish narxi", "ru": "Цена входа", "en": "Entry price",
    },
    "card.exit": {
        "uz": "Chiqish narxi", "ru": "Цена выхода", "en": "Exit price",
    },
    "card.r": {
        "uz": "Natija (R)", "ru": "Результат (R)", "en": "Result (R)",
    },
    "card.ref_code": {
        "uz": "Taklif kodi", "ru": "Код приглашения", "en": "Invite code",
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
