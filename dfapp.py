"""346/350: Dip Funded — Mini App uchun JSON (hisoblar, hisob holati, statistika, savdo).
Bot (amallar navbati orqali) ham, web (DIPFUNDED_API_KEY bo'lsa — to'g'ridan-to'g'ri) ham ishlatadi.
Har funksiya (ok, json matni) qaytaradi — `app_actions.result` bilan bir xil shakl."""
import json
import logging
import re
import time

import db
import dipfunded
import i18n

log = logging.getLogger("dfapp")

def df_status(a: dict, lang: str) -> str:
    if a["status"] == "active":
        return i18n.t("df.st_active", lang, n=a["phase"])
    return i18n.t(f"df.st_{a['status']}", lang)


DF_LIVE = ("active", "funded", "passed", "review")   # 347: ilovada ko'rinadigan holatlar
_DF_TOUR: dict = {}    # uid -> (vaqt, hisob id | None)


async def df_tour_acc(uid: int, accs: list) -> int | None:
    """347: qaysi hisob turnir hisobi. Dip Funded API buni bermaydi (sayt o'zgartirilmaydi) —
    turnir hisobi Dip Classic $10,000 (crypto); reytingdagi foydalanuvchi nomi va foyda %
    hisobnikiga mos kelsa — o'sha. 10 daqiqa kesh."""
    if any("tournament" in x for x in accs):      # 349: Dip Funded API belgisi (aniq)
        return next((x["id"] for x in accs if x.get("tournament")), None)
    hit = _DF_TOUR.get(uid)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    cand = [x for x in accs if int(x.get("size") or 0) == 10_000 and (x.get("market") or "crypto") == "crypto"
            and "Classic" in str(x.get("program") or "") and x.get("status") == "active"]
    found = None
    if cand:
        try:
            st = await dipfunded.stats(uid, cand[0]["id"], limit=1)
            name = st.get("username")
            board = (await dipfunded.fetch_tour(limit=100)).get("board") or []
            rows = [r for r in board if name and r.get("name") == name and not r.get("out")]
            if rows:
                pct = float(rows[0].get("pct") or 0)
                best = min(cand, key=lambda x: abs(float(x.get("pnl_pct") or 0) - pct))
                if abs(float(best.get("pnl_pct") or 0) - pct) < 0.1 or len(cand) == 1:
                    found = best["id"]
        except Exception as e:
            log.info("Turnir hisobi aniqlanmadi (uid=%s): %s", uid, e)
            return hit[1] if hit else None
    _DF_TOUR[uid] = (time.time(), found)
    return found


def df_name(a: dict) -> str:
    return f"{a['program']} ${int(a['size']):,}"


def state_json(data: dict, lang) -> dict:
    """255/310: Dip Funded hisobi holati Mini App uchun (hisob sahifasi va terminal)."""
    acc, st = data["account"], data["state"]
    px = data.get("prices") or st.get("prices") or {}
    return {"id": acc["id"], "name": df_name(acc), "status": acc["status"],
            "status_txt": df_status(acc, lang), "tradable": bool(acc.get("tradable")),
            "equity": st.get("equity"), "pnl": st.get("pnl"), "balance": st.get("balance"),
            "available": st.get("available"), "daily": st.get("daily"),
            "max": st.get("max"), "target": st.get("target"), "days": st.get("days"),
            "positions": [{"symbol": p_["symbol"], "qty": p_.get("qty"), "value": p_.get("value"),
                           "avg": p_.get("avg_price"), "price": p_.get("price"),
                           "upnl": p_.get("upnl"), "upnl_pct": p_.get("upnl_pct"),
                           "sl": p_.get("sl"), "tp": p_.get("tp")}
                          for p_ in (st.get("positions") or [])],
            "orders": [{"id": o["id"], "symbol": o["symbol"], "limit": o.get("limit"),
                        "amount": o.get("amount"), "sl": o.get("sl"), "tp": o.get("tp")}
                       for o in (st.get("orders") or [])],
            "trades": [{"time": t_.get("time"), "ts": t_.get("ts"), "symbol": t_.get("symbol"), "side": t_.get("side"),
                        "price": t_.get("price"), "pnl": t_.get("pnl"), "kind": t_.get("kind")}
                       for t_ in (st.get("trades") or [])][:10],
            "prices": {k: float(v) for k, v in px.items()}}


async def trade(uid: int, lang, f: dict) -> tuple[bool, str]:
    """310: Dip Funded savdosi ilova terminalidan — sotib olish (market/limit, SL/TP),
    sotish (ulush), SL/TP, limitni bekor qilish/o'zgartirish. Huquqni Dip Funded o'zi
    tekshiradi (hisob shu Telegram akkauntiga tegishlimi). Javob — yangilangan holat."""
    if not dipfunded.enabled():
        return False, json.dumps({"code": "off"})
    op, acc, sym = f.get("op"), f.get("acc"), f.get("symbol")
    try:
        if op == "buy":
            if not sym or not f.get("amount"):
                return False, json.dumps({"code": "amount", "text": i18n.t("man.bad_number", lang)})
            data = await dipfunded.buy(uid, acc, sym, f["amount"], limit=f.get("limit"),
                                       sl=f.get("sl"), tp=f.get("tp"))
        elif op == "sell":
            fr = f.get("fraction") or 0
            if not sym or not (0 < fr <= 1):
                return False, json.dumps({"code": "amount", "text": i18n.t("man.bad_number", lang)})
            data = await dipfunded.sell(uid, acc, sym, fr)
        elif op == "protect":
            data = await dipfunded.protect(uid, acc, sym, {k: f[k] for k in ("sl", "tp") if k in f})
        elif op == "cancel":
            data = await dipfunded.cancel(uid, acc, int(f.get("order_id") or 0))
        elif op == "modify":
            data = await dipfunded.modify(uid, acc, int(f.get("order_id") or 0),
                                          {k: f[k] for k in ("limit", "sl", "tp") if k in f})
        else:
            return False, json.dumps({"code": "bad"})
    except dipfunded.NotLinked as e:
        return False, json.dumps({"code": str(e) or "not_linked"})
    except dipfunded.ApiError as e:
        return False, json.dumps({"code": e.code, "text": e.text})
    except Exception as e:
        log.warning("Mini App Dip Funded savdosi: %s", e)
        return False, json.dumps({"code": "unavailable"})
    out = state_json(data, lang)
    out["msg"] = re.sub(r"<[^>]+>", "", str(data.get("message") or ""))
    return True, json.dumps(out, default=float)


async def main_acc(uid: int):
    try:
        raw = await db.get_setting(f"dfset:{uid}")
        return (json.loads(raw) if raw else {}).get("main")
    except Exception:
        return None


async def accounts(uid: int, lang) -> tuple[bool, str]:
    if not dipfunded.enabled():
        return False, json.dumps({"code": "off"})
    try:
        data = await dipfunded.accounts(uid)
        # 347: yopilgan hisoblar (failed, ended…) ilovada ko'rinmaydi
        live = [x for x in (data.get("accounts") or []) if x.get("status") in DF_LIVE]
        tour = await df_tour_acc(uid, live)
        out = {"main": await main_acc(uid), "accounts": [
            {"id": x["id"], "name": (i18n.t("df.tour_name", lang, size=f"{int(x['size']):,}")
                                     if x["id"] == tour else df_name(x)),
             "tour": x["id"] == tour, "status": x["status"],
             "phase": x.get("phase"), "status_txt": df_status(x, lang),
             "equity": x.get("equity"), "pnl_pct": x.get("pnl_pct")}
            for x in live]}
        return True, json.dumps(out, default=float)
    except dipfunded.NotLinked as e:
        return False, json.dumps({"code": str(e) or "not_linked"})
    except Exception as e:
        log.warning("Mini App Dip Funded: %s", e)
        return False, json.dumps({"code": "unavailable"})


async def account(uid: int, acc: int, lang) -> tuple[bool, str]:
    if not dipfunded.enabled():
        return False, json.dumps({"code": "off"})
    try:
        return True, json.dumps(state_json(await dipfunded.account(uid, int(acc)), lang), default=float)
    except dipfunded.NotLinked as e:
        return False, json.dumps({"code": str(e) or "not_linked"})
    except Exception as e:
        log.warning("Mini App Dip Funded: %s", e)
        return False, json.dumps({"code": "unavailable"})


async def stats(uid: int, acc: int) -> tuple[bool, str]:
    """346: hisobning BARCHA yopilgan savdolari (sahifalab, 100 tadan) — web davr bo'yicha hisoblaydi."""
    if not dipfunded.enabled():
        return False, json.dumps({"code": "off"})
    try:
        acc, tr, off, head = int(acc), [], 0, {}
        for _ in range(40):
            d = await dipfunded.stats(uid, acc, limit=100, offset=off)
            head = head or d
            part = d.get("trades") or []
            tr += [{"sym": x.get("symbol"), "t": x.get("time"), "pnl": x.get("pnl"),
                    "qty": x.get("qty"), "entry": x.get("entry"), "exit": x.get("exit"),
                    "pnl_pct": x.get("pnl_pct"), "id": x.get("id")} for x in part]
            off += len(part)
            if not part or off >= int(d.get("total") or 0):
                break
        sm = head.get("summary") or {}
        return True, json.dumps({"acc": acc, "starting": head.get("starting"),
                                 "fees": sm.get("fees"), "trades": tr}, default=float)
    except dipfunded.NotLinked as e:
        return False, json.dumps({"code": str(e) or "not_linked"})
    except Exception as e:
        log.warning("Mini App Dip Funded statistikasi: %s", e)
        return False, json.dumps({"code": "unavailable"})
