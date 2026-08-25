"""Ochiq natijalar sahifasi — guruh statistikasini jonli havola sifatida.

Nima uchun: guruh egasi skrinshot tashlash o'rniga havola beradi va odam
haqiqiy, tekshiriladigan natijani ko'radi. Skrinshotni tahrirlash mumkin,
bu sahifani esa yo'q — u to'g'ridan-to'g'ri bazadan o'qiladi.

Xavfsizlik:
  - FAQAT o'qish. Hech bir yo'l bazaga yozmaydi.
  - Ko'rsatiladigan workspace `/top` bilan bir xil darvozadan o'tadi
    (`public` + `public_approved` + arxivlanmagan) — veb yangi ruxsat
    ochmaydi, allaqachon ommaviy bo'lgan narsanigina ko'rsatadi.
  - Har qanday matn (guruh nomi, juftlik) HTML uchun ekranlanadi.
  - Bot bilan ALOHIDA servis: bu yerda nima bo'lsa ham signal kuzatuvi
    to'xtamaydi.
"""
import asyncio
import html
import logging
import os
import time
from datetime import datetime

from aiohttp import web

import chart
import db
import stats
import tracker

log = logging.getLogger("web")

# Brauzer/Telegram HTML'ni SAQLAMASIN. Server keshi (CACHE_TTL) baribir
# ishlaydi, lekin Telegram WebView eski sahifani ko'rsatib turishi
# yangilanish chiqqanda foydalanuvchini adashtirardi.
NO_CACHE = {"Cache-Control": "no-store, max-age=0"}

# Kichik grafik rasmi brauzerda 24 soat keshlanadi (yopilgan savdo
# o'zgarmaydi). Chizish uslubi o'zgarganda esa eski rasm ko'rinib
# qolmasligi uchun havolaga versiya qo'shiladi — yangi manzil eski
# keshga tushmaydi. Grafik ko'rinishini o'zgartirsangiz, shu raqamni
# oshiring.
MINI_V = "3"

CACHE_TTL = 120.0          # sahifa/grafik keshi (soniya)
_cache: dict[str, tuple[float, object]] = {}


# Yopilgan savdo grafigi HECH QACHON o'zgarmaydi (savdo tugagan, shamlar
# tarixiy) — shuning uchun uzoq keshlanadi va birjaga faqat bir marta
# murojaat qilinadi. Aks holda bitta sahifa ochilishi o'nlab so'rov yuborib,
# birja limitini yeb qo'yardi va kuzatuv siklini ham buzardi.
MINI_TTL = 86400.0


def _cached(key: str, ttl: float = CACHE_TTL):
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < ttl:
        return hit[1]
    return None


def _put(key: str, value):
    # Kesh cheksiz o'smasin: eng eski yozuvlar tashlanadi.
    if len(_cache) > 200:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    _cache[key] = (time.monotonic(), value)
    return value


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def fmt_price(x) -> str:
    x = float(x)
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    return f"{x:.8f}".rstrip("0")


CSS = """
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
/* Ranglar Whale Payment Bot mini-ilovasidan olingan: qora-kumush, sovuq
   kulrang sirtlar. Yashil/qizil FAQAT savdo natijasi uchun qoladi —
   boshqa hech qayerda rangli urg'u yo'q, shuning uchun raqamga ko'z
   birinchi tushadi. */
:root{--bg:#0A0A0C;--bg2:#101013;--card:#17171B;--card2:#1E1E23;
      --line:#28282E;--ink:#F3F4F6;--mut:#95979E;--faint:#57585E;
      --silver:#DADDE2;--silver-dim:#84868C;--glow:rgba(218,221,226,.10);
      --acc:#DADDE2;--long:#2ecc8f;--short:#ff5c5c;
      /* Tepadagi band joy. Oddiy brauzerda 0; Telegram'da skript aniq
         qiymatni qo'yadi (pastdagi TG_SCRIPT'ga qarang). */
      --tgtop:env(safe-area-inset-top,0px)}
body{background:var(--bg);color:var(--ink);
     font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     line-height:1.5;padding:0 20px 64px;min-height:100vh;position:relative}
/* FON QATLAMLARI. Whale ilovasida fon jonli (3D to'lqin) — bu yerda uning
   o'rniga ikkita sekin suzuvchi kumush yorug'lik ishlatiladi: JS ham,
   670 KB kutubxona ham kerak emas, GPU faqat transform/opacity bilan
   ishlaydi. Ikkalasi ham `pointer-events:none` — bosishga xalaqit bermaydi. */
body::before{content:"";position:fixed;inset:-20% -10%;z-index:-2;pointer-events:none;
  background:
    radial-gradient(ellipse 620px 380px at 50% 6%,rgba(218,221,226,.13),transparent 62%),
    radial-gradient(ellipse 520px 320px at 12% 42%,rgba(218,221,226,.06),transparent 66%),
    radial-gradient(ellipse 560px 340px at 92% 78%,rgba(218,221,226,.05),transparent 66%);
  animation:drift 26s ease-in-out infinite alternate}
/* Donadorlik: tekis qora fonda gradient "chiziqlar" (banding) ko'rinadi;
   juda mayin shovqin ularni yo'qotadi va sirtga "qog'oz" tuyg'usi beradi. */
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.5;
  background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='.035'/%3E%3C/svg%3E")}
@keyframes drift{
  0%  {transform:translate3d(0,0,0) scale(1)}
  50% {transform:translate3d(-2.5%,1.5%,0) scale(1.06)}
  100%{transform:translate3d(2%,-1%,0) scale(1.02)}
}
@media (prefers-reduced-motion:reduce){body::before{animation:none}}
.wrap{max-width:980px;margin:0 auto}
header{padding:calc(34px + var(--tgtop,0px)) 0 26px;border-bottom:1px solid var(--line);
       margin-bottom:32px}
.brand{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;font-weight:600;
       letter-spacing:.26em;color:var(--silver);text-transform:uppercase}
h1{font-family:"Space Grotesk",Inter,sans-serif;font-size:clamp(26px,5vw,40px);
   font-weight:700;letter-spacing:-.015em;margin-top:8px}
.sub{color:var(--mut);margin-top:6px;font-size:15px}
a{color:var(--silver);text-decoration:none}
a:hover{text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;
      margin-bottom:30px}
.tile{background:linear-gradient(155deg,rgba(23,23,27,.88),rgba(16,16,19,.88));
      backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
      border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.tile .k{font-size:12px;color:var(--mut);letter-spacing:.06em;text-transform:uppercase}
.tile .v{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:25px;font-weight:600;
         margin-top:6px;letter-spacing:-.01em}
.pos{color:var(--long)}.neg{color:var(--short)}
h2{font-family:"Space Grotesk",Inter,sans-serif;font-size:20px;font-weight:600;
   margin:34px 0 14px}
.chart{width:100%;border:1px solid var(--line);border-radius:14px;display:block}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px}
th,td{padding:11px 12px;text-align:right;border-bottom:1px solid var(--line);
      font-variant-numeric:tabular-nums;white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:12px;letter-spacing:.05em;
   text-transform:uppercase;text-align:right}
th:first-child,td:first-child{text-align:left}
tbody tr:hover{background:#ffffff06}

/* Tor ekranda jadval yonga siljimaydi: har qator blokka aylanadi —
   birinchi katak sarlavha bo'lib alohida qatorda, qolganlari esa
   "yorliq qiymat" juftliklari bo'lib yoniga tiziladi. Shunda BARCHA
   ma'lumot ko'rinadi, hech narsa kesilmaydi. */
@media (max-width:640px){
  .scroll{overflow-x:visible}
  table{min-width:0}
  thead{display:none}
  tbody tr{display:block;padding:13px 0;border-bottom:1px solid var(--line)}
  tbody tr:last-child{border-bottom:0}
  tbody tr:hover{background:none}
  td{display:inline-flex;align-items:baseline;gap:5px;border:0;
     padding:0 16px 0 0;text-align:left;font-size:13.5px;white-space:nowrap}
  td:first-child{display:block;font-size:15.5px;font-weight:600;
                 padding:0;margin-bottom:7px}
  td:not(:first-child)::before{content:attr(data-k);color:var(--mut);
                                font-size:11.5px;letter-spacing:.04em;
                                text-transform:uppercase}
}
.badge{display:inline-block;padding:2px 8px;border-radius:5px;font-size:12px;font-weight:600}
.b-long{background:#2ecc8f22;color:var(--long)}
.b-short{background:#ff5c5c22;color:var(--short)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.gcard{background:linear-gradient(155deg,rgba(23,23,27,.88),rgba(16,16,19,.88));
       backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
       border:1px solid var(--line);border-radius:16px;
       padding:18px 20px;display:block;color:inherit;position:relative;
       overflow:hidden;transition:border-color .18s,transform .18s,background .18s}
.gcard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
               background:var(--line)}
.gcard.pos-edge::before{background:var(--long)}
.gcard.neg-edge::before{background:var(--short)}
.gcard:hover{border-color:var(--silver-dim);text-decoration:none;transform:translateY(-2px)}
.gcard:active{transform:scale(.975);border-color:var(--silver-dim);
              background:linear-gradient(155deg,rgba(30,30,35,.95),rgba(20,20,24,.95))}
.gtop{display:flex;justify-content:space-between;align-items:center;gap:12px}
.gname{display:flex;align-items:center;gap:10px;min-width:0}
.gcard .n{font-family:"Space Grotesk",Inter,sans-serif;font-size:18px;font-weight:600;
          overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* Guruh logotipi — Telegram avatari. Rasm bo'lmasa nomning birinchi harfi
   (.ph) chiziladi: shunda kartalar bir xil ko'rinishda qoladi. */
.glogo{width:32px;height:32px;flex:none;border-radius:10px;object-fit:cover;
       border:1px solid var(--line);background:var(--card2);display:block}
.glogo.ph{display:flex;align-items:center;justify-content:center;
          font-family:"Space Grotesk",Inter,sans-serif;font-size:15px;
          font-weight:700;color:var(--silver-dim)}
/* Guruh sahifasidagi KATTA logotip. */
.htitle{display:flex;align-items:center;gap:16px;margin-top:10px}
.htitle h1{margin-top:0;min-width:0;overflow:hidden;text-overflow:ellipsis}
.blogo{width:76px;height:76px;flex:none;border-radius:20px;object-fit:cover;
       border:1px solid var(--line);background:var(--card2);
       box-shadow:0 10px 30px rgba(0,0,0,.45)}
.blogo.ph{display:flex;align-items:center;justify-content:center;
          font-family:"Space Grotesk",Inter,sans-serif;font-size:32px;
          font-weight:700;color:var(--silver-dim)}
@media (max-width:640px){
  .htitle{gap:12px}
  .blogo{width:60px;height:60px;border-radius:16px}
  .blogo.ph{font-size:26px}
}
/* O'rin raqami. Ro'yxat daromad bo'yicha tartiblangan — birinchi uchtasi
   ko'zga tashlansin, qolgani xotirjam kulrang. */
.rank{display:inline-flex;align-items:center;justify-content:center;
      width:28px;height:28px;flex:none;border-radius:9px;background:var(--card2);
      border:1px solid var(--line);color:var(--mut);
      font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:13px;font-weight:700}
.rank.r1{background:linear-gradient(150deg,#f6d67a,#c8a12a);color:#231d05;border-color:transparent}
.rank.r2{background:linear-gradient(150deg,#e2e7ef,#98a2b1);color:#1b1f26;border-color:transparent}
.rank.r3{background:linear-gradient(150deg,#e4a97b,#b57741);color:#241606;border-color:transparent}
.gcard .big{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:23px;
            font-weight:600;white-space:nowrap;letter-spacing:-.01em}
.gstats{display:flex;gap:18px;margin-top:14px;color:var(--mut);font-size:13px;
        flex-wrap:wrap}
.gstats span{color:var(--ink);font-weight:600;
             font-family:"IBM Plex Mono",ui-monospace,monospace}
.gfoot{display:flex;justify-content:space-between;align-items:center;margin-top:16px;
       padding-top:14px;border-top:1px solid var(--line);min-height:20px}
.chip{background:rgba(218,221,226,.10);color:var(--silver);font-size:12px;font-weight:600;
      padding:3px 9px;border-radius:20px}
/* "Batafsil" — havola emas, tugmaga o'xshasin: karta bosiladigan
   ekanligi bir qarashda tushunilsin. */
.gbtn{margin-left:auto;display:inline-flex;align-items:center;
      background:rgba(218,221,226,.06);border:1px solid rgba(218,221,226,.20);
      color:var(--silver);font-size:13px;font-weight:600;padding:7px 14px;
      border-radius:9px;transition:background .18s,color .18s,border-color .18s}
.gcard:hover .gbtn{background:var(--silver);border-color:var(--silver);color:#0A0A0C}
.gcard:active .gbtn{background:rgba(218,221,226,.22)}

/* hero */
.hero{border-bottom:1px solid var(--line);padding-bottom:30px}
/* Asosiy tugma — kumush gradient, qora matn (Whale ilovasidagi kabi). */
.btn{display:inline-block;margin-top:22px;
     background:linear-gradient(150deg,#EDEEF1,#AEB1B7);color:#0A0A0C;
     font-family:"Space Grotesk",Inter,sans-serif;font-weight:700;font-size:15px;
     padding:12px 24px;border-radius:12px;
     transition:transform .15s cubic-bezier(.22,.8,.32,1),filter .15s}
.btn:hover{text-decoration:none;filter:brightness(1.05);
           box-shadow:0 8px 26px rgba(218,221,226,.18)}
.btn:active{transform:scale(.955);filter:brightness(.96)}
/* SHAFFOF (shishasimon) tugma — ikkilamchi harakatlar uchun: fon
   ko'rinib turadi, chegara kumush. Asosiy kumush tugma bilan raqobat
   qilmaydi, lekin baribir tugma ekanligi ko'rinadi. */
.ghost{display:inline-flex;align-items:center;gap:6px;
       background:rgba(218,221,226,.06);border:1px solid rgba(218,221,226,.20);
       backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
       color:var(--silver);font-weight:600;font-size:13.5px;
       padding:8px 15px;border-radius:10px;
       transition:background .18s,border-color .18s,transform .12s cubic-bezier(.22,.8,.32,1)}
.ghost:hover{background:rgba(218,221,226,.12);border-color:rgba(218,221,226,.34);
             text-decoration:none}
.ghost:active{transform:scale(.955);background:rgba(218,221,226,.18)}
.back{margin-top:10px}
/* Guruhga qo'shilish — sahifadagi eng muhim harakat, shuning uchun
   oddiy tugmadan kattaroq. */
.join{margin-top:18px;font-size:16px;padding:14px 28px;
      box-shadow:0 8px 26px rgba(218,221,226,.14)}
.note{margin-top:26px;color:var(--faint);font-size:13px}
/* oxirgi savdolar — grafikli kartalar */
.trades{display:flex;flex-direction:column;gap:9px}
/* Fon SHAFFOF EMAS: ichidagi kichik grafik ham aynan shu rangda
   chiziladi (chart.CARD_BG), shunda rasm chegarasi ko'rinmaydi. */
.trade{background:var(--card);
       border:1px solid var(--line);border-radius:14px;
       padding:14px 16px;display:grid;position:relative;overflow:hidden;
       grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:14px}
/* Chap chetdagi rangli chiziq — guruh kartalaridagi kabi: foyda/zarar
   ro'yxatda bir qarashda skanerlanadi. */
.trade::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
               background:var(--line)}
.trade.pos-edge::before{background:var(--long)}
.trade.neg-edge::before{background:var(--short)}
.tsym{font-family:"Space Grotesk",Inter,sans-serif;font-size:15px;font-weight:600}
.tsub{color:var(--mut);font-size:12.5px;margin-top:4px;
      font-family:"IBM Plex Mono",ui-monospace,monospace}
.tmini{width:160px;height:55px;border-radius:6px;display:block;flex:none}
.tpnl{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:17px;font-weight:600;
      white-space:nowrap;min-width:76px;text-align:right}
@media (max-width:640px){
  /* Telefonda karta BIR QATOR bo'lib qoladi: chapda juftlik, o'rtada
     kichkina grafik, o'ngda natija. Avval grafik pastga to'liq kenglikda
     tushardi va bitta savdo ekranning uchdan birini egallardi — 25 ta
     savdoni ko'rish uchun juda uzoq aylantirish kerak edi. */
  .join{display:block;text-align:center;font-size:16px;padding:15px 18px}
  .trade{padding:12px 12px 12px 14px;gap:9px}
  /* Matn ko'chmasin: bir kartada ikki qator, boshqasida uch qator bo'lib
     ro'yxat notekis ko'rinardi. Endi hamma karta bir xil balandlikda. */
  .tsym,.tsub{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tsym{font-size:14px}
  .tsub{font-size:10.5px;margin-top:3px;letter-spacing:-.02em}
  .badge{padding:2px 6px;font-size:11px}
  .tmini{width:78px;height:28px;border-radius:5px}
  .tpnl{font-size:15px;min-width:0}
}
@media (max-width:380px){
  /* Eng tor telefonlarda grafik matnni siqib qo'ymasin: narx va sana
     to'liq ko'rinsin, grafik esa kichrayaversin. */
  .tmini{width:62px;height:24px}
  .tsub{font-size:10px}
  .trade{gap:7px}
}
@media (max-width:340px){
  /* Juda tor ekran (eski iPhone SE): grafik o'rniga narx va sana muhim —
     grafik butunlay olib tashlanadi, matn esa to'liq ko'rinadi. */
  .tmini{display:none}
}

/* Ochiq pozitsiya kartasi — savdo kartasi bilan bir xil, faqat grafiksiz
   va nomsiz. */
.open{background:var(--card);border:1px solid var(--line);border-radius:14px;
      padding:14px 16px;display:flex;align-items:center;gap:12px;
      position:relative;overflow:hidden}
.open::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
              background:var(--line)}
.open.pos-edge::before{background:var(--long)}
.open.neg-edge::before{background:var(--short)}
.ometa{min-width:0;flex:1}
.oname{font-family:"Space Grotesk",Inter,sans-serif;font-size:15px;font-weight:600}
.osub{color:var(--mut);font-size:11.5px;margin-top:3px;
      font-family:"IBM Plex Mono",ui-monospace,monospace}
.opnl{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:17px;
      font-weight:600;white-space:nowrap}

.cta{margin-top:40px;
     background:linear-gradient(135deg,var(--glow),rgba(23,23,27,.9) 55%);
     border:1px solid var(--line);border-radius:18px;padding:28px 30px}
.cta h3{font-family:"Space Grotesk",Inter,sans-serif;font-size:21px;font-weight:600;
        margin-bottom:10px}
.cta p{color:var(--mut);font-size:15px}
.steps{margin:16px 0 4px;padding-left:20px;color:var(--mut);font-size:15px}
.steps li{margin-bottom:9px}
.steps li::marker{color:var(--silver);font-weight:600}
.cta .btn{margin-top:18px}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;background:rgba(218,221,226,.08);
     color:var(--silver);padding:2px 7px;border-radius:5px;font-size:13px}
footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);
       color:var(--faint);font-size:13px;display:flex;justify-content:space-between;
       flex-wrap:wrap;gap:10px}
.empty{color:var(--mut);padding:26px 0}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600'
         '&family=IBM+Plex+Mono:wght@500;600;700&display=swap">')


# Telegram Mini App skripti. Bo'lmasa ham sahifa oddiy veb-sahifa sifatida
# ishlayveradi — quyidagi kod har bir chaqiruvni tekshirib ishlatadi.
TG_SCRIPT = """
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<script>
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) return;                       // oddiy brauzer — hech narsa qilmaymiz
  try { tg.ready(); } catch (e) {}
  try { tg.expand(); } catch (e) {}      // to'liq balandlikda ochilsin
  // Pastga surganda ilova yopilib ketmasin: sahifa uzun, foydalanuvchi
  // jadvalni o'qish uchun suradi va bu tasodifan yopilishga olib kelardi.
  // Bot API 7.7+ da mavjud, eskirog'ida jimgina o'tkazib yuboriladi.
  try { tg.disableVerticalSwipes && tg.disableVerticalSwipes(); } catch (e) {}
  try {
    tg.setHeaderColor && tg.setHeaderColor('#0b0e14');
    tg.setBackgroundColor && tg.setBackgroundColor('#0b0e14');
  } catch (e) {}

  // TEPADAGI BAND JOY.
  // Telegram sarlavhasi (Yopish / cheveron / menyu) sahifa USTIDAN chiziladi,
  // shuning uchun sarlavha va "TRADE CONTROLLER" yozuvi tugmalar tagida
  // qolib ketardi. safeAreaInset = holat qatori (soat, batareya),
  // contentSafeAreaInset = Telegram sarlavhasi balandligi. Ikkalasi
  // qo'shilib, header'ning tepa bo'shlig'iga qo'shiladi.
  function inset(o) { return (o && typeof o.top === 'number') ? o.top : 0; }
  function applyTop() {
    var t = 0;
    try { t += inset(tg.safeAreaInset); } catch (e) {}
    try { t += inset(tg.contentSafeAreaInset); } catch (e) {}
    // Mobil Telegram suzuvchi sarlavhani HAR DOIM sahifa ustidan chizadi,
    // lekin ba'zi mijozlar insetlarni 0 deb qaytaradi — shuning uchun
    // telefonda quyi chegara qo'yiladi. Desktop va oddiy brauzerda tugmalar
    // sahifadan tashqarida, u yerda hech narsa qo'shilmaydi.
    var mobil = tg.platform === 'ios' || tg.platform === 'android';
    if (mobil && t < 72) t = 72;
    // 0 bo'lsa CSS'dagi env(safe-area-inset-top) o'z holicha qolsin.
    if (t > 0) {
      document.documentElement.style.setProperty('--tgtop', t + 'px');
    }
  }
  applyTop();
  // Insetlar oyna o'zgarganda (kengaytirish, aylantirish) yangilanadi.
  ['safeAreaChanged', 'contentSafeAreaChanged', 'viewportChanged'].forEach(function (ev) {
    try { tg.onEvent && tg.onEvent(ev, applyTop); } catch (e) {}
  });
})();
</script>"""


def page(title: str, body: str, bot: str | None) -> str:
    link = f'<a href="https://t.me/{e(bot)}">@{e(bot)}</a>' if bot else "Trade Controller"
    return (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='dark'>"
        f"<title>{e(title)}</title>{FONTS}<style>{CSS}</style>{TG_SCRIPT}</head><body>"
        f"<div class='wrap'>{body}"
        f"<footer><div>Trade Controller — {link}</div>"
        f"<div>Ma'lumot bazadan jonli o'qiladi</div></footer></div></body></html>")


def _cls(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "")


def join_cta(bot: str | None) -> str:
    """Guruhlar ostidagi chaqiruv: "o'z guruhingizni shu yerda ko'ring".

    Sahifaga kelgan odamning aksari — signal beruvchi yoki guruh egasi. Ular
    uchun keyingi qadam aniq bo'lishi kerak, aks holda sahifa shunchaki
    ko'rilib yopiladi."""
    btn = (f"<a class='btn' href='https://t.me/{e(bot)}'>Botni ochish</a>"
           if bot else "")
    return (
        "<div class='cta'><h3>O'z guruhingizni shu yerda ko'rmoqchimisiz?</h3>"
        "<p>Bot signallaringizni avtomatik kuzatadi va statistikani o'zi yig'adi. "
        "Sahifani ochish uchun uch qadam:</p>"
        "<ol class='steps'>"
        "<li>Botni guruhingizga qo'shib, admin qiling va guruhda "
        "<code>/setup</code> yozing</li>"
        "<li>Signallaringizni bot orqali kiriting — u qolganini o'zi bajaradi</li>"
        "<li>Tayyor bo'lgach <code>/public on</code> yozing; moderator "
        "tasdiqlagach guruhingiz shu ro'yxatda paydo bo'ladi</li>"
        "</ol>"
        f"{btn}</div>")


def net_result(r) -> float:
    """Guruh natijasi — guruh sahifasidagi AYNI usul: pozitsiya hajmi
    belgilangan bo'lsa depozitga tortilgan, aks holda sof foizlar yig'indisi."""
    if r["deposit"] and r["n_alloc"]:
        return float(r["sum_weighted"])
    return float(r["sum_pct"])


async def index(request):
    bot = request.app["bot_username"]
    cached = _cached("index")
    if cached is not None:
        return web.Response(text=cached, content_type="text/html", headers=NO_CACHE)

    rows = await db.public_workspaces()
    # Eng yaxshi natija yuqorida — bu sahifaning butun mazmuni shu.
    rows = sorted(rows, key=lambda r: net_result(r), reverse=True)

    # Umumiy plitalar (jami signal, umumiy winrate...) olib tashlandi:
    # ular hech kimning natijasi emas — turli guruhlarning aralashmasi.
    # Har bir guruhning o'z raqamlari kartasida va o'z sahifasida.
    cards = []
    for pos, r in enumerate(rows, 1):
        total = r["total"] or 0
        wr = (r["wins"] / total * 100) if total else 0
        net = net_result(r)
        when = (f"{r['last_closed'].astimezone(stats.TZ):%d.%m.%Y}"
                if r["last_closed"] else "—")
        openb = (f"<span class='chip'>{r['n_open']} ta ochiq</span>"
                 if r["n_open"] else "")
        # O'rin raqami: ro'yxat daromad bo'yicha tartiblangan, shuning uchun
        # o'rin ma'noli. Birinchi uchtasi alohida rangda.
        rank_cls = f"r{pos}" if pos <= 3 else ""
        # Logotip — guruh avatari. Bo'lmasa nomning birinchi harfi.
        logo = (f"<img class='glogo' src='/g/{r['id']}/logo.png' alt='' "
                f"loading='lazy' onerror=\"this.remove()\">"
                if r["has_logo"] else
                f"<span class='glogo ph'>{e(r['name'][:1].upper())}</span>")
        cards.append(
            f"<a class='gcard {_cls(net)}-edge' href='/g/{r['id']}'>"
            f"<div class='gtop'>"
            f"<div class='gname'><span class='rank {rank_cls}'>{pos}</span>"
            f"{logo}"
            f"<span class='n'>{e(r['name'])}</span></div>"
            f"<div class='big {_cls(net)}'>{net:+.1f}%</div></div>"
            f"<div class='gstats'>"
            f"<div><span>{total}</span> signal</div>"
            f"<div><span>{wr:.0f}%</span> winrate</div>"
            f"<div><span>{e(when)}</span></div></div>"
            f"<div class='gfoot'>{openb}<span class='gbtn'>Batafsil →</span></div></a>")

    # "Botni ochish" faqat sahifa OXIRIDA (join_cta ichida). Avval u tepada
    # ham bor edi — bir sahifada bitta asosiy harakat yetadi, ikkitasi
    # e'tiborni bo'ladi.
    body = (
        "<header class='hero'><div class='brand'>Trade Controller</div>"
        "<h1>Ochiq natijalar</h1>"
        "<div class='sub'>Bu guruhlar o'z savdo statistikasini ommaga ochgan. "
        "Har bir raqam bazadan jonli o'qiladi — signal kiritilganda yoziladi, "
        "bozor TP yoki stopga tekkanda avtomatik yopiladi. Qo'lda tahrirlab "
        "bo'lmaydi.</div></header>"
        + (f"<h2>Top daromad beruvchi guruhlar</h2>"
           f"<div class='cards'>{''.join(cards)}</div>" if cards else
           "<div class='empty'>Hozircha ochiq guruh yo'q.</div>")
        + ("<div class='note'>Reyting joriy umumiy natija bo'yicha tartiblangan. "
           "O'tmishdagi natija kelajakni kafolatlamaydi.</div>" if cards else "")
        + join_cta(bot))
    cached = _put("index", page("Ochiq natijalar — Trade Controller", body, bot))
    return web.Response(text=cached, content_type="text/html", headers=NO_CACHE)


async def group_page(request):
    ws_id = int(request.match_info["wid"])
    bot = request.app["bot_username"]
    ws = await db.public_workspace(ws_id)
    if not ws:
        raise web.HTTPNotFound(text="Bunday sahifa yo'q yoki u ochiq emas.")

    cached = _cached(f"g{ws_id}")
    if cached is not None:
        return web.Response(text=cached, content_type="text/html", headers=NO_CACHE)

    s = await db.period_stats(ws_id)
    rows = await db.equity_series(ws_id)
    deposit = ws["deposit"]
    total = s["total"] or 0

    pnls = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
    weighted = None
    if deposit:
        weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                    for r in rows
                    if r["pnl_pct"] is not None and r["alloc_amount"] is not None]
    net = sum(weighted) if weighted else sum(pnls)
    net_label = "Jami natija (depozitga nisbatan)" if weighted else "Jami natija"
    wr = (s["wins"] / total * 100) if total else 0
    avg_r = float(s["avg_r"] or 0)

    tiles = [
        ("Yopilgan signallar", f"{total}", ""),
        ("Winrate", f"{wr:.1f}%", ""),
        (net_label, f"{net:+.2f}%", _cls(net)),
        ("O'rtacha R", f"{avg_r:+.2f}", _cls(avg_r)),
    ]
    tiles_html = "".join(
        f"<div class='tile'><div class='k'>{e(k)}</div>"
        f"<div class='v {c}'>{e(v)}</div></div>" for k, v, c in tiles)

    # Oylik
    months = await db.monthly_breakdown(ws_id, limit=12)
    mon_rows = "".join(
        f"<tr><td>{stats.MONTHS_UZ[r['month'].month - 1]} {r['month'].year}</td>"
        f"<td data-k='Savdo'>{r['total']}</td>"
        f"<td data-k='Winrate'>"
        f"{(r['wins'] / r['total'] * 100) if r['total'] else 0:.0f}%</td>"
        f"<td data-k='Natija' class='{_cls(float(r['sum_pct']))}'>"
        f"{float(r['sum_pct']):+.2f}%</td></tr>"
        for r in months)

    # OCHIQ POZITSIYALAR — faqat joriy foiz, juftlik nomisiz.
    # Ochiq savdoning tikeri guruh a'zolarining haqqi: ochiq sahifada uni
    # ko'rsatish signalni tekinga berish bo'lardi. Foiz esa guruh hozir
    # qanday ishlayotganini ko'rsatadi va hech narsani oshkor qilmaydi.
    # PENDING'lar chiqmaydi: ular hali ochilmagan, joriy foizi ham yo'q.
    live = [r for r in await db.live_signals(ws_id) if r["status"] == "ACTIVE"]
    opens = ""
    for i, r in enumerate(live, 1):
        try:
            price = await tracker.provider(r["market"]).last_price(r["symbol"])
        except Exception:
            log.warning("Ochiq pozitsiya narxi olinmadi (#%s)", r["id"], exc_info=True)
            price = None
        if price is None:
            continue
        p = tracker.pnl_at(r["side"], float(r["entry"]), price)
        since = (f"{r['opened_at'].astimezone(stats.TZ):%d.%m}"
                 if r["opened_at"] else "—")
        opens += (
            f"<div class='open {_cls(p)}-edge'>"
            f"<div class='ometa'><div class='oname'>Pozitsiya {i}</div>"
            f"<div class='osub'>{e(since)} dan beri</div></div>"
            f"<div class='opnl {_cls(p)}'>{p:+.2f}%</div></div>")

    # Oxirgi savdolar — jadval emas, har biri kichik grafigi bilan karta.
    # Grafik `loading=lazy`: ekranga chiqmagani umuman yuklanmaydi, ya'ni
    # sahifa ochilishi birjaga o'nlab so'rov yubormaydi.
    recent = await db.recent_closed(ws_id, 25)
    trades = ""
    for r in recent:
        p = float(r["pnl_pct"]) if r["pnl_pct"] is not None else 0.0
        side_cls = "b-long" if r["side"] == "LONG" else "b-short"
        # Sana qisqa: telefonda "0.02038 → 0.02145 · 23.08" bir qatorga sig'sin.
        # Yil ro'yxatda ortiqcha — savdolar yaqin sanalar bo'yicha tartiblangan.
        when = f"{r['closed_at'].astimezone(stats.TZ):%d.%m}" if r["closed_at"] else "—"
        exit_txt = (fmt_price(r["exit_price"]) if r["exit_price"] is not None else "—")
        trades += (
            f"<div class='trade {_cls(p)}-edge'>"
            f"<div class='tmeta'><div class='tsym'>{e(r['symbol'])} "
            f"<span class='badge {side_cls}'>{e(r['side'])}</span></div>"
            f"<div class='tsub'>{fmt_price(r['entry'])} → {exit_txt}"
            f" · {e(when)}</div></div>"
            f"<img class='tmini' src='/s/{r['id']}/mini.png?v={MINI_V}' loading='lazy' "
            f"alt='' onerror=\"this.remove()\">"
            f"<div class='tpnl {_cls(p)}'>{p:+.2f}%</div></div>")

    def section(title, header, body_rows):
        if not body_rows:
            return ""
        return (f"<h2>{e(title)}</h2><div class='scroll'><table><thead><tr>{header}</tr>"
                f"</thead><tbody>{body_rows}</tbody></table></div>")

    # Guruhga qo'shilish — sahifaning ASOSIY maqsadi. Avval u sarlavha
    # ostidagi kichkina matn havolasi edi va ko'zga tashlanmasdi; endi
    # to'liq tugma, sarlavha ostida alohida qatorda.
    invite = ""
    if ws["invite_link"]:
        invite = (f"<a class='btn join' href='{e(ws['invite_link'])}' "
                  "rel='nofollow noopener'>Guruhga qo'shilish →</a>")

    # Katta logotip sarlavha yonida. Bo'lmasa — nomning birinchi harfi;
    # shunda sarlavha qatori har doim bir xil balandlikda turadi.
    big_logo = (f"<img class='blogo' src='/g/{ws_id}/logo.png' alt='' "
                f"onerror=\"this.remove()\">"
                if ws["logo"] else
                f"<span class='blogo ph'>{e(ws['name'][:1].upper())}</span>")

    body = (
        f"<header><div class='brand'>Trade Controller</div>"
        f"<div class='htitle'>{big_logo}<h1>{e(ws['name'])}</h1></div>"
        f"<div class='sub'><a class='ghost back' href='/'>← Barcha guruhlar</a></div>"
        f"{invite}</header>"
        f"<div class='grid'>{tiles_html}</div>"
        + (f"<h2>Balans o'zgarishi</h2>"
           f"<img class='chart' src='/g/{ws_id}/equity.png' alt='Equity' loading='lazy'>"
           if len(pnls) >= 2 else "")
        + section("Oylik natijalar",
                  "<th>Oy</th><th>Savdo</th><th>Winrate</th><th>Natija</th>", mon_rows)
        + (f"<h2>Hozir ochiq</h2><div class='trades'>{opens}</div>"
           "<div class='note'>Juftlik nomi ko'rsatilmaydi — ochiq savdo "
           "guruh a'zolari uchun. Foiz joriy bozor narxidan hisoblanadi.</div>"
           if opens else "")
        + (f"<h2>Oxirgi savdolar</h2><div class='trades'>{trades}</div>"
           if trades else "")
        + ("<div class='empty'>Hali yopilgan signal yo'q.</div>" if not total else ""))

    out = page(f"{ws['name']} — natijalar", body, bot)
    _put(f"g{ws_id}", out)
    return web.Response(text=out, content_type="text/html", headers=NO_CACHE)


async def equity_png(request):
    ws_id = int(request.match_info["wid"])
    ws = await db.public_workspace(ws_id)
    if not ws:
        raise web.HTTPNotFound()
    key = f"eq{ws_id}"
    buf = _cached(key)
    if buf is None:
        # Grafik chizish qimmat (matplotlib) — shu sabab keshlanadi.
        img = await stats.equity_chart(ws_id, ws["deposit"])
        if img is None:
            raise web.HTTPNotFound()
        buf = _put(key, img.getvalue())
    return web.Response(body=buf, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=120"})


async def logo_png(request):
    """Guruh logotipi (Telegram avatari). Bazadan o'qiladi — veb servisda
    BOT_TOKEN yo'q, Telegram'ga umuman murojaat qilinmaydi."""
    ws_id = int(request.match_info["wid"])
    data = await db.public_logo(ws_id)
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(data), content_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


async def mini_png(request):
    """Bitta yopilgan savdoning kichik grafigi.

    Signal o'zi emas, uning WORKSPACE'i darvozadan o'tishi tekshiriladi —
    yopiq guruh signalini id taxmin qilib ko'rish mumkin emas."""
    sig_id = int(request.match_info["sid"])
    key = f"mini{sig_id}"
    buf = _cached(key, MINI_TTL)
    if buf is None:
        sig = await db.public_signal(sig_id)
        if not sig:
            raise web.HTTPNotFound()
        # Brauzer sahifadagi barcha rasmni BIRDAN so'raydi (25 tagacha).
        # Semafor ularni navbatga qo'yadi: birjaga bir vaqtda ko'pi bilan
        # ikkita so'rov ketadi, ya'ni bitta sahifa ochilishi rate-limit'ga
        # urilib, kuzatuv siklini ham buzib qo'ymaydi.
        async with request.app["mini_sem"]:
            buf = _cached(key, MINI_TTL)     # navbatda turganda tayyor bo'lishi mumkin
            if buf is None:
                try:
                    img = await chart.mini_chart(sig)
                except Exception:
                    log.warning("Kichik grafik yasalmadi (#%s)", sig_id, exc_info=True)
                    img = None
                if img is None:
                    raise web.HTTPNotFound()
                buf = _put(key, img.getvalue())
    return web.Response(body=buf, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


async def healthz(request):
    return web.Response(text="ok")


async def on_start(app):
    await db.init()
    log.info("Veb: bazaga ulandi")


async def on_stop(app):
    if db._pool is not None:
        await db._pool.close()


def build_app() -> web.Application:
    app = web.Application()
    app["bot_username"] = os.getenv("BOT_USERNAME", "")
    # Birjaga bir vaqtda ketadigan grafik so'rovlari soni (pastda izoh).
    app["mini_sem"] = asyncio.Semaphore(2)
    app.add_routes([
        web.get("/", index),
        web.get("/healthz", healthz),
        web.get(r"/g/{wid:\d+}", group_page),
        web.get(r"/g/{wid:\d+}/equity.png", equity_png),
        web.get(r"/g/{wid:\d+}/logo.png", logo_png),
        web.get(r"/s/{sid:\d+}/mini.png", mini_png),
    ])
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    web.run_app(build_app(), port=int(os.getenv("PORT", 8080)))
