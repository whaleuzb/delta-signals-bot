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
import os

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
        "save": "Saqlash", "spot_dep": "Spot depozit", "fut_dep": "Futures depozit",
        "best": "Eng yaxshi pozitsiya", "busy": "Band summa",
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
        "save": "Сохранить", "spot_dep": "Спот депозит", "fut_dep": "Фьючерс депозит",
        "best": "Лучшая позиция", "busy": "В позициях",
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
        "save": "Save", "spot_dep": "Spot deposit", "fut_dep": "Futures deposit",
        "best": "Best position", "busy": "In positions",
    },
}


# 240: sahifa alohida faylda (webapp.html) — JS'ni Python satri ichida
# ekranlash shart bo'lmasin. __T__ — tarjimalar.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp.html"),
          encoding="utf-8") as _fh:
    PAGE = _fh.read().replace("__T__", json.dumps(T, ensure_ascii=False))
