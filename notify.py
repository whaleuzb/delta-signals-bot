"""352: Telegram bildirishnomalar (web servis fonida) — birja va Dip Funded hisoblari.
Har ~2 daqiqada holat oldingisi bilan solishtiriladi:
  - limit order bajarildi (order yo'qoldi + pozitsiya/aktiv o'zgardi; faqat yo'qolgani — bekor, xabarsiz);
  - pozitsiya yopildi (TP / SL / boshqa), yangi pozitsiya ochildi, pozitsiya qisman yopildi/kattalashdi;
  - Dip Funded: kunlik yoki maksimal zarar limitining 80% ishlatildi (kuniga/hisobga bir marta).
Holat xotirada: qayta ishga tushgandan keyingi birinchi aylanish faqat bazani yozadi (xabarsiz).
O'chirish: `bot_settings` `ntf_off:<uid>` (ilovada Birja bo'limida)."""
import asyncio
import html
import logging
import time
from datetime import datetime, timezone

import config
import db
import i18n

log = logging.getLogger("notify")
EPS = 1e-9
STATE: dict = {}          # (uid, ex) -> holat
RISK_SENT: dict = {}      # (uid, acc, turi) -> sana / bayroq


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def fp(x) -> str:
    x = _f(x)
    if x == 0:
        return "0"
    if abs(x) >= 1000:
        return f"{x:,.2f}".rstrip("0").rstrip(".")
    if abs(x) >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".")


def money(x) -> str:
    x = _f(x)
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


# ───────────────────────── holat (birja) ─────────────────────────

def cex_state(snap: dict, orders: list | None) -> dict:
    pos = {}
    for p in (snap or {}).get("pos") or []:
        k = f"{p.get('sym')}:{p.get('ps') or 'BOTH'}:{p.get('side')}"
        pos[k] = {"sym": p.get("sym"), "side": p.get("side"), "qty": _f(p.get("qty")), "entry": _f(p.get("entry")),
                  "mark": _f(p.get("mark")), "upnl": _f(p.get("upnl")), "lev": p.get("lev")}
    ords = {}
    for o in orders or []:
        ords[str(o.get("id"))] = {"sym": o.get("sym"), "side": o.get("side"), "type": str(o.get("type") or ""),
                                  "price": _f(o.get("price")), "qty": _f(o.get("qty")),
                                  "trigger": _f(o.get("trigger")) or None, "mkt": o.get("mkt")}
    assets = {a.get("a"): _f(a.get("q")) for a in (snap or {}).get("assets") or []}
    return {"pos": pos, "ord": ords, "assets": assets}


def _base(sym: str) -> str:
    for q in ("USDT", "USDC", "FDUSD"):
        if sym and sym.endswith(q) and len(sym) > len(q):
            return sym[:-len(q)]
    return sym or ""


def cex_events(prev: dict, cur: dict) -> list:
    """Ikki holat farqi → [(tur, ma'lumot)]."""
    ev, filled_syms = [], set()
    pp, cp = prev["pos"], cur["pos"]
    # 1) yo'qolgan limit orderlar: bajarilganmi?
    for oid, o in prev["ord"].items():
        if oid in cur["ord"] or o["trigger"] or "limit" not in o["type"]:
            continue
        sym = o["sym"]
        if o.get("mkt") == "spot":
            b = _base(sym)
            d = cur["assets"].get(b, 0) - prev["assets"].get(b, 0)
            hit = d > EPS if o["side"] == "buy" else d < -EPS
        else:
            def tot(P):
                return sum(x["qty"] for x in P.values() if x["sym"] == sym)
            hit = abs(tot(cp) - tot(pp)) > EPS or any(
                (x["sym"] == sym) != (k in pp) for k, x in cp.items() if x["sym"] == sym)
        if hit:
            ev.append(("filled", o))
            filled_syms.add(sym)
    # 2) yopilgan pozitsiyalar
    for k, p in pp.items():
        if k in cp:
            continue
        gone = [o for oid, o in prev["ord"].items() if oid not in cur["ord"] and o["sym"] == p["sym"] and o["trigger"]]
        tp = any("take_profit" in o["type"] for o in gone)
        sl = any("stop" in o["type"] for o in gone)
        why = "tp" if tp and not sl else "sl" if sl and not tp else ("tp" if p["upnl"] >= 0 else "sl") if gone else ""
        ev.append(("closed", dict(p, why=why)))
    # 3) yangi / o'zgargan pozitsiyalar
    for k, p in cp.items():
        if k not in pp:
            if p["sym"] not in filled_syms:
                ev.append(("opened", p))
        else:
            dq = p["qty"] - pp[k]["qty"]
            if abs(dq) > max(EPS, pp[k]["qty"] * 1e-6) and p["sym"] not in filled_syms:
                ev.append(("grew" if dq > 0 else "part", dict(p, dq=abs(dq))))
    return ev


# ───────────────────────── holat (Dip Funded) ─────────────────────────

def df_state(st: dict) -> dict:
    pos = {p["symbol"]: {"sym": p["symbol"] + "USDT", "side": "long", "qty": _f(p.get("qty")), "entry": _f(p.get("avg")),
                         "mark": _f(p.get("price")), "upnl": _f(p.get("upnl")), "sl": p.get("sl"), "tp": p.get("tp")}
           for p in st.get("positions") or []}
    ords = {str(o["id"]): {"sym": o["symbol"] + "USDT", "side": "buy", "type": "limit", "price": _f(o.get("limit")),
                           "qty": _f(o.get("amount")) / _f(o.get("limit")) if _f(o.get("limit")) else 0,
                           "amount": _f(o.get("amount")), "trigger": None, "mkt": "df"}
            for o in st.get("orders") or []}
    return {"pos": pos, "ord": ords}


def df_events(prev: dict, cur: dict) -> list:
    ev, filled = [], set()
    pp, cp = prev["pos"], cur["pos"]
    for oid, o in prev["ord"].items():
        if oid in cur["ord"]:
            continue
        b = _base(o["sym"])
        if cp.get(b, {}).get("qty", 0) - pp.get(b, {}).get("qty", 0) > EPS:
            ev.append(("filled", o))
            filled.add(b)
    for b, p in pp.items():
        if b not in cp:
            m = p["mark"]
            why = ""
            if p.get("tp") and m and m >= _f(p["tp"]) * 0.995:
                why = "tp"
            elif p.get("sl") and m and m <= _f(p["sl"]) * 1.005:
                why = "sl"
            ev.append(("closed", dict(p, why=why)))
        elif cp[b]["qty"] < p["qty"] - max(EPS, p["qty"] * 1e-6):
            ev.append(("part", dict(cp[b], dq=p["qty"] - cp[b]["qty"])))
    for b, p in cp.items():
        if b not in pp and b not in filled:
            ev.append(("opened", p))
    return ev


def df_risk(uid: int, acc: int, st: dict, today: str) -> list:
    out = []
    for kind in ("daily", "max"):
        r = st.get(kind) or {}
        used = _f(r.get("used_pct"))
        key = (uid, acc, kind)
        if used >= 80:
            mark = today if kind == "daily" else "1"
            if RISK_SENT.get(key) != mark:
                RISK_SENT[key] = mark
                out.append(("risk_" + kind, {"used": used, "left": _f(r.get("left"))}))
        elif kind == "max" and used < 60:
            RISK_SENT.pop(key, None)
    return out


# ───────────────────────── xabar matni ─────────────────────────

def text(ev: tuple, src: str, lang: str) -> str:
    kind, d = ev
    side = "LONG" if d.get("side") in ("long", "buy") else "SHORT"
    sym = html.escape(str(d.get("sym") or ""))
    s = html.escape(src)
    if kind == "filled":
        return i18n.t("ntf.filled", lang, src=s, side=str(d.get("side") or "").upper(), sym=sym,
                      qty=fp(d.get("qty")), price=fp(d.get("price")))
    if kind == "closed":
        k = {"tp": "ntf.closed_tp", "sl": "ntf.closed_sl"}.get(d.get("why"), "ntf.closed")
        return i18n.t(k, lang, src=s, sym=sym, side=side, pnl=money(d.get("upnl")), price=fp(d.get("mark")))
    if kind == "opened":
        return i18n.t("ntf.opened", lang, src=s, sym=sym, side=side, qty=fp(d.get("qty")), price=fp(d.get("entry")))
    if kind in ("part", "grew"):
        return i18n.t("ntf." + kind, lang, src=s, sym=sym, side=side, qty=fp(d.get("dq")), left=fp(d.get("qty")))
    if kind in ("risk_daily", "risk_max"):
        return i18n.t("ntf." + kind, lang, src=s, used=f"{d['used']:.0f}", left=f"${d['left']:,.2f}")
    return ""


async def send(uid: int, msg: str, lang: str, path: str = "/app") -> bool:
    import httpx
    kb = {"inline_keyboard": [[{"text": i18n.t("ntf.btn", lang), "web_app": {"url": config.WEB_URL + path}}]]}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
                             json={"chat_id": uid, "text": msg, "parse_mode": "HTML",
                                   "disable_web_page_preview": True, "reply_markup": kb})
        return r.status_code == 200
    except Exception as e:
        log.info("Bildirishnoma yuborilmadi (uid=%s): %s", uid, type(e).__name__)
        return False


async def _emit(uid: int, evs: list, src: str, path: str):
    if not evs or await db.get_setting(f"ntf_off:{uid}"):
        return
    lang = i18n.normalize(await db.get_user_lang(uid))
    for e in evs[:6]:
        m = text(e, src, lang)
        if m:
            await send(uid, m, lang, path)


# ───────────────────────── aylanish ─────────────────────────

async def _cex_tick(row):
    import webapp
    import cex
    uid, ex = row["user_id"], row["exchange"]
    k = webapp._cex_keys(row)
    snap = await webapp._cx_call("snapshot", ex, k)
    orders = None
    if ex in cex.TRADE_EX:
        orders = []
        for op, mkt in (("fut_open", "fut"), ("spot_open", "spot")):
            try:
                for o in await webapp._cx_call("trade", ex, k, {"op": op, "a": {}}) or []:
                    orders.append(dict(o, mkt=mkt))
            except Exception:
                orders = None     # orderlar o'qilmadi — bu safar order hodisalari yo'q
                break
    cur = cex_state(snap, orders)
    key = (uid, ex)
    prev = STATE.get(key)
    STATE[key] = cur
    if prev is None:
        return
    if orders is None:            # order ma'lumoti yo'q — faqat pozitsiyalar
        prev = dict(prev, ord={})
        cur = dict(cur, ord={})
    await _emit(uid, cex_events(prev, cur), webapp_name(ex), "/app")


def webapp_name(ex: str) -> str:
    return {"binance": "Binance", "bitget": "Bitget", "mexc": "MEXC", "bingx": "BingX", "bitunix": "Bitunix", "bybit": "Bybit"}.get(ex, ex)


async def _df_tick(uid: int):
    import dipfunded
    if await db.get_setting(f"dfoff:{uid}"):
        return
    data = await dipfunded.accounts(uid)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for a in data.get("accounts") or []:
        if a.get("status") not in ("active", "funded"):
            continue
        st = (await dipfunded.account(uid, a["id"])).get("state") or {}
        cur = df_state({"positions": [{"symbol": p["symbol"], "qty": p.get("qty"), "avg": p.get("avg_price"),
                                       "price": p.get("price"), "upnl": p.get("upnl"), "sl": p.get("sl"), "tp": p.get("tp")}
                                      for p in st.get("positions") or []],
                        "orders": st.get("orders") or []})
        key = (uid, f"df{a['id']}")
        prev = STATE.get(key)
        STATE[key] = cur
        evs = (df_events(prev, cur) if prev is not None else []) + df_risk(uid, a["id"], st, today)
        await _emit(uid, evs, f"Dip Funded #{a['id']}", f"/app?df=1&acc={a['id']}")


async def loop(_app=None):
    async def run():
        await asyncio.sleep(60)
        while True:
            t0 = time.monotonic()
            try:
                sem = asyncio.Semaphore(3)

                async def one(coro):
                    async with sem:
                        try:
                            await coro
                        except Exception as e:
                            log.info("Bildirishnoma tekshiruvi xato: %s", type(e).__name__)
                jobs = [one(_cex_tick(r)) for r in await db.cex_all()]
                import dipfunded
                if dipfunded.enabled():
                    jobs += [one(_df_tick(u)) for u in await db.setting_users("dfw:")]
                await asyncio.gather(*jobs)
            except Exception:
                log.warning("Bildirishnomalar aylanishi xato", exc_info=True)
            await asyncio.sleep(max(30, 120 - (time.monotonic() - t0)))
    import webapp
    t = asyncio.get_running_loop().create_task(run())
    webapp._CEX_BG.add(t)
