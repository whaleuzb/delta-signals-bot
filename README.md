# Trade Controller

Telegram guruhdagi trading signallarni avtomatik kuzatib, foiz va R statistikasini
yurituvchi bot. Narx manbasi — kripto uchun **MEXC Spot**, forex/metallar uchun
**Twelve Data** (ixtiyoriy, `TWELVE_DATA_API_KEY` bo'lsa yoqiladi). Signal kiritishda
qaysi bozor ekani avtomatik aniqlanadi — alohida tanlash shart emas.

Multi-tenant: bitta bot bir nechta mustaqil **workspace**ga xizmat qiladi — istalgan
yopiq guruh o'zini `/setup` bilan ro'yxatdan o'tkazib, o'z admini boshqaradigan alohida
statistika olishi mumkin; istalgan odam esa shaxsiy (hech qayerga post bo'lmaydigan)
savdo jurnali sifatida foydalanishi mumkin. Workspace'lar bir-birining ma'lumotini
ko'rmaydi.

---

## Qanday ishlaydi

1. Botga birinchi marta shaxsiy yozganda, u "Shaxsiy jurnal" yoki "Menda guruh bor"
   deb so'raydi. Guruh tanlansa — botni o'z guruhingizga admin qilib qo'shib, o'sha
   yerda `/setup` yozish kerak (shu guruh uchun mustaqil workspace ochiladi, bitta
   admin — bitta guruh). Shaxsiy tanlansa — darhol shaxsiy jurnal ochiladi.
2. Workspace admini botga shaxsiy chatda grafik rasmini tashlaydi (yoki `/new` — bosqichma-
   bosqich sehrgar).
3. Caption bo'lsa — undan o'qiladi. Bo'lmasa — Claude vision grafikdan darajalarni topadi.
4. Bot parse qilingan darajalarni **tasdiqlash tugmasi** bilan ko'rsatadi. Bir bosish —
   signal bazaga tushadi; guruh workspace bo'lsa — guruhga ham post bo'ladi (shaxsiy
   workspace'da post bo'lmaydi, faqat jurnalga yoziladi).
5. Har 45 soniyada worker MEXC'dan 1 daqiqalik shamlarni oladi va TP/SL teginishini
   tekshiradi. Yopilgan signal guruhdagi asl postga **reply** qilib e'lon qilinadi.
   Alohida job ochiq pozitsiyalar joriy foizini har ±5% bosqichda (foydada ham,
   zararda ham) kuzatib, bosqich o'zgarganda bildirishnoma yuboradi.
6. `/stats`, `/month`, `/year`, `/symbols`, `/equity` — statistika. Guruh workspace'da
   shu guruh a'zolariga ochiq, shaxsiy workspace'da faqat egasiga.

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

**"Jami natija" pozitsiya hajmiga qarab hisoblanadi.**
Depozit (`/depozit`) belgilangan bo'lsa, har bir signal necha pul bilan
kirilgani (`alloc_amount`) bo'yicha depozitga nisbatan tortiladi — signal
+30% ko'rsatgani depozitning +30% o'sishini anglatmaydi, agar shu savdoga
depozitning faqat bir qismi ishlatilgan bo'lsa. Depozit belgilanmagan
workspace'larda — eski, pozitsiya hajmisiz narx-harakati foizi ko'rsatiladi.
`/equity` grafigi ham xuddi shu mantiqda — deposit bo'lsa REAL pul balansida
chiziladi, bo'lmasa eski 100-indeksli egri chiziq ko'rsatiladi. Signal
yopilganda depozit o'zi ham avtomatik yangilanadi (real natija qo'shiladi/
ayiriladi) — qo'lda hisoblash shart emas.

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
| `ADMIN_IDS` | vergul bilan, masalan `1101182189` — super-adminlar (barcha workspace'ga kirish) |
| `ANTHROPIC_API_KEY` | ixtiyoriy — bo'sh bo'lsa vision o'chadi |

5. Start command: `python bot.py`
6. Botni guruhga admin qilib qo'shing (post yuborish va reply uchun), so'ngra guruh
   ichida `/setup` yozing — `CHANNEL_ID` kabi env o'zgaruvchi endi kerak emas, har bir
   guruh o'zini shu buyruq bilan ro'yxatdan o'tkazadi.

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

BTCUSDT LONG market entry 65000 tp 67000 sl 64000   ← "market" — darhol ochiq
```

Bot juftlikni MEXC Spot (yoki forex bo'lsa Twelve Data) ro'yxati bilan tekshiradi,
LONG/SHORT mantiqini validatsiya qiladi (SL entrydan past bo'lishi va h.k.) va
risk 25% dan oshsa ogohlantiradi.

**Kirish rejimi:** standart holatda ("limit") signal narx `entry` darajasiga
tegmaguncha kutadi. Matnda `market` yoki `bozor` so'zi bo'lsa (yoki sehrgarda
"🎯 Oddiy" tanlansa) — signal darhol "ochiq" deb hisoblanadi, kutmasdan.

---

## Komandalar

| Komanda | Vazifa |
|---|---|
| `/stats` | umumiy statistika: winrate, jami foiz, kompaund, R, profit factor |
| `/month` | joriy oy + oxirgi 12 oy jadvali |
| `/year` | joriy yil natijalari |
| `/symbols` | juftliklar kesimida natija |
| `/equity` | equity curve + drawdown grafigi |
| `/pdf` | statistikani PDF hisobot sifatida yuklab olish |
| `/open` | ochiq signallar, joriy foiz bilan |
| `/cancel <id>` | signalni qo'lda bekor qilish |
| `/setup` | (faqat guruhda, admin) shu guruh uchun workspace ochish |
| `/new` | signal kiritish sehrgari (bosqichma-bosqich) |
| `/depozit [summa]` | (admin/egasi) umumiy kapitalni ko'rish yoki belgilash — real pul/pozitsiya hajmiga bog'liq natija shundan hisoblanadi |
| `/top` | joriy oydagi eng yaxshi (ochiq) guruhlar reytingi |
| `/public on\|off` | (admin/egasi) guruhni /top reytingiga so'rov yuborish/olib tashlash — moderator tasdig'idan keyin ko'rinadi |
| `/havola <link>\|off` | (admin/egasi) guruhning taklif havolasi — /top da guruh nomi shunga link bo'ladi |
| `/taklif` | do'stlaringizni taklif qilish uchun shaxsiy havola |
| `/yordam` | yo'riqnoma: guruh ulash, signal kiritish, xatolar |
| `/sahifa` | guruhning ochiq natijalar sahifasi (veb havola) |
| `/tuzat [JUFTLIK]` | (super-admin) xato kiritilgan signalni statistikadan chiqarish yoki qaytarish |

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
