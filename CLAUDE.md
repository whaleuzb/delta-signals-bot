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
      `db.set_milestone()` yangilanadi. `band == 0` ham saqlanadi (bosqichdan
      chiqib ketgan holat) — shu tufayli keyinroq xuddi shu bosqichga qaytib
      kirilsa, qayta xabar beriladi (faqat "rekord"ni emas, har bir bosqich
      chegarasini kuzatadi — retracement/qayta o'sish ham bildirishnoma
      oladi, chunki bu foydalanuvchiga pozitsiyani "nazorat qilishga" ko'proq
      yordam beradi).
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
      ALL-TIME edi, alohida latent xato). `equity_chart()` esa hali ham
      argumentsiz chaqiradi (grafik har doim to'liq tarixni ko'rsatishi
      kerak — o'zgarmadi).
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
