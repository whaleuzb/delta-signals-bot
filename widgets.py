"""363: Telegram Bot API 10.4 widjetlari — chat ichidagi kichik interaktiv bloklar.

Hujjat: https://core.telegram.org/bots/widgets (sandbox QuickJS, tarmoq yo'q, HTML ≤ 32 KB va
zlib-9 bilan siqilganda ≤ 4096 bayt, holat — `chat_data`/`public_data` ≤ 1024 bayt, so'rov
`TelegramWidget.request(data)` 1-64 bayt → bot `widget_query` oladi va 15 s ichida
`answerWidgetQuery(data ≤ 1024 bayt)` bilan javob beradi). Hozircha prod'da FAQAT bot bilan
shaxsiy chatda ishlaydi; shaxsiy chatda widjet ko'rinib turganda o'zi (fon so'rovi) har 5 s dan
siyrak so'rashi mumkin — biz har 20 s da yangi holat so'raymiz (`r`).

Widjetlar:
  pos   — egasining ochiq signallari, jonli P&L; BE / 50% / yopish (ikki bosish)        (1)
  trade — signalni ulangan birjada ochish: birja, Spot/Futures, 10-100%, ikki bosish   (2)
  df    — Dip Funded hisobi: equity, kunlik limit / maks. zarar / maqsad, pozitsiyalar (4)
  dip   — DIP balans, vazifalar (bajarish / tekshirish), taklif havolasini nusxalash    (5)

Javob formati (hammasi uchun): {"d": yangi holat (ixtiyoriy), "m": xabar matni (ixtiyoriy)}.
Birja savdosi web servisda (kalitlar va Singapur relay o'sha yerda) — `/api/internal/wtrade`."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import zlib

import config
import db
import i18n

log = logging.getLogger(__name__)

# ─────────────────────────── matnlar ───────────────────────────
WT = {
    "uz": {"pos": "Ochiq pozitsiyalar", "none": "Ochiq pozitsiya yo'q", "lim": "Limit", "entry": "Kirish",
           "px": "Narx", "close": "Yopish", "cancel": "Bekor", "sure": "Yana bosing", "busy": "Biroz kuting va qayta bosing",
           "err": "Xato — qayta urinib ko'ring", "app": "Ilovada ochish", "trade": "Birjada ochish",
           "nokey": "Birja ulanmagan — ilovada ulang", "free": "Bo'sh", "amt": "Summa", "buy": "Ochish",
           "dl": "Kunlik limit", "mx": "Maks. zarar", "tg": "Maqsad", "days": "Kunlar", "left": "qoldi",
           "eq": "Hisob", "bal": "DIP balans", "tasks": "Vazifalar", "go": "Bajarish", "ck": "Tekshirish",
           "done": "Bajarildi", "ref": "Taklif havolasi", "copy": "Nusxa", "notask": "Hozircha yangi vazifa yo'q",
           "upd": "yangilandi", "chart": "Grafik", "save": "Saqlash", "drag": "Surgichni chapga-o'ngga suring", "tour": "Turnir", "own": "Ichki", "you": "Siz", "refs": "Takliflar", "week": "bu hafta", "earned": "ishlab topildi", "per": "har bir taklif uchun", "share": "Ulashish", "inv": "Trade Controller — signallar, birja va Dip Funded bitta botda. Qo'shiling:", "live": "Jonli", "closed": "Yopildi", "upnl": "ochiq · jami", "load": "Yuklanmoqda…"},
    "ru": {"pos": "Открытые позиции", "none": "Нет открытых позиций", "lim": "Лимит", "entry": "Вход",
           "px": "Цена", "close": "Закрыть", "cancel": "Отменить", "sure": "Нажмите ещё раз", "busy": "Подождите и нажмите снова",
           "err": "Ошибка — попробуйте ещё раз", "app": "Открыть в приложении", "trade": "Открыть на бирже",
           "nokey": "Биржа не подключена — подключите в приложении", "free": "Свободно", "amt": "Сумма", "buy": "Открыть",
           "dl": "Дневной лимит", "mx": "Макс. просадка", "tg": "Цель", "days": "Дни", "left": "осталось",
           "eq": "Счёт", "bal": "Баланс DIP", "tasks": "Задания", "go": "Выполнить", "ck": "Проверить",
           "done": "Выполнено", "ref": "Ссылка-приглашение", "copy": "Копировать", "notask": "Новых заданий пока нет",
           "upd": "обновлено", "chart": "График", "save": "Сохранить", "drag": "Двигайте ползунок влево-вправо", "tour": "Турнир", "own": "Внутренний", "you": "Вы", "refs": "Приглашения", "week": "за неделю", "earned": "заработано", "per": "за каждое приглашение", "share": "Поделиться", "inv": "Trade Controller — сигналы, биржа и Dip Funded в одном боте. Присоединяйтесь:", "live": "Онлайн", "closed": "Закрыта", "upnl": "открыто · итог", "load": "Загрузка…"},
    "en": {"pos": "Open positions", "none": "No open positions", "lim": "Limit", "entry": "Entry",
           "px": "Price", "close": "Close", "cancel": "Cancel", "sure": "Tap again", "busy": "Wait a moment and tap again",
           "err": "Error — try again", "app": "Open in the app", "trade": "Open on exchange",
           "nokey": "No exchange connected — connect one in the app", "free": "Free", "amt": "Amount", "buy": "Open",
           "dl": "Daily limit", "mx": "Max loss", "tg": "Target", "days": "Days", "left": "left",
           "eq": "Account", "bal": "DIP balance", "tasks": "Tasks", "go": "Start", "ck": "Check",
           "done": "Done", "ref": "Invite link", "copy": "Copy", "notask": "No new tasks yet",
           "upd": "updated", "chart": "Chart", "save": "Save", "drag": "Drag the slider left or right", "tour": "Tournament", "own": "Internal", "you": "You", "refs": "Invites", "week": "this week", "earned": "earned", "per": "per invite", "share": "Share", "inv": "Trade Controller — signals, exchanges and Dip Funded in one bot. Join:", "live": "Live", "closed": "Closed", "upnl": "open · total", "load": "Loading…"},
}
EXN = {"binance": "Binance", "bitget": "Bitget", "bingx": "BingX", "mexc": "MEXC", "bitunix": "Bitunix", "bybit": "Bybit"}

# ─────────────────────────── HTML ───────────────────────────
# Umumiy: holat D (chatData'dan), so'rov Q() — bitta vaqtda bitta, javobdagi d/m qo'llanadi,
# ko'rinib turganda har 20 s da 'r' (fon so'rovi; shaxsiy chatda ruxsat). Bosishlar —
# delegatsiya (data-a / data-v), so'rov bosish ishlovchisi ichida sinxron chaqiriladi.
# 364: Trade Controller uslubi — tungi fon (#070807), burchakda lime nur, Acid Lime (#c2f23a) urg'u,
# qizil #ff5c5c, oynasimon qatorlar va pill tugmalar (ilovadagi `.glass`/`.chip`/`.btn.p` kabi).
# Fon body'da — hujjatga ko'ra butun pufakni (bubble) bo'yaydi, yorug' mavzuda ham bir xil ko'rinadi.
_CSS = ("body{margin:0;padding:12px 13px 13px;font:13.5px/1.35 system-ui,sans-serif;color:#f5f5f7;font-variant-numeric:tabular-nums;"
        "background:radial-gradient(130% 80% at 0% 0%,rgba(194,242,58,.14),rgba(194,242,58,0) 55%),linear-gradient(165deg,#13150f,#070807)}"
        ".h{display:flex;justify-content:space-between;align-items:center;font-size:11.5px;color:rgba(200,205,194,.62);margin-bottom:6px}"
        ".h b{color:#f5f5f7;font-size:14.5px;font-weight:800;display:flex;align-items:center;gap:7px}"
        ".lg{width:20px;height:20px;border-radius:7px;background:#c2f23a;color:#0b0c0a;font-size:10px;font-weight:900;display:inline-flex;align-items:center;justify-content:center}"
        ".m{color:rgba(200,205,194,.62);font-size:11.5px;margin-top:2px}"
        ".g{color:#c2f23a}.e{color:#ff5c5c}.k{font-weight:800}"
        ".r{padding:9px 10px;margin-top:6px;border-radius:14px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08)}"
        ".r.on{border-color:rgba(194,242,58,.45)}"
        ".t{display:flex;justify-content:space-between;align-items:center;gap:8px}"
        ".a{display:flex;gap:6px;margin-top:8px}"
        "button{flex:1;padding:9px 4px;font-size:12.5px;font-weight:700;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);color:#f5f5f7}"
        "button.p{background:rgba(194,242,58,.16);border-color:rgba(194,242,58,.42);color:#c2f23a}"
        "button.d{background:rgba(255,92,92,.13);border-color:rgba(255,92,92,.38);color:#ff5c5c}"
        "button[disabled]{color:rgba(200,205,194,.36)}"
        ".c{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}"
        ".c button{flex:none;padding:6px 12px;border-radius:999px;font-size:12px;color:rgba(200,205,194,.8)}"
        ".c .on{border-color:rgba(194,242,58,.55);background:rgba(194,242,58,.1);color:#fff}"
        ".n{font-size:12px;margin-top:9px;padding:7px 10px;border-radius:10px;background:rgba(255,255,255,.05);color:#e8eae4}"
        ".bar{height:6px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden;margin:4px 0 9px}.bar i{display:block;height:100%;border-radius:3px}"
        ".tg{font-size:10px;font-weight:800;padding:2px 6px;border-radius:6px;margin-left:6px}"
        ".L{background:rgba(194,242,58,.14);color:#c2f23a}.S{background:rgba(255,92,92,.14);color:#ff5c5c}"
        ".av{width:30px;height:30px;border-radius:50%;background:rgba(194,242,58,.12);color:#c2f23a;font-weight:900;font-size:11px;display:inline-flex;align-items:center;justify-content:center;margin-right:9px;flex:none}"
        ".rg{position:relative;height:4px;border-radius:2px;margin:9px 0 3px;background:linear-gradient(90deg,#ff5c5c,rgba(255,255,255,.18) 45%,#c2f23a)}"
        ".rg i{position:absolute;top:-4px;width:12px;height:12px;border-radius:50%;background:#fff;margin-left:-6px;transition:left .6s}"
        ".rg b{position:absolute;top:-3px;width:2px;height:10px;background:rgba(255,255,255,.55);margin-left:-1px}"
        ".big{font-size:24px;font-weight:900;letter-spacing:-.02em}"
        ".sl{position:relative;height:30px;margin:6px 4px 0;touch-action:pan-y}"
        ".sl:before{content:'';position:absolute;left:0;right:0;top:13px;height:4px;border-radius:2px;background:rgba(255,255,255,.12)}"
        ".sl i{position:absolute;top:5px;width:20px;height:20px;border-radius:50%;margin-left:-10px;background:#c2f23a}"
        ".md{display:inline-block;width:22px}")

_JS = ("var W=TelegramWidget,w=document.getElementById('w'),B=0,M='',S=0,C=0,G=null;"
       "function P(s){try{return JSON.parse(s)}catch(e){return null}}var D=P(W.chatData)||{};"
       "function F(x,n){return x==null?'—':Number(x).toLocaleString('en-US',{maximumFractionDigits:n==null?2:n})}"
       "function U(x){return(x>=0?'+$':'-$')+F(Math.abs(x))}"
       "function H(t,i){return'<div class=h><b><span class=lg>'+(i||'TC')+'</span>'+t+'</b><span>'+(B?'⟳':(D.t||''))+'</span></div>'}"
       "function Q(x,f){if(B){M='{{busy}}';R();return}B=1;R();W.request(x).then(function(a){B=0;var r=P(a.result)||{};"
       "if(r.d)D=r.d;if(r.g)G=r.g;M=r.m||'';if(f)f(r);R()},function(e){B=0;M=e.code=='BUSY'||e.code=='RATE_LIMITED'?'{{busy}}':'{{err}}';R()})}"
       "W.onEvent('chatDataChanged',function(){D=P(W.chatData)||D;R()});"
       "w.addEventListener('click',function(e){var t=e.target;while(t&&t!==w&&!(t.dataset&&t.dataset.a))t=t.parentNode;"
       "if(t&&t!==w)A(t.dataset.a,t.dataset.v)});"
       "function T2(v,f){if(C!==v){C=v;R();setTimeout(function(){if(C===v){C=0;R()}},3500);return}C=0;f()}"
       "function RQ(){return 'r'}"
       "setInterval(function(){if(W.isActive&&!B)Q(RQ())},20000);")

_TAIL = "R();Q(RQ());"

# (1) Ochiq pozitsiyalar. Qator: [sid, sym, 'L'|'S', pnl%, narx, kirish, sl, lev, 'A'|'P', $pnl, q, e, tp]
# q / e — narx va kirishning SL→TP oralig'idagi o'rni (0..1): "qayerdamiz" chizig'i.
_POS = ("function R(){var L=D.L||[],tot=0;L.forEach(function(x){if(x[9]!=null)tot+=x[9]});"
        "var h=H('{{pos}}')+(L.length?'<div class=t><span class=m>'+L.length+' · {{upnl}}</span><span class=\"k '+(tot>=0?'g':'e')+'\" style=font-size:17px>'+U(tot)+'</span></div>':'<div class=m>{{none}}</div>');"
        "L.forEach(function(x){var p=x[8]=='P',o=S==x[0],pc=p||x[3]==null?'':x[3]>=0?'g':'e';"
        "h+='<div class=\"r'+(o?' on':'')+'\" data-a=s data-v='+x[0]+'><div class=t><span style=display:flex;align-items:center><span class=av>'+x[1].slice(0,3)+'</span><span><span class=k>'+x[1]+'</span>'"
        "+'<span class=\"tg '+x[2]+'\">'+(x[2]=='L'?'LONG':'SHORT')+(x[7]>1?' '+x[7]+'x':'')+'</span><div class=m>{{entry}} '+x[5]+' · {{px}} '+x[4]+'</div></span></span>'"
        "+'<span style=text-align:right><div class=\"k '+pc+'\" style=font-size:15px>'+(p?'{{lim}}':(x[3]>=0?'+':'')+F(x[3])+'%')+'</div>'+(x[9]!=null?'<div class=\"m '+pc+'\">'+U(x[9])+'</div>':'')+'</span></div>';"
        "if(x[10]!=null)h+='<div class=rg><b style=left:'+x[11]*100+'%></b><i style=left:'+x[10]*100+'%></i></div><div class=\"t m\" style=font-size:10.5px><span>SL '+x[6]+'</span><span>TP '+x[12]+'</span></div>';"
        "if(o)h+='<div class=a><button data-a=ch>📈</button>'+(p?'':'<button data-a=be class=p>BE</button><button data-a=pc>50%</button>')"
        "+'<button data-a=cl class=d>'+(C==x[0]?'{{sure}}':(p?'{{cancel}}':'{{close}}'))+'</button></div>'+(G&&G.s==x[0]?CH():'');h+='</div>'});"
        "if(M)h+='<div class=n>'+M+'</div>';"
        "h+='<div class=a><button data-a=app>{{app}} ›</button></div>';w.innerHTML=h}"
        "function A(a,v){if(a=='s'){if(S!=v)G=null;S=S==v?0:+v;C=0;R()}else if(a=='be')Q('be:'+S);else if(a=='pc')Q('pc:'+S+':50');"
        "else if(a=='cl')T2(S,function(){Q('cl:'+S)});else if(a=='app')W.openTelegramLink('{{link}}');"
        "else if(a=='ch')Q('ch:'+S);else if(a=='e'){E=v;NV=null;R()}else if(a=='sv'&&NV)Q(E+':'+S+':'+NV,function(r){if(!r.err&&G)G[E]=NV;NV=null})}"
        # 364-2: grafik — shamlar 0..4095 ga kodlangan (2 belgi), Y = 125 - v/4095*118; chiziqlar: kirish, SL, TP, narx.
        "var E='sl',NV=null,AB='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';"
        "function Z(i){return AB.indexOf(G.c[i])*64+AB.indexOf(G.c[i+1])}"
        "function V(p){return(p-G.lo)/(G.hi-G.lo)*4095}function Y(v){return(125-v/4095*118).toFixed(1)}"
        "function LN(p,c,t,id){if(p==null)return'';var y=Y(V(p));return'<line '+(id?'id='+id+' ':'')+'x1=0 x2=300 y1='+y+' y2='+y+' stroke='+c+' stroke-dasharray=4,3 />'"
        "+'<text '+(id?'id='+id+'t ':'')+'x=296 y='+(y-3)+' fill='+c+' font-size=10 text-anchor=end>'+t+' '+F(p,6)+'</text>'}"
        "function CH(){var n=G.c.length/8,cw=300/n,s='<svg viewBox=\"0 0 300 130\" width=100% height=140 style=display:block;margin-top:8px>';"
        "for(var j=0;j<n;j++){var o=Z(j*8),hh=Z(j*8+2),ll=Z(j*8+4),c=Z(j*8+6),k=c>=o?'#c2f23a':'#ff5c5c',x=(j*cw+cw/2).toFixed(1),t=Y(Math.max(o,c)),b=Y(Math.min(o,c));"
        "s+='<line x1='+x+' x2='+x+' y1='+Y(hh)+' y2='+Y(ll)+' stroke='+k+' /><rect x='+(x-cw*.35).toFixed(1)+' width='+(cw*.7).toFixed(1)+' y='+t+' height='+Math.max(1,b-t).toFixed(1)+' fill='+k+' />'}"
        "s+=LN(G.e,'#f5f5f7','{{entry}}')+LN(E=='sl'&&NV?NV:G.sl,'#ff5c5c','SL',E=='sl'?'ed':'')+LN(E=='tp'&&NV?NV:G.tp,'#c2f23a','TP',E=='tp'?'ed':'')+'</svg>';"
        "var cur=NV||G[E]||G.px,f=Math.max(0,Math.min(1,V(cur)/4095));"
        "return s+'<div class=c><button data-a=e data-v=sl'+(E=='sl'?' class=on':'')+'>SL</button><button data-a=e data-v=tp'+(E=='tp'?' class=on':'')+'>TP</button><span class=m style=align-self:center>{{drag}}</span></div>'"
        "+'<div class=sl id=sl><i id=kn style=left:'+f*100+'%></i></div><div class=a><button data-a=sv class=p'+(NV?'':' disabled')+'>{{save}}'+(NV?' · '+F(NV,6):'')+'</button></div>'}"
        "var SR=null;w.addEventListener('pointerdown',function(e){var t=e.target;if(!t||(t.id!='sl'&&t.id!='kn')||!G)return;var el=document.getElementById('sl');SR=el.getBoundingClientRect();try{el.setPointerCapture(e.pointerId)}catch(x){}MV(e)});"
        "w.addEventListener('pointermove',function(e){if(SR)MV(e)});w.addEventListener('pointerup',function(){if(SR){SR=null;R()}});w.addEventListener('pointercancel',function(){SR=null});"
        "function MV(e){var f=Math.max(0,Math.min(1,(e.clientX-SR.left)/SR.width)),p=G.lo+f*(G.hi-G.lo);NV=+p.toPrecision(6);"
        "var k=document.getElementById('kn');if(k)k.style.left=f*100+'%';var l=document.getElementById('ed'),y=Y(V(NV));if(l){l.setAttribute('y1',y);l.setAttribute('y2',y)}"
        "var tt=document.getElementById('edt');if(tt){tt.setAttribute('y',y-3);tt.textContent=E.toUpperCase()+' '+F(NV,6)}}")

# (2) Tezkor savdo. D: {s,y,d,e,sl,tp,lv,f,x:[[ex,nom]],i:{av,px}}
_TRADE = ("var X=0,K=D.f?'fut':'spot',G=25;function RQ(){return D.x&&D.x.length?'i:'+D.s+':'+D.x[X][0]+':'+K:'n'}"
          "function R(){var h=H((D.y||'')+'<span class=\"tg '+D.d+'\">'+(D.d=='L'?'LONG':'SHORT')+(D.f&&D.lv?' '+D.lv+'x':'')+'</span>','⚡')"
          "+'<div class=r style=\"display:flex;justify-content:space-between;text-align:center\"><span><div class=m>{{entry}}</div><b>'+D.e+'</b></span><span><div class=m>SL</div><b class=e>'+(D.sl||'—')+'</b></span><span><div class=m>TP</div><b class=g>'+(D.tp||'—')+'</b></span></div>';var x=D.x||[];"
          "if(!x.length){h+='<div class=n>{{nokey}}</div><div class=a><button data-a=app class=p>{{app}} ›</button></div>';w.innerHTML=h;return}"
          "h+='<div class=c>'+x.map(function(z,j){return'<button data-a=x data-v='+j+(j==X?' class=on':'')+'>'+z[1]+'</button>'}).join('')"
          "+(D.f?'<button data-a=k data-v=fut'+(K=='fut'?' class=on':'')+'>Futures</button>'+(D.d=='L'?'<button data-a=k data-v=spot'+(K=='spot'?' class=on':'')+'>Spot</button>':''):'')+'</div>';"
          "var i=D.i||{},av=i.av,amt=av!=null?Math.floor(av*G)/100:null;"
          "h+='<div class=t><span class=m>{{free}}: '+(av==null?'…':'$'+F(av))+(i.px?' · {{px}} '+i.px:'')+'</span></div>'"
          "+'<div class=t style=margin:6px 0 2px><span class=m>{{amt}}</span><span class=big>'+(amt==null?'—':'$'+F(amt))+'</span></div>';"
          "h+='<div class=c>'+[10,25,50,100].map(function(p){return'<button data-a=p data-v='+p+(p==G?' class=on':'')+'>'+p+'%</button>'}).join('')+'</div>';"
          "h+='<div class=a><button data-a=go class='+(D.d=='L'?'p':'d')+(amt?'':' disabled')+' style=padding:12px;font-size:14px>'"
          "+(C=='go'?'{{sure}}':'{{buy}} '+(D.d=='L'?'LONG':'SHORT'))+'</button></div>';"
          "if(M)h+='<div class=n>'+M+'</div>';w.innerHTML=h}"
          "function A(a,v){if(a=='x'){X=+v;D.i=null;C=0;Q(RQ())}else if(a=='k'){K=v;D.i=null;C=0;Q(RQ())}else if(a=='p'){G=+v;C=0;R()}"
          "else if(a=='go')T2('go',function(){Q('o:'+D.s+':'+D.x[X][0]+':'+K+':'+G)});else if(a=='app')W.openTelegramLink('{{link}}')}")

# (4) Dip Funded. D: {c,n,s,eq,pn,dl:[%,left],mx:[%,left],tg:%,dy,p:[[sym,upnl,%]],a:[[id,nom]],t}
_DF = ("function RQ(){return 'r:'+(D.c||0)}"
       "function K(v){return v>75?'#ff5c5c':v>50?'#f5b83d':'#c2f23a'}"
       "function G(l,v,c,s){v=Math.max(0,Math.min(100,v||0));return'<div class=t style=font-size:12px;margin-top:4px><span>'+l+'</span><span class=m>'+s+'</span></div><div class=bar><i style=\"width:'+v+'%;background:'+c+'\"></i></div>'}"
       "function R(){var h=H('Dip Funded','DF');if(!D.c){w.innerHTML=h+'<div class=m>'+(M||'{{load}}')+'</div>';return}"
       "if(D.a&&D.a.length>1)h+='<div class=c>'+D.a.map(function(z){return'<button data-a=a data-v='+z[0]+(z[0]==D.c?' class=on':'')+'>'+z[1]+'</button>'}).join('')+'</div>';"
       "h+='<div class=m>'+D.n+' · '+D.s+'</div><div class=t style=margin:3px 0 8px><span class=big>$'+F(D.eq)+'</span><span class=\"k '+(D.pn>=0?'g':'e')+'\" style=font-size:15px>'+U(D.pn)+'</span></div>';"
       "var dl=D.dl||[0,0],mx=D.mx||[0,0];h+='<div class=r>'+G('{{dl}}',dl[0],K(dl[0]),F(dl[0],0)+'% · $'+F(dl[1])+' {{left}}')"
       "+G('{{mx}}',mx[0],K(mx[0]),F(mx[0],0)+'% · $'+F(mx[1])+' {{left}}')"
       "+(D.tg!=null?G('{{tg}}',D.tg,'#c2f23a',F(D.tg,0)+'%'+(D.dy?' · {{days}} '+D.dy:'')):'')+'</div>';"
       "(D.p||[]).forEach(function(x){h+='<div class=\"r t\"><span style=display:flex;align-items:center><span class=av>'+x[0].slice(0,3)+'</span><b>'+x[0]+'</b></span><span class=\"k '+(x[1]>=0?'g':'e')+'\">'+U(x[1])+' · '+F(x[2])+'%</span></div>'});"
       "if(M)h+='<div class=n>'+M+'</div>';h+='<div class=a><button data-a=app>{{app}} ›</button></div>';w.innerHTML=h}"
       "function A(a,v){if(a=='a'){D.c=+v;Q(RQ())}else if(a=='app')W.openTelegramLink('{{link}}')}")

# (5) DIP. D: {b, u ($), T:[[id,nom,dip,url,done]], l: taklif havolasi}
_DIP = ("function RQ(){return 'dr'}function R(){var h=H('DIP','💎')"
        "+'<div class=r><div class=m>{{bal}}</div><div class=t><span class=\"big g\">'+F(D.b)+' DIP</span><span class=m>≈ $'+F(D.u)+'</span></div></div>';"
        "var T=D.T||[];h+='<div class=m style=margin-top:10px>{{tasks}}</div>';if(!T.length)h+='<div class=m>{{notask}}</div>';"
        "T.forEach(function(x){h+='<div class=r><div class=t><span class=k>'+x[1]+'</span><span class=\"tg L\">+'+F(x[2])+' DIP</span></div>'"
        "+(x[4]?'<div class=\"m g\">✓ {{done}}</div>':'<div class=a><button data-a=go data-v='+x[0]+'>{{go}} ›</button><button data-a=ck data-v='+x[0]+' class=p>{{ck}}</button></div>')+'</div>'});"
        "if(D.l)h+='<div class=a style=margin-top:10px><button data-a=cp class=p>🔗 {{ref}} · {{copy}}</button></div>';"
        "if(M)h+='<div class=n>'+M+'</div>';w.innerHTML=h}"
        "function A(a,v){if(a=='ck')Q('ck:'+v);else if(a=='cp')W.copyText(D.l);else if(a=='go'){var x=(D.T||[]).filter(function(z){return z[0]==v})[0];"
        "if(x&&x[3]){if(/^https:\\/\\/t\\.me\\//.test(x[3]))W.openTelegramLink(x[3]);else W.openLink(x[3])}}}")

# (7) Turnir. D: {k:'df'|'own', b:[[o'rin, ism, %]], o:[[o'rin, ism, %]], me:[o'rin, %], st, t}
_TOUR = ("var TB=0;function RQ(){return 'tr'}"
         "function RW(L,me){var h='';(L||[]).forEach(function(x){var md=['🥇','🥈','🥉'][x[0]-1]||'#'+x[0];"
         "h+='<div class=\"r t\"'+(x[3]?' style=border-color:rgba(194,242,58,.5)':'')+'><span><span class=md>'+md+'</span><b>'+x[1]+'</b></span><span class=\"k '+(x[2]>=0?'g':'e')+'\">'+(x[2]>=0?'+':'')+F(x[2])+'%</span></div>'});"
         "if(me)h+='<div class=n>{{you}}: <b>#'+me[0]+'</b> · <b class='+(me[1]>=0?'g':'e')+'>'+(me[1]>=0?'+':'')+F(me[1])+'%</b></div>';return h}"
         "function R(){var h=H('{{tour}}','🏆'),two=D.b&&D.b.length&&D.o&&D.o.length;if(!two)TB=D.b&&D.b.length?0:1;"
         "if(two)h+='<div class=c><button data-a=tb data-v=0'+(TB==0?' class=on':'')+'>Dip Funded</button><button data-a=tb data-v=1'+(TB==1?' class=on':'')+'>{{own}}</button></div>';"
         "if(D.st)h+='<div class=m>'+D.st+'</div>';h+=TB==0?RW(D.b):RW(D.o,D.me);if(!(D.b||[]).length&&!(D.o||[]).length)h+='<div class=m>{{load}}</div>';"
         "if(M)h+='<div class=n>'+M+'</div>';h+='<div class=a><button data-a=app>{{app}} ›</button></div>';w.innerHTML=h}"
         "function A(a,v){if(a=='tb'){TB=+v;R()}else if(a=='app')W.openTelegramLink('{{link}}')}")

# (10) Referal. D: {n, w, e (DIP), per, l (havola), s (ulashish havolasi)}
_REF = ("function RQ(){return 'rf'}function R(){var h=H('{{refs}}','🎁')"
        "+'<div class=r style=\"display:flex;justify-content:space-between;text-align:center\"><span><div class=big>'+F(D.n,0)+'</div><div class=m>{{refs}}</div></span>"
        "<span><div class=\"big g\">+'+F(D.w,0)+'</div><div class=m>{{week}}</div></span><span><div class=big>'+F(D.e,0)+'</div><div class=m>DIP {{earned}}</div></span></div>'"
        "+'<div class=m style=margin-top:8px>+'+F(D.per)+' DIP {{per}}</div>'+(D.l?'<div class=r style=user-select:text;-webkit-user-select:text;font-size:12px>'+D.l+'</div>':'')"
        "+'<div class=a><button data-a=sh class=p>📤 {{share}}</button><button data-a=cp>📋 {{copy}}</button></div>';if(M)h+='<div class=n>'+M+'</div>';w.innerHTML=h}"
        "function A(a){if(a=='sh'&&D.s)W.openTelegramLink(D.s);else if(a=='cp'&&D.l)W.copyText(D.l)}")

# (11) Guruhdagi jonli signal kartasi (hozircha test serverda; `WIDGET_GROUPS=1` bilan yoqiladi).
# So'rov yo'q (guruhda fon so'rovi yo'q) — holatni bot `editMessageWidgetData` bilan yangilaydi.
# D: {y, d, lv, e, sl, tp, px, pn, st:'A'|'P'|'C', q, ee, t}
_SIG = ("function RQ(){return ''}function Q(){}"
        "function R(){var c=D.st=='C',p=D.st=='P',pc=D.pn==null?'':D.pn>=0?'g':'e';"
        "var h=H((D.y||'')+'<span class=\"tg '+D.d+'\">'+(D.d=='L'?'LONG':'SHORT')+(D.lv>1?' '+D.lv+'x':'')+'</span>','TC')"
        "+'<div class=t style=margin:2px 0 6px><span class=m>'+(c?'{{closed}}':p?'{{lim}}':'● {{live}}')+(D.t?' · '+D.t:'')+'</span>"
        "<span class=\"big '+pc+'\">'+(D.pn==null?'—':(D.pn>=0?'+':'')+F(D.pn)+'%')+'</span></div>';"
        "if(D.q!=null)h+='<div class=rg><b style=left:'+D.ee*100+'%></b><i style=left:'+D.q*100+'%></i></div>';"
        "h+='<div class=r style=\"display:flex;justify-content:space-between;text-align:center\"><span><div class=m>{{entry}}</div><b>'+D.e+'</b></span>"
        "<span><div class=m>SL</div><b class=e>'+(D.sl||'—')+'</b></span><span><div class=m>TP</div><b class=g>'+(D.tp||'—')+'</b></span><span><div class=m>{{px}}</div><b>'+(D.px||'—')+'</b></span></div>';"
        "if(!c)h+='<div class=a><button data-a=go class=p>⚡ {{trade}}</button></div>';w.innerHTML=h}"
        "function A(a){if(a=='go')W.openTelegramLink('{{link}}')}")

_BODY = {"pos": _POS, "trade": _TRADE, "df": _DF, "dip": _DIP, "tour": _TOUR, "ref": _REF, "sig": _SIG}


def _js_str(s: str) -> str:
    """Matnni JS '...' satri ichiga xavfsiz qo'yish (HTML ichida ham)."""
    return (s.replace("\\", "\\\\").replace("'", "\\'").replace("<", "\\x3c").replace("\n", " "))


def build_html(kind: str, lang: str | None, link: str = "") -> str:
    L = WT.get(i18n.normalize(lang), WT["uz"])
    src = _BODY[kind]
    js = _JS + src + _TAIL
    for k, v in L.items():
        js = js.replace("{{" + k + "}}", _js_str(v))
    js = js.replace("{{link}}", _js_str(link))
    return f"<style>{_CSS}</style><div id=w></div><script>{js}</script>"


def packed_size(html: str) -> int:
    return len(zlib.compress(html.encode("utf-8"), 9))


# ─────────────────────────── Bot API ───────────────────────────
async def _api(bot, method: str, **kw):
    kw = {k: v for k, v in kw.items() if v is not None}
    return await bot.do_api_request(method, api_kwargs=kw)


async def send(bot, chat_id: int, kind: str, lang, data: dict, caption: str, link: str = ""):
    html = build_html(kind, lang, link)
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode()) > 1024:
        log.warning("Widjet holati 1024 baytdan oshdi (%s, %d) — qisqartiriladi", kind, len(raw.encode()))
        raw = "{}"
    return await _api(bot, "sendWidget", chat_id=chat_id, html=html, chat_data=raw,
                      caption=caption[:1000], allow_queries=True)


def _fit(d: dict, key: str, lim: int = 1000) -> str:
    """Javob/holat ≤ 1024 bayt: ro'yxatni (key) oxiridan qisqartiradi."""
    while True:
        s = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        if len(s.encode()) <= lim or not d.get(key):
            return s
        d[key] = d[key][:-1]


async def answer(bot, qid: str, d: dict | None = None, m: str | None = None, key: str = "L",
                 g: dict | None = None) -> None:
    mm = ',"m":' + json.dumps(m[:200], ensure_ascii=False) if m else ""
    if g is not None:                   # 364-2: grafik — o'zi alohida javob
        data = '{"g":' + json.dumps(g, separators=(",", ":")) + mm + "}"
    elif d is not None:
        data = '{"d":' + _fit(d, key, 1010 - len(mm.encode())) + mm + "}"
    else:
        data = "{" + mm.lstrip(",") + "}"
    try:
        await _api(bot, "answerWidgetQuery", widget_query_id=qid, data=data)
    except Exception as e:
        log.warning("answerWidgetQuery xato: %s", e)


# ─────────────────────────── holatlar ───────────────────────────
def _B():
    """Ishlab turgan bot moduli. Bot `python bot.py` bilan ishga tushadi (`__main__`) —
    `import bot` modulni IKKINCHI marta yuklardi (alohida global holat bilan)."""
    import sys
    m = sys.modules.get("__main__")
    if m is not None and hasattr(m, "act_be"):
        return m
    import bot
    return bot


def _hm() -> str:
    return time.strftime("%H:%M", time.gmtime(time.time() + 5 * 3600))     # Toshkent


def _track(s, price, entry) -> list:
    """364: narx va kirishning SL → keyingi TP oralig'idagi o'rni (0..1) + TP matni."""
    B = _B()
    tps = [float(x) for x in (s["tps"] or [])]
    hit = int(s["tp_hit"] or 0)
    tp = tps[min(hit, len(tps) - 1)] if tps else None
    if s["sl"] is None or tp is None or not price:
        return [None, None, ""]
    sl = float(s["sl"])
    span = (tp - sl) if s["side"] == "LONG" else (sl - tp)
    if span <= 0:
        return [None, None, ""]
    f = (lambda x: max(0.0, min(1.0, ((x - sl) if s["side"] == "LONG" else (sl - x)) / span)))
    return [round(f(float(price)), 3), round(f(entry), 3), B.fmt_price(tp)]


async def pos_data(uid: int) -> dict:
    """(1) Egasining (ilovadagidek) ochiq signallari, jonli P&L bilan."""
    B = _B()
    import tracker
    rows = []
    for w in await db.user_manage_workspaces(uid):
        rows += [(w, s) for s in await db.live_signals(w["id"])]
    rows = rows[-8:]
    L = []
    for w, s in rows:
        lv = int(s["leverage"] or 1)
        price = await B.safe_last_price(s["market"], s["symbol"])
        entry = float(s["entry"])
        pnl = usd = None
        if price and s["status"] == "ACTIVE":
            filled = float(s["filled_pct"] or 0)
            pnl = (float(s["realized_pct"] or 0) + max(0.0, 1 - filled) * tracker.pnl_at(s["side"], entry, price)) * lv
            if s["alloc_amount"]:
                usd = round(pnl / 100 * float(s["alloc_amount"]), 2)
            pnl = round(pnl, 2)
        sym = s["symbol"][:-4] if s["symbol"].endswith("USDT") else s["symbol"]
        L.append([s["id"], sym, "L" if s["side"] == "LONG" else "S", pnl,
                  B.fmt_price(float(price)) if price else "—", B.fmt_price(entry),
                  B.fmt_price(float(s["sl"])) if s["sl"] is not None else "", lv,
                  "A" if s["status"] == "ACTIVE" else "P", usd] + _track(s, price, entry))
    return {"L": L, "t": _hm()}


async def trade_data(uid: int, sid: int):
    sig = await db.get_signal(sid)
    if not sig or sig["market"] not in ("crypto", "futures"):
        return None
    B = _B()
    tps = [float(x) for x in (sig["tps"] or [])]
    hit = int(sig["tp_hit"] or 0)
    tp = tps[min(hit, len(tps) - 1)] if tps and hit < len(tps) else None
    exs = []
    for r in await db.cex_list(uid):
        if r["exchange"] in EXN:
            exs.append([r["exchange"], EXN[r["exchange"]]])
    fut = sig["market"] == "futures" or (sig["leverage"] or 1) > 1 or sig["side"] == "SHORT"
    return sig, {"s": sig["id"], "y": sig["symbol"][:-4] if sig["symbol"].endswith("USDT") else sig["symbol"],
                 "d": "L" if sig["side"] == "LONG" else "S", "e": B.fmt_price(float(sig["entry"])),
                 "sl": B.fmt_price(float(sig["sl"])) if sig["sl"] is not None else "",
                 "tp": B.fmt_price(tp) if tp else "", "lv": int(sig["leverage"] or 0) or None,
                 "f": 1 if fut else 0, "x": exs}


async def df_data(uid: int, acc: int | None, lang) -> dict:
    import dfapp
    ok, raw = await dfapp.accounts(uid, lang)
    if not ok:
        return {"err": (json.loads(raw) or {}).get("code") or "unavailable"}
    A = json.loads(raw)
    accs = A.get("accounts") or []
    if not accs:
        return {"err": "not_linked"}
    ids = [a["id"] for a in accs]
    acc = acc if acc in ids else (A.get("main") if A.get("main") in ids else ids[0])
    ok, raw = await dfapp.account(uid, acc, lang)
    if not ok:
        return {"err": (json.loads(raw) or {}).get("code") or "unavailable"}
    s = json.loads(raw)
    dl, mx, tg, dy = s.get("daily") or {}, s.get("max") or {}, s.get("target") or {}, s.get("days") or {}
    pos = sorted(s.get("positions") or [], key=lambda p: -abs(float(p.get("upnl") or 0)))[:5]
    return {"c": acc, "n": s.get("name") or "", "s": s.get("status_txt") or "", "eq": round(float(s.get("equity") or 0), 2),
            "pn": round(float(s.get("pnl") or 0), 2),
            "dl": [round(float(dl.get("used_pct") or 0), 1), round(float(dl.get("left") or 0), 2)],
            "mx": [round(float(mx.get("used_pct") or 0), 1), round(float(mx.get("left") or 0), 2)],
            "tg": round(float(tg.get("progress")), 1) if tg.get("progress") is not None else None,
            "dy": f"{dy.get('done')}/{dy.get('min')}" if dy.get("min") else None,
            "p": [[p.get("symbol"), round(float(p.get("upnl") or 0), 2), round(float(p.get("upnl_pct") or 0), 2)] for p in pos],
            "a": [[a["id"], ("#%s" % a["id"])] for a in accs][:6], "t": _hm()}


async def dip_data(uid: int, bot_username: str | None) -> dict:
    B = _B()
    bal = float(await db.dip_balance(uid))
    T = []
    for r in await db.dip_tasks_for(uid):
        if r["kind"] == "dw":           # Delta Wear — buyurtma raqami kerak, ilovada
            continue
        T.append([r["id"], (r["title"] or "")[:40], float(r["reward"]), r["url"] or "", 1 if r["done"] else 0])
    T.sort(key=lambda x: x[4])
    code = await db.ensure_ref_code(uid)
    return {"b": round(bal, 2), "u": round(bal / 100, 2), "T": T[:5], "l": B.referral_link(code, bot_username) or ""}


_AB = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _enc(v: float) -> str:
    v = max(0, min(4095, int(round(v))))
    return _AB[v // 64] + _AB[v % 64]


async def chart_data(sig, n: int = 40) -> dict | None:
    """364-2 (1): oxirgi n sham (signal TF'i, yo'q bo'lsa 1h), 0..4095 ga kodlangan; oraliq —
    shamlar + kirish/SL/TP (juda uzoq bo'lsa kesiladi, chiziq chetga yopishadi)."""
    import tracker
    tfm = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    tf = sig["chart_tf"] if sig["chart_tf"] in tfm else "1h"
    now = int(time.time() * 1000)
    try:
        cs = await tracker.provider(sig["market"]).klines(sig["symbol"], now - (n + 5) * tfm[tf] * 1000,
                                                          limit=n + 5, tf=tf, end_ms=now)
    except Exception:
        log.warning("Widjet grafigi: shamlar olinmadi (%s)", sig["symbol"], exc_info=True)
        return None
    rows = [(float(c.open), float(c.high), float(c.low), float(c.close)) for c in cs][-n:]
    if not rows:
        return None
    lo, hi = min(r[2] for r in rows), max(r[1] for r in rows)
    tps = [float(x) for x in (sig["tps"] or [])]
    hit = int(sig["tp_hit"] or 0)
    tp = tps[min(hit, len(tps) - 1)] if tps else None
    sl = float(sig["sl"]) if sig["sl"] is not None else None
    e = float(sig["entry"])
    span = hi - lo or hi * 0.01 or 1
    for v in (e, sl, tp):            # 2.5 oraliqdan uzoq chiziqlar diapazonni buzmasin
        if v and lo - 2.5 * span <= v <= hi + 2.5 * span:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.06 or hi * 0.005
    lo, hi = lo - pad, hi + pad
    k = 4095 / (hi - lo)
    c = "".join(_enc((x - lo) * k) for r in rows for x in r)
    return {"s": sig["id"], "c": c, "lo": float(f"{lo:.8g}"), "hi": float(f"{hi:.8g}"), "e": e, "sl": sl, "tp": tp,
            "px": rows[-1][3]}


async def tour_data(uid: int, lang) -> dict:
    """364-2 (7): Dip Funded turniri (top-10) va ichki turnir (top-10 + o'zingiz)."""
    import dipfunded
    import tournament
    out = {"b": [], "o": [], "me": None, "st": "", "t": _hm()}
    try:
        d = await dipfunded.cached_tour()
        out["b"] = [[int(r.get("rank") or i + 1), str(r.get("name") or "—")[:16], round(float(r.get("pct") or 0), 2)]
                    for i, r in enumerate((d.get("board") or [])[:10])]
    except Exception:
        log.warning("Widjet: Dip Funded turniri o'qilmadi", exc_info=True)
    try:
        t = await tournament.latest()
        if t:
            dep = float(t["deposit"])
            st = await tournament.standings(t["id"])
            for pos, r in enumerate(st, 1):
                eq = float(r["equity"]) if r["equity"] is not None else dep
                row = [int(r["rank"] or pos), tournament.display_name(r)[:16], round((eq / dep - 1) * 100, 2)]
                if r["user_id"] == uid:
                    out["me"] = row[0:1] + row[2:]
                if pos <= 10:
                    out["o"].append(row + ([1] if r["user_id"] == uid else []))
    except Exception:
        log.warning("Widjet: ichki turnir o'qilmadi", exc_info=True)
    return out


async def ref_data(uid: int, bot_username: str | None, lang) -> dict:
    """364-2 (10): takliflar soni, shu hafta, ishlab topilgan DIP, ulashish havolasi."""
    from urllib.parse import quote
    B = _B()
    code = await db.ensure_ref_code(uid)
    link = B.referral_link(code, bot_username) or ""
    async with db.pool().acquire() as c:
        n = await c.fetchval("SELECT COUNT(*) FROM referrals WHERE referrer_id=$1", uid)
        wk = await c.fetchval("SELECT COUNT(*) FROM referrals WHERE referrer_id=$1 AND created_at > now() - interval '7 days'", uid)
        e = await c.fetchval("SELECT COALESCE(SUM(amount),0) FROM dip_ledger WHERE user_id=$1 AND reason='referral'", uid)
    L = WT.get(i18n.normalize(lang), WT["uz"])
    share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(L['inv'], safe='')}" if link else ""
    if len(share) > 256:
        share = f"https://t.me/share/url?url={quote(link, safe='')}"
    return {"n": int(n or 0), "w": int(wk or 0), "e": round(float(e or 0), 2), "per": float(config.DIP_PER_REF),
            "l": link, "s": share}


def sig_card(sig, price) -> dict:
    """364-2 (11): guruhdagi jonli signal kartasi holati."""
    import tracker
    B = _B()
    lv = int(sig["leverage"] or 1)
    e = float(sig["entry"])
    tps = [float(x) for x in (sig["tps"] or [])]
    hit = int(sig["tp_hit"] or 0)
    tp = tps[min(hit, len(tps) - 1)] if tps else None
    st = {"ACTIVE": "A", "PENDING": "P"}.get(sig["status"], "C")
    if st == "C":
        pn = float(sig["pnl_pct"] or 0) * lv
    elif st == "A" and price:
        filled = float(sig["filled_pct"] or 0)
        pn = (float(sig["realized_pct"] or 0) + max(0.0, 1 - filled) * tracker.pnl_at(sig["side"], e, price)) * lv
    else:
        pn = None
    q, ee, _tp = _track(sig, price, e) if st != "C" else (None, None, "")
    return {"y": sig["symbol"][:-4] if sig["symbol"].endswith("USDT") else sig["symbol"],
            "d": "L" if sig["side"] == "LONG" else "S", "lv": lv, "e": B.fmt_price(e),
            "sl": B.fmt_price(float(sig["sl"])) if sig["sl"] is not None else "",
            "tp": B.fmt_price(tp) if tp else "", "px": B.fmt_price(float(price)) if price else "",
            "pn": round(pn, 2) if pn is not None else None, "st": st, "q": q, "ee": ee, "t": _hm()}


def app_link(bot_username: str | None, param: str = "") -> str:
    return f"https://t.me/{bot_username}?startapp{'=' + param if param else ''}" if bot_username else "https://t.me"


# ─────────────────────────── widget_query ───────────────────────────
def internal_token() -> str:
    return hashlib.sha256(("wtrade:" + (config.BOT_TOKEN or "")).encode()).hexdigest()


async def _wtrade(payload: dict) -> dict:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.post(f"{config.WEB_URL}/api/internal/wtrade", json=payload,
                             headers={"X-Internal": internal_token()})
        return r.json()
    except Exception as e:
        log.warning("wtrade so'rovi o'tmadi: %s", type(e).__name__)
        return {"ok": False, "m": None}


async def handle(update, ctx) -> None:
    """`widget_query` — PTB 21 bu maydonni bilmaydi, u `update.api_kwargs`da keladi."""
    q = (update.api_kwargs or {}).get("widget_query") or (update.api_kwargs or {}).get("shared_widget_query")
    if not q:
        return
    B = _B()
    qid, data = q.get("id"), str(q.get("data") or "")
    uid = int((q.get("from") or {}).get("id") or 0)
    lang = await B.user_lang(uid)
    L = WT.get(i18n.normalize(lang), WT["uz"])
    try:
        await _handle(ctx, qid, uid, lang, L, data)
    except Exception:
        log.exception("Widjet so'rovi xato (%s)", data[:40])
        await answer(ctx.bot, qid, m=L["err"])


async def _handle(ctx, qid, uid, lang, L, data) -> None:
    B = _B()
    p = data.split(":")
    op = p[0]
    # (1) pozitsiyalar
    if op in ("r",) and len(p) == 1:
        await answer(ctx.bot, qid, await pos_data(uid))
        return
    if op in ("be", "pc", "cl") and len(p) >= 2 and p[1].isdigit():
        sig = await db.get_signal(int(p[1]))
        ws = await db.get_workspace(sig["workspace_id"]) if sig else None
        if not sig or sig["status"] not in ("PENDING", "ACTIVE"):
            await answer(ctx.bot, qid, await pos_data(uid), i18n.t("man.gone", lang))
            return
        if not ws or not await B.can_manage_signal(ctx.bot, uid, ws, sig):
            await answer(ctx.bot, qid, None, i18n.t("man.no_right", lang))
            return
        if op == "be":
            err = await B.act_be(ctx, ws, sig, lang)
            msg = err or i18n.t("app.be_ok", lang)
        elif op == "pc":
            _ok, msg, _c = await B.act_partial(ctx, ws, sig, 50, uid)
        else:
            _ok, msg = await B.act_close(ctx, ws, sig, uid, lang)
        await answer(ctx.bot, qid, await pos_data(uid), B.re.sub(r"<[^>]+>", "", msg or "OK"))
        return
    # (2) tezkor savdo: i:SID:EX:MKT | o:SID:EX:MKT:PCT
    if op in ("i", "o") and len(p) >= 4 and p[1].isdigit():
        r = await _wtrade({"uid": uid, "sid": int(p[1]), "ex": p[2], "m": p[3], "op": op,
                           "pct": int(p[4]) if op == "o" and len(p) > 4 and p[4].isdigit() else 0, "lang": lang})
        got = await trade_data(uid, int(p[1]))
        d = got[1] if got else {}
        if r.get("ok") and op == "i":
            d["i"] = {"av": r.get("av"), "px": r.get("px")}
        elif r.get("ok"):
            d["i"] = {"av": r.get("av"), "px": r.get("px")}
        await answer(ctx.bot, qid, d, r.get("m") or (None if r.get("ok") else L["err"]), key="x")
        return
    if op == "n":
        await answer(ctx.bot, qid, None, L["nokey"])
        return
    # (4) Dip Funded
    if op == "r" and len(p) == 2:
        d = await df_data(uid, int(p[1]) if p[1].isdigit() and p[1] != "0" else None, lang)
        if d.get("err"):
            await answer(ctx.bot, qid, None, i18n.t("df.app_open", lang) if d["err"] == "not_linked" else L["err"])
        else:
            await answer(ctx.bot, qid, d, key="p")
        return
    # (5) DIP
    if op == "dr":
        await answer(ctx.bot, qid, await dip_data(uid, ctx.bot.username), key="T")
        return
    if op == "ck" and len(p) == 2 and p[1].isdigit():
        ok, msg = await B._app_diptask(ctx, uid, lang, {"args": json.dumps({"id": int(p[1])})})
        await answer(ctx.bot, qid, await dip_data(uid, ctx.bot.username), B.re.sub(r"<[^>]+>", "", msg or ""), key="T")
        return
    # 364-2: grafik va SL/TP surish
    if op in ("ch", "sl", "tp") and len(p) >= 2 and p[1].isdigit():
        sig = await db.get_signal(int(p[1]))
        ws = await db.get_workspace(sig["workspace_id"]) if sig else None
        if not sig or not ws or not await B.can_manage_signal(ctx.bot, uid, ws, sig):
            await answer(ctx.bot, qid, None, i18n.t("man.no_right", lang))
            return
        if op == "ch":
            g = await chart_data(sig)
            await answer(ctx.bot, qid, g=g) if g else await answer(ctx.bot, qid, None, L["err"])
            return
        try:
            price = float(p[2])
            assert price > 0
        except Exception:
            await answer(ctx.bot, qid, None, i18n.t("man.bad_number", lang))
            return
        if sig["status"] not in ("PENDING", "ACTIVE"):
            await answer(ctx.bot, qid, await pos_data(uid), i18n.t("man.gone", lang))
            return
        if op == "sl":
            if sig["sl"] is None:
                await answer(ctx.bot, qid, None, i18n.t("man.bad_number", lang))
                return
            err = await B.act_sl(ctx, ws, sig, price, lang)
            msg = err or i18n.t("man.stop_set", lang, p=B.fmt_price(price))
        else:
            tps = [float(x) for x in (sig["tps"] or [])]
            hit = int(sig["tp_hit"] or 0)
            if hit < len(tps):
                tps[hit] = price
            else:
                tps.append(price)
            err, shown = await B.act_tps(ctx, ws, sig, tps, lang)
            msg = err or i18n.t("man.tps_set", lang, tps=shown)
        await answer(ctx.bot, qid, await pos_data(uid), B.re.sub(r"<[^>]+>", "", msg or "OK"))
        return
    # 364-2: turnir va referal
    if op == "tr":
        await answer(ctx.bot, qid, await tour_data(uid, lang), key="o")
        return
    if op == "rf":
        await answer(ctx.bot, qid, await ref_data(uid, ctx.bot.username, lang), key="l")
        return
    await answer(ctx.bot, qid, None, L["err"])


# ─────────────────────────── yuborish (bot buyruqlari) ───────────────────────────
CAP = {
    "pos": {"uz": "📊 Ochiq pozitsiyalar — jonli", "ru": "📊 Открытые позиции — онлайн", "en": "📊 Open positions — live"},
    "df": {"uz": "Dip Funded hisobi — jonli", "ru": "Счёт Dip Funded — онлайн", "en": "Dip Funded account — live"},
    "dip": {"uz": "💎 DIP balans va vazifalar", "ru": "💎 Баланс DIP и задания", "en": "💎 DIP balance and tasks"},
    "tour": {"uz": "🏆 Turnir reytingi — jonli", "ru": "🏆 Рейтинг турнира — онлайн", "en": "🏆 Tournament standings — live"},
    "ref": {"uz": "🎁 Takliflaringiz", "ru": "🎁 Ваши приглашения", "en": "🎁 Your invites"},
}


async def send_pos(bot, uid: int, lang) -> None:
    await send(bot, uid, "pos", lang, await pos_data(uid), CAP["pos"][i18n.normalize(lang)],
               app_link(bot.username))


async def send_df(bot, uid: int, lang) -> None:
    d = await df_data(uid, None, lang)
    if d.get("err"):
        d = {}
    await send(bot, uid, "df", lang, d, CAP["df"][i18n.normalize(lang)], app_link(bot.username))


async def send_dip(bot, uid: int, lang) -> None:
    await send(bot, uid, "dip", lang, await dip_data(uid, bot.username), CAP["dip"][i18n.normalize(lang)])


async def send_tour(bot, uid: int, lang) -> None:
    await send(bot, uid, "tour", lang, await tour_data(uid, lang), CAP["tour"][i18n.normalize(lang)],
               app_link(bot.username, "tour"))


async def send_ref(bot, uid: int, lang) -> None:
    await send(bot, uid, "ref", lang, await ref_data(uid, bot.username, lang), CAP["ref"][i18n.normalize(lang)])


# ── 364-2 (11): guruhdagi jonli signal kartasi ──
# Telegram hozircha widjetni guruhga faqat TEST serverda qabul qiladi. 365: o'zini o'zi tekshiradi —
# yangi signalda yuborib ko'radi; Telegram rad etsa, 12 soat urinmaydi (`gw_retry_at`), keyin yana.
# Birinchi muvaffaqiyatda adminlarga xabar (`gw_live`). `WIDGET_GROUPS=0` — butunlay o'chirish.
# Kanalga widjet yuborib bo'lmaydi.
GROUPS = __import__("os").getenv("WIDGET_GROUPS", "") != "0"
GW_RETRY = 12 * 3600
_GW_LAST: dict[int, str] = {}
# Guruhning o'ziga tegishli xatolar (bot chiqarilgan, huquq yo'q) — "Telegram hali ruxsat bermagan" emas
_GW_LOCAL = ("not enough rights", "chat not found", "kicked", "not a member", "have no rights",
             "chat_write_forbidden", "topic", "thread")


async def _gw_open() -> bool:
    try:
        v = await db.get_setting("gw_retry_at")
        return not v or time.time() >= float(v)
    except Exception:
        return True


async def _gw_result(bot, ok: bool, err: str = "") -> None:
    if ok:
        if not await db.get_setting("gw_live"):
            await db.set_setting("gw_live", str(int(time.time())))
            log.info("Guruh widjetlari ISHLAY BOSHLADI — Telegram ruxsat berdi")
            for a in config.ADMIN_IDS:
                try:
                    await bot.send_message(a, "🧩 Guruhdagi jonli signal kartalari ishlay boshladi — Telegram widjetlarni "
                                              "guruhlarda ruxsat berdi. Endi har yangi signal postiga jonli karta qo'shiladi.")
                except Exception:
                    pass
        await db.set_setting("gw_retry_at", None)
        return
    low = err.lower()
    if any(x in low for x in _GW_LOCAL):
        return
    await db.set_setting("gw_retry_at", str(time.time() + GW_RETRY))
    if await db.get_setting("gw_live"):
        await db.set_setting("gw_live", None)
    log.info("Guruh widjeti hali qabul qilinmaydi (%s) — %d soatdan keyin yana urinadi", err[:120], GW_RETRY // 3600)


async def send_group_sig(bot, ws, sig, lang) -> None:
    if not GROUPS or ws["type"] != "group" or ws["is_channel"] or not ws["group_chat_id"]:
        return
    if not await _gw_open():
        return
    B = _B()
    price = await B.safe_last_price(sig["market"], sig["symbol"])
    d = sig_card(sig, price)
    html = build_html("sig", lang, f"https://t.me/{bot.username}?start=tw_{sig['id']}")
    raw = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    cap = f"#{sig['id']} {sig['symbol']} {sig['side']}"
    try:
        r = await _api(bot, "sendWidget", chat_id=ws["group_chat_id"], html=html, chat_data=raw, caption=cap,
                       message_thread_id=ws["group_topic_id"], reply_to_message_id=sig["group_msg_id"],
                       allow_sending_without_reply=True)
        mid = (r or {}).get("message_id") if isinstance(r, dict) else getattr(r, "message_id", None)
        if mid:
            await db.set_setting(f"gw:{sig['id']}", f"{ws['group_chat_id']}:{mid}")
            _GW_LAST[sig["id"]] = raw
            await _gw_result(bot, True)
    except Exception as e:
        await _gw_result(bot, False, str(e))


async def group_sig_job(ctx) -> None:
    """Har daqiqa: guruh widjetlari holatini yangilash (o'zgargan bo'lsa); yopilgan signal — oxirgi
    marta yangilanib, ro'yxatdan chiqariladi. editMessageWidgetData = 1 xabar (limit) — faqat o'zgarganda."""
    if not GROUPS:
        return
    B = _B()
    for sid in (await db.setting_users("gw:"))[:40]:
        try:
            raw = await db.get_setting(f"gw:{sid}")
            sig = await db.get_signal(sid)
            if not raw or not sig:
                await db.set_setting(f"gw:{sid}", None)
                continue
            chat, mid = raw.split(":")
            price = await B.safe_last_price(sig["market"], sig["symbol"]) if sig["status"] == "ACTIVE" else None
            data = json.dumps(sig_card(sig, price), ensure_ascii=False, separators=(",", ":"))
            cmp = json.loads(data)
            cmp.pop("t", None)
            key = json.dumps(cmp, sort_keys=True)
            if _GW_LAST.get(sid) != key:
                await _api(ctx.bot, "editMessageWidgetData", chat_id=int(chat), message_id=int(mid), chat_data=data)
                _GW_LAST[sid] = key
            if sig["status"] not in ("PENDING", "ACTIVE"):
                await db.set_setting(f"gw:{sid}", None)
                _GW_LAST.pop(sid, None)
        except Exception as e:
            if "not modified" not in str(e):
                log.warning("Guruh widjeti yangilanmadi (#%s): %s", sid, e)


async def send_trade(bot, uid: int, sid: int, lang) -> bool:
    got = await trade_data(uid, sid)
    if not got:
        return False
    sig, d = got
    L = WT.get(i18n.normalize(lang), WT["uz"])
    cap = f"⚡ {sig['symbol']} {sig['side']} — {L['trade']}"
    await send(bot, uid, "trade", lang, d, cap, app_link(bot.username, f"sg_{sid}"))
    return True
