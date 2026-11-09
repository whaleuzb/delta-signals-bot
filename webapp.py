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
ACTIONS = ("be", "sl", "pc", "close", "tps", "entry", "tpsl", "add", "lim", "limx", "size", "tf", "limmv")
WS_ACTIONS = ("dep", "fdep", "df", "dfacc", "dfone", "newsig", "ref", "refcode", "refshare", "dipout", "diplook", "diptask", "dipapply")       # 254: signalga emas, workspace/odamga


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
    import dipfunded
    return web.json_response({"uid": uid, "lang": lang, "ws": out,
                              "bot": request.app["bot_username"],
                              # 256: veb servisda Dip Funded kaliti yo'q (enabled() False) —
                              # havolalar faqat sayt manziliga bog'liq, hisoblarni bot beradi.
                              "df": dipfunded.site_url("/") if config.DIPFUNDED_URL else None,
                              "df_buy": dipfunded.site_url("/account/buy") if config.DIPFUNDED_URL else None,
                              "df_link": dipfunded.site_url("/account/telegram/link") if config.DIPFUNDED_URL else None},
                             headers=NO_CACHE)


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
        live = unreal = None
        if price and r["status"] == "ACTIVE":
            unreal = max(0.0, 1 - filled) * tracker.pnl_at(r["side"], entry, price) * L
            live = realized * L + unreal
        alloc = _f(r["alloc_amount"])
        adds = await db.signal_adds(r["id"], "PENDING")
        dep_k = ws["fut_deposit"] if (r["leverage"] or 1) > 1 else ws["deposit"]
        out.append({
            "adds": [float(a["price"]) for a in adds],
            "usd": alloc is not None, "can_size": alloc is None and dep_k is not None,
            "id": r["id"], "symbol": r["symbol"], "side": r["side"], "lev": L,
            "status": r["status"], "market": r["market"], "tf": r["chart_tf"],
            "entry": entry, "sl": _f(r["sl"]),
            "tps": [float(t) for t in (r["tps"] or [])], "tp_hit": r["tp_hit"] or 0,
            "price": price, "live": live, "alloc": alloc,
            "money": (live / 100 * alloc) if (live is not None and alloc) else None,
            "filled": filled,
            # 297: birjadagidek — ochiq qism (unrealized) va qisman yopilgan qism (realized), % (leverajli)
            "unreal": unreal, "real": realized * L if r["status"] == "ACTIVE" else 0.0,
            "opened": r["opened_at"].isoformat() if r["opened_at"] else None,
        })
    return web.json_response({"ws": ws["id"], "items": out}, headers=NO_CACHE)


# 241: kartadagi kichik grafik. Shamlar (market, juftlik, tf) bo'yicha
# keshlanadi — kripto 2 daqiqa, forex/aksiya 10 daqiqa (Twelve Data limiti).
_SPARK: dict[tuple, tuple[float, list]] = {}
_SPARK_SEM = asyncio.Semaphore(3)
_TFS = (("5m", 300_000), ("15m", 900_000), ("1h", 3_600_000),
        ("4h", 14_400_000), ("1d", 86_400_000))
# 281: signalga taymfreym tanlangan bo'lsa (`chart_tf`) — kichik grafik shu taymda.
_TF_MS = {"1m": 60_000, **dict(_TFS)}


def _spark_tf(start_ms: int, now_ms: int) -> tuple[str, int]:
    span = max(now_ms - start_ms, 3 * 3_600_000) * 1.25
    for tf, ms in _TFS:
        if span / ms <= 110:
            return tf, int(now_ms - span)
    return "1d", int(now_ms - 110 * 86_400_000)


async def _spark(r) -> list | None:
    import time as _t
    now = int(_t.time() * 1000)
    t0 = r["opened_at"] or r["created_at"]
    tf = r.get("chart_tf") if hasattr(r, "get") else None
    if tf in _TF_MS:
        begin = now - 110 * _TF_MS[tf]
    else:
        tf, begin = _spark_tf(int(t0.timestamp() * 1000), now)
    key = (r["market"], r["symbol"], tf)
    ttl = 120 if r["market"] in ("crypto", "futures", None) else 600
    hit = _SPARK.get(key)
    if hit and _t.monotonic() - hit[0] < ttl:
        return hit[1]
    async with _SPARK_SEM:
        hit = _SPARK.get(key)
        if hit and _t.monotonic() - hit[0] < ttl:
            return hit[1]
        try:
            cs = await tracker.provider(r["market"]).klines(
                r["symbol"], begin, limit=200, tf=tf, end_ms=now)
            data = [round(float(c.close), 10) for c in cs][-120:]
            mark = None
            if r["opened_at"]:
                om = int(r["opened_at"].timestamp() * 1000)
                for k, c in enumerate(cs[-120:]):
                    if c.open_ms >= om:
                        mark = k
                        break
            out = [data, mark]
        except Exception:
            log.warning("Kichik grafik shamlari olinmadi (%s)", r["symbol"], exc_info=True)
            out = None
        if out is not None:
            if len(_SPARK) > 500:
                _SPARK.clear()
            _SPARK[key] = (_t.monotonic(), out)
        return out


_CANDLES: dict = {}


async def api_candles(request):
    """289: signal terminali — shamlar (egasi/boshqaruvchisi). 30 soniya kesh."""
    import time as _t
    body, uid = await _body(request)
    try:
        sig = await db.get_signal(int(body.get("sig")))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    ws = await db.get_workspace(sig["workspace_id"]) if sig else None
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    tf = body.get("tf") if body.get("tf") in _TF_MS else (sig["chart_tf"] if sig["chart_tf"] in _TF_MS else "1h")
    key = (sig["market"], sig["symbol"], tf)
    hit = _CANDLES.get(key)
    if hit and _t.monotonic() - hit[0] < 30:
        rows = hit[1]
    else:
        now = int(_t.time() * 1000)
        try:
            cs = await tracker.provider(sig["market"]).klines(
                sig["symbol"], now - 160 * _TF_MS[tf], limit=200, tf=tf, end_ms=now)
        except Exception:
            log.warning("Terminal shamlari olinmadi (%s %s)", sig["symbol"], tf, exc_info=True)
            cs = []
        rows = [[c.open_ms, float(c.open), float(c.high), float(c.low), float(c.close)] for c in cs][-160:]
        if rows:
            if len(_CANDLES) > 300:
                _CANDLES.clear()
            _CANDLES[key] = (_t.monotonic(), rows)
    adds = await db.signal_adds(sig["id"], "PENDING")
    return web.json_response({"tf": tf, "c": rows,
                              "adds": [float(a["price"]) for a in adds if a["kind"] == "LIMIT"]},
                             headers=NO_CACHE)


async def api_spark(request):
    body, uid = await _body(request)
    try:
        ws = await db.get_workspace(int(body.get("ws")))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    rows = await db.live_signals(ws["id"])
    res = await asyncio.gather(*(_spark(r) for r in rows))
    return web.json_response(
        {str(r["id"]): {"c": v[0], "m": v[1]} for r, v in zip(rows, res) if v and v[0]},
        headers=NO_CACHE)


async def _wait_action(aid: int):
    for _ in range(50):
        await asyncio.sleep(0.5)
        a = await db.app_action_get(aid)
        if a and a["status"] in ("ok", "fail", "stale"):
            return web.json_response({"ok": a["status"] == "ok",
                                      "msg": a["result"] or ""}, headers=NO_CACHE)
    return web.json_response({"ok": False, "pending": True, "msg": ""}, headers=NO_CACHE)


async def _ws_act(body, uid: int, act: str):
    """254: depozit o'rnatish (spot/futures) va Dip Funded menyusini botda
    ochish — bot bajaradi (`app_action_job`), sig_id=0."""
    arg = None
    if act == "newsig":
        # 258: yangi signal — forma maydonlari JSON'da; huquqni bot tekshiradi
        # (`can_submit_signal`), bu yerda faqat workspace egaligi.
        f = body.get("args")
        try:
            ws = await db.get_workspace(int((f or {}).get("ws")))
        except (TypeError, ValueError, AttributeError):
            raise web.HTTPBadRequest()
        if not _can(ws, uid):
            raise web.HTTPForbidden()
        aid = await db.app_action_add(uid, 0, act, None, json.dumps(f)[:2000])
        return await _wait_action(aid)
    if act in ("diptask", "dipapply"):
        # 282: Earn — vazifani tekshirish / joylashtirish arizasi (bot bajaradi).
        f = body.get("args") if isinstance(body.get("args"), dict) else {}
        args = json.dumps({"id": int(f.get("id") or 0)} if act == "diptask" else
                          {"kind": str(f.get("kind") or "")[:10], "target": str(f.get("target") or "")[:120],
                           "note": str(f.get("note") or "")[:300]})
        aid = await db.app_action_add(uid, 0, act, None, args)
        return await _wait_action(aid)
    if act in ("ref", "refcode", "refshare", "dipout", "diplook"):
        f = body.get("args") if isinstance(body.get("args"), dict) else {}
        args = json.dumps({"code": str(f.get("code") or "")[:20]}) if act == "refcode" else \
            json.dumps({"dest": str(f.get("dest") or "")[:8], "net": str(f.get("net") or "")[:8],
                        "addr": str(f.get("addr") or "")[:80]}) if act == "dipout" else \
            json.dumps({"to": str(f.get("to") or "")[:40]}) if act == "diplook" else None
        aid = await db.app_action_add(uid, 0, act, None, args)
        return await _wait_action(aid)
    if act == "dfone":
        try:
            arg = float(int(body.get("arg")))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest()
    if act not in ("df", "dfacc", "dfone"):
        try:
            ws = await db.get_workspace(int(body.get("ws")))
            arg = float(body.get("arg"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest()
        if not _can(ws, uid) or not (arg > 0):
            raise web.HTTPForbidden()
        args = json.dumps({"ws": ws["id"]})
    else:
        args = None
    aid = await db.app_action_add(uid, 0, act, arg, args)
    return await _wait_action(aid)


async def api_period(request):
    """254: davr bo'yicha statistika (bot "📊 Statistika"dagi kabi) — faqat egasi."""
    from datetime import datetime, timedelta
    import stats as _st
    body, uid = await _body(request)
    try:
        ws = await db.get_workspace(int(body.get("id")))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    kind = "fut" if body.get("kind") == "fut" else "spot"
    p = str(body.get("p") or "all")
    now = datetime.now(_st.TZ)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = {"d": day0, "w": day0 - timedelta(days=day0.weekday()),
             "m": day0.replace(day=1), "y": day0.replace(month=1, day=1)}.get(p)
    with db.stats_kind(kind):
        r = await db.period_stats(ws["id"], since)
        syms = await db.top_symbols(ws["id"], since, None, limit=50)
    total = r["total"] or 0
    return web.json_response({
        "n": total, "wins": r["wins"] or 0, "losses": r["losses"] or 0, "be": r["be"] or 0,
        "sum": float(r["sum_pct"] or 0), "avg_win": float(r["avg_win"] or 0),
        "avg_loss": float(r["avg_loss"] or 0), "avg_r": float(r["avg_r"] or 0),
        "liqs": r["liqs"] or 0,
        "money": float(r["real_pnl_money"]) if r["real_pnl_money"] is not None else None,
        "wr": (r["wins"] / total * 100) if total else 0,
        "syms": [{"s": x["symbol"], "n": x["closed"], "w": x["wins"], "sum": float(x["sum_pct"])}
                 for x in syms],
    }, headers=NO_CACHE)


async def api_act(request):
    body, uid = await _body(request)
    act = str(body.get("action") or "")
    if act in WS_ACTIONS:
        return await _ws_act(body, uid, act)
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
    args = body.get("args")
    if args is not None:
        if not isinstance(args, (list, dict)):
            raise web.HTTPBadRequest()
        args = json.dumps(args)[:2000]
    aid = await db.app_action_add(uid, sid, act, arg, args)
    # Bot navbatni ~2 soniyada oladi; natijani 25 soniyagacha kutamiz.
    for _ in range(50):
        await asyncio.sleep(0.5)
        a = await db.app_action_get(aid)
        if a and a["status"] in ("ok", "fail", "stale"):
            return web.json_response({"ok": a["status"] == "ok",
                                      "msg": a["result"] or ""}, headers=NO_CACHE)
    return web.json_response({"ok": False, "pending": True, "msg": ""}, headers=NO_CACHE)


# ─────────────── 244: ochiq sahifa, reyting va turnir — Mini App ichida ───────────────
# Hisob-kitob web.py'dagi funksiyalardan (sahifa va JSON bir xil son bersin).
W = None            # web moduli (build_app o'rnatadi)


def _iso(d):
    return d.isoformat() if d else None


async def _uid_opt(request) -> tuple[dict, int | None]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body, _verify(str(body.get("initData") or ""))


async def api_top(request):
    body, _uid = await _uid_opt(request)

    def item(r, fut=False):
        total = r["total"] or 0
        return {"id": r["id"], "name": r["name"], "channel": bool(r["is_channel"]),
                "username": r["username"], "logo": bool(r["has_logo"]),
                "net": round(float(r["sum_pct"]) if fut else W.net_result(r), 2),
                "total": total, "wr": round((r["wins"] / total * 100) if total else 0, 1),
                "last": _iso(r["last_closed"]), "open": r["n_open"] or 0,
                "lev": int(r["avg_lev"]) if fut and r.get("avg_lev") else None}
    rows = await db.public_workspaces()
    try:
        futs = list(await db.public_futures_workspaces())
    except Exception:
        log.exception("Mini App: futures reytingi o'qilmadi")
        futs = []
    key = lambda x: -x["net"]
    return web.json_response({
        "groups": sorted((item(r) for r in rows if not r["is_channel"]), key=key),
        "channels": sorted((item(r) for r in rows if r["is_channel"]), key=key),
        "futures": sorted((item(r, True) for r in futs), key=key),
    }, headers=NO_CACHE)


async def api_diptasks(request):
    """282: DIP Earn — faol vazifalar (bajarilganlari belgilangan) va joylashtirish
    arizasi uchun auditoriya ma'lumoti."""
    _body, uid = await _uid_opt(request)
    rows = await db.dip_tasks_for(uid)
    aud = await db.audience_stats()
    return web.json_response({
        "tasks": [{"id": r["id"], "kind": r["kind"], "title": r["title"], "url": r["url"],
                   "note": r["note"], "logo": r["has_logo"],
                   "reward": float(r["reward"]), "verified": r["verified"], "done": r["done"], "n": r["n"]}
                  for r in rows],
        "aud": aud, "price": config.DIP_PLACE_PRICE, "days": config.DIP_PLACE_DAYS}, headers=NO_CACHE)


async def api_diptop(request):
    """268: DIP reytingi (ochiq) — ism faqat birinchi so'z, username ko'rsatilmaydi."""
    _body, uid = await _uid_opt(request)
    rows = await db.dip_top(50, uid)

    def nm(r):
        n = (r["first_name"] or "").strip().split()
        return (n[0][:18] if n else None) or "Trader"
    out = [{"rank": r["rank"], "name": nm(r), "dip": round(float(r["earned"]), 2), "refs": r["refs"],
            "av": r["av"], "me": bool(uid) and r["user_id"] == uid} for r in rows]
    top = [x for x in out if x["rank"] <= 50]
    mine = next((x for x in out if x["me"]), None)
    return web.json_response({"top": top, "me": mine}, headers=NO_CACHE)


def _curve(rows, deposit, net) -> list:
    pts, acc = [], 0.0
    weighted = bool(deposit) and any(r["alloc_amount"] is not None for r in rows)
    for r in rows:
        if r["pnl_pct"] is None:
            continue
        v = float(r["pnl_pct"])
        if weighted:
            if r["alloc_amount"] is None:
                continue
            v = v * float(r["alloc_amount"]) / float(deposit)
        acc += v
        pts.append(acc)
    if pts and abs(pts[-1]) > 1e-9:
        k = net / pts[-1]
        pts = [x * k for x in pts]
    return [round(x, 2) for x in pts][-300:]


async def api_hstat(request):
    """279: Bosh sahifa kartalari uchun kichik grafiklar — spot/futures natija
    egri chizig'i, oxirgi natijalar va win-rate (faqat egasi)."""
    body, uid = await _body(request)
    try:
        ws = await db.get_workspace(int(body.get("id")))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    out = {}
    for kind in ("spot", "fut"):
        with db.stats_kind(kind):
            eq = await db.equity_series(ws["id"])
        vals = [float(r["pnl_pct"]) for r in eq if r["pnl_pct"] is not None]
        if not vals:
            continue
        dep = ws["fut_deposit"] if kind == "fut" else ws["deposit"]
        net = sum(vals)
        wins = sum(1 for v in vals if v > 0)
        out[kind] = {"curve": _curve(eq, dep, net)[-60:], "last": [round(v, 2) for v in vals[-14:]],
                     "n": len(vals), "wr": round(wins / len(vals) * 100, 1)}
    return web.json_response(out, headers=NO_CACHE)


async def api_group(request):
    body, uid = await _uid_opt(request)
    try:
        wid = int(body.get("id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    ws = await db.public_workspace(wid)
    owner = False
    if not ws and uid is not None:
        w2 = await db.get_workspace(wid)
        if _can(w2, uid):
            ws, owner = w2, True
    if not ws:
        raise web.HTTPNotFound()
    lang = i18n.normalize(body.get("lang"))
    out = {"id": ws["id"], "name": ws["name"], "channel": bool(ws["is_channel"]),
           "logo": bool(ws["logo"]), "public": not owner,
           "join": __import__("paymembers").join_url(ws) or None,
           "mine": uid is not None and _can(ws, uid), "personal": ws["type"] == "personal"}
    for kind in ("spot", "fut"):
        n = await W._group_numbers(ws, lang, kind)
        if kind == "fut" and not n["total"]:
            continue
        with db.stats_kind(kind):
            eq = await db.equity_series(ws["id"])
            months = await db.monthly_breakdown(ws["id"], limit=12)
        dep = ws["fut_deposit"] if kind == "fut" else ws["deposit"]
        liqs = next((v for k, v, c in n["tiles"][4:]), None)
        with db.stats_kind(kind):
            syms = await db.top_symbols(ws["id"], limit=50)
        out[kind] = {
            # 283: juftliklar ochiq sahifada ko'rsatilmaydi — faqat egasiga.
            "syms": [{"s": x["symbol"], "n": x["closed"], "w": x["wins"], "sum": float(x["sum_pct"])}
                     for x in syms] if out["mine"] else [],
            "n": n["total"], "wr": round(n["winrate"], 1), "avg_r": round(n["avg_r"], 2),
            "liqs": liqs,
            "net": round(n["net"], 2),
            "curve": _curve(eq, dep, n["net"]),
            "months": [{"y": r["month"].year, "m": r["month"].month, "n": r["total"],
                        "wr": round(r["wins"] / r["total"] * 100) if r["total"] else 0,
                        "sum": float(r["sum_pct"])} for r in months],
        }
    # Ochiq pozitsiyalar: kanalda — juftlik bilan; yopiq guruhda faqat
    # egasi/a'zo (213) ko'radi, boshqalarga "Pozitsiya N".
    reveal = bool(ws["is_channel"]) or owner or (
        uid is not None and ws["group_chat_id"] and await W.is_member(ws, uid))
    live = [r for r in await db.live_signals(ws["id"]) if r["status"] == "ACTIVE"]
    prices = await asyncio.gather(*(_price(r) for r in live))
    opens = []
    for k, (r, p) in enumerate(zip(live, prices), 1):
        L = r["leverage"] or 1
        pnl = tracker.pnl_at(r["side"], float(r["entry"]), p) * L if p else None
        opens.append({"n": k, "symbol": r["symbol"] if reveal else None,
                      "side": r["side"] if reveal else None, "lev": L,
                      "entry": float(r["entry"]) if reveal else None, "pnl": pnl,
                      "since": _iso(r["opened_at"]),
                      "url": W.post_url(ws, r["group_msg_id"],
                                        members_only=not ws["is_channel"])})
    out["opens"] = opens
    out["reveal"] = reveal
    trades = []
    for r in (await db.closed_for_months(ws["id"]))[:400]:
        L = r["leverage"] or 1
        trades.append({"id": r["id"], "symbol": r["symbol"], "side": r["side"], "lev": L,
                       "entry": float(r["entry"]),
                       "exit": float(r["exit_price"]) if r["exit_price"] is not None else None,
                       "pnl": float(r["pnl_pct"]) * L if r["pnl_pct"] is not None else 0.0,
                       "closed": _iso(r["closed_at"]),
                       "url": W.post_url(ws, r["result_msg_id"] or r["group_msg_id"])})
    out["trades"] = trades
    return web.json_response(out, headers=NO_CACHE)


_TSPARK: dict[int, list] = {}


async def _tspark(sig) -> list | None:
    """Yopilgan savdo grafigi (o'zgarmaydi — doimiy kesh)."""
    if sig["id"] in _TSPARK:
        return _TSPARK[sig["id"]]
    t0 = sig["opened_at"] or sig["created_at"]
    t1 = sig["closed_at"]
    if not t0 or not t1:
        return None
    a, b = int(t0.timestamp() * 1000), int(t1.timestamp() * 1000)
    span = max(b - a, 3_600_000)
    a, b = a - span // 5, b + span // 10
    tf = next((tf for tf, ms in _TFS if (b - a) / ms <= 80), "1d")
    async with _SPARK_SEM:
        try:
            cs = await tracker.provider(sig["market"]).klines(sig["symbol"], a, limit=120, tf=tf, end_ms=b)
        except Exception:
            return None
    data = [round(float(c.close), 10) for c in cs]
    if len(_TSPARK) > 3000:
        _TSPARK.clear()
    if len(data) >= 2:
        _TSPARK[sig["id"]] = data
    return data


async def api_tspark(request):
    body, uid = await _uid_opt(request)
    ids = [int(x) for x in (body.get("ids") or [])[:30] if str(x).isdigit()]
    ok_ws: dict[int, bool] = {}
    out = {}

    async def one(i):
        sig = await db.get_signal(i)
        if not sig or sig["status"] not in ("TP", "SL", "BREAKEVEN"):
            return
        w = sig["workspace_id"]
        if w not in ok_ws:
            ws = await db.public_workspace(w)
            ok_ws[w] = bool(ws) or (uid is not None and _can(await db.get_workspace(w), uid))
        if not ok_ws[w]:
            return
        d = await _tspark(sig)
        if d:
            out[str(i)] = {"c": d, "e": float(sig["entry"]),
                           "x": float(sig["exit_price"]) if sig["exit_price"] is not None else None}
    for i in ids:                      # ketma-ket: ok_ws keshi ishlasin
        await one(i)
    return web.json_response(out, headers=NO_CACHE)


async def api_tour(request):
    import dipfunded
    import tournament
    d = await dipfunded.cached_tour()
    df = {"state": d["state"], "starts": _iso(d["starts"]), "ends": _iso(d["ends"]),
          "prizes": [int(x) for x in (d.get("prizes") or dipfunded.TOUR_PRIZES)],
          "count": int(d.get("count") or 0), "url": dipfunded.tour_url(),
          "board": [{"rank": r.get("rank"), "name": r.get("name"), "pct": float(r.get("pct") or 0),
                     "out": bool(r.get("out"))} for r in (d.get("board") or [])[:50]]}
    own = None
    try:
        t = await tournament.latest()
    except Exception:
        log.exception("Mini App: turnir o'qilmadi")
        t = None
    if t:
        dep = float(t["deposit"])
        st = await tournament.standings(t["id"], limit=50)
        rows = []
        for pos, r in enumerate(st, 1):
            eq = float(r["equity"]) if r["equity"] is not None else dep
            rows.append({"rank": r["rank"] or pos, "name": tournament.display_name(r),
                         "eq": eq, "ret": (eq / dep - 1) * 100, "trades": r["trades"],
                         "wr": (r["wins"] / r["trades"] * 100) if r["trades"] else None})
        opens = []
        if t["status"] == "ACTIVE":
            for r in await tournament.open_positions(t["id"]):
                opens.append({"name": tournament.display_name(r), "symbol": r["symbol"],
                              "side": r["side"], "amount": float(r["amount"]),
                              "status": r["status"],
                              "pnl": float(r["live_pct"]) if r["live_pct"] is not None else None})
        own = {"id": t["id"], "status": t["status"], "deposit": dep,
               "ends": _iso(t["ends_at"]), "rows": rows, "opens": opens}
    return web.json_response({"df": df, "own": own}, headers=NO_CACHE)


_INVITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "invite.jpg")


async def invite_jpg(request):
    """259: taklif posti rasmi (Telegram `InlineQueryResultPhoto` — faqat JPEG URL)."""
    with open(_INVITE, "rb") as fh:
        return web.Response(body=fh.read(), content_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})


async def app_page(request):
    # 252: bot nomi sahifaga yoziladi — Telegram tashqarisida (brauzer,
    # to'lov boti) ochilganda ham "Botni ochish" havolasi ishlasin.
    return web.Response(text=PAGE.replace("__BOT__", json.dumps(request.app["bot_username"] or "")),
                        content_type="text/html", headers=NO_CACHE)


async def api_ver(request):
    return web.json_response({"v": PAGE_VER}, headers=NO_CACHE)


def routes() -> list:
    return [
        web.get("/app", app_page),
        web.get("/api/app/ver", api_ver),
        web.get("/invite.jpg", invite_jpg),
        web.post("/api/app/me", api_me),
        web.post("/api/app/open", api_open),
        web.post("/api/app/act", api_act),
        web.post("/api/app/spark", api_spark),
        web.post("/api/app/candles", api_candles),
        web.post("/api/app/top", api_top),
        web.post("/api/app/diptop", api_diptop),
        web.post("/api/app/diptasks", api_diptasks),
        web.post("/api/app/hstat", api_hstat),
        web.post("/api/app/period", api_period),
        web.post("/api/app/group", api_group),
        web.post("/api/app/tour", api_tour),
        web.post("/api/app/tspark", api_tspark),
    ]


T = {
    "uz": {
        "bot": "Bot", "open": "Ochiq signallar", "open_sub": "Jonli boshqaruv",
        "deposit": "Depozit", "spot": "Spot", "fut": "Futures", "stats": "Statistika",
        "stats_sub": "Natijalar", "tour": "Turnir", "tour_sub": "Oylik musobaqa",
        "df": "Dip Funded", "df_sub": "Prop hisoblar", "soon": "Tez orada",
        "journals": "Jurnallarim", "lang": "Til", "back_bot": "Botga qaytish", "ui_lang": "Ilova tili",
        "top": "Top", "top_sub": "Reyting", "groups": "Guruhlar", "channels": "Kanallar",
        "top_empty": "Hozircha reytingda hech kim yo'q", "sig_w": "signal", "welcome": "Xush kelibsiz",
        "t_live": "Davom etmoqda", "t_soon": "Boshlanishiga", "t_df_sub": "Sovrinli turnir",
        "t_players": "qatnashchi", "t_place": "o'rin", "t_join": "Qatnashish", "t_board": "Reyting",
        "t_own": "TC turniri", "t_empty": "Hali qatnashchi yo'q",
        "not_public": "Sahifa ochiq emas", "subscribe": "Obuna bo'lish", "join": "Qo'shilish",
        "equity": "Dinamika", "monthly": "Oylar bo'yicha", "position": "Pozitsiya",
        "hidden_note": "Juftliklar — faqat a'zolarga", "recent": "Yopilgan savdolar",
        "no_closed": "Hali yopilgan signal yo'q",
        "s_sig": "Signal", "s_wr": "Winrate", "s_net": "Natija", "s_r": "O'rtacha R", "s_liq": "Likvidatsiya",
        "months": "Oylar", "history": "Tarix", "open_s": "Ochiq",
        "tp_btn": "TP", "tps_title": "Maqsadlar (TP)", "tps_hint": "Bo'sh joy bilan: 110 120 130",
        "entry_btn": "Kirish", "entry_title": "Yangi kirish narxi", "tpsl_btn": "TP/SL qo'yish",
        "sl_l": "Stop (SL)", "add_btn": "Qo'shish", "add_title": "Pozitsiyaga qo'shish",
        "now": "Hozirgi narx", "lim": "Limit", "size_usd": "Summa, $", "size_x": "Hajm (1 = boshlang'ich)",
        "prices": "Limit narxlari (5 tagacha)", "lims": "Limitlar", "size_btn": "Summa",
        "size_title": "Pozitsiya summasi",
        "join_setup": "Qo'shilish havolasi ulanmagan — botda ulash",
        "p_d": "Bugun", "p_w": "Hafta", "p_m": "Oy", "p_y": "Yil", "p_all": "Hammasi",
        "money": "Pul natija", "wl": "Foyda / zarar", "avg_wl": "O'rtacha foyda / zarar",
        "dep_title": "Depozit", "dep_spot": "Spot depozit", "dep_fut": "Futures depozit",
        "busy_l": "Pozitsiyalarda", "free_l": "Bo'sh", "new_val": "Yangi qiymat, $",
        "df_open": "Dip Funded botda ochildi", "df_site": "Saytni ochish", "df_acc": "Hisoblarim (botda)",
        "df_title": "Dip Funded", "df_txt": "Prop hisoblar: savdo, sotish va hisob holati botda. Turnir — Turnir bo'limida.",
        "df_buy": "Prop hisob olish", "df_accs": "Prop hisoblar", "df_none": "Hali prop hisob yo'q",
        "df_nolink": "Telegram Dip Funded akkauntiga ulanmagan", "df_link_btn": "Akkauntni ulash",
        "df_unav": "Dip Funded hozir javob bermayapti", "df_equity": "Equity", "df_balance": "Balans",
        "df_free": "Bo'sh", "df_daily": "Kunlik limit", "df_maxdd": "Maks. zarar", "df_target": "Maqsad",
        "df_days": "Savdo kunlari", "df_pos": "Pozitsiyalar", "df_orders": "Limit buyruqlar",
        "df_term": "Savdo terminali", "df_inbot": "Botda boshqarish",
        "ns_title": "Yangi signal", "ns_btn": "Yangi signal", "ns_pair": "Juftlik (masalan BTC)",
        "ns_kind": "Turi", "ns_lev": "Leveraj", "ns_side": "Yo'nalish", "ns_entry_mode": "Kirish",
        "ns_market": "Bozor narxi", "ns_limit": "Limit", "ns_entry": "Kirish narxi", "ns_tf": "Taymfreym (grafik)", "term_hint": "Chiziqni (SL, TP, kirish, limit) barmoq bilan surib, saqlang", "ns_sl": "Stop (SL)",
        "ns_tps": "Maqsadlar (TP) — bo'sh joy bilan", "ns_amount": "Summa, $ (ixtiyoriy)",
        "ns_send": "Signal berish", "ns_where": "Qayerga",
        "ref_title": "Taklif qilish", "ref_sub": "Do'stlaringizni taklif qiling — DIP yig'ing", "ref_code": "Taklif kodingiz",
        "ref_link": "Shaxsiy havola", "ref_count": "Siz orqali kelganlar", "ref_copy": "Nusxa olish",
        "ref_share": "Ulashish", "ref_copied": "Nusxa olindi", "ref_pick": "O'z kodimni tanlash",
        "ref_need": "Yana {n} ta odam taklif qilsangiz, o'z kodingizni tanlay olasiz",
        "ref_new": "Yangi kod ({mn}–{mx} belgi)", "ref_share_txt": "Trade Controller — signallar natijasini kuzatish boti",
        "man_fill": "Juftlik, stop va TP ni to'ldiring",
        "pairs": "Juftliklar",
        "dip_out": "Tokenlarni chiqarish", "dip_out_lock": "{min} DIP dan ochiladi · yana {n} DIP", "dip_out_pend": "So'rov ko'rib chiqilmoqda: {n} DIP", "dip_out_ask": "Barcha {n} DIP ni chiqarishga so'rov yuborilsinmi?", "dip_to_df": "Dip Funded hisobiga", "dip_to_df_s": "Komissiyasiz · darhol o'tadi", "dip_to_usdt": "USDT qilib hamyonga", "dip_fee_s": "Komissiya {p}% ({n} DIP)", "dip_get": "Siz olasiz", "dip_net": "Tarmoq: faqat BEP20 (BNB Smart Chain)", "dip_addr": "USDT hamyon manzili", "dip_send": "So'rov yuborish", "dip_move": "O'tkazish", "dip_to_other": "Kimgadir o'tkazish", "dip_to_ph": "Dip Funded ID yoki @username", "dip_to_ask": "{name} ({id}) ga {n} DIP o'tkazilsinmi?", "dip_nouser": "Bunday foydalanuvchi topilmadi", "dip": "DIP", "dip_rank": "Reyting", "dip_rank_sub": "Eng ko'p DIP yig'ganlar", "dip_refs": "taklif", "dip_you": "Siz", "dip_empty": "Hali hech kim DIP yig'magan", "dip_invite": "Do'st taklif qilish", "dip_more": "Taklif sahifasi", "earn_title": "DIP Earn", "earn_sub": "Vazifalarni bajaring — har biri uchun DIP oling. Kanal obunasi bot orqali tekshiriladi.", "earn_done": "Bajarildi", "earn_check": "Tekshirish", "earn_go": "Bajarish", "earn_people": "kishi", "earn_verified": "tekshiriladi", "earn_empty": "Hozircha vazifalar yo'q", "earn_apply_btn": "Hamkor bo'lish", "earn_apply_title": "Hamkor bo'lish", "earn_apply_sub": "Kanalingiz, guruhingiz yoki botingiz barcha foydalanuvchilarga DIP vazifasi sifatida ko'rinadi.", "earn_price": "Joylashtirish narxi", "earn_once": "1 oy", "earn_aud": "Auditoriya (jonli raqamlar)", "earn_a_users": "Foydalanuvchilar", "earn_a_m30": "30 kunda faol", "earn_a_d7": "7 kunda faol", "earn_a_d1": "Bugun faol", "earn_a_groups": "Signal guruhlari", "earn_a_dip": "DIP yig'uvchilar", "earn_f1": "Hammasi jonli auditoriya — botlar emas, Telegram'dagi haqiqiy treyderlar", "earn_f2": "DIP faqat obuna bo'lgandan keyin beriladi — bot har birini tekshiradi", "earn_f3": "Auditoriya: kripto va forex treyderlar, signal guruhlari egalari va a'zolari", "earn_f4": "Vazifa DIP bo'limida 1 oy davomida barcha foydalanuvchilarga ko'rinadi", "earn_k_channel": "Kanal", "earn_k_group": "Guruh", "earn_note": "Izoh yoki aloqa (ixtiyoriy)", "earn_send": "Ariza yuborish", "earn_need": "Manzilni kiriting", "earn_def_channel": "Kanalga obuna bo'ling va obunani saqlang", "earn_def_group": "Guruhga qo'shiling", "earn_def_bot": "Botni oching va /start bosing", "earn_def_link": "Saytga kiring va tanishib chiqing", "t_upnl": "Unrealized PnL (USDT)", "t_rpnl": "Realized PnL", "t_roe": "ROE", "t_margin": "Marja", "t_notional": "Pozitsiya hajmi", "t_qty": "Miqdor", "t_mark": "Mark narx", "t_avg": "O'rtacha kirish", "t_liq": "Likvidatsiya", "t_closed": "Yopilgan qism", "t_opened": "Ochilgan", "t_risk": "SL'da", "t_reward": "Keyingi TP'da", "t_rr": "R:R", "t_nosize": "Summa kiritilmagan — natija faqat % da. $ uchun «Hajm»ni kiriting", "t_pos": "Pozitsiya", "t_total": "Jami natija", "dip_bal": "DIP balans", "dip_per": "Har bir taklif uchun +{n} DIP", "dip_note": "1000 DIP = $10 · Dip Funded hisobiga yoki USDT qilib hamyonga chiqarish mumkin",
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
        "bot": "Бот", "open": "Открытые сигналы", "open_sub": "Живое управление",
        "deposit": "Депозит", "spot": "Спот", "fut": "Фьючерсы", "stats": "Статистика",
        "stats_sub": "Результаты", "tour": "Турнир", "tour_sub": "Ежемесячный конкурс",
        "df": "Dip Funded", "df_sub": "Проп-счета", "soon": "Скоро",
        "journals": "Мои журналы", "lang": "Язык", "back_bot": "Вернуться в бот", "ui_lang": "Язык приложения",
        "top": "Топ", "top_sub": "Рейтинг", "groups": "Группы", "channels": "Каналы",
        "top_empty": "В рейтинге пока никого", "sig_w": "сигн.", "welcome": "Добро пожаловать",
        "t_live": "Идёт", "t_soon": "До начала", "t_df_sub": "Турнир с призами",
        "t_players": "участн.", "t_place": "место", "t_join": "Участвовать", "t_board": "Рейтинг",
        "t_own": "Турнир TC", "t_empty": "Пока нет участников",
        "not_public": "Страница не открыта", "subscribe": "Подписаться", "join": "Вступить",
        "equity": "Динамика", "monthly": "По месяцам", "position": "Позиция",
        "hidden_note": "Пары — только участникам", "recent": "Закрытые сделки",
        "no_closed": "Пока нет закрытых сигналов",
        "s_sig": "Сигналы", "s_wr": "Винрейт", "s_net": "Итог", "s_r": "Средний R", "s_liq": "Ликвидации",
        "months": "Месяцы", "history": "История", "open_s": "Открытые",
        "tp_btn": "TP", "tps_title": "Цели (TP)", "tps_hint": "Через пробел: 110 120 130",
        "entry_btn": "Вход", "entry_title": "Новая цена входа", "tpsl_btn": "Поставить TP/SL",
        "sl_l": "Стоп (SL)", "add_btn": "Добавить", "add_title": "Добавить к позиции",
        "now": "По рынку", "lim": "Лимит", "size_usd": "Сумма, $", "size_x": "Объём (1 = исходный)",
        "prices": "Цены лимитов (до 5)", "lims": "Лимиты", "size_btn": "Сумма",
        "size_title": "Сумма позиции",
        "join_setup": "Ссылка для вступления не подключена — подключить в боте",
        "p_d": "Сегодня", "p_w": "Неделя", "p_m": "Месяц", "p_y": "Год", "p_all": "Всё",
        "money": "Результат в $", "wl": "Прибыль / убыток", "avg_wl": "Средняя прибыль / убыток",
        "dep_title": "Депозит", "dep_spot": "Спот депозит", "dep_fut": "Фьючерс депозит",
        "busy_l": "В позициях", "free_l": "Свободно", "new_val": "Новое значение, $",
        "df_open": "Dip Funded открыт в боте", "df_site": "Открыть сайт", "df_acc": "Мои счета (в боте)",
        "df_title": "Dip Funded", "df_txt": "Проп-счета: торговля и состояние счёта в боте. Турнир — во вкладке Турнир.",
        "df_buy": "Купить проп-счёт", "df_accs": "Проп-счета", "df_none": "Пока нет проп-счетов",
        "df_nolink": "Telegram не привязан к Dip Funded", "df_link_btn": "Привязать аккаунт",
        "df_unav": "Dip Funded сейчас не отвечает", "df_equity": "Equity", "df_balance": "Баланс",
        "df_free": "Свободно", "df_daily": "Дневной лимит", "df_maxdd": "Макс. просадка", "df_target": "Цель",
        "df_days": "Торговые дни", "df_pos": "Позиции", "df_orders": "Лимитные ордера",
        "df_term": "Терминал", "df_inbot": "Управлять в боте",
        "ns_title": "Новый сигнал", "ns_btn": "Новый сигнал", "ns_pair": "Пара (например BTC)",
        "ns_kind": "Тип", "ns_lev": "Плечо", "ns_side": "Направление", "ns_entry_mode": "Вход",
        "ns_market": "По рынку", "ns_limit": "Лимит", "ns_entry": "Цена входа", "ns_tf": "Таймфрейм (график)", "term_hint": "Перетащите линию (SL, TP, вход, лимит) пальцем и сохраните", "ns_sl": "Стоп (SL)",
        "ns_tps": "Цели (TP) — через пробел", "ns_amount": "Сумма, $ (необязательно)",
        "ns_send": "Отправить сигнал", "ns_where": "Куда",
        "ref_title": "Пригласить", "ref_sub": "Приглашайте друзей — копите DIP", "ref_code": "Ваш код",
        "ref_link": "Личная ссылка", "ref_count": "Пришли по вашей ссылке", "ref_copy": "Копировать",
        "ref_share": "Поделиться", "ref_copied": "Скопировано", "ref_pick": "Выбрать свой код",
        "ref_need": "Пригласите ещё {n} — и сможете выбрать свой код",
        "ref_new": "Новый код ({mn}–{mx} символов)", "ref_share_txt": "Trade Controller — бот для учёта результатов сигналов",
        "man_fill": "Заполните пару, стоп и TP",
        "pairs": "Пары",
        "dip_out": "Вывести токены", "dip_out_lock": "Доступно от {min} DIP · ещё {n} DIP", "dip_out_pend": "Заявка рассматривается: {n} DIP", "dip_out_ask": "Отправить заявку на вывод всех {n} DIP?", "dip_to_df": "На счёт Dip Funded", "dip_to_df_s": "Без комиссии · сразу", "dip_to_usdt": "В USDT на кошелёк", "dip_fee_s": "Комиссия {p}% ({n} DIP)", "dip_get": "Вы получите", "dip_net": "Сеть: только BEP20 (BNB Smart Chain)", "dip_addr": "Адрес USDT-кошелька", "dip_send": "Отправить заявку", "dip_move": "Перевести", "dip_to_other": "Перевести другому", "dip_to_ph": "ID Dip Funded или @username", "dip_to_ask": "Перевести {n} DIP пользователю {name} ({id})?", "dip_nouser": "Пользователь не найден", "dip": "DIP", "dip_rank": "Рейтинг", "dip_rank_sub": "Больше всего DIP", "dip_refs": "пригл.", "dip_you": "Вы", "dip_empty": "Пока никто не собрал DIP", "dip_invite": "Пригласить друга", "dip_more": "Страница приглашений", "earn_title": "DIP Earn", "earn_sub": "Выполняйте задания — за каждое DIP. Подписка на канал проверяется ботом.", "earn_done": "Выполнено", "earn_check": "Проверить", "earn_go": "Выполнить", "earn_people": "чел.", "earn_verified": "с проверкой", "earn_empty": "Пока заданий нет", "earn_apply_btn": "Стать партнёром", "earn_apply_title": "Стать партнёром", "earn_apply_sub": "Ваш канал, группа или бот будет виден всем пользователям как DIP-задание.", "earn_price": "Цена размещения", "earn_once": "1 месяц", "earn_aud": "Аудитория (живые цифры)", "earn_a_users": "Пользователи", "earn_a_m30": "Активны 30 дн.", "earn_a_d7": "Активны 7 дн.", "earn_a_d1": "Активны сегодня", "earn_a_groups": "Сигнальные группы", "earn_a_dip": "Собирают DIP", "earn_f1": "Только живая аудитория — не боты, реальные трейдеры в Telegram", "earn_f2": "DIP даются только после подписки — бот проверяет каждого", "earn_f3": "Аудитория: крипто- и форекс-трейдеры, владельцы и участники сигнальных групп", "earn_f4": "Задание видно всем в разделе DIP в течение 1 месяца", "earn_k_channel": "Канал", "earn_k_group": "Группа", "earn_note": "Комментарий или контакт (необяз.)", "earn_send": "Отправить заявку", "earn_need": "Укажите адрес", "earn_def_channel": "Подпишитесь на канал и оставайтесь подписаны", "earn_def_group": "Вступите в группу", "earn_def_bot": "Откройте бота и нажмите /start", "earn_def_link": "Перейдите на сайт и ознакомьтесь", "t_upnl": "Нереализ. PnL (USDT)", "t_rpnl": "Реализ. PnL", "t_roe": "ROE", "t_margin": "Маржа", "t_notional": "Размер позиции", "t_qty": "Кол-во", "t_mark": "Марк. цена", "t_avg": "Ср. вход", "t_liq": "Ликвидация", "t_closed": "Закрыто", "t_opened": "Открыта", "t_risk": "На SL", "t_reward": "На след. TP", "t_rr": "R:R", "t_nosize": "Сумма не указана — результат только в %. Для $ укажите «Объём»", "t_pos": "Позиция", "t_total": "Итог", "dip_bal": "Баланс DIP", "dip_per": "+{n} DIP за каждое приглашение", "dip_note": "1000 DIP = $10 · можно вывести на счёт Dip Funded или в USDT на кошелёк",
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
        "bot": "Bot", "open": "Open signals", "open_sub": "Live controls",
        "deposit": "Deposit", "spot": "Spot", "fut": "Futures", "stats": "Statistics",
        "stats_sub": "Results", "tour": "Tournament", "tour_sub": "Monthly contest",
        "df": "Dip Funded", "df_sub": "Prop accounts", "soon": "Soon",
        "journals": "My journals", "lang": "Language", "back_bot": "Back to bot", "ui_lang": "App language",
        "top": "Top", "top_sub": "Ranking", "groups": "Groups", "channels": "Channels",
        "top_empty": "Nobody in the ranking yet", "sig_w": "signals", "welcome": "Welcome",
        "t_live": "Live", "t_soon": "Starts in", "t_df_sub": "Prize tournament",
        "t_players": "players", "t_place": "place", "t_join": "Join", "t_board": "Leaderboard",
        "t_own": "TC tournament", "t_empty": "No players yet",
        "not_public": "Page is not public", "subscribe": "Subscribe", "join": "Join",
        "equity": "Equity", "monthly": "Monthly", "position": "Position",
        "hidden_note": "Pairs — members only", "recent": "Closed trades",
        "no_closed": "No closed signals yet",
        "s_sig": "Signals", "s_wr": "Winrate", "s_net": "Result", "s_r": "Avg R", "s_liq": "Liquidations",
        "months": "Months", "history": "History", "open_s": "Open",
        "tp_btn": "TP", "tps_title": "Targets (TP)", "tps_hint": "Space-separated: 110 120 130",
        "entry_btn": "Entry", "entry_title": "New entry price", "tpsl_btn": "Set TP/SL",
        "sl_l": "Stop (SL)", "add_btn": "Add", "add_title": "Add to position",
        "now": "Market", "lim": "Limit", "size_usd": "Size, $", "size_x": "Size (1 = initial)",
        "prices": "Limit prices (up to 5)", "lims": "Limits", "size_btn": "Size",
        "size_title": "Position size",
        "join_setup": "Join link not connected — set it in the bot",
        "p_d": "Today", "p_w": "Week", "p_m": "Month", "p_y": "Year", "p_all": "All",
        "money": "Result $", "wl": "Wins / losses", "avg_wl": "Avg win / loss",
        "dep_title": "Deposit", "dep_spot": "Spot deposit", "dep_fut": "Futures deposit",
        "busy_l": "In positions", "free_l": "Free", "new_val": "New value, $",
        "df_open": "Dip Funded opened in the bot", "df_site": "Open website", "df_acc": "My accounts (bot)",
        "df_title": "Dip Funded", "df_txt": "Prop accounts: trading and status in the bot. Tournament — in the Tournament tab.",
        "df_buy": "Get a prop account", "df_accs": "Prop accounts", "df_none": "No prop accounts yet",
        "df_nolink": "Telegram is not linked to Dip Funded", "df_link_btn": "Link account",
        "df_unav": "Dip Funded is not responding", "df_equity": "Equity", "df_balance": "Balance",
        "df_free": "Free", "df_daily": "Daily limit", "df_maxdd": "Max loss", "df_target": "Target",
        "df_days": "Trading days", "df_pos": "Positions", "df_orders": "Limit orders",
        "df_term": "Trading terminal", "df_inbot": "Manage in bot",
        "ns_title": "New signal", "ns_btn": "New signal", "ns_pair": "Pair (e.g. BTC)",
        "ns_kind": "Type", "ns_lev": "Leverage", "ns_side": "Direction", "ns_entry_mode": "Entry",
        "ns_market": "Market", "ns_limit": "Limit", "ns_entry": "Entry price", "ns_tf": "Timeframe (chart)", "term_hint": "Drag a line (SL, TP, entry, limit) and save", "ns_sl": "Stop (SL)",
        "ns_tps": "Targets (TP) — space-separated", "ns_amount": "Size, $ (optional)",
        "ns_send": "Send signal", "ns_where": "Where",
        "ref_title": "Invite", "ref_sub": "Invite friends — earn DIP", "ref_code": "Your code",
        "ref_link": "Personal link", "ref_count": "Joined through you", "ref_copy": "Copy",
        "ref_share": "Share", "ref_copied": "Copied", "ref_pick": "Pick my own code",
        "ref_need": "Invite {n} more to pick your own code",
        "ref_new": "New code ({mn}–{mx} chars)", "ref_share_txt": "Trade Controller — signal results tracking bot",
        "man_fill": "Fill in pair, stop and TP",
        "pairs": "Pairs",
        "dip_out": "Withdraw tokens", "dip_out_lock": "Unlocks at {min} DIP · {n} DIP to go", "dip_out_pend": "Request under review: {n} DIP", "dip_out_ask": "Send a request to withdraw all {n} DIP?", "dip_to_df": "To Dip Funded account", "dip_to_df_s": "No fee · instant", "dip_to_usdt": "As USDT to a wallet", "dip_fee_s": "Fee {p}% ({n} DIP)", "dip_get": "You receive", "dip_net": "Network: BEP20 (BNB Smart Chain) only", "dip_addr": "USDT wallet address", "dip_send": "Send request", "dip_move": "Transfer", "dip_to_other": "Send to someone", "dip_to_ph": "Dip Funded ID or @username", "dip_to_ask": "Send {n} DIP to {name} ({id})?", "dip_nouser": "User not found", "dip": "DIP", "dip_rank": "Ranking", "dip_rank_sub": "Most DIP collected", "dip_refs": "invites", "dip_you": "You", "dip_empty": "No one has collected DIP yet", "dip_invite": "Invite a friend", "dip_more": "Invite page", "earn_title": "DIP Earn", "earn_sub": "Complete tasks — earn DIP for each. Channel subscriptions are checked by the bot.", "earn_done": "Done", "earn_check": "Check", "earn_go": "Start", "earn_people": "people", "earn_verified": "verified", "earn_empty": "No tasks yet", "earn_apply_btn": "Become a partner", "earn_apply_title": "Become a partner", "earn_apply_sub": "Your channel, group or bot is shown to every user as a DIP task.", "earn_price": "Listing price", "earn_once": "1 month", "earn_aud": "Audience (live numbers)", "earn_a_users": "Users", "earn_a_m30": "Active 30d", "earn_a_d7": "Active 7d", "earn_a_d1": "Active today", "earn_a_groups": "Signal groups", "earn_a_dip": "DIP collectors", "earn_f1": "100% live audience — not bots, real traders on Telegram", "earn_f2": "DIP is given only after subscribing — the bot checks everyone", "earn_f3": "Audience: crypto & forex traders, signal group owners and members", "earn_f4": "The task is visible to everyone in the DIP section for 1 month", "earn_k_channel": "Channel", "earn_k_group": "Group", "earn_note": "Note or contact (optional)", "earn_send": "Send application", "earn_need": "Enter the address", "earn_def_channel": "Subscribe to the channel and stay subscribed", "earn_def_group": "Join the group", "earn_def_bot": "Open the bot and press /start", "earn_def_link": "Visit the website and explore it", "t_upnl": "Unrealized PnL (USDT)", "t_rpnl": "Realized PnL", "t_roe": "ROE", "t_margin": "Margin", "t_notional": "Position size", "t_qty": "Qty", "t_mark": "Mark price", "t_avg": "Avg entry", "t_liq": "Liquidation", "t_closed": "Closed part", "t_opened": "Opened", "t_risk": "At SL", "t_reward": "At next TP", "t_rr": "R:R", "t_nosize": "No amount set — result in % only. Set «Size» for $", "t_pos": "Position", "t_total": "Total", "dip_bal": "DIP balance", "dip_per": "+{n} DIP per invite", "dip_note": "1000 DIP = $10 · withdraw to Dip Funded or as USDT to a wallet",
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
# 273: sahifa versiyasi — Telegram yig'ib qo'ygan (minimize) eski oynani
# qaytarganda ilova yangi versiya chiqqanini bilib, o'zini qayta yuklaydi.
import hashlib as _hl
PAGE_VER = _hl.sha1(PAGE.encode()).hexdigest()[:12]
PAGE = PAGE.replace("__VER__", PAGE_VER)
