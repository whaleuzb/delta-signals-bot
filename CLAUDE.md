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

36. **Juftlikni tanib olish — nomzodlar ro'yxati (`parsing.symbol_candidates`,
    `bot.resolve_symbol`).**
    - Shikoyat: "btcusdt, btc, Btc yozuvlarini o'qimayapti, faqat BTCUSDT
      qabul qilyapti". Tekshirganda **registr aybdor emasligi** aniqlandi —
      parser ham, `normalize()` ham hammasini katta harfga o'girardi.
      Ikkita boshqa nuqson bor edi:
      1. **Parser matndagi BIRINCHI so'zni juftlik deb olardi.** Shu sabab
         "Yangi signal: btc long..." da juftlik `Yangi` bo'lib chiqar va
         "❌ Yangi topilmadi" chiqardi. Foydalanuvchiga bu "faqat toza
         BTCUSDT ishlaydi" bo'lib ko'rinadi, chunki toza qatorda birinchi
         so'z chindan ham juftlik bo'ladi. Aynan shu asosiy sabab.
      2. `exchange.normalize()` bo'sh joy va `_` ni tashlamasdi:
         "BTC USDT" va "BTC_USDT" rad etilardi.
    - Yechim: matndan bitta so'zni TAXMIN QILISH o'rniga nomzodlar ro'yxati
      yig'iladi va tanlov BIRJAGA qoldiriladi — ro'yxatida bori o'sha.
      Avval hamma nomzod kripto, keyin forex bo'yicha sinaladi. Qimmat emas:
      ikkala manba juftliklar ro'yxatini 1 soatga keshlaydi, ya'ni bu
      to'plamda qidiruv, tarmoq so'rovi emas.
    - `_NOT_SYMBOL` ro'yxati endi faqat tezlik uchun — to'liq bo'lishi shart
      emas, chunki begona so'z baribir birjada topilmaydi.
    - `resolve_symbol()` uch joyda ishlatiladi: `show_preview`,
      `wizard_symbol`, `/tuzat`. Birja ro'yxatini olishda xato bo'lsa
      `try/except` bilan tutiladi (avval bu yerda himoya yo'q edi).
    - `valid_symbols()` status filtri yumshatildi ("1" | "ENABLED" |
      "TRADING"): MEXC bir kun yozilishni o'zgartirsa butun ro'yxat bo'shab
      qolib BARCHA signallar rad etilishi mumkin edi.
    - 23 ta holatda tekshirildi (registr, ajratgichlar, oldidagi begona
      so'zlar, forex, topilmasligi kerak bo'lgani).

37. **Grafik timeframe'i (`signals.chart_tf`, `tf:` tugmalari).**
    - Muammo: grafik doim 1m shamlarda chizilardi, holbuki signal 15m yoki
      4h asosida berilgan bo'lishi mumkin — masshtab mos kelmasdi.
    - "📈 Bot grafigi bilan" bosilganda endi timeframe so'raladi
      (1m/5m/15m/1h/4h/1d). Tanlov `signals.chart_tf` ga yoziladi va
      **yopilgandagi natija grafigi ham AYNAN shu tf'da** chiziladi.
    - **`tracker.py` ga TEGILMADI va tegilmasligi ham kerak**: u
      `klines()` ni `tf` bermasdan chaqiradi, ya'ni standart `1m` da qoladi.
      Yirikroq shamda TP/SL teginishi sham ichida yashirinib qolardi —
      timeframe faqat KO'RSATISH uchun, hisob uchun emas.
    - `exchange`/`forex.klines()` ga `tf` parametri qo'shildi (standart
      "1m", shuning uchun eski chaqiruvlar o'zgarmadi). MEXC 1 soatni
      "60m", Twelve Data "1h" deb ataydi — moslashtirish jadvallari
      har bir modulda. Twelve Data kunlik shamda faqat sanani qaytaradi
      ("2026-08-24") — sana formati shunga qarab tanlanadi.
    - `chart.py` daqiqa emas, **SHAM SONI** bo'yicha oyna hisoblaydi
      (`SETUP_BARS=120`). Yopilgan signalda savdo tanlangan tf'da bir
      necha shamgina davom etgan bo'lsa (4h grafikda 40 daqiqalik savdo)
      oyna orqaga cho'ziladi — kamida ~40 sham (`MIN_BARS`), aks holda
      grafik bo'm-bo'sh ko'rinardi.
    - `chart_tf` NULL (eski signallar, yoki foydalanuvchi o'z rasmini
      tanlagan holat) → `DEFAULT_TF = "15m"`.
    - Oqim: `okc:` endi darhol e'lon qilmaydi, `tf_kb()` ni ko'rsatadi;
      `tf:<token>:<tf>` tasdiqlaydi; `bk:<token>` orqaga qaytaradi.
      Handler patterni `^(okc|ok|no|ed|tf|bk):`.
    - 14 ta holatda tekshirildi (har bir tf, standartga tushish, natija
      grafigi tf'i, eski signal, qisqa savdo yirik tf'da).

38. **"Yangi signal" tugmasi o'lik qolib ketardi (`allow_reentry`).**
    - Shikoyat: "yangi signal tugmasi ishlamayapti" — hech qanday xabar ham,
      xato ham chiqmasdi.
    - Sabab: `ConversationHandler(allow_reentry=False)` (standart). Sehrgar
      YARIM YO'LDA tashlab ketilgan bo'lsa suhbat OCHIQ qoladi va PTB
      entry_point'larni umuman tekshirmaydi — tugma bosilishi jimgina
      yo'qoladi. `conversation_timeout=900` tufayli bu 15 daqiqa davom
      etardi.
    - Ayni holatga tushishning eng oson yo'li: `/bekor`. U global
      `CommandHandler` edi, fallback EMAS — ya'ni `user_data["wiz"]` ni
      tozalardi, lekin suhbatni tugatmasdi. Natijada suhbat ochiq qolar,
      ustiga `wiz` yo'qolgani uchun keyingi bosqich `KeyError` berardi.
    - Tuzatish: `allow_reentry=True`, `/bekor` fallback sifatida ham
      qo'shildi, va har bir bosqichga `_wiz_or_end()` qo'riqchisi —
      holat yo'qolgan bo'lsa KeyError o'rniga tushunarli xabar.
    - Diagnostika usuli (kelajakda foydali): `main()` ni `run_polling`
      patch qilib chaqirib, `ConversationHandler.check_update()` ni sun'iy
      `Update` bilan sinash — tarmoqsiz, qaysi handler ushlashini aniq
      ko'rsatadi. Shu bilan avval marshrutlash to'g'riligi tasdiqlandi
      (`newsig` → ConversationHandler), keyin ochiq suhbatda ISHLAMASLIGI
      isbotlandi.

39. **Signal kiritish oqimi: 3 tugma → YAKUNIY KO'RISH → tasdiqlash.**
    - Foydalanuvchi so'rovi: uchta tugma (rasm yuklash / bot grafigi /
      rasmsiz) va "hammasi kiritilgandan keyin bot avval RASMNI o'ziga
      yuborsin, tasdiqlash tugmasi chiqsin".
    - 1-bosqich (`preview_kb`): `pic:` — 🖼 Rasm yuklash (rasm allaqachon
      biriktirilgan bo'lsa "Yuborgan rasmim bilan" va to'g'ridan 2-bosqichga),
      `okc:` — 📈 Bot grafikni aniqlasin (→ `tf_kb`), `nopic:` — 📝 Rasmsiz.
    - 2-bosqich (`send_final_preview`): signal guruhga QANDAY chiqishi AYNAN
      shu ko'rinishda avval muallifga yuboriladi, ostida ✅ Tasdiqlash.
      `go:` bosilgandagina baza yozuvi yaratiladi va guruhga ketadi.
    - **Rasm ikki marta yuklanmaydi**: ko'rish uchun yuborilgan rasmning
      Telegram qaytargan `file_id` si (`ready_file_id`) saqlanadi va guruhga
      o'sha yuboriladi. Ya'ni guruh AYNAN ko'rilgan rasmni oladi.
    - `setup_chart()` dan `sig_id` OLIB TASHLANDI: grafik endi baza yozuvidan
      OLDIN, ko'rish uchun chiziladi — raqam hali mavjud emas. Raqam xabar
      matnida (`draft_text(d, sig_id)`) baribir ko'rinadi.
    - Grafik chizilmasa oqim to'xtamaydi: ogohlantiradi va rasmsiz
      tasdiqlashni taklif qiladi.
    - `AWAITING_SIGNAL_PHOTO` — "Rasm yuklash" bosilgandan keyingi rasm
      YANGI signal deb o'qilmasligi uchun (`on_photo` da eng oldin
      tekshiriladi). `/bekor` uni ham tozalaydi.
    - Handler patterni: `^(okc|nopic|pic|go|no|ed|tf|bk):` — eski `ok:`
      olib tashlandi.
    - 17 ta holatda tekshirildi (uchala yo'l, rasm biriktirish, file_id
      qayta ishlatish, grafik chizilmagan holat).
    - **Sehrgar (`/new`) ham shu oqimga keltirildi**: avval u BIRINCHI qadamda
      rasm so'rardi ("1/6 — Grafik rasmni yuboring"), ya'ni 3 tugma umuman
      chiqmasdi va foydalanuvchi "chiqmadiku?" deb yozdi. `WIZ_PHOTO` holati,
      `wizard_photo`/`wizard_skip_photo` va `WIZ_PHOTO_KB` butunlay olib
      tashlandi — endi sehrgar juftlikdan boshlanadi (1/6 … 6/6, raqamlar
      nihoyat ketma-ket) va rasm tanlovi oxirida, `show_preview()` da
      chiqadi. Ikkala yo'l (tez matnli va sehrgar) endi bir xil tugaydi.
    - **Daraja yorliqlari grafik ICHIGA ko'chirildi** (foydalanuvchi: "grafik
      juda chetga tiqilib qolgan"). Avval "Entry 71,000" kabi yorliqlar
      o'qlar TASHQARISIDA turardi va `right=0.86` bilan o'zi uchun
      kenglikning ~15% ini zaxiralab, shamlarni chapga siqardi. Endi ular
      o'ng chekkada, ichkarida, yarim shaffof fon (`bbox`) ostida —
      `right=0.985`, ya'ni shamlar deyarli butun kenglikni egallaydi.
    - Keyin foydalanuvchi TradingView skrinshotini yubordi: oxirgi shamdan
      KEYIN bo'sh joy qolishi kerak ("right offset"). Birinchi urinishda
      shamlar o'ng chekkaga taqalib, yorliqlar ular USTIGA tushgan edi.
      Endi `right_pad = max(8, len(candles) * 0.14)` va
      `xlim = (-1.5, len(candles) - 1 + right_pad)` — yorliqlar aynan shu
      bo'shliqqa tushadi va narx harakatini to'smaydi.


40. **To'liq tekshiruv (foydalanuvchi so'rovi) — 4 ta kamchilik topildi va
    tuzatildi.**
    - Tekshiruv usuli: kompilyatsiya → o'lik havolalar → **har bir tugmani
      ro'yxatdan o'tgan handler patternlari bilan solishtirish** (65 ta
      `callback_data`, 24 ta pattern: o'lik tugma ham, to'qnashuv ham,
      ishlatilmaydigan handler ham YO'Q) → haqiqiy Postgres'da 45 ta
      funksional chaqiruv → tracker regressiyasi.
    - **(a) Tugmani ikki marta bosish xato berardi.** Telefonda bu juda
      tez-tez bo'ladi: ikkinchi bosishda Telegram "message is not modified"
      deydi va foydalanuvchi bekorga qo'rqinchli xato xabarini ko'rardi.
      `_clear_kb()` yordamchisi qo'shildi — barcha
      `edit_message_reply_markup(None)` chaqiruvlari shu orqali ketadi.
    - **(b) Uzun sarlavhada RASM butunlay yo'qolardi.** Telegram rasm
      sarlavhasi 1024 belgi; ko'p TP + ogohlantirish + vision izohi bo'lsa
      `send_photo` yiqilib, matnga tushardi — ya'ni bot chizgan grafik
      guruhga umuman bormasdi. Endi sarlavha oldindan qisqartiriladi.
    - **(c) Rasm baytlari xotirada osilib qolardi.** Tasdiqlanmagan qoralama
      `PENDING` da PNG baytlari bilan abadiy qolardi. Endi Telegram'ga
      yuklangach `gen` tozalanadi (file_id yetarli) va `MAX_PENDING = 500`
      chegarasi qo'shildi — eng eski qoralama chiqarib yuboriladi.
    - **(d) Admin ro'yxatida bloklaganlar ko'rinmasdi.** `users.blocked`
      broadcast'da ishlatilardi, lekin `/admin → Foydalanuvchilar` uni
      ko'rsatmasdi. Endi 🚫 belgisi bilan chiqadi.

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

---

## Keyingi qo'shimchalar

40. **Ochiq pozitsiyani boshqarish (`/open` → ⚙️ Boshqarish).**
    - Bo'shliq: signal e'lon qilingandan keyin faqat "to'liq yopish" va
      "bekor" bor edi. Savdoda esa stopni ko'chirish, maqsadni o'zgartirish
      va qisman yopish kundalik amallar.
    - `mng:` — boshqaruv oynasi (joriy holat, to'plangan foiz, jonli natija).
      `mbe:` — stop breakeven'ga, `msl:` — stop yangi narxga,
      `mtp:` — maqsadlarni almashtirish, `mpc:<id>:<25|50|75>` — qisman yopish.
    - Har bir o'zgarish guruhga asl signal postiga JAVOB qilib yoziladi
      (`notify_group`) — a'zolar nima o'zgarganini ko'rib turadi.
    - `db.set_stop()` **`sl_initial` ga TEGMAYDI**: R hisobi asl risk bo'yicha
      qolishi shart, aks holda stopni ko'chirish statistikani sun'iy
      chiroyliroq ko'rsatib yuborardi.
    - **`tracker.partial_close()`** — TP tegishi bilan bir xil hisob: ulush ×
      joriy foiz `realized_pct` ga qo'shiladi, `filled_pct` oshadi, qolgan
      qism odatdagidek kuzatilaveradi. Qolgan qism tugasa signal to'liq
      yopiladi va depozit ham yangilanadi.
    - **`tracker.process()` da bitta himoya qo'shildi** (yagona o'zgarish):
      `share = min(alloc[tp_hit], 1 - filled)`. Qo'lda qisman yopilgandan
      keyin TP tegsa `filled_pct` 1 dan oshib, foiz IKKI MARTA hisoblanardi.
      Qo'lda aralashuv bo'lmasa `min()` hech narsani o'zgartirmaydi
      (alloc yig'indisi aynan 1) — shu sabab `test_tracker.py` ning 9 ta
      holati o'zgarishsiz qoldi.
    - Himoyalar: stop kirish narxidan ±50% dan uzoq bo'lsa rad etiladi
      (nol tushib qolgan yozuv signalni bejiz yopib yuborardi); maqsadlar
      soni allaqachon bajarilganidan kam bo'lsa rad etiladi (`tp_hit`
      indeksi ro'yxatdan chiqib ketardi).
    - 15 ta holatda tekshirildi: qisman yopish hisobi, to'liq yopilishga
      o'tish, R, qisman yopish + TP, qisman yopish + STOP.

41. **Avtomatik kunlik hisobot (`/hisobot 21`).**
    - Belgilangan mahalliy soatda guruhga kun yakuni chiqadi: nechta signal
      yopildi, winrate, umumiy natija, eng yaxshi/yomon juftlik, ochiq
      pozitsiyalar soni. Egasidan hech qanday harakat talab qilmaydi.
    - `digest_job` har 15 daqiqada aylanadi (soatni o'tkazib yubormaslik
      uchun), lekin `workspaces.digest_last` (DATE) tufayli har guruhga
      kuniga FAQAT BIR MARTA yuboriladi — bot restart bo'lsa ham takrorlanmaydi.
    - `mark_digest_sent()` yuborishdan OLDIN chaqiriladi: matn tayyorlash yoki
      yuborish yiqilsa, keyingi aylanish qayta urinib guruhni bezovta qilmasin.
    - Bugun yopilgan signal bo'lmasa post umuman yuborilmaydi (bo'sh
      "bugun hech narsa yo'q" xabari spam bo'lardi).
    - Natija `/stats` bilan AYNI usulda hisoblanadi: depozit belgilangan
      bo'lsa har savdo `alloc_amount/deposit` bo'yicha tortiladi, aks holda
      sof foizlar yig'indisi. Ikki joyda ikki xil raqam chiqmasligi uchun.
    - Standart holat — O'CHIRILGAN (`digest_hour IS NULL`): hech kimga
      bexosdan post ketmaydi.
    - 14 ta holatda tekshirildi (bo'sh kun, sof foiz, tortilgan hisob,
      kechagi signallar chetda, faqat belgilangan soatda, takrorlanmaslik).

42. **Risk kalkulyatori (pozitsiya hajmi tugmalari).**
    - Avval depozit belgilangan bo'lsa bot shunchaki "necha pul ishlatasiz?"
      deb so'rardi va hisobni odam o'zi qilardi.
    - Endi 1% / 2% / 3% tugmalari chiqadi va hajm o'zi hisoblanadi:
      `hajm = depozit * risk% / (|entry - sl| / entry)`. Tasdiqlangach bot
      "stop tegsa qancha yo'qotasiz" ni ham ko'rsatadi.
    - **Hajm depozitdan oshmaydi**: spot rejimda leverage yo'q, juda tor
      stopda formula depozitdan katta son berardi. Cheklanganda buni
      ochiq yozadi, jimgina kesib qo'ymaydi.
    - Qo'lda summa yozish ham, o'tkazib yuborish ham avvalgidek qoladi.
    - `alloc:` va `allocskip:` patternlari to'qnashmaydi (`^alloc:` "allocskip:"
      ga mos kelmaydi — tekshirildi).

43. **Ochiq natijalar sahifasi (`web.py`) — alohida veb servis.**
    - Maqsad: guruh egasi skrinshot tashlash o'rniga JONLI havola beradi.
      Skrinshotni tahrirlash mumkin, sahifani esa yo'q — u to'g'ridan-to'g'ri
      bazadan o'qiladi. Bu botga qila olmaydigan ish.
    - **Ruxsat darvozasi `/top` bilan AYNAN bir xil**: `public` (egasi yoqqan)
      + `public_approved` (super-admin tasdiqlagan) + arxivlanmagan.
      `db.public_workspace()` shu shartni bitta joyda ushlab turadi. Ya'ni veb
      YANGI ruxsat ochmaydi — allaqachon ommaviy bo'lgan narsanigina ko'rsatadi.
      Tekshirildi: tasdiqlanmagan guruh ham 404 beradi.
    - **Faqat o'qish**: hech bir yo'l bazaga yozmaydi.
    - **Bot bilan ALOHIDA servis** (`python web.py`): bot polling rejimida
      ishlaydi va HTTP port ochmaydi. Bitta jarayonga qo'shilsa veb yiqilganda
      signal kuzatuvi ham to'xtardi.
    - Yo'llar: `/` (ochiq guruhlar ro'yxati), `/g/<id>` (statistika, equity,
      juftliklar, oylik, oxirgi savdolar), `/g/<id>/equity.png`, `/healthz`.
    - Kesh: sahifa va PNG 120 soniyaga keshlanadi (matplotlib qimmat), kesh
      200 yozuvdan oshsa eng eskilari tashlanadi.
    - Barcha matn (guruh nomi, juftlik) HTML uchun ekranlanadi.
    - Yagona yangi bog'liqlik: `aiohttp`.

44. **Veb sahifa botga ulandi (`/sahifa`, menyudagi 🌐 tugma).**
    - `web_page_url(ws)` — havola FAQAT `/top` darvozasidan o'tgan guruhlarda
      qaytariladi (`public` + `public_approved` + arxivlanmagan + guruh
      turi). Aks holda None va tugma umuman ko'rsatilmaydi: bosilib 404
      olishdan ko'ra tugmaning yo'qligi to'g'ri.
    - `WebAppInfo` — sahifa Telegram ICHIDA (Mini App) ochiladi. Telegram
      buni faqat SHAXSIY chatdagi inline tugmada qo'llaydi; bosh menyu doim
      shaxsiy chatda ko'rsatilgani uchun bu yerda xavfsiz.
    - Yonida "🔗 Havola" tugmasi — ulashish uchun manzil `<code>` ichida
      alohida qatorda beriladi (ko'chirishga qulay).
    - `config.WEB_URL` bo'sh bo'lsa tugma ham, buyruq ham havola bermaydi —
      ya'ni veb servis o'chirilsa bot hech narsani buzmasdan ishlayveradi.
    - Veb tomonda guruhlar ostiga chaqiruv bloki qo'shildi ("O'z guruhingizni
      shu yerda ko'rmoqchimisiz?") — uch qadamli yo'riqnoma va botga tugma.
      Sahifaga kelganlarning aksari guruh egasi, ular uchun keyingi qadam
      aniq bo'lishi kerak.

45. **Mobil ko'rinish va Mini App xatti-harakati tuzatildi.**
    - Shikoyat: "ma'lumotlar oxirigacha ko'rinmayapti, yonga surish hojat
      bo'lmasin" + "pastga slayd qilinsa veb yopilib ketyapti".
    - **Jadvallar**: `min-width:560px` tor ekranda gorizontal siljish
      hosil qilar va ustunlar kesilib qolardi. Endi `@media (max-width:640px)`
      da har qator BLOKKA aylanadi: birinchi katak (juftlik/oy) alohida
      qatorda qalin, qolganlari `data-k` atributidan olingan yorliq bilan
      "SAVDO 14  WINRATE 79%  NATIJA +119.99%" ko'rinishida yoniga tiziladi.
      Hech narsa yashirilmaydi — barcha ustun ko'rinadi.
      Tekshirildi (390px): sahifa 390 vs 390, uchala jadval 350 vs 350 —
      gorizontal siljish YO'Q.
    - **Mini App yopilib ketishi**: Telegram'da pastga surish ilovani
      yopadi. `telegram-web-app.js` ulanib, `disableVerticalSwipes()`
      chaqiriladi (Bot API 7.7+; eskirog'ida jimgina o'tkazib yuboriladi).
      Shu bilan birga `expand()` — to'liq balandlik, va header/fon rangi
      sahifa foniga moslanadi.
    - Skript har chaqiruvni `window.Telegram` va metod mavjudligiga
      tekshiradi — oddiy brauzerda sahifa hech narsa buzilmasdan ishlayveradi.

46. **Har bir savdo uchun kichik grafik (`chart.mini_chart`, `/s/<id>/mini.png`).**
    - "Oxirgi savdolar" jadval emas, endi KARTA ro'yxati: chapda juftlik va
      kirish→chiqish, o'rtada kichik grafik, o'ngda natija.
    - Grafik ataylab soddalashtirilgan (320×110, o'q ham yozuv ham yo'q):
      narx chizig'i, kirish darajasi (ko'k punktir) va chiqish nuqtasi.
      Bu o'lchamda shamlar o'qilmaydi, chiziq esa savdo shaklini bir
      qarashda ko'rsatadi.
    - **Birjani ortiqcha yuklamaslik uchun ikki himoya**:
      1. `loading="lazy"` — ekranga chiqmagan rasm umuman yuklanmaydi.
      2. Yopilgan savdo grafigi HECH QACHON o'zgarmaydi (savdo tugagan,
         shamlar tarixiy) → `MINI_TTL = 24 soat` va HTTP
         `Cache-Control: max-age=86400`. Ya'ni birjaga savdo boshiga
         faqat BIR marta murojaat qilinadi.
      Bu muhim edi: bitta sahifada 25 ta savdo bor, keshsiz har ochilish
      25 ta klines so'rovi yuborib, birja limitini yeb qo'yardi va
      kuzatuv siklini ham buzardi.
    - **Xavfsizlik**: `db.public_signal()` signalning o'zini emas, uning
      WORKSPACE'ini tekshiradi (`public_workspace()` bilan bir xil shart).
      Shu sabab yopiq guruh signalini id taxmin qilib ko'rish mumkin emas —
      tekshirildi: yopiq guruh signali va mavjud bo'lmagan id — ikkalasi 404.
    - Rasm yuklanmasa `onerror` uni olib tashlaydi — buzuq rasm belgisi
      chiqmaydi, karta shunchaki grafiksiz qoladi.

47. **`startTime` sham chegarasiga tushirilishi shart (`chart.align`).**
    Ishlab turgan serverda BARCHA `/s/<id>/mini.png` 404 qaytardi, holbuki
    MEXC `200 OK` javob berardi. Sabab: chegaraga tushmagan `startTime`
    (masalan `1787136373499` — 15m qadamiga bo'linmaydi) uchun MEXC 200
    bilan BO'SH ro'yxat qaytaradi. `_fetch` bo'sh ro'yxatni "ma'lumot yo'q"
    deb tushunib, grafikni jimgina chizmay qo'yardi.
    - Kuzatuv (tracker) bu tuzoqqa tushmaydi: uning `last_checked_ms` qiymati
      sham OCHILISH vaqtidan olinadi va allaqachon chegarada. Grafikda esa
      boshlang'ich nuqta `opened_at` — ixtiyoriy soniya.
    - `align()` uchala grafik funksiyasida ham qo'llanadi. Chegaraga PASTGA
      tushiriladi, ya'ni oyna faqat kengayadi — hech qanday sham yo'qolmaydi.
    - Yonida ikkita kichik tuzatish:
      - `exchange.klines` endi har qanday 4xx da traceback ko'tarmay, ogohlantirish
        yozib bo'sh ro'yxat qaytaradi (`VANRYUSDT` — ro'yxatdan chiqarilgan
        juftlik — 400 berib log'ni traceback bilan to'ldirgandi).
      - `web.py` da `asyncio.Semaphore(2)`: brauzer sahifadagi rasmlarni
        birdan so'raganda birjaga ~15 ta parallel so'rov ketardi. Navbatda
        turgan so'rov keshni QAYTA tekshiradi — oldingisi allaqachon
        chizib qo'ygan bo'lishi mumkin.
    - Diagnostika: `mini_chart` endi ikkala "grafik chizilmadi" yo'lida ham
      sababni log'ga yozadi (sham kelmadi / oraliqqa tushmadi).

48. **Mini App tepasida Telegram sarlavhasi uchun joy (`--tgtop`).**
    Telegram kengaytirilgan oynada "Yopish", cheveron va menyu tugmalarini
    sahifa USTIDAN chizadi — "TRADE CONTROLLER" yozuvi va sarlavha ular
    tagida qolib ketardi.
    - `header{padding-top:calc(34px + var(--tgtop,0px))}`. Standart qiymat —
      `env(safe-area-inset-top,0px)`, ya'ni oddiy brauzerda 0.
    - Skript `safeAreaInset.top` (holat qatori) + `contentSafeAreaInset.top`
      (Telegram sarlavhasi) yig'indisini qo'yadi va uni
      `safeAreaChanged` / `contentSafeAreaChanged` / `viewportChanged`
      hodisalarida qayta hisoblaydi.
    - Mijoz insetlarni bermasa (eski API), lekin mobil va oyna kengaytirilgan
      bo'lsa — 56px zaxira. Desktop va oddiy brauzerda hech narsa qo'shilmaydi.
    - O'lchandi (390px, Chromium): oddiy brauzer 34px, tdesktop 34px,
      insetli iOS (59+46) 139px, insetsiz iOS 90px.

49. **Veb sahifa: HTML keshlanmaydi, "Juftliklar kesimi" olib tashlandi.**
    - `NO_CACHE = {"Cache-Control": "no-store, max-age=0"}` — bosh va guruh
      sahifasida. Telegram WebView HTML'ni saqlab qolib, yangilanish
      chiqqanidan keyin ham ESKI sahifani ko'rsatardi (tepa bo'shlig'i
      tuzatilgani ko'rinmadi). Server keshi (`CACHE_TTL=120`) o'z holicha
      ishlayveradi — bu faqat mijoz keshi haqida.
    - `--tgtop`: mobil Telegram'da endi SHARTSIZ kamida 72px. Ba'zi mijozlar
      `safeAreaInset`/`contentSafeAreaInset` ni 0 deb qaytaradi, suzuvchi
      sarlavha esa baribir sahifa ustida turadi. Desktop va oddiy brauzerda
      0 — u yerda tugmalar sahifadan tashqarida.
      O'lchandi (390px): brauzer 34px, tdesktop 34px, insetli iOS 139px,
      insetsiz iOS 106px.
    - Guruh sahifasidan "Juftliklar kesimi" jadvali olib tashlandi (`top_symbols`
      endi faqat botda ishlatiladi). Oxirgi savdolar kartalari o'sha
      ma'lumotni ko'rgazmaliroq beradi.

50. **MEXC `startTime` ni yolg'iz qabul qilmaydi — `endTime` ham kerak.**
    `align()` dan keyin shamlar kela boshladi, lekin grafiklar baribir
    chizilmadi. Diagnostika log'i sababni ko'rsatdi:
    `"34 shamdan 0 tasi oraliqqa tushdi"` — MEXC so'ralgan oynaning BOSHIDAN
    emas, OXIRIDAN `limit` ta sham qaytaradi (Binance'dan farqi shu). Ya'ni
    o'tmishdagi savdo uchun eng SO'NGGI shamlar kelib, hammasi filtrdan
    o'tmay tushib qolardi.
    - `exchange.klines` va `forex.klines` ga `end_ms` qo'shildi
      (`endTime` / `end_date`), `chart._fetch` uni uzatadi,
      `mini_chart` va `signal_chart` oyna oxirini fetch'dan OLDIN hisoblaydi.
    - **Kuzatuv (tracker) buni sezmaydi** — u doim "hozirgacha" o'qiydi,
      shuning uchun `end_ms` siz ham to'g'ri ishlaydi. Shu sabab bu xato
      faqat grafiklarda ko'rindi.
    - Tekshirildi (MEXC xatti-harakatini taqlid qiluvchi soxta birja +
      haqiqiy Postgres): `endTime` yo'q → uchala `mini.png` 404;
      `endTime` bor → uchalasi ham 200. Sahifada 10/10 grafik chizildi.

51. **Telefonda savdo kartasi bir qator.**
    Avval grafik pastga to'liq kenglikda tushardi va bitta savdo ekranning
    uchdan birini egallardi. Endi: chapda juftlik, o'rtada 84×30 grafik,
    o'ngda natija.
    - `.tsym`/`.tsub` — `nowrap + ellipsis`: matn ko'chib, kartalar notekis
      balandlikda bo'lib qolmasin.
    - Kartadagi sana `dd.mm` (yilsiz) — tor ekranda joy yetsin uchun.
    - O'lchandi (Chromium, haqiqiy sahifa): 390px va 360px — 10/10 grafik
      chizildi, hamma karta 68px, kesilgan matn 0, gorizontal siljish yo'q.

52. **Kirish narxi shamlarga mos kelmasa — chiziq chizilmaydi, grafik qoladi.**
    Eski sinov signallarida narxlar qo'lda o'ylab yozilgan ("kirish 100,
    chiqish 91"), shamlar esa haqiqiy bozordan keladi. Miqyos kirish
    chizig'iga tortilib, haqiqiy narx harakati tep-tekis chiziqqa aylanardi —
    savdo +60% deb turgani holda grafik hech narsa ko'rsatmasdi.
    - `show_entry = c_lo*0.9 <= entry <= c_hi*1.1`. Shart bajarilmasa kirish
      punktiri CHIZILMAYDI va — muhimi — `set_ylim` ham uni HISOBGA OLMAYDI.
      Faqat chiziqni yashirish yetarli emas edi: miqyos baribir buzilgan
      bo'lardi.
    - Grafikning o'zi baribir chiziladi: u o'sha davrdagi haqiqiy narx
      harakatini ko'rsatadi. Eski statistika ham grafikli bo'lib qoladi.
    - Haqiqiy savdoda kirish HAR DOIM oyna ichida (savdo o'sha narxdan
      ochilgan), shuning uchun bu shart yangi signallarga umuman tegmaydi.

53. **Kichik grafik havolasida versiya (`MINI_V`).**
    Rasm brauzerda 24 soat keshlanadi (yopilgan savdo o'zgarmaydi). Chizish
    uslubi o'zgarganda esa telefonda ESKI rasm ko'rinib qolardi — sahifa
    yangilansa ham. Havola endi `/s/<id>/mini.png?v=2` ko'rinishida:
    yangi manzil eski keshga tushmaydi. **Grafik ko'rinishini
    o'zgartirsangiz, `MINI_V` ni oshiring.** So'rov qatori route'ga ta'sir
    qilmaydi — tekshirildi, `?v=2` bilan ham 200 keladi.

54. **"Guruhga qo'shilish" — matn havolasi emas, tugma.**
    U sahifaning asosiy maqsadi, lekin sarlavha ostidagi kichkina havola
    bo'lib ko'zga tashlanmasdi. Endi `.join` tugmasi: oddiy `.btn` dan
    kattaroq (16px matn, 13×26 padding) va yengil ko'k soya bilan.
    Telefonda `display:block` — butun kenglikni egallaydi, barmoq bilan
    bosish oson. O'lchandi: 390px ekranda 350×52, desktopda 218×50.

55. **Bosh sahifa: umumiy plitalar olib tashlandi, guruh kartalari yangilandi.**
    - "2 ochiq guruh / 19 signal / 58% winrate / 6 kuzatuvda" plitalari
      olib tashlandi. Bu raqamlar HECH KIMNING natijasi emas — turli
      guruhlarning aralashmasi; har bir guruhning o'z raqamlari kartasida
      va o'z sahifasida bor. `.htiles`/`.htile` uslublari ham o'chirildi.
    - Sarlavha: "Guruhlar" → **"Top daromad beruvchi guruhlar"** (ro'yxat
      allaqachon daromad bo'yicha tartiblangan, sarlavha buni aytadi).
    - Har bir kartada endi **o'rin raqami** bor (1, 2, 3 — oltin/kumush/
      bronza, keyingilari kulrang), fon yengil gradient, "Batafsil →" esa
      matn emas — ramkali tugma (kursor ustiga kelganda to'lib ko'karadi).
      Guruh nomi uzun bo'lsa ellipsis bilan kesiladi, karta buzilmaydi.
    - O'lchandi (390px): 3 karta, 3 o'rin raqami, 3 tugma, plita 0,
      gorizontal siljish yo'q.

56. **Dizayn Whale Payment Bot mini-ilovasidan olindi.**
    Manba: `whale-payment-bot/webapp_static/index.html` — qora-kumush palitra,
    yuqorida yengil kumush yorug'lik, shishasimon kartalar.
    - Ranglar: `--bg:#0A0A0C`, `--card:#17171B`, `--card2:#1E1E23`,
      `--line:#28282E`, `--silver:#DADDE2`, `--mut:#95979E`. Ko'k urg'u
      butunlay olib tashlandi — yashil/qizil FAQAT savdo natijasi uchun,
      shuning uchun ko'z birinchi raqamga tushadi.
    - Shriftlar: **Space Grotesk** (sarlavha, tugma, juftlik nomi),
      **Inter** (matn), **IBM Plex Mono** (barcha raqamlar, eyebrow).
    - Asosiy tugma — kumush gradient, qora matn; bosilganda `scale(.98)`.
    - `body` foni `radial-gradient(... at 50% -8%)` + `background-attachment:fixed`.
    - **Grafik ranglari ham moslashtirildi**: `chart.BG`/`stats.BG` → `#101013`,
      `GRID` → `#28282E`, `ACC` → kumush. Kichik grafik esa alohida
      `chart.CARD_BG = "#17171B"` bilan chiziladi va `.trade` foni AYNAN
      shu rang (shaffof emas) — shunda rasm chegarasi ko'rinmaydi.
      Rasm uslubi o'zgargani uchun `MINI_V` 3 ga oshirildi.
    - 3D kit va `three.js` OLINMADI: 670 KB, ustiga u Whale brendining
      belgisi — Trade Controller sahifasiga tegishli emas.
    - Savdo kartasiga ham chap chetdagi rangli chiziq qo'shildi.
    - Tor ekranlar: ≤380px da grafik 62×24 va matn 10px; ≤340px da grafik
      butunlay yashiriladi — narx va sana muhimroq.
    - O'lchandi: 390px va 360px — 10/10 grafik, kesilgan matn 0, hamma
      karta 67px, gorizontal siljish yo'q. 320px — matn to'liq, grafik yo'q.

57. **Fon qatlamlari, shaffof tugmalar, bosilish sezgisi.**
    - Tepadagi "Botni ochish" olib tashlandi — bitta sahifada bitta asosiy
      harakat yetadi, u endi faqat sahifa oxiridagi CTA blokida.
    - **Fon**: `body::before` — uchta kumush yorug'lik (tepada, chapda,
      o'ngda), 26 soniyalik `drift` animatsiyasi bilan sekin suzadi.
      `body::after` — mayin SVG shovqin (`feTurbulence`): tekis qora fonda
      gradient "chiziqlari" (banding) ko'rinmay ketadi. Ikkalasi ham
      `position:fixed`, `z-index:-1/-2`, `pointer-events:none`.
      `prefers-reduced-motion` da animatsiya o'chadi.
      Whale ilovasidagi 3D to'lqin JS+670 KB kutubxona talab qiladi;
      bu yechim faqat CSS va GPU faqat transform/opacity bilan ishlaydi.
    - **`.ghost`** — shaffof shishasimon tugma: `rgba(218,221,226,.06)` fon,
      kumush chegara, blur. Ikkilamchi harakatlar uchun ("← Barcha guruhlar",
      "Batafsil"). Asosiy kumush tugma bilan raqobat qilmaydi.
    - **Bosilish sezgisi**: `.btn:active` → `scale(.955)` + yorug'lik pasayadi,
      `.ghost:active` → `scale(.955)` + fon yorishadi, `.gcard:active` →
      `scale(.975)` + chegara kumushga o'tadi va ichidagi "Batafsil" yorishadi.

58. **Ochiq pozitsiyalar sahifada — faqat foiz, juftlik nomisiz.**
    Guruh sahifasida "Hozir ochiq" bo'limi: har bir ACTIVE pozitsiya
    "Pozitsiya N", ochilgan sanasi va JORIY foizi bilan ko'rsatiladi.
    - Tiker ATAYLAB yashiriladi: ochiq savdoning juftligi guruh a'zolarining
      haqqi, ochiq sahifada uni berish signalni tekinga berish bo'lardi.
      Foiz esa guruh hozir qanday ishlayotganini ko'rsatadi va hech narsani
      oshkor qilmaydi.
    - PENDING chiqmaydi — hali ochilmagan, joriy foizi ham yo'q.
    - Foiz `tracker.pnl_at()` bilan joriy narxdan hisoblanadi (bot ichidagi
      ayni funksiya). Sahifa 120 s keshlanadi, `last_price` esa 5 s —
      ya'ni birjaga ortiqcha yuk tushmaydi.

59. **`web_app` tugmasi GURUHDA xabarni butunlay rad etadi.**
    Guruhdagi "🏠 Bosh menyu" tugmasi bosilganda "Ishlov berishda xato"
    chiqardi. Sabab: Mini App (`WebAppInfo`) tugmasi FAQAT shaxsiy chatda
    ruxsat etilgan; guruhga yuborilsa Telegram butun xabarni
    BUTTON_TYPE_INVALID bilan rad etadi va bitta tugma tufayli MENYU
    UMUMAN ochilmaydi.
    - `main_menu_kb(uid, ws, private)` va `send_web_link` endi chat turini
      biladi: shaxsiy chatda `web_app`, guruhda oddiy `url` tugmasi
      (sahifani brauzerda ochadi, hamma joyda ishlaydi).
    - Chaqiruv joylari `update.effective_chat.type` / `q.message.chat.type`
      ni uzatadi.
    - Tekshirildi: shaxsiy chat → web_app tugma bor, url yo'q;
      guruh → web_app yo'q, url tugma bor.

60. **"🔗 Havola" tugmasi olib tashlandi.** U "🌐 Ochiq sahifa" bilan AYNI
    sahifaga olib borardi — bitta harakat uchun ikkita tugma. Endi bosh
    menyuda faqat "Ochiq sahifa". Havolani ulashish kerak bo'lsa `/sahifa`
    buyrug'i qoldi (u manzilni `<code>` ichida yuboradi, nusxalashga qulay);
    `m:weblink` ishlov beruvchisi ham saqlandi — eski xabarlardagi tugmalar
    ishlayversin.

61. **Guruh logotipi = Telegram guruh AVATARI.**
    - Rasm **bazada bayt ko'rinishida** saqlanadi (`workspaces.logo BYTEA`,
      `logo_at`). Nega `file_id` emas: veb servis ALOHIDA jarayon va unda
      `BOT_TOKEN` yo'q — `file_id` bilan rasmni yuklab ololmaydi. Bayt bazada
      tursa, veb uni to'g'ridan to'g'ri beradi va Telegram'ga umuman
      murojaat qilmaydi.
    - `bot.refresh_logo()` — `get_chat` → `photo.big_file_id` → `get_file` →
      yuklab olish → markazidan kvadrat qirqish → 256×256 PNG. Guruhda avatar
      bo'lmasa bazadagi eskisi tozalanadi.
    - Chaqiriladi: `/setup` da darhol, so'ng `logo_job` (sutkada bir marta,
      bir siklda 25 tagacha guruh — `db.logo_targets(24)`). Avatar
      o'zgartirilsa sahifada ham bir kun ichida yangilanadi.
    - Veb: `/g/<id>/logo.png` — darvoza `public_workspace()` bilan bir xil
      (yopiq guruh rasmi id taxmin qilib olinmaydi), brauzerda 1 soat
      keshlanadi. Ro'yxatda 32×32, guruh sahifasida 76×76 (telefonda 60×60).
    - **Rasm bo'lmasa** — nomning birinchi harfi bilan avatar (`.glogo.ph`,
      `.blogo.ph`), shunda kartalar bir xil ko'rinishda qoladi.
    - `requirements.txt` ga `pillow` qo'shildi: avval u faqat matplotlib
      orqali kelardi, endi kod uni to'g'ridan-to'g'ri ishlatadi.
    - Tekshirildi: kvadrat avatar → 256×256 PNG; kvadrat bo'lmagan rasm →
      qirqilib 256×256; avatarsiz guruh → baza tozalandi; Telegram xatosi →
      yiqilmaydi. Sahifada 2 ta rasm + 1 ta harf-avatar, buzuq rasm yo'q.

62. **Kompaniya aksiyalari (AAPL, TSLA, NVDA ...) — `market="stock"`.**
    - Narx manbai forex bilan AYNI: Twelve Data, ayni API kalit, ayni so'rov
      chegarasi. Shu sabab `stocks.py` o'z HTTP mijozini OCHMAYDI —
      `forex.time_series()` va `forex.price()` ni ishlatadi. Buning uchun
      forex.py ichida `klines`/`last_price` ikkiga bo'lindi: tashqi qism
      juftlikni "EUR/USD" shakliga keltiradi, ichki qism esa API bilan
      gaplashadi. Forex xatti-harakati o'zgarmadi (tekshirildi).
    - **Tiker o'zgarishsiz uzatiladi.** Forexdagi `_api_symbol` 6 belgili
      nomni ikkiga bo'ladi — aksiyada bu tikerni buzardi.
    - Tiker BITTALAB tekshiriladi (68-bandga qarang) — ro'yxat yuklab
      olinmaydi.
    - `resolve_symbol` tartibi: **kripto → forex → aksiya**. Aksiya oxirida,
      chunki bot asosan kripto uchun ishlatiladi va to'qnashuvda kripto
      ustun bo'lishi kerak. Tiker uzunligi 6 dan oshsa umuman qidirilmaydi —
      "SIGNAL" kabi tasodifiy so'zlar ro'yxatga urilmasin.
    - `normalize`: `$AAPL`, `NASDAQ:NVDA`, `tsla` → toza tiker; nuqta
      saqlanadi (BRK.B kabi sinf belgisi).
    - Bozor yopiq bo'lsa (kechasi, dam olish, bayram) Twelve Data yangi sham
      bermaydi → `time_series` bo'sh ro'yxat qaytaradi va kuzatuv keyingi
      ochilishda davom etadi. Forexdagi dam olish kuni bilan bir xil holat.
    - Belgisi: 📈 (forex 💱). SPOT SHORT ogohlantirishi endi FAQAT kriptoga
      chiqadi — forex va aksiyada short oddiy hol.
    - Tekshirildi (soxta Twelve Data): tiker aniqlash 7/7, Meksika birjasidagi
      AAPL ro'yxatga tushmadi, `/time_series` ga `NVDA` (bo'linmagan) va
      forexga `EUR/USD` ketdi, uchala moduldagi `provider("stock")` → stocks,
      `resolve_symbol(["TSLA"])` → `("TSLA","stock")`.

63. **XAUUSD (oltin) topilmasligi — `/forex_pairs` metallarni bermaydi.**
    Modul izohida "oltin/kumush kabi metallar" deb yozilgan bo'lsa ham,
    ishlab turgan serverda `XAUUSD` "topilmadi" edi: Twelve Data'ning
    `/forex_pairs` ro'yxatida metallar yo'q ekan. `/time_series` va `/price`
    esa `XAU/USD` ni bemalol qabul qiladi.
    - Yechim: `_METALS` to'plami (XAU/XAG/XPT/XPD + EUR juftliklari) ro'yxatdan
      TASHQARI tekshiriladi.
    - **Shunchaki ro'yxatga qo'shib qo'yish YETARLI EMAS edi**: reja yoki
      hudud sabab narx kelmasa, signal qabul qilinib, keyin PENDING'da qotib
      qolardi. Shu sabab `_probe()` bir marta `/price` so'raydi va javobni
      1 soat keshlaydi — narx kelmasa juftlik topilmagan hisoblanadi.
    - Tekshirildi (soxta API, metallar ro'yxatda YO'Q holatda): narx kelganda
      XAUUSD/XAGUSD topiladi va API'ga `XAU/USD` shaklida ketadi; narx
      kelmaganda topilmaydi; EURUSD ikkala holatda ham ishlayveradi; probe
      ikkinchi chaqiruvda qayta so'ramaydi.

64. **"Tahrirlash" va "Bekor qilish" rasmli ko'rikda ishlamasligi.**
    Signal ko'rigi RASM bo'lib yuboriladi (`send_final_preview`). Rasmli
    xabarda `edit_message_text` ni Telegram RAD ETADI ("there is no text in
    the message to edit") — shu sabab ikkala tugma ham "Ishlov berishda xato"
    berardi. (Ilgari ko'rik matn edi, shuning uchun ilgari ishlagan.)
    - `_edit(q, text, ...)` yordamchisi qo'shildi: rasm bo'lsa IZOH
      (`edit_message_caption`), matn bo'lsa matn tahrirlanadi; `BadRequest`
      bo'lsa oxirgi chora — yangi xabar yoziladi.
    - Ko'rik oqimidagi to'rtala joyga qo'llandi: "eskirgan", "Bekor qilindi",
      "Tahrirlash", "Ruxsat yo'q".
    - Tahrirdan keyin eski ko'rikning tugmalari olib tashlanadi: yangi ko'rik
      yuboriladi, eskisidan "Tasdiqlash" bosilsa ekrandagi rasm bilan
      yuboriladigan signal mos kelmasligi mumkin edi.
    - Tekshirildi: rasmli xabar → caption tahrirlandi; matnli → matn;
      Telegram rad etsa → yangi xabar yozildi.

65. **Rasmdan o'qish (vision) sifatini oshirish.**
    "Ko'p rasmlarni o'qiy olmayabti" muammosi bo'yicha beshta o'zgarish:
    - **Model**: `claude-sonnet-5` → **`claude-opus-5`**. Bu yerda xato narxi
      baland (noto'g'ri daraja = noto'g'ri signal), rasm esa kuniga bir necha
      marta o'qiladi — pul jihatidan farq sezilmaydi.
    - **Javob shakli**: majburiy asbob chaqirish (`tool_choice`) o'rniga
      **structured outputs** (`output_config.format` + JSON sxema). Sabab:
      majburiy asbob tanlash fikrlash bilan yaxshi birlashmaydi, fikrlash esa
      aynan grafik o'qishda (narx o'qini solishtirish, darajalarni taqqoslash)
      eng ko'p yordam beradi. Buning uchun `anthropic` 0.40 → **1.0.0**
      (Railway Python 3.13 — 1.x talabi ≥3.10, mos).
    - **Prompt qayta yozildi**: qayerga qarash (pozitsiya asbobi, matnli
      yorliqlar, gorizontal chiziqlar), ming ajratgichi tuzog'i
      ("65 000" va "65.000"), va **javob berishdan oldin mantiqiy tekshiruv**
      (LONG'da stop past, TP yuqori; SHORT'da teskari).
    - **Rasm ostidagi yozuv MASLAHAT sifatida beriladi**: to'liq signal
      sifatida o'qib bo'lmasa ham, unda ko'pincha juftlik nomi yoki tomon
      bo'ladi. Zid bo'lsa rasmga ishonish aytilgan.
    - **Javobdan keyingi tozalash (`_clean`)**: model darajani to'g'ri o'qib,
      stop bilan TP ni ALMASHTIRIB qo'yishi mumkin (ayniqsa SHORT'da). Endi
      darajalar kirish narxiga nisbatan joylashuvi bo'yicha qayta taqsimlanadi
      (geometriya yolg'on gapirmaydi) va ishonch 0.6 gacha pasaytiriladi.
      Geometriya baribir buzuq bo'lsa — modelga aynan shu xato aytilib **bir
      marta qayta so'raladi**.
    - Yonida: rasm turi baytlardan aniqlanadi (avval doim "image/jpeg" deb
      yuborilardi — fayl sifatida yuborilgan PNG'da API xato berardi), va
      grafikdagi "BINANCE:BTCUSDT.P" kabi nom nomzodlarga bo'linadi
      (`_vision_symbols`) — aks holda birja prefiksi bilan birga qidirilib
      topilmasdi.
    - Tekshirildi (mahalliy soxta API): so'rovda `claude-opus-5`, json_schema,
      to'g'ri media turi va caption maslahati bor; almashtirilgan SHORT
      darajalari qayta taqsimlandi va ishonch pasaydi; "grafik emas" javobida
      qayta so'ralmadi (1 so'rov); buzuq geometriyada qayta so'raldi (2 so'rov)
      va ogohlantirish promptga tushdi.

66. **Shaxsiy jurnalda signal KARTASI yuborilmasdi.**
    Guruhda signal tasdiqlangach karta (rasm + darajalar) guruhga post
    qilinardi; shaxsiy jurnalda esa faqat "✅ qabul qilindi" tasdig'i chiqib,
    signalning o'zi hech qayerda ko'rinmasdi. Natijada keyingi xabarlar
    (TP, stop, ±5%) javob beradigan asosiy xabar ham yo'q edi.
    - Endi karta egasining shaxsiy chatiga yuboriladi va uning `message_id`
      `signals.group_msg_id` ga saqlanadi (ustun nomi guruhdan qolgan, lekin
      bu shunchaki xabar id'si — javob o'sha chatda bo'ladi).
    - "Oddiy rejim" ochilish xabari ham shaxsiyda ishlaydi (avval faqat
      guruhga ketardi).
    - Natija va ±5% xabarlari endi shaxsiyda ham signal kartasiga JAVOB
      bo'lib keladi — guruhdagi bilan bir xil tartib.
    - Tekshirildi (haqiqiy Postgres + soxta Telegram): karta ketdi
      (`karta_xabar_id=1002`), ochilish xabari unga javob bo'ldi, TP
      yopilishi va +5% bosqichi ham javob bo'lib keldi.
    - **Kunlik hisobot (`/hisobot`) hali FAQAT guruh uchun** —
      `db.digest_workspaces()` da `type='group'` sharti bor.

67. **Kunlik hisobot shaxsiy jurnal uchun ham yoqildi.**
    `db.digest_workspaces()` dagi `type='group'` sharti olib tashlandi:
    endi guruh ham, shaxsiy jurnal ham qamrab olinadi. `digest_job` hisobotni
    guruh chatiga yoki egasining shaxsiy chatiga yuboradi; `/hisobot`
    buyrug'idagi "shaxsiy jurnal uchun mavjud emas" to'sig'i ham olib
    tashlandi, matnlar workspace turiga qarab yoziladi.
    `digest_last` himoyasi o'zgarmadi — kuniga bir marta.
    Tekshirildi: ikkala workspace ham ro'yxatga tushdi, hisobot ikkalasiga
    ham ketdi (guruh chatiga va shaxsiy chatga), ikkinchi aylanishda
    takrorlanmadi.

68. **Aksiya ro'yxatini yuklab olish ISHLAMADI — bittalab tekshirishga o'tildi.**
    Ishlab turgan serverda hech bir tiker topilmasdi va bot "qotib qolardi".
    Log: `Aksiyalar ro'yxati olinmadi` + `httpx.ReadTimeout`. Sabab:
    `/stocks?country=United States` javobi bir necha megabayt — 15 soniyalik
    chegaraga sig'maydi. Ro'yxat DOIM bo'sh qolar, har bir tiker esa o'sha 15
    soniyani kutardi.
    - Endi `/price?symbol=TSLA` so'raladi: javob bir necha bayt va bir yo'la
      IKKI savolga javob beradi — tiker bormi VA shu rejada narx keladimi.
      Ikkinchisi muhim: narx kelmasa signal qabul qilinib, keyin PENDING'da
      qotib qolardi (metallardagi bilan bir xil mantiq, 63-band).
    - Kesh: topilgani 24 soat, topilmagani 1 soat. Tarmoq xatosi
      KESHLANMAYDI — vaqtinchalik uzilish tikerni bir soatga "yo'q" qilib
      qo'ymasin.
    - `resolve_symbol` da aksiya bosqichi FAQAT dastlabki 2 nomzodni sinaydi:
      bu tarmoq so'rovi (kripto/forex esa keshdagi ro'yxatda qidiruv), bepul
      reja esa daqiqasiga 8 so'rov beradi.
    - 6 belgidan uzun so'z umuman so'ralmaydi.
    - Tekshirildi: DOCU, docu, CRCL, crcl, tsla, $AAPL, NASDAQ:TSLA — hammasi
      topildi; uzun so'zlar tarmoqqa chiqmadi; ikkinchi chaqiruvda 0 so'rov;
      olti nomzodli xabarda atigi 2 so'rov.

69. **Uzoq ishda "yozmoqda…" ko'rsatkichi (`busy`).**
    Ba'zi javoblar 5-7 soniya kechikardi (juftlik tekshiruvi tarmoqqa
    chiqadi) va foydalanuvchi bot ishlamayapti deb o'ylardi.
    - `busy(bot, chat_id, note=None, after=1.2)` — async kontekst menejer,
      IKKI bosqichli:
      1. darhol Telegram'ning "yozmoqda…" belgisi (u ~5 soniya turadi,
         shuning uchun 4 soniyada bir yangilanadi);
      2. ish `after` dan cho'zilsa — matnli xabar ("🔎 Juftlikni
         tekshiryapman…"), va u ish tugagach **o'chiriladi**.
      Shu sabab tez javoblarda chat toza qoladi, sekinlarida esa nima
      bo'layotgani ko'rinadi.
    - Sikl qadami 0.25 s, lekin tarmoqqa 4 soniyada bir marta chiqadi.
      **Avval qadam ham 4 soniya edi va 2.5 soniyalik ishda xabar umuman
      chiqmasdi** — buni sinov ochib berdi.
    - Ko'rsatkichdagi har qanday Telegram xatosi yutiladi: bu faqat
      ko'rsatkich, asosiy ishga xalaqit bermasligi kerak. Ish istisno bilan
      tugasa ham xabar o'chiriladi (`finally`).
    - Qo'llangan joylar: sehrgar juftlik qadami, matn/rasm signal ko'rigi,
      rasmdan o'qish, menyudagi Statistika / Juftliklar / Ochiq signallar,
      `/stats`, `/open`, `/equity`.
    - Tekshirildi: 0.3 s → faqat "yozmoqda"; 2.5 s → xabar chiqdi va o'chdi;
      9 s → belgi 3 marta yangilandi, xabar bitta; xato bo'lsa ham tozalandi.

70. **News Trade AI — bozorni qimirlatadigan yangiliklarni avtomatik topib,
    alohida kanalga jonli grafik bilan joylash (1-bosqich: faqat SEC).**
    Foydalanuvchi "NewsTrade.AI" kanalining formatini ko'rsatdi: tanga+%
    sarlavha, shamlar grafigi + "News" belgisi, AI xulosa, vaqt o'tishi
    bilan tahrirlanadigan xabar. `NEWS_CHANNEL_ID` bo'sh bo'lsa butun
    funksiya jimgina o'chiq (mavjud ixtiyoriy-funksiya andozasi).
    - Yangi modullar: `news.py` (SEC EDGAR full-text qidiruv —
      `efts.sec.gov`, rasmiy, bepul, kalitsiz; Telegram'ga bog'liq emas),
      `newsai.py` (`vision.py` andozasida, lekin matn uchun — tarjima/
      qisqa xulosa/"bu bozorni qimirlatadimi" filtri/tiker taxmini).
    - Unlock kalendari va cryptocurrencyalerting.com (listing/delisting)
      ATAYLAB ta'sirlanmagan: unlock manbai (DefiLlama Pro $300/oy yoki
      GitHub'dagi emissions-adapters skaneri) hali tanlanmagan;
      listing/delisting bepul rejasi webhook bermaydi (faqat Trader
      $19.99/oy+dan), foydalanuvchi avval bepul rejani sinab ko'rishni
      tanladi — botning o'z kodi bilan ulanmagan, xizmatning o'z Telegram
      integratsiyasidan foydalaniladi.
    - `chart.py`: `_render()`ga TEGILMADI (entry/sl/tps u yerda majburiy,
      "ixtiyoriy" qilish mavjud signal grafiklarini buzish xavfi edi).
      Shamlar chizish qismi `_draw_candles()`ga ajratilib, ham `_render()`,
      ham yangi `news_chart()`da ishlatiladi. `news_chart()` — Entry/SL/TP
      yo'q, faqat "News" vertikal chizig'i + nuqta va sarlavhada joriy %.
      **Birinchi urinishda foiz sarlavha yoniga belgilar soni bo'yicha
      taxmin qilingan joyga qo'yilgan edi — matn ustma-ust tushib qoldi**
      (proporsional shrift monospace emas). `_render()`dagi pnl kabi
      o'ng burchakka (`ha="right"`) ko'chirildi — aniq ishladi.
    - `db.py`: `news_events` — GLOBAL jadval (`required_channels` kabi,
      workspace_id yo'q). `external_key UNIQUE` — bir xil hodisa ikki
      marta post qilinmasin (SEC accession number). `posted` — kelajakda
      webhook manbalari (masalan listing) `FALSE` bilan yozib qo'yishi,
      `news_scan_job` esa navbatdagi ishlanmagan qatorni topishi uchun
      (hozir faqat SEC bor, u o'zi darhol `TRUE` bilan yaratadi).
    - `bot.py`: `news_scan_job` (90s) — SEC skanerdan kelgan har hodisani
      AI tahlildan o'tkazadi. **Market-moving bo'lmagan yoki tiker
      topilmagan hodisalar HAM bazaga yoziladi** (postlanmasa ham) — aks
      holda keyingi skaner siklida xuddi shu hodisa qayta topilib, Claude
      bekorga qayta chaqirilardi.
    - Jonli yangilanish (`_live_update`) — `job_queue` emas, alohida
      `asyncio.create_task`: bitta HODISAGA tegishli, chegaralangan
      davomiylik (`NEWS_LIVE_MINUTES`, standart 20 daq). Har
      `NEWS_REFRESH_SECONDS` (standart 4s) qayta chiziladi va
      `edit_message_media` bilan yangilanadi. **Umumiy tezlik cheklovi**
      (`_paced_media_edit`, global lock + oxirgi tahrirlash vaqti,
      `NEWS_MIN_EDIT_GAP`): bir nechta hodisa parallel jonli bo'lsa ham
      Telegram flood-control'ga urilmaydi — bitta hodisa yolg'iz bo'lsa
      amalda 3-4s bilan yangilanadi, bir nechtasi bo'lsa avtomatik
      sekinlashadi. `RetryAfter` kelsa shuncha kutib, KEYINGI siklda
      davom etadi (darhol qayta urinmaydi, sikl o'zi qayta chaqiradi).
    - `news_idx` (demak "kirish" narxi) `event_at`dan hisoblanadi va HAR
      chaqiriqda bir xil qoladi (start_ms/event_ms o'zgarmas) — shuning
      uchun % butun jonli oyna davomida bitta ONdan, barqaror hisoblanadi.
    - Tekshirildi: to'liq zanjir (SEC → AI → resolve → grafik → post)
      mock bilan — yangi hodisa postlanadi, takroriy hodisa Claude'ni
      QAYTA CHAQIRMAYDI (dedup DB darajasida), rutin hodisa postlanmay
      lekin yozilib qo'yiladi, `NEWS_CHANNEL_ID` bo'sh bo'lsa job hech
      narsa qilmaydi. `_live_update`: yolg'iz holatda davriy tahrirlash,
      ikkita parallel hodisada umumiy tezlik cheklovi ushlab turildi,
      `RetryAfter`da yiqilmadi. `test_tracker.py` 9/9 — o'zgarmadi.

71. **Iqtisodiy taqvim — AQSH makro yangiliklari (`econcalendar.py`).**
    Har kuni `ECON_DIGEST_HOUR`da (standart 12:00, mahalliy vaqt) kunlik
    ro'yxat, har hodisadan `ECON_REMIND_MINUTES` (standart 15) oldin
    eslatma — News Trade AI bilan bir xil `NEWS_CHANNEL_ID` kanaliga.
    - Manba: Forex Factory'ning ochiq, kalitsiz JSON eksporti
      (`nfs.faireconomy.media/ff_calendar_thisweek.json`) — ko'plab MT4/5
      indikatorlari shundan foydalanadi, lekin RASMIY EMAS. Shu sabab
      hamma maydon `.get()` bilan, keng `try/except` bilan o'qiladi.
      Manba o'zi 5 daqiqada 2 so'rovga cheklagan — natija 30 daqiqa
      keshlanadi (`_econ_events_cached`), bo'sh javob ESKI keshni
      o'chirmaydi (vaqtincha uzilish eslatmalarni butunlay
      to'xtatmasin).
    - Faqat `country=="USD"` va `impact` "High"/"Medium" (foydalanuvchi
      "faqat AQSH" dedi; "Low" va bayramlar chiqarib tashlanadi — PMI,
      iste'molchi ishonchi kabi ko'p e'tiborli hodisalar odatda "Medium"
      bo'lgani uchun faqat "High" bilan chegaralanmadi).
    - **Bir xil vaqtdagi hodisalar BITTA eslatma xabarida birlashadi**
      (masalan ikkita PMI bir vaqtda chiqsa) — foydalanuvchi ko'rsatgan
      namuna shunday edi. `due: dict[when, list[hodisa]]` bilan guruhlanadi.
    - Dedup — `news_events`ga o'xshamaydi (u yerda UNIQUE tashqi kalit),
      bu yerda alohida GLOBAL jadval `econ_calendar_state(kind, event_key)`
      — `kind='digest'` uchun kalit `YYYY-MM-DD`, `kind='reminder'` uchun
      hodisa vaqtining ISO satri. `digest_job`dagi kabi: kun/hodisa AVVAL
      belgilanadi, keyin yuboriladi — yuborish yiqilsa ham qayta-qayta
      urinib bezovta qilmaydi.
    - Tekshirildi (mock): digest bir marta (2-o'tishda 0 xabar), bir xil
      vaqtdagi ikkita hodisa BITTA guruh xabarida, 15 daqiqadan uzoqroq
      hodisa hali chiqarilmagan, `NEWS_CHANNEL_ID` bo'sh bo'lsa job hech
      narsa qilmaydi. `test_tracker.py` 9/9 — o'zgarmadi.

72. **Hajm portlashi (surge) — uzoq pasaygan, keyin hajmi keskin oshgan
    tangalarni topib, CryptoPanic'dan sababini qidirish.**
    Foydalanuvchi: "uzoq vaqtdan beri pasayib kelgan token birdaniga
    savdo hajmi oshib ketishi va u bilan bog'liq yangilikni real vaqtda
    qo'shsak-chi". Binance emas, **MEXC**da qolindi — Binance Futures
    Railway hududini 451 bilan bloklagan (loyiha shu sabab MEXC'ga
    o'tgan), va aynan shu funksiya uchun MEXC'da kichik tangalar ko'proq.
    - **Sovuq boshlanish ochiq aytilgan**: "portladimi yo'qmi"ni bilish
      uchun bot O'ZI hajm tarixini yig'ib borishi kerak (`volume_snapshots`,
      har `SURGE_SNAPSHOT_HOURS` — standart 4 soat). Bot yangi ishga
      tushgan kuni HECH NARSA aniqlanmaydi — bu kutilgan holat, xato emas.
    - `exchange.ticker_24hr()` — MEXC'ning BITTA so'rovi BARCHA USDT
      juftliklarining 24 soatlik hajmini beradi (minglab alohida so'rov
      o'rniga). `db.volume_surge_candidates()` — bitta SQL bilan "oxirgi
      hajm > bazaviy o'rtacha × multiplier" bo'lgan barcha nomzodlarni
      qaytaradi (har juftlik uchun alohida so'rov emas).
    - **Ikki bosqichli tekshiruv**: (1) hajm nomzodi arzon SQL so'rov bilan
      topiladi, (2) FAQAT nomzodlar uchun kunlik shamlar so'raladi (`exchange.
      klines(tf="1d")`) — uzoq muddatli pasayish (`SURGE_DECLINE_PCT`,
      standart -25%/`SURGE_DECLINE_DAYS` kunda) TASDIQLANMASA (masalan bu
      oddiy davom etayotgan o'sish edi) — post qilinmaydi VA bazaga
      yozilmaydi (keyingi siklda yangi ma'lumot bilan qayta baholanishi
      mumkin — `news_events.external_key` UNIQUE bilan dedup faqat
      POST QILINGANDA ishga tushadi).
    - `cryptonews.py` — CryptoPanic (`?currencies=TICKER`, bepul token,
      `vision.py`/`news.py` andozasida ixtiyoriy). **Yangilik topilmasa
      ham post ketadi** ("aniq sabab topilmadi — spekulyatsiya bo'lishi
      mumkin") — kichik tanga portlashining aksariyati haqiqatan
      yangiliksiz bo'ladi, bu botning KAMCHILIGI emas.
    - `chart.news_chart()`ga `label` parametri qo'shildi ("News" ->
      surge uchun "Portlash"); `_news_render()`/`_live_update()`ga
      `tf`/`before_ms`/`label` — SEC standart qiymatlarda (1m, 60 daqiqa,
      "News") ISHLAYVERADI, surge esa BOSHQA oyna bilan (1h, 4 kun oldin,
      "Portlash") XUDDI SHU funksiyalarni qayta ishlatadi. `before_ms`
      ataylab `_news_render`dagi `limit=200` chegarasidan ANCHA past
      (4 kun = 96 sham) — aks holda so'ralgan oyna limitga sig'may,
      "hozirgi" sham o'rniga eski shamda to'xtab qolardi.
    - Tekshirildi (mock): to'liq zanjir (nomzod → pasayish tasdig'i →
      CryptoPanic → grafik → post) ishladi; bir xil tanga/kun QAYTA
      postlanmadi; pasayish tasdiqlanmasa POST HAM, BAZA YOZUVI HAM
      bo'lmadi; yangilik topilmasa ham "spekulyatsiya" matni bilan
      post ketdi. `volume_snapshot_job`/`surge_scan_job` tashqi
      qatlamlari va `NEWS_CHANNEL_ID` bo'sh holati alohida tekshirildi.
      `test_tracker.py` 9/9 — o'zgarmadi.

73. **News Trade AI/surge postlari ostida tugmalar: MEXC referal havolasi
    + tikersiz "Jurnalga kiritish".**
    - **"💹 Savdo qilish"** — `/refhavola` bilan admin belgilagan MEXC
      REFERAL havolasi (Railway o'zgaruvchisi emas — `bot_settings`
      jadvalida, qayta deploy qilmasdan o'zgartirilishi uchun). Havolada
      `{symbol}` bo'lsa `BAZA_QUOTE` shaklidagi juftlik bilan (masalan
      `BTC_USDT` — MEXC URL formati `BTCUSDT` emas, orada `_` talab
      qiladi) almashtiriladi. **Belgilanmagan bo'lsa tugma UMUMAN
      chiqmaydi** — referalsiz oddiy havola bexosdan postlanib qolmasin
      (foydalanuvchi ataylab shunday so'radi: "referal havola bo'lsin").
    - **"📝 Jurnalga kiritish"** — `https://t.me/<bot>?start=journal_<SYMBOL>`
      deep-link. Muhim arxitektura qarori: **wizard'ning `ConversationHandler`
      holat mashinasiga TEGILMADI** — `/start` conversation'ning
      `entry_points`ida emas (alohida `CommandHandler`), shuning uchun
      `cmd_start`dan to'g'ridan-to'g'ri biror `WIZ_*` holatiga "sakrash"
      ISHLAMAYDI (foydalanuvchi keyingi bosgan tugmasi hech qanday
      handler'ga to'g'ri kelmay, "o'lik tugma" bo'lib qolardi — bu
      loyihalash bosqichida aniqlanib, ataylab bu yo'ldan qaytildi).
      Buning o'rniga: mavjud "bitta xabar" erkin-matn yo'li (`parsing.parse`)
      qayta ishlatildi — `AWAITING_JOURNAL_SYMBOL[uid] = (symbol, ws_id)`
      o'rnatiladi, `on_text_signal` buni EDIT/ALLOC kabi boshqa AWAITING_*
      bilan bir qatorda tekshiradi, foydalanuvchi yozgan TIKERSIZ matnga
      symbol OLDIGA QO'SHIB (`parsing.parse(f"{symbol} {text}")`)
      beriladi — `parsing.py`ga sira tegilmadi. `show_preview()` baribir
      `resolve_symbol()`ni o'zi qayta chaqiradi, shuning uchun bu yetarli.
    - `/start journal_<SYMBOL>` — shaxsiy jurnalga (`get_or_create_personal_workspace`)
      yo'naltiriladi, guruhga emas (bu ommaviy kanal postidan kelgan
      shaxsiy harakat). Tiker resolve bo'lmasa AWAITING o'rnatilmaydi.
      `/bekor` `AWAITING_JOURNAL_SYMBOL`ni ham tozalaydi (boshqa AWAITING_*
      bilan bir xil ro'yxatda).
    - Yangi `bot_settings(key, value)` GLOBAL jadval — bitta qiymatli
      sozlamalar uchun qayta ishlatiladigan andoza (birinchi foydalanuvchisi
      `mexc_ref_url`, kelajakdagi shunga o'xshash sozlamalar ham shu
      jadvalga yozilishi mumkin).
    - Tekshirildi (mock): `_signal_buttons` — referal yo'q/bor/`{symbol}`
      almashtirish/bot_username yo'q holatlari; to'liq zanjir — deep-link
      → AWAITING → noto'g'ri matn (holat SAQLANADI) → to'g'ri tikersiz
      matn → `show_preview` chaqirilib PENDING'ga yoziladi (symbol/market
      to'g'ri aniqlangan) → noto'g'ri tiker bilan AWAITING o'rnatilmaydi.
      `test_tracker.py` 9/9 — o'zgarmadi.

74. **`/charttest`ning chalg'ituvchi xatosi va jonli grafikda tugmalar
    yo'qolib qolishi tuzatildi; News Trade AI aksiyalar (stock) bilan
    bog'liq yangiliklarni ham qamrab oldi.**
    - Railway logida `/charttest sol` bitta martalik `httpx.ReadTimeout`
      (`telegram.error.TimedOut`) tufayli muvaffaqiyatsiz bo'lgan, lekin
      xabar "Kanalga postlab bo'lmadi (bot admin emasmi?)" deb ruxsat
      xatosidek ko'rsatgan — chalg'ituvchi. `TimedOut`/`NetworkError`
      endi alohida ushlanadi, aniq "tarmoq vaqtincha javob bermadi, qayta
      urinib ko'ring" xabari bilan.
    - **Jonli grafik tugmalari yo'qolib qolishi**: `edit_message_media`ga
      `reply_markup` uzatilmasa, Telegram MAVJUD klaviaturani o'chirib
      tashlar ekan (`editMessageCaption`dan farqli — u yerda tegilmagan
      maydon saqlanib qoladi, `edit_message_media`da esa YO'Q). `_paced_media_edit`/
      `_live_update` endi `reply_markup` qabul qiladi va uni har bir
      tahrirlashda qayta uzatadi — barcha uchta chaqiruv joyida (SEC
      yangilik, hajm portlashi, `/charttest`).
    - **Aksiya (stock) yangiliklari**: `news.py`dagi `SEC_KEYWORDS`
      avval FAQAT kripto iboralarini o'z ichiga olardi (`cryptocurrency`,
      `digital asset`). Qo'shimcha `SEC_STOCK_KEYWORDS` — aksiyaga katta
      ta'sir qiladigan 8-K "Item" turlariga mos iboralar (bankrotlik —
      "chapter 11"/"going concern", birjadan chiqarish — "notice of
      delisting", hisobotni qayta ko'rib chiqish — "restatement...",
      yirik bitim — "merger agreement"/"definitive agreement to acquire",
      moliyaviy majburiyatni bajarmaslik — "event of default"). Boshqa
      HECH NARSA o'zgartirilmadi — pastdagi butun quvur (`newsai.analyze`,
      `_resolve_news_symbol`, `tracker.provider(market)` orqali
      `stocks.klines`, `chart.news_chart`) ALLAQACHON market-agnostik
      edi (`NEWS_MARKETS = (("crypto", exchange), ("stock", stocks),
      ("forex", forex))` — oldingi bosqichda tayyor bo'lgan), shuning
      uchun yagona kerakli o'zgarish qidiruv kalit so'zlarini kengaytirish
      bo'ldi. Railway `TWELVE_DATA_API_KEY` productionda ALLAQACHON
      sozlangan (tekshirildi) — aksiya narx ma'lumoti ishlab turibdi.
    - Tekshirildi (mock, real Postgres bilan): soxta SEC hodisasi
      ("Boeing... chapter 11") → `newsai.analyze` mock (symbol_hint="BA")
      → `exchange.resolve` muvaffaqiyatsiz → `stocks.resolve` muvaffaqiyatli
      → `stocks.klines` mock → grafik bilan post, bazada `market='stock'`,
      `symbol='BA'`. `test_tracker.py` 9/9 — o'zgarmadi.
    - **`/charttest` ham kriptoga cheklanmasin deb kengaytirildi**:
      foydalanuvchi `/charttest TSLA` sinab ko'rganda avvalgi versiya
      faqat `exchange.resolve` (MEXC)ni chaqirardi va "Tiker MEXC'da
      topilmadi: TSLA" deb chalg'ituvchi javob berardi — aslida TSLA
      MEXC'da yo'q, lekin aksiya sifatida ishlashi kerak edi. Endi
      `cmd_charttest` xuddi haqiqiy yangilik pipeline'i ishlatadigan
      `_resolve_news_symbol()` orqali kripto→aksiya→forex bo'ylab
      qidiradi. Market kripto bo'lmasa (aksiya/forex bozori yopiq
      bo'lishi mumkin — kecha/dam olish kuni) `tf`/`before_ms` ham
      `surge_scan_job`dagidek kengroq oynaga (1h, 4 kun) o'tkaziladi,
      aks holda oxirgi 60 daqiqada hech qanday 1m sham topilmasdi.
      Tekshirildi (mock): `/charttest TSLA` → `stocks.resolve` orqali
      topildi, `tf="1h"` bilan chaqirildi, bazada `market='stock'`
      yozildi; topilmaydigan tiker bilan aniq xato xabari qaytdi.

75. **Barcha grafiklarga (signal, News Trade AI, /charttest) doimiy
    Anchored Volume Profile qo'shildi.**
    - Foydalanuvchi TradingView'dan misol rasm yubordi: shamlardan keyin
      bo'sh joy, so'ng grafik pane'ning O'NG CHEKKASIGA tirab, ICHKARIGA
      qarab o'sadigan (kattaroq hajm — uzunroq ustun) gorizontal ustunlar
      zonasi — anchor nuqtadan (o'sha rasmda "NEWS") buyon narx darajalari
      bo'yicha hajm taqsimoti. Aynan shu format takrorlandi.
    - **Hajm ma'lumoti yo'q edi**: `exchange.Candle`/`forex.Candle`da
      (`stocks.Candle = forex.Candle`) `volume` maydoni umuman yo'q edi.
      Ikkalasiga ham `volume: float = 0.0` default bilan qo'shildi (eski
      pozitsion `Candle(...)` chaqiruvlari — testlarda, `tracker.py`da
      ham — buzilmadi). `exchange.klines()` MEXC kline massividan `k[5]`ni
      o'qiydi; `forex.time_series()` Twelve Data javobidagi `"volume"`
      kalitini (bor bo'lsa) o'qiydi — YO'Q bo'lsa (forex — markazlashtirilmagan
      bozor, ko'pincha hajm yo'q) `0.0`, AVP shunda shunchaki chizilmaydi
      (yolg'on "hajm 0" ko'rsatishdan ko'ra to'g'rirog'i).
    - **`chart.py`**: yangi umumiy `_draw_anchored_vp(ax, candles, anchor_idx,
      lo, hi, vp_left, vp_right)` — `anchor_idx`dan OXIRIGACHA bo'lgan
      shamlarning hajmini 60 ta narx-bin'ga taqsimlaydi, har bir bin uchun
      `vp_right` chekkasiga tirab, ICHKARIGA (`vp_left` tomon) o'sadigan
      `barh` chizadi; uzunlik VA shaffoflik (alpha) ikkalasi ham nisbiy
      hajmga qarab o'zgaradi (ko'proq savdo qilingan narx — uzunroq VA
      yorqinroq). Yangi `VP_COLOR` (oltin/amber) — shamlardan (yashil/
      qizil) va ACC (kumush, Entry chizig'i)dan ANIQ ajralib turishi uchun.
      `_render()`/`news_chart()` ikkalasida ham `right_pad`dan KEYIN,
      ALOHIDA doimiy zona sifatida (`vp_width`, "chartni o'rtaroqqa surish"
      — bo'sh joy avvalgidan bir oz qisqartirilib, o'rniga shu zona
      qo'shildi, natijada grafik butunligi to'liqroq/markazlashganroq
      ko'rinadi). Daraja yorliqlari (`Entry`/`SL`/`TP`) endi `gap_end`ga
      (VP zonasidan OLDIN) bog'langan — avval ular `x_max`ga bog'liq edi,
      VP zonasi qo'shilgach ular VP ustiga tushib qolardi.
    - **Anchor nuqtasi grafik turiga qarab**: `news_chart()` — `news_idx`
      (News/Portlash belgisi, allaqachon bor edi). `signal_chart()` —
      YANGI hisoblanadigan `entry_idx` (kirish shami, `exit_idx` qanday
      topilsa xuddi shunday — `opened_at`ga eng yaqin `close_ms`).
      `setup_chart()` (hali OCHILMAGAN signal — kirish shami yo'q) — anchor
      berilmaydi, `_render()` ichida `0`ga (butun ko'rinadigan oyna) tushadi.
      `mini_chart()`ga ATAYLAB TEGILMADI — bu sham chizmaydi, faqat kichik
      chiziq (320×110, ro'yxat kartochkasi uchun soddalashtirilgan grafik,
      docstring'ida "o'q ham, yozuv ham yo'q" deb ATAYLAB loyihalangan) —
      AVP tushunchasi bu yerda strukturaviy jihatdan qo'llanmaydi.
    - Tekshirildi: sun'iy shamlar (tasodifiy narx + tanlangan narx
      zonalarida 3x ko'proq hajm) bilan haqiqiy PNG chizildi va vizual
      ko'zdan kechirildi — `news_chart()` va `_render()` (Entry/SL/TP/
      Chiqish bilan) ikkalasida ham VP zonasi to'g'ri joyda, yorliqlar
      VP bilan ustma-ust tushmadi, "node" (ko'p savdo qilingan narx)
      joylarida ustunlar aniq uzunroq/yorqinroq chiqdi — TradingView
      namunasiga o'xshash natija. `_process_news_event`/`_process_surge_candidate`/
      `/charttest` to'liq zanjirlari (avvalgi bosqichlarda yozilgan mock
      skriptlar) qayta ishga tushirilib tekshirildi — buzilish yo'q.
    - **DARHOL TUZATILDI (foydalanuvchi productionda skrinshot yubordi)**:
      dastlabki versiya profilni FAQAT anchor nuqtasidan (News/Portlash/
      Entry) OXIRIGACHA hisoblardi — "haqiqiy Anchored VP" semantikasi.
      Amalda muammoli chiqdi: yangi post qilingan `/charttest`/News Trade AI
      xabarida anchordan keyin hali 1-2 ta sham bo'lgani uchun profil
      deyarli bo'sh/yupqa ko'rinardi ("nega bunaqa volume kam?").
      Foydalanuvchi "avvalgi charti volumesini ham olish kerak" dedi —
      shuning uchun `_draw_anchored_vp` → `_draw_volume_profile`ga
      o'zgartirildi: endi ANCHORDAN QAT'IY NAZAR, GRAFIKDA KO'RINAYOTGAN
      BARCHA shamlarning hajmi hisoblanadi (haqiqiy "Anchored" emas,
      "Visible Range Volume Profile"ga yaqinroq). `_render()`dagi
      `entry_idx` parametri va `signal_chart()`dagi hisoblash shu bilan
      ORTIQCHA bo'lib qoldi — OLIB TASHLANDI (o'lik kod qoldirilmadi).
      Tekshirildi: sun'iy stsenariy (60 sham anchordan OLDIN, FAQAT 2 ta
      KEYIN — aynan foydalanuvchi skrinshotidagi holat) bilan PNG qayta
      chizildi — profil endi to'liq/boy chiqdi, aniq "node"lar ko'rinadi.
      `test_tracker.py` 9/9 — o'zgarmadi.

76. **Signal grafigi (`_render()`) — "pozitsiya izi" uslubi, qisqa
    ikonka-yorliqlar, kattaroq bo'sh joy.**
    - Foydalanuvchi productionda TLMUSDT signal grafigi skrinshotini
      yubordi: "Entry 0.00157" kabi yorliqlar shamlar ustiga tushib,
      "chartga aralashib ketyabti" (aralashib/xalaqit berib). Ikkinchi
      referens sifatida boshqa botning dizaynini ko'rsatdi — so'zsiz,
      faqat kirish/chiqish nuqtalarida ikonka (uchburchak) belgilar,
      shamlar ustida to'g'ridan-to'g'ri.
    - **Yorliqlar qisqartirildi, ikonkaga almashtirildi** (foydalanuvchi
      "so'zlar o'rniga ikonkalar bo'lsa ham roziman" dedi): "Entry X" →
      "● X", "SL X" → "✕ X", "TPn X" → "▲n X" — matplotlib STANDART
      shrifti (DejaVu Sans) qo'llab-quvvatlaydigan oddiy geometrik
      belgilar ishlatildi (emoji EMAS — 🎯🛑 kabi rangli emoji matplotlib
      standart renderida ko'pincha "bo'sh katakcha" bo'lib chiqadi,
      shrift qo'llab-quvvatlamasa).
    - **Bo'sh joy kattalashtirildi** (`right_pad`: `len(candles)*0.10` →
      `*0.45`, ham `_render()`da ham `news_chart()`da) — foydalanuvchi
      "chart yana ham orqaroqqa surish kerak, hozirgi shamni ramka
      markaziga chiqarish kerak" dedi. Natijada oxirgi/joriy sham ramka
      markaziga ANCHA yaqinroq chiqadi, yorliqlar esa keng bo'sh joyda
      shamlarga tegmasdan joylashadi.
    - **"Pozitsiya izi" (position trace)**: YOPILGAN savdolarda (`entry_idx`
      ma'lum bo'lganda — `signal_chart()` `opened_at`dan hisoblaydi, xuddi
      `exit_idx` qanday topilsa shunday) kirish endi BUTUN KENGLIKDAGI
      chiziq+yorliq EMAS — aynan o'sha shamning USTIGA yo'nalishga mos
      uchburchak belgi qo'yiladi (LONG — "^" yuqoriga, SHORT — "v" pastga;
      chiqish belgisi teskari yo'nalishda, xuddi shu andozada, allaqachon
      bor edi). Natijada kirish→chiqish "iz"i shamlar ustida ko'rinadi —
      referens dizaynga o'xshash. Hali OCHILMAGAN signalda (`setup_chart`,
      `entry_idx=None`) — kirish shami yo'q, shuning uchun avvalgidek
      butun kenglikdagi chiziq+qisqa yorliq qoladi (yagona mantiqiy variant).
      SL/TP chiziqlari HAR IKKALA holatda ham qoladi (ochiq/yopiq) — bular
      rejalashtirilgan darajalar, savdo holatidan qat'iy nazar foydali.
    - Chiqish annotatsiyasidan ham "Chiqish" so'zi olib tashlandi — endi
      faqat narx+foiz (masalan "518  (+6.80%)").
    - Tekshirildi: uchta stsenariy (yopilgan savdo — kirish/chiqish
      uchburchaklar bilan, hali ochilmagan — kirish chizig'i bilan,
      news_chart) uchun haqiqiy PNG chizildi va vizual ko'zdan kechirildi —
      yorliqlar endi shamlardan aniq ajratilgan, joriy sham markazga
      yaqinroq, uchburchak belgilar to'g'ri yo'nalish va joyda chiqdi.
      `bot.py` `chart.signal_chart()`/`setup_chart()`/`news_chart()`ni
      FAQAT yuqori darajadagi funksiyalar orqali chaqiradi (`_render()`ga
      to'g'ridan-to'g'ri murojaat qilmaydi) — imzo o'zgarishi `bot.py`ga
      butunlay ta'sir qilmadi. `test_tracker.py` 9/9 — o'zgarmadi.

77. **Bosh menyuga "News Trade AI" tugmasi qo'shildi.**
    - `main_menu_kb()` — Statistika/Ochiq signallar qatoridan keyin, `url=
      f"https://t.me/{NEWS_CHANNEL_USERNAME}"` bilan URL tugma (channel
      havolasi to'g'ridan-to'g'ri, callback emas — Telegram kanalni ICHKI
      menyuda ocha olmaydi). Boshqa News Trade AI qismlari bilan bir xil
      andoza: `config.NEWS_CHANNEL_ID` bo'sh bo'lsa tugma UMUMAN chiqmaydi
      (funksiya o'chiq bo'lsa reklama ham chiqmasin). Havola qattiq yozilgan
      (mexc_ref_url kabi `bot_settings`ga chiqarilmadi) — sabab: bu referal/
      pul havolasi emas, botning o'z kanal identifikatori, tez-tez
      o'zgarmaydi (mexc_ref_url esa foydalanuvchi tez-tez yangilashi mumkin
      bo'lgan tashqi referal
      havolasi, shuning uchun u admin buyruq bilan sozlanadigan qilingan edi).

78. **News Trade AI/surge/`/charttest` postlariga "↗️ Do'stlarga yuborish"
    tugmasi qo'shildi.**
    - Telegram'ning RASMIY "share" chuqur-havolasidan foydalanildi:
      `https://t.me/share/url?url=<postning ochiq havolasi>` — bosilganda
      Telegram o'zi ICHKI chat-tanlash oynasini ochadi, foydalanuvchi
      istalgan do'stiga/guruhga OLDINGA yuboradi. Botda HECH QANDAY
      qo'shimcha logika (forward buyrug'i, inline mode va h.k.) YOZILMADI —
      bu to'liq Telegram'ning tayyor mexanizmi, faqat to'g'ri havola
      qurish kifoya.
    - **Arxitekturaviy qiyinchilik**: postning ochiq havolasi
      (`t.me/<kanal>/<message_id>`) `message_id`ga muhtoj, u esa faqat
      `send_photo`/`send_message` QAYTARGANDAN keyin ma'lum bo'ladi —
      ya'ni boshidanoq (`reply_markup=` bilan birga yuborishda) bu
      tugmani qo'sha olmaymiz. Yechim: yangi `_add_share_button(bot_,
      chat_id, message_id, buttons)` — post yuborilgach DARHOL
      chaqiriladi, mavjud tugmalarga ("Savdo qilish"/"Jurnalga kiritish")
      yangisini qo'shib, `edit_message_reply_markup` bilan xabarni
      tahrirlaydi (foydalanuvchi buni sezmaydi — bir necha millisoniya).
      Barcha uchta postlash joyida (`_process_news_event`,
      `_process_surge_candidate`, `cmd_charttest`) ishlatiladi; qaytgan
      YANGILANGAN `buttons` keyin `_live_update()`ga `reply_markup=`
      sifatida uzatiladi — aks holda birinchi jonli tahrirlashda
      "Do'stlarga yuborish" tugmasi yo'qolib qolardi (73-bandda
      hujjatlashtirilgan `edit_message_media` xatti-harakati bilan bir xil
      sabab).
    - Yangi `NEWS_CHANNEL_USERNAME = "newstradeuz"` konstantasi — kanal
      ochiq (public) username'i, `t.me/...` havola qurish uchun (raqamli
      `NEWS_CHANNEL_ID`dan farqli — u faqat postlash uchun). Bosh
      menyudagi "News Trade AI" tugmasi (77-band) ham shu konstantaga
      o'tkazildi — ikki joyda bir xil qiymat yozilmasligi uchun.
    - Tekshirildi (mock, real Postgres bilan): `/charttest btc` to'liq
      zanjiri — post yuborilgach `edit_message_reply_markup` chaqirilgani,
      oxirgi tugma matni va havolasi (`https://t.me/share/url?url=
      https%3A%2F%2Ft.me%2Fnewstradeuz%2F<message_id>` — to'g'ri
      URL-encode bilan) tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

79. **Umumiy tekshiruv (barcha o'zgarishlardan keyin): productionda
    kutilgan, lekin zararsiz `BadRequest` spami topildi va jimlantirildi.**
    - `/py_compile` barcha `.py` fayllarga, `test_tracker.py` 9/9 —
      tozalik uchun asosiy tekshiruv (o'zgarmadi).
    - Railway loglarini kengroq oynada (faqat deploy boshlanishi emas,
      keyingi bir necha daqiqalik ish) ko'zdan kechirishda haqiqiy
      productiondagi News Trade AI posti (msg=21, haqiqiy yangilik,
      sinov emas) jonli yangilanish davomida qayta-qayta
      `telegram.error.BadRequest: Message is not modified: specified new
      message content and reply markup are exactly the same...` xatosini
      berayotgani, har safar TO'LIQ traceback bilan `WARNING` darajasida
      loglanayotgani aniqlandi.
    - **Sabab — bug EMAS**: narx ikkita `NEWS_REFRESH_SECONDS` (4s) oralig'ida
      o'zgarmasa (shamlar ma'lumoti aynan bir xil qaytadi), qayta chizilgan
      grafik BAYT-BAYT avvalgisi bilan bir xil chiqadi — Telegram esa
      "hech narsa o'zgarmagan" tahrirlashni RAD ETADI. `_paced_media_edit`ning
      mavjud `except Exception` bloki buni allaqachon to'g'ri ushlab
      turgan edi (job HECH QACHON qulamadi, keyingi tsiklda davom etardi)
      — funksional buzilish YO'Q, faqat keraksiz log shovqini.
    - Tuzatildi: `except BadRequest as e` alohida qo'shildi — xabar matnida
      "message is not modified" bo'lsa `ok=True` (mazmun ALLAQACHON
      dolzarb) va HECH QANDAY log yozilmaydi; boshqa turdagi `BadRequest`lar
      (masalan "Chat not found") hamon avvalgidek to'liq traceback bilan
      `WARNING` beradi — faqat aniq zararsiz holat jimlantirildi, boshqa
      xatolar sezilarli qolishda davom etadi.
    - Tekshirildi (mock): "Message is not modified" `BadRequest` →
      `ok=True`, nol warning logi; boshqa `BadRequest` ("Chat not found")
      → `ok=False`, bitta warning logi (avvalgidek). `test_tracker.py`
      9/9 — o'zgarmadi.

80. **Jonli grafik yangilanganda postning TAGIDAGI MATNI (caption)
    o'chib qolishi tuzatildi.**
    - Foydalanuvchi: "kanalda grafik yangilanganda tagidagi matn
      yoqolib qolyabti". Xuddi 73-band (tugmalar) va 74-band
      (`edit_message_media` haqidagi umumiy tushuncha) bilan BIR XIL
      ILDIZ sabab, FAQAT boshqa maydonga tegishli: `_paced_media_edit`
      `InputMediaPhoto(photo, filename="news.png")`ni `caption`SIZ
      qurar edi — `edit_message_media` esa BUTUN media obyektini
      (rasm + izoh) yangisi bilan ALMASHTIRADI, eskisidan HECH NARSA
      "meros" bo'lib qolmaydi. Caption berilmasa — Telegram uni
      shunchaki BO'SH qiladi.
    - Tuzatish AYNAN 73-band bilan bir xil andozada: `_paced_media_edit`/
      `_live_update`ga yangi `caption: str | None = None` parametri
      qo'shildi, `InputMediaPhoto`ga endi `caption=caption,
      parse_mode=ParseMode.HTML` beriladi. Barcha uchta chaqiruv joyida
      (`_process_news_event`, `_process_surge_candidate`, `cmd_charttest`)
      dastlab `send_photo`ga berilgan AYNAN O'SHA `caption` o'zgaruvchisi
      `_live_update(..., caption=caption)`ga ham uzatiladi — ikkinchi
      marta yozilmaydi, faqat qayta ishlatiladi.
    - Tekshirildi (mock): `_paced_media_edit`ga caption berilganda
      `edit_message_media`ga uzatilgan `InputMediaPhoto.caption`/
      `.parse_mode` aynan mos kelishi tasdiqlandi; `/charttest` to'liq
      zanjiri (share tugmasi bilan birga) qayta ishga tushirilib
      tekshirildi — buzilish yo'q. `test_tracker.py` 9/9 — o'zgarmadi.

81. **"Kanalda ko'proq xabar kelishi uchun" — surge parametrlari
    yumshatildi, Upbit yangi listing e'lonlari va yirik likvidatsiyalar
    qo'shildi (aksiya watchlist hali kutilmoqda — foydalanuvchi tiker
    ro'yxatini beradi).**
    - Avval bir nechta variant taklif qilindi (birja e'lonlari, aksiya
      hajm portlashi, surge yumshatish, likvidatsiyalar); har birini
      QURISHDAN OLDIN WebSearch orqali TEKSHIRILDI (sandbox tarmog'i
      ko'p domenni bloklagani uchun to'g'ridan-to'g'ri test qilib
      bo'lmaydi) — natijada muhim CHEKLOVLAR aniqlandi va foydalanuvchiga
      aytilib, qamrov shunga qarab TORAYTIRILDI:
      - **Binance/Coinbase'ning bepul, ochiq yangi-listing API'si YO'Q**
        (faqat pullik/norasmiy scraping xizmatlar) — QOLDIRILDI.
      - **Upbit**'ning `api-manager.upbit.com/api/v1/notices` — ochiq,
        kalitsiz, bir nechta mustaqil manbada tasdiqlangan — QO'SHILDI.
      - **Bithumb**'ning rasmiy notices manzili sandbox'da tekshirib
        bo'lmadi (`apidocs.bithumb.com` butunlay bloklangan edi) —
        noto'g'ri/taxminiy URL yozib "ishlayotgandek" ko'rsatishdan
        ko'ra ROSHIQ QOLDIRILDI, keyinroq production loglaridan aniq
        manzil topilsa qo'shiladi.
      - **CoinGlass**'ning likvidatsiya API'sida BEPUL reja UMUMAN YO'Q
        ($29/oy dan boshlanadi) — o'rniga **Coinalyze** tanlandi (bepul,
        lekin ro'yxatdan o'tib kalit olish kerak — foydalanuvchi
        keyinroq beradi, hozircha `COINALYZE_API_KEY` bo'sh).
      - **Aksiya hajm portlashi**: Twelve Data bepul rejasi (daqiqasiga
        8 so'rov) minglab tikerni skanerlashga yetmaydi — kripto kabi
        bitta bulk so'rov (`ticker_24hr()`) yo'q. Foydalanuvchi o'zi
        kichik watchlist (~15-20 ta tiker) berishga rozi bo'ldi, lekin
        RO'YXATNI HALI YUBORMADI — shu qism KEYINGI bosqichga qoldirildi
        (kod tayyor emas, kutilmoqda).
    - **`config.py`**: `SURGE_VOLUME_MULTIPLIER` 3→2.2, `SURGE_DECLINE_PCT`
      25→15 (ko'proq, ozroq "kafolatlangan" signal). Yangi: `UPBIT_NOTICES_URL`,
      `COINALYZE_API_KEY` (bo'sh — jimgina o'chiq), `LIQUIDATION_SYMBOLS`
      (BTC/ETH/SOL/BNB/XRP, Coinalyze belgilash uslubida), `LIQUIDATION_MULTIPLIER=4`.
    - **`listings.py`** (yangi) — `upbit_scan(since)`, `news.sec_scan()`
      bilan BIR XIL natija shakli (`{source, external_key, symbol=None,
      market=None, headline_en, body_en, event_at, source_url}`) —
      `news_scan_job`ga qo'shimcha manba sifatida to'g'ridan-to'g'ri
      qo'shiladi, alohida ishlov KERAK EMAS. Notice sarlavhasi koreyscha
      keladi — TARJIMA QILINMAYDI, xom holda `newsai.analyze()`ga
      beriladi (Claude ko'p tilli, o'zi tarjima/tahlil/tiker-taxmin
      qiladi). `LISTING_KEYWORDS` — koreyscha ("상장"="listing",
      "거려지원"="savdo qo'llab-quvvatlash") + inglizcha filtr, texnik
      ishlar kabi aloqasiz e'lonlarni chiqarib tashlaydi.
    - **`liquidations.py`** (yangi) — `liquidation_candidates()`:
      Coinalyze'dan har bir kuzatilayotgan instrument uchun 5 daqiqalik
      likvidatsiya ustunlarini oladi, OXIRGI ustunni OLDINGI ustunlar
      o'rtachasi bilan solishtiradi, `LIQUIDATION_MULTIPLIER`dan katta
      bo'lsa `Spike` qaytaradi. **Javob shakli TASDIQLANMAGAN** (API
      hujjatiga to'g'ridan-to'g'ri kira olmadik) — `l`/`s` maydonlarini
      bir nechta ehtimoliy nom bilan sinab o'qiydi, aniqlik production
      loglarida tekshirilib kerak bo'lsa moslashtiriladi (SEC/CryptoPanic
      integratsiyalarida bo'lgani kabi).
    - **`bot.py`**: `news_scan_job` endi SEC va Upbit'ni ALOHIDA
      try/except ichida chaqiradi (bittasi ishlamay qolsa ikkinchisi
      davom etadi). Yangi `_process_liquidation_spike()`/
      `liquidation_scan_job()` (interval=300s, Coinalyze bucket
      o'lchamiga mos) — mavjud `_news_render`/`_signal_buttons`/
      `_add_share_button`/`_live_update` infratuzilmasini QAYTA
      ishlatadi (`label="Likvidatsiya"`), 15 daqiqalik oynada dedup.
      Coinalyze belgisidan (`BTCUSDT_PERP.A`) baza aktiv ajratilib
      (`BTC`) `exchange.resolve()` bilan MEXC juftligiga aylantiriladi;
      topilmasa (masalan MEXC'da yo'q kam tarqalgan tanga) jimgina
      o'tkazib yuboriladi.
    - Tekshirildi (mock): `listings.upbit_scan()` — koreyscha listing
      sarlavhasi TO'G'RI tanlandi, texnik-ish e'loni chiqarib tashlandi;
      `liquidations.liquidation_candidates()` — soxta 10 ta bucket
      (oxirgisi 46x portlash) bilan to'g'ri `Spike` qaytardi;
      `_process_liquidation_spike()` to'liq zanjiri (resolve → grafik →
      post → baza yozuvi) tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

82. **Upbit va Coinalyze — production'da real xatolar chiqib, ikkalasi
    ham tuzatildi (81-band bilan bir xil ish davomi, alohida band —
    haqiqiy manzil/sxema faqat DEPLOY qilingandan keyin ma'lum bo'ldi).**
    - **Upbit — 3 marta noto'g'ri manzil**: `api-manager.upbit.com/notices`
      → 404, `/notices/search` → 404, ochiq-manba crawler'dan topilgan
      `project-team.upbit.com/api/v1/disclosure` → `httpx.ConnectError:
      Name or service not known` (domen UMUMAN mavjud emas — o'sha
      crawler loyihasi ESKIRGAN edi). Uchala urinish ham xavfsiz
      ushlangan (`news_scan_job` HECH QACHON qulamadi, faqat Upbit
      qismi ishlamadi) — lekin funksiya haligacha ISHLAMAYDI. Aniq
      manzil topilmaguncha shu holatda qoladi (foydalanuvchidan brauzer
      DevTools orqali haqiqiy so'rov manzilini so'rash so'raldi).
    - **Coinalyze — RASMIY hujjat foydalanuvchi tomonidan taqdim etildi**
      (`api.coinalyze.net` sandbox'da bloklangani uchun o'zim to'g'ridan-
      to'g'ri o'qiy olmagan edim). Bu ANIQLAB berdi: (1) `/liquidation-history`
      `from`/`to` (UNIX soniya) parametrlarini MAJBURIY talab qiladi —
      dastlabki versiyada BU IKKALASI HAM YUBORILMAGAN edi (ishlatib
      ko'rilganda 400 bilan rad etilardi); (2) `symbols` BITTA so'rovda
      vergul bilan 20 tagacha instrumentni qabul qiladi — dastlab HAR
      BIR instrument uchun ALOHIDA so'rov yuborilardi (5 ta so'rov
      o'rniga endi 1 ta); (3) javob shakli — RO'YXAT, har biri
      `{"symbol", "history": [...]}` — bu qism to'g'ri taxmin qilingan
      edi. `liquidations.py` shu uchala tuzatish bilan to'liq qayta
      yozildi: `liquidation_candidates()` endi BITTA `httpx` chaqiruvi
      qiladi (`from`/`to`/`convert_to_usd=true` bilan), javobni
      `{symbol: history}` ro'yxati sifatida ishlaydi.
    - Tekshirildi: yangi so'rov URL'i sinov API kaliti bilan qurilib,
      barcha majburiy parametrlar (`symbols` — 5 ta instrument vergul
      bilan, `interval=5min`, `from`/`to`, `convert_to_usd=true`,
      `api_key`) to'g'ri mavjudligi tasdiqlandi; to'liq mock-zanjir
      (soxta ko'p-instrumentli javob → `Spike` → post) qayta ishga
      tushirilib tekshirildi. `test_tracker.py` 9/9 — o'zgarmadi.
    - **Upbit — TO'G'RI manzil topildi (foydalanuvchi brauzer orqali)**:
      uchala avvalgi urinish (ikkitasi 404, biri mavjud bo'lmagan domen)
      muvaffaqiyatsiz bo'lgach, foydalanuvchi DevTools (Network) orqali
      haqiqiy so'rovni tekshirib berdi — `pub-info.upbit.com/api/v1/announcements`
      (`os=web&page=1&per_page=20&category=all`), HTTP 200, to'liq javob
      namunasi bilan. Eskirgan manzillar (`api-manager.upbit.com`,
      `project-team.upbit.com`) Upbit tomonidan shu ALOHIDA mikroservisga
      ko'chirilgan ekan. `listings.py` ushbu tasdiqlangan shaklga
      (`data.notices[]` — `id`/`title`/`listed_at`/`category`, `+09:00`
      vaqt mintaqasi bilan) to'liq qayta yozildi. Tekshirildi (mock,
      foydalanuvchi yuborgan aniq javob namunasi bilan): listing e'loni
      TO'G'RI tanlandi (`external_key="upbit:6516"`), texnik-ish e'loni
      chiqarib tashlandi, KST vaqt mintaqasi UTC'ga to'g'ri aylantirildi.
      `test_tracker.py` 9/9 — o'zgarmadi. Bu bilan barcha 82-band
      elementlari (Upbit + Coinalyze) endi haqiqatan ISHLASHI kutilmoqda
      — Coinalyze faqat `COINALYZE_API_KEY` qo'yilgach.
    - **Upbit — 2-marta, 403 Forbidden**: manzil to'g'ri edi, lekin
      sarlavhasiz (standart httpx User-Agent) so'rov rad etilgan. Brauzer
      sarlavhalari (`User-Agent`/`Referer`/`Origin`) qo'shilgach ishladi
      (`news_scan_job` keyingi barcha yurishlarida Upbit haqida OGOHLANTIRISH
      chiqmadi). `COINALYZE_API_KEY` ham foydalanuvchi tomonidan Railway'ga
      qo'shildi — `liquidation_scan_job` ham xatosiz ishladi. Ikkalasi ham
      HOZIR HAQIQATAN ISHLAMOQDA (production loglarida tasdiqlangan).

83. **Likvidatsiya posti: long/short taqsimoti qo'shildi.**
    - Foydalanuvchi: "likvidatsiya longmi shortmi bilib bo'lmayabti" —
      caption faqat JAMI ($ va necha barobar) ko'rsatardi, long/short
      ALOHIDA ko'rinmasdi (bu esa narx yo'nalishini bildiradi: LONG ko'p
      yopilsa narx PASAYGANDA, SHORT ko'p yopilsa narx KO'TARILGANDA
      likvidatsiya bo'ladi — traderlar uchun muhim farq).
    - `liquidations.py`: `Spike`ga `long_usd`/`short_usd` maydonlari
      qo'shildi (`_bucket_sides()` — avvalgi `_bucket_total()` shu
      funksiya orqali qayta yozildi, natija o'zgarmadi). Oxirgi ustunning
      xom holati endi `log.debug()` bilan yoziladi — Coinalyze'ning
      individual maydon nomlari (`l`/`s` long/short deb TAXMIN qilingan,
      rasmiy hujjatda ko'rsatilmagan) production loglarida tasdiqlash
      uchun.
    - `bot.py` `_process_liquidation_spike()`: caption'ga "🔴 Long: $X
      🟢 Short: $Y" qatori va qaysi tomon USTUN bo'lsa shunga mos
      yo'nalish izohi ("narx pasaygan/ko'tarilgan bo'lishi mumkin")
      qo'shildi.
    - **Jonli yangilanish "umuman ishlamadi" muammosi**: kodni qayta
      ko'rib chiqishda `_live_update()`/`_paced_media_edit()` chaqiruvi
      surge/SEC bilan BIR XIL, allaqachon ishlayotgan infratuzilma —
      liquidationga xos xato TOPILMADI. Eng ehtimolli sabab: o'sha payt
      ketma-ket bir necha marta deploy qilingan edi (Upbit tuzatish +
      Coinalyze kalit) — `asyncio.create_task()` fon vazifasi konteyner
      qayta ishga tushganda O'CHIB QOLADI (bu BARCHA News Trade AI jonli
      yangilanishlariga tegishli umumiy, oldindan bilingan cheklov,
      alohida tuzatish talab qilmaydi — post yuborilgandan keyin qayta
      deploy qilinmasa muammo bo'lmasligi kerak).
    - Tekshirildi (mock): to'liq zanjir qayta ishga tushirilib, caption
      matnida "🔴 Long: $4,000,000   🟢 Short: $3,000,000" va "📉 Asosan
      LONG yopildi (57%)" qatorlari to'g'ri chiqishi tasdiqlandi.
      `test_tracker.py` 9/9 — o'zgarmadi.
    - **Grafikdagi belgi rangi ham qo'shildi** ("stikerlar bo'lsin,
      likvidatsiyada qizil yashil"): `chart.news_chart()`ga yangi
      `marker_color: str | None = None` parametri — berilmasa avvalgidek
      ACC (kumush, SEC/Upbit/Portlash/Sinov uchun o'zgarishsiz). Likvidatsiya
      uchun `_process_liquidation_spike()` LONG ustun bo'lsa `chart.RED`,
      SHORT ustun bo'lsa `chart.GREEN` hisoblab, buni `_news_render()` va
      `_live_update()` orqali OXIRIGACHA (jonli yangilanish davomida ham
      BARQAROR — narx o'zgarsa ham rang o'zgarmaydi, chunki yo'nalish
      likvidatsiya PAYTIDA aniqlangan, joriy narxdan emas) uzatadi.
      Tekshirildi: haqiqiy PNG chizilib (qizil — LONG ustun stsenariysi),
      belgi/chiziq/yorliq rangi to'g'ri RED chiqishi vizual tasdiqlandi;
      to'liq mock-zanjir qayta ishga tushirildi. `test_tracker.py` 9/9.

84. **Jonli yangilanish "umuman ishlamaydi" — HAQIQIY sabab topildi va
    tuzatildi (83-band'dagi "deploy vaqti" taxmini YETARLI emas edi).**
    - Foydalanuvchi 83-banddagi tuzatishdan KEYIN ham, oraliqda faqat
      BITTA deploy bo'lgan holda, "rasmlar yangilanmayabti" deb yana
      xabar berdi — bu deploy-vaqti taxminini yetarsiz qildi, chunki bu
      qadar kam deploy fonida muammo shunchalik tez-tez qaytmasligi kerak.
    - Haqiqiy sabab: Python hujjatlariga ko'ra `asyncio.create_task()`
      event loop'da qaytgan Task obyektiga faqat KUCHSIZ (weak) referens
      saqlaydi — chaqiruvchi natijani hech qayerda ushlab turmasa, Python
      uni ISHLASH DAVOMIDA, hech qanday xato bermay, kutilmagan payt
      "garbage collect" qilib yuborishi mumkin. `bot.py`da to'rtta joyda
      (`_process_news_event`, `_process_surge_candidate`,
      `_process_liquidation_spike`, `/charttest`) xuddi shu xato bor
      edi — qaytgan Task hech qayerga saqlanmagan.
    - Tuzatish: modul darajasida `_background_tasks: set[asyncio.Task]`
      to'plami va `_spawn_background(coro)` yordamchisi qo'shildi — Task
      to'plamda KUCHLI referens sifatida ushlab turiladi, tugagach
      `add_done_callback` orqali o'zi to'plamdan chiqib ketadi. Barcha
      to'rtta `asyncio.create_task(_live_update(...))` chaqiruvi
      `_spawn_background(_live_update(...))`ga almashtirildi.
    - Tekshirildi: standalone skriptda `_spawn_background` mexanizmi
      ishlashi tasdiqlandi (vazifa ishlayotganda to'plamda BOR, `gc.collect()`
      chaqirilsa ham tirik qoladi, tugagach to'plamdan avtomatik chiqadi).
      `test_tracker.py` 9/9 — o'zgarmadi (bu kod `tracker.py`ga tegmaydi).
      Production'da deploy tasdiqlandi.

85. **Likvidatsiya posti butunlay soddalashtirildi — foydalanuvchi aniq
    namuna berdi ("avvalgisi juda chalkash").** Namuna:
    `🔴 #PUMP Likvidlanish Long: $533,89K narx: $0,0045581 Binance`.
    - **Mezon o'zgardi**: avvalgi "o'rtachadan necha marta ko'p" nisbati
      (`LIQUIDATION_MULTIPLIER`) OLIB TASHLANDI — endi oddiy: oxirgi
      5-daqiqalik ustunda long YOKI short tomonning BIRI
      `config.LIQUIDATION_MIN_USD` (standart 500000)dan katta bo'lsa
      post qilinadi ("faqat 500.000$dan katta... kichiklari kerak emas").
      `liquidations.py` shu sabab soddalashtirildi: `Spike`dan
      `ratio`/`baseline_usd` olib tashlandi, faqat `long_usd`/`short_usd`
      qoldi; o'rtacha hisoblash mantig'i butunlay ketdi.
    - **Kuzatiladigan ro'yxat kengaytirildi**: namunada `#PUMP` — bu
      avvalgi 5 ta asosiy tanga (BTC/ETH/SOL/BNB/XRP) ro'yxatida yo'q
      edi. `LIQUIDATION_SYMBOLS`ga yana 15 ta mashhur fyuchers qo'shildi
      (DOGE/ADA/AVAX/LINK/LTC/TRX/DOT/SUI/APT/ARB/OP/NEAR/INJ/WIF/PUMP)
      — jami 20 ta (Coinalyze'ning bitta so'rovdagi maksimal chegarasi).
    - **Xabar formati butunlay yangi, ixcham bitta qatorga tushirildi**
      (avvalgi ko'p qatorli, izohli caption OLIB TASHLANDI):
      `{🔴/🟢} #{BAZA} Likvidlanish {Long/Short}: ${miqdorK} narx: ${narx} Binance`.
      Emoji/rang mantiqi eskisi bilan bir xil qoldi (LONG ustun → qizil,
      SHORT ustun → yashil). "Binance" qat'iy yozilgan — `.A` Coinalyze
      kodida haqiqatan BINANCE degani (config.py'dagi izohda tasdiqlangan),
      shuning uchun bu YOLG'ON emas.
    - **Yangi raqam formatlash** (`_eu_decimal`/`_fmt_usd_k`/`_fmt_price`,
      bot.py): foydalanuvchi namunasi Yevropa/rus uslubida (vergul =
      kasr belgisi, nuqta = minglik ajratgich) — standart Python
      `f"{x:,.2f}"` (AQSH uslubi) dan farqli. `_fmt_price()` narxni
      moslashuvchan aniqlik bilan (8 xonagacha, ortiqcha nollarsiz)
      chiqaradi — arzon tanga uchun ko'p kasr xonasi ($0,0045581), qimmat
      tanga uchun kam ($101,0065), popundek son uchun kasrsiz ($100).
      Narx `exchange.last_price(symbol, fresh=True)` orqali JONLI olinadi
      (Coinalyze bermaydi).
    - Dedup bucket granularligi 15 daqiqadan 5 daqiqaga tushirildi — skan
      joyi (`liquidation_scan_job`) allaqachon har 5 daqiqada ishlaydi,
      shunga mos.
    - Tekshirildi (mock, haqiqiy Postgres): to'liq zanjir ($533,89K PUMP
      long, $978,47K SOL short kabi) ishga tushirilib caption AYNAN
      foydalanuvchi namunasiga mos chiqishi tasdiqlandi
      (`🔴 #PUMP Likvidlanish Long: $533,89K narx: $0,0045581 Binance`);
      $500K'dan kichik nomzod (`ETHUSDT_PERP.A`, $10K) TO'G'RI filtrlanib
      tashlanishi ham tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

86. **MarketTwits (Telegram kanali) — Telethon userbot orqali yangi
    manba qo'shildi.** Foydalanuvchi: "telegram kanallardagi
    yangiliklardan qanday foydalansak bo'ladi?" -> "markettwits".
    - **Nega oddiy Bot API emas**: bot faqat O'ZI ADMIN qilingan
      kanallarni "eshitadi" — MarketTwits kabi begona ommaviy kanal
      bizni admin qilmaydi. Yechim: `tgsource.py` — Telethon (MTProto,
      foydalanuvchi-akkaunt) orqali kanalga oddiy A'ZO sifatida qo'shilib,
      barcha postlarni jonli o'qiydi.
    - **MUHIM sandbox cheklovi**: MTProto — HTTPS emas, xom TCP protokol;
      bu rivojlantirish sandbox'ining tarmoq siyosati tomonidan
      BLOKLANGAN (`curl .../__agentproxy/status` orqali tasdiqlandi —
      faqat HTTPS CONNECT qo'llab-quvvatlanadi, "raw-TCP" YO'Q). Shu
      sabab Telethon login/tinglash **faqat production'da (Railway)**
      ishlaydi va sinaladi — bu yerda faqat kod yozildi, ishga tushirish
      sinalmadi (`py_compile` va to'liq `import bot` orqali sintaksis/
      import xatolari yo'qligi tekshirildi, xolos).
    - **Login oqimi butunlay admin-buyruqlar orqali** (`/tg_login
      +998...` -> `/tg_code 12345` -> kerak bo'lsa `/tg_password ...`) —
      bevosita JONLI botga yozib amalga oshiriladi (bu yerda EMAS, sabab
      yuqorida). Sessiya `telethon.sessions.StringSession` bilan STRING
      sifatida Postgres'ga (`bot_settings`, `db.get_setting/set_setting`
      — mavjud kalit-qiymat jadvali qayta ishlatildi) saqlanadi — FAYL
      emas, chunki Railway konteyneri qayta ishga tushganda fayl
      yo'qoladi, baza esa yo'q.
    - `config.py`: `TELETHON_API_ID`/`TELETHON_API_HASH` (foydalanuvchi
      my.telegram.org'dan olib berdi — kodga YOZILMADI, faqat Railway
      maxfiy o'zgaruvchisiga), `TELEGRAM_NEWS_CHANNELS` (standart:
      `markettwits`, vergul bilan bir nechtasi qo'shilishi mumkin).
    - `bot.py`: `_process_markettwits_message()` kelgan xabarni SEC/Upbit
      bilan BIR XIL shaklga (`headline_en`/`external_key`/...) o'rab,
      mavjud `_process_news_event()` quvuridan (AI tahlil -> grafik ->
      post -> jonli yangilanish) o'tkazadi — yangi post-mantiq YOZILMADI,
      to'liq qayta ishlatildi. `_BotCtx` — yengil o'rovchi (`_process_
      news_event` faqat `ctx.bot`dan foydalanadi, Telethon tinglovchisi
      esa oddiy `Bot` obyekti beradi). `_start_markettwits_listener()`
      idempotent — `post_init`da (avval login qilingan bo'lsa) VA
      `/tg_code`/`/tg_password` muvaffaqiyatidan keyin (qayta deploy
      kutmasdan) chaqiriladi.
    - Tekshirildi (mock, haqiqiy Postgres): to'liq zanjir ("SEC
      Bitcoin ETF arizasini tasdiqladi" kabi matn) `_process_news_event`
      orqali to'g'ri postlanishi VA xuddi shu `external_key` bilan
      IKKINCHI marta kelsa dedup ishlashi (qayta postlanmasligi)
      tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

87. **MarketTwits: AI'siz (hashtag-asosli) filtrga o'tkazildi —
    Anthropic kredit tugagani sabab.** Foydalanuvchi `/tg_test` bilan 3
    ta xabar sinadi, birortasi ham postlanmadi — Railway loglarida sabab
    aniq ko'rindi: `anthropic.BadRequestError: Your credit balance is
    too low`. Bu MarketTwits'ga xos emas edi — `newsai.analyze()` orqali
    o'tuvchi HAMMA manba (SEC/Upbit ham) o'sha payt AI xatosi bilan
    jimgina hech narsa postlamayotgan edi. Foydalanuvchi: "AI siz o'zimiz
    filtr yaratsak o'sha filtr bilan ishlansa bo'lmaydimi?" — MarketTwits
    uchun HA, chunki manba o'zi deyarli har bir postga #HASHTAG qo'yadi
    (masalan `#ASTR #hisobot`, `#Sui`) — bu tayyor, bepul signal.
    - `bot.py`: `_process_markettwits_message()` endi `_process_news_event()`/
      `newsai.analyze()`ni UMUMAN chaqirmaydi (SEC/Upbit hali ham AI
      kerak — ular o'zgarmadi, faqat MarketTwits AI'siz). Yangi
      `_markettwits_symbol()` — matndagi har bir `#hashtag`ni
      `_resolve_news_symbol()` bilan (avval AI symbol_hint uchun
      ishlatilgan, o'sha funksiya qayta ishlatildi) sinab, birinchi
      RESOLVE bo'ladigan tikerni qaytaradi. Tiker topilmasa — post
      QILINMAYDI (bu AI'siz "kuchli yangilikmi" filtri — faqat aniq
      tikerga bog'liq postlar o'tadi, kengroq makro/geosiyosiy xabarlar
      esa STIKER YO'Q sabab tabiiy ravishda chiqarib tashlanadi — bu
      cheklov, ongli qabul qilindi).
    - Tarjima ham AI'siz — xabar QANDAY kelsa (odatda ruscha) shundayligicha
      postlanadi, faqat manba havolasi (`t.me/<kanal>/<msg_id>`) qo'shiladi.
      Grafik/jonli-yangilanish qismi o'zgarmadi (bu allaqachon AI'siz,
      faqat birja narx ma'lumoti).
    - `/tg_test` yordam matni yangilandi ("AI kuchli deb topsa" o'rniga
      "matnda tanish #hashtag bo'lsa").
    - Tekshirildi (mock, haqiqiy Postgres, `newsai.analyze` chaqirilsa
      AssertionError otadigan qilib ataylab sinov qilindi — ya'ni AI
      chaqirilmaganini ISBOTLAB): `#BTC` bilan post to'g'ri yuborildi;
      `#Eron #Ormuz #geopolitika` (tanish tiker yo'q) to'g'ri filtrlandi.
      `test_tracker.py` 9/9 — o'zgarmadi.
    - **Ochiq savol**: SEC/Upbit hali ham `newsai.analyze()`ga bog'liq —
      Anthropic kreditsiz ular ham postlamaydi. Foydalanuvchiga alohida
      aytilgan, hal qilinishi kutilmoqda (kredit qo'shish yoki ularni ham
      AI'siz qilish).

88. **MarketTwits: admin panelda boshqariladigan qo'shimcha #hashtag
    ro'yxati qo'shildi.** Foydalanuvchi: "boshqa hashtaglarni ham
    qo'shsa bo'ladimi? Yoki qo'shadigan tugma yarataylik admin panelga" —
    87-banddagi tiker-asosli filtr KENGROQ makro/geosiyosiy xabarlarni
    (masalan `#Eron #Ormuz #geopolitika` — hech qanday tikerga to'g'ridan-
    to'g'ri bog'lanmaydi) o'tkazib yubormasdi. Endi admin bunday
    "muhim" mavzu-hashtaglarni QAYTA DEPLOY QILMASDAN qo'sha oladi.
    - `db.py`: yangi `market_hashtags` jadvali (`hashtag TEXT PRIMARY
      KEY`) + `list_market_hashtags()`/`add_market_hashtag()`/
      `remove_market_hashtag()`.
    - `bot.py`: Admin panelga "📰 MarketTwits hashtaglar" tugmasi
      (`admin_home_kb()`), `_admin_hashtags_view()` (ro'yxat + har biriga
      ❌ o'chirish tugmasi + ➕ qo'shish), `handle_hashtag_add()` (bitta
      xabarda bir nechta hashtag, bo'shliq/vergul bilan ajratilgan,
      # bilan/#siz qabul qilinadi) — xuddi mavjud "📢 Majburiy obuna"
      bo'limi (`_admin_channels_view`/`handle_channel_add`) andozasida.
    - `_process_markettwits_message()`: yangi `_markettwits_matches_topic()`
      — tiker topilmasa, matndagi hashtaglardan biri `market_hashtags`
      ro'yxatida bormi tekshiradi; topilsa post qilinadi, lekin
      **grafiksiz, matn-only** (chizadigan tiker yo'q — jonli yangilanish
      ham yo'q, faqat statik matn + manba havolasi).
    - Tekshirildi (mock, haqiqiy Postgres — MIGRATE orqali yangi jadval
      qo'shilgani ham tasdiqlandi): hashtag qo'shilgach curated-topic
      orqali (tikersiz) matn-only post to'g'ri yuborildi; hashtag
      o'chirilgach xuddi shu matn endi filtrlanib qolishi tasdiqlandi.
      Ikkalasida ham `newsai.analyze` chaqirilmagani ISBOTLANDI
      (chaqirilsa AssertionError otadigan qilib sinaldi). `test_tracker.py`
      9/9 — o'zgarmadi.

89. **Jonli yangilanish arxitekturasi TUBDAN o'zgartirildi: bazadan
    qayta tiklanadigan, deploy'ga TO'LIQ chidamli qilindi.** Foydalanuvchi:
    "deploy vaqtida yangilanish to'xtab qolyapti shuni deploy qilinsa ham
    davom etadigan jarayon qilsak bo'ladimi? Bot ham deploy vaqtida
    ishlamayabti". 84-banddagi tuzatish (`_spawn_background` — task
    kuchli referensda saqlash) faqat GARBAGE COLLECTION muammosini
    hal qilgan edi; Railway DEPLOY qilinganda esa butun KONTEYNER (demak
    butun Python jarayoni, xotiradagi HAMMA narsa bilan) o'zi qayta
    ishga tushadi — hech qanday kuchli referens buni saqlab qololmaydi,
    chunki jarayonning o'zi yo'qoladi. Bu 82-bandda "kutilgan cheklov"
    deb yozilgan edi, lekin foydalanuvchi buni endi ANIQ muammo sifatida
    hal qilishni so'radi.
    - Yechim: `poll_job`/`tracker.run_once()` signal-kuzatuvi qanday
      qurilgan bo'lsa (har safar BAZADAN qayta o'qiydi, xotirada HECH
      qanday holat saqlamaydi) — jonli yangilanish ham xuddi shunga
      o'tkazildi. Avvalgi `_live_update()` (har HODISAGA bitta,
      `asyncio.sleep()` sikli bilan uzoq ishlaydigan fon vazifasi,
      holati FAQAT lokal o'zgaruvchilarda) BUTUNLAY OLIB TASHLANDI.
    - `db.py`: `news_events`ga yangi ustunlar (`ALTER TABLE ADD COLUMN
      IF NOT EXISTS`) — `caption`, `render_tf`, `render_before_ms`,
      `render_label`, `render_marker_color`. `set_news_message()` endi
      caption + render-holatini ham saqlaydi (grafiksiz post uchun
      `render_tf=None` — bu "jonli yangilanish kerak emas" belgisi).
      Yangi `active_live_events(cutoff_minutes)` — hali jonli oynasi
      tugamagan (+1 daqiqa zaxira bilan) hodisalarni qaytaradi.
    - `bot.py`: yangi `news_live_job()` — BITTA umumiy `job_queue`
      vazifasi (`NEWS_REFRESH_SECONDS` interval bilan, `poll_job` kabi),
      har safar `db.active_live_events()`dan hozir aktiv BARCHA
      hodisalarni oladi, har birini qayta chizadi/tahrirlaydi, muddati
      o'tganlarni `finalize_news_outcome()` bilan yakunlaydi. Tugmalar
      (`_signal_buttons` + `_share_button`) har safar QAYTADAN
      hisoblanadi (deterministik — saqlash shart emas). 5 ta post joyi
      (`_process_news_event`, `_process_surge_candidate`,
      `_process_liquidation_spike`, `cmd_charttest`,
      `_process_markettwits_message`) endi `_spawn_background(_live_update(...))`
      chaqirmaydi — shunchaki `db.set_news_message()`ga caption/render
      parametrlarini uzatadi, xolos. `_spawn_background`/`_background_tasks`
      o'zi QOLDI — Telethon tinglovchisi (`tgsource.start_listener`)
      hali ham chinakam UZOQ ishlaydigan yagona fon vazifasi, unga
      tegishli emas.
    - Tekshirildi (mock, haqiqiy Postgres, ATAYLAB "xotira yo'q" holatda):
      post qilingandek caption/render_tf/before_ms/label bazaga to'g'ri
      yozilishi; keyin XUDDI YANGI JARAYON birinchi marta ishga
      tushgandagidek (hech qanday oldingi Python obyekti/o'zgaruvchisiz)
      `news_live_job()` chaqirilib, bazadan hodisani to'g'ri topib
      `edit_message_media` chaqirilishi (= "restart-chidamlilik" real
      isbotlandi); muddati o'tgan hodisa uchun `outcome_pct` to'g'ri
      yozilishi (finalize). `test_tracker.py` 9/9 — o'zgarmadi.

90. **MarketTwits: AI'siz tarjima (o'zbekchaga) qo'shildi + manba
    havolasi olib tashlandi.** Foydalanuvchi: "rus tilida qanday o'zbek
    tiliga o'girib keyin yuborsak bo'ladi? Keyin post tagida link chiqib
    qolyabti... uni chiqmaydigan qilish kerak".
    - **Tarjima**: yangi `translate.py` — MyMemory
      (`api.mymemory.translated.net`) orqali, bepul/kalitsiz. AVVAL
      Google Translate'ning norasmiy endpoint'i (`translate.googleapis.com`)
      sinaldi — sandbox'dan **429 "Sorry... automated queries"** bilan
      RAD ETDI (avtomatlashtirilgan so'rovlarni faol bloklaydi). MyMemory
      esa aynan shu maqsad uchun MAXSUS qurilgan rasmiy API — shuning
      uchun tanlandi.
    - `bot.py`: `_process_markettwits_message()`da yangi `_CYRILLIC_RE`
      — matnda KIRILL harflar bo'lsagina tarjima chaqiriladi (kanal
      aralash, ba'zan inglizcha post ham keladi — ularni "ru->uz"
      juftligi orqali qayta "tarjima qilish" natijani buzardi). Tarjima
      muvaffaqiyatsiz bo'lsa (`translate.to_uz()` `None` qaytarsa) — asl
      matn ishlatiladi, POST BLOKLANMAYDI. Tarjima natijasi
      `news_events.translation_uz`ga ham yoziladi (SEC/Upbit bilan bir
      xil ustun, endi MarketTwits ham to'ldiradi).
    - **Havola olib tashlandi**: caption oxiridagi
      `🔗 <a href="t.me/...">MarketTwits</a>` qatori butunlay o'chirildi
      — endi faqat sarlavha+matn, hech qanday manba havolasi ko'rinmaydi.
    - MUHIM (keyingi ishlar uchun eslatma): MyMemory'ni sandbox'dan
      real so'rov bilan sinab bo'lmadi — proxy uni ORGANIZATSIYA
      siyosati bo'yicha 403 bilan rad etadi (Telethon/MTProto'dan FARQLI
      — bu HTTPS, lekin domen oq ro'yxatda emas). Shuning uchun bu ham
      (Telethon kabi) FAQAT production'da (Railway) haqiqiy so'rov bilan
      tasdiqlanishi kerak.
    - Tekshirildi (mock, tarjima funksiyasi soxta javob bilan): kirill
      matn uchun `translate.to_uz()` chaqirilishi VA natija captionda
      to'g'ri chiqishi; lotin/ingliz matn uchun `translate.to_uz()`
      UMUMAN chaqirilmasligi (AssertionError otadigan qilib sinaldi);
      ikkalasida ham captionda "🔗"/havola YO'QLIGI tasdiqlandi.
      `test_tracker.py` 9/9 — o'zgarmadi.

91. **Tarjima haqiqiy ishlatilganda 429 (juda ko'p so'rov) bilan
    rad etayotgani aniqlandi va tuzatildi.** Foydalanuvchi ekran
    skrinshotini yubordi — real kanal posti to'g'ri tarjima qilingan
    (birinchi so'rov), lekin keyingi (`/tg_test`) so'rov ruscha holida
    qoldi. Production loglarida sabab aniq: `httpx.HTTPStatusError:
    429 Too Many Requests` — MyMemory'ning email'siz (kalitsiz) so'rov
    chegarasi tez tugab qolar ekan.
    - MyMemory hujjatiga ko'ra so'rovga ISTALGAN email qo'shilsa
      (tasdiqlanishi shart EMAS) kunlik limit sezilarli ko'tariladi —
      `config.TRANSLATE_EMAIL` (standart: loyihaga xos umumiy manzil,
      foydalanuvchining shaxsiy emaili EMAS — shunday so'ralgan/tanlangan).
      `translate.py`da har bir so'rovga `de=<email>` parametri qo'shildi.
    - Qo'shimcha: 429 kelsa 3 soniya kutib BIR MARTA qayta uriniladi
      (vaqtinchalik tirbandlikni yengish uchun — doimiy limit tugashini
      "davolamaydi", faqat burst holatlarda yordam beradi).
    - Tekshirildi (mock, soxta HTTP javob bilan): birinchi so'rov 429
      qaytarsa, IKKINCHI (qayta) so'rov muvaffaqiyatli natija berishi va
      HAR IKKALA so'rovda ham `de` parametri to'g'ri qo'shilgani
      tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

92. **MarketTwits: Rossiya bayrog'i filtri + tarjima sifati (hashtag
    aralashmasligi + HTML entity leak) tuzatildi.** Foydalanuvchi
    haqiqiy postni misol keltirdi: "#T" (MOEX'dagi T-Technologies)
    tasodifan AT&T (NYSE: T)ga o'xshab RESOLVE bo'lib qolgan (soxta
    musbat), va tarjima natijasida xom `&#10;` matni ko'rinib qoldi.
    - **Rossiya filtri**: matnda 🇷🇺 bo'lsa — tiker/hashtag mos kelsa
      HAM post UMUMAN qilinmaydi ("Rossiya bayrog'i bor xabarlar
      kelmasin" — aniq so'ralgan). Bu tekshiruv symbol/topic filtridan
      OLDIN, dedup tekshiruvidan keyin joylashtirildi.
    - **HTML entity leak** (`&#10;` xom holda ko'rinib qolishi):
      MyMemory ko'p qatorli matndagi qator ko'chirishlarni ba'zan
      `&#10;` (HTML son-entity) sifatida qaytar ekan — `translate.py`
      endi natijani darhol `html.unescape()` qiladi (Telegram bu kabi
      entitylarni ORQAGA dekodlamaydi, xom matn sifatida ko'rsatadi —
      production'da tasdiqlangan).
    - **Bog'liq topilgan xato** (shu tekshiruv paytida): `html.escape()`
      standart holda `'`/`"` belgilarni ham `&#x27;`/`&quot;`ga
      aylantiradi — Telegram buni HAM orqaga dekodlamaydi (xuddi
      `&#10;` kabi). MarketTwits caption qurilishida `quote=False`
      qo'shildi (faqat matn, HTML atribut EMAS — xavfsiz).
    - **Tarjima sifati**: hashtaglar endi matndan AJRATIB olinadi va
      TARJIMA QILINMAYDI — birga yuborilganda (masalan "#новости" so'z
      bilan aralashib) natija chalkash chiqardi (foydalanuvchi
      tasdiqlagan "#xabar berish" kabi noto'g'ri natija). Endi faqat
      asosiy matn tarjima qilinadi, hashtaglar captionning boshiga
      o'zgarishsiz qaytariladi.
    - Tekshirildi (mock): 🇷🇺 bilan post UMUMAN yuborilmasligi (RESOLVE
      bo'ladigan "#T" bo'lsa ham); hashtaglar tarjima so'roviga
      YUBORILMAGANI (`translate.to_uz` ga uzatilgan matnda yo'qligi
      tekshirildi) va captionda saqlanib qolgani; apostrof to'g'ri
      chiqishi (`e'lon`, `&#x27;lon` EMAS). Alohida, haqiqiy HTTP javob
      simulyatsiyasi bilan: `translate.to_uz()`ning o'zi `&#10;`/`&#39;`
      kabi entitylarni to'g'ri asl belgilarga (`\n`, `'`) aylantirishi
      tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

93. **Neft (WTI/Brent) tovar narxi qo'shildi — foydalanuvchi so'radi:
    "neft bilan bog'liq aktivlar kiritilmaganmi?"** Javob: neft
    KOMPANIYALARI (XOM, CVX kabi aksiyalar) allaqachon avtomatik
    ishlaydi (`stocks.py` istalgan tikerni probe qiladi), lekin xom
    neftning O'ZI (tovar narxi) ulanmagan edi — endi qo'shildi.
    - `forex.py`: metallar (`_METALS`) qanday alohida tekshirilsa,
      neft ham xuddi shunday — `_OIL_API_SYMBOLS = {"WTIUSD": "WTI/USD",
      "BRENTUSD": "BRENT/USD"}` (Twelve Data'ning `/forex_pairs`
      ro'yxatida yo'q, lekin `/time_series`/`/price` qabul qiladi).
    - **Topilgan qo'shimcha nozik joy**: `_api_symbol()`ning standart
      3+3 pozitsion bo'lish mantig'i ("EURUSD" -> "EUR/USD") 8 harfli
      "BRENTUSD"ni "BRE/NTUSD" deb NOTO'G'RI bo'lardi — shu sabab neft
      uchun ANIQ xarita ishlatildi (metallarga esa tegilmadi, ular
      baxtlicha 6 harfli).
    - **Topilgan qo'shimcha nozik joy #2**: `resolve()` avval faqat
      kvota-valyutali shaklni ("XAUUSD") tekshirar edi — MarketTwits
      hashtaglari esa odatda QISQA keladi ("#BRENT", "#XAUUSD" emas).
      Endi `resolve()` bare nomga ("BRENT") ham "USD" qo'shib qayta
      tekshiradi — bu METALLARGA HAM (avvaldan mavjud, lekin shu
      kungacha bare "#XAU" ishlamas edi) foyda berdi, qo'shimcha
      o'zgarish talab qilinmadi (bitta umumiy tuzatish).
    - Tekshirildi (mock, `forex.price`/`enabled`/`valid_symbols`
      soxta javob bilan): `_api_symbol("BRENTUSD")` to'g'ri "BRENT/USD"
      berishi; `resolve("brent")` (bare, kichik harf) narx kelsa
      "BRENTUSD" ga RESOLVE bo'lishi; narx kelmasa (probe False)
      RESOLVE BO'LMASLIGI tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

94. **MarketTwits caption'idan hashtaglar butunlay olib tashlandi.**
    Foydalanuvchi: "bot o'zi aktivni nomini yozyabti, yana hashtaglar
    ham bor ko'payib ketyabti" — 92-bandda hashtaglar caption BOSHIGA
    qaytarilardi (`#BTC #новости\n\n...`), lekin sarlavhada aktiv nomi
    (masalan "BTCUSDT") allaqachon ko'rinadi — hashtaglar shunchaki
    ortiqcha qator edi.
    - `bot.py`: `hashtag_line` butunlay olib tashlandi — hashtaglar hali
      ham matndan AJRATIB tarjima qilinadi (92-band sababiga ko'ra,
      tarjima sifatini saqlash uchun), lekin endi captionga UMUMAN
      qaytarilmaydi, faqat tashlab yuboriladi.
    - Tekshirildi (mock): caption'da "#BTC"/"#новости" kabi hashtaglar
      ENDI YO'QLIGI, faqat sarlavha+tarjima qilingan matn qolishi
      tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.

95. **MarketTwits: noto'g'ri tikerga moslashish tuzatildi — faqat
    BIRINCHI hashtag tekshiriladi.** Foydalanuvchi production'da real
    misol keltirdi: "#BE #cot" (Bloom Energy haqidagi xabar) —
    kanalga **"COTUSDT"** (kripto!) grafigi bilan postlangan, garchi
    matn Bloom Energy (NYSE: BE) aksiya opsionlari haqida bo'lsa ham.
    - **Sabab**: `_markettwits_symbol()` HAMMA hashtagni ketma-ket
      sinardi. Birinchi ("BE" — to'g'ri tiker) ehtimol vaqtinchalik xato
      (Twelve Data tezlik chegarasi — `poll_job` signal kuzatuvi allaqachon
      shu limitni faol band qilib turadi, loglarda "Twelve Data rate
      limit — kutamiz" muntazam ko'rinadi) sabab RESOLVE bo'lmay qoldi,
      shunda funksiya ALOQASIZ ikkinchi hashtag "cot"ga o'tib, u
      tasodifan haqiqiy kripto tikeriga (COTUSDT) to'g'ri kelib qoldi.
    - **Tuzatish**: endi faqat BIRINCHI hashtag tekshiriladi (MarketTwits
      konventsiyasi — asosiy tiker doim birinchi, keyingilari mavzu-teg:
      "#hisobot", "#geopolitika" kabi). Birinchi hashtag RESOLVE bo'lmasa
      — post UMUMAN qilinmaydi, ALOQASIZ hashtagga sakrab NOTO'G'RI
      grafik chizishdan ko'ra shu xavfsizroq.
    - Tekshirildi (mock): "#BE #cot" holatida "BE" muvaffaqiyatsiz
      bo'lganda ENDI "cot"ga o'tmasligi (symbol=None qaytishi) VA "BE"
      muvaffaqiyatli bo'lganda to'g'ri ishlashi ikkalasi ham tasdiqlandi.
      `test_tracker.py` 9/9 — o'zgarmadi.

96. **Savdo hajmi portlashi endi (imkon qadar) Binance ma'lumotidan.**
    Foydalanuvchi: "Binance datalarini topishimiz kerak bo'lyabti
    baribir... Likvidatsiya, Savdo hajmi oshishi binanceda pul ko'p
    aylanadi" — ya'ni "pul qayerda ko'p aylanishi" eng aniq Binance'da
    ko'rinadi, MEXC'da emas.
    - **Muhim tarixiy topilma** (`exchange.py`ning boshidagi izohdan):
      Binance **Futures** API (`fapi.binance.com`) Railway serverining
      hududini ILGARI 451 (huquqiy sabab bilan bloklash) bilan rad
      etgan — shu sabab bu loyihada MEXC ishlatiladi. Foydalanuvchiga
      shu tarix ochiq aytildi (AskUserQuestion orqali) — u baribir
      Binance **Spot** API'sini (boshqa domen, ehtimol bloklanmagan)
      sinashni tanladi.
    - **Likvidatsiya allaqachon Binance'dan** — `liquidations.py`
      (Coinalyze, `.A` = Binance market kodi) o'zgarishsiz qoldi,
      bu band shunchaki tasdiqlash edi.
    - `exchange.py`: yangi `volume_ticker_24hr()` — avval Binance Spot
      (`api.binance.com/api/v3/ticker/24hr`) sinaydi, XATO bo'lsa
      (masalan 451 yana chiqsa) JIMGINA mavjud `ticker_24hr()`
      (MEXC)ga qaytadi — hech narsa to'xtamaydi. Ikkala API bir xil
      maydon nomlarini (`symbol`/`quoteVolume`) qaytargani uchun
      umumiy `_parse_ticker_24hr()` ga chiqarildi (nusxa ko'paytirilmadi).
    - `bot.py`: `volume_snapshot_job()` endi `exchange.ticker_24hr()`
      o'rniga `exchange.volume_ticker_24hr()` chaqiradi.
    - Tekshirildi (mock, `httpx` client'lar soxta javob bilan): Binance
      muvaffaqiyatli bo'lganda undan foydalanilishi; Binance xato
      (masalan "451 Blocked") qaytarganda JIMGINA MEXC'ga o'tilishi
      ikkalasi ham tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.
      **Haqiqiy Binance Spot'ning Railway'dan ochiqligi hali
      production'da tasdiqlanmagan** — keyingi deploy loglarida
      tekshiriladi (agar Binance so'rovi muvaffaqiyatsiz bo'lsa,
      "Binance hajm surati olinmadi" ogohlantirishi ko'rinadi va
      tizim baribir MEXC bilan ishlashda davom etadi).
    - **Production'da TASDIQLANDI (deploydan 30s keyin, `volume_snapshot_job`
      birinchi yurishida)**: Binance **Spot** API (`api.binance.com`) HAM
      451 bilan rad etadi — xuddi ilgari Futures (`fapi.binance.com`)
      kabi: `httpx.HTTPStatusError: Client error '451' for url
      'https://api.binance.com/api/v3/ticker/24hr'`. Railway'ning
      hozirgi hosting hududi Binance tomonidan TO'LIQ (Spot + Futures)
      bloklangan degani. Fallback mexanizmi mo'ljallangandek ishladi —
      xato ushlanib, MEXC'ga jimgina o'tdi, `volume_snapshot_job`
      "executed successfully" bilan yakunlandi, hech narsa buzilmadi.
      Amaliy natija: hozircha (Railway hudud o'zgarmaguncha) tizim
      baribir MEXC ma'lumotidan foydalanadi — kod o'zgarishsiz qoldi
      (kelajakda Binance ochilib qolsa, avtomatik ishlay boshlaydi,
      qayta deploy shart emas).

97. **Binance yangi listinglari qo'shildi — foydalanuvchi haqiqiy
    JSON API'ni topib berdi.** Ilgari cryptocurrencyalerting.com'ning
    bepul rejasi webhook bermasligi sabab listing manbai "hozircha kod
    tashqarisida" qoldirilgan edi. Foydalanuvchi shu sayt sahifasi
    (`binance-new-listings.html`) ORTIDAGI haqiqiy, kalitsiz JSON
    endpoint'ni (`main.min.js` faylidan) topib, standalone Python
    skript namunasi bilan taqdim etdi: `GET
    https://api.cryptocurrencyalerting.com/binance-new-coins` —
    `[{"code","name","exchange","alert_id","created_at","type",
    "market_url"}, ...]`.
    - **AI ISHLATILMAYDI** — MarketTwits qanday AI'siz bo'lsa xuddi
      shunday, lekin sababi BOSHQA: bu yerda ma'lumot ALLAQACHON
      tuzilgan (aniq tiker/nom/vaqt) — "muhimmi-yo'qmi" filtri kerak
      emas (yangi listing o'zi allaqachon signal), tarjima ham shart
      emas (shablon matn: "{nom} ({tiker}) Binance'da yangi ro'yxatga
      olindi").
    - `listings.py`: yangi `binance_scan(since)` — Upbit bilan BIR XIL
      shakl EMAS (AI kerak emasligi uchun `_process_news_event()`dan
      MUSTAQIL); `code`/`name`/`event_at`/`market_url` maydonlari bilan
      qaytaradi. `since` filtri MUHIM — API oylar oldingi tarixni ham
      qaytaradi, filtrsiz birinchi ishga tushishda o'nlab eski post
      "toshib ketardi".
    - `bot.py`: yangi `_process_binance_listing()` + `binance_listing_job()`
      (har 90s, `news_scan_job` bilan bir xil davriylik). Tiker
      `exchange.resolve()` orqali MEXC'da qidiriladi — YANGI listing
      ko'pincha bizning kuzatuvimizdagi birjada HALI yo'q, shunda
      matn-only post (grafiksiz, lekin baribir foydali — "yangi tanga
      qo'shildi" xabari).
    - **MUHIM tuzatish shu band paytida topildi**: birinchi yozganda
      ESKIRGAN naqsh (`_spawn_background(_live_update(...))`)
      ishlatilgan edi — bu funksiya ENDI MAVJUD EMAS (avvalroq, 83-90
      bandlar oralig'idagi ishda, "deploy vaqtida yangilanish to'xtab
      qolyabti" muammosi butunlay YANGI arxitektura — `news_live_job`,
      DB'dagi `render_tf`/`render_label` ustunlari orqali — bilan hal
      qilingan, `_live_update` o'chirilgan). Kod `py_compile`da xato
      bermadi (chunki `_spawn_background`ning o'zi hali mavjud, faqat
      `_live_update` yo'q edi — bu `NameError` sifatida FAQAT ishga
      tushganda chiqardi), lekin `db.set_news_message()`ning yangi
      imzosi (`caption` MAJBURIY parametr) mock testda DARHOL
      `TypeError` berdi — shu orqali xato ishlab chiqarishdan OLDIN
      ushlandi. To'g'rilanib, boshqa 6 ta chaqiruv joyi (SEC/Upbit,
      likvidatsiya, surge, MarketTwits, /charttest) bilan BIR XIL
      naqshga (`db.set_news_message(eid, msg_id, caption, render_tf=...,
      render_label=...)`, spawn YO'Q) moslashtirildi.
    - Tekshirildi (mock, haqiqiy Postgres): `binance_scan()` 24 soatdan
      eski yozuvni to'g'ri filtrlashi; tiker MEXC'da topilmasa matn-only
      post to'g'ri chiqishi; tiker topilsa GRAFIKLI post va bazada
      `render_tf='1m'`/`render_label='Listing'` to'g'ri saqlanishi
      (`news_live_job` buni "aktiv" deb topishi uchun MUHIM); dedup
      ishlashi — barchasi tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.
    - **Hali production'da haqiqiy so'rov bilan sinalmagan** (domen
      sandbox'da bloklangan) — keyingi deploydan keyin Railway
      loglarida tasdiqlanishi kerak.
    - **Production'da TASDIQLANDI** (keyingi deploy, `first=60`dan keyin):
      `binance_listing_job` xatosiz ("executed successfully", "olinmadi"
      ogohlantirishisiz) ishladi — `api.cryptocurrencyalerting.com`
      domeni Railway'dan ochiq.

98. **Coinbase va Kraken ham qo'shildi (xuddi shu sayt orqali) —
    foydalanuvchi so'radi: "coinbase va kreken ham shu sayt orqali
    olish imkoni bormi?"** Saytning boshqa sahifalari ("New Coinbase
    Listings", "New Kraken Listings") ham xuddi Binance'niki kabi naqshda
    (`{apiHost}/{birja}-new-coins`) ishlaydi deb TAXMIN qilindi — bu
    Binance endpoint'i qanday tasdiqlanganidan FARQLI (o'sha
    foydalanuvchi tomonidan aniq topilgan edi), hali sinalmagan taxmin.
    - `listings.py`: `binance_scan()` UMUMIY `exchange_listing_scan(exchange,
      since)` funksiyasiga qayta quriladi (`EXCHANGE_LISTING_URLS`
      lug'ati — Binance/Coinbase/Kraken), uchtasi ham shu bitta
      funksiyadan foydalanadigan yengil o'rovchilarga (`binance_scan`/
      `coinbase_scan`/`kraken_scan`) ega. Natija itemiga `exchange`
      maydoni qo'shildi.
    - `bot.py`: `_process_binance_listing()` -> `_process_exchange_listing()`
      (umumiy, `item["exchange"]` orqali sarlavha/caption/external_key
      moslashadi — "Binance'da"/"Coinbase'da"/"Kraken'da"). `binance_listing_job()`
      (nomi saqlanib qoldi, funksiyasi kengaydi) endi
      `EXCHANGE_LISTING_SCANNERS` lug'ati orqali UCHALASINI ham,
      HAR BIRINI ALOHIDA try/except bilan chaqiradi — Coinbase/Kraken
      (hali tasdiqlanmagan) ishlamasa ham, Binance (tasdiqlangan)
      baribir ishlashda davom etadi.
    - Tekshirildi (mock): `_process_exchange_listing()` Coinbase itemi
      bilan to'g'ri caption ("Coinbase'da yangi ro'yxatga olindi")
      chiqarishi tasdiqlandi. `test_tracker.py` 9/9 — o'zgarmadi.
    - **Coinbase/Kraken endpoint'lari hali production'da sinalmagan** —
      keyingi deploy loglarida tasdiqlanishi kerak (Binance'dan farqli,
      bular ENDPOINT NOMI TAXMIN qilingan, browser orqali tasdiqlanmagan).

99. **Coinbase/Kraken taxmini production'da SINALDI VA NOTO'G'RI chiqdi —
    ikkalasi ham kod bazasidan OLIB TASHLANDI, faqat Binance qoldi.**
    #98'dagi taxmin ikki bosqichda tekshirildi (Railway logi):
    - 1-urinish: `httpx.AsyncClient(follow_redirects=True)` YO'Q holda
      `/coinbase-new-coins` va `/kraken-new-coins` — ikkalasi ham
      **301 Moved Permanently** qaytardi (`raise_for_status()` buni ham
      xato deb hisoblaydi). `follow_redirects=True` qo'shib qayta
      deploy qilindi.
    - 2-urinish: redirect endi ergashildi, lekin javob TANASI BO'SH —
      `JSONDecodeError: Expecting value`. Sababni aniqlash uchun
      vaqtinchalik `log.info(url/status/len/body)` qo'shildi, qayta
      deploy qilindi — natija: ikkalasi ham `.../404` manziliga redirect
      bo'lib, saytning STANDART Rails 404 HTML sahifasini qaytargan
      ekan. Xulosa: `/coinbase-new-coins` va `/kraken-new-coins`
      MANZILLARI UMUMAN MAVJUD EMAS — cryptocurrencyalerting.com'da
      Binance uchungina shu naqshdagi ochiq endpoint bor, Coinbase/
      Kraken uchun YO'Q (ehtimol ular boshqa mexanizm — masalan faqat
      to'lovli Trader reja/webhook — talab qiladi).
    - Tuzatish: `listings.py`dagi `EXCHANGE_LISTING_URLS`dan Coinbase/
      Kraken o'chirildi (faqat Binance qoldi), `coinbase_scan()`/
      `kraken_scan()` o'rovchilari va vaqtinchalik diagnostika logi
      olib tashlandi. `bot.py`dagi `EXCHANGE_LISTING_SCANNERS`dan ham
      ikkalasi o'chirildi — endi faqat Binance skanerlanadi (avvalgi
      per-birja try/except arxitekturasi tufayli bu ham bitta qatorlik
      o'zgarish bo'ldi).
    - **Saboq**: taxmin qilingan API manzillarini HAR DOIM production
      logida haqiqiy javob (status+tana) bilan tekshirish kerak — "xato
      chiqmasligi" (masalan 301) hali "ishlayapti" degani emas, chunki
      httpx standart holatda redirectga ergashmaydi va uni xatoga
      chiqaradi; ergashtirilgandan keyin ham natija haqiqiy JSON emas,
      404 sahifa bo'lishi mumkin — shuning uchun status/tana matnini
      ko'rmasdan "ishladi" deb xulosa chiqarib bo'lmaydi.

100. **Foydalanuvchi: "economic calendar ishlamadi soat 12:00 da xabar
     kelmadi"** — production loglari tekshirildi (Railway):
     - Diagnostika (vaqtinchalik log): `TZ=Asia/Tashkent`,
       `ECON_DIGEST_HOUR=12`, `NEWS_CHANNEL_ID` sozlangan — sozlamalarda
       xato YO'Q.
     - `econ_job` bugun (2026-08-26) soat 07:00:43 UTC (=12:00:43
       Toshkent)da xatosiz ("executed successfully") ishlagan.
     - Bazadagi "digest bugun yuborilganmi" bayrog'i (`econ_calendar_state`,
       kind='digest') **True** — bu bayroq FAQAT bitta joyda (`econ_job`
       ichida, `send_message`dan BEVOSITA OLDIN) belgilanadi, boshqa hech
       qanday admin buyruq yoki test yo'li uni belgilamaydi.
     - Butun kun davomidagi (barcha deploy) loglarda "Iqtisodiy taqvim
       digest yuborilmadi" xatosi (`log.exception`, `send_message`
       muvaffaqiyatsiz bo'lsa chiqadi) **HECH QACHON ko'rinmadi**.
     - Xulosa: kodda xato TOPILMADI — barcha belgilar xabar 12:00'da
       NEWS_CHANNEL_ID kanaliga MUVAFFAQIYATLI yuborilganini ko'rsatadi
       (xuddi shu kanalga MarketTwits/listing postlari ham muammosiz
       borayotgani allaqachon tasdiqlangan). Foydalanuvchiga shu kanalni
       (soat 12:00 atrofida) qayta tekshirish so'raldi — agar haqiqatan
       ham yo'q bo'lsa, muammo Telegram tomonida yoki boshqa sababda
       bo'lishi mumkin, kod darajasida hozircha aniqlanmadi.
     - Diagnostika loglari (startup va har-tsiklli) tekshiruvdan keyin
       kod bazasidan olib tashlandi (vaqtinchalik edi).

101. **Foydalanuvchi: "likvidatsiya bilan bog'liq xabarlar rasmi
     yangilanmayabti"** — TOPILDI VA TUZATILDI (haqiqiy xato edi).
     - Diagnostika (vaqtinchalik loglar): `news_live_job` likvidatsiya
       postlarini har 4s tekshirar, `_paced_media_edit()` har safar
       Telegram'dan "message is not modified" javobini olar edi (kod bu
       holatni xato deb hisoblamay, jimgina "muvaffaqiyatli" deb
       belgilaydi — shu sabab tashqaridan sezilmasdi). Solishtirish
       uchun bir xil tsiklda boshqa manba (surge) posti HAR safar
       HAQIQIY yangilanardi.
     - **Ildiz sabab**: `_news_render()`dagi `limit = min(chart.MAX_CANDLES,
       200)` QATTIQ 200ga cheklangan edi. Likvidatsiya `liq_before_ms =
       4 soat` (1 daqiqalik shamlarda = 240 dona) ishlatadi — bu 200
       chegaradan OSHIB ketadi. MEXC `/klines`da `startTime`+`endTime`
       ikkalasi berilganda ham natija `limit`ga qarab START tomondan
       kesiladi (oxirigacha YETMAYDI) — natijada qaytgan shamlar HAR
       DOIM `start_ms`dan boshlab, "hozir"gacha yetmasdan, bir xil
       (harakatsiz) massiv bo'lib qolar edi — grafik doim BAYT-BAYT bir
       xil chiqib, Telegram tahrirlashni rad etardi. Boshqa manbalar
       (SEC/listing — standart 60 daqiqa, surge — 4 kun lekin 1 SOATLIK
       shamlarda = 96 dona) 200 chegaradan hech qachon oshmagani uchun
       muammo faqat likvidatsiyada ko'rinardi.
     - **Tuzatish** (`bot.py`, `_news_render()`): `limit` endi haqiqiy
       oyna kengligidan ([start_ms, end_ms] + jonli o'sish zaxirasi)
       DINAMIK hisoblanadi: `needed = (end_ms-start_ms)//shamDavomiyligi +
       NEWS_LIVE_MINUTES//shamDavomiyligi + 10`, `limit = min(MAX_CANDLES,
       max(200, needed))`. Standart holatlar (SEC/listing/surge) uchun
       natija o'zgarmadi (baribir 200 dan kichik chiqadi — sinov bilan
       tasdiqlandi), likvidatsiya uchun endi ~270-290 chiqadi (to'liq
       4 soat + jonli o'sishni qamrab oladi).
     - Tekshirildi: `chart.py`/`config.py`ni bevosita import qilib
       (bot.py to'liq import qilinmasdan — bu muhitda `cryptography`
       paketi buzilgan, loyihaga aloqasi yo'q) `needed`/`limit`
       hisob-kitobi qo'lda tasdiqlandi. `test_tracker.py` 9/9 —
       o'zgarmadi.
     - Diagnostika loglari (barchasi) tekshiruvdan keyin olib tashlandi.
     - **Keyingi qadam**: production'da yangi likvidatsiya posti chiqqach
       (yoki mavjud faol posting'lar orqali) grafik endi haqiqatan
       yangilanayotganini Railway logida ("message is not modified"
       o'rniga haqiqiy tahrirlash) tasdiqlash kerak.

102. **Foydalanuvchi: "Savdo hajmi keskin oshdi xabaridagi grafik taym
     freymi 1D yoki 4h lik bo'lsin."** Ikkalasidan qaysi birini
     tanlashini va oyna kengligini ham so'radim:
     - Taym freym: **1D (kunlik)** tanlandi.
     - Oyna kengligi: xabar matni "N kunlik pasayish" deydi
       (`SURGE_DECLINE_DAYS=30`), lekin grafik oldin faqat oxirgi 4
       kunni ko'rsatardi (matn/grafik NOMOS edi) — foydalanuvchi buni
       ham **30 kunga kengaytirishni** tanladi (grafik endi matndagi
       davrni to'liq qamrab oladi).
     - `bot.py` `_process_surge_candidate()`: `_news_render(...)`
       chaqiruvi `tf="1h"` -> `tf="1d"`, `surge_before_ms = 4 *
       86_400_000` (qattiq 4 kun) -> `config.SURGE_DECLINE_DAYS *
       86_400_000` (dinamik, standart 30 kun). `db.set_news_message(...,
       render_tf=...)` ham `"1h"` -> `"1d"`ga mos yangilandi (jonli
       yangilanish endi ham 1D shamlarda davom etadi).
     - Eski izoh (4 kun ataylab `limit=200`dan past qoldirilgani haqida)
       yangilandi — #101'da `_news_render()`ning `limit` chegarasi
       dinamik hisoblanadigan qilib tuzatilgani uchun bu cheklov endi
       muammo emas (30 kunlik shamlar soni — 30 — baribir 200dan ancha
       past).
     - Tekshirildi: `test_tracker.py` 9/9 — o'zgarmadi (tracker.py'ga
       tegilmadi).

103. **Foydalanuvchi: "Keyin harbir grafikda taym freym ko'rinib
     tursin."** Signal grafigi (`chart._render()`, LONG/SHORT
     tugmalar chizadigan asosiy grafik) allaqachon tf'ni sarlavha
     ostida ko'rsatib kelayotgan edi ("· 1m" kabi) — lekin News Trade
     AI/listing/likvidatsiya/hajm-portlashi grafigi (`chart.news_chart()`)
     buni umuman ko'rsatmasdi.
     - `chart.news_chart()`: yangi ixtiyoriy `tf: str | None = None`
       parametri qo'shildi, berilsa `_render()`dagi bilan bir xil
       uslubda ("· {tf}") sarlavha (symbol) ostiga chiziladi.
     - `bot.py` `_news_render()`: `chart.news_chart(...)` chaqiruviga
       `tf=tf` qo'shildi — bu ORTIQCHA parametr talab qilmaydi, chunki
       `_news_render()` allaqachon `tf` argumentini oladi va endi uni
       grafik chizuvchi funksiyaga ham uzatadi. Natijada `_news_render()`
       orqali o'tuvchi BARCHA post turlari (SEC/listing "1m", likvidatsiya
       "1m", hajm portlashi "1d", /charttest ixtiyoriy) avtomatik tf
       ko'rsatadigan bo'ldi — alohida har bir chaqiruv joyini
       o'zgartirish shart bo'lmadi.
     - Tekshirildi: `chart.news_chart()` to'g'ridan-to'g'ri soxta
       shamlar bilan chaqirilib (tf bilan VA tf'siz — orqaga
       muvofiqlik uchun) PNG muvaffaqiyatli chiqishi tasdiqlandi,
       natija rasmi foydalanuvchiga ko'rsatildi. `test_tracker.py`
       9/9 — o'zgarmadi.

104. **Foydalanuvchi: "men likvidatsiya xabarida oddiy chart emas
     heatmap chiqishini xoxlayabman"** — CoinGlass uslubidagi narx-
     klaster heatmap kerakligi aniqlashtirildi (AskUserQuestion orqali:
     CoinGlass uslubi vs o'zimizning vaqt-asosli heatmap — birinchisi
     tanlandi).
     - **CoinGlass'ning o'zi**: WebSearch+WebFetch bilan tekshirildi —
       `/liquidation-heatmap` endpoint'i FAQAT Professional ($699/oy)
       yoki Enterprise tarifda ochiq (GitHub'dagi rasmiy API docs
       mirror'ida ✅/❌ jadvali bilan tasdiqlangan) — Hobbyist/Startup/
       Standard'da YOPIQ. Juda qimmat, mos emas.
     - Foydalanuvchi "boshqa saytdan izlab koramizmi?" so'radi —
       WebSearch orqali muqobillar qidirildi: Hyblock Capital eng
       istiqbolli chiqdi (bepul tarifda shu turdagi endpoint bor
       ko'rinardi), lekin ularning docs sahifalari sandbox'da
       bloklangan edi. **Foydalanuvchi o'zi Hyblock'da bepul hisob
       ochib**, avval OAuth2 autentifikatsiya hujjatini, keyin
       `/liquidationHeatmap` endpoint'ining TO'LIQ rasmiy OpenAPI
       spetsifikatsiyasini (YAML) yuborib berdi — bu ilgari
       cryptocurrencyalerting.com bilan bo'lgan holatga o'xshash
       ("foydalanuvchi sandbox yeta olmagan joyni o'zi tekshiradi").
     - **`hyblock.py`** (yangi modul): OAuth2 Client Credentials oqimi
       — `POST /oauth2/token` (`x-api-key` header + Basic Auth
       `client_id:client_secret`) orqali `access_token` olinadi,
       xotirada `expires_in`ga qarab keshlanadi (60s zaxira bilan),
       401 kelsa BIR marta majburiy yangilanadi. `liquidation_heatmap
       (coin, lookback)` — `GET /liquidationHeatmap?coin=BTC&lookback=
       12h` so'raydi, `data` ro'yxatini (`{startingPrice, endingPrice,
       side, size, timestamp}`) qaytaradi. `HYBLOCK_API_KEY`/
       `_CLIENT_ID`/`_CLIENT_SECRET` (Railway'da, bo'sh bo'lsa modul
       jimgina o'chadi) — `config.py`ga qo'shildi.
     - **`chart.py`**: yangi `liquidation_heatmap_chart(buckets, coin,
       lookback)` — narx (Y) va vaqt (X) panjarasida `pcolormesh`
       (`inferno` rang xaritasi) bilan issiqlik xaritasi chizadi (bir
       xil narx+vaqt katagida ikkala tomon — long/short — `size`lari
       QO'SHILADI, chunki bu yerda yo'nalish emas, UMUMIY klaster
       zichligi ko'rsatiladi). `news_chart()`dan/`_draw_candles`dan
       BUTUNLAY ALOHIDA (mavjud shamli grafiklarga tegilmadi).
     - **`bot.py`**: yangi `_liquidation_heatmap_photo(base)` yordamchisi
       — Hyblock heatmap muvaffaqiyatli bo'lsa PNG qaytaradi, aks holda
       `None` (chaqiruvchi shunda MAVJUD shamli grafikka qaytadi —
       xatarsiz fallback, xuddi boshqa manbalar 451/404 bo'lganda
       qanday ishlagan bo'lsa). `_process_liquidation_spike()`: avval
       odatdagidek `_news_render()` chaqiriladi (bu `live_pct`/keyinги
       `finalize_news_outcome` hisobi UCHUN saqlanib qoladi —
       O'ZGARTIRILMADI), so'ng heatmap muvaffaqiyatli bo'lsa faqat
       YUBORILADIGAN RASM heatmap bilan ALMASHTIRILADI. `news_live_job()`:
       `row["source"] == "liquidation"` bo'lsa xuddi shunday heatmap'ga
       urinadi (jonli yangilanish davomida ham heatmap davom etadi).
     - Tekshirildi (mock, production kalitlarisiz): token olish, token
       keshlash (ikkinchi chaqiruvda POST QAYTA yubormasligi), 401'dan
       keyin BIR marta qayta token olish, kalitlar bo'sh bo'lganda
       so'rov umuman yubormaslik, `chart.liquidation_heatmap_chart()`
       haqiqiy PNG chiqarishi (foydalanuvchiga ko'rsatildi) va bo'sh/
       nol ma'lumotda `None` qaytarishi — barchasi tasdiqlandi.
       `test_tracker.py` 9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy Hyblock kalitlari bilan sinalmagan**
       — foydalanuvchidan `HYBLOCK_API_KEY`/`HYBLOCK_CLIENT_ID`/
       `HYBLOCK_CLIENT_SECRET` so'ralmoqda (Railway o'zgaruvchisi
       sifatida, kodga/CLAUDE.md'ga yozilmaydi).

105. **#104'dagi Hyblock Capital PULLIK bo'lib chiqdi (foydalanuvchi
     o'zi tekshirdi: "pullik ekan") — CoinAnk bilan ALMASHTIRILDI.**
     AskUserQuestion orqali yo'l so'ralganda foydalanuvchi savolni
     rad etib, o'zi "upbitdagidek malumotni olib kormaymizmi?" taklif
     qildi — ya'ni Upbit/cryptocurrencyalerting.com'da qanday qilingan
     bo'lsa, brauzer DevTools orqali biror bepul veb-sahifa ortidagi
     ICHKI JSON so'rovini topish. Foydalanuvchi **Claude in Chrome**
     orqali (29 ta amal) buni bajardi: `coinank.com`ning bepul heatmap
     sahifasi ortida `api.coinank.com/api/liqMap/getLiqHeatMap`
     endpoint'ini topdi va **login/token'siz (guest) holatda ham
     Python orqali to'g'ridan-to'g'ri ishlashini shaxsan tekshirdi**
     (200 OK).
     - `hyblock.py` BUTUNLAY O'CHIRILDI (o'rniga endi ishlatilmaydigan,
       pullik xizmat kodini saqlash ma'nosiz), o'rniga **`coinank.py`**
       yozildi — ancha SODDA (OAuth2 yo'q, faqat statik
       `coinank-apikey` header'i). `GET /getLiqHeatMap?exchangeName=
       Binance&symbol=...&interval=...` so'raydi, javobdagi
       `data.liqHeatMap.{data,chartTimeArray,priceArray}` uchligini
       `chart.liquidation_heatmap_chart()` kutgan umumiy `{startingPrice,
       timestamp, size}` shakliga o'giradi (shu sabab `chart.py`ga
       HECH QANDAY o'zgarish kerak bo'lmadi — faqat izohlar/parametr
       nomi `lookback`->`interval`ga yangilandi, mantiq bir xil qoldi).
     - **MUHIM OGOHLANTIRISH** (kodda ham yozilgan): bu RASMIY,
       hujjatlashtirilgan ochiq API EMAS — saytning frontend'i
       ishlatadigan ICHKI chaqiruv. `coinank-apikey` sayt darajasidagi
       STATIK kalit (shaxsiy hisob emas) — istalgan payt CoinAnk
       tomonidan o'zgartirilishi yoki bloklanishi mumkin. Shu sabab
       qattiq kodga yozilmadi, `COINANK_API_KEY` (Railway o'zgaruvchisi)
       orqali beriladi — agar kelajakda ishlamay qolsa, xuddi shu
       usulda (DevTools -> Network -> `getLiqHeatMap`) qayta olib,
       FAQAT o'zgaruvchini yangilash kifoya (qayta deploy shart emas).
     - `config.py`: `HYBLOCK_*` o'chirildi, `COINANK_API_KEY`/
       `COINANK_INTERVAL` (standart `"1d"`) qo'shildi.
     - `bot.py`: `import hyblock` -> `import coinank`,
       `_liquidation_heatmap_photo()` endi ikkita parametr oladi
       (`symbol` — CoinAnk so'rovi uchun to'liq juftlik, `base` —
       grafik sarlavhasi uchun) — CoinAnk'ning `symbol` parametri
       Hyblock'ning `coin`idan farqli, quote QO'SHILGAN holda kerak
       (masalan "ETHUSDT", "BTC" emas).
     - Tekshirildi (mock, foydalanuvchi yuborgan haqiqiy javob
       namunasiga asoslanib): to'g'ri parametrlar (`symbol`,
       `exchangeName=Binance`, `coinank-apikey` header) bilan so'ralishi,
       `size=0` nuqtalarning chiqarib tashlanishi, `[xIndex,yIndex,size]`
       uchliklarning `chartTimeArray`/`priceArray` orqali to'g'ri
       narx/vaqtga o'girilishi, o'chirilgan holatda so'rov umuman
       yubormasligi, `success:false` javobida `None` qaytarishi va
       yakuniy PNG chiqishi — barchasi tasdiqlandi (rasm foydalanuvchiga
       ko'rsatildi). `test_tracker.py` 9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy `coinank-apikey` bilan sinalmagan**
       — foydalanuvchi yuborgan kalit Railway'ga qo'yilgach keyingi
       deployda tasdiqlanadi.

106. **`/heatmaptest` admin buyrug'i qo'shildi** — CoinAnk heatmap
     zanjirini haqiqiy likvidatsiya hodisasini kutmasdan sinash uchun
     (`/charttest`ning heatmap versiyasi). `/heatmaptest ETH` — tikerni
     MEXC orqali tasdiqlaydi, `_liquidation_heatmap_photo()`ni
     to'g'ridan-to'g'ri chaqiradi, natijani (rasm yoki xato sababi)
     SHU CHATGA yuboradi — kanalga POSTLAMAYDI. `set_my_commands`ga
     ataylab qo'shilmagan (faqat super-admin, `/charttest` qanday
     bo'lsa xuddi shunday).
     - Haqiqiy `COINANK_API_KEY` (foydalanuvchi yuborgan) Railway
       o'zgaruvchisiga qo'yildi. Keyingi tekshiruv: `/heatmaptest`
       orqali production'da chindan ishlashini tasdiqlash (sandbox
       `api.coinank.com`ni bloklagani uchun bu yerdan sinab bo'lmadi —
       `curl` "CONNECT tunnel failed, response 403" bilan rad etdi).

107. **CoinAnk ham ishlamadi — production'da 403 "system error" qaytardi
     (server/datacenter IP bloklangan ko'rinadi, Binance 451'iga
     o'xshash, lekin geografik emas — botga qarshi himoya). Brauzerga
     o'xshash `Origin`/`Referer`/Chrome User-Agent sarlavhalari
     qo'shib ko'rildi — YORDAM BERMADI, xato o'zgarmadi. Foydalanuvchi:
     "shamda qolaqolsin" — heatmap g'oyasidan BUTUNLAY voz kechildi.**
     - `coinank.py` o'chirildi, `chart.py`dagi `liquidation_heatmap_chart()`
       (va faqat shu yerda ishlatilgan `import numpy as np`) olib
       tashlandi, `config.py`dagi `COINANK_API_KEY`/`COINANK_INTERVAL`
       o'chirildi, `bot.py`dagi barcha izlar (`import coinank`,
       `_liquidation_heatmap_photo()`, ikkala chaqiruv joyi —
       `_process_liquidation_spike()` va `news_live_job()`,
       `/heatmaptest` buyrug'i va uning handler ro'yxatdan
       o'tkazilishi) butunlay olib tashlandi. `COINANK_API_KEY`
       Railway'da bo'shatildi.
     - Likvidatsiya posti #101'dagi (klines `limit` dinamik hisoblash
       tuzatilgandan keyingi) holatiga to'liq qaytdi — faqat oddiy
       shamli grafik, hech qanday heatmap.
     - **To'liq saboq (#98-#107 yo'li)**: CoinGlass ($699/oy) ->
       Hyblock Capital (amalda pullik) -> CoinAnk (bepul ko'rindi,
       lekin server IP bloklandi) — UCHALASI HAM ishlamadi, ikkitasi
       narx, bittasi botga qarshi himoya sababli. Xulosa: "brauzerda
       bepul ko'ringan narsa" serverdan (Railway) doim ham ishlayvermaydi
       — buni ANIQ tasdiqlash uchun albatta production'da (sandbox'da
       emas) sinash kerak, xuddi shu holatda ham bo'lgani kabi.
     - `test_tracker.py` 9/9 — o'zgarmadi (bu butun epizod davomida
       hech qachon buzilmagan).

108. **Foydalanuvchi Hyblock Capital veb-sahifasidagi ko'rinishni
     yoqtirib, "jurnaldagi kiritilgan signallarga ham qoysak bo'ladimi?"
     so'radi — HAQIQIY MEXC savdo ma'lumotidan Volume + Volume Delta
     panellari endi HAM hajm portlashi (surge) postida, HAM jurnal
     signal grafiklarida (`setup_chart()`/`signal_chart()`) ishlaydi.**
     - Foydalanuvchi tasdiqladi: jurnal grafiklari (`_render()` orqali,
       `setup_chart()` — signal E'LON QILINGANDA, `signal_chart()` —
       YOPILGANDA) FAQAT BIR MARTA chiziladi, News Trade AI'ning har-
       4-soniyalik jonli yangilanishidek TAKROR emas — shuning uchun
       MEXC tezlik chegarasi xavfi bu yerda YO'Q, xavfsiz qo'shildi.
     - `exchange.py`: `_agg_trades(symbol, start_ms, end_ms)` — MEXC
       `/aggTrades`ni SAHIFALAB (`startTime`ni oxirgi savdodan keyingiga
       surib) oladi, 429/tarmoq xatosida QISMAN natija bilan jimgina
       to'xtaydi, `AGG_TRADES_MAX=60000` xavfsizlik devori bilan.
       `volume_delta_profile(symbol, start_ms, end_ms, lo, hi, n_bins)` —
       `m` (`isBuyerMaker`) maydoni orqali xarid/sotuvni ajratib, narx
       darajasi bo'yicha `(vol_bins, delta_bins)` qaytaradi.
     - `chart.py`: `_draw_side_profiles()` — Volume/Volume Delta
       panellarini chizuvchi UMUMIY yordamchi (`_render()` va
       `surge_profile_chart()` ikkalasida ham ishlatiladi, kod
       takrorlanishining oldini olish uchun). `_render()`ga ixtiyoriy
       `vol_bins`/`delta_bins`/`bin_lo`/`bin_size` parametrlari qo'shildi
       — berilsa uch ustunli (GridSpec: narx+Volume+Volume Delta)
       joylashuvga o'tadi, berilmasa (barcha ESKI chaqiruvlar) xatti-
       harakat BUTUNLAY O'ZGARMAYDI (bitta o'qli, ichki hajm profili
       bilan). `_delta_profile()` — `setup_chart()`/`signal_chart()`
       uchun umumiy: FAQAT kripto uchun (aksiya/forex'da tarixiy savdo
       ma'lumoti yo'q), oxirgi `DELTA_WINDOW_MS` (48 soat — #107'dagi
       MEXC `limit=1000` cheklovi sababli 30 kun EMAS) ichidan hisoblaydi,
       har qanday xato — `None` (chaqiruvchi ODDIY, profilsiz grafikka
       xatarsiz qaytadi).
     - `db.py`: yangi `profile_data JSONB` ustuni (`news_events`) +
       `set_news_profile(event_id, vol_bins, delta_bins, bin_lo,
       bin_size)` — surge posti uchun BIR MARTA hisoblangan profilni
       saqlaydi. Haqiqiy Postgres bilan JSONB yozish/o'qish (`$2::jsonb`
       cast, asyncpg bu ustunni xom JSON matni sifatida qaytaradi)
       TASDIQLANDI.
     - `bot.py`: `_news_render()` ikkiga bo'lindi — `_news_candles()`
       (shamlar/`news_idx`/`live_pct`ni hisoblaydi, RASM CHIZMAYDI) va
       yupqa `_news_render()` (`chart.news_chart()` chizadi, BARCHA ESKI
       chaqiruvchilar — SEC/listing/likvidatsiya — o'zgarishsiz davom
       etadi). `_process_surge_candidate()`: endi `_news_candles()` +
       `exchange.volume_delta_profile()` (48 soat) chaqiradi, muvaffaqiyatli
       bo'lsa `chart.surge_profile_chart()`, aks holda oddiy
       `chart.news_chart()` (fallback) — natija `db.set_news_profile()`
       bilan saqlanadi. `news_live_job()`: `row["profile_data"]` mavjud
       bo'lsa CACHED bin'lar + YANGI shamlar bilan `chart.surge_profile_
       chart()` chaqiradi (exchange'ga QAYTA so'rov YO'Q), aks holda
       eski `_news_render()` yo'li.
     - Tekshirildi: (1) `_agg_trades()` sahifalash (2 sahifa, `startTime`
       to'g'ri surilishi), 429'da qisman natija; (2) xarid/sotuv `m`
       maydoni orqali to'g'ri ajratilishi; (3) `chart._delta_profile()`
       faqat kripto uchun ishlashi va MEXC xatosida `None` qaytarishi;
       (4) `setup_chart()`/`signal_chart()` profilli VA profilsiz
       (forex, xato) holatlarda PNG chiqarishi; (5) haqiqiy Postgres
       bilan `profile_data` JSONB round-trip. Barcha natija rasmlari
       foydalanuvchiga ko'rsatildi (2 marta — birinchi versiyada
       "volume juda noaniq" fikri bo'yicha soxta test ma'lumoti
       realroq qilib qayta chizildi). `test_tracker.py` 9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy hajm portlashi/jurnal signali bilan
       tasdiqlanmagan** — keyingi haqiqiy surge hodisasi yoki jurnal
       signalida Railway logi orqali tekshirilishi kerak.

109. **Foydalanuvchi (ARIAUSDT misolidan keyin): "O'zi taym freym tanlansa
     natija ham o'sha taymda keladimi?" -> "Yoq, buni tuzatish kerak.
     Tanlangan taym freymda natijani yuborishi kerak."** AskUserQuestion
     orqali aniqlashtirildi: foydalanuvchi XAVFSIZ variantni tanladi —
     TP/SL ANIQLASH hamon 1 daqiqalik aniqlikda qoladi (`tracker.py`ga
     tegilmadi, #37'dagi qaror to'g'ri edi), FAQAT ko'RSATISH (yopilish
     grafigi) izchil bo'lishi kerak edi.
     - **Topilgan haqiqiy bo'shliq**: `preview_kb()`da UCHTA tanlov bor —
       "🖼 Yuborgan rasmim bilan"/"🖼 Rasm yuklash" (pic), "📈 Bot grafikni
       aniqlasin" (okc -> tf_kb), "📝 Rasmsiz davom etish" (nopic). Taym
       freym FAQAT "okc" yo'lida so'ralardi. Lekin **yopilish grafigi
       (`chart.signal_chart()`) HAR DOIM avtomatik chiziladi**, foydalanuvchi
       ochilishda "pic"/"nopic" tanlagan bo'lsa ham — bu holatlarda
       `chart_tf` NULL qolib, standart 15m'ga tushib qolardi (aynan
       ARIAUSDT holati).
     - **Tuzatish**: "pic" (mavjud fayl bilan), "nopic" va rasm-yuklash
       (`AWAITING_SIGNAL_PHOTO`) yo'llarining HAMMASI endi ham `tf_kb()`
       ko'rsatadi ("Yopilgandagi natija grafigi qaysi taym freymda
       chizilsin?" matni bilan) — FARQI: yangi `item["want_bot_chart"]`
       bayrog'i `False` qilib belgilanadi (faqat "okc" yo'lida `True`).
       `"tf"` handler'ida endi shu bayroq tekshiriladi: `True` bo'lsa
       OCHILISH uchun ham bot grafigi chiziladi (`chart.setup_chart()`),
       `False` bo'lsa faqat `chart_tf` saqlanadi va OCHILISH grafigisiz
       (yoki foydalanuvchi rasmi bilan) davom etadi — YOPILISH grafigi
       baribir keyinroq shu saqlangan `chart_tf`da chiziladi.
     - Natija: endi QANDAY variant tanlansa ham, `chart_tf` HECH QACHON
       NULL qolmaydi (standart 15m'ga tayanish yo'qoladi) — yopilish
       grafigi doim foydalanuvchi bilib tanlagan taym freymda chiqadi.

110. **Foydalanuvchi: "shaxsiy kabinetda nega natija grafik bilan
     kelmayabti? Buni tuzatgan edikku?"** — aniqlashtirildi: Telegram'dagi
     ShAXSIY chat (bot bilan DM) haqida, "yopish" TUGMASINI QO'LDA
     bosilgandagi holat.
     - **Haqiqiy xato topildi**: avtomatik yopilish (TP/SL tekkanda,
       `poll_job`/`tracker` orqali) shaxsiy workspace uchun grafikni
       TO'G'RI yuborardi (`elif ws["type"] == "personal":` shoxchasi bor
       edi) — LEKIN **qo'lda yopish** (`on_close_confirm()`, "Yopish"
       tugmasi) faqat `if ws["type"] == "group" and ws["group_chat_id"]:`
       shoxchasiga ega edi — shaxsiy workspace uchun HECH QANDAY qo'shimcha
       xabar/grafik yuborilmasdi, faqat asl xabar matni tahrirlanardi.
     - **Tuzatish**: `on_close_confirm()`da endi `ws["type"] in ("group",
       "personal")` ikkalasi uchun ham grafik (`chart.signal_chart()`)
       tayyorlanadi; keyin ICHKARIDA `if.../elif ws["type"] == "personal"`
       orqali guruh yoki `ws["owner_id"]`ga (shaxsiy DM) mos ravishda
       yuboriladi — bu naqsh avtomatik-yopilish yo'lidagi (`on_button`
       ichidagi poll_job hodisa handleri, ~qator 2426) mavjud "personal"
       shoxchasi bilan BIR XIL uslubda yozildi.

111. **Foydalanuvchi: "economik xabarlarni natijasi nega kelmayabti?"**
     AskUserQuestion orqali aniqlashtirildi ("Boshqa narsa" javobi, misol
     bilan): bu digest/eslatma (#17, ishlab turibdi) haqida EMAS —
     foydalanuvchi natija (`actual`) chiqqach BATAFSIL xabar (teglar,
     "AQSh - KATEGORIYA - KO'RSATKICH (oy):" sarlavhasi, har bir metrika
     uchun oylik/yillik "kutilgan/oldingi" qatorlari) VA shu yangilikning
     BTC narxiga ta'sirini (grafik bilan) xohlagan — o'zining haqiqiy
     misolini (PCE narx indeksasi posti) aynan shu formatda yuborgan.
     - **Yangi topilma**: `econcalendar.py` `actual` maydonini UMUMAN
       o'qimasdi (faqat `forecast`/`previous`) — Forex Factory'ning
       HAFTALIK fayli natija chiqqach shu maydonni O'ZI to'ldiradi,
       alohida so'rov shart emas (faqat mavjud 30-daqiqalik keshni
       kuting). Bu — yangi funksiyaning yagona texnik noaniqligi edi,
       endi tasdiqlandi (mock javob bilan sinaldi — bu domen ham
       sandbox'da bloklangan, production Railway logi orqali
       tasdiqlanishi kerak).
     - **Arxitektura qarori — YANGI infratuzilma emas, MAVJUDINI qayta
       ishlatish**: #108'dagi surge/SEC quvuri (`news_events` jadvali +
       `_news_render()`/`_news_candles()` + `news_live_job()`) allaqachon
       aynan shu narsani qiladi — hodisa post qilinadi, keyin
       `NEWS_LIVE_MINUTES` davomida narx grafigi avtomatik yangilanadi.
       Shuning uchun HECH QANDAY yangi jadval/ustun QO'SHILMADI — faqat
       `source="econ"`, `symbol="BTCUSDT"`, `market="crypto"` bilan bitta
       yangi `news_events` qatori yoziladi, qolgani (jonli % kuzatuv,
       grafik sarlavhasidagi `{symbol} ({live_pct:+.2f}%)`) BEPUL keladi.
     - **newsai.py**: yangi `econ_result(events)` — `analyze()` andozasida,
       LEKIN butun xabar matnini (teglar, sarlavha, har bir metrika
       qatori) TO'LIQ Claude'ga yozdiradi (qattiq shablon + foydalanuvchi
       bergan aynan o'zi misol PROMPT ichida) — bir xil `when` vaqtida
       chiqqan bir nechta ko'rsatkich (masalan oylik+yillik PCE) BITTA
       guruh sifatida uzatiladi, Claude ularni bitta xabarda birlashtiradi.
       `is_market_moving=false` bo'lsa (arzimas ko'rsatkich) chaqiruvchi
       postlamaydi.
     - **bot.py — `econ_job()`ga 3-bo'lim qo'shildi** (yangi alohida job
       EMAS, mavjud 60s tsiklga qo'shimcha): `actual` to'ldirilgan va
       `ECON_RESULT_LOOKBACK_MINUTES` (standart 180) ichida chiqqan
       hodisalar `when` bo'yicha guruhlanadi; `econ_calendar_state`
       (`kind="result"`) orqali AVVAL belgilanadi (Claude chaqiruvi/post
       muvaffaqiyatsiz bo'lsa ham qayta urinilmaydi — #17'dagi digest
       naqshi bilan bir xil); `newsai.econ_result()` natijasi ->
       `db.insert_news_event(source="econ", symbol="BTCUSDT", ...)` ->
       `_news_render("BTCUSDT", "crypto", when, label="BTC")` -> post ->
       `db.set_news_message(..., render_tf="1m", render_label="BTC")` —
       shundan keyin `news_live_job()` uni BOSHQA HECH QANDAY o'zgarishsiz
       avtomatik jonli yangilaydi (umumiy `active_live_events()` so'rovi
       `source`ga qaramaydi).
     - **config.py**: `ECON_RESULT_LOOKBACK_MINUTES=180` — funksiya
       birinchi marta ishga tushganda (yoki uzoq to'xtab qolgandan keyin)
       haftaning ESKI natijalarini birdaniga postlab tashlamasligi uchun.
     - Tekshirildi (mock): (1) `econcalendar.fetch_week()` `actual`ni
       to'g'ri o'qishi va past-ta'sirli hodisani hamon chiqarib
       tashlashi; (2) `newsai.econ_result()` — client yo'q/JSON bo'lmagan
       javob holatlarida xavfsiz `None`; (3) `econ_job()` uch xil
       hodisadan (actual bor+yaqin / actual yo'q / actual bor lekin
       ESKI) FAQAT to'g'risini postlashi, `insert_news_event`/`set_news_
       message` parametrlari to'g'ri uzatilishi, ikkinchi chaqiriqda
       TAKRORIY post YO'Qligi. `test_tracker.py` 9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy natija bilan tasdiqlanmagan** —
       keyingi haqiqiy AQSH makro relizida (masalan navbatdagi PCE/CPI/NFP)
       Railway logi orqali tekshirilishi kerak: `actual` maydoni
       haqiqatan kelayaptimi, Claude formatlash to'g'rimi, BTC grafigi
       to'g'ri postlanayaptimi.

112. **Foydalanuvchi (MOVRUSDT surge post skrinshoti bilan): "nega movr
     tokenini kech yubordi?"** Sabab topildi: `volume_snapshot_job` 24
     soatlik hajmni bazaga FAQAT `SURGE_SNAPSHOT_HOURS` (avvalgi qiymat:
     4) soatda bir yozardi, `surge_scan_job` esa shu bazadagi "oxirgi"
     yozuvni har 30 daqiqada tekshirardi — ya'ni portlash BOSHLANGANDAN
     keyin bazaga yozilishi uchun 4 soatgacha, keyin aniqlanishi uchun
     yana 30 daqiqagacha, jami ~4.5 soatgacha kechikish bo'lishi mumkin
     edi (MOVR aynan shunday kech ketgan).
     - **Tuzatish**: `SURGE_SNAPSHOT_HOURS` standart qiymati 4 -> 1
       (`config.py`). `exchange.volume_ticker_24hr()` — barcha juftliklar
       uchun BITTA bulk so'rov (har juftlikka alohida emas), shuning
       uchun soatiga bir chaqirish tezlik chegarasiga xavf solmaydi.
       Bazaviy o'rtacha (`SURGE_BASELINE_EXCLUDE_HOURS=12`,
       `min_snapshots=3`) mantig'iga tegilmadi — faqat ko'proq/tezroq
       yozuv to'planadi, kechikish endi ~4.5 soat o'rniga ~1.5 soatgacha.
     - `test_tracker.py` 9/9 — o'zgarmadi (`tracker.py`ga tegilmadi).

113. **Foydalanuvchi (likvidatsiya post skrinshoti bilan): "1 million
     dollorni 1.123,64K qilib yuboryabti tog'irlash kerak."** Xato
     topildi: `_fmt_usd_k()` HAR DOIM 1000ga bo'lib "K" qo'shardi —
     $1.123.640 kabi million miqdorlar "1.123,64K" bo'lib chiqib, "1
     mingga yaqin" deb chalkash o'qilardi.
     - **Tuzatish**: `value_usd >= 1_000_000` bo'lsa endi 1 000 000ga
       bo'linib "M" qo'shiladi (masalan "1,12M"), aks holda eskicha "K"
       (mingda). Yagona chaqiruvchi joyi — `_process_liquidation_spike()`
       likvidatsiya xabari.
     - Tekshirildi: 1.123.640 -> "1,12M", 533.890 -> "533,89K" (o'zgarmadi),
       chegara holatlari (999.999 -> "1.000,00K", 1.000.000 -> "1,00M").
       `test_tracker.py` 9/9 — o'zgarmadi.

114. **Foydalanuvchi (AASTUSDT/QAITUSDT portlash post skrinshotlari
     bilan): "Delta chiqmadi avvalgidek keklayapti portlash."** Ya'ni
     #108'da qo'shilgan Volume/Volume Delta ikki panelli grafik o'rniga
     ESKI (profilsiz, faqat bitta ichki hajm ustuni) ko'rinish qaytib
     kelayapti — bu `_process_surge_candidate()`ning `chart.news_chart()`
     FALLBACK yo'liga tushayotganini bildiradi (`exchange.volume_delta_
     profile()` `None` qaytarayotgani uchun).
     - **Ildiz sabab topildi**: `exchange.py`da MEXC `/api/v3` — Binance
       spot API'ni deyarli aynan oynaydi (fayl boshidagi izohga qarang),
       Binance'ning HUJJATLASHTIRILGAN cheklovi bo'yicha `/aggTrades`da
       `startTime` VA `endTime` ikkalasi ham berilsa, ular orasidagi FARQ
       1 SOATDAN KICHIK bo'lishi SHART. `_agg_trades()` esa 48 soatlik
       DELTA_WINDOW_MS oynasini BUTUNLIGICHA (`endTime=end_ms` o'zgarmas)
       BITTA so'rovda yuborardi — bu MEXC tomonidan doim rad etilib
       (400/bo'sh natija), `volume_delta_profile()` HAR DOIM `None`
       qaytarardi. Bu #108'dagi mock testlarda ANIQLANMAGAN edi, chunki
       ular `_client.get()`ni to'g'ridan-to'g'ri mocklab, MEXC'ning bu
       real vaqt-oyna cheklovini simulyatsiya qilmagan edi.
     - **Tuzatish**: `_agg_trades()` endi IKKI qavatli tsikl — TASHQI
       tsikl 48 soatlik oynani `AGG_TRADES_WINDOW_MS=55 daqiqa`lik
       kichik oynalarga bo'lib-bo'lib so'raydi (har biri < 1 soat, MEXC
       chegarasidan xavfsiz), ICHKI tsikl esa har bir kichik oyna ICHIDA
       (agar 1000 tadan ko'p savdo bo'lsa) avvalgidek `startTime`ni
       surib sahifalaydi. 400-499 status endi BUTUN funksiyani emas,
       FAQAT shu kichik oynani to'xtatadi (keyingi oynaga o'tiladi);
       429 esa hamon BUTUN funksiyani to'xtatadi (tezlik chegarasi —
       qayta urinish xavfli).
     - Tekshirildi (mock): MEXC'ning haqiqiy >1 soat cheklovi simulyatsiya
       qilindi (`endTime-startTime>1soat` bo'lsa 400) — ESKI (bitta
       so'rov) yondashuv 400 bilan muvaffaqiyatsiz bo'lishi, YANGI
       (oynali) yondashuv esa 48 soatlik oynadagi (oxirgi 30 daqiqadagi)
       savdoni MUVAFFAQIYATLI topishi va HECH BIR so'rov 1 soatdan
       oshmasligi tasdiqlandi (53 so'rov/nomzod — kam-tez-tez chaqiriladi,
       muammo emas). Eski pagination/429/xarid-sotuv testlari (#108)
       o'zgarishsiz 9/9 o'tdi. `test_tracker.py` 9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy portlash hodisasi bilan
       tasdiqlanmagan** — keyingi surge postida Railway logi orqali
       (yoki rasmning o'zida Volume+Delta ikki panel ko'rinishi bilan)
       tekshirilishi kerak.

115. **Foydalanuvchi (TACUSDT surge skrinshoti bilan): "Bu kechagi kungini
     xisoblayabtiyu? Nega bunaqa? Keyin chartni o'rtaroqqa surish kerak
     hammasi tiqlib qolgan. Portlash schemasini jiddiy o'zgartirishimiz
     kerak. Kech kelgan xabar hechkimga foyda bermaydi."** Uchta alohida
     narsa: (1) "Portlash" belgisi noto'g'ri shamda, (2) grafik joylashuvi
     tiqilib qolgan, (3) umuman kechikish hali ham katta.
     - **(1) "Kechagi kun" xatosi — ildiz sabab topildi**: `_news_candles()`
       (bot.py, barcha post turlari — SEC/surge/likvidatsiya/econ uchun
       UMUMIY) `news_idx`ni shamning `close_ms` (davr OXIRI)ga ENG YAQINini
       qidirib topardi. Lekin HALI TUGAMAGAN (joriy) sham uchun `close_ms`
       — davr OXIRI, ya'ni "1d"da BUGUN KECHQURUN (KELAJAKDA). Kunning ilk
       soatlarida "hozir"gacha bo'lgan masofa "bugun oxiri"gacha nisbatan
       "kecha oxiri"gacha YAQINROQ chiqib, `news_idx` bir sham OLDINGA
       (kechagiga) siljib qolardi — aynan TACUSDT'da ko'ringan xato.
       **Tuzatish**: endi `event_ms` qaysi shamning `[open_ms, close_ms)`
       oralig'iga TUSHISHINI qidiradi (joriy tugamagan sham uchun ham
       to'g'ri — `open_ms` allaqachon o'tgan, `event_ms` shu oraliqda),
       eski masofaviy usul faqat FALLBACK sifatida qoladi.
     - **(2) Tiqilib qolish**: `chart.surge_profile_chart()` narx panelida
       O'NG TOMONDA umuman bo'sh joy yo'q edi (`xlim` to'g'ridan-to'g'ri
       oxirgi shamda tugardi) — boshqa barcha grafik funksiyalarida
       (`_render()`/`news_chart()`) bor `right_pad` shu yerda YO'Q edi.
       Endi qo'shildi (`max(6.0, len(candles)*0.3)`), oxirgi sham va
       "Portlash" yorlig'i Volume panelidan ajralib turadi.
     - **(3) Kechikish — foydalanuvchi tafsilot berishni istamadi
       ("yuqorida bergan variantga o'zgartiraylik"), shuning uchun o'zim
       qaror qildim**: `SURGE_SNAPSHOT_HOURS` yana qisqartirildi (1 -> 0.25,
       ya'ni 15 daqiqa — bitta bulk so'rov bo'lgani uchun hamon xavfsiz),
       `surge_scan_job`ning qattiq yozilgan 1800s (30 daqiqa) intervali
       endi yangi `config.SURGE_SCAN_SECONDS=300` (5 daqiqa) bilan
       almashtirildi. Eng yomon holatda kechikish: ~4.5 soat (#108 oldin)
       -> ~1.5 soat (#112) -> endi **~20 daqiqa**.
     - Tekshirildi (mock): `news_idx` tuzatishi — sun'iy "joriy kun ertalab
       soat 02:00" holatida ESKI kod kechagi shamni tanlashi, YANGI kod
       to'g'ri BUGUNGI (oxirgi) shamni tanlashi isbotlandi. Vizual: mock
       ma'lumot bilan qayta chizilgan rasm foydalanuvchiga yuborildi —
       "Portlash" endi oxirgi shamda, o'ng tomonda bo'sh joy bor. Eski
       profil/pagination testlari (#108, #114) o'zgarishsiz o'tdi.
       `test_tracker.py` 9/9 — o'zgarmadi.
     - **Hali production'da tasdiqlanmagan** — keyingi haqiqiy portlash
       hodisasida Railway logi + kanaldagi rasmning o'zi orqali
       tekshirilishi kerak (news_idx to'g'ri shamda, grafik tiqilib
       qolmagan, kechikish kamaygan).

116. **Foydalanuvchi: boshqa bir botning "Big Whales Buy Activity" xabar
     namunasini yuborib, "Kunlik savdo hajmidan 10% baland summa kirsa
     buyga ham sellga ham xabar keladigan" funksiya so'radi.** AskUserQuestion
     orqali qamrov aniqlashtirildi: (1) FAQAT portlash nomzodlarida
     (butun bozor EMAS — MEXC individual savdolarni HAR juftlik uchun
     ALOHIDA so'rov talab qiladi, yuzlab juftlikda bu tezlik chegarasiga
     zarba berardi; portlash nomzodlari esa bir vaqtda kam sonli bo'ladi,
     xavfsiz), (2) mavjud News Trade AI kanaliga (alohida kanal shart emas).
     - **Arxitektura — deyarli hech qanday YANGI infratuzilma shart
       bo'lmadi**: `db.active_live_events()` (allaqachon `news_live_job`
       ishlatadigan, `source`ga qaramaydigan so'rov) orqali "hozir jonli
       kuzatilayotgan portlash hodisalari" ro'yxati olinadi (yangi so'rov
       shart emas), `exchange._agg_trades()` (#114'da tuzatilgan, MEXC
       1-soatlik oyna cheklovini hisobga oluvchi) orqali so'nggi
       `WHALE_WINDOW_MINUTES` (15) daqiqalik savdolar olinadi, `m`
       (isBuyerMaker) maydoni orqali xarid/sotuv ajratiladi.
     - **`db.py`**: yangi `latest_volume_snapshot(symbol)` — bitta
       juftlikning eng so'nggi USDT hajmi (`volume_snapshots`dan, allaqachon
       `exchange.volume_ticker_24hr()`ning `quoteVolume`i — USDT, aynan
       kerakli birlik).
     - **`bot.py` — yangi `whale_scan_job()`** (`WHALE_SCAN_SECONDS=120`da
       bir): aktiv portlash tangalarini oladi, har biri uchun 24s hajm +
       so'nggi 15 daqiqalik savdolarni oladi, xarid VA sotuv summasini
       (USDT) ALOHIDA hisoblaydi; qaysi tomon 24s hajmning `WHALE_MIN_
       PCT=10` foizidan OSHSA — o'sha tomon uchun ALOHIDA xabar (grafiksiz,
       oddiy matn, foydalanuvchi namunasiga o'xshash format: miqdor+tanga,
       narx+% o'zgarish, hajm+% ulush, davomiylik, 24s hajm). Ikkalasi
       ham chegaradan oshsa — ikkita alohida xabar (buy va sell).
     - **Dedup**: `news_events.source="whale"`, `external_key=
       "whale:{symbol}:{sana}:{buy|sell}"` — mavjud UNIQUE cheklov orqali
       (SEC/surge bilan bir xil naqsh), kuniga bitta tanga+tomon uchun
       bitta xabar. `active_live_events()`ga ta'sir qilmasligi uchun
       `message_id`/`render_tf` ATAYLAB o'rnatilmaydi (faqat dedup uchun
       yozuv, jonli yangilanish shart emas — bu bir martalik matn xabar).
     - **`config.py`**: `WHALE_MIN_PCT=10`, `WHALE_WINDOW_MINUTES=15`,
       `WHALE_SCAN_SECONDS=120`.
     - Miqdor formatlash (`_fmt_usd_k` — #113'dagi M/K tuzatishi) va narx
       formatlash (`_fmt_price`) — mavjud yordamchilar QAYTA ishlatildi,
       yangi funksiya yozilmadi.
     - Tekshirildi (mock): (1) faqat 10% chegaradan OSHGAN tomon (buy)
       uchun xabar yozilishi, sotuv (chegaradan past) e'tiborga
       olinmasligi, boshqa `source` (SEC) va `symbol=None` qatorlar
       chetlab o'tilishi; (2) xabar matni to'g'ri formatlanishi (miqdor,
       narx%, hajm%, davomiylik, 24s hajm barchasi to'g'ri hisoblangan);
       (3) dedup — `insert_news_event` `None` qaytarsa qayta yubormaslik;
       (4) 24s hajm topilmasa xavfsiz o'tkazib yuborish. `test_tracker.py`
       9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy kit faolligi bilan tasdiqlanmagan** —
       birinchi haqiqiy portlash+kit faolligi to'qnashganda Railway logi
       orqali tekshirilishi kerak.

117. **Foydalanuvchi: "Bunga ham 1D grafik bo'lishi kerak."** (#116'dagi
     kit faolligi xabariga nisbatan — u matn-only edi.) Boshqa BARCHA post
     turlari (SEC/surge/likvidatsiya/econ) grafik bilan keladi, kit
     faolligi shu naqshdan chiqib qolgan edi.
     - **Tuzatish**: `whale_scan_job()` endi `_news_render()` (mavjud,
       barcha oddiy — profilsiz — post turlari ishlatadigan umumiy
       funksiya) orqali "1d" grafik chizadi, portlashdagi bilan bir xil
       oyna (`SURGE_DECLINE_DAYS` kunlik). Belgi rangi/yorlig'i tomonga
       qarab: xarid — YASHIL "Xarid", sotuv — QIZIL "Sotuv" (likvidatsiya
       postidagi `marker_color` naqshi bilan bir xil). Matn (`caption`)
       o'zgarishsiz qoladi, `db.set_news_message(render_tf="1d", ...)`
       orqali endi `news_live_job()` grafikni BOSHQA hech qanday
       o'zgarishsiz avtomatik jonli yangilaydi (boshqa turlar bilan bir xil).
       Grafik yasalmasa (`_news_render()` `None`/xato qaytarsa) — avvalgidek
       matn-only postga xavfsiz qaytadi.
     - Tekshirildi (mock): (1) grafik muvaffaqiyatli bo'lsa `send_photo` +
       `set_news_message(render_tf="1d", render_label="Xarid", ...)` to'g'ri
       chaqirilishi; (2) grafik topilmasa matn-only (`send_message`)
       fallback ishlashi. Vizual: mock ma'lumot bilan chizilgan namuna
       (KERNELUSDT, YASHIL "Xarid" belgisi, +12.00%) News Trade AI
       uslubiga mos ekanligi tasdiqlandi. `test_tracker.py` 9/9 —
       o'zgarmadi.

118. **Foydalanuvchi: "Portlash habaridagi grafik bilan bir xil bo'lsin.
     Volume+delta."** (#117'da qo'shilgan grafik oddiy — profilsiz —
     `news_chart()` edi.)
     - **Yechim — MAVJUD profilni QAYTA ISHLATISH, yangi so'rov EMAS**:
       kit hodisasi doim shu tanga PORTLASH sifatida ALLAQACHON
       kuzatilayotgan payt yuz beradi (`whale_scan_job()` faqat surge
       nomzodlarini tekshiradi, #116), demak o'sha portlash hodisasi
       UCHUN ALLAQACHON hisoblangan Volume/Volume Delta profili
       (`news_events.profile_data`, #108'da qo'shilgan, 48 soatlik
       haqiqiy MEXC savdolaridan) bazada BOR. `whale_scan_job()` endi
       `db.active_live_events()`dan qaytgan surge qatorining
       `profile_data`sini o'qiydi (`surge_rows` endi symbol->QATOR
       xaritasi, faqat symbol to'plami emas) va bo'lsa `chart.
       surge_profile_chart()`ga TO'G'RIDAN-TO'G'RI uzatadi — MEXC'ga
       QO'SHIMCHA so'rov YO'Q, va ikkala xabar (portlash + kit) AYNAN
       BIR XIL profil ma'lumotini ko'rsatadi (foydalanuvchi so'ragan
       aynan shu). Profil topilmasa (masalan portlash chizilganda
       xato bo'lgan) — #117'dagi oddiy (marker rangli) grafikka
       xavfsiz qaytadi.
     - Kit hodisasining O'ZIGA ham `db.set_news_profile()` bilan bin'lar
       nusxalanadi — shunda `news_live_job()` ham uni keyingi jonli
       yangilanishlarda QAYTA SO'RAMASDAN xuddi shu profilli grafikni
       chizadi (surge live-update yo'lining AYNAN o'zi).
     - Tekshirildi (mock): (1) profil MAVJUD bo'lganda `surge_profile_
       chart()` (Volume+Delta) chaqirilishi, oddiy `news_chart()`
       chaqirilMASLIGI, profil kit hodisasiga ham nusxalanishi; (2) profil
       YO'Q bo'lganda oddiy `news_chart()` (marker rangi bilan) fallback
       ishlashi. Eski dedup/matn-format/24s-hajm-yo'q testlari (#116) ham
       yangilangan mocklar bilan qayta o'tkazildi. `test_tracker.py` 9/9 —
       o'zgarmadi.

119. **Foydalanuvchi: "⏰ Diqqat, 15 daqiqa keyin: 🇺🇸 Unemployment Claims —
     Shuni natijasi kelmadi."** (#111'da qo'shilgan econ natija funksiyasi
     haqida.) Railway logi orqali aniqlandi: aynan shu hodisa vaqti atrofida
     (`12:33:46 UTC` — AQSH haftalik ish o'rinlari hisoboti odatda 8:30 ET
     = shu payt) `econcalendar.fetch_week()` **429 (Too Many Requests)**
     qaytargan (`nfs.faireconomy.media`ning umumiy tezlik chegarasi —
     Railway'ning umumiy IP hududi sababli, #107'dagi CoinAnk holatiga
     o'xshash).
     - **Haqiqiy xato topildi**: `_econ_events_cached()` muvaffaqiyatsiz
       (bo'sh) javobda ham `_econ_cache_at`ni YANGILAB qo'yardi — bu esa
       KEYINGI qayta urinishni TO'LIQ 30 daqiqaga (`ECON_CACHE_TTL`)
       kechiktirar edi. Aynan "actual" natija chiqqan payt shu
       muvaffaqiyatsiz tsiklga to'g'ri kelib qolsa, tabiiy 429 o'zi
       tezda tuzalgan bo'lsa ham, bot 30 daqiqagacha ESKI (actual'siz)
       ma'lumot bilan qolib ketardi.
     - **Tuzatish**: yangi `_econ_cache_ok` bayrog'i — muvaffaqiyatsizlikdan
       keyin YANGI, ANCHA QISQAROQ `ECON_CACHE_RETRY_TTL=300` (5 daqiqa)
       qo'llanadi (muvaffaqiyatli holatda hamon 30 daqiqa — manbaning o'z
       tezlik chegarasini hurmat qilish uchun).
     - **Ikkinchi ehtimoliy sabab (bug EMAS, ATAYLAB)**: `newsai.econ_
       result()` bu ko'rsatkichni "kam ta'sirli" (`is_market_moving=false`)
       deb topgan bo'lishi ham mumkin — haftalik ish o'rinlari arizalari
       ko'pincha rutin, keskin bozor harakati keltirmaydigan ko'rsatkich.
       Bu holat oldin JIMGINA o'tkazib yuborilardi (loglarda iz qoldirmasdi)
       — endi `log.info(...)` qo'shildi, kelajakda shunga o'xshash "nega
       kelmadi" savollariga Railway logi orqali ANIQ javob berish mumkin
       bo'lishi uchun.
     - Tekshirildi (mock): (1) muvaffaqiyatsiz fetch'dan keyin qisqa
       (5 daqiqa) TTL ichida qayta so'ralmasligi, TTL o'tgach ESKI 30
       daqiqani emas, YANGI qisqa oralig'ni kutib qayta so'ralishi;
       (2) muvaffaqiyatli holatda odatdagi to'liq 30 daqiqalik TTL
       qo'llanishi (RETRY_TTL bilan aralashib ketmasligi). Eski econ
       testlari (#111) ham o'zgarishsiz o'tdi. `test_tracker.py` 9/9 —
       o'zgarmadi.
     - **Hali production'da haqiqiy 429 holatida tasdiqlanmagan** —
       keyingi shunga o'xshash hodisada (yangi manba muvaffaqiyatsizligi)
       Railway logi orqali tekshirilishi kerak: endi 5 daqiqada qayta
       urinilyaptimi.

120. **Foydalanuvchi: "Tokenlarni portlash va whales trakerga keladiganini
     top 500 ta tokenga o'zgartiraylik. Yoki savdo hajmi 10 million
     dollordan katta aktivlarni kuzatsin. Hozirgi beryotgan tokenlari
     kapitallashuvi juda past va yaroqsiz."** Ikkita variant taklif
     qilingan edi — ODDIYROQ va BARQARORROQ (top-N doim o'zgarib turadi,
     mutlaq chegara esa doim bir xil ma'noni bildiradi) bo'lgani uchun
     **mutlaq 24 soatlik hajm chegarasi** ($10M) tanlandi.
     - **Sabab**: `db.volume_surge_candidates()` FAQAT nisbiy o'sishga
       (`latest_volume > avg_volume * multiplier`) qarardi — mutlaq
       hajm/kapitallashuv haqida umuman fikr yuritmasdi. Shu sabab juda
       kichik/likvidsiz tanga ozgina dollarlik savdodan keyin ham "2.2x
       o'sdi" deb portlash sifatida chiqib ketardi.
     - **Bozor kapitallashuvi EMAS, 24 soatlik HAJM ishlatildi**:
       kapitallashuv uchun bepul/ishonchli manba yo'q (yangi tashqi
       integratsiya kerak bo'lardi), lekin 24s savdo hajmi — likvidlik va
       "amalda savdo qilса bo'ladimi" degan savolning to'g'ridan-to'g'ri
       o'lchovi — ALLAQACHON bazada bor (`volume_snapshots`,
       `exchange.volume_ticker_24hr()`ning `quoteVolume`si).
     - **Tuzatish**: `db.volume_surge_candidates()`ga yangi `min_volume_usd`
       parametri — SQL `WHERE`ga `AND l.latest_volume >= $4` qo'shildi.
       `config.SURGE_MIN_VOLUME_USD=10_000_000` (`surge_scan_job()`dan
       uzatiladi). Bu chegara PORTLASH VA kit (whale) kuzatuvining
       IKKALASIGA ham ta'sir qiladi — kit kuzatuvi FAQAT portlash
       nomzodlarida ishlaydi (#116), shuning uchun bitta joyni tuzatish
       ikkalasini ham hal qiladi.
     - Tekshirildi: haqiqiy Postgres bilan (`initdb`/`pg_ctl`, shu seansda
       ilgari ishlatilgan `/tmp/pgtest2` instansiyasi qayta ishga
       tushirilib) ikkita soxta tanga — biri katta hajm+3x o'sish, biri
       kichik hajm+5x o'sish (nisbiy o'sish YANA HAM katta, lekin mutlaq
       hajm past) — bilan sinaldi: `min_volume_usd=0` (eski xatti-harakat)
       ikkalasini ham qaytardi, `min_volume_usd=10_000_000` bilan FAQAT
       katta hajmli tanga qaytdi. `test_tracker.py` 9/9 — o'zgarmadi.

121. **Foydalanuvchi: "Nega stopni yuqoriga ko'tarsam hali tushmagan
     bo'lsayam erta yopib yuboryapti?"** Kod tekshirildi (`tracker.py`
     `process()`, `bot.py`ning "✏️ Stop"/"Stop → breakeven" oqimlari) —
     `last_checked_ms` orqali eskirgan shamlarni QAYTA SKAN QILISH bugi
     TOPILMADI (bu mexanizm to'g'ri ishlayapti, #37/#106'da tasdiqlangan
     1 daqiqalik aniqlik prinsipi ham buzilmagan).
     - **Haqiqiy topilma**: qo'lda yangi stop kiritishda ("✏️ Stop" matn
       oqimi, `handle_manage_input()`) YOKI "Stop → breakeven" tugmasida
       (`on_manage_be()`) JORIY bozor narxi bilan HECH QANDAY solishtirish
       yo'q edi. Agar foydalanuvchi yangi stopni JORIY narxning "narigi
       tomonida" qo'ysa (LONG: narx allaqachon yangi stopdan PAST; SHORT:
       BALAND) — bu texnik jihatdan TO'G'RI, chunki stop haqiqatan ham
       "allaqachon tegilgan" hisoblanadi, lekin `tracker.py`ning KEYINGI
       tsiklida (odatda sekundlar ichida) signal DARHOL yopiladi.
       Foydalanuvchi buni "narx hali yetmagan bo'lsa ham erta yopdi" deb
       xato tushunishi mumkin — ular buni CHARTdagi haqiqiy narx bilan
       emas, xayolidagi narx bilan solishtirgan.
     - **Tuzatish**: ikkalasi ham endi qo'llashdan OLDIN jonli narxni
       (`tracker.provider(market).last_price(symbol, fresh=True)`)
       tekshiradi — agar yangi stop allaqachon "tegilgan" bo'lsa,
       ANIQ ogohlantirish bilan RAD ETADI (o'rnatilmaydi): "✏️ Stop"da
       qayta kiritishni so'raydi (`AWAITING_SL` saqlanadi), "Stop →
       breakeven"da `show_alert=True` xabar ko'rsatib hech narsa
       o'zgartirmaydi. Ikkalasida ham "buni xohlasangiz '🔒 To'liq
       yopish'dan foydalaning" — chunki DARHOL yopish uchun mo'ljallangan
       to'g'ri vosita ALLAQACHON bor.
     - Narx olinmasa (tarmoq xatosi) — ESKI xatti-harakat (ogohlantirmasdan
       davom etadi) xavfsiz saqlanadi, funksiya butunlay to'xtab qolmaydi.
     - Tekshirildi (mock): (1) yangi stop allaqachon "tegilgan" bo'lsa
       ogohlantirish chiqishi va `db.set_stop()` CHAQIRILMASLIGI; (2)
       xavfsiz stop odatdagidek o'rnatilishi; (3) narx olinmasa xavfsiz
       davom etishi. `test_tracker.py` 9/9 — o'zgarmadi (`tracker.py`ga
       tegilmadi).

122. **Foydalanuvchi (#121'da ham #117'dagi bilan bir xil muammo
     kuzatilgach): "Oxirgi 0G 121 chi signalni hali yopmadim ochiqligicha
     qaytar tez. Keyin public dagi Madrimov Vip statistikasini 0 ga
     qaytarish kerak — shu kamchilik sabab signallari ishlamay qolgan."**
     Ikkita alohida ehtiyoj: (1) noto'g'ri yopilgan #121'ni ACTIVE holatiga
     qaytarish (YANGI FUNKSIYA — bunday imkoniyat oldin YO'Q edi), (2)
     "Madrimov Vip" workspace'ining ommaviy statistikasini tuzatish.
     - **(1) `/qaytar <ID>` — yangi super-admin buyrug'i**:
       `tracker.reopen_signal()` — yopiq (TP/SL/BREAKEVEN) signalni ACTIVE
       holatiga qaytaradi. Raqamlar QO'LDA KIRITILMAYDI — `cmd_tuzat`dagi
       bilan bir xil falsafa ("statistikani hech kim tekshira olmaydigan
       qo'lyozmaga aylantirmaslik"): `filled_pct`/`realized_pct` saqlangan
       `tp_hit`/`tps`/`entry`/`side`dan QAT'IY qayta hisoblanadi (yopilishdan
       OLDIN chinakam tegilgan TP'lar asosida — xato yopilishning o'zi
       hissasi butunlay olib tashlanadi). `sl` xavfsiz `sl_initial`ga
       qaytariladi (aynan shu yopilishga sabab bo'lgan xato stopni saqlab
       qolish ma'nosiz — #121'da yangi joriy-narx tekshiruvi #121'ni HAM
       himoya qiladi, endi qayta o'sha xato takrorlanmaydi). `last_checked_
       ms` HOZIRGA o'rnatiladi — aks holda keyingi tekshiruvda ESKI
       (allaqachon "tegilgan" holatni ko'rsatuvchi) shamlar qayta
       o'ynatilib, signal yana zumda yopilib qolardi. Depozit ham
       `cmd_tuzat`dagi bilan bir xil naqshda tuzatiladi (yopilishda
       ayirilgan/qo'shilgan pul qaytarib olinadi).
     - **(2) "Madrimov Vip" statistikasi — YANGI KOD KERAK EMAS, MAVJUD
       vosita bor**: `db.py`/`bot.py`ni tekshirganda aniqlandi — ommaviy
       sahifadagi statistika (`db.public_workspaces()`) HECH QANDAY alohida
       saqlangan "hisoblagich" EMAS, `signals` jadvalidan JONLI hisoblanadi
       (`excluded=FALSE` bo'lgan yopiq signallar bo'yicha). Xato signalni
       statistikadan chiqarish uchun ALLAQACHON `/tuzat` buyrug'i bor
       (super-admin, workspace ICHIDA ishlatiladi) — har bir signalni
       "🚫 chiqarish"/"↩️ qaytarish" bilan statistikaga kiritish/chiqarish
       mumkin, depozit ham mos ravishda tuzatiladi. **Bu Claude tomonidan
       BAJARILMADI** — chunki (a) `/tuzat` allaqachon aynan shu vazifa
       uchun mo'ljallangan va foydalanuvchining o'zi (super-admin) buni
       "Madrimov Vip" guruh chatida ishlatishi kerak (Claude Telegram
       foydalanuvchisi sifatida harakat qila olmaydi), (b) qaysi signallar
       ANIQ "shu kamchilik sabab" ekanini faqat foydalanuvchi biladi.
     - **Muhim cheklov, foydalanuvchiga aytilishi kerak**: Claude bu
       seansda production Postgres bazasiga TO'G'RIDAN-TO'G'RI ulanib
       yoza olmaydi (DATABASE_URL kabi maxfiy ma'lumotlarni ko'rish sandbox
       xavfsizlik siyosati tomonidan bloklangan) — shuning uchun `/qaytar`
       buyrug'ini HAM aynan foydalanuvchi (yoki boshqa super-admin)
       Telegram'da o'zi yozishi kerak, Claude buni ORQAVAROT bajara
       olmaydi.
     - Tekshirildi (mock): (1) `tp_hit=0` (hech qanday haqiqiy TP tegmagan)
       holatida to'liq ACTIVE'ga qaytishi, filled/realized 0'ga tushishi,
       sl `sl_initial`ga qaytishi; (2) `tp_hit=1` (TP1 chindan tegilgan)
       holatida FAQAT TP1 ulushi saqlanishi (qolgani emas); (3) ochiq yoki
       topilmagan signalni qaytarishga urinish xavfsiz `None`; (4)
       `cmd_qaytar()` to'liq oqimi — depozit to'g'ri tiklanishi (misolda
       -5% * $1000 yopilishda ayirilgan $50 qaytarilishi). `test_tracker.py`
       9/9 — o'zgarmadi.
     - **Hali production'da haqiqiy #121 bilan tasdiqlanmagan** —
       foydalanuvchi `/qaytar 121`ni ishlatgach Railway logi/signal holati
       orqali tekshirilishi kerak.

123. **Foydalanuvchi: "Madrimov guruhini statistikasini 1 marta 0 ga
     qaytarib ber. Keyingi safar o'zim qilaman."** (#122'ning davomi —
     "Madrimov Vip" statistikasi uchun `/tuzat` bor deb aytilgan edi, lekin
     bu safar foydalanuvchi ANIQ shu BIR martalik ishni Claude'dan
     bajarishni so'radi.)
     - **Muhim texnik cheklov (yana bir bor)**: Claude production Postgres
       bazasiga TO'G'RIDAN-TO'G'RI ulanolmaydi (DATABASE_URL kabi maxfiy
       ma'lumotlar sandbox xavfsizlik siyosati tomonidan bloklangan,
       `mcp__Railway__list-variables` sinab ko'rilganda tasdiqlandi). Shu
       sabab bu ONE-TIME tuzatish ALOHIDA admin buyruq sifatida EMAS
       (buni foydalanuvchi o'zi Telegram'da bosishi kerak bo'lardi),
       balki **bot ISHGA TUSHGANDA bir marta o'zi bajaradigan** kod
       sifatida yozildi — bu kod bot ICHIDA, uning O'Z qonuniy DB
       ulanishi bilan ishlaydi, Claude hech qanday maxfiy ma'lumotni
       ko'rmaydi.
     - **Xavfsizlik naqshi — `bot_settings` bayrog'i**: `_run_one_time_
       fixes()` (`post_init()`dan chaqiriladi) `onetime_reset_madrimov_
       stats` kalitini tekshiradi — allaqachon bajarilgan bo'lsa (konteyner
       qayta tushsa ham) IKKINCHI marta ISHLAMAYDI.
     - **Workspace'ni ANIQ topish — noto'g'ri guruhga tegib ketmaslik
       uchun**: `db.find_workspaces_by_name("madrimov")` (`ILIKE`, katta-
       kichik harfga bog'liq emas) — agar ANIQ 1 TA mos kelmasa (0 yoki
       bir nechta) — HECH NARSA QILINMAYDI, faqat aniq `log.warning()`
       bilan nima topilgani yoziladi (keyin Railway logi orqali tekshirib,
       kerak bo'lsa qo'lda hal qilinadi).
     - **`db.reset_workspace_stats(workspace_id)`** — `cmd_tuzat`dagi
       BITTA-BITTA "🚫 chiqarish" bilan BIR XIL natija, faqat bir martada
       BARCHASI uchun: workspace'ning barcha YOPIQ (`excluded=FALSE`)
       signallarini `excluded=TRUE` qiladi (statistika — jami/g'alaba/foiz
       yig'indisi — 0'ga tushadi), depozitni esa har bir signalning
       haqiqiy (`pnl_pct * alloc_amount`) hissasi bo'yicha TESKARI
       tuzatadi (bitta tranzaksiyada) — natijada depozit hech qanday
       signal yopilmagandagi boshlang'ich holatiga qaytadi (o'zboshimcha
       "0" emas, matematik izchil qiymat). **HECH NARSA O'CHIRILMAYDI** —
       `excluded` faqat bayroq, `/tuzat` bilan istalgan payt QAYTARISH
       mumkin (foydalanuvchining o'zi "keyingi safar o'zim qilaman" deb
       aytgan aynan shu vosita orqali).
     - Tekshirildi: haqiqiy Postgres bilan (shu seansda ilgari ishlatilgan
       `/tmp/pgtest2` instansiyasi) — 2 ta yopiq (biri foydali +20%, biri
       zararli -5%, ikkalasi ham $1000 hissali) va 1 ta ochiq (ACTIVE) va
       1 ta ALLAQACHON excluded signal + BOSHQA workspace'dagi signal bilan
       sinaldi: FAQAT 2 ta yopiq signal `excluded=TRUE` bo'ldi, ACTIVE va
       allaqachon-excluded signallarga tegilmadi, depozit to'g'ri
       ($1500 -> $1350, ya'ni -$150 = 20%*1000 - 5%*1000) tuzatildi,
       BOSHQA workspace butunlay tegilmay qoldi. `find_workspaces_by_name`
       aniq bitta va bir nechta mos kelish holatlarida ham sinaldi.
       `test_tracker.py` 9/9 — o'zgarmadi.
     - **Ishlashi Railway logi orqali (deploy'dan darhol keyin) TEKSHIRILISHI
       SHART** — "madrimov" bo'yicha aniq 1 ta workspace topilib, muvaffaqiyatli
       tuzatilganini tasdiqlash kerak; agar 0/bir nechta topilsa — foydalanuvchiga
       aniq nom/ID so'rab, prompt yangilanishi kerak.

124. **Foydalanuvchi: "Keyin botdagi hamma kamchiliklarni top. Menimcha
     Limit order qo'yishda kamchiliklar bor. Kichik foizlarda stop qo'yilsa
     darrov yopilib qolyabti. Katta foizdagi stop lossda hammasi yaxshi
     ishlayabti."** Real bug — kod bilan RIVAM TASDIQLANDI (`tracker.py`
     `process()`).
     - **Ildiz sabab**: Limit order (`PENDING`) to'lganda (`c.low<=entry
       <=c.high`) kod SHU SHAMNING O'ZIDA SL/TP tegishini ham darhol
       tekshirardi — orasiga `continue` YO'Q edi. Agar stop kirish narxiga
       YAQIN bo'lsa (kichik %), ODDIY sham shovqinining o'zi (halokatli
       harakat SHART EMAS) allaqachon SL darajasiga yetib qolardi — signal
       kirish bilan BIR VAQTDA zumda yopilardi. Katta % stopda esa xuddi
       shu sham hech qachon muammo tug'dirmasdi (shovqin unchalik uzoq
       yetmaydi) — foydalanuvchi tasvirlagan aynan shu naqsh.
       **FAQAT Limit orderlarga xos** — Market order (`entry_mode=
       'market'`) to'g'ridan-to'g'ri ACTIVE holatda boshlanadi ("kirish
       shami" tushunchasi umuman yo'q), shu sabab bu xato u yerda
       bo'lishi MUMKIN EMAS edi — foydalanuvchining o'z tashxisi
       ("Limit order qo'yishda") ANIQ to'g'ri chiqdi.
     - Mock bilan ANIQ reproduksiya qilindi: entry=100/sl=98 (2%) va bir
       xil sham (low=97.5) bilan entry=100/sl=80 (20%) solishtirildi —
       kichigi zumda "SL" (-2.00%), kattasi esa xuddi shu shamda "ACTIVE"
       (ochiq) qoldi — aynan foydalanuvchi ta'riflagan naqsh.
     - **AskUserQuestion orqali ikkita yechim taklif qilindi** (bu trade-
       simulyatsiya falsafasiga ta'sir qiladigan qaror, o'zim hal
       qilmadim): (A) hozirgi holat — konservativ, statistikani past
       ko'rsatishga moyil, lekin kichik % stoplar amalda ishlatib
       bo'lmas; (B) entry to'lgan shamda SL/TP TEKSHIRILMAYDI, keyingi
       shamdan boshlanadi — Market order bilan IZCHIL bo'ladi. **Foydalanuvchi
       (B)ni tanladi.**
     - **Tuzatish**: `process()`da entry to'lgan (yoki to'lmagan) holatning
       IKKALASI ham endi `continue` bilan tugaydi — SL/TP tekshiruvi HECH
       QACHON entry bilan bir xil shamda BAJARILMAYDI, faqat KEYINGI
       shamdan. Market order yo'li (status allaqachon ACTIVE bo'lib
       kirgan holatlar) BUTUNLAY TEGILMADI — o'sha yerda SL/TP hamon SHU
       shamning o'zida tekshiriladi (bu yerda hech qachon muammo yo'q edi).
     - Tekshirildi (mock): (1) reproduksiya stsenariysi endi ikkalasi ham
       "ACTIVE" (muammo yo'qoldi); (2) entry+SL bir shamda o'tkazib
       yuborilib, KEYINGI shamdagi HAQIQIY SL to'g'ri ishlashi; (3) entry+TP
       bir shamda o'tkazib yuborilib, KEYINGI shamdagi HAQIQIY TP1 to'g'ri
       ishlashi; (4) Market order (ACTIVE'dan boshlangan) — SHU shamning
       o'zida SL hamon ishlayveradi, xatti-harakat O'ZGARMAGAN. Mavjud
       `test_tracker.py` 9/9 — BARCHASI o'zgarishsiz o'tdi (hech qaysi
       mavjud test entry bilan bir shamda SL/TP tegishini sinamagan edi,
       shuning uchun ular buzilmadi).
     - **Ta'sir doirasi**: FAQAT KELAJAKDAGI (hali PENDING) Limit
       signallariga qo'llanadi — allaqachon yopilgan eski signallar
       QAYTA HISOBLANMAYDI (tarixni qayta yozish yo'q, izchil siyosat).
     - **"Botdagi hamma kamchiliklarni top" — keng so'rov, TO'LIQ audit
       BAJARILMADI**: bu seansda faqat foydalanuvchi ko'rsatgan ANIQ va
       tasdiqlangan yo'nalish (`tracker.py`ning trade-simulyatsiya
       yadrosi) chuqur tekshirildi va tuzatildi. Butun kod bazasini
       "hamma kamchilik" uchun audit qilish alohida, aniqroq so'rov
       (masalan qaysi qism: signal skanerlash, jonli yangilanish,
       xabarlar, UI oqimlari) bilan davom ettirilishi kerak.

125. **Foydalanuvchi: "boshqa kamchiliklarni top va tuzat."** — keyin bitta
     nazariy holat topilib ("Ha, shuni ham tuzat" bilan tasdiqlandi), keyin
     esa **"Balki oco rejimidan ko'nikma ko'chirarmiz?"** — bittasi
     noto'g'ri chiqib bekor qilindi, ikkinchisi esa CHINDAN eski (hech
     qachon ishlamagan) xatoni ochib, to'g'ri tuzatdi.
     - **1-urinish (BEKOR QILINDI)**: nazariy holat — TP1 tegib, stop
       breakeven'ga ko'chgach, XUDDI SHU shamda narx qaytib breakeven'ga
       tushsa, natija hozir "BREAKEVEN" bo'lib chiqadi, aslida "TP" (TP1
       olingan, foydali) bo'lishi kerak edi degan taxmin bilan tuzatish
       yozildi. **Taxmin NOTO'G'RI chiqdi**: shamning `low`'i albatta
       `high`'dan KEYIN keladi degan asossiz farazga tayangan edi — aslida
       bir tekis ko'tarilayotgan shamda `low == open` bo'lishi mumkin (TP1'ga
       chiqishdan OLDIN, "TP1'dan keyin qaytish" emas). Bu tuzatish
       `test_tracker.py`ning 9 tasidan 4 tasini BUZDI (TP1→TP2→TP3 ketma-
       ketligi noto'g'ri erta "BREAKEVEN" bilan to'xtab qolardi) — to'liq
       regressiya to'plami DARHOL ushladi. **To'liq bekor qilindi**;
       faqat haqiqatan hech qachon ishlamaydigan (isbotlangan no-op,
       o'chirilsa ham/qolsa ham natija bir xil) bitta o'lik qator xavfsiz
       deb topilib alohida olib tashlandi (`ec063e7`).
     - **2-urinish (MUVAFFAQIYATLI) — OCO'dan ko'nikma**: `process()`da SL
       va TP bitta shamning ICHIDA ikkalasi ham tegilganda (`ambiguous`),
       eski kod HAR DOIM "SL birinchi" deb TAXMIN qilardi
       (`CONSERVATIVE_SAME_CANDLE` bayrog'i "tuzatib" berishi kerak edi).
       Foydalanuvchi taklifi asosida — haqiqiy birjalardagi OCO (One-
       Cancels-the-Other) order'lar qanday ANIQ savdo tartibiga qarab
       hal qilinishini takrorlab — `exchange.resolve_touch_order()` (yangi)
       qo'shildi: shu 1-daqiqalik shamning ICHIDAGI HAQIQIY MEXC
       savdolarini (`_agg_trades()`, allaqachon mavjud, vaqt tartibida)
       ko'rib, SL va TP darajalaridan QAYSI BIRI CHINDAN OLDIN tegilganini
       topadi. Faqat `market == "crypto"` uchun (forex/aksiyada bunday
       ochiq individual savdo ma'lumoti yo'q); savdo topilmasa, tarmoq
       xatosi bo'lsa, yoki bitta savdoning o'zi ikkalasini ham "tegdi" deb
       ko'rsatsa (chegara narxlar bir-biriga juda yaqin) — `None` qaytadi
       va chaqiruvchi ESKI konservativ taxminga qaytadi (xavfsiz fallback).
     - **Yon kashfiyot — `CONSERVATIVE_SAME_CANDLE` HECH QACHON ishlamagan**:
       shu integratsiyani sinash chog'ida (birinchi urinish faqat
       `tp_touched=False` qo'yardi) test natija BUTUNLAY o'zgarmaganini
       ko'rsatdi — sabab: pastdagi yopish bloki (`if sl_touched:`)
       `tp_touched`ning qiymatiga UMUMAN qaramaydi, faqat `sl_touched`ga
       qaraydi. Ya'ni bu bayroq (va uni ishlatuvchi eski qator) qo'shilgan
       kundan beri **funksional o'lik** bo'lgan — SL har doim "g'olib"
       chiqargan, `CONSERVATIVE_SAME_CANDLE`ning qiymati (True/False)
       hech qanday farq qilmagan. Tuzatish: `resolved == "TP"` bo'lganda
       endi haqiqatan tekshiriladigan `sl_touched = False` qo'yiladi (
       `tp_touched` emas) — shu orqali TP1 to'g'ri hisoblanadi va signal
       ochiq qoladi (agar TP2/TP3 hali tegmagan bo'lsa).
     - Tekshirildi (mock, `test_tracker.py`ga 2 ta yangi holat qo'shildi):
       (4b) `resolve_touch_order` "TP" qaytarsa — signal "ACTIVE" bo'lib
       qoladi, faqat TP1 ulushi (+2.0%) hisoblangan; (4c) "SL" qaytarsa —
       eski konservativ natija bilan BIR XIL (-4.0%). Mavjud 9 ta holat
       (shu jumladan "konserv." — savdo ma'lumoti yo'q/`None` holati)
       o'zgarishsiz o'tdi. `python3 -m py_compile` — barcha o'zgargan
       fayllar (`exchange.py`, `tracker.py`, `test_tracker.py`) toza.
     - **Ta'sir doirasi**: FAQAT `market == "crypto"` signallariga (forex/
       aksiya konservativ xatti-harakatni saqlab qoladi) va FAQAT ikkalasi
       (SL va TP) bir xil shamda tegilgan (kamdan-kam, "noaniq") holatlarga
       tegishli — oddiy holatlar (faqat SL YOKI faqat TP tegilgan)
       butunlay tegilmagan.
     - **Ishlashi Railway logi orqali TEKSHIRILMAGAN** — bu haqiqiy
       "ikkalasi ham bitta shamda tegilgan" holat kamdan-kam uchraydi;
       birinchi shunday hodisa yuz berganda log'da `resolve_touch_order`
       chaqiruvi va natijasi (yoki xatosi) kuzatilishi kerak.
