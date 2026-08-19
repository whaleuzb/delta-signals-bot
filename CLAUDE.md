# Delta Signals Bot — loyiha konteksti

Telegram guruhdagi trading signallarni avtomatik kuzatib, foiz va R statistikasini
yurituvchi bot. Delta Community uchun.

**Stack:** Python 3.11+ · python-telegram-bot 21 · asyncpg + Railway PostgreSQL ·
Binance USDⓈ-M Futures public API · matplotlib · Claude vision (ixtiyoriy)

---

## Arxitektura

Bitta process (`python bot.py`) — Telegram polling va kuzatuv sikli bir joyda,
PTB `job_queue` orqali. Trafik oshsa `tracker.run_once()` ni alohida service'ga
ajratish mumkin, lekin hozirgi hajmda kerak emas.

| Fayl | Vazifa |
|---|---|
| `config.py` | barcha env o'zgaruvchilar va savdo qoidalari |
| `db.py` | schema, pool, so'rovlar, statistika SQL |
| `exchange.py` | Binance klines/exchangeInfo, symbol normalizatsiya |
| `parsing.py` | caption matnidan darajalarni o'qish + validatsiya |
| `vision.py` | caption bo'lmasa grafik rasmidan o'qish (Claude tool use) |
| `tracker.py` | **asosiy dvigatel** — shamlarni qayta o'ynatib TP/SL aniqlaydi |
| `stats.py` | hisobotlar, equity curve + drawdown |
| `bot.py` | handlerlar, tasdiqlash oqimi, guruhga e'lonlar |
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

`BOT_TOKEN` · `DATABASE_URL` · `ADMIN_IDS` · `CHANNEL_ID` — majburiy.
`ANTHROPIC_API_KEY` — bo'sh bo'lsa vision jim o'chadi, bot ishlayveradi.
Qolganlari `.env.example` da.

---

## Uslub

- Kod izohlari va bot xabarlari **o'zbek tilida**, texnik atamalar inglizcha qoladi.
- Bot xabarlarida HTML parse mode (`<b>`, `<code>`), Markdown emas.
- Yangi funksiya qo'shilsa `test_tracker.py` ga tegishli holat qo'shilsin.
- To'liq fayl qaytaring, qismli diff emas.
