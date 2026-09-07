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
