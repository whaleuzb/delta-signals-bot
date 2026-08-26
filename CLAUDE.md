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
