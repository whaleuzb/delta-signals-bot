# Delta Signals Bot

Telegram guruhdagi trading signallarni avtomatik kuzatib, foiz va R statistikasini
yurituvchi bot. Narx manbasi — **MEXC Spot**, hisob-kitob esa **spot (1x)**.

---

## Qanday ishlaydi

1. Adminlar botga shaxsiy chatda grafik rasmini tashlaydi.
2. Caption bo'lsa — undan o'qiladi. Bo'lmasa — Claude vision grafikdan darajalarni topadi.
3. Bot parse qilingan darajalarni **tasdiqlash tugmasi** bilan ko'rsatadi. Bir bosish —
   signal bazaga tushadi va guruhga post bo'ladi.
4. Har 45 soniyada worker MEXC'dan 1 daqiqalik shamlarni oladi va TP/SL teginishini
   tekshiradi. Yopilgan signal guruhdagi asl postga **reply** qilib e'lon qilinadi.
5. `/stats`, `/month`, `/year`, `/equity` — statistika.

---

## Muhim texnik qarorlar

**1 daqiqalik klines, `ticker/price` emas.**
Bot uxlab turgan 45 soniyada narx TP'ga tegib qaytishi mumkin. Klines'da har shamning
`high`/`low` bor, shuning uchun hech qanday teginish yo'qolmaydi. Bot uzoq vaqt o'chib
qolsa ham, qayta ishga tushganda o'tgan shamlarni ketma-ket qayta o'ynatadi.

**Futures narxi + spot hisob.**
Futures perpetual narxi spot narxdan biroz farq qiladi (basis, odatda 0.1% dan kam,
lekin kuchli volatillikda kattaroq). TradingView'da odatda `.P` juftliklari ko'riladi,
shuning uchun futures narxi grafiklaringizga mos tushadi. PnL esa leveragesiz,
sof spot foiz sifatida hisoblanadi.

**Bitta shamda ham TP ham SL.**
1 daqiqa ichida qaysi biri avval tegganini bilib bo'lmaydi. Bot konservativ yo'l
tutadi — SL hisoblanadi, signal `ambiguous` deb belgilanadi va adminga ogohlantirish
yuboriladi. Statistikangiz optimistik bo'lib qolmasligi uchun.

**Bo'lib sotish.**
Spotda odatda pozitsiya bo'lib sotiladi. `TP_ALLOCATION = [0.5, 0.3, 0.2]` —
TP1'da 50%, TP2'da 30%, TP3'da 20%. Foiz shu ulushlarga qarab tortiladi.
TP soni kam bo'lsa ulushlar avtomatik normallashadi.

**TP1 dan keyin breakeven.**
`MOVE_SL_TO_BE=true` bo'lsa TP1 olingach stop entry darajasiga ko'chadi.

**Faqat R emas, faqat foiz ham emas.**
Ikkalasi ham saqlanadi. Foiz obunachilarga tushunarli, R esa signal sifatini
haqqoniy ko'rsatadi — 20 ta signalda +50% ko'rsatib, aslida riskni 3 barobar
oshirgan bo'lish mumkin.

---

## Railway'ga deploy

1. Repo'ni GitHub'ga push qiling.
2. Railway'da yangi project → **Deploy from GitHub repo**.
3. Shu project ichiga **PostgreSQL** qo'shing.
4. Variables (`.env.example` ga qarang):

| O'zgaruvchi | Izoh |
|---|---|
| `BOT_TOKEN` | @BotFather'dan |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `ADMIN_IDS` | vergul bilan, masalan `1101182189` |
| `CHANNEL_ID` | guruh/kanal id, `-100...` bilan boshlanadi |
| `ANTHROPIC_API_KEY` | ixtiyoriy — bo'sh bo'lsa vision o'chadi |

5. Start command: `python bot.py`
6. Botni guruhga admin qilib qo'shing (post yuborish va reply uchun).

> **Diqqat:** `run_polling(drop_pending_updates=False)` — ataylab shunday.
> `True` qilinsa restart paytida kelgan xabarlar jimgina yo'qoladi.

Deploydan keyin schema avtomatik yaratiladi (`db.init()`).

---

## Signal formatlari

Hammasi ishlaydi:

```
BTCUSDT LONG entry 65000 tp 67000 68500 sl 64000

BTC/USDT
LONG
Entry: 65 000
TP1 67 000
TP2 68 500
Stop: 64 000

ADAUSDT long kirish 0.85 maqsad 0.92 0.98 stop 0.80

eth long 3200 3400 3550 3100      ← kalit so'zsiz: entry, TP lar, SL
```

Bot juftlikni MEXC Spot ro'yxati bilan tekshiradi, LONG/SHORT mantiqini
validatsiya qiladi (SL entrydan past bo'lishi va h.k.) va risk 25% dan oshsa
ogohlantiradi.

---

## Komandalar

| Komanda | Vazifa |
|---|---|
| `/stats` | umumiy statistika: winrate, jami foiz, kompaund, R, profit factor |
| `/month` | joriy oy + oxirgi 12 oy jadvali |
| `/year` | joriy yil natijalari |
| `/symbols` | juftliklar kesimida natija |
| `/equity` | equity curve + drawdown grafigi |
| `/open` | ochiq signallar, joriy foiz bilan |
| `/cancel <id>` | signalni qo'lda bekor qilish |

---

## Test

```bash
python test_tracker.py
```

Baza va internet kerak emas — dvigatel sintetik shamlarda tekshiriladi:
to'liq TP, stop, breakeven, bitta shamda TP+SL, entry to'lmagan holat,
muddat tugashi, SHORT, va bot uzilib qolgandagi ikki bosqichli qayta ishlash.

---

## Keyingi qadamlar (ixtiyoriy)

- Guruh a'zolari uchun `/stats` ni faqat oyning oxirida avtomatik post qilish
  (`job_queue.run_monthly`).
- Signal postiga "jonli" PnL ko'rsatkichi — har 5 daqiqada caption yangilanishi.
- Signal muallifi bo'yicha kesim, agar bir nechta analitik ishlasa.
- Trafik oshsa worker'ni alohida Railway service'ga ajratish.
