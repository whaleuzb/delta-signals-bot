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
import time
import logging
import os

from aiohttp import web

import config
import db
import i18n
import tracker

log = logging.getLogger("webapp")

NO_CACHE = {"Cache-Control": "no-store, max-age=0"}
ACTIONS = ("be", "sl", "pc", "close", "tps", "entry", "tpsl", "add", "lim", "limx", "size", "tf", "limmv", "share", "rcard")
WS_ACTIONS = ("dep", "fdep", "df", "dfacc", "dfone", "newsig", "ref", "refcode", "refshare", "dipout", "diplook", "diptask", "dipapply", "dftrade", "newsshare")       # 254: signalga emas, workspace/odamga


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
            "entry_first": float(r["entry_first"]) if r["entry_first"] is not None else None,
            "marks": [{"t": _iso(m["at"]), "p": m["price"], "k": m["kind"]} for m in await db.signal_marks(r["id"])],
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


async def api_sighist(request):
    """300: signal tarixi — yaratildi/ochildi + guruhga ketgan hodisalar (egasi)."""
    body, uid = await _body(request)
    try:
        sig = await db.get_signal(int(body.get("sig")))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest()
    ws = await db.get_workspace(sig["workspace_id"]) if sig else None
    if not _can(ws, uid):
        raise web.HTTPForbidden()
    ev = [{"at": _iso(r["at"]), "text": r["text"]} for r in await db.signal_events(sig["id"])]
    return web.json_response({"created": _iso(sig["created_at"]), "opened": _iso(sig["opened_at"]),
                              "events": ev}, headers=NO_CACHE)


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


_DF_SYM = __import__("re").compile(r"^[A-Z0-9]{1,15}$")


async def api_dfcandles(request):
    """310: Dip Funded terminali — juftlik shamlari MEXC'dan (BTC -> BTCUSDT, AAPLON ->
    AAPLONUSDT). Ochiq bozor ma'lumoti, faqat initData kerak. 30 soniya kesh."""
    import time as _t
    body, _uid = await _body(request)
    sym = str(body.get("sym") or "").upper()
    if not _DF_SYM.match(sym):
        raise web.HTTPBadRequest()
    tf = body.get("tf") if body.get("tf") in _TF_MS else "1h"
    pair = sym if sym.endswith(config.QUOTE) else sym + config.QUOTE
    key = ("crypto", pair, tf)
    hit = _CANDLES.get(key)
    if hit and _t.monotonic() - hit[0] < 30:
        rows = hit[1]
    else:
        now = int(_t.time() * 1000)
        try:
            cs = await tracker.provider("crypto").klines(
                pair, now - 160 * _TF_MS[tf], limit=200, tf=tf, end_ms=now)
        except Exception:
            log.warning("DF terminal shamlari olinmadi (%s %s)", pair, tf, exc_info=True)
            cs = []
        rows = [[c.open_ms, float(c.open), float(c.high), float(c.low), float(c.close)] for c in cs][-160:]
        if rows:
            if len(_CANDLES) > 300:
                _CANDLES.clear()
            _CANDLES[key] = (_t.monotonic(), rows)
    return web.json_response({"tf": tf, "c": rows}, headers=NO_CACHE)


async def api_pairs(request):
    """313: juftlik tanlash oynasi — MEXC spot yoki fyuchers juftliklari (hajm bo'yicha)."""
    body, _uid = await _body(request)
    kind = "fut" if body.get("kind") == "fut" else "spot"
    import exchange as _ex
    import futures as _fu
    try:
        rows = await (_fu if kind == "fut" else _ex).price_list()
    except Exception:
        log.warning("Juftliklar ro'yxati olinmadi (%s)", kind, exc_info=True)
        rows = []
    return web.json_response({"kind": kind, "p": [[s, p] for s, p in rows[:2500]]},
                             headers={"Cache-Control": "private, max-age=30"})


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
    if act == "newsshare":
        # 315: News Trade postini ulashish — faqat post raqami.
        f = body.get("args") if isinstance(body.get("args"), dict) else {}
        try:
            m = int(f.get("m"))
        except (TypeError, ValueError):
            raise web.HTTPBadRequest()
        aid = await db.app_action_add(uid, 0, act, None, json.dumps({"m": m}))
        return await _wait_action(aid)
    if act == "dftrade":
        # 310: Dip Funded savdosi (ilova terminali) — huquqni Dip Funded tekshiradi
        # (hisob shu Telegram akkauntiga tegishlimi); bu yerda faqat shakl va chegaralar.
        f = body.get("args") if isinstance(body.get("args"), dict) else {}
        op = str(f.get("op") or "")
        if op not in ("buy", "sell", "protect", "cancel", "modify"):
            raise web.HTTPBadRequest()
        clean = {"op": op}
        for k in ("acc", "order_id"):
            if f.get(k) is not None:
                try:
                    clean[k] = int(f[k])
                except (TypeError, ValueError):
                    raise web.HTTPBadRequest()
        if "acc" not in clean:
            raise web.HTTPBadRequest()
        if f.get("symbol") is not None:
            sym = str(f["symbol"]).upper()
            if not _DF_SYM.match(sym):
                raise web.HTTPBadRequest()
            clean["symbol"] = sym
        for k in ("amount", "limit", "sl", "tp", "fraction"):
            if k in f:
                v = f[k]
                if v is None or v == "":
                    clean[k] = None
                    continue
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    raise web.HTTPBadRequest()
                if not (x > 0) or x != x or x > 1e12:
                    raise web.HTTPBadRequest()
                clean[k] = x
        aid = await db.app_action_add(uid, 0, act, None, json.dumps(clean))
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


# 307: amallar navbatini to'ldirib yuborishdan himoya — har bir odamga daqiqasiga
# 30 ta amal (oddiy foydalanishda bunga hech qachon yetilmaydi). Har amal botda
# ish qiladi (ba'zilari rasm chizadi), cheksiz bo'lsa bitta odam botni band qiladi.
_ACT_LIMIT, _ACT_WINDOW = 30, 60.0
_act_hits: dict[int, list[float]] = {}


def _act_allowed(uid: int) -> bool:
    now = time.monotonic()
    hits = [t for t in _act_hits.get(uid, ()) if now - t < _ACT_WINDOW]
    if len(hits) >= _ACT_LIMIT:
        _act_hits[uid] = hits
        return False
    hits.append(now)
    _act_hits[uid] = hits
    if len(_act_hits) > 5000:          # eski yozuvlar xotirani yemasin
        for k in [k for k, v in _act_hits.items() if not v or now - v[-1] > _ACT_WINDOW]:
            _act_hits.pop(k, None)
    return True


async def api_act(request):
    body, uid = await _body(request)
    if not _act_allowed(uid):
        raise web.HTTPTooManyRequests()
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


# 298: tanga belgilari (Dip Funded'dan, CC0/MIT — static/coins/LICENSE.md).
_COIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "coins")
COINS = sorted(f[:-4] for f in os.listdir(_COIN_DIR) if f.endswith(".svg")) if os.path.isdir(_COIN_DIR) else []


async def coin_svg(request):
    name = request.match_info["c"].lower()
    if name not in COINS:
        raise web.HTTPNotFound()
    with open(os.path.join(_COIN_DIR, name + ".svg"), "rb") as fh:
        return web.Response(body=fh.read(), content_type="image/svg+xml",
                            headers={"Cache-Control": "public, max-age=604800"})


# ─────────────── 324: birja hisoblari (faqat o'qish) ───────────────
_CEX_CACHE: dict[tuple, tuple[float, dict]] = {}
_CEX_TTL = 20.0


async def _cx_call(op: str, ex: str, k: dict, extra: dict | None = None):
    """326: `CEX_RELAY_URL` bo'lsa — Singapurdagi `cex` servisi orqali (ichki tarmoq),
    bo'lmasa — shu yerdan to'g'ridan-to'g'ri (`cex` moduli)."""
    import cex
    url = os.getenv("CEX_RELAY_URL", "").rstrip("/")
    if not url:
        if op == "trade":
            return await cex.trade(ex, k, (extra or {}).get("op"), (extra or {}).get("a"))
        f = {"verify": cex.verify, "snapshot": cex.snapshot, "history": cex.history,
             "trades": cex.trades}[op]
        return await f(ex, k)
    import httpx
    try:
        async with httpx.AsyncClient(timeout=90 if op in ("trades", "trade") else 30) as c:
            r = await c.post(f"{url}/{op}", json={"ex": ex, "k": k, **(extra or {})},
                             headers={"X-Relay-Token": os.getenv("RELAY_TOKEN", "")})
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        log.warning("cex servisiga ulanib bo'lmadi (%s): %s", op, type(e).__name__)
        raise cex.ApiErr("net", type(e).__name__)
    if d.get("err"):
        raise cex.ApiErr(d["err"], str(d.get("msg") or ""))
    return {"history": d.get("hist"), "trades": d.get("trades"), "trade": d.get("r")}.get(op, d.get("snap"))


async def cex_relay_check(_app=None):
    """Ishga tushganda: Singapurdagi `cex` servisiga ichki tarmoq orqali ulanish bormi (logga)."""
    url = os.getenv("CEX_RELAY_URL", "").rstrip("/")
    if not url:
        return
    import httpx

    async def run():
        for k in range(6):
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(url + "/healthz")
                log.info("cex servisi (Singapur): ulanish bor — HTTP %s", r.status_code)
                return
            except Exception as e:
                last = type(e).__name__
            await asyncio.sleep(15)
        log.warning("cex servisiga ulanib bo'lmadi (%s) — birja hisoblari ishlamaydi", last)
    _CEX_BG.add(asyncio.get_running_loop().create_task(run()))


def _cex_keys(row) -> dict:
    import cex
    return {"key": cex.unseal(row["key_enc"]), "secret": cex.unseal(row["secret_enc"]),
            "pass": cex.unseal(row["pass_enc"]) if row["pass_enc"] else ""}


async def _cex_one(uid: int, row, fresh: bool) -> dict:
    import cex
    ex = row["exchange"]
    ck = (uid, ex)
    hit = _CEX_CACHE.get(ck)
    if hit and not fresh and time.monotonic() - hit[0] < _CEX_TTL:
        return hit[1]
    base = {"ex": ex, "name": cex.NAMES.get(ex, ex), "mask": row["key_mask"]}
    try:
        k = _cex_keys(row)
    except Exception:
        # Shifr kaliti o'zgargan (EXCH_ENC_KEY/BOT_TOKEN) — qayta ulash kerak.
        res = {**base, "err": "reconnect"}
    else:
        try:
            res = {**base, **await _cx_call("snapshot", ex, k)}
        except cex.ApiErr as e:
            res = {**base, "err": e.code}
        except Exception:
            log.warning("Birja hisobi o'qilmadi (%s)", ex, exc_info=True)
            res = {**base, "err": "api"}
    if len(_CEX_CACHE) > 2000:
        _CEX_CACHE.clear()
    _CEX_CACHE[ck] = (time.monotonic(), res)
    if not res.get("err"):
        try:
            await _cex_rec(uid, ex, res)
        except Exception:
            log.warning("Balans tarixi yozilmadi (%s)", ex, exc_info=True)
    return res


# 328: balans tarixi — har hisob uchun soatiga ko'pi bilan bitta yozuv.
_CEX_REC: dict[tuple, float] = {}
_CEX_BG: set = set()          # fon vazifalari (GC ularni yo'qotmasin)
_CEX_REC_GAP = 50 * 60


async def _cex_rec(uid: int, ex: str, res: dict) -> None:
    from datetime import datetime, timezone
    key = (uid, ex)
    now = time.time()
    last = _CEX_REC.get(key)
    if last is None:
        at = await db.cex_hist_last_at(uid, ex)
        last = at.timestamp() if at else 0.0
    if now - last < _CEX_REC_GAP:
        _CEX_REC[key] = last
        return
    fut = (res.get("fut") or {}).get("eq")
    await db.cex_hist_add(uid, ex, datetime.now(timezone.utc), float(res.get("total") or 0),
                          float(res.get("spot_usd") or 0), float(fut) if fut is not None else None)
    _CEX_REC[key] = now


async def _cex_backfill(uid: int, ex: str, k: dict) -> None:
    """Ulanganda: birja o'zi bergan o'tmish (Binance — 30 kun kunlik)."""
    from datetime import datetime, timezone
    try:
        rows = await _cx_call("history", ex, k) or []
    except Exception as e:
        log.info("Balans o'tmishi olinmadi (%s): %s", ex, e)
        return
    n = await db.cex_hist_add_many(uid, ex, [
        (datetime.fromtimestamp(r[0] / 1000, timezone.utc), float(r[1]), float(r[2]), float(r[3]))
        for r in rows])
    if n:
        log.info("Balans o'tmishi yuklandi (%s, uid=%s): %s kun", ex, uid, n)


async def cex_hist_loop(_app=None):
    """Har soat: barcha ulangan hisoblar balansi tarixga (ilova ochilmasa ham)."""
    async def backfill_old():
        # Funksiyadan oldin ulangan (o'tmishi yuklanmagan) Binance hisoblari.
        from datetime import datetime, timezone, timedelta
        for r in await db.cex_all():
            if r["exchange"] != "binance":
                continue
            first = await db.cex_hist_first_at(r["user_id"], r["exchange"])
            if first is None or first > datetime.now(timezone.utc) - timedelta(days=2):
                try:
                    await _cex_backfill(r["user_id"], r["exchange"], _cex_keys(r))
                except Exception:
                    log.warning("Balans o'tmishi yuklanmadi", exc_info=True)

    async def run():
        await asyncio.sleep(20)
        try:
            await backfill_old()
        except Exception:
            log.warning("Balans o'tmishi tekshiruvi xato", exc_info=True)
        await asyncio.sleep(100)
        while True:
            try:
                rows = await db.cex_all()
                sem = asyncio.Semaphore(3)

                async def one(r):
                    async with sem:
                        await _cex_one(r["user_id"], r, True)
                await asyncio.gather(*(one(r) for r in rows), return_exceptions=True)
                for r in rows:                      # 334/335: savdo tarixi (statistika uchun) — barcha birjalar
                    await _cx_sync(r["user_id"], r["exchange"], r)
            except Exception:
                log.warning("Balans tarixi tsikli xato", exc_info=True)
            await asyncio.sleep(3600)
    t = asyncio.get_running_loop().create_task(run())
    _CEX_BG.add(t)


async def api_cex(request):
    body, uid = await _body(request)
    rows = await db.cex_list(uid)
    fresh = bool(body.get("fresh")) and _act_allowed(uid)
    res = await asyncio.gather(*(_cex_one(uid, r, fresh) for r in rows))
    return web.json_response({"acc": list(res)}, headers=NO_CACHE)


def _cx_msg(text: str) -> str:
    """Birja javobidan foydalanuvchiga ko'rsatiladigan qisqa matn (JSON bo'lsa — `msg`)."""
    t = (text or "").strip()
    try:
        d = json.loads(t)
        if isinstance(d, dict):
            t = str(d.get("msg") or d.get("message") or t)
    except ValueError:
        pass
    return t[:160]


async def api_cexadd(request):
    import cex
    body, uid = await _body(request)
    if not _act_allowed(uid):
        raise web.HTTPTooManyRequests()
    ex = str(body.get("ex") or "")
    key = str(body.get("key") or "").strip()
    sec = str(body.get("secret") or "").strip()
    pas = str(body.get("pass") or "").strip()
    if ex not in cex.EXCHANGES or not (8 <= len(key) <= 200) or not (8 <= len(sec) <= 200) \
            or len(pas) > 100 or (ex in cex.NEEDS_PASS and not pas):
        return web.json_response({"ok": False, "err": "bad"}, headers=NO_CACHE)
    k = {"key": key, "secret": sec, "pass": pas}
    try:
        await _cx_call("verify", ex, k)
    except cex.ApiErr as e:
        log.info("Birja kaliti rad etildi (%s, uid=%s): %s — %s", ex, uid, e.code, e.text[:200])
        return web.json_response({"ok": False, "err": e.code, "msg": _cx_msg(e.text)},
                                 headers=NO_CACHE)
    except Exception:
        log.warning("Birja kalitini tekshirishda xato (%s)", ex, exc_info=True)
        return web.json_response({"ok": False, "err": "api"}, headers=NO_CACHE)
    await db.cex_put(uid, ex, cex.seal(key), cex.seal(sec), cex.seal(pas) if pas else None,
                     cex.mask(key))
    _CEX_CACHE.pop((uid, ex), None)
    _CEX_REC.pop((uid, ex), None)
    log.info("Birja hisobi ulandi (%s, uid=%s)", ex, uid)
    t = asyncio.get_running_loop().create_task(_cex_backfill(uid, ex, k))
    _CEX_BG.add(t)
    t.add_done_callback(_CEX_BG.discard)
    row = next((r for r in await db.cex_list(uid) if r["exchange"] == ex), None)
    if row is not None:
        t2 = asyncio.get_running_loop().create_task(_cx_sync(uid, ex, row))
        _CEX_BG.add(t2)
        t2.add_done_callback(_CEX_BG.discard)
    return web.json_response({"ok": True}, headers=NO_CACHE)


async def api_cexhist(request):
    """328: balans tarixi grafigi. ex bo'lmasa — barcha hisoblar yig'indisi.
    7 kungacha — soatlik, undan ko'p — kunlik nuqtalar; har hisob oxirgi
    ma'lum qiymati bilan davom ettiriladi (carry forward)."""
    from datetime import datetime, timezone, timedelta
    body, uid = await _body(request)
    ex = body.get("ex") or None
    import cex
    if ex is not None and ex not in cex.EXCHANGES:
        raise web.HTTPBadRequest()
    try:
        days = int(body.get("days") or 30)
    except (TypeError, ValueError):
        days = 30
    days = days if days in (7, 30, 90, 365) else 30
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = await db.cex_hist_rows(uid, since, ex)
    step = 3600 if days <= 7 else 86400
    by = {}
    for r in sorted(rows, key=lambda r: r["at"]):
        by.setdefault(r["exchange"], []).append((r["at"].timestamp(), float(r["total"])))
    pts = []
    t = (since.timestamp() // step + 1) * step
    end = now.timestamp()
    idx = {e: 0 for e in by}
    cur = {}
    while True:
        tt = min(t, end)
        for e, lst in by.items():
            i = idx[e]
            while i < len(lst) and lst[i][0] <= tt:
                cur[e] = lst[i][1]
                i += 1
            idx[e] = i
        if cur:
            pts.append([int(tt * 1000), round(sum(cur.values()), 2)])
        if t >= end:
            break
        t += step
    return web.json_response({"days": days, "p": pts}, headers=NO_CACHE)


_CEX_TR: dict[tuple, tuple[float, dict]] = {}
_CEX_TR_TTL = 600.0


async def api_cextrades(request):
    """329: savdolar tarixi (Binance: fyuchers yopilishlari + spot orderlar), 10 daq kesh."""
    import cex
    body, uid = await _body(request)
    ex = str(body.get("ex") or "")
    if ex not in cex.EXCHANGES:
        raise web.HTTPBadRequest()
    key = (uid, ex)
    hit = _CEX_TR.get(key)
    fresh = bool(body.get("fresh"))
    if hit and time.monotonic() - hit[0] < (_CEX_TR_TTL if not fresh else 60):
        return web.json_response(hit[1], headers=NO_CACHE)
    if not _act_allowed(uid):
        raise web.HTTPTooManyRequests()
    row = next((r for r in await db.cex_list(uid) if r["exchange"] == ex), None)
    if row is None:
        raise web.HTTPNotFound()
    try:
        res = {"ok": True, "tr": await _cx_call("trades", ex, _cex_keys(row))}
    except cex.ApiErr as e:
        return web.json_response({"ok": False, "err": e.code, "msg": _cx_msg(e.text)}, headers=NO_CACHE)
    except Exception:
        log.warning("Savdolar tarixi olinmadi (%s)", ex, exc_info=True)
        return web.json_response({"ok": False, "err": "api"}, headers=NO_CACHE)
    if len(_CEX_TR) > 500:
        _CEX_TR.clear()
    _CEX_TR[key] = (time.monotonic(), res)
    return web.json_response(res, headers=NO_CACHE)


# ─────────────── 334: savdo tarixi sinxronizatsiyasi va statistika ───────────────
_CX_SYNC_RUN: set = set()
_CX_SYNC_GAP = 600          # ilova so'raganda — ko'pi bilan 10 daqiqada bir marta


def _year_start_ms() -> int:
    from datetime import datetime, timezone
    n = datetime.now(timezone.utc)
    return int(datetime(n.year, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _dt(ms: int):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def _inc_rows(lst: list) -> list:
    return [{"key": x["key"], "kind": "inc", "typ": x.get("type"), "sym": x.get("sym") or "", "t": _dt(int(x["t"])),
             "amt": float(x.get("amt") or 0), "fee_a": x.get("asset"), "ref": x.get("trade") or None}
            for x in lst if x.get("t")]


async def _cx_sync(uid: int, ex: str, row) -> None:
    """Binance savdo tarixini bazaga: futures income (so'nggi ~85 kun oddiy API, undan eski —
    yil boshigacha asinxron CSV) va spot fill'lari (juftlik kursorlari bilan)."""
    if (uid, ex) in _CX_SYNC_RUN:
        return
    _CX_SYNC_RUN.add((uid, ex))
    try:
        k = _cex_keys(row)
        st = await db.cex_sync_get(uid, ex)
        now = int(time.time() * 1000)
        if ex != "binance":
            await _cx_sync_other(uid, ex, k, st, now)
            return
        if not st.get("cutoff"):
            st["year_from"] = _year_start_ms()
            st["cutoff"] = max(st["year_from"], now - 85 * 86_400_000)
        call = lambda op, a: _cx_call("trade", ex, k, {"op": op, "a": a})
        # 1) futures — oddiy API (cutoff dan hozirgacha, oxirgi sinxdan 1 soat ustma-ust)
        try:
            start = max(st["cutoff"], int(st.get("fut_last") or 0) - 3_600_000)
            rows = await call("inc_raw", {"start": start, "end": now})
            await db.cex_tr_add(uid, ex, _inc_rows(rows or []))
            st["fut_last"] = now
            st.pop("fut_err", None)
        except cex_mod().ApiErr as e:
            if e.code == "auth":
                raise
            st["fut_err"] = _cx_msg(e.text) or e.code
        # 2) futures — yil boshidan cutoff gacha (asinxron yuklab olish, oyiga 5 ta limit)
        asy = st.get("async") or {}
        if st["year_from"] < st["cutoff"] and asy.get("status") not in ("done", "fail"):
            try:
                if not asy.get("id"):
                    if int(asy.get("tries") or 0) >= 2:
                        asy["status"] = "fail"
                    else:
                        r = await call("inc_async_req", {"start": st["year_from"], "end": st["cutoff"] - 1})
                        asy.update({"id": r.get("id"), "status": "pending", "req_at": now,
                                    "tries": int(asy.get("tries") or 0) + 1})
                else:
                    r = await call("inc_async_get", {"id": asy["id"]})
                    if r.get("expired"):
                        asy.update({"id": None, "status": "none"})
                    elif str(r.get("status")).lower() == "completed" and r.get("url"):
                        lst = await call("inc_async_fetch", {"url": r["url"]}) or []
                        lst = [x for x in lst if st["year_from"] <= int(x["t"]) < st["cutoff"]]
                        await db.cex_tr_add(uid, ex, _inc_rows(lst))
                        asy.update({"status": "done", "n": len(lst)})
                    elif now - int(asy.get("req_at") or now) > 2 * 86_400_000:
                        asy.update({"status": "fail", "err": "timeout"})
            except cex_mod().ApiErr as e:
                if e.code == "auth":
                    raise
                asy.update({"status": "fail", "err": _cx_msg(e.text) or e.code})
                log.info("Futures eski tarixi olinmadi (uid=%s): %s", uid, asy["err"])
            st["async"] = asy
        # 3) spot fill'lari
        try:
            sp = st.get("spot") or {}
            bad = set(st.get("spot_bad") or [])
            if now - int(st.get("spot_cands_at") or 0) > 6 * 3_600_000:
                for sy in await call("spot_cands", {}) or []:
                    if sy not in sp and sy not in bad:
                        sp[sy] = None
                st["spot_cands_at"] = now
            for sy in await db.cex_tr_spot_syms(uid, ex):
                sp.setdefault(sy, None)
            todo = {sy: (None if v is None else int(v) + 1) for sy, v in sp.items() if sy not in bad}
            if todo:
                r = await call("spot_sync", {"syms": todo})
                await db.cex_tr_add(uid, ex, [{"key": x["key"], "kind": "spot", "typ": x["side"], "sym": x["sym"],
                                               "t": _dt(int(x["t"])), "qty": x["qty"], "quote": x["quote"],
                                               "fee": x["fee"], "fee_a": x.get("fee_a"), "ref": x.get("oid")}
                                              for x in r.get("rows") or []])
                for sy, last in (r.get("cursors") or {}).items():
                    sp[sy] = last
                for sy in r.get("bad") or []:
                    bad.add(sy)
                    sp.pop(sy, None)
            st["spot"], st["spot_bad"] = sp, sorted(bad)
            st.pop("spot_err", None)
        except cex_mod().ApiErr as e:
            if e.code == "auth":
                raise
            st["spot_err"] = _cx_msg(e.text) or e.code
        st["synced_at"] = int(time.time() * 1000)
        await db.cex_sync_put(uid, ex, st)
    except Exception:
        log.warning("Savdo tarixi sinxronlanmadi (%s uid=%s)", ex, uid, exc_info=True)
    finally:
        _CX_SYNC_RUN.discard((uid, ex))


async def _cx_sync_other(uid: int, ex: str, k: dict, st: dict, now: int) -> None:
    """335: MEXC / Bitget / BingX — bitta relay chaqiruvi (`hist_sync`): birja bergancha tarix
    (odatda ~90 kun, spot ~30 kun), keyin har soat qo'shilib boradi."""
    if not st.get("year_from"):
        st["year_from"] = _year_start_ms()
        st["cutoff"] = st["year_from"]          # asinxron yuklab olish yo'q
    since = max(st["year_from"], int(st.get("fut_last") or 0) - 3_600_000)
    try:
        r = await _cx_call("trade", ex, k, {"op": "hist_sync", "a": {"since": since, "spot_t": st.get("spot_t") or {}}}) or {}
    except cex_mod().ApiErr as e:
        if e.code == "auth":
            raise
        st["fut_err"] = _cx_msg(e.text) or e.code
        st["synced_at"] = now
        await db.cex_sync_put(uid, ex, st)
        return
    await db.cex_tr_add(uid, ex, _inc_rows(r.get("inc") or []))
    await db.cex_tr_add(uid, ex, [{"key": x["key"], "kind": "spot", "typ": x["side"], "sym": x["sym"],
                                   "t": _dt(int(x["t"])), "qty": x["qty"], "quote": x["quote"], "fee": x["fee"],
                                   "fee_a": x.get("fee_a"), "ref": x.get("oid")} for x in r.get("spot") or []])
    st["spot_t"] = r.get("spot_t") or st.get("spot_t") or {}
    st["fut_last"] = now
    st["depth"] = r.get("depth")
    errs = r.get("errs") or []
    if errs:
        st["fut_err"] = "; ".join(errs)[:200]
        log.info("%s tarixi qisman olindi (uid=%s): %s", ex, uid, st["fut_err"])
    else:
        st.pop("fut_err", None)
    st["synced_at"] = int(time.time() * 1000)
    await db.cex_sync_put(uid, ex, st)


def cex_mod():
    import cex
    return cex


def _cx_summary(ev: list) -> dict:
    from datetime import datetime, timezone
    ev = sorted(ev, key=lambda e: e["t"])
    n = len(ev)
    wins = [e["pnl"] for e in ev if e["pnl"] > 0]
    loss = [e["pnl"] for e in ev if e["pnl"] < 0]
    cum, curve, months, syms = 0.0, [], {}, {}
    for e in ev:
        cum += e["pnl"]
        curve.append([e["t"], round(cum, 2)])
        m = datetime.fromtimestamp(e["t"] / 1000, timezone.utc).strftime("%Y-%m")
        months[m] = months.get(m, 0.0) + e["pnl"]
        s = syms.setdefault(e["sym"], [0.0, 0])
        s[0] += e["pnl"]
        s[1] += 1
    if len(curve) > 200:
        step = len(curve) / 200
        curve = [curve[int(i * step)] for i in range(200)] + [curve[-1]]
    return {"n": n, "pnl": round(sum(e["pnl"] for e in ev), 2), "wins": len(wins), "losses": len(loss),
            "wr": (len(wins) / n * 100) if n else 0.0,
            "avg_win": (sum(wins) / len(wins)) if wins else 0.0, "avg_loss": (sum(loss) / len(loss)) if loss else 0.0,
            "pf": (sum(wins) / -sum(loss)) if loss else None,
            "best": max((e["pnl"] for e in ev), default=0.0), "worst": min((e["pnl"] for e in ev), default=0.0),
            "curve": curve, "months": sorted([[k, round(v, 2)] for k, v in months.items()]),
            "syms": sorted([[k, round(v[0], 2), v[1]] for k, v in syms.items()], key=lambda x: -abs(x[1]))[:15]}


def _cx_stats(rows, since_ms: int) -> dict:
    """Saqlangan tarixdan: futures yopilishlari (REALIZED_PNL, 60 s ichidagi fill'lar bitta),
    komissiya/funding; spot — o'rtacha tannarx bo'yicha realizatsiya qilingan PnL."""
    fut, by_trade, fees, funding = [], {}, 0.0, 0.0
    spot_orders = {}
    for r in rows:
        tm = int(r["t"].timestamp() * 1000)
        if r["kind"] == "inc":
            typ, sym, amt = r["typ"], r["sym"] or "", float(r["amt"] or 0)
            if typ == "REALIZED_PNL":
                e = fut[-1] if fut else None
                if not (e and e["sym"] == sym and tm - e["t"] <= 60_000):
                    e = {"sym": sym, "t": tm, "pnl": 0.0, "fee": 0.0, "mkt": "fut"}
                    fut.append(e)
                e["pnl"] += amt
                e["t"] = tm
                if r["ref"]:
                    by_trade[(sym, r["ref"])] = e
            elif typ == "FUNDING_FEE" and tm >= since_ms:
                funding += amt
        elif r["kind"] == "spot":
            key = (r["sym"], r["ref"] or str(tm))
            o = spot_orders.get(key)
            if o is None:
                o = spot_orders[key] = {"sym": r["sym"], "side": r["typ"], "qty": 0.0, "quote": 0.0, "t": tm}
            o["qty"] += float(r["qty"] or 0)
            o["quote"] += float(r["quote"] or 0)
            o["t"] = max(o["t"], tm)
    for r in rows:
        if r["kind"] == "inc" and r["typ"] == "COMMISSION":
            tm = int(r["t"].timestamp() * 1000)
            e = by_trade.get((r["sym"] or "", r["ref"]))
            if e is not None:
                e["fee"] += float(r["amt"] or 0)
            if tm >= since_ms:
                fees += float(r["amt"] or 0)
    spot_ev, held = [], {}
    for o in sorted(spot_orders.values(), key=lambda o: o["t"]):
        h = held.setdefault(o["sym"], [0.0, 0.0])
        if o["side"] == "buy":
            h[0] += o["qty"]
            h[1] += o["quote"]
        elif o["qty"] > 0 and h[0] > 0:
            sold = min(o["qty"], h[0])
            avg = h[1] / h[0]
            pnl = o["quote"] * (sold / o["qty"]) - avg * sold
            h[0] -= sold
            h[1] -= avg * sold
            spot_ev.append({"sym": o["sym"], "t": o["t"], "pnl": pnl, "mkt": "spot"})
    fut_p = [e for e in fut if e["t"] >= since_ms]
    spot_p = [e for e in spot_ev if e["t"] >= since_ms]
    f = _cx_summary(fut_p)
    f.update({"fees": round(fees, 2), "funding": round(funding, 2), "net": round(f["pnl"] + fees + funding, 2)})
    sp = _cx_summary(spot_p)
    al = _cx_summary(fut_p + spot_p)
    al["net"] = round(al["pnl"] + fees + funding, 2)
    return {"all": al, "fut": f, "spot": sp,
            "first": int(rows[0]["t"].timestamp() * 1000) if rows else None}


async def api_cexstats(request):
    """334: birja statistikasi — davr: 30d | 90d | ytd | all. Kerak bo'lsa fonda sinxronizatsiya."""
    import cex
    body, uid = await _body(request)
    ex = str(body.get("ex") or "")
    if ex not in cex.EXCHANGES:
        raise web.HTTPBadRequest()
    per = body.get("per") if body.get("per") in ("30d", "90d", "ytd", "all") else "ytd"
    row = next((r for r in await db.cex_list(uid) if r["exchange"] == ex), None)
    if row is None:
        raise web.HTTPNotFound()
    st = await db.cex_sync_get(uid, ex)
    now = int(time.time() * 1000)
    if (not st.get("synced_at") or now - int(st["synced_at"]) > _CX_SYNC_GAP * 1000
            or (bool(body.get("fresh")) and now - int(st["synced_at"]) > 60_000)) and (uid, ex) not in _CX_SYNC_RUN:
        t = asyncio.get_running_loop().create_task(_cx_sync(uid, ex, row))
        _CEX_BG.add(t)
        t.add_done_callback(_CEX_BG.discard)
    since = {"30d": now - 30 * 86_400_000, "90d": now - 90 * 86_400_000,
             "ytd": _year_start_ms(), "all": 0}[per]
    rows = await db.cex_tr_rows(uid, ex)
    res = _cx_stats(rows, since)
    asy = st.get("async") or {}
    res.update({"supported": True, "per": per, "since": since,
                "sync": {"running": (uid, ex) in _CX_SYNC_RUN, "at": st.get("synced_at"),
                         "old": asy.get("status") or ("done" if st.get("year_from") and st.get("year_from") >= st.get("cutoff", 0) else "none"),
                         "old_err": asy.get("err"), "year_from": st.get("year_from"), "cutoff": st.get("cutoff"),
                         "err": st.get("fut_err") or st.get("spot_err"), "depth": st.get("depth")}})
    return web.json_response(res, headers=NO_CACHE)


_TRADE_ARGS = {"mkt", "sym", "side", "type", "price", "quote", "qty", "margin", "lev",
               "tp", "sl", "frac", "ps", "id", "algo"}


async def api_cextrade(request):
    """330: ilovadan savdo (hozircha Binance Spot + Futures). O'qish amallari
    (info/open) — jurnalsiz; o'zgartiruvchilar `cex_orders`ga yoziladi."""
    import cex
    body, uid = await _body(request)
    ex, op = str(body.get("ex") or ""), str(body.get("op") or "")
    a = body.get("a") or {}
    if ex not in cex.TRADE_EX or op not in cex.TRADE_OPS or not isinstance(a, dict) \
            or not set(a) <= _TRADE_ARGS or len(json.dumps(a)) > 1000:
        raise web.HTTPBadRequest()
    if not _act_allowed(uid):
        raise web.HTTPTooManyRequests()
    row = next((r for r in await db.cex_list(uid) if r["exchange"] == ex), None)
    if row is None:
        raise web.HTTPNotFound()
    write = op not in cex.TRADE_READ
    try:
        r = await _cx_call("trade", ex, _cex_keys(row), {"op": op, "a": a})
        res = {"ok": True, "r": r}
    except cex.ApiErr as e:
        res = {"ok": False, "err": e.code, "msg": _cx_msg(e.text)}
    except Exception:
        log.warning("Savdo amali xato (%s %s)", ex, op, exc_info=True)
        res = {"ok": False, "err": "api"}
    if write:
        log.info("Savdo: %s %s uid=%s %s → %s", ex, op, uid, json.dumps(a)[:200],
                 "ok" if res["ok"] else f"{res.get('err')} {res.get('msg', '')}")
        try:
            await db.cex_order_log(uid, ex, op, a, res["ok"], res.get("r") if res["ok"] else res)
        except Exception:
            log.warning("Savdo jurnali yozilmadi", exc_info=True)
        _CEX_CACHE.pop((uid, ex), None)
        _CEX_TR.pop((uid, ex), None)
    return web.json_response(res, headers=NO_CACHE)


async def api_cexdel(request):
    import cex
    body, uid = await _body(request)
    ex = str(body.get("ex") or "")
    if ex not in cex.EXCHANGES:
        raise web.HTTPBadRequest()
    ok = await db.cex_del(uid, ex)
    _CEX_CACHE.pop((uid, ex), None)
    _CEX_REC.pop((uid, ex), None)
    _CEX_TR.pop((uid, ex), None)
    return web.json_response({"ok": ok}, headers=NO_CACHE)


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
        web.get(r"/coins/{c:[a-z0-9]{1,12}}.svg", coin_svg),
        web.post("/api/app/me", api_me),
        web.post("/api/app/open", api_open),
        web.post("/api/app/act", api_act),
        web.post("/api/app/spark", api_spark),
        web.post("/api/app/candles", api_candles),
        web.post("/api/app/dfcandles", api_dfcandles),
        web.post("/api/app/pairs", api_pairs),
        web.post("/api/app/sighist", api_sighist),
        web.post("/api/app/top", api_top),
        web.post("/api/app/diptop", api_diptop),
        web.post("/api/app/diptasks", api_diptasks),
        web.post("/api/app/hstat", api_hstat),
        web.post("/api/app/period", api_period),
        web.post("/api/app/group", api_group),
        web.post("/api/app/tour", api_tour),
        web.post("/api/app/tspark", api_tspark),
        web.post("/api/app/cex", api_cex),
        web.post("/api/app/cexadd", api_cexadd),
        web.post("/api/app/cexdel", api_cexdel),
        web.post("/api/app/cexhist", api_cexhist),
        web.post("/api/app/cextrades", api_cextrades),
        web.post("/api/app/cextrade", api_cextrade),
        web.post("/api/app/cexstats", api_cexstats),
    ]


T = {
    "uz": {
        "bot": "Bot", "open": "Ochiq signallar", "open_sub": "Jonli boshqaruv",
        "deposit": "Depozit", "spot": "Spot", "fut": "Futures", "stats": "Statistika",
        "stats_sub": "Natijalar", "tour": "Turnir", "tour_sub": "Oylik musobaqa",
        "df": "Dip Funded", "df_sub": "Prop hisoblar", "journals": "Jurnallarim", "lang": "Til", "back_bot": "Botga qaytish", "ui_lang": "Ilova tili",
        "top": "Top", "top_sub": "Reyting", "groups": "Guruhlar", "channels": "Kanallar",
        "top_empty": "Hozircha reytingda hech kim yo'q", "sig_w": "signal", "welcome": "Xush kelibsiz",
        "t_live": "Davom etmoqda", "t_soon": "Boshlanishiga", "t_df_sub": "Sovrinli turnir",
        "t_players": "qatnashchi", "t_place": "o'rin", "t_join": "Qatnashish", "t_board": "Reyting",
        "t_own": "TC turniri", "t_empty": "Hali qatnashchi yo'q",
        "not_public": "Sahifa ochiq emas", "subscribe": "Obuna bo'lish", "join": "Qo'shilish",
        "equity": "Dinamika", "position": "Pozitsiya",
        "hidden_note": "Juftliklar — faqat a'zolarga", "no_closed": "Hali yopilgan signal yo'q",
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
        "df_unav": "Dip Funded hozir javob bermayapti", "df_balance": "Balans",
        "df_free": "Bo'sh", "df_daily": "Kunlik limit", "df_maxdd": "Maks. zarar", "df_target": "Maqsad",
        "df_days": "Savdo kunlari", "df_pos": "Pozitsiyalar", "df_orders": "Limit buyruqlar",
        "df_term": "Savdo terminali", "df_avg": "O'rtacha narx", "df_market": "Market", "df_limit_p": "Limit narx", "df_amount": "Summa, USDT", "df_sl_opt": "SL (ixtiyoriy)", "df_tp_opt": "TP (ixtiyoriy)", "df_qty": "Miqdor", "df_tpsl_hint": "Bo'sh qoldirilsa — olib tashlanadi", "df_pick": "Juftlikni tanlang", "df_pos1": "Pozitsiya", "df_mark": "Joriy narx", "df_value": "Qiymat", "df_no_pos": "Bu juftlikda pozitsiya yo'q — BUY bilan oching", "df_trades": "So'nggi savdolar", "pp_typed": "shu nom bilan", "pp_choose": "Juftlikni tanlang", "df_share": "Hisobdagi ulush", "df_equity2": "Equity", "nws_prep": "Ulashish tayyorlanmoqda…", "wallet": "Birja", "w_soon": "Tez orada", "w_sub": "Birja", "w_txt": "DIP, USDT va Dip Funded balanslaringiz bir joyda — bo'lim tayyorlanmoqda.", "df_inbot": "Botda boshqarish",
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
        "dip_out": "Tokenlarni chiqarish", "dip_out_lock": "{min} DIP dan ochiladi · yana {n} DIP", "dip_out_pend": "So'rov ko'rib chiqilmoqda: {n} DIP", "dip_to_df": "Dip Funded hisobiga", "dip_to_df_s": "Komissiyasiz · darhol o'tadi", "dip_to_usdt": "USDT qilib hamyonga", "dip_fee_s": "Komissiya {p}% ({n} DIP)", "dip_get": "Siz olasiz", "dip_net": "Tarmoq: faqat BEP20 (BNB Smart Chain)", "dip_addr": "USDT hamyon manzili", "dip_send": "So'rov yuborish", "dip_move": "O'tkazish", "dip_to_other": "Kimgadir o'tkazish", "dip_to_ph": "Dip Funded ID yoki @username", "dip_to_ask": "{name} ({id}) ga {n} DIP o'tkazilsinmi?", "dip_nouser": "Bunday foydalanuvchi topilmadi", "dip": "DIP", "dip_rank": "Reyting", "dip_rank_sub": "Eng ko'p DIP yig'ganlar", "dip_refs": "taklif", "dip_you": "Siz", "dip_empty": "Hali hech kim DIP yig'magan", "dip_invite": "Do'st taklif qilish", "earn_title": "DIP Earn", "earn_sub": "Vazifalarni bajaring — har biri uchun DIP oling. Obuna bot orqali tekshiriladi va 3, 7 kundan keyin qayta tekshiriladi: chiqib ketsangiz DIP qaytarib olinadi.", "earn_done": "Bajarildi", "earn_check": "Tekshirish", "earn_go": "Bajarish", "earn_people": "kishi", "earn_verified": "tekshiriladi", "earn_empty": "Hozircha vazifalar yo'q", "earn_apply_btn": "Hamkor bo'lish", "earn_apply_title": "Hamkor bo'lish", "earn_apply_sub": "Kanalingiz, guruhingiz yoki botingiz barcha foydalanuvchilarga DIP vazifasi sifatida ko'rinadi.", "earn_price": "Joylashtirish narxi", "earn_once": "1 oy", "earn_aud": "Auditoriya (jonli raqamlar)", "earn_a_users": "Foydalanuvchilar", "earn_a_m30": "30 kunda faol", "earn_a_d7": "7 kunda faol", "earn_a_d1": "Bugun faol", "earn_a_groups": "Signal guruhlari", "earn_a_dip": "DIP yig'uvchilar", "earn_f1": "Hammasi jonli auditoriya — botlar emas, Telegram'dagi haqiqiy treyderlar", "earn_f2": "DIP faqat obuna bo'lgandan keyin beriladi — bot har birini tekshiradi", "earn_f3": "Auditoriya: kripto va forex treyderlar, signal guruhlari egalari va a'zolari", "earn_f4": "Vazifa DIP bo'limida 1 oy davomida barcha foydalanuvchilarga ko'rinadi", "earn_k_channel": "Kanal", "earn_k_group": "Guruh", "earn_note": "Izoh yoki aloqa (ixtiyoriy)", "earn_send": "Ariza yuborish", "earn_need": "Manzilni kiriting", "earn_def_channel": "Kanalga obuna bo'ling va obunani saqlang", "earn_def_group": "Guruhga qo'shiling", "earn_def_bot": "Botni oching va /start bosing", "earn_def_link": "Saytga kiring va tanishib chiqing", "t_rpnl": "Realized PnL", "t_margin": "Marja", "t_notional": "Pozitsiya hajmi", "t_qty": "Miqdor", "t_liq": "Likvidatsiya", "t_closed": "Yopilgan qism", "t_opened": "Ochilgan", "t_risk": "SL'da", "t_reward": "Keyingi TP'da", "t_rr": "R:R", "t_nosize": "Summa kiritilmagan — natija faqat % da. $ uchun «Hajm»ni kiriting", "t_total": "Jami natija", "t_tab_pos": "Pozitsiya", "t_tab_ord": "Buyurtmalar", "t_more": "Batafsil", "t_vol": "Hajm (USDT)", "t_entry_px": "Kirish narxi", "t_now": "Joriy narx", "t_pnl": "P&L (USDT)", "t_roi": "ROI", "t_no_ord": "Kutilayotgan buyurtma yo'q", "t_lim_add": "Limit (qo'shimcha kirish)", "t_entry_ord": "Limit kirish", "t_tab_hist": "Tarix", "t_created": "Signal yaratildi", "t_open_ev": "Pozitsiya ochildi", "t_no_hist": "Hozircha hodisa yo'q", "t_share": "Ulashish", "dip_bal": "DIP balans", "dip_per": "Har bir taklif uchun +{n} DIP", "dip_note": "1000 DIP = $10 · Dip Funded hisobiga yoki USDT qilib hamyonga chiqarish mumkin",
        "home": "Bosh", "signals": "Signallar", "profile": "Profil",
        "none": "Ochiq signal yo'q", "entry": "Kirish", "stop": "Stop", "price": "Narx",
        "be": "BE", "close": "Yopish", "cancel": "Bekor qilish", "newstop": "Yangi stop narxi",
        "confirm_close": "Pozitsiyani to'liq yopasizmi?", "confirm_cancel": "Limitni bekor qilasizmi?",
        "confirm_pc": "{p}% qismini yopasizmi?", "wait": "Bajarilmoqda…",
        "nows": "Sizda hali jurnal yo'q. Botda /start bosing.",
        "personal": "Shaxsiy jurnal",
        "channel": "Kanal", "group": "Guruh", "slow": "Bot hozir band — birozdan keyin qayta urinib ko'ring.", "rc_share": "Ulashish", "rc_post": "Postni ochish",
        "pnl_total": "Ochiq natija", "open_n": "{n} ta ochiq",
        "invested": "Summa", "limit": "Limit",
        "save": "Saqlash", "spot_dep": "Spot depozit", "fut_dep": "Futures depozit",
        "best": "Eng yaxshi pozitsiya", "busy": "Band summa",
    },
    "ru": {
        "bot": "Бот", "open": "Открытые сигналы", "open_sub": "Живое управление",
        "deposit": "Депозит", "spot": "Спот", "fut": "Фьючерсы", "stats": "Статистика",
        "stats_sub": "Результаты", "tour": "Турнир", "tour_sub": "Ежемесячный конкурс",
        "df": "Dip Funded", "df_sub": "Проп-счета", "journals": "Мои журналы", "lang": "Язык", "back_bot": "Вернуться в бот", "ui_lang": "Язык приложения",
        "top": "Топ", "top_sub": "Рейтинг", "groups": "Группы", "channels": "Каналы",
        "top_empty": "В рейтинге пока никого", "sig_w": "сигн.", "welcome": "Добро пожаловать",
        "t_live": "Идёт", "t_soon": "До начала", "t_df_sub": "Турнир с призами",
        "t_players": "участн.", "t_place": "место", "t_join": "Участвовать", "t_board": "Рейтинг",
        "t_own": "Турнир TC", "t_empty": "Пока нет участников",
        "not_public": "Страница не открыта", "subscribe": "Подписаться", "join": "Вступить",
        "equity": "Динамика", "position": "Позиция",
        "hidden_note": "Пары — только участникам", "no_closed": "Пока нет закрытых сигналов",
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
        "df_unav": "Dip Funded сейчас не отвечает", "df_balance": "Баланс",
        "df_free": "Свободно", "df_daily": "Дневной лимит", "df_maxdd": "Макс. просадка", "df_target": "Цель",
        "df_days": "Торговые дни", "df_pos": "Позиции", "df_orders": "Лимитные ордера",
        "df_term": "Терминал", "df_avg": "Средняя цена", "df_market": "Рынок", "df_limit_p": "Лимит-цена", "df_amount": "Сумма, USDT", "df_sl_opt": "SL (необяз.)", "df_tp_opt": "TP (необяз.)", "df_qty": "Количество", "df_tpsl_hint": "Пустое поле — удалить", "df_pick": "Выберите пару", "df_pos1": "Позиция", "df_mark": "Текущая цена", "df_value": "Стоимость", "df_no_pos": "По этой паре позиции нет — откройте через BUY", "df_trades": "Последние сделки", "pp_typed": "как введено", "pp_choose": "Выберите пару", "df_share": "Доля счёта", "df_equity2": "Equity", "nws_prep": "Готовим к отправке…", "wallet": "Биржа", "w_soon": "Скоро", "w_sub": "Биржа", "w_txt": "DIP, USDT и балансы Dip Funded в одном месте — раздел готовится.", "df_inbot": "Управлять в боте",
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
        "dip_out": "Вывести токены", "dip_out_lock": "Доступно от {min} DIP · ещё {n} DIP", "dip_out_pend": "Заявка рассматривается: {n} DIP", "dip_to_df": "На счёт Dip Funded", "dip_to_df_s": "Без комиссии · сразу", "dip_to_usdt": "В USDT на кошелёк", "dip_fee_s": "Комиссия {p}% ({n} DIP)", "dip_get": "Вы получите", "dip_net": "Сеть: только BEP20 (BNB Smart Chain)", "dip_addr": "Адрес USDT-кошелька", "dip_send": "Отправить заявку", "dip_move": "Перевести", "dip_to_other": "Перевести другому", "dip_to_ph": "ID Dip Funded или @username", "dip_to_ask": "Перевести {n} DIP пользователю {name} ({id})?", "dip_nouser": "Пользователь не найден", "dip": "DIP", "dip_rank": "Рейтинг", "dip_rank_sub": "Больше всего DIP", "dip_refs": "пригл.", "dip_you": "Вы", "dip_empty": "Пока никто не собрал DIP", "dip_invite": "Пригласить друга", "earn_title": "DIP Earn", "earn_sub": "Выполняйте задания — за каждое DIP. Подписка проверяется ботом и повторно через 3 и 7 дней: при отписке DIP списываются.", "earn_done": "Выполнено", "earn_check": "Проверить", "earn_go": "Выполнить", "earn_people": "чел.", "earn_verified": "с проверкой", "earn_empty": "Пока заданий нет", "earn_apply_btn": "Стать партнёром", "earn_apply_title": "Стать партнёром", "earn_apply_sub": "Ваш канал, группа или бот будет виден всем пользователям как DIP-задание.", "earn_price": "Цена размещения", "earn_once": "1 месяц", "earn_aud": "Аудитория (живые цифры)", "earn_a_users": "Пользователи", "earn_a_m30": "Активны 30 дн.", "earn_a_d7": "Активны 7 дн.", "earn_a_d1": "Активны сегодня", "earn_a_groups": "Сигнальные группы", "earn_a_dip": "Собирают DIP", "earn_f1": "Только живая аудитория — не боты, реальные трейдеры в Telegram", "earn_f2": "DIP даются только после подписки — бот проверяет каждого", "earn_f3": "Аудитория: крипто- и форекс-трейдеры, владельцы и участники сигнальных групп", "earn_f4": "Задание видно всем в разделе DIP в течение 1 месяца", "earn_k_channel": "Канал", "earn_k_group": "Группа", "earn_note": "Комментарий или контакт (необяз.)", "earn_send": "Отправить заявку", "earn_need": "Укажите адрес", "earn_def_channel": "Подпишитесь на канал и оставайтесь подписаны", "earn_def_group": "Вступите в группу", "earn_def_bot": "Откройте бота и нажмите /start", "earn_def_link": "Перейдите на сайт и ознакомьтесь", "t_rpnl": "Реализ. PnL", "t_margin": "Маржа", "t_notional": "Размер позиции", "t_qty": "Кол-во", "t_liq": "Ликвидация", "t_closed": "Закрыто", "t_opened": "Открыта", "t_risk": "На SL", "t_reward": "На след. TP", "t_rr": "R:R", "t_nosize": "Сумма не указана — результат только в %. Для $ укажите «Объём»", "t_total": "Итог", "t_tab_pos": "Позиция", "t_tab_ord": "Ордера", "t_more": "Подробнее", "t_vol": "Объём (USDT)", "t_entry_px": "Цена входа", "t_now": "Текущая цена", "t_pnl": "P&L (USDT)", "t_roi": "ROI", "t_no_ord": "Нет ожидающих ордеров", "t_lim_add": "Лимит (доп. вход)", "t_entry_ord": "Лимитный вход", "t_tab_hist": "История", "t_created": "Сигнал создан", "t_open_ev": "Позиция открыта", "t_no_hist": "Пока событий нет", "t_share": "Поделиться", "dip_bal": "Баланс DIP", "dip_per": "+{n} DIP за каждое приглашение", "dip_note": "1000 DIP = $10 · можно вывести на счёт Dip Funded или в USDT на кошелёк",
        "home": "Главная", "signals": "Сигналы", "profile": "Профиль",
        "none": "Нет открытых сигналов", "entry": "Вход", "stop": "Стоп", "price": "Цена",
        "be": "БУ", "close": "Закрыть", "cancel": "Отменить", "newstop": "Новая цена стопа",
        "confirm_close": "Закрыть позицию полностью?", "confirm_cancel": "Отменить лимит?",
        "confirm_pc": "Закрыть {p}%?", "wait": "Выполняется…",
        "nows": "У вас ещё нет журнала. Нажмите /start в боте.",
        "personal": "Личный журнал",
        "channel": "Канал", "group": "Группа", "slow": "Бот занят — попробуйте чуть позже.", "rc_share": "Поделиться", "rc_post": "Открыть пост",
        "pnl_total": "Открытый результат", "open_n": "{n} открыто",
        "invested": "Сумма", "limit": "Лимит",
        "save": "Сохранить", "spot_dep": "Спот депозит", "fut_dep": "Фьючерс депозит",
        "best": "Лучшая позиция", "busy": "В позициях",
    },
    "en": {
        "bot": "Bot", "open": "Open signals", "open_sub": "Live controls",
        "deposit": "Deposit", "spot": "Spot", "fut": "Futures", "stats": "Statistics",
        "stats_sub": "Results", "tour": "Tournament", "tour_sub": "Monthly contest",
        "df": "Dip Funded", "df_sub": "Prop accounts", "journals": "My journals", "lang": "Language", "back_bot": "Back to bot", "ui_lang": "App language",
        "top": "Top", "top_sub": "Ranking", "groups": "Groups", "channels": "Channels",
        "top_empty": "Nobody in the ranking yet", "sig_w": "signals", "welcome": "Welcome",
        "t_live": "Live", "t_soon": "Starts in", "t_df_sub": "Prize tournament",
        "t_players": "players", "t_place": "place", "t_join": "Join", "t_board": "Leaderboard",
        "t_own": "TC tournament", "t_empty": "No players yet",
        "not_public": "Page is not public", "subscribe": "Subscribe", "join": "Join",
        "equity": "Equity", "position": "Position",
        "hidden_note": "Pairs — members only", "no_closed": "No closed signals yet",
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
        "df_unav": "Dip Funded is not responding", "df_balance": "Balance",
        "df_free": "Free", "df_daily": "Daily limit", "df_maxdd": "Max loss", "df_target": "Target",
        "df_days": "Trading days", "df_pos": "Positions", "df_orders": "Limit orders",
        "df_term": "Trading terminal", "df_avg": "Avg price", "df_market": "Market", "df_limit_p": "Limit price", "df_amount": "Amount, USDT", "df_sl_opt": "SL (optional)", "df_tp_opt": "TP (optional)", "df_qty": "Quantity", "df_tpsl_hint": "Leave empty to remove", "df_pick": "Choose a pair", "df_pos1": "Position", "df_mark": "Mark price", "df_value": "Value", "df_no_pos": "No position in this pair — open one with BUY", "df_trades": "Recent trades", "pp_typed": "as typed", "pp_choose": "Choose a pair", "df_share": "Share of account", "df_equity2": "Equity", "nws_prep": "Preparing to share…", "wallet": "Exchange", "w_soon": "Coming soon", "w_sub": "Exchange", "w_txt": "Your DIP, USDT and Dip Funded balances in one place — this section is on its way.", "df_inbot": "Manage in bot",
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
        "dip_out": "Withdraw tokens", "dip_out_lock": "Unlocks at {min} DIP · {n} DIP to go", "dip_out_pend": "Request under review: {n} DIP", "dip_to_df": "To Dip Funded account", "dip_to_df_s": "No fee · instant", "dip_to_usdt": "As USDT to a wallet", "dip_fee_s": "Fee {p}% ({n} DIP)", "dip_get": "You receive", "dip_net": "Network: BEP20 (BNB Smart Chain) only", "dip_addr": "USDT wallet address", "dip_send": "Send request", "dip_move": "Transfer", "dip_to_other": "Send to someone", "dip_to_ph": "Dip Funded ID or @username", "dip_to_ask": "Send {n} DIP to {name} ({id})?", "dip_nouser": "User not found", "dip": "DIP", "dip_rank": "Ranking", "dip_rank_sub": "Most DIP collected", "dip_refs": "invites", "dip_you": "You", "dip_empty": "No one has collected DIP yet", "dip_invite": "Invite a friend", "earn_title": "DIP Earn", "earn_sub": "Complete tasks — earn DIP for each. Subscriptions are checked by the bot and again after 3 and 7 days: leave and the DIP is taken back.", "earn_done": "Done", "earn_check": "Check", "earn_go": "Start", "earn_people": "people", "earn_verified": "verified", "earn_empty": "No tasks yet", "earn_apply_btn": "Become a partner", "earn_apply_title": "Become a partner", "earn_apply_sub": "Your channel, group or bot is shown to every user as a DIP task.", "earn_price": "Listing price", "earn_once": "1 month", "earn_aud": "Audience (live numbers)", "earn_a_users": "Users", "earn_a_m30": "Active 30d", "earn_a_d7": "Active 7d", "earn_a_d1": "Active today", "earn_a_groups": "Signal groups", "earn_a_dip": "DIP collectors", "earn_f1": "100% live audience — not bots, real traders on Telegram", "earn_f2": "DIP is given only after subscribing — the bot checks everyone", "earn_f3": "Audience: crypto & forex traders, signal group owners and members", "earn_f4": "The task is visible to everyone in the DIP section for 1 month", "earn_k_channel": "Channel", "earn_k_group": "Group", "earn_note": "Note or contact (optional)", "earn_send": "Send application", "earn_need": "Enter the address", "earn_def_channel": "Subscribe to the channel and stay subscribed", "earn_def_group": "Join the group", "earn_def_bot": "Open the bot and press /start", "earn_def_link": "Visit the website and explore it", "t_rpnl": "Realized PnL", "t_margin": "Margin", "t_notional": "Position size", "t_qty": "Qty", "t_liq": "Liquidation", "t_closed": "Closed part", "t_opened": "Opened", "t_risk": "At SL", "t_reward": "At next TP", "t_rr": "R:R", "t_nosize": "No amount set — result in % only. Set «Size» for $", "t_total": "Total", "t_tab_pos": "Position", "t_tab_ord": "Orders", "t_more": "Details", "t_vol": "Size (USDT)", "t_entry_px": "Entry price", "t_now": "Last price", "t_pnl": "P&L (USDT)", "t_roi": "ROI", "t_no_ord": "No pending orders", "t_lim_add": "Limit (add entry)", "t_entry_ord": "Limit entry", "t_tab_hist": "History", "t_created": "Signal created", "t_open_ev": "Position opened", "t_no_hist": "No events yet", "t_share": "Share", "dip_bal": "DIP balance", "dip_per": "+{n} DIP per invite", "dip_note": "1000 DIP = $10 · withdraw to Dip Funded or as USDT to a wallet",
        "home": "Home", "signals": "Signals", "profile": "Profile",
        "none": "No open signals", "entry": "Entry", "stop": "Stop", "price": "Price",
        "be": "BE", "close": "Close", "cancel": "Cancel", "newstop": "New stop price",
        "confirm_close": "Close the whole position?", "confirm_cancel": "Cancel the limit order?",
        "confirm_pc": "Close {p}%?", "wait": "Working…",
        "nows": "No journal yet. Press /start in the bot.",
        "personal": "Personal journal",
        "channel": "Channel", "group": "Group", "slow": "Bot is busy — try again shortly.", "rc_share": "Share", "rc_post": "Open post",
        "pnl_total": "Open result", "open_n": "{n} open",
        "invested": "Size", "limit": "Limit",
        "save": "Save", "spot_dep": "Spot deposit", "fut_dep": "Futures deposit",
        "best": "Best position", "busy": "In positions",
    },
}


# 324: Wallet — birja hisoblari
T["uz"].update({
    "cx_st_depth": "{e} tarixni faqat so'nggi ~90 kun (spot ~30 kun) beradi — undan keyingi savdolar har soat saqlanib boradi va yillik statistika to'lib boradi.",
    "cx_tr_cnt": "{n} ta savdo", "cx_margin": "Marja",
    "cx_pos_open": "{n} ta ochiq", "cx_st_ytd": "Yil boshidan", "cx_acc": "Hisob", "cx_assets_n": "aktiv", "cx_no_pos": "Ochiq pozitsiya yo'q", "cx_drag": "TP va SL chiziqlarini grafikda surib o'zgartirish mumkin.", "cx_per_ytd": "{y} yil boshidan", "cx_st_all": "Hammasi", "cx_st_net": "Sof natija", "cx_st_pf": "Profit factor", "cx_st_avg": "O'rtacha foyda / zarar", "cx_st_best": "Eng yaxshi savdo", "cx_st_worst": "Eng yomon savdo", "cx_st_months": "Oylar bo'yicha", "cx_st_syms": "Juftliklar bo'yicha", "cx_st_sync": "Savdo tarixi Binance'dan yuklanmoqda…", "cx_st_old_pending": "{y} yil boshidan to'liq futures tarixi Binance'dan yuklab olinmoqda — bir necha daqiqadan bir necha soatgacha. Hozircha so'nggi ~3 oy ko'rinadi.", "cx_st_old_fail": "{y} yil boshidagi eski futures tarixi olinmadi — so'nggi ~3 oy ko'rsatilmoqda. {e}", "cx_st_only": "Statistika hozircha faqat Binance uchun.", "cx_st_empty": "Bu davrda yopilgan savdo yo'q", "cx_st_synced": "Yangilangan", "cx_st_from": "tarix",
    "tr_trade": "savdo", "tr_enable": "Bot ichidan savdo qilish uchun Binance kalitida «Enable Spot & Margin Trading» va/yoki «Enable Futures» ruxsatini yoqing (pul yechish — yoqilmaydi), so'ng «Kalitni yangilash».", "tr_noperm_spot": "Kalitda Spot savdo ruxsati yo'q — Binance'da «Enable Spot & Margin Trading»ni yoqing.", "tr_noperm_fut": "Kalitda Futures ruxsati yo'q — Binance'da «Enable Futures»ni yoqing.", "tr_lev": "Leveraj", "tr_margin": "Marja, USDT", "tr_qty": "Miqdor", "tr_size": "Pozitsiya", "tr_open": "Ochiq orderlar", "tr_need_amt": "Summani kiriting", "tr_confirm": "Real order yuboriladi. Tasdiqlaysizmi?", "tr_sent": "Order yuborildi", "tr_cancel_q": "Orderni bekor qilasizmi?", "tr_cancelled": "Order bekor qilindi", "tr_close": "Yopish", "tr_close_txt": "Pozitsiyaning qancha qismi bozor narxida yopilsin?", "tr_close_q": "{s} pozitsiyasining {p}% bozor narxida yopiladi. Tasdiqlaysizmi?", "tr_closed": "Pozitsiya yopildi", "tr_tpsl_ok": "TP/SL saqlandi", "cx_e_noperm": "Kalitda bu savdo ruxsati yo'q", "cx_e_small": "Summa juda kichik (birja minimumidan kam)", "cx_e_nopos": "Bu juftlikda ochiq pozitsiya yo'q", "cx_e_noex": "Bu birjada savdo hozircha yo'q",
    "cx_trades": "Savdolar tarixi", "cx_tr_load": "Binance'dan yuklanmoqda — 10–20 soniya…", "cx_tr_only": "Savdolar tarixi hozircha faqat Binance uchun.", "cx_tr_n": "Savdolar", "cx_tr_fee": "Komissiya", "cx_tr_days": "oxirgi {n} kun", "cx_tr_none": "Savdolar topilmadi", "cx_tr_orders": "ta order", "cx_tr_spot_note": "hozirgi va oxirgi 30 kundagi coinlar bo'yicha", "cx_tr_refresh": "Yangilash",
    "cx_hist": "Balans tarixi", "cx_hist_empty": "Tarix to'planmoqda — balans har soat yozib boriladi", "cx_dn": "{n} kun",
    "loading": "Yuklanmoqda…", "cx_sub": "Birja hisoblaringiz bir joyda", "cx_total": "Umumiy balans",
    "cx_n": "ta birja", "cx_mine": "Ulangan birjalar", "cx_connect": "Birjani ulash", "cx_more": "Yana ulash",
    "cx_intro": "Birja hisobingizni ulang — balans, aktivlar va ochiq fyuchers pozitsiyalaringiz shu yerda ko'rinadi.",
    "cx_ro": "Faqat o'qish kaliti", "cx_link": "Ulash", "cx_pos_n": "pozitsiya", "cx_pos": "Ochiq pozitsiyalar",
    "cx_assets": "Spot aktivlar", "cx_entry": "Kirish", "cx_empty": "Hisobda aktiv yoki pozitsiya yo'q.",
    "cx_rekey": "Kalitni yangilash", "cx_del": "Uzish", "cx_del_q": "Birja hisobini uzasizmi? Kalit bazadan o'chiriladi.",
    "cx_deleted": "Hisob uzildi, kalit o'chirildi", "cx_upd": "Yangilanmoqda…",
    "cx_how": "Birjada yangi API kalit yarating: FAQAT «O'qish» (Read-only) ruxsati, IP cheklovi — yo'q (Unrestricted). Binance'da kalit turi — «System generated». Bot ichidan savdo uchun — «Spot & Margin Trading» va «Futures» ruxsatlarini ham yoqing. Pul yechish ruxsatini HECH QACHON yoqmang. Kalitlar shifrlangan holda saqlanadi.",
    "cx_fill": "Barcha maydonlarni to'ldiring", "cx_check": "Tekshirilmoqda…", "cx_ok": "Birja hisobi ulandi ✅",
    "cx_safe": "Bot pul yecha olmaydi — pul yechish ruxsati bor kalit qabul qilinmaydi. Savdo faqat siz tasdiqlagan orderlar bilan. Kalitlar shifrlangan, istalgan payt uzishingiz mumkin.",
    "cx_e_auth": "Birja kalitni qabul qilmadi. Tekshiring: IP cheklovi o'chirilgan (Unrestricted), kalit turi «System generated» (HMAC), API Key va Secret to'liq nusxalangan", "cx_e_withdraw": "Bu kalitda pul yechish ruxsati bor — xavfsizlik uchun qabul qilinmaydi. Faqat o'qish kalitini yarating.",
    "cx_e_geo": "Birja server hududidan so'rovni blokladi — tez orada tuzatiladi", "cx_e_net": "Birja javob bermadi, keyinroq urinib ko'ring",
    "cx_e_api": "Birjadan ma'lumot olinmadi", "cx_e_bad": "Kalit formati noto'g'ri", "cx_e_reconnect": "Kalitni qayta ulang",
    "cx_e_rate": "Juda ko'p urinish — bir daqiqadan keyin", "cx_e_perm": "Kalitda o'qish ruxsati yo'q",
})
T["ru"].update({
    "cx_st_depth": "{e} отдаёт историю только за последние ~90 дней (спот ~30 дней) — дальше сделки сохраняются каждый час, и годовая статистика будет накапливаться.",
    "cx_tr_cnt": "сделок: {n}", "cx_margin": "Маржа",
    "cx_pos_open": "{n} открыто", "cx_st_ytd": "С начала года", "cx_acc": "Счёт", "cx_assets_n": "активов", "cx_no_pos": "Нет открытых позиций", "cx_drag": "Линии TP и SL можно двигать прямо на графике.", "cx_per_ytd": "С начала {y}", "cx_st_all": "Всё", "cx_st_net": "Чистый результат", "cx_st_pf": "Profit factor", "cx_st_avg": "Средняя прибыль / убыток", "cx_st_best": "Лучшая сделка", "cx_st_worst": "Худшая сделка", "cx_st_months": "По месяцам", "cx_st_syms": "По парам", "cx_st_sync": "Загружаем историю сделок с Binance…", "cx_st_old_pending": "Полная история фьючерсов с начала {y} года загружается с Binance — от нескольких минут до нескольких часов. Пока показаны последние ~3 месяца.", "cx_st_old_fail": "Старую историю фьючерсов с начала {y} получить не удалось — показаны последние ~3 месяца. {e}", "cx_st_only": "Статистика пока только для Binance.", "cx_st_empty": "За этот период закрытых сделок нет", "cx_st_synced": "Обновлено", "cx_st_from": "история с",
    "tr_trade": "торговля", "tr_enable": "Чтобы торговать из бота, включите в ключе Binance «Enable Spot & Margin Trading» и/или «Enable Futures» (вывод — не включать), затем «Обновить ключ».", "tr_noperm_spot": "У ключа нет права Spot-торговли — включите «Enable Spot & Margin Trading» на Binance.", "tr_noperm_fut": "У ключа нет права Futures — включите «Enable Futures» на Binance.", "tr_lev": "Плечо", "tr_margin": "Маржа, USDT", "tr_qty": "Количество", "tr_size": "Позиция", "tr_open": "Открытые ордера", "tr_need_amt": "Введите сумму", "tr_confirm": "Будет отправлен реальный ордер. Подтверждаете?", "tr_sent": "Ордер отправлен", "tr_cancel_q": "Отменить ордер?", "tr_cancelled": "Ордер отменён", "tr_close": "Закрыть", "tr_close_txt": "Какую часть позиции закрыть по рынку?", "tr_close_q": "Будет закрыто {p}% позиции {s} по рынку. Подтверждаете?", "tr_closed": "Позиция закрыта", "tr_tpsl_ok": "TP/SL сохранены", "cx_e_noperm": "У ключа нет права на эту торговлю", "cx_e_small": "Сумма слишком мала (меньше минимума биржи)", "cx_e_nopos": "По этой паре нет открытой позиции", "cx_e_noex": "Торговля на этой бирже пока недоступна",
    "cx_trades": "История сделок", "cx_tr_load": "Загружаем с Binance — 10–20 секунд…", "cx_tr_only": "История сделок пока только для Binance.", "cx_tr_n": "Сделки", "cx_tr_fee": "Комиссия", "cx_tr_days": "за {n} дн", "cx_tr_none": "Сделок не найдено", "cx_tr_orders": "ордеров", "cx_tr_spot_note": "по текущим монетам и монетам за 30 дней", "cx_tr_refresh": "Обновить",
    "cx_hist": "История баланса", "cx_hist_empty": "История собирается — баланс записывается каждый час", "cx_dn": "{n} дн",
    "loading": "Загрузка…", "cx_sub": "Ваши биржевые счета в одном месте", "cx_total": "Общий баланс",
    "cx_n": "бирж", "cx_mine": "Подключённые биржи", "cx_connect": "Подключить биржу", "cx_more": "Подключить ещё",
    "cx_intro": "Подключите биржевой счёт — баланс, активы и открытые фьючерсные позиции будут видны здесь.",
    "cx_ro": "Ключ только для чтения", "cx_link": "Подключить", "cx_pos_n": "поз.", "cx_pos": "Открытые позиции",
    "cx_assets": "Спот-активы", "cx_entry": "Вход", "cx_empty": "На счёте нет активов и позиций.",
    "cx_rekey": "Обновить ключ", "cx_del": "Отключить", "cx_del_q": "Отключить биржевой счёт? Ключ будет удалён.",
    "cx_deleted": "Счёт отключён, ключ удалён", "cx_upd": "Обновляем…",
    "cx_how": "Создайте на бирже новый API-ключ: ТОЛЬКО «Чтение» (Read-only), без ограничения по IP (Unrestricted). На Binance тип ключа — «System generated». Не включайте торговлю и вывод. Ключи хранятся в зашифрованном виде.",
    "cx_fill": "Заполните все поля", "cx_check": "Проверяем…", "cx_ok": "Биржевой счёт подключён ✅",
    "cx_safe": "Бот только читает баланс и позиции — не торгует и не может выводить средства. Ключи зашифрованы, отключить можно в любой момент.",
    "cx_e_auth": "Биржа не приняла ключ. Проверьте: ограничение по IP выключено (Unrestricted), тип ключа «System generated» (HMAC), API Key и Secret скопированы полностью", "cx_e_withdraw": "У ключа есть право вывода — из соображений безопасности не принимается. Создайте ключ только для чтения.",
    "cx_e_geo": "Биржа блокирует регион сервера — скоро исправим", "cx_e_net": "Биржа не ответила, попробуйте позже",
    "cx_e_api": "Не удалось получить данные биржи", "cx_e_bad": "Неверный формат ключа", "cx_e_reconnect": "Подключите ключ заново",
    "cx_e_rate": "Слишком много попыток — через минуту", "cx_e_perm": "У ключа нет права чтения",
})
T["en"].update({
    "cx_st_depth": "{e} only provides ~90 days of history (spot ~30 days) — new trades are saved every hour, so the yearly stats will build up.",
    "cx_tr_cnt": "{n} trades", "cx_margin": "Margin",
    "cx_pos_open": "{n} open", "cx_st_ytd": "Year to date", "cx_acc": "Account", "cx_assets_n": "assets", "cx_no_pos": "No open positions", "cx_drag": "Drag the TP and SL lines on the chart to change them.", "cx_per_ytd": "Since start of {y}", "cx_st_all": "All", "cx_st_net": "Net result", "cx_st_pf": "Profit factor", "cx_st_avg": "Avg win / loss", "cx_st_best": "Best trade", "cx_st_worst": "Worst trade", "cx_st_months": "By month", "cx_st_syms": "By pair", "cx_st_sync": "Loading trade history from Binance…", "cx_st_old_pending": "Full futures history since the start of {y} is being downloaded from Binance — from a few minutes to a few hours. The last ~3 months are shown meanwhile.", "cx_st_old_fail": "Older futures history since the start of {y} could not be fetched — showing the last ~3 months. {e}", "cx_st_only": "Statistics are available for Binance only for now.", "cx_st_empty": "No closed trades in this period", "cx_st_synced": "Updated", "cx_st_from": "history from",
    "tr_trade": "trade", "tr_enable": "To trade from the bot, enable «Enable Spot & Margin Trading» and/or «Enable Futures» on your Binance key (never withdrawals), then «Update key».", "tr_noperm_spot": "The key has no Spot trading permission — enable «Enable Spot & Margin Trading» on Binance.", "tr_noperm_fut": "The key has no Futures permission — enable «Enable Futures» on Binance.", "tr_lev": "Leverage", "tr_margin": "Margin, USDT", "tr_qty": "Quantity", "tr_size": "Position", "tr_open": "Open orders", "tr_need_amt": "Enter an amount", "tr_confirm": "A real order will be sent. Confirm?", "tr_sent": "Order sent", "tr_cancel_q": "Cancel this order?", "tr_cancelled": "Order cancelled", "tr_close": "Close", "tr_close_txt": "How much of the position to close at market?", "tr_close_q": "{p}% of the {s} position will be closed at market. Confirm?", "tr_closed": "Position closed", "tr_tpsl_ok": "TP/SL saved", "cx_e_noperm": "The key has no permission for this trade", "cx_e_small": "Amount too small (below exchange minimum)", "cx_e_nopos": "No open position in this pair", "cx_e_noex": "Trading on this exchange is not available yet",
    "cx_trades": "Trade history", "cx_tr_load": "Loading from Binance — 10–20 seconds…", "cx_tr_only": "Trade history is available for Binance only for now.", "cx_tr_n": "Trades", "cx_tr_fee": "Fees", "cx_tr_days": "last {n} days", "cx_tr_none": "No trades found", "cx_tr_orders": "orders", "cx_tr_spot_note": "for current coins and coins held in the last 30 days", "cx_tr_refresh": "Refresh",
    "cx_hist": "Balance history", "cx_hist_empty": "Collecting history — the balance is recorded every hour", "cx_dn": "{n}d",
    "loading": "Loading…", "cx_sub": "All your exchange accounts in one place", "cx_total": "Total balance",
    "cx_n": "exchanges", "cx_mine": "Connected exchanges", "cx_connect": "Connect an exchange", "cx_more": "Connect more",
    "cx_intro": "Connect your exchange account — balance, assets and open futures positions will show up here.",
    "cx_ro": "Read-only key", "cx_link": "Connect", "cx_pos_n": "positions", "cx_pos": "Open positions",
    "cx_assets": "Spot assets", "cx_entry": "Entry", "cx_empty": "No assets or positions on this account.",
    "cx_rekey": "Update key", "cx_del": "Disconnect", "cx_del_q": "Disconnect this exchange? The key will be deleted.",
    "cx_deleted": "Disconnected, key deleted", "cx_upd": "Refreshing…",
    "cx_how": "Create a new API key: READ-ONLY permission, no IP restriction (Unrestricted). On Binance choose the «System generated» key type. Do not enable trading or withdrawals. Keys are stored encrypted.",
    "cx_fill": "Fill in all fields", "cx_check": "Checking…", "cx_ok": "Exchange connected ✅",
    "cx_safe": "The bot only reads balances and positions — it cannot trade or withdraw. Keys are encrypted and you can disconnect any time.",
    "cx_e_auth": "The exchange rejected the key. Check: IP restriction is off (Unrestricted), key type is «System generated» (HMAC), API Key and Secret are copied in full", "cx_e_withdraw": "This key can withdraw funds — rejected for safety. Create a read-only key.",
    "cx_e_geo": "The exchange blocks the server region — fix coming soon", "cx_e_net": "The exchange did not respond, try later",
    "cx_e_api": "Could not load exchange data", "cx_e_bad": "Invalid key format", "cx_e_reconnect": "Please reconnect the key",
    "cx_e_rate": "Too many attempts — try in a minute", "cx_e_perm": "The key has no read permission",
})

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
PAGE = PAGE.replace("__COINS__", json.dumps(COINS))
