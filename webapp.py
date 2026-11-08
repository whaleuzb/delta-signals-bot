"""Trade Controller Mini App (238) — 1-bosqich: bosh sahifa + ochiq signallar.

Tuzilishi (foydalanuvchi ko'rsatgan namuna bo'yicha): tepada workspace
tanlovi va "Bot" havolasi, o'rtada logo, ostida katta kartalar, pastda
suzuvchi bo'limlar paneli.

Xavfsizlik:
  - Har so'rovda Telegram imzolagan `initData` tekshiriladi
    (`web.verify_init_data`) — id'ni brauzer o'zi yozib yubora olmaydi.
  - O'qish: faqat odam EGASI bo'lgan workspace (yoki super-admin).
  - Yozish (BE, stop, qisman/to'liq yopish) veb servisda BAJARILMAYDI —
    `app_actions` navbatiga yoziladi, bot uni botdagi tugma bilan AYNI
    funksiya orqali bajaradi va huquqni o'zi qayta tekshiradi.
"""
import asyncio
import json
import logging

from aiohttp import web

import config
import db
import i18n
import tracker

log = logging.getLogger("webapp")

NO_CACHE = {"Cache-Control": "no-store, max-age=0"}
ACTIONS = ("be", "sl", "pc", "close")


# `web.build_app` o'rnatadi (aylanma importsiz): web.verify_init_data.
VERIFY = None


def _verify(init_data: str) -> int | None:
    return VERIFY(init_data) if VERIFY else None


async def _body(request) -> tuple[dict, int]:
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest()
    uid = _verify(str(body.get("initData") or ""))
    if uid is None:
        raise web.HTTPForbidden()
    return body, uid


def _can(ws, uid: int) -> bool:
    return bool(ws) and (ws["owner_id"] == uid or uid in config.ADMIN_IDS)


def _f(x):
    return float(x) if x is not None else None


async def api_me(request):
    _, uid = await _body(request)
    rows = await db.user_manage_workspaces(uid)
    lang = i18n.normalize(await db.get_user_lang(uid))
    out = []
    for w in rows:
        n = len(await db.live_signals(w["id"]))
        out.append({
            "id": w["id"], "name": w["name"], "type": w["type"],
            "channel": bool(w["is_channel"]), "open": n,
            "deposit": _f(w["deposit"]), "fut_deposit": _f(w["fut_deposit"]),
            "page": (f"/g/{w['id']}" if w["type"] == "group" and w["public"]
                     and w["public_approved"] else None),
        })
    return web.json_response({"uid": uid, "lang": lang, "ws": out,
                              "bot": request.app["bot_username"]}, headers=NO_CACHE)


async def _price(r):
    try:
        return await tracker.provider(r["market"]).last_price(r["symbol"])
    except Exception:
        return None


async def api_open(request):
    body, uid = await _body(request)
    try:
        ws = await db.get_workspace(int(body.get("ws")))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    rows = await db.live_signals(ws["id"])
    prices = await asyncio.gather(*(_price(r) for r in rows))
    out = []
    for r, price in zip(rows, prices):
        L = r["leverage"] or 1
        entry = float(r["entry"])
        filled = float(r["filled_pct"] or 0)
        realized = float(r["realized_pct"] or 0)
        live = None
        if price and r["status"] == "ACTIVE":
            live = (realized + max(0.0, 1 - filled) * tracker.pnl_at(r["side"], entry, price)) * L
        alloc = _f(r["alloc_amount"])
        out.append({
            "id": r["id"], "symbol": r["symbol"], "side": r["side"], "lev": L,
            "status": r["status"], "market": r["market"],
            "entry": entry, "sl": _f(r["sl"]),
            "tps": [float(t) for t in (r["tps"] or [])], "tp_hit": r["tp_hit"] or 0,
            "price": price, "live": live, "alloc": alloc,
            "money": (live / 100 * alloc) if (live is not None and alloc) else None,
            "filled": filled,
            "opened": r["opened_at"].isoformat() if r["opened_at"] else None,
        })
    return web.json_response({"ws": ws["id"], "items": out}, headers=NO_CACHE)


async def api_act(request):
    body, uid = await _body(request)
    act = str(body.get("action") or "")
    if act not in ACTIONS:
        raise web.HTTPBadRequest()
    try:
        sid = int(body.get("sig"))
        arg = float(body["arg"]) if body.get("arg") not in (None, "") else None
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    sig = await db.get_signal(sid)
    ws = await db.get_workspace(sig["workspace_id"]) if sig else None
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    aid = await db.app_action_add(uid, sid, act, arg)
    # Bot navbatni ~2 soniyada oladi; natijani 25 soniyagacha kutamiz.
    for _ in range(50):
        await asyncio.sleep(0.5)
        a = await db.app_action_get(aid)
        if a and a["status"] in ("ok", "fail", "stale"):
            return web.json_response({"ok": a["status"] == "ok",
                                      "msg": a["result"] or ""}, headers=NO_CACHE)
    return web.json_response({"ok": False, "pending": True, "msg": ""}, headers=NO_CACHE)


async def app_page(request):
    return web.Response(text=PAGE, content_type="text/html", headers=NO_CACHE)


def routes() -> list:
    return [
        web.get("/app", app_page),
        web.post("/api/app/me", api_me),
        web.post("/api/app/open", api_open),
        web.post("/api/app/act", api_act),
    ]


T = {
    "uz": {
        "bot": "Bot", "open": "Ochiq signallar", "open_sub": "Jonli natija va boshqaruv",
        "deposit": "Depozit", "spot": "Spot", "fut": "Futures", "stats": "Statistika",
        "stats_sub": "Natijalar sahifasi", "tour": "Turnir", "tour_sub": "Oylik musobaqa",
        "df": "Dip Funded", "df_sub": "Prop hisoblar", "soon": "Tez orada",
        "home": "Bosh", "signals": "Signallar", "profile": "Profil",
        "none": "Ochiq signal yo'q", "entry": "Kirish", "stop": "Stop", "price": "Narx",
        "be": "BE", "close": "Yopish", "cancel": "Bekor qilish", "newstop": "Yangi stop narxi",
        "confirm_close": "Pozitsiyani to'liq yopasizmi?", "confirm_cancel": "Limitni bekor qilasizmi?",
        "confirm_pc": "{p}% qismini yopasizmi?", "wait": "Bajarilmoqda…",
        "pending": "Kutilmoqda", "nows": "Sizda hali jurnal yo'q. Botda /start bosing.",
        "only_tg": "Bu sahifa Telegram ichida ochiladi.", "personal": "Shaxsiy jurnal",
        "channel": "Kanal", "group": "Guruh", "slow": "Bot hozir band — birozdan keyin qayta urinib ko'ring.",
        "pnl_total": "Ochiq natija", "open_n": "{n} ta ochiq",
        "goto_bot": "Botda ochish", "invested": "Summa", "limit": "Limit",
    },
    "ru": {
        "bot": "Бот", "open": "Открытые сигналы", "open_sub": "Живой результат и управление",
        "deposit": "Депозит", "spot": "Спот", "fut": "Фьючерсы", "stats": "Статистика",
        "stats_sub": "Страница результатов", "tour": "Турнир", "tour_sub": "Ежемесячный конкурс",
        "df": "Dip Funded", "df_sub": "Проп-счета", "soon": "Скоро",
        "home": "Главная", "signals": "Сигналы", "profile": "Профиль",
        "none": "Нет открытых сигналов", "entry": "Вход", "stop": "Стоп", "price": "Цена",
        "be": "БУ", "close": "Закрыть", "cancel": "Отменить", "newstop": "Новая цена стопа",
        "confirm_close": "Закрыть позицию полностью?", "confirm_cancel": "Отменить лимит?",
        "confirm_pc": "Закрыть {p}%?", "wait": "Выполняется…",
        "pending": "Ожидание", "nows": "У вас ещё нет журнала. Нажмите /start в боте.",
        "only_tg": "Эта страница открывается внутри Telegram.", "personal": "Личный журнал",
        "channel": "Канал", "group": "Группа", "slow": "Бот занят — попробуйте чуть позже.",
        "pnl_total": "Открытый результат", "open_n": "{n} открыто",
        "goto_bot": "Открыть в боте", "invested": "Сумма", "limit": "Лимит",
    },
    "en": {
        "bot": "Bot", "open": "Open signals", "open_sub": "Live result & controls",
        "deposit": "Deposit", "spot": "Spot", "fut": "Futures", "stats": "Statistics",
        "stats_sub": "Results page", "tour": "Tournament", "tour_sub": "Monthly contest",
        "df": "Dip Funded", "df_sub": "Prop accounts", "soon": "Soon",
        "home": "Home", "signals": "Signals", "profile": "Profile",
        "none": "No open signals", "entry": "Entry", "stop": "Stop", "price": "Price",
        "be": "BE", "close": "Close", "cancel": "Cancel", "newstop": "New stop price",
        "confirm_close": "Close the whole position?", "confirm_cancel": "Cancel the limit order?",
        "confirm_pc": "Close {p}%?", "wait": "Working…",
        "pending": "Pending", "nows": "No journal yet. Press /start in the bot.",
        "only_tg": "Open this page inside Telegram.", "personal": "Personal journal",
        "channel": "Channel", "group": "Group", "slow": "Bot is busy — try again shortly.",
        "pnl_total": "Open result", "open_n": "{n} open",
        "goto_bot": "Open in bot", "invested": "Size", "limit": "Limit",
    },
}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><title>Trade Controller</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{--bg:#000;--card:#141416;--card2:#1c1c1f;--line:#26262a;--ink:#f4f4f5;--mut:#8b8b92;
 --g:#2ecc8f;--r:#ff5c5c;--b:#3b82f6;--top:0px}
html,body{background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,Inter,"Segoe UI",Roboto,sans-serif}
body{padding:calc(var(--top) + 12px) 16px 120px;min-height:100vh}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px}
.pill{background:#1a1a1d;border:1px solid var(--line);border-radius:999px;padding:10px 16px;font-weight:600;
 font-size:15px;color:var(--ink);display:flex;align-items:center;gap:8px;max-width:70%;overflow:hidden;
 white-space:nowrap;text-overflow:ellipsis;text-decoration:none;cursor:pointer}
.pill select{position:absolute;opacity:0;inset:0}
.hero{text-align:center;margin:26px 0 22px}
.logo{width:120px;height:120px;margin:0 auto 12px;border-radius:32px;display:grid;place-items:center;
 background:radial-gradient(circle at 30% 25%,#2a2a30,#0d0d0f 70%);border:1px solid var(--line);
 box-shadow:0 0 60px rgba(46,204,143,.12)}
.hero h1{font-size:20px;font-weight:700}
.hero .sub{color:var(--mut);font-size:13px;margin-top:4px}
.big{font-size:34px;font-weight:800;margin-top:8px;letter-spacing:-.5px}
.card{position:relative;overflow:hidden;background:var(--card);border-radius:24px;padding:20px;margin-bottom:12px;
 min-height:118px;cursor:pointer;border:1px solid #1d1d21}
.card h2{font-size:21px;font-weight:700;line-height:1.2;max-width:62%}
.card .s{color:var(--mut);font-size:14px;margin-top:6px;max-width:62%}
.card .tag{position:absolute;right:18px;top:18px;background:rgba(255,255,255,.08);border-radius:999px;
 padding:7px 14px;font-weight:600;font-size:14px}
.card .tag2{top:62px;opacity:.75}
.c-open{background:linear-gradient(120deg,#11131a 0%,#14213a 55%,#2a5ca8 130%)}
.c-dep{background:linear-gradient(120deg,#121212 0%,#14261f 60%,#1f6b4d 140%)}
.c-tour{background:linear-gradient(120deg,#151313 0%,#2d2414 60%,#a8781e 140%)}
.c-df{background:linear-gradient(120deg,#121214 0%,#241634 60%,#6b3fb0 140%)}
.c-stats{background:linear-gradient(120deg,#121214 0%,#1b1f26 60%,#3b4a63 140%)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.row2 .card{margin-bottom:12px}
.row2 .card h2,.row2 .card .s{max-width:100%}
.deco{position:absolute;right:-6px;bottom:-10px;font-size:76px;opacity:.9;filter:drop-shadow(0 6px 18px rgba(0,0,0,.5))}
.nav{position:fixed;left:50%;transform:translateX(-50%);bottom:calc(14px + env(safe-area-inset-bottom,0px));
 width:min(92vw,440px);background:rgba(28,28,31,.82);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
 border:1px solid #2a2a2e;border-radius:999px;display:flex;padding:6px;z-index:10}
.nav a{flex:1;text-align:center;padding:8px 0 6px;border-radius:999px;color:var(--mut);font-size:11px;
 text-decoration:none;cursor:pointer}
.nav a .i{font-size:22px;display:block;line-height:1.1;margin-bottom:2px;filter:grayscale(1);opacity:.75}
.nav a.on{background:#3a3a3f;color:#fff}
.nav a.on .i{filter:none;opacity:1}
.g{color:var(--g)}.r{color:var(--r)}.m{color:var(--mut)}
.sig{background:var(--card);border:1px solid #1d1d21;border-radius:22px;padding:16px;margin-bottom:12px}
.sh{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.sym{font-weight:700;font-size:17px}
.b{display:inline-block;font-size:11px;font-weight:700;border-radius:8px;padding:2px 7px;margin-left:4px;vertical-align:2px}
.bl{background:rgba(46,204,143,.15);color:var(--g)}.bs{background:rgba(255,92,92,.15);color:var(--r)}
.bx{background:rgba(255,255,255,.08);color:#ddd}
.pnl{font-weight:800;font-size:20px;text-align:right}
.pnl small{display:block;font-size:13px;font-weight:600}
.kv{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}
.kv div{background:var(--card2);border-radius:12px;padding:8px 10px;font-size:13px}
.kv b{display:block;font-size:11px;color:var(--mut);font-weight:500}
.tps{font-size:13px;color:var(--mut);margin-bottom:12px;word-break:break-word}
.acts{display:flex;flex-wrap:wrap;gap:8px}
.btn{border:0;border-radius:12px;padding:10px 12px;font-weight:700;font-size:14px;color:#fff;background:#2a2a2e;
 cursor:pointer;flex:1;min-width:58px;white-space:nowrap}
.btn.p{background:var(--b)}.btn.s{background:#1f8f63}.btn.d{background:#c73e3e}
.btn:disabled{opacity:.5}
.empty{text-align:center;color:var(--mut);padding:60px 10px}
.toast{position:fixed;left:16px;right:16px;bottom:96px;background:#232327;border:1px solid #333;border-radius:16px;
 padding:12px 14px;font-size:14px;z-index:20;display:none}
h3{font-size:22px;margin:6px 0 14px}
</style></head><body>
<div class="top"><div class="pill" id="wsPill">…</div><a class="pill" id="botLink" href="#">🤖 <span id="tBot"></span></a></div>
<div id="view"></div>
<div class="toast" id="toast"></div>
<nav class="nav" id="nav"></nav>
<script>
var T=__T__;
var tg=window.Telegram&&window.Telegram.WebApp;var S={ws:[],cur:null,lang:'uz',tab:'home',items:[]};
function t(k,o){var s=(T[S.lang]||T.uz)[k]||k;if(o)for(var x in o)s=s.replace('{'+x+'}',o[x]);return s}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function fp(x){if(x==null)return'—';x=+x;if(x>=100)return x.toLocaleString('en-US',{maximumFractionDigits:2});if(x>=1)return x.toFixed(4);return(+x.toFixed(8)).toString()}
function fm(x){return(x>=0?'+':'−')+'$'+Math.abs(x).toLocaleString('en-US',{maximumFractionDigits:2})}
function fpc(x){return(x>=0?'+':'')+x.toFixed(2)+'%'}
function api(p,b){b=b||{};b.initData=tg?tg.initData:'';return fetch('/api/app/'+p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}).then(function(r){if(!r.ok)throw r.status;return r.json()})}
function toast(m){var e=document.getElementById('toast');e.innerHTML=m;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(function(){e.style.display='none'},4500)}
function haptic(k){try{tg.HapticFeedback.notificationOccurred(k)}catch(e){}}
function cur(){return S.ws.filter(function(w){return w.id==S.cur})[0]}
function wsName(w){return (w.type=='personal'?'📒 ':w.channel?'📢 ':'👥 ')+(w.type=='personal'?t('personal'):w.name)}
function nav(){var tabs=[['home','🏠',t('home')],['signals','📈',t('signals')],['stats','📊',t('stats')],['tour','🏆',t('tour')],['profile','👤',t('profile')]];
 document.getElementById('nav').innerHTML=tabs.map(function(x){return'<a class="'+(S.tab==x[0]?'on':'')+'" onclick="go(\\''+x[0]+'\\')"><span class="i">'+x[1]+'</span>'+esc(x[2])+'</a>'}).join('')}
function go(tab){S.tab=tab;try{tg.HapticFeedback.selectionChanged()}catch(e){}render()}
function botUrl(start){return 'https://t.me/'+S.bot+(start?'?start='+start:'')}
function openLink(u){if(!u)return;if(u.indexOf('https://t.me/')==0&&tg&&tg.openTelegramLink)tg.openTelegramLink(u);else if(tg&&tg.openLink&&u.indexOf('http')==0)tg.openLink(u);else location.href=u}
function pill(){var w=cur();var el=document.getElementById('wsPill');
 if(!w){el.textContent='Trade Controller';return}
 el.innerHTML='<span>'+esc(wsName(w))+(S.ws.length>1?' ▾':'')+'</span>'+(S.ws.length>1?'<select id="wsSel">'+S.ws.map(function(x){return'<option value="'+x.id+'"'+(x.id==S.cur?' selected':'')+'>'+esc(wsName(x))+'</option>'}).join('')+'</select>':'');
 el.style.position='relative';var s=document.getElementById('wsSel');if(s)s.onchange=function(){S.cur=+s.value;try{localStorage.setItem('tc_ws',S.cur)}catch(e){}load()}}
function totals(){var m=0,has=false,p=0;S.items.forEach(function(i){if(i.money!=null){m+=i.money;has=true}});return has?m:null}
function render(){nav();pill();var v=document.getElementById('view');var w=cur();
 if(!w){v.innerHTML='<div class="empty">'+esc(t('nows'))+'</div>';return}
 if(S.tab=='home')return home(v,w);if(S.tab=='signals')return signals(v,w);
 if(S.tab=='stats'){if(w.page)openLink(location.origin+w.page);S.tab='home';return render()}
 if(S.tab=='tour'){openLink(location.origin+'/t');S.tab='home';return render()}
 if(S.tab=='profile'){openLink(botUrl());S.tab='home';return render()}}
function home(v,w){var tot=totals();var n=S.items.length;
 var dep='';if(w.deposit!=null)dep+=t('spot')+': $'+w.deposit.toLocaleString('en-US',{maximumFractionDigits:0});
 if(w.fut_deposit!=null)dep+=(dep?' · ':'')+t('fut')+': $'+w.fut_deposit.toLocaleString('en-US',{maximumFractionDigits:0});
 v.innerHTML='<div class="hero"><div class="logo"><svg width="64" height="64" viewBox="0 0 64 64"><g stroke-linecap="round"><line x1="14" y1="14" x2="14" y2="50" stroke="#ff5c5c" stroke-width="3"/><rect x="9" y="22" width="10" height="18" rx="3" fill="#ff5c5c"/><line x1="32" y1="8" x2="32" y2="44" stroke="#2ecc8f" stroke-width="3"/><rect x="27" y="14" width="10" height="22" rx="3" fill="#2ecc8f"/><line x1="50" y1="4" x2="50" y2="36" stroke="#2ecc8f" stroke-width="3"/><rect x="45" y="8" width="10" height="20" rx="3" fill="#2ecc8f"/></g></svg></div>'
 +'<h1>'+esc(w.type=='personal'?t('personal'):w.name)+'</h1>'
 +(tot!=null?'<div class="big '+(tot>=0?'g':'r')+'">'+fm(tot)+'</div><div class="sub">'+esc(t('pnl_total'))+'</div>':'<div class="sub">Trade Controller</div>')+'</div>'
 +'<div class="card c-open" onclick="go(\\'signals\\')"><h2>'+esc(t('open'))+'</h2><div class="s">'+esc(t('open_sub'))+'</div><div class="tag">'+esc(t('open_n',{n:n}))+'</div><div class="deco">📈</div></div>'
 +'<div class="card c-dep" onclick="openLink(botUrl())"><h2>'+esc(t('deposit'))+'</h2><div class="s">'+esc(dep||'—')+'</div><div class="deco">💰</div></div>'
 +'<div class="row2"><div class="card c-stats" onclick="go(\\'stats\\')"><h2>'+esc(t('stats'))+'</h2><div class="s">'+esc(w.page?t('stats_sub'):t('soon'))+'</div><div class="deco" style="font-size:54px">📊</div></div>'
 +'<div class="card c-tour" onclick="go(\\'tour\\')"><h2>'+esc(t('tour'))+'</h2><div class="s">'+esc(t('tour_sub'))+'</div><div class="deco" style="font-size:54px">🏆</div></div></div>'
 +'<div class="card c-df" onclick="openLink(botUrl())"><h2>'+esc(t('df'))+'</h2><div class="s">'+esc(t('df_sub'))+'</div><div class="deco">🚀</div></div>'}
function sigCard(i){var long=i.side=='LONG';var pend=i.status=='PENDING';
 var pnl=i.live!=null?'<div class="pnl '+(i.live>=0?'g':'r')+'">'+fpc(i.live)+(i.money!=null?'<small>'+fm(i.money)+'</small>':'')+'</div>':'<div class="pnl m" style="font-size:14px">'+esc(pend?t('limit'):'—')+'</div>';
 var tps=i.tps.map(function(x,k){return(k<i.tp_hit?'✅':'◻️')+fp(x)}).join(' · ');
 var a='';if(!pend&&i.sl!=null){var be=Math.abs(i.sl-i.entry)<1e-12;
  a+='<button class="btn p" '+(be?'disabled':'')+' onclick="act('+i.id+',\\'be\\')">'+esc(t('be'))+'</button>'
   +'<button class="btn" onclick="askStop('+i.id+')">✏️ '+esc(t('stop'))+'</button>';
  if(i.filled<0.999)a+='<button class="btn" onclick="act('+i.id+',\\'pc\\',25)">25%</button><button class="btn" onclick="act('+i.id+',\\'pc\\',50)">50%</button><button class="btn" onclick="act('+i.id+',\\'pc\\',75)">75%</button>'}
 a+='<button class="btn d" onclick="act('+i.id+',\\'close\\')">'+esc(pend?t('cancel'):t('close'))+'</button>';
 return '<div class="sig" id="s'+i.id+'"><div class="sh"><div><div class="sym">'+esc(i.symbol)+'<span class="b '+(long?'bl':'bs')+'">'+i.side+'</span>'+(i.lev>1?'<span class="b bx">'+i.lev+'x</span>':'')+'</div><div class="m" style="font-size:12px;margin-top:2px">#'+i.id+(i.alloc?' · '+esc(t('invested'))+' $'+i.alloc.toLocaleString('en-US',{maximumFractionDigits:0}):'')+'</div></div>'+pnl+'</div>'
 +'<div class="kv"><div><b>'+esc(t('entry'))+'</b>'+fp(i.entry)+'</div><div><b>'+esc(t('stop'))+'</b>'+fp(i.sl)+'</div><div><b>'+esc(t('price'))+'</b>'+fp(i.price)+'</div></div>'
 +(tps?'<div class="tps">🎯 '+tps+'</div>':'')+'<div class="acts">'+a+'</div></div>'}
function signals(v,w){v.innerHTML='<h3 style="margin-top:18px">'+esc(t('open'))+'</h3>'+(S.items.length?S.items.map(sigCard).join(''):'<div class="empty">'+esc(t('none'))+'</div>')}
function confirmBox(m,cb){if(tg&&tg.showConfirm){try{tg.showConfirm(m,function(ok){if(ok)cb()});return}catch(e){}}if(confirm(m))cb()}
function askStop(id){var i=S.items.filter(function(x){return x.id==id})[0];var p=prompt(t('newstop')+' ('+i.symbol+')',i.sl);if(p==null)return;p=parseFloat(String(p).replace(',','.'));if(!(p>0))return;act(id,'sl',p,true)}
function act(id,a,arg,skip){var i=S.items.filter(function(x){return x.id==id})[0];
 var m=a=='close'?(i.status=='PENDING'?t('confirm_cancel'):t('confirm_close')):a=='pc'?t('confirm_pc',{p:arg}):null;
 var run=function(){var card=document.getElementById('s'+id);if(card)card.querySelectorAll('button').forEach(function(b){b.disabled=true});toast(esc(t('wait')));
  api('act',{sig:id,action:a,arg:arg}).then(function(r){if(r.pending){toast(esc(t('slow')));}else{toast(r.msg||'OK');haptic(r.ok?'success':'error')}load()}).catch(function(){toast('⚠️');load()})};
 if(m&&!skip)confirmBox(m,run);else run()}
function load(){var w=cur();if(!w){render();return}
 return api('open',{ws:w.id}).then(function(d){S.items=d.items;w.open=d.items.length;render()}).catch(function(){render()})}
(function init(){if(tg){try{tg.ready();tg.expand();tg.setHeaderColor&&tg.setHeaderColor('#000000');tg.setBackgroundColor&&tg.setBackgroundColor('#000000');
 var ins=(tg.contentSafeAreaInset&&tg.contentSafeAreaInset.top||0)+(tg.safeAreaInset&&tg.safeAreaInset.top||0);document.documentElement.style.setProperty('--top',ins+'px')}catch(e){}}
 if(!tg||!tg.initData){document.getElementById('view').innerHTML='<div class="empty">'+esc(t('only_tg'))+'</div>';return}
 api('me').then(function(d){S.ws=d.ws;S.lang=d.lang||'uz';S.bot=d.bot;document.getElementById('tBot').textContent=t('bot');
  document.getElementById('botLink').onclick=function(e){e.preventDefault();openLink(botUrl())};
  var saved=null;try{saved=+localStorage.getItem('tc_ws')}catch(e){}
  S.cur=(S.ws.filter(function(x){return x.id==saved})[0]||S.ws[0]||{}).id;
  var q=new URLSearchParams(location.search);if(q.get('tab'))S.tab=q.get('tab');
  render();load();setInterval(function(){if(!document.hidden)load()},15000)})
 .catch(function(){document.getElementById('view').innerHTML='<div class="empty">⚠️</div>'})})();
</script></body></html>""".replace("__T__", json.dumps(T, ensure_ascii=False))
