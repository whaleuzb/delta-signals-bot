# Delta Signals Bot — loyiha konteksti

Telegram guruhdagi trading signallarni avtomatik kuzatib, foiz va R statistikasini
yurituvchi bot. Delta Community uchun.

**Stack:** Python 3.11+ · python-telegram-bot 21 · asyncpg + Railway PostgreSQL ·
MEXC Spot public API · matplotlib · Claude vision (ixtiyoriy)

> Avval Binance USDⓈ-M Futures ishlatilgan, lekin Railway serveri joylashgan
> hududni Binance 451 (huquqiy sabab) bilan bloklagani uchun MEXC Spot'ga
> o'tildi (2026-08). MEXC'da kichik altcoinlar ham ko'proq bor.

---

## Arxitektura

Bitta process (`python bot.py`) — Telegram polling va kuzatuv sikli bir joyda,
PTB `job_queue` orqali. Trafik oshsa `tracker.run_once()` ni alohida service'ga
ajratish mumkin, lekin hozirgi hajmda kerak emas.

| Fayl | Vazifa |
|---|---|
| `config.py` | barcha env o'zgaruvchilar va savdo qoidalari |
| `db.py` | schema, pool, so'rovlar, statistika SQL |
| `exchange.py` | MEXC klines/exchangeInfo, symbol normalizatsiya |
| `parsing.py` | caption matnidan darajalarni o'qish + validatsiya |
| `vision.py` | caption bo'lmasa grafik rasmidan o'qish (Claude tool use) |
| `tracker.py` | **asosiy dvigatel** — shamlarni qayta o'ynatib TP/SL aniqlaydi |
| `stats.py` | hisobotlar, equity curve + drawdown |
| `bot.py` | handlerlar, asosiy menyu, signal kiritish sehrgari (wizard), tasdiqlash oqimi, guruhga e'lonlar |
| `test_tracker.py` | sintetik shamlarda dvigatel testi (baza/internet kerak emas) |

Signal hayot sikli:
`PENDING → ACTIVE → TP | SL | BREAKEVEN` (yoki `EXPIRED` / `CANCELLED`)

---

## BUZILMASIN — qiyin yo'l bilan topilgan qarorlar

Bular allaqachon sinovdan o'tgan. O'zgartirishdan oldin `test_tracker.py` ni ishlating.

1. **1 daqiqalik klines, `ticker/price` emas.**
   Bot 45 soniya uxlaydi; shu vaqtda narx TP'ga tegib qaytishi mumkin. Klines'dagi
   `high`/`low` shuning uchun kerak. `last_price()` faqat `/open` ko'rsatkichi uchun.

2. **`last_checked_ms` dan davom etish.**
   Bot uzilib qolsa, qayta ishga tushganda o'tgan shamlar ketma-ket qayta o'ynatiladi.
   Natija bir xil chiqishi kerak — `test_tracker.py` dagi "Uzilgan sikl" testi shuni tekshiradi.

3. **asyncpg `NUMERIC` ustunga `float` qabul qilmaydi.**
   `db._d()` orqali `Decimal` ga o'girish shart. Bu birinchi signaldayoq crash beradigan bug edi.

4. **Bitta shamda TP ham SL ham teksa — SL hisoblanadi.**
   1 daqiqa ichida tartibni bilib bo'lmaydi. Signal `ambiguous=true` bo'ladi va admin
   ogohlantiriladi. Statistika optimistik bo'lib qolmasligi uchun ataylab konservativ.

5. **`run_polling(drop_pending_updates=False)`.**
   `True` qilinsa restart paytida kelgan xabarlar jimgina yo'qoladi.

6. **`parsing.py` dagi ikkita raqam regexi.**
   `NUM` — bo'sh joyli minglikni tushunadi (`65 000`), bitta qiymat kutilgan joyda.
   `NUMS` — bo'sh joyni ajratgich deb biladi (`172 168` = ikkita raqam), ketma-ket
   qiymatlar uchun. Ikkalasini bittaga birlashtirmang — `"tp 172 168"` yopishib qoladi.
   Shuningdek `tp\d` — indeks faqat `tp` ga yopishgan bo'lsa (`TP1`), aks holda
   `"tp 172"` da `1` narxdan yeb ketiladi.

7. **Vision natijasi hech qachon to'g'ridan-to'g'ri bazaga tushmaydi.**
   Har doim admin tasdiqlash tugmasidan o'tadi. Bu oqimni avtomatlashtirmang —
   bitta noto'g'ri o'qilgan raqam butun statistikani buzadi.

8. **Spot rejimi.** PnL leveragesiz. TP'lar `TP_ALLOCATION` bo'yicha bo'lib sotiladi
   (50/30/20), foiz shu ulushlarga tortiladi. `r_multiple` `sl_initial` dan hisoblanadi,
   BE ga ko'chgan `sl` dan emas.

9. **Signal kiritishning IKKI yo'li bor, ikkalasi ham ishlaydi.**
   - Tezkor: bitta xabar (caption/matn, `on_photo`/`on_text_signal`) — tajribali admin uchun.
   - Sehrgar (wizard): `➕ Yangi signal` tugmasi yoki `/new` — `ConversationHandler`
     orqali bosqichma-bosqich (grafik → juftlik → yo'nalish → entry → TP → SL).
   Ikkalasi ham oxirida bitta umumiy `show_preview()` ga tushadi — tasdiqlash/tahrirlash/
   bekor tugmalari bir xil. Wizard faqat shaxsiy chatda ishlaydi (guruhda emas).

10. **Guruh — forum (topics) rejimida.** `CHANNEL_ID` supergroup uchun `-100` prefiksi
    bilan bo'lishi SHART (masalan `-1001804915914`, oddiy `-1804915914` emas — aks holda
    Telegram "Chat not found" beradi). Aniq mavzuga yozish uchun `CHANNEL_TOPIC_ID`
    (`message_thread_id`) kerak — bo'sh bo'lsa umumiy (General) mavzuga tushadi.
    To'g'ri qiymatlarni topish uchun `on_group_message` debug logi ishlatiladi (guruhga
    xabar yozilganda `chat_id`/`thread_id`ni logga chiqaradi).

11. **Kirish nazorati — alohida obunachilar bazasi YO'Q, guruh a'zoligi tekshiriladi.**
    whale-payment-bot muddati tugagan obunachilarni "Whales Uzb" guruhidan (aynan shu
    workspace'ning `group_chat_id`'si) har 6 soatda avtomatik chiqarib turadi — shuning
    uchun "hozir guruh a'zosimi" tekshiruvi "hozir obunachimi" degani bilan bir xil.
    `can_view()` (`bot.py`) `get_chat_member(group_chat_id, uid)` chaqiradi, ikkala botni
    DB darajasida bog'lash SHART EMAS. Bu faqat `type='group'` workspace'larga tegishli —
    shaxsiy workspace'da faqat egasi ko'radi. Statistikaga oid barcha buyruq/tugmalar
    shu bilan himoyalangan; super-adminlar (`is_admin`, `config.ADMIN_IDS`) har doim o'tadi.

12. **Multi-tenant: `workspaces` jadvali, `CHANNEL_ID` env o'zgaruvchisi endi YO'Q.**
    Bitta bot ko'p mustaqil "joy"ga xizmat qiladi — har bir `signals` yozuvi bitta
    `workspace_id`ga tegishli, workspace'lar bir-birining ma'lumotini ko'rmaydi.
    - `type='group'` — yopiq Telegram guruhi, guruh admini `/setup` yozib ochadi
      (`cmd_setup`, faqat guruh ichida, faqat creator/administrator, bitta admin —
      bitta guruh: `UNIQUE(owner_id,type)`). `group_chat_id`/`group_topic_id` shu
      workspace ichida saqlanadi (avval global `CHANNEL_ID`/`CHANNEL_TOPIC_ID` edi).
    - `type='personal'` — istalgan odam uchun avtomatik ochiladigan shaxsiy jurnal
      (`get_or_create_personal_workspace`), hech qayerga post qilinmaydi, faqat egasi
      ko'radi.
    - Ruxsat ikki bosqich: `can_manage()` (signal kirita/yopa oladi — workspace admini
      yoki super-admin) va `can_view()` (statistikani ko'ra oladi — yuqoridagi #11).
    - Shaxsiy chatda qaysi workspace ishlatilishini `resolve_workspace()` aniqlaydi:
      `ctx.user_data["workspace_id"]` keshi → agar bitta variant bo'lsa avtomatik →
      bir nechta variant bo'lsa (o'z guruhi + shaxsiy) `send_workspace_switcher()`
      tugmalarini ko'rsatadi (`switch` / `ws:<id>` callback'lar). Guruh ichida — doim
      o'sha guruhning workspace'i, tanlov yo'q.
    - Signal kiritish (tezkor va sehrgar) endi FAQAT shaxsiy chatda ishlaydi (guruh
      ichida emas) — chunki bitta guruh xabaridan qaysi workspace'ga tegishli ekanini
      bilib bo'lmaydi (agar bitta admin bir nechta guruhni boshqarsa). Guruhga post
      `ws["group_chat_id"]` orqali `on_button`/`poll_job` ichida amalga oshadi.
    - `tracker.run_once()` barcha workspace'lardagi ochiq signallarni bitta so'rovda
      oladi (`db.live_signals(None)`), har hodisaga o'z `workspace_id`sini qo'shib
      qaytaradi — `poll_job` shu bo'yicha guruhni topib xabar yuboradi (yoki shaxsiy
      bo'lsa hech narsa yubormaydi).
    - Eski production ma'lumotlar `migrate_multitenant.py` bir martalik skripti bilan
      "Whales Uzb" workspace'iga bog'landi (startCommand vaqtincha
      `python migrate_multitenant.py; python bot.py` qilingan holda ishga tushirildi).

---

## Buyruqlar

```bash
python test_tracker.py          # dvigatel testi — o'zgartirishdan keyin majburiy
python bot.py                   # lokal ishga tushirish (.env kerak)
pip install -r requirements.txt
```

Deploy: Railway, GitHub repo'dan avtomatik. Start command `python bot.py`.
Schema `db.init()` da avtomatik yaratiladi.

---

## Env o'zgaruvchilar

`BOT_TOKEN` · `DATABASE_URL` · `ADMIN_IDS` — majburiy.
`ANTHROPIC_API_KEY` — bo'sh bo'lsa vision jim o'chadi, bot ishlayveradi.
`CHANNEL_ID`/`CHANNEL_TOPIC_ID` endi YO'Q — har bir guruh o'zini `/setup` bilan
ro'yxatdan o'tkazadi (#12 ga qarang). Qolganlari `.env.example` da.

---

## Uslub

- Kod izohlari va bot xabarlari **o'zbek tilida**, texnik atamalar inglizcha qoladi.
- Bot xabarlarida HTML parse mode (`<b>`, `<code>`), Markdown emas.
- Yangi funksiya qo'shilsa `test_tracker.py` ga tegishli holat qo'shilsin.
- To'liq fayl qaytaring, qismli diff emas.
