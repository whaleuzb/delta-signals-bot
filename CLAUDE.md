# Trade Controller — loyiha konteksti

Telegram guruhdagi trading signallarni avtomatik kuzatib, foiz va R statistikasini
yurituvchi bot. Delta Community uchun.

**Stack:** Python 3.11+ · python-telegram-bot 21 · asyncpg + Railway PostgreSQL ·
MEXC Spot public API (kripto) · Twelve Data (forex, ixtiyoriy) · matplotlib ·
Claude vision (ixtiyoriy)

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
| `exchange.py` | MEXC klines/exchangeInfo, symbol normalizatsiya (kripto) |
| `forex.py` | Twelve Data klines/forex_pairs, symbol normalizatsiya (forex, ixtiyoriy) |
| `parsing.py` | caption matnidan darajalarni o'qish + validatsiya |
| `vision.py` | caption bo'lmasa grafik rasmidan o'qish (Claude tool use) |
| `tracker.py` | **asosiy dvigatel** — shamlarni qayta o'ynatib TP/SL aniqlaydi |
| `stats.py` | hisobotlar, equity curve + drawdown, `/symbols` uchun ochiq pozitsiyalarning joriy (live) foizi |
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
      ikkalasi ham bo'lsa (o'z guruhi + shaxsiy) `send_workspace_switcher()` tugmalarini
      ko'rsatadi (`switch` / `ws:<id>` callback'lar). Guruh ichida — doim o'sha
      guruhning workspace'i, tanlov yo'q.
    - **Birinchi murojaat (ikkalasi ham yo'q)** — hech narsa avtomatik yaratilmaydi.
      `send_onboarding()` ikkita tugma ko'rsatadi: "Shaxsiy jurnal" (darhol yaratadi)
      yoki "Menda guruh bor" (`on_onboard`, `onboard:` callback — botni guruhga
      qo'shish va `/setup` yozish yo'riqnomasini beradi). Avval har doim shaxsiy
      workspace sukut bo'yicha avtomatik ochilar edi — foydalanuvchi tanlamasdan;
      bu endi noto'g'ri, chunki guruh egalari ham shu yo'l bilan kelishi kerak.
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

13. **Real (kapitalga bog'liq) PnL — `workspaces.deposit` + `signals.alloc_amount`.**
    Hozirgacha barcha foiz "signal narxi qancha harakatlandi" degani edi (masalan
    "TP1'da +4%") — bu HAQIQIY portfel natijasi emas, chunki har bir savdoga qancha
    pul qo'yilgani hisobga olinmagan. Endi ixtiyoriy qo'shimcha qatlam bor:
    - `workspaces.deposit` — workspace egasining umumiy kapitali (`/depozit 1000`
      yoki "💰 Depozit" tugmasi bilan belgilanadi). `can_manage()` bo'lganlargagina
      ko'rinadi/o'zgartiriladi (guruhda — faqat admin, guruh a'zolari admin qancha
      pul bilan savdo qilayotganini bilmasligi kerak; shaxsiy workspace'da — faqat
      egasi, u yerda bu muammo emas).
    - `signals.alloc_amount` + `signals.deposit_snapshot` — har bir signal
      tasdiqlangach (`on_button`), agar workspace'da depozit belgilangan bo'lsa,
      bot ixtiyoriy ravishda "necha pul ishlatasiz?" deb so'raydi (`AWAITING_ALLOC`,
      `⏭ O'tkazib yuborish` tugmasi bilan bekor qilsa bo'ladi). `deposit_snapshot`
      — o'sha ONDAGI depozit qiymati, keyinchalik depozit o'zgarsa ham bu signalning
      real hisobi o'zgarmasin uchun saqlanadi (`sl_initial` R-hisobda saqlanganidek).
    - Real natija = `pnl_pct/100 * alloc_amount` (pulda), foizi esa shu summani
      workspace'ning JORIY depozitiga nisbatan hisoblanadi (`stats.summary`'dagi
      `deposit` parametri) — davr ichida deposit o'zgargan bo'lsa taxminiy, lekin
      amaliy jihatdan yetarli.
    - `stats.summary(..., deposit=..., show_money=...)` — `show_money` guruhda
      `can_manage(uid, ws)` orqali aniqlanadi: admin pul miqdorini ham ko'radi,
      oddiy a'zo faqat foizni. Shaxsiy workspace'da egasi doim `can_manage`, shuning
      uchun avtomatik ikkalasini ham ko'radi.
    - Depozit belgilanmagan workspace'larda bu qator umuman chiqmaydi (`deposit`
      yoki `real_pnl_money` `None` bo'lsa) — eski, faqat-foizli statistika ishlayveradi,
      hech narsa buzilmaydi. To'liq ixtiyoriy, orqaga mos (backward-compatible) qatlam.

14. **Forex — `forex.py` (Twelve Data), `signals.market` orqali kripto'dan ajratiladi.**
    `exchange.py` (MEXC) faqat kripto beradi — forex/metallar (EURUSD, XAUUSD va h.k.)
    uchun butunlay boshqa manba kerak bo'ldi.
    - `tracker.py`'dagi `provider(market)` / `bot.py`'dagi `provider_for(market)` —
      `market == 'forex'` bo'lsa `forex` modulini, aks holda `exchange` (MEXC) ni
      qaytaradi. Ikkala modul bir xil interfeys beradi: `resolve()`, `klines()`,
      `last_price()`, `close()`, bir xil `Candle` shakli — shu sabab `process()`,
      `close_now()` va bot.py'dagi barcha narx so'rovlari faqat provider tanlashni
      almashtirdi, ichki mantiq (shamlarni qayta o'ynatish, TP/SL, R) O'ZGARMADI.
    - **Bozor avtomatik aniqlanadi, admin tanlamaydi**: avval `exchange.resolve()`
      (kripto, MEXC/USDT juftlik) sinaladi, topilmasa `forex.resolve()` (Twelve
      Data'ning `/forex_pairs` ro'yxati) sinaladi. Kripto juftliklar doim `USDT` bilan
      tugagani uchun (`config.QUOTE`) va forex kodlari (EURUSD, XAUUSD) undan farqli
      bo'lgani uchun to'qnashuv ehtimoli past. Bitta joyda — `show_preview()` —
      hal qilinadi, `wizard_symbol()` ham xuddi shu tartibni ishlatadi (ikki marta
      alohida yozilgan, lekin natija bir xil bo'lishi SHART).
    - `TWELVE_DATA_API_KEY` bo'sh bo'lsa `forex.enabled()` `False` qaytaradi —
      `forex.resolve()` har doim `None`, demak forex butunlay o'chadi, kripto
      hech qanday o'zgarishsiz ishlayveradi (`ANTHROPIC_API_KEY` naqshi bilan bir xil).
    - Forex'da SHORT ochiq savdo — `ALLOW_SHORT` ogohlantirishi faqat kripto uchun
      (`draft.get("market") != "forex"` tekshiruvi), chunki forex/CFD tabiatan
      ikki tomonlama, spot-emas cheklovi yo'q.
    - **Bepul reja limiti**: Twelve Data bepul rejasi daqiqasiga ~8, kuniga ~800
      so'rov bilan cheklangan. `POLL_SECONDS=45` bilan bir nechta ochiq forex
      signal parallel bo'lsa bu limitga tez yetish mumkin — hozircha alohida
      navbat/keshlash qilinmagan (MVP), kerak bo'lsa keyinroq qo'shiladi.

15. **`signals.entry_mode` — 'market' (oddiy) vs 'limit' (standart), `tracker.py`
    ga UMUMAN TEGILMAGAN.**
    Avval har bir signal PENDING'dan boshlanib, narx `entry` darajasiga tegmaguncha
    kutar edi (limit-order mantig'i) — admin "allaqachon kirib bo'lgan" savdoni
    yozganda ham shu tekshiruv ishlar edi, ba'zan chalkashlikka sabab bo'lardi.
    - Yechim ataylab `tracker.py`'da EMAS, `db.create_signal()`'da: `entry_mode`
      `'market'` bo'lsa, signal to'g'ridan-to'g'ri `status='ACTIVE'`,
      `opened_at=now()` bilan yaratiladi (PENDING bosqichisiz). `tracker.process()`
      buni PENDING deb hech qachon ko'rmaydi — shuning uchun uning BUZILMASIN
      #1-4 dagi sinovdan o'tgan holat mashinasi bir qatorga ham tegilmadi
      (`test_tracker.py` shu sababdan o'zgarishsiz qoladi).
    - `'limit'` (standart, hozirgi xatti-harakat) — status PENDING, `tracker.py`
      narx `entry`ga tegishini kutadi, xuddi avvalgidek.
    - Tanlov ikki joyda: sehrgarda (`WIZ_MODE` bosqichi, symbol'dan keyin, side'dan
      oldin — "🎯 Oddiy" / "⏳ Limit" tugmalari) va tezkor matn/caption'da
      (`parsing.parse()` — matnda "market" yoki "bozor" so'zi bo'lsa market,
      aks holda limit; shu so'zlar juftlik nomi deb noto'g'ri o'qilib qolmasligi
      uchun symbol-exclusion ro'yxatiga ham qo'shilgan).
    - Market rejimda `tracker.py` hech qachon "OPEN" hodisasini chiqarmaydi (chunki
      status hech qachon PENDING→ACTIVE o'tmaydi), shuning uchun guruhga "▶️
      pozitsiya ochildi" xabari `poll_job` orqali emas — `on_button()`'ning o'zida,
      signal yaratilgan zahoti, sinxron yuboriladi.

16. **`/symbols` — ⏳ (ochilgan, live foiz bilan) va 🕐 (hali limitga bormagan,
    foizsiz) ikkita ALOHIDA stiker.**
    Avval ikkalasi ham bitta ⏳ badge ostida "ochiq" deb ko'rsatilardi, foizsiz.
    Endi `db.open_signals_summary()` PENDING va ACTIVE'ni ajratib qaytaradi:
    - **ACTIVE** (⏳) — allaqachon ochilgan, ishlayotgan pozitsiya. `stats.py`
      o'zi `exchange`/`forex`'dan joriy narxni so'rab, `tracker.pnl_at()` bilan
      LIVE (realizatsiya qilinmagan) foizni hisoblab ko'rsatadi — shu sabab
      `stats.py` endi narx manbalariga bog'liq (avval faqat `db` + formatlash edi,
      bu `bot.py`'dagi `open_signals_view()` bilan bir xil naqsh).
    - **PENDING** (🕐) — hali entry/limit darajasiga tegmagan, kutilmoqda. Foiz
      KO'RSATILMAYDI (hisoblash uchun asos yo'q — pozitsiya hali ochilmagan).
    - Bitta juftlikda ham yopilgan tarix, ham joriy ochiq pozitsiya bo'lsa —
      ikkalasi ham ko'rinadi: yopilganlar yig'indisi (qalin) + jarayondagi live
      foiz (kursiv, alohida). Saralash hamon faqat yopilgan `sum_pct` bo'yicha
      (o'zgarmadi) — live foiz saralashga ta'sir qilmaydi.
    - `/open` (`open_signals_view()`, `bot.py`) shu bilan bir xil `🕐`ni PENDING
      uchun ishlatadi (avval ⏳ edi — ikki joyda ikki xil ma'noni oldini olish
      uchun birlashtirildi). ACTIVE uchun esa endi bitta statik belgi emas —
      joriy live foizga qarab `📈` (foydada) yoki `📉` (zararda) ko'rsatiladi;
      narx olinmasa (kamdan-kam) `▶️` bilan orqaga qaytadi.

17. **Guruh a'zosi (egasi emas) ham DM'da statistikani ko'ra oladi — `group_viewers`
    jadvali orqali, `can_manage`/`can_view` modeliga hech narsa qo'shmasdan.**
    Onboarding'dagi "🏘 Menda yopiq guruh bor" endi ikkiga bo'linadi
    (`GROUP_ROLE_KB`): "👥 Men a'zoman" va "👑 Men egaman". Muammo: Telegram Bot
    API foydalanuvchi qaysi guruhlarga a'zoligini o'zi bilib bo'lmaydi — shuning
    uchun "a'zoman" tanlansa `send_group_picker()` barcha RO'YXATDAN O'TGAN
    guruh workspace'larini (`db.list_group_workspaces()`) tugma qilib ko'rsatadi,
    foydalanuvchi o'zinikini tanlaydi, `on_view_join()` shu guruhda haqiqatan
    (jonli) a'zoligini `get_chat_member()` bilan tekshiradi — aks holda rad etadi.
    - `group_viewers (user_id, workspace_id)` — faqat DM'da qaysi workspace'ni
      ko'rsatishni ESLAB QOLISH uchun (marshrutlash keshi, restart'dan keyin ham
      qolishi uchun DB'da, `ctx.user_data` kabi vaqtinchalik emas). Bu HAQIQIY
      ruxsat EMAS — `can_view()` har safar guruh a'zoligini jonli qayta
      tekshiradi, shuning uchun a'zolikdan chiqib ketsa yozuv qolsa ham ko'rish
      avtomatik yopiladi.
    - `resolve_workspace()` endi 2 emas N-way: owned_group + personal +
      barcha viewer_links yig'ilib, aynan bitta bo'lsa avtomatik, ko'p bo'lsa
      switcher (`send_workspace_switcher()` endi 👑 egasi / 👥 a'zo bo'lgan
      guruhlar / 🧑 shaxsiy / ➕ yana guruhga qo'shilish — barchasini ko'rsatadi).
    - Viewer sifatida kirgan workspace'da `can_manage()` avtomatik `False`
      (egasi ham, super-admin ham emas) — shuning uchun "➕ Yangi signal",
      "💰 Depozit" tugmalari va pul miqdorlari ko'rinmaydi, faqat statistika —
      qo'shimcha tekshiruv yozish shart bo'lmadi, mavjud modeldan bepul keldi.

18. **O'sish uchun 3 ta funksiya: `/top` reyting, `/taklif` referral, shaxsiy
    workspace'ga DM bildirishnoma.**
    - `/top` — joriy oy bo'yicha eng yaxshi GURUH workspace'lari reytingi
      (`db.top_workspaces()`, faqat `type='group' AND public=TRUE`). Shaxsiy
      workspace'lar reytingga umuman kirmaydi. Standart holat — `public=FALSE`
      (YASHIRIN): guruh admini o'zi `/public on` yozmaguncha hech kim ko'rmaydi.
      `/top` o'zi workspace talab qilmaydi — istalgan joyda, istalgan
      foydalanuvchi ishlata oladi (kirish nazoratisiz, ataylab — kashfiyot/o'sish
      uchun ochiq).
    - `/taklif` — har bir foydalanuvchiga shaxsiy deep-link beradi
      (`t.me/<bot>?start=ref_<uid>`). `cmd_start()` `ref_` prefiksini o'qib
      `db.add_referral()` chaqiradi (`referred_id` UNIQUE — bitta odam faqat bir
      marta "taklif qilingan" bo'ladi, birinchi havola g'olib). Hozircha faqat
      hisoblagich (`db.count_referrals()`) — mukofot mexanizmi yo'q, chunki bu
      botda to'lov tizimi yo'q (obuna whale-payment-bot'da, alohida).
    - **Shaxsiy workspace endi jim emas.** `poll_job()` avval faqat
      `type='group'` uchun xabar yuborardi, shaxsiy uchun butunlay `continue`
      qilardi. Endi `type='personal'` bo'lsa xuddi guruhdagidek barcha
      hodisalar (OPEN/TP/BE/STOP/EXPIRED) `ws["owner_id"]`ga DM qilinadi —
      hozircha yoqib/o'chirib bo'lmaydigan qatiy standart (opt-out yo'q, kerak
      bo'lsa keyinroq qo'shiladi).

19. **`/top` reytingidagi guruh nomlari — bosiladigan havola (`/havola`).**
    - `workspaces.invite_link` (nullable TEXT) — guruh admini/egasi `/havola
      <link>` bilan belgilaydi, `/havola off` bilan o'chiradi. `/depozit` va
      `/public` bilan bir xil naqsh: `get_ws_or_prompt()` → `can_manage()` →
      faqat `type='group'` → argumentsiz joriy qiymatni ko'rsatadi.
      `https://`/`http://` bo'lmasa avtomatik `https://` qo'shiladi.
    - `cmd_top()` endi har bir qatorda `r["invite_link"]` bo'lsa guruh nomini
      `<a href="...">` bilan o'raydi — bosilsa botga qo'shiladigan havolaga
      olib boradi. Bo'lmasa oddiy qalin matn (eski xatti-harakat).
    - **HTML-escaping tuzatildi.** Guruh nomi (`workspaces.name`) Telegram
      guruh sarlavhasidan (`chat.title`) kelgan — ixtiyoriy foydalanuvchi
      matni, `parse_mode=ParseMode.HTML` bilan chop etilganda maxsus belgilar
      (`<`, `>`, `&`) Telegram HTML parserini buzishi yoki (ayniqsa yangi
      `<a href>` holatida) link/markup in'ektsiyasiga olib kelishi mumkin
      edi. Endi `html.escape()` — `cmd_top()`, `cmd_public()`, `cmd_deposit()`
      va `cmd_link()` da guruh nomi va havola HTML'ga chiqarilishdan oldin
      har doim escape qilinadi.

20. **Ochiq pozitsiya foizi bosqichma-bosqich (±5%) bildirishnomasi (`milestone_job`).**
    - Alohida job (`poll_job` bilan bir xil `POLL_SECONDS` intervalda, lekin
      20 soniya siljigan boshlanish bilan — ikkalasi bir vaqtda urilib
      ketmasin uchun) — `poll_job`dan mustaqil, TP/SL kuzatuviga tegmaydi,
      faqat `db.live_signals()` orqali barcha ACTIVE signallarni olib, joriy
      narxni so'raydi va `tracker.pnl_at()` bilan joriy foizni hisoblaydi.
    - `signals.milestone_pct` (INT, ishorali, 5 ga karrali) — oxirgi xabar
      qilingan bosqich. `bot.milestone_band(pnl)` joriy foizni bosqichga
      aylantiradi (masalan +12.3% → 10, -7.1% → -5, |pnl|<5% → 0). Bosqich
      o'zgarsa (ikki tomonga ham — foyda oshsa/kamaysa, zarar chuqurlashsa/
      kamaysa) va nolga teng bo'lmasa — xabar yuboriladi (📈/📉) va
      `db.set_milestone()` yangilanadi.
    - **TUZATILDI (spam edi):** avval bosqich HAR o'zgarganda xabar ketardi va
      `band == 0` ham saqlanardi. Narx chegara atrofida tebranganda
      (+5.35% → +4.98% → +5.01%) har siklda bir xil "+5% bosqichi" xabari
      qayta yuborilardi — jonli guruhda 3 ta signal uchun soatiga o'nlab
      xabar. Mening dastlabki asosim ("qaytib kirsa qayta xabar berish
      foydali") amalda noto'g'ri chiqdi.
      Endi `milestone_should_notify(last, band)` — ratchet: xabar faqat
      NOLDAN UZOQROQ yangi bosqichga birinchi marta yetganda beriladi
      (+5 e'lon qilingach yana +5 emas, faqat +10; zararga o'tsa -5).
      `milestone_pct` faqat XABAR YUBORILGANDA saqlanadi — 0 ga hech qachon
      qaytarilmaydi. Ishora almashsa hisob qaytadan boshlanadi (bu kamida
      2 bosqichlik haqiqiy yurish).
    - Xabar yo'nalishi `poll_job` bilan bir xil: guruh workspace bo'lsa signal
      postiga reply, shaxsiy workspace bo'lsa egasiga DM.

21. **Statistika: pozitsiya hajmiga (real pul) qarab hisoblanadigan "Jami natija"/
    "Kompaund" + jarayondagi pozitsiyalar hisobotda ko'rinishi.**
    - **Muammo edi:** `/stats`dagi "Jami foiz"/"Kompaund" har bir yopilgan
      signalni xuddi BUTUN depozit o'sha savdoga kirgandek hisoblar edi (raw
      `pnl_pct`larni to'g'ridan-to'g'ri yig'ish/kompaundlash) — shuning uchun
      +210%/+437% kabi haqiqatdan uzoq, shishirilgan raqamlar chiqardi.
      Position sizing (`alloc_amount` — signalga necha pul ishlatilgani)
      butunlay hisobga olinmas edi.
    - **Yechim:** `deposit` belgilangan bo'lsa, har bir signal endi
      `pnl_pct * alloc_amount / deposit` — ya'ni o'sha savdo DEPOZITNING necha
      foizini harakatlantirgani bo'yicha tortiladi (`stats.summary()`).
      "Jami natija" — shu tortilgan foizlar yig'indisi, "Kompaund" — shularni
      ketma-ket kompaundlash (`_compound()` xuddi shu tortilgan ro'yxatga
      qo'llanadi). `deposit` belgilanmagan workspace'larda eski (raw,
      pozitsiya hajmisiz) hisob saqlanib qoladi — hech narsa buzilmaydi.
      Winrate o'zgarmadi (g'alaba/mag'lubiyat belgisi pozitsiya hajmidan
      qat'i nazar bir xil).
    - `alloc_amount` yo'q signallar tortilgan ro'yxatdan chetda qoladi (lekin
      Signallar/Winrate sonига kiraveradi). Mamurjonning "Whales Uzb"
      guruhida (workspace id=1, 1101182189 egalik qiladi) 14 ta eski yopilgan
      signalda `alloc_amount` yo'q edi — foydalanuvchining aniq so'rovi bilan
      bir martalik skript orqali har biriga 2500 dan belgilandi (faqat shu
      foydalanuvchining guruhiga tegdi, boshqa tenant'larga tegilmadi).
    - `db.equity_series()` endi `since`/`until` qabul qiladi (avval doim
      BUTUN tarixni qaytarardi — shuning uchun `/month`/`/yil`da "Jami foiz"
      to'g'ri davrga mos kelsa ham "Kompaund" sirli ravishda har doim
      ALL-TIME edi, alohida latent xato). `equity_chart()` argumentsiz
      chaqiraveradi (grafik har doim to'liq tarixni ko'rsatadi — davr bilan
      kesilmaydi), lekin #22'da o'zi ham pozitsiya hajmiga qarab hisoblanadigan
      bo'ldi.
    - **Yangi: jarayondagi (ochiq) pozitsiyalar `/stats`da ham ko'rinadi**
      (`stats._open_summary()`) — foydalanuvchi "nega guruhda ko'proq signal
      bor-ku, hisobotda faqat yopilganlar ko'rinadi" deb chalkashgani uchun.
      🕐 kutilayotgan (PENDING) soni va ⏳ ochiq (ACTIVE) pozitsiyalarning
      joriy (unrealized) foizi/puli — xuddi yopilganlar kabi `alloc_amount`ga
      tortilgan holda. Faqat davr "joriy"ga tegishli bo'lsa ko'rinadi (o'tgan
      oy/yil hisobotida yo'q — chunki ochiq pozitsiya hali qaysi davrga
      tegishli ekani noaniq).
    - **`/symbols` standart davri `/stats` bilan mos qilindi** — avval
      `/symbols` standart holatda JORIY OYni, `/stats` esa BUTUN DAVRni
      ko'rsatardi (`cmd_symbols()`/`on_menu()`'s "symbols" tarmog'i). Ikkala
      bo'lim solishtirilganda "mos kelmayapti" degan taassurot shundan edi —
      endi ikkalasi ham "Barchasi" bilan boshlanadi.

22. **Depozit endi signal yopilganda avtomatik yangilanadi + Equity grafigi
    ham pozitsiya hajmiga qarab (real balans) chiziladi.**
    - **Depozit avval statik son edi.** `/depozit` faqat qo'lda kiritilardi —
      signal yopilganda hech qachon o'zgarmasdi, shuning uchun "joriy depozit"
      haqiqiy hisob balansini aks ettirmasdi (foydalanuvchi buni to'g'ri
      payqadi: "yopilgan pnl umumiy depozitga nega qo'shilmagan?").
      `db.apply_deposit_delta()` — yangi funksiya, faqat `deposit IS NOT NULL`
      workspace'larda ishlaydi. `bot.poll_job()` endi signal TO'LIQ yopilganda
      (STOP hodisasi, yoki yakuniy TP — `e.get("closes")`) va unda
      `alloc_amount` bo'lsa, real pul natijasini (`pnl_pct/100*alloc_amount`)
      depozitga qo'shadi/ayiradi — bir marta, signal yopilgan zahoti.
    - Bir martalik skript (`reconcile_deposit.py`, ishlatilib o'chirilgan) —
      yangi avtomatik yangilanish yozilishidan OLDIN yopilgan signallarning
      real natijasini joriy depozitga bir martalik qo'shib qo'ydi (Whales Uzb:
      100 000 → 105 261.42, 14 ta signal).
    - **Equity grafigi (`stats.equity_chart()`) xuddi shu sabab bilan
      shishirilgan edi** — `pnl_pct`ni to'g'ridan-to'g'ri kompaundlab, 100'dan
      boshlanuvchi indeks chizardi (har savdo xuddi butun depozit bilan
      kirilgandek). Endi `deposit` parametri qo'shildi (`cmd_equity()`/
      `on_menu()`'s "equity" tarmog'i ikkalasi ham `ws["deposit"]`ni
      uzatadi): berilsa, egri chiziq REAL PUL balansida chiziladi — boshlang'ich
      balans joriy depozitdan shu davrdagi jami real natijani ORQAGA AYIRIB
      topiladi, keyin har savdo o'z `alloc_amount`i bilan ketma-ket qo'shiladi
      (`summary()`dagi bilan bir xil mantiq). Drawdown %'i o'zgarmadi (nisbiy
      hisob — pul yoki indeks, farqi yo'q). `deposit` yo'q workspace'larda —
      eski 100-indeksli, pozitsiya hajmisiz egri chiziq (o'zgarmagan).

23. **Equity grafigi qayta ishlangan: ikkita panel, `twinx` YO'Q.**
    - Foydalanuvchi bir necha variantdan "har savdo ustunlari + kumulyativ
      balans" ko'rinishini tanladi, lekin birinchi urinishda ustunlar va
      balans chizig'i bitta panelda ikkita y o'qi bilan (`ax.twinx()`)
      chizilgandi. **Bu chalkash edi va shunday qilmaslik kerak:** ikki o'qning
      nol nuqtasi va masshtabi bir-biriga bog'liq emas, shuning uchun chiziq
      ustunlar orasidan kesib o'tib, "+1,025 ustun turibdi-yu, chiziq nega
      pastda?" degan yolg'on taassurot berardi (foydalanuvchi: "pnl nega
      aralashib ketgan").
    - Endi ikkita alohida panel, `sharex=True`: YUQORIDA kumulyativ balans
      (o'z o'lchovida, boshlang'ich punktir chiziq bilan), PASTDA har savdo
      hissasi (nol chizig'idan yuqori/past). Bir xil x o'qi tufayli qaysi savdo
      balansni qayerga surgani baribir ko'rinadi, lekin o'lchovlar aralashmaydi.
    - x o'qi — sana emas, **savdo tartibi** (1..N). Sana bo'lsa ustunlar
      notekis joylashib bir-birining ustiga chiqib ketardi. Sana oralig'i
      sarlavha ostidagi qatorda ko'rsatiladi. Yorliq "Signal #" emas, "Savdo
      tartibi" — chunki bu ketma-ketlik raqami, `signals.id` emas.
    - Ko'p signalga chidamli: `n > 25` bo'lsa ustun ustidagi raqamlar
      chiqarilmaydi (ustma-ust tushardi), `n > 20` bo'lsa x belgilari
      siyraklashtiriladi, kenglik `n`ga qarab o'sadi (maks. 20 dyuym).
    - Ustma-ust tushishning oldini olish uchun: "cho'qqi" yozuvi faqat oxirgi
      nuqtadan kamida 3 savdo uzoqda bo'lsa chiqadi, sarlavha va uning ostidagi
      xulosa qatori `fig.suptitle()` + `fig.text()` bilan alohida y'da turadi
      (avval bitta `set_title()` ichida bo'lib, matn ustma-ust tushardi).
    - Drawdown paneli olib tashlandi (o'rniga savdo ustunlari) — lekin
      **max DD sarlavha ostidagi xulosa qatorida saqlanib qoldi**, ma'lumot
      yo'qolmasin uchun.

24. **Xavfsizlik ko'rigi natijalari (foydalanuvchi so'rovi bilan).**
    - **Qo'lda yopishda depozit yangilanmasdi (tuzatildi).** `poll_job()`
      avtomatik yopilganda `apply_deposit_delta()` chaqirardi, lekin
      `on_close_confirm()` ("vaqtidan oldin yopish" tugmasi) chaqirmasdi —
      depozit jimgina haqiqatdan uzoqlashardi. Endi ikkala yo'l ham
      yangilaydi. **Yangi yopish yo'li qo'shilsa, depozitni yangilashni
      unutmang.**
    - **Narx so'rovlari portlashi (tuzatildi).** `/stats`, `/symbols`, `/open`
      HAR ochiq signal uchun alohida `last_price()` chaqirardi — 20 ta ochiq
      signalda bitta tugma bosilishi 20 ta so'rov. Kesh ham, rate-limit ham
      yo'q edi, ya'ni istalgan guruh a'zosi buyruqni tez-tez bosib bot IP'sini
      birja limitiga uchratishi va shu bilan **kuzatuv siklini ham** (poll_job
      → klines) buzishi mumkin edi. Twelve Data'da bu ayniqsa xavfli —
      bepul reja daqiqasiga atigi 8 so'rov. Yechim: `exchange.last_price()` va
      `forex.last_price()` ga 5 soniyalik kesh. `tracker.close_now()` esa
      `fresh=True` bilan chaqiradi — u yerdagi narx savdoning YAKUNIY natijasi
      sifatida bazaga yoziladi, shuning uchun keshdan olinmasligi kerak.
    - **Eski bir martalik skriptlar o'chirildi.** `delete_test_signal.py` da
      `DELETE FROM signals WHERE symbol='BTCUSDT'` — workspace bo'yicha
      CHEKLANMAGAN, ya'ni ishga tushsa BARCHA tenant'larning ma'lumotini
      o'chirardi. Botdan chaqirilmasdi, lekin biz bir martalik skriptlarni
      aynan `startCommand`ni almashtirib ishga tushiramiz — shuning uchun
      bunday skriptni repoda qoldirish xavfli. `add_signal_manual.py`,
      `backfill_manual.py`, `fix_signal16.py`, `migrate_multitenant.py` ham
      birga olib tashlandi. **Bir martalik skript ishlatilgach darhol
      o'chirilsin.**
    - **Toza chiqqan joylar** (qayta tekshirishga hojat yo'q, lekin buzmang):
      SQL — barcha foydalanuvchi qiymatlari `$N` parametr orqali, f-string
      ichida faqat konstantalar (`CLOSED`, `config.TZ`); signal ustidan amal
      qiluvchi callback'lar (`close:`, `closeok:`, `/cancel`) signalning O'Z
      workspace'ini olib `can_manage()` tekshiradi (cached workspace'ga
      ishonmaydi) — IDOR yo'q; `on_button` tokeni `secrets` bilan generatsiya
      qilinadi va egasi tekshiriladi; `can_view()` xatolikda `False` qaytaradi
      (fail-closed); `/havola` `http(s)://` bo'lmagan sxemani majburan
      `https://` bilan almashtiradi (`javascript:` zararsizlanadi); repoda
      hardcoded sir yo'q, `.env` gitignore'da.
    - `/top` moderatsiyasi — 25-bandda hal qilindi.

25. **`/top` reytingi endi moderatsiyadan o'tadi (super-admin tasdig'i).**
    - Sabab: reytingdagi guruh nomi va `/havola` havolasi BARCHA bot
      foydalanuvchilariga ko'rinadi, ya'ni istalgan guruh egasi u yerga
      fishing havolasini qo'yishi mumkin edi.
    - `workspaces.public_approved` — egasining `public` xohishidan ALOHIDA
      ustun. `top_workspaces()` ikkalasini ham talab qiladi. `/public on`
      endi darhol chiqarmaydi, super-adminlarga tugmali so'rov yuboradi
      (`pubok:`/`pubno:` — `is_admin()` bilan himoyalangan). Rad etilsa
      `public` ham FALSE ga qaytariladi. Egaga qaror haqida DM boradi.
      `/tasdiq` — super-admin uchun kutayotganlar ro'yxati (ataylab
      `set_my_commands()` ga QO'SHILMAGAN — hammaga ko'rinmasin uchun).
    - **Eng muhim qism: `db.set_invite_link()` havola o'zgarsa tasdiqni
      BEKOR qiladi** (`public_approved AND invite_link IS NOT DISTINCT FROM $2`
      — UPDATE'ning o'ng tomonida ustun ESKI qiymatni beradi). Busiz
      moderatsiya ma'nosiz bo'lardi: zararsiz havola bilan tasdiqlanib,
      keyin uni almashtirib qo'yish mumkin edi. Bu chetlab o'tish yo'li
      haqiqiy Postgres'da test qilib yopilgani tasdiqlandi.
    - Migratsiya `DO $$ ... $$` bloki ichida: ustun BIRINCHI yaratilganda
      eski `public=TRUE` guruhlar avtomatik tasdiqlanadi (reytingdan jimgina
      tushib qolmasliklari uchun). Oddiy `UPDATE` bo'lsa MIGRATE har
      restartda bajarilgani uchun RAD ETILGAN guruhlarni qayta tasdiqlab
      yuborardi — bu ham haqiqiy bazada test qilingan.

26. **Majburiy obuna + `/admin` paneli (super-admin uchun).**
    - Yangi jadvallar: `users` (har update'da upsert — statistika uchun; avval
      foydalanuvchilar HECH QAYERDA yozilmasdi) va `required_channels`.
    - **Gate `TypeHandler(Update, gate)` da, `group=-1`** — hamma
      handlerlardan oldin ishlaydi, shuning uchun birorta yo'l ochiq qolib
      ketmaydi. Obuna bo'lmasa `ApplicationHandlerStop`. Faqat SHAXSIY chat
      gate qilinadi: guruh ichidagi oqimlar (`/setup`, signal postlari,
      `poll_job` xabarlari) to'sib qo'yilmaydi.
    - **`missing_subscriptions()` XATOLIKDA OCHIQ QOLADI (fail-open).** Bot
      kanalda admin bo'lmasa yoki kanal o'chirilgan bo'lsa `get_chat_member`
      xato beradi — bunda foydalanuvchi O'TKAZILADI. Aks holda bitta noto'g'ri
      sozlama butun botni hamma uchun qulflab qo'yardi. Shuning uchun kanal
      qo'shilayotganda botning o'sha kanalda admin ekani tekshiriladi va
      admin emas bo'lsa ochiq OGOHLANTIRISH beriladi (aks holda talab
      jimgina ishlamay turaverardi).
    - Adminlar hech qachon gate qilinmaydi — o'zini qulflab qo'yish xavfi.
    - `_sub_ok_until` — to'liq obuna bo'lganlar 5 daqiqa keshlanadi (har
      update'da N ta `get_chat_member` bo'lmasin). Obuna BO'LMAGAN holat
      ataylab keshlanmaydi — "✅ Obuna bo'ldim" tugmasi darhol ishlashi kerak.
      Kanal qo'shilganda/o'chirilganda kesh butunlay tozalanadi.
    - `/admin` — tugmali panel: 📊 statistika (foydalanuvchi/workspace/signal),
      🎁 referrallar (eng faol takliflovchilar), 📢 majburiy obuna kanallari
      (qo'shish/o'chirish), 🛡 `/top` tasdiqlari. `/admin` ham `/tasdiq` ham
      `set_my_commands()` ga QO'SHILMAGAN — oddiy foydalanuvchilarga
      ko'rinmasin uchun (`is_admin()` bilan himoyalangan, ko'rinmasligi
      qo'shimcha qatlam).
    - Kanal qo'shish: `@username` yoki kanaldan forward. Forward rasm bo'lishi
      mumkin, shuning uchun `AWAITING_CHANNEL` tekshiruvi `on_text_signal`
      va `on_photo` ikkalasida ham bor — aks holda forward qilingan post
      signal deb o'qilib ketardi.

26. **PDF hisobot (`stats.pdf_report()`, `/pdf` va statistika ostidagi tugma).**
    - `matplotlib`ning `PdfPages` backend'i ishlatiladi — reportlab/weasyprint
      kabi YANGI KUTUBXONA QO'SHILMADI (matplotlib allaqachon equity grafigi
      uchun bor edi; weasyprint bo'lsa Railway'ga og'ir tizim bog'liqliklari
      kerak bo'lardi).
    - 2 sahifa: 1) ko'rsatkichlar + balans egri chizig'i, 2) juftliklar va
      oylar kesimi. Fon ataylab OQ (bot grafiklari qorong'i) — hujjat chop
      etiladi/ulashiladi, qorong'i fon siyohni yeydi va bosmada yomon chiqadi.
    - Ruxsat: `can_view()` tekshiriladi, `show_money` esa `can_manage()`dan
      keladi — guruh a'zosi olgan PDF'da real pul summasi ko'rinmaydi, faqat
      foiz (bot ichidagi statistika bilan bir xil qoida).
    - PDF doim BUTUN davrni oladi (ekrandagi Oy/Yil tugmalari faqat matnga
      tegishli).
    - `_equity_curve()` — `equity_chart()` va `pdf_report()` uchun umumiy
      hisob; balans mantig'i ikki joyda takrorlanib, keyin bir-biridan
      ajralib ketmasligi uchun ajratildi.
    - **Yo'l-yo'lakay tuzatildi:** oy nomlari `[:3]` bilan qisqartirilganda
      "Iyun" va "Iyul" IKKALASI HAM "Iyu" bo'lib qolar edi (`monthly_table()`
      dagi eski xato). Endi matnli jadvalda `[:4]`, PDF'da to'liq nom.

27. **Admin panelida guruhlarni boshqarish, foydalanuvchilar kesimi va PDF eksport.**
    - **Guruhlar** (`adm:groups`) — ulangan har bir guruh workspace'i, yonida
      JONLI holat: `group_health()` `get_chat_member(chat_id, bot.id)` bilan
      botning guruhda hali borligini va admin ekanini tekshiradi
      (✅ ishlayapti · ⚠️ admin emas · 🚫 chiqarilgan · ⚪ biriktirilmagan).
      "Bloklash holati" aynan shu — bot guruhdan chiqarib yuborilgan bo'lsa
      darhol ko'rinadi. Tekshiruv faqat admin ro'yxatni ochganda bajariladi
      (har guruh uchun 1-2 so'rov), fon jarayonida emas.
    - **Arxivlash** (`workspaces.archived`) — o'chirish EMAS, ataylab
      qaytariladigan: arxivlangan guruh `/top` reytingida, "men a'zoman"
      ro'yxatida va kuzatuvchi ulanishlarida ko'rinmaydi, lekin signal tarixi
      butunlay saqlanadi. O'chirish `signals.workspace_id` FK'si tufayli
      baribir tarixni yo'q qilishni talab qilardi — arxiv xavfsizroq.
    - **Foydalanuvchilar** (`adm:users:<offset>`) — sahifalangan ro'yxat,
      har birida rol nishonlari: 🧑 shaxsiy jurnal · 👑 guruh egasi ·
      👥 yopiq guruhga ulangan · 🎁 taklif qilgan. Karta ichida (`adm:usr:`)
      egalik qiladigan va ulangan guruhlar ro'yxati chiqadi.
    - **Jonli a'zolik tekshiruvi** (`adm:usrchk:`) — `group_viewers` faqat
      foydalanuvchi guruhni TANLAGANINI bildiradi; hozir haqiqatan a'zomi
      yo'qmi faqat Telegram aytadi. Shuning uchun bu alohida tugma ostida,
      ataylab talab bo'yicha: barcha foydalanuvchi × guruh juftligini
      avtomatik tekshirish juda ko'p so'rov bo'lardi.
    - **PDF eksport** — `stats.pdf_table_report()` umumiy ko'p sahifali
      monospace jadval generatori (guruhlar va userlar ro'yxati ikkalasi
      shundan foydalanadi, sahifa to'lganda avtomatik yangisi ochiladi).

28. **`/yordam` — bot ichidagi yo'riqnoma + tashqi rasmli qo'llanma.**
    - Sabab: foydalanuvchilarning katta qismi guruh ulash va signal kiritishda
      qotib qolardi. Eng ko'p uchraydigan xato — signalni GURUHGA yozish
      (bot faqat shaxsiy chatda qabul qiladi).
    - Yordam matni ataylab bot ICHIDA to'liq saqlanadi (`HELP_TOPICS`) —
      odam qotib qolgan paytda tashqi sahifaga o'tishni xohlamaydi. Havola
      qo'shimcha, almashtirish emas.
    - 4 ta mavzu: guruh ulash · signal kiritish · limit/market farqi ·
      ko'p uchraydigan xatolar. Bosh menyuda "❓ Yordam" tugmasi,
      `/yordam` va `/help` buyruqlari (`/help` avval bosh menyuni ochardi).
    - `config.GUIDE_URL` — rasmli qo'llanma havolasi, env orqali
      o'zgartiriladi (qo'llanma ko'chirilsa kodga tegish shart emas).
      Bo'sh qilinsa tugma ko'rsatilmaydi.
    - Yordam matnlari Telegram HTML sifatida tekshirilgan (faqat ruxsat
      etilgan teglar, escape qilinmagan `<`/`>` yo'q, 4096 belgidan qisqa) —
      noto'g'ri teg butun xabarni yuborilmay qoldiradi.

29. **Qo'llanma — Telegraph maqolasi, veb-sahifa emas.**
    - Avval qo'llanma oddiy veb-sahifa (Claude artifact) edi — foydalanuvchidan
      LOGIN so'rardi va bu to'siq bo'ldi. Telegraph esa Telegram ichida darhol
      ochiladi, login talab qilmaydi va guruhga qadab qo'yish mumkin.
    - `guide.py` — matn Telegraph node ko'rinishida. Telegraph faqat cheklangan
      teglarni qabul qiladi (h3/h4, p, ul/ol/li, b, i, code, pre, blockquote,
      aside, hr, a) — **h1/h2 va JADVAL yo'q**, shuning uchun kalit so'zlar
      jadvali ro'yxatga aylantirilgan.
    - `publish_guide.py` — chop etadi va `getPage` bilan tekshiradi.
      `TELEGRAPH_TOKEN` + `TELEGRAPH_PATH` env bo'lsa `editPage` ishlatiladi:
      YANGI sahifa yaratilmaydi, **havola o'zgarmaydi** — guruhga qadalgan
      xabar eskirmaydi. Ikkalasi Railway env'ida saqlangan.
    - Chop etish Railway'dan bajariladi: bu sandbox'dan `api.telegra.ph` ga
      tarmoq ruxsati yo'q (tashkilot siyosati, 403).

30. **Yo'riqnoma rasmlari — botning o'zi yuboradi, tashqi hosting yo'q.**
    - Rasmlar HTML/CSS dan **Chromium (Playwright) skrinshoti** bilan
      yasalgan (`guide_images/_manba.html` — manba, tahrirlab qayta render
      qilish mumkin). matplotlib bunday maket uchun yaroqsiz edi.
    - **Telegraph rasm yuklashni QABUL QILMAYDI.** Ikki xato ketma-ket
      chiqdi: avval `api.telegra.ph/upload` → `UNKNOWN_METHOD` (yuklash
      `api.` prefiksisiz boshqa hostda), keyin to'g'ri manzilda ham
      `Unknown error` — xizmat anonim yuklashni cheklab qo'ygan. Chetlab
      o'tilmadi.
    - Yechim: rasmlar **bot orqali** yuboriladi (`send_help_photo`).
      Tashqi hosting kerak emas, login yo'q, rasm foydalanuvchi chatida
      qolib ketadi. Telegram `file_id` keshlanadi (`_photo_ids`) — bir marta
      yuklanadi, keyin qayta ishlatiladi.
    - `guide.py` dagi `_fig()` baribir qoldirildi: rasm URL'i bo'lmasa figure
      tashlab ketiladi, ya'ni maqola matn bilan buzilmasdan chop etiladi.
      Kelajakda rasm hosting topilsa, faqat URL berish kifoya.
    - `.gitignore` da `*.png` bor edi — `!guide_images/*.png` istisnosi
      qo'shildi, aks holda rasmlar repoga tushmasdi.

31. **Broadcast (`/admin` → 📣 Broadcast).**
    - **`copy_message` ishlatiladi, `send_message` emas** — admin xabarni
      qanday yozsa (matn, rasm, video, formatlash) shundayligicha ketadi va
      "forwarded from" yozuvi chiqmaydi. Aks holda har bir tur uchun alohida
      kod yozish kerak bo'lardi.
    - **Tezlik ataylab cheklangan: 20 xabar/sekund** (`BROADCAST_PER_SEC`).
      Telegram ~30/sek ruxsat beradi; undan oshsa flood-limit tushadi va bot
      VAQTINCHA JAZOLANADI — ya'ni signal xabarlari ham yetmay qoladi.
    - `RetryAfter` tutilganda kutiladi va **o'sha odamga qayta urinadi**
      (tashlab ketilmaydi — aks holda xabar unga yetmasdi).
    - `Forbidden` (bot bloklangan) → `users.blocked = TRUE`, keyingi
      broadcast'da o'tkazib yuboriladi. Odam qaytib kelsa `upsert_user()`
      uni avtomatik FALSE ga qaytaradi (u har update'da ishlaydi).
    - **Job sifatida ishlaydi** (`job_queue.run_once`) — yuborish uzoq
      davom etsa ham bot javob berishda davom etadi.
    - Tasdiqlash bosqichi majburiy: hammaga ketgan xabarni qaytarib
      bo'lmaydi, shuning uchun avval nechta odamga ketishi va taxminiy vaqt
      ko'rsatiladi.

32. **Jonli narx chaqiruvlari himoyalandi (to'liq tekshiruvda topildi).**
    - Muammo: `last_price()` faqat status != 200 bo'lsa None qaytarardi, lekin
      TARMOQ XATOSI (timeout, connection reset) yuqoriga otilardi. Chaqiruv
      joylarining 6 tadan 5 tasi himoyasiz edi — ya'ni birjadagi bir soniyalik
      uzilish `/stats`, `/symbols`, `/open` va signal ko'rinishini BUTUNLAY
      yiqitardi.
    - Bu ayniqsa bema'ni edi, chunki **yopilgan signallar statistikasi jonli
      narxga umuman bog'liq emas** — foydalanuvchi bekorga butun hisobotini
      yo'qotardi.
    - Yechim: `bot.safe_last_price()` va `stats._safe_price()` — xatoni
      log qilib None qaytaradi. Chaqiruvchilar None'ni allaqachon to'g'ri
      ishlatardi ("narx olinmadi" deb ko'rsatadi), shuning uchun degradatsiya
      silliq.
    - `tracker.close_now()` ham o'raldi: endi None qaytaradi va chaqiruvchi
      "Yopib bo'lmadi (narx olinmadi)" degan ANIQ xabar beradi, umumiy xato
      ekrani o'rniga. Signal ochiqligicha qoladi — hech narsa buzilmaydi.
    - Tekshirish usuli: birja mavjud bo'lmagan muhitda (sandbox proksisi
      bloklaydi) `/stats` chaqirildi — avval yiqilardi, endi yopilgan
      statistika to'liq chiqadi va faqat ochiq pozitsiya qatori
      "narx olinmadi" deb degradatsiya qiladi.

33. **Yopilgan signal uchun real narx grafigi (`chart.py`, `stats.signal_chart` emas —
    alohida modul).**
    - Foydalanuvchi so'rovi: signal yopilganda faqat matn kelayotgan edi —
      "tiker nomi va kirish/chiqish nuqtasini aniq yozsa o'zi grafik topib
      rasmda ko'rsatib guruhga yubora oladimi" degan savolga javoban.
    - Bannner-reklama emas, **haqiqiy dalil** yasashga qaror qilindi: signal
      ochilgan-yopilgan oralig'idagi haqiqiy 1m shamlar (`tracker.provider(
      market).klines()` — kuzatuvda ishlatilayotgan xuddi shu chaqiruv,
      yangi so'rov turi yo'q) ustiga Entry/SL/TP chiziqlari va aniq chiqish
      nuqtasi chizib beriladi. Forex tomonida Twelve Data bepul rejasi
      daqiqasiga 8 so'rov bilan cheklangani uchun **pagination yo'q** —
      bitta `klines(limit=...)` chaqiruvi, agar butun oraliqni qamrab
      olmasa grafik shunchaki qisqaroq chiqadi (hech qachon qo'shimcha
      so'rov otilmaydi).
    - Rasm chetiga workspace nomi (pastki chap) va bot havolasi —
      `t.me/{ctx.bot.username}` (pastki o'ng) — qo'yiladi: bunday natija
      rasmlari ko'pincha guruhdan tashqarida qayta ulashiladi, shu payt ham
      qaysi guruh va qaysi bot ekanligi ko'rinib tursin degan talab bilan.
    - `poll_job()`dagi STOP va yakuniy TP hodisalarida ishlatiladi:
      `chart.signal_chart()` muvaffaqiyatli bo'lsa `send_photo(caption=txt)`,
      aks holda (shamlar yetarli emas, birja javob bermadi va h.k.) jim
      tarzda avvalgi `send_message(txt)`ga qaytiladi — hech qachon
      natija xabarining o'zi yo'qolmaydi.
    - Qo'lda yopish (`on_close_confirm` → `tracker.close_now()`, "vaqtidan
      oldin yopish") ham xuddi shunday grafik oladi — foydalanuvchi savoli:
      "vaqtidan oldin yopsam ham natijasi ko'rinadimi?". `close_now()`
      bazaga yozib bo'lgach `db.get_signal()` bilan yangilangan yozuv qayta
      o'qiladi (closed_at/exit_price/pnl_pct endi to'ldirilgan), keyin xuddi
      avtomatik yopilishdagi bir xil `chart.signal_chart()` chaqiriladi.
      CANCELLED holat (PENDING entryga tegmay bekor qilingan) bundan
      mustasno — u yerda hech qachon narx harakati bo'lmagan, grafik
      ma'nosiz.
    - `tracker.py`ga tegilmadi — faqat `tracker.provider()` funksiyasi
      qayta ishlatildi, shuning uchun `test_tracker.py` qayta ishga
      tushirilib (9/9 holat o'zgarishsiz), tracker buzilmagani tasdiqlandi.

34. **Signal e'lon qilishda ikki tugma: o'z rasming yoki bot grafigi
    (`chart.setup_chart()`).**
    - Foydalanuvchi savoli: "signal kiritayotganimda ham rasm yuborish shart
      bo'lmasin? Yoki ikki tugma — biri rasm yuborish, ikkinchi bot o'zi
      topishi". Rasm avval ham majburiy EMAS edi (matnli signal to'liq
      ishlardi), lekin buni tugmadan ko'rish mumkin emasdi.
    - Endi ko'rish oynasida (`show_preview`) ikki tasdiqlash tugmasi:
      `ok:` — "🖼 Mening rasmim bilan" (rasm biriktirilgan bo'lsa) yoki
      "📝 Rasmsiz e'lon"; `okc:` — "📈 Bot grafigi bilan". Handler patterni
      `^(okc|ok|no|ed):` — `okc` birinchi turishi shart emas (regex `ok`
      alternativi ":" ni talab qilgani uchun "okc:" ga mos kelmaydi), lekin
      aniqlik uchun oldinga qo'yildi.
    - `chart.py` ikkala holatga umumiy `_render()` atrofida qayta tuzildi:
      `setup_chart()` — e'lon paytidagi oxirgi ~150 sham + rejalashtirilgan
      darajalar (chiqish nuqtasi yo'q, o'ng yuqorida "kutilmoqda"/"ochildi"),
      `signal_chart()` — yopilgandagi haqiqiy yo'l. Guruhda ikkala rasm bir
      xil uslubda ko'rinadi.
    - Zaxira zanjiri: bot grafigi chizilmasa → foydalanuvchi rasmi →
      oddiy matn. Signal hech qachon yuborilmay qolmaydi.
    - Grafik `db.create_signal()` dan KEYIN chiziladi, chunki sarlavhaga
      haqiqiy `#id` kerak.

35. **Xato signalni hisobdan chiqarish (`signals.excluded`, `/tuzat`).**
    - Foydalanuvchi so'rovi: "xato signal kiritsam yopilganidan keyin uni
      o'chira olmayapman... umumiy statistikani tahrirlash imkonini ber".
    - **Raqamlarni qo'lda tahrirlash ATAYLAB QILINMADI.** Agar `pnl_pct`
      ni qo'ldan yozish mumkin bo'lsa, statistika hech kim tekshira
      olmaydigan qo'lyozmaga aylanadi va `/top` reytingi ma'nosini
      yo'qotadi. Buning o'rniga noto'g'ri signalning O'ZI hisobdan
      chiqariladi — qolgan har bir raqam haqiqiy bozor ma'lumotidan
      hisoblanaveradi.
    - O'chirish emas, BAYROQ (`excluded`): qator saqlanadi, guruhdagi eski
      xabar bilan bog'liqlik buzilmaydi va istalgan payt qaytarish mumkin.
    - Filtrlangan joylar (hammasida `AND NOT excluded`): `period_stats`,
      `monthly_breakdown`, `equity_series`, `top_symbols`, `top_workspaces`,
      `platform_stats`, `admin_list_groups`, va **`live_signals` +
      `open_signals_summary`** — oxirgi ikkisi muhim: chiqarilgan OCHIQ
      signal kuzatuvdan ham chiqadi, ya'ni xato signal guruhga TP/SL
      xabarlari yubormay qo'yadi.
    - Depozit ham to'g'rilanadi: `alloc_amount` bilan yopilgan signal
      chiqarilsa unga qo'shilgan pul qaytarib olinadi, qaytarilsa yana
      qo'shiladi (`on_fix`). Aks holda depozit jimgina noto'g'ri bo'lardi.
    - `/tuzat` — faqat super-admin, `set_my_commands` ro'yxatiga
      qo'shilmagan. `/tuzat ARIAUSDT` — bitta juftlik bo'yicha filtr.
      Ro'yxatda chiqarilganlar ham ko'rinadi (🚫 belgisi bilan) — qaytarish
      uchun ular ham kerak.
    - Haqiqiy Postgres'da tekshirildi: chiqarish/qaytarishda `period_stats`,
      `top_symbols`, `equity_series`, `live_signals`, `platform_stats` va
      depozit — hammasi to'g'ri o'zgardi.

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
`TWELVE_DATA_API_KEY` — bo'sh bo'lsa forex jim o'chadi, kripto ishlayveradi (#14).
`CHANNEL_ID`/`CHANNEL_TOPIC_ID` endi YO'Q — har bir guruh o'zini `/setup` bilan
ro'yxatdan o'tkazadi (#12 ga qarang). Qolganlari `.env.example` da.

---

## Uslub

- Kod izohlari va bot xabarlari **o'zbek tilida**, texnik atamalar inglizcha qoladi.
- Bot xabarlarida HTML parse mode (`<b>`, `<code>`), Markdown emas.
- Yangi funksiya qo'shilsa `test_tracker.py` ga tegishli holat qo'shilsin.
- To'liq fayl qaytaring, qismli diff emas.
