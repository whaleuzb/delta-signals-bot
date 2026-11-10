"""324: birja hisoblarini ulash — MEXC, Bitget, BingX, Binance (1-bosqich: FAQAT O'QISH).

Foydalanuvchi Mini App'dagi Wallet bo'limida o'z API kalitini kiritadi; bot
spot balans, fyuchers balansi va ochiq fyuchers pozitsiyalarini ko'rsatadi.
Savdo QILINMAYDI — bu modulda faqat GET (o'qish) so'rovlari bor.

Xavfsizlik:
  - Kalit va maxfiy kalit bazada AES-GCM bilan shifrlangan (`seal`/`unseal`).
    Shifr kaliti `EXCH_ENC_KEY` (bo'lmasa BOT_TOKEN'dan hosil qilinadi) —
    baza sizib chiqsa ham kalitlar o'qilmaydi.
  - Kalitlar brauzerga HECH QACHON qaytarilmaydi (faqat niqoblangan ko'rinish).
  - Pul yechish ruxsati bor kalit qabul qilinmaydi (birja buni ko'rsatsa:
    Binance `apiRestrictions`, Bitget `authorities`); MEXC/BingX'da
    API buni ko'rsatmaydi — ilovada "faqat o'qish" ko'rsatmasi beriladi..
  - Logga kalit/imzo yozilmaydi.

Railway serveri AQShda — Binance u yerdan 451 (hudud bloki) qaytaradi.
Bu holat `ApiErr("geo")` bo'lib foydalanuvchiga tushunarli xabar chiqadi.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import urlencode

import httpx

import config

log = logging.getLogger("cex")

EXCHANGES = ("mexc", "bitget", "bingx", "binance")
NAMES = {"mexc": "MEXC", "bitget": "Bitget", "bingx": "BingX", "binance": "Binance"}
NEEDS_PASS = {"bitget"}
STABLE = {"USDT", "USDC", "FDUSD", "BUSD", "TUSD", "USDE", "DAI", "USD"}

_http = httpx.AsyncClient(timeout=12, headers={"User-Agent": "Mozilla/5.0"})


class ApiErr(Exception):
    """code: auth | perm | withdraw | geo | net | api"""

    def __init__(self, code: str, text: str = ""):
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text


# ─────────────────────────── shifrlash ───────────────────────────

def _aes_key() -> bytes:
    raw = os.getenv("EXCH_ENC_KEY") or ("tc-cex-v1:" + config.BOT_TOKEN)
    return hashlib.sha256(raw.encode()).digest()


def seal(text: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    ct = AESGCM(_aes_key()).encrypt(nonce, text.encode(), b"cex")
    return base64.b64encode(nonce + ct).decode()


def unseal(blob: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(blob)
    return AESGCM(_aes_key()).decrypt(raw[:12], raw[12:], b"cex").decode()


def mask(key: str) -> str:
    return (key[:4] + "…" + key[-4:]) if len(key) > 10 else "…"


# ─────────────────────────── umumiy so'rov ───────────────────────────

async def _get(url: str, headers: dict, params: str = "") -> object:
    return await _req("GET", url, headers, params)


async def _req(method: str, url: str, headers: dict, params: str = "", body: str | None = None) -> object:
    full = url + ("?" + params if params else "")
    try:
        r = await _http.request(method, full, headers=headers, content=body)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise ApiErr("net", type(e).__name__)
    if r.status_code == 451 or (r.status_code == 403 and "restricted" in r.text.lower()):
        raise ApiErr("geo", r.text[:200])
    try:
        data = r.json()
    except ValueError:
        if r.status_code in (401, 403):
            raise ApiErr("auth", r.text[:200])
        raise ApiErr("api", f"HTTP {r.status_code}")
    if r.status_code in (401, 403):
        raise ApiErr("auth", json.dumps(data)[:200])
    if r.status_code >= 400:
        raise ApiErr("api", json.dumps(data)[:200])
    return data


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _ms() -> int:
    return int(time.time() * 1000)


# Har birja: spot(k) -> {asset: qty}, fut(k) -> (equity, upnl) | None,
# pos(k) -> [pozitsiya], perms(k) -> withdraw ruxsati bormi (None = noma'lum).
# k = {"key","secret","pass"}.

# ─────────────────────────── Binance ───────────────────────────

async def _bn(k, base, path, extra=None):
    q = urlencode({**(extra or {}), "recvWindow": 10000, "timestamp": _ms()})
    q += "&signature=" + _hex(k["secret"], q)
    d = await _get(base + path, {"X-MBX-APIKEY": k["key"]}, q)
    if isinstance(d, dict) and isinstance(d.get("code"), int) and d["code"] < 0:
        code = d["code"]
        raise ApiErr("auth" if code in (-2014, -2015, -1022, -2008) else "api", d.get("msg", ""))
    return d


async def bn_spot(k):
    d = await _bn(k, "https://api.binance.com", "/api/v3/account", {"omitZeroBalances": "true"})
    return {b["asset"]: _f(b["free"]) + _f(b["locked"]) for b in d.get("balances", [])}


async def bn_fut(k):
    d = await _bn(k, "https://fapi.binance.com", "/fapi/v2/account")
    return _f(d.get("totalMarginBalance")), _f(d.get("totalUnrealizedProfit"))


async def bn_pos(k):
    d = await _bn(k, "https://fapi.binance.com", "/fapi/v2/positionRisk")
    out = []
    for p in d if isinstance(d, list) else []:
        amt = _f(p.get("positionAmt"))
        if not amt:
            continue
        out.append({"sym": p["symbol"], "side": "long" if amt > 0 else "short", "qty": abs(amt),
                    "entry": _f(p.get("entryPrice")), "mark": _f(p.get("markPrice")),
                    "upnl": _f(p.get("unRealizedProfit")), "lev": _f(p.get("leverage")),
                    "liq": _f(p.get("liquidationPrice")) or None,
                    "ps": p.get("positionSide") or "BOTH"})
    return out


async def bn_perms(k):
    d = await _bn(k, "https://api.binance.com", "/sapi/v1/account/apiRestrictions")
    return bool(d.get("enableWithdrawals"))


# ─────────────────────────── MEXC ───────────────────────────

async def _mx_spot(k, path, extra=None):
    q = urlencode({**(extra or {}), "recvWindow": 10000, "timestamp": _ms()})
    q += "&signature=" + _hex(k["secret"], q)
    d = await _get("https://api.mexc.com" + path, {"X-MEXC-APIKEY": k["key"]}, q)
    if isinstance(d, dict) and d.get("code") not in (None, 0, 200) and "balances" not in d:
        code = d.get("code")
        raise ApiErr("auth" if code in (700002, 700003, 10072, 700001) else "api", str(d.get("msg", "")))
    return d


async def _mx_fut(k, path, params=None):
    q = urlencode(sorted((params or {}).items()))
    ts = str(_ms())
    sign = _hex(k["secret"], k["key"] + ts + q)
    d = await _get("https://contract.mexc.com" + path,
                   {"ApiKey": k["key"], "Request-Time": ts, "Signature": sign,
                    "Content-Type": "application/json"}, q)
    if not isinstance(d, dict) or not d.get("success"):
        code = d.get("code") if isinstance(d, dict) else None
        raise ApiErr("auth" if code in (401, 402, 406, 602) else "api",
                     str(d.get("message", "") if isinstance(d, dict) else d))
    return d.get("data")


_mx_csize: dict[str, float] = {}
_mx_csize_at = 0.0


async def _mx_contract_size(sym: str) -> float:
    global _mx_csize_at
    if not _mx_csize or time.time() - _mx_csize_at > 3600:
        try:
            d = await _get("https://contract.mexc.com/api/v1/contract/detail", {})
            for c in d.get("data") or []:
                _mx_csize[c["symbol"]] = _f(c.get("contractSize")) or 1.0
            _mx_csize_at = time.time()
        except ApiErr:
            pass
    return _mx_csize.get(sym, 1.0)


async def mx_spot(k):
    d = await _mx_spot(k, "/api/v3/account")
    return {b["asset"]: _f(b["free"]) + _f(b["locked"]) for b in d.get("balances", [])}


async def mx_fut(k):
    d = await _mx_fut(k, "/api/v1/private/account/assets") or []
    for a in d:
        if a.get("currency") == "USDT":
            return _f(a.get("equity")), _f(a.get("unrealized"))
    return 0.0, 0.0


async def mx_pos(k):
    d = await _mx_fut(k, "/api/v1/private/position/open_positions") or []
    out = []
    marks = {}
    for p in d:
        vol = _f(p.get("holdVol"))
        if not vol:
            continue
        sym = p["symbol"]
        if sym not in marks:
            try:
                t = await _get("https://contract.mexc.com/api/v1/contract/ticker", {}, "symbol=" + sym)
                marks[sym] = _f((t.get("data") or {}).get("fairPrice") or (t.get("data") or {}).get("lastPrice"))
            except ApiErr:
                marks[sym] = 0.0
        cs = await _mx_contract_size(sym)
        qty = vol * cs
        side = "long" if p.get("positionType") == 1 else "short"
        entry, mark = _f(p.get("holdAvgPrice") or p.get("openAvgPrice")), marks[sym]
        upnl = (mark - entry) * qty * (1 if side == "long" else -1) if mark else 0.0
        out.append({"sym": sym.replace("_", ""), "side": side, "qty": qty, "entry": entry,
                    "mark": mark or None, "upnl": upnl, "lev": _f(p.get("leverage")),
                    "liq": _f(p.get("liquidatePrice")) or None})
    return out


async def mx_perms(k):
    # `/api/v3/account`dagi `canWithdraw` HISOB holati (kalit ruxsati emas) —
    # unga qarab rad etilsa, faqat-o'qish kaliti ham rad bo'lardi. Noma'lum.
    return None


# ─────────────────────────── Bitget (v2) ───────────────────────────

async def _bg(k, path, params=None):
    q = urlencode(params or {})
    ts = str(_ms())
    pre = ts + "GET" + path + ("?" + q if q else "")
    sign = base64.b64encode(hmac.new(k["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
    d = await _get("https://api.bitget.com" + path,
                   {"ACCESS-KEY": k["key"], "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
                    "ACCESS-PASSPHRASE": k.get("pass") or "", "Content-Type": "application/json",
                    "locale": "en-US"}, q)
    if not isinstance(d, dict) or d.get("code") != "00000":
        code = str(d.get("code")) if isinstance(d, dict) else ""
        raise ApiErr("auth" if code in ("40006", "40009", "40012", "40037", "40038") else "api",
                     str(d.get("msg", "") if isinstance(d, dict) else d))
    return d.get("data")


async def bg_spot(k):
    d = await _bg(k, "/api/v2/spot/account/assets") or []
    return {b["coin"].upper(): _f(b.get("available")) + _f(b.get("frozen")) + _f(b.get("locked"))
            for b in d}


async def bg_fut(k):
    d = await _bg(k, "/api/v2/mix/account/accounts", {"productType": "USDT-FUTURES"}) or []
    eq = sum(_f(a.get("usdtEquity") or a.get("accountEquity")) for a in d)
    up = sum(_f(a.get("unrealizedPL")) for a in d)
    return eq, up


async def bg_pos(k):
    d = await _bg(k, "/api/v2/mix/position/all-position",
                  {"productType": "USDT-FUTURES", "marginCoin": "USDT"}) or []
    out = []
    for p in d:
        qty = _f(p.get("total"))
        if not qty:
            continue
        out.append({"sym": p["symbol"].upper(), "side": "long" if p.get("holdSide") == "long" else "short",
                    "qty": qty, "entry": _f(p.get("openPriceAvg")), "mark": _f(p.get("markPrice")) or None,
                    "upnl": _f(p.get("unrealizedPL")), "lev": _f(p.get("leverage")),
                    "liq": _f(p.get("liquidationPrice")) or None,
                    "ps": str(p.get("holdSide") or "").upper() if p.get("posMode") == "hedge_mode" else "BOTH"})
    return out


async def bg_perms(k):
    d = await _bg(k, "/api/v2/spot/account/info") or {}
    auth = [str(a).lower() for a in (d.get("authorities") or [])]
    if not auth:
        return None
    return any("withdraw" in a for a in auth)


# ─────────────────────────── BingX ───────────────────────────

async def _bx(k, path, params=None):
    q = urlencode({**(params or {}), "timestamp": _ms(), "recvWindow": 10000})
    q += "&signature=" + _hex(k["secret"], q)
    d = await _get("https://open-api.bingx.com" + path, {"X-BX-APIKEY": k["key"]}, q)
    if not isinstance(d, dict) or d.get("code") not in (0, "0"):
        code = d.get("code") if isinstance(d, dict) else None
        raise ApiErr("auth" if code in (100001, 100413, 100419, 100410) else "api",
                     str(d.get("msg", "") if isinstance(d, dict) else d))
    return d.get("data")


async def bx_spot(k):
    d = await _bx(k, "/openApi/spot/v1/account/balance") or {}
    return {b["asset"].upper(): _f(b.get("free")) + _f(b.get("locked")) for b in d.get("balances") or []}


async def bx_fut(k):
    d = await _bx(k, "/openApi/swap/v2/user/balance") or {}
    b = d.get("balance") if isinstance(d, dict) else None
    if isinstance(b, list):
        b = next((x for x in b if x.get("asset") == "USDT"), b[0] if b else {})
    b = b or {}
    return _f(b.get("equity")), _f(b.get("unrealizedProfit"))


async def bx_pos(k):
    d = await _bx(k, "/openApi/swap/v2/user/positions") or []
    out = []
    for p in d:
        qty = abs(_f(p.get("positionAmt")))
        if not qty:
            continue
        out.append({"sym": p["symbol"].replace("-", "").upper(),
                    "side": "long" if str(p.get("positionSide")).upper() == "LONG" else "short",
                    "qty": qty, "entry": _f(p.get("avgPrice")), "mark": _f(p.get("markPrice")) or None,
                    "upnl": _f(p.get("unrealizedProfit")), "lev": _f(p.get("leverage")),
                    "liq": _f(p.get("liquidationPrice")) or None,
                    "ps": str(p.get("positionSide") or "BOTH").upper()})
    return out


async def bx_perms(k):
    return None


_IMPL = {
    "binance": (bn_spot, bn_fut, bn_pos, bn_perms),
    "mexc": (mx_spot, mx_fut, mx_pos, mx_perms),
    "bitget": (bg_spot, bg_fut, bg_pos, bg_perms),
    "bingx": (bx_spot, bx_fut, bx_pos, bx_perms),
}


# ─────────────────────────── yuqori daraja ───────────────────────────

async def _prices() -> dict[str, float]:
    import exchange
    try:
        return dict(await exchange.price_list())
    except Exception:
        return {}


async def verify(ex: str, k: dict) -> None:
    """Ulashdan oldin: kalit ishlaydimi (spot balans o'qiladi) va pul yechish ruxsati yo'qmi."""
    spot, _fut, _pos, perms = _IMPL[ex]
    await spot(k)
    try:
        wd = await perms(k)
    except ApiErr as e:
        if e.code in ("auth", "geo"):
            raise
        wd = None
    if wd:
        raise ApiErr("withdraw")


async def snapshot(ex: str, k: dict) -> dict:
    """Spot aktivlar ($ bilan), fyuchers balansi va ochiq pozitsiyalar.
    Spot o'qilmasa — xato (kalit ishlamayapti); fyuchers ixtiyoriy."""
    spot_f, fut_f, pos_f, _ = _IMPL[ex]
    spot_r, fut_r, pos_r, px = await asyncio.gather(
        spot_f(k), fut_f(k), pos_f(k), _prices(), return_exceptions=True)
    if isinstance(spot_r, BaseException):
        if isinstance(spot_r, ApiErr):
            raise spot_r
        log.warning("%s spot o'qilmadi: %s", ex, type(spot_r).__name__)
        raise ApiErr("api", type(spot_r).__name__)
    px = px if isinstance(px, dict) else {}
    assets = []
    for a, q in spot_r.items():
        if q <= 0:
            continue
        usd = q if a in STABLE else (q * px[a] if a in px else None)
        if usd is not None and usd < 1:
            continue
        assets.append({"a": a, "q": q, "usd": usd})
    assets.sort(key=lambda x: -(x["usd"] or 0))
    spot_usd = sum(x["usd"] or 0 for x in assets)
    fut = None
    if not isinstance(fut_r, BaseException):
        fut = {"eq": fut_r[0], "upnl": fut_r[1]}
    elif not (isinstance(fut_r, ApiErr) and fut_r.code in ("auth", "perm")):
        log.info("%s fyuchers balansi o'qilmadi: %s", ex, fut_r)
    pos = pos_r if not isinstance(pos_r, BaseException) else []
    out = {"ex": ex, "spot_usd": spot_usd, "assets": assets[:40], "fut": fut, "pos": pos,
           "total": spot_usd + (fut["eq"] if fut else 0)}
    if ex in TRADE_EX:
        try:
            out["trade"] = await (TRADE_PERMS.get(ex) or bn_trade_perms)(k)
        except ApiErr:
            out["trade"] = None
    return out


# ─────────────────────────── 328: balans tarixi ───────────────────────────

async def bn_history(k, days: int = 30) -> list:
    """Binance kunlik hisob suratlari (`/sapi/v1/accountSnapshot`, 30 kungacha):
    spot `totalAssetOfBtc` × o'sha kungi BTC narxi (MEXC kunlik shami) + fyuchers
    stable aktivlar `marginBalance`. Natija: [(ts_ms, total, spot, fut)]."""
    import exchange
    days = max(7, min(30, days))
    spot_r, fut_r = await asyncio.gather(
        _bn(k, "https://api.binance.com", "/sapi/v1/accountSnapshot", {"type": "SPOT", "limit": days}),
        _bn(k, "https://api.binance.com", "/sapi/v1/accountSnapshot", {"type": "FUTURES", "limit": days}),
        return_exceptions=True)
    if isinstance(spot_r, BaseException):
        raise spot_r
    spot_btc = {int(v["updateTime"]): _f((v.get("data") or {}).get("totalAssetOfBtc"))
                for v in spot_r.get("snapshotVos") or []}
    fut = {}
    if not isinstance(fut_r, BaseException):
        for v in fut_r.get("snapshotVos") or []:
            fut[int(v["updateTime"]) // 86_400_000] = sum(
                _f(a.get("marginBalance") or a.get("walletBalance"))
                for a in (v.get("data") or {}).get("assets") or [] if a.get("asset") in STABLE)
    if not spot_btc:
        return []
    t0 = min(spot_btc) - 2 * 86_400_000
    try:
        cs = await exchange.klines("BTCUSDT", t0, limit=40, tf="1d", end_ms=max(spot_btc) + 86_400_000)
        btc = {c.open_ms // 86_400_000: float(c.close) for c in cs}
    except Exception:
        btc = {}
    out = []
    for ts, b in sorted(spot_btc.items()):
        day = ts // 86_400_000
        px = btc.get(day) or btc.get(day - 1)
        if px is None and b > 0:
            continue
        sp = b * (px or 0)
        fu = fut.get(day, 0.0)
        out.append((ts, sp + fu, sp, fu))
    return out


async def history(ex: str, k: dict) -> list:
    """Birjaning o'z tarixi (hozircha faqat Binance beradi); qolganlari — bo'sh."""
    if ex == "binance":
        return await bn_history(k)
    return []


# ─────────────────────────── 329: savdolar tarixi ───────────────────────────
QUOTES = ("USDT", "FDUSD", "USDC")


async def bn_fut_trades(k, days: int = 180) -> dict:
    """Fyuchers yopilgan savdolari — `/fapi/v1/income` (REALIZED_PNL, COMMISSION,
    FUNDING_FEE), 7 kunlik oynalar bilan `days` kungacha. Bir yopilishning bir
    nechta fill'i (60 s ichida, bir juftlik) bitta qatorga birlashtiriladi."""
    now = _ms()
    wins = []
    t = now - days * 86_400_000
    while t < now:
        wins.append((t, min(t + 7 * 86_400_000 - 1, now)))
        t += 7 * 86_400_000
    sem = asyncio.Semaphore(4)

    async def one(a, b):
        out, start = [], a
        async with sem:
            for _ in range(5):
                try:
                    d = await _bn(k, "https://fapi.binance.com", "/fapi/v1/income",
                                  {"startTime": start, "endTime": b, "limit": 1000})
                except ApiErr as e:
                    if e.code == "auth":
                        raise
                    return out
                if not isinstance(d, list) or not d:
                    break
                out += d
                if len(d) < 1000:
                    break
                start = int(d[-1]["time"]) + 1
        return out

    res = await asyncio.gather(*(one(a, b) for a, b in wins), return_exceptions=True)
    for r in res:
        if isinstance(r, ApiErr) and r.code == "auth":
            raise r
    rows = [x for r in res if isinstance(r, list) for x in r]
    rows.sort(key=lambda x: int(x.get("time") or 0))
    events, by_trade, funding = [], {}, 0.0
    for x in rows:
        typ, sym, tm = x.get("incomeType"), x.get("symbol") or "", int(x.get("time") or 0)
        val = _f(x.get("income"))
        if typ == "FUNDING_FEE":
            funding += val
        elif typ == "REALIZED_PNL":
            ev = events[-1] if events else None
            if not (ev and ev["sym"] == sym and tm - ev["t"] <= 60_000):
                ev = {"sym": sym, "t": tm, "pnl": 0.0, "fee": 0.0, "n": 0}
                events.append(ev)
            ev["pnl"] += val
            ev["n"] += 1
            ev["t"] = tm
            if x.get("tradeId"):
                by_trade[(sym, str(x["tradeId"]))] = ev
    for x in rows:
        if x.get("incomeType") == "COMMISSION":
            ev = by_trade.get((x.get("symbol") or "", str(x.get("tradeId") or "")))
            if ev is not None:
                ev["fee"] += _f(x.get("income"))
    events.reverse()
    pnl = sum(e["pnl"] for e in events)
    fees = sum(_f(x.get("income")) for x in rows if x.get("incomeType") == "COMMISSION")
    wins_n = sum(1 for e in events if e["pnl"] > 0)
    return {"items": events[:500], "pnl": pnl, "fees": fees, "funding": funding,
            "n": len(events), "wins": wins_n, "days": days}


async def bn_spot_trades(k) -> dict:
    """Spot savdolar — `/api/v3/myTrades` faqat juftlik bo'yicha. Nomzodlar: hozirgi
    va oxirgi 30 kun ichida hisobda bo'lgan aktivlar × USDT/FDUSD/USDC.
    Fill'lar `orderId` bo'yicha bitta qatorga birlashtiriladi."""
    assets = set()
    try:
        for a, q in (await bn_spot(k)).items():
            if q > 0:
                assets.add(a)
    except ApiErr as e:
        if e.code == "auth":
            raise
    try:
        snap = await _bn(k, "https://api.binance.com", "/sapi/v1/accountSnapshot",
                         {"type": "SPOT", "limit": 30})
        for v in snap.get("snapshotVos") or []:
            for b in (v.get("data") or {}).get("balances") or []:
                if _f(b.get("free")) + _f(b.get("locked")) > 0:
                    assets.add(b.get("asset"))
    except ApiErr:
        pass
    assets = {a for a in assets if a and a not in STABLE and a not in ("BNB_OLD",)}
    pairs = [a + q for a in sorted(assets)[:40] for q in QUOTES]
    sem = asyncio.Semaphore(5)

    async def one(sym):
        async with sem:
            try:
                return await _bn(k, "https://api.binance.com", "/api/v3/myTrades",
                                 {"symbol": sym, "limit": 1000})
            except ApiErr as e:
                if e.code == "auth":
                    raise
                return []
    res = await asyncio.gather(*(one(p) for p in pairs), return_exceptions=True)
    for r in res:
        if isinstance(r, ApiErr) and r.code == "auth":
            raise r
    orders = {}
    for r in res:
        if not isinstance(r, list):
            continue
        for x in r:
            key = (x.get("symbol"), x.get("orderId"))
            o = orders.get(key)
            if o is None:
                o = orders[key] = {"sym": x.get("symbol"), "side": "buy" if x.get("isBuyer") else "sell",
                                   "qty": 0.0, "quote": 0.0, "t": 0, "fee": 0.0, "fee_a": x.get("commissionAsset")}
            o["qty"] += _f(x.get("qty"))
            o["quote"] += _f(x.get("quoteQty"))
            o["fee"] += _f(x.get("commission"))
            o["t"] = max(o["t"], int(x.get("time") or 0))
    items = sorted(orders.values(), key=lambda o: -o["t"])
    for o in items:
        o["price"] = o["quote"] / o["qty"] if o["qty"] else 0.0
    return {"items": items[:500], "n": len(items), "pairs": len(pairs)}


async def trades(ex: str, k: dict) -> dict | None:
    """Savdolar tarixi (hozircha faqat Binance). None — birja qo'llab-quvvatlanmaydi."""
    if ex != "binance":
        return None
    fut, spot = await asyncio.gather(bn_fut_trades(k), bn_spot_trades(k), return_exceptions=True)
    for r in (fut, spot):
        if isinstance(r, ApiErr) and r.code in ("auth", "geo"):
            raise r
    return {"fut": fut if isinstance(fut, dict) else None,
            "spot": spot if isinstance(spot, dict) else None}


# ─────────────────────────── 330: savdo (Binance Spot + USDT-M Futures) ───────────────────────────
# Real pul. Har amal: ruxsat tekshiruvi (apiRestrictions), birja filtrlari bo'yicha
# yaxlitlash (LOT_SIZE/PRICE_FILTER), xatoda birjaning o'z xabari qaytariladi.
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

TRADE_EX = ("binance", "bitget", "bingx", "mexc")   # 355: hammasida savdo
SAPI = "https://api.binance.com"
FAPI = "https://fapi.binance.com"


async def _bn_send(k, base, path, method, params) -> object:
    q = urlencode({**params, "recvWindow": 10000, "timestamp": _ms()})
    q += "&signature=" + _hex(k["secret"], q)
    d = await _req(method, base + path, {"X-MBX-APIKEY": k["key"]}, q)
    if isinstance(d, dict) and isinstance(d.get("code"), int) and d["code"] < 0:
        raise ApiErr("auth" if d["code"] in (-2014, -2015, -1022, -2008) else "api",
                     json.dumps(d)[:200])
    return d


async def bn_trade_perms(k) -> dict:
    d = await _bn(k, SAPI, "/sapi/v1/account/apiRestrictions")
    return {"spot": bool(d.get("enableSpotAndMarginTrading")), "fut": bool(d.get("enableFutures"))}


def _dec(x) -> Decimal:
    return Decimal(str(x))


def _floor(x, step) -> Decimal:
    st = _dec(step)
    if st <= 0:
        return _dec(x)
    return (_dec(x) / st).to_integral_value(ROUND_DOWN) * st


def _round(x, step) -> Decimal:
    st = _dec(step)
    if st <= 0:
        return _dec(x)
    return (_dec(x) / st).to_integral_value(ROUND_HALF_UP) * st


def _s(d: Decimal) -> str:
    t = format(d.normalize(), "f")
    return t if t not in ("-0",) else "0"


_FX: dict = {}           # (mkt, sym) -> (ts, filters)
_FX_FUT_AT = 0.0


def _parse_filters(sym_info: dict) -> dict:
    out = {"step": 0.0, "min_qty": 0.0, "mstep": 0.0, "tick": 0.0, "min_notional": 0.0,
           "base": sym_info.get("baseAsset"), "quote": sym_info.get("quoteAsset"),
           "status": sym_info.get("status")}
    for f in sym_info.get("filters") or []:
        t = f.get("filterType")
        if t == "LOT_SIZE":
            out["step"], out["min_qty"] = _f(f.get("stepSize")), _f(f.get("minQty"))
        elif t == "MARKET_LOT_SIZE":
            out["mstep"] = _f(f.get("stepSize"))
        elif t == "PRICE_FILTER":
            out["tick"] = _f(f.get("tickSize"))
        elif t in ("MIN_NOTIONAL", "NOTIONAL"):
            out["min_notional"] = _f(f.get("minNotional") or f.get("notional"))
    if not out["mstep"]:
        out["mstep"] = out["step"]
    return out


async def bn_filters(mkt: str, sym: str) -> dict:
    global _FX_FUT_AT
    now = time.time()
    hit = _FX.get((mkt, sym))
    if hit and now - hit[0] < 3600:
        return hit[1]
    if mkt == "spot":
        d = await _get(SAPI + "/api/v3/exchangeInfo", {}, "symbol=" + sym)
        lst = d.get("symbols") or []
        if not lst:
            raise ApiErr("api", f"{sym}: Binance Spot'da bunday juftlik yo'q")
        fx = _parse_filters(lst[0])
        _FX[(mkt, sym)] = (now, fx)
        return fx
    if now - _FX_FUT_AT > 3600 or not any(k[0] == "fut" for k in _FX):
        d = await _get(FAPI + "/fapi/v1/exchangeInfo", {})
        for si in d.get("symbols") or []:
            _FX[("fut", si["symbol"])] = (now, _parse_filters(si))
        _FX_FUT_AT = now
    hit = _FX.get(("fut", sym))
    if not hit:
        raise ApiErr("api", f"{sym}: Binance Futures'da bunday juftlik yo'q")
    return hit[1]


async def _bn_price(mkt: str, sym: str) -> float:
    if mkt == "spot":
        d = await _get(SAPI + "/api/v3/ticker/price", {}, "symbol=" + sym)
        return _f(d.get("price"))
    d = await _get(FAPI + "/fapi/v1/premiumIndex", {}, "symbol=" + sym)
    return _f(d.get("markPrice"))


async def _bn_dual(k) -> bool:
    d = await _bn(k, FAPI, "/fapi/v1/positionSide/dual")
    return bool(d.get("dualSidePosition"))


def _sym(a) -> str:
    s = str(a.get("sym") or "").upper().replace("/", "").replace("-", "")
    if not s.isascii() or not s.isalnum() or not (1 <= len(s) <= 20):
        raise ApiErr("bad", "symbol")
    s = s if s.endswith(("USDT", "USDC", "FDUSD")) and len(s) > 5 else s + "USDT"
    if len(s) > 24:
        raise ApiErr("bad", "symbol")
    return s


def _pos(a, key, required=True, lo=0.0, hi=1e15) -> float | None:
    v = a.get(key)
    if v in (None, ""):
        if required:
            raise ApiErr("bad", key)
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ApiErr("bad", key)
    if not (lo < x <= hi):
        raise ApiErr("bad", key)
    return x


def _need(perms: dict, mkt: str):
    if not perms.get(mkt):
        raise ApiErr("noperm", mkt)


async def bn_info(k, a) -> dict:
    """Savdo formasi uchun: narx, filtrlar, mavjud mablag', joriy leveraj, rejim."""
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    fx, px, perms = await asyncio.gather(bn_filters(mkt, sym), _bn_price(mkt, sym), bn_trade_perms(k))
    out = {"mkt": mkt, "sym": sym, "price": px, "fx": fx, "perm": perms}
    if mkt == "spot":
        bal = await bn_spot(k)
        out["avail"] = {"quote": bal.get(fx["quote"], 0.0), "base": bal.get(fx["base"], 0.0)}
    else:
        acc, pr, dual = await asyncio.gather(
            _bn(k, FAPI, "/fapi/v2/account"),
            _bn(k, FAPI, "/fapi/v2/positionRisk", {"symbol": sym}),
            _bn_dual(k))
        out["avail"] = {"quote": _f(acc.get("availableBalance"))}
        out["lev"] = int(_f((pr[0] if isinstance(pr, list) and pr else {}).get("leverage")) or 0) or None
        out["dual"] = dual
    return out


async def bn_spot_order(k, a) -> dict:
    _need(await bn_trade_perms(k), "spot")
    sym = _sym(a)
    side = "BUY" if a.get("side") == "buy" else "SELL"
    typ = "LIMIT" if a.get("type") == "limit" else "MARKET"
    fx = await bn_filters("spot", sym)
    p = {"symbol": sym, "side": side, "type": typ, "newOrderRespType": "RESULT"}
    if typ == "LIMIT":
        price = _round(_pos(a, "price"), fx["tick"])
        p["price"], p["timeInForce"] = _s(price), "GTC"
        if side == "BUY" and a.get("qty") in (None, ""):
            qty = _floor(_dec(_pos(a, "quote")) / price, fx["step"])
        else:
            qty = _floor(_pos(a, "qty"), fx["step"])
        if qty <= 0:
            raise ApiErr("small", "qty")
        p["quantity"] = _s(qty)
    elif side == "BUY" and a.get("qty") in (None, ""):
        p["quoteOrderQty"] = _s(_floor(_pos(a, "quote"), "0.01"))
    else:
        qty = _floor(_pos(a, "qty"), fx["mstep"] or fx["step"])
        if qty <= 0:
            raise ApiErr("small", "qty")
        p["quantity"] = _s(qty)
    d = await _bn_send(k, SAPI, "/api/v3/order", "POST", p)
    return {"id": d.get("orderId"), "status": d.get("status"), "filled": _f(d.get("executedQty")),
            "quote": _f(d.get("cummulativeQuoteQty")), "sym": sym, "side": side.lower(), "type": typ.lower()}


async def bn_spot_open(k, a=None) -> list:
    d = await _bn(k, SAPI, "/api/v3/openOrders")
    return [{"sym": o["symbol"], "id": o["orderId"], "side": o["side"].lower(), "type": o["type"].lower(),
             "price": _f(o.get("price")), "qty": _f(o.get("origQty")), "filled": _f(o.get("executedQty")),
             "t": int(o.get("time") or 0)} for o in (d if isinstance(d, list) else [])]


async def bn_spot_cancel(k, a) -> dict:
    sym = _sym(a)
    oid = int(_pos(a, "id"))
    d = await _bn_send(k, SAPI, "/api/v3/order", "DELETE", {"symbol": sym, "orderId": oid})
    return {"id": d.get("orderId"), "status": d.get("status")}


async def _bn_cond(k, sym, side_close, typ, trigger, ps=None) -> dict:
    """Shartli yopish orderi (TP/SL, closePosition). 2025-12 dan Binance shartli
    orderlarni Algo API'ga ko'chirgan — avval o'sha, endpoint bo'lmasa eski usul."""
    p = {"algoType": "CONDITIONAL", "symbol": sym, "side": side_close, "type": typ,
         "triggerPrice": trigger, "closePosition": "true", "workingType": "MARK_PRICE"}
    if ps and ps != "BOTH":
        p["positionSide"] = ps
    try:
        return await _bn_send(k, FAPI, "/fapi/v1/algoOrder", "POST", p)
    except ApiErr as e:
        if e.code == "auth" or not ("404" in e.text or "Not Found" in e.text or "-1102" in e.text
                                    or "-1100" in e.text):
            raise
    p2 = {"symbol": sym, "side": side_close, "type": typ, "stopPrice": trigger,
          "closePosition": "true", "workingType": "MARK_PRICE"}
    if ps and ps != "BOTH":
        p2["positionSide"] = ps
    return await _bn_send(k, FAPI, "/fapi/v1/order", "POST", p2)


async def _bn_set_tpsl(k, sym, side, tp, sl, ps, fx) -> list:
    """side — pozitsiya tomoni (long/short). Xatolar ro'yxat bo'lib qaytadi (asosiy order bekor bo'lmaydi)."""
    close = "SELL" if side == "long" else "BUY"
    warn = []
    for typ, val in (("TAKE_PROFIT_MARKET", tp), ("STOP_MARKET", sl)):
        if val is None:
            continue
        try:
            await _bn_cond(k, sym, close, typ, _s(_round(val, fx["tick"])), ps)
        except ApiErr as e:
            warn.append(("TP" if typ.startswith("TAKE") else "SL") + ": " + e.text[:120])
    return warn


async def bn_fut_order(k, a) -> dict:
    _need(await bn_trade_perms(k), "fut")
    sym = _sym(a)
    side = "long" if a.get("side") == "long" else "short"
    typ = "LIMIT" if a.get("type") == "limit" else "MARKET"
    margin = _pos(a, "margin")
    lev = int(_pos(a, "lev", hi=125))
    tp, sl = _pos(a, "tp", False), _pos(a, "sl", False)
    fx, dual = await asyncio.gather(bn_filters("fut", sym), _bn_dual(k))
    await _bn_send(k, FAPI, "/fapi/v1/leverage", "POST", {"symbol": sym, "leverage": lev})
    if typ == "LIMIT":
        price = _round(_pos(a, "price"), fx["tick"])
    else:
        price = _dec(await _bn_price("fut", sym))
    if price <= 0:
        raise ApiErr("api", "price")
    qty = _floor(_dec(margin) * lev / price, fx["mstep"] if typ == "MARKET" else fx["step"])
    if qty <= 0 or float(qty) < fx["min_qty"]:
        raise ApiErr("small", f"min {fx['min_qty']}")
    ps = ("LONG" if side == "long" else "SHORT") if dual else None
    p = {"symbol": sym, "side": "BUY" if side == "long" else "SELL", "type": typ,
         "quantity": _s(qty), "newOrderRespType": "RESULT"}
    if typ == "LIMIT":
        p["price"], p["timeInForce"] = _s(price), "GTC"
    if ps:
        p["positionSide"] = ps
    d = await _bn_send(k, FAPI, "/fapi/v1/order", "POST", p)
    warn = await _bn_set_tpsl(k, sym, side, tp, sl, ps or "BOTH", fx) if (tp or sl) else []
    return {"id": d.get("orderId"), "status": d.get("status"), "qty": float(qty),
            "avg": _f(d.get("avgPrice")), "sym": sym, "side": side, "type": typ.lower(),
            "lev": lev, "warn": warn}


async def _bn_position(k, sym, ps=None) -> dict | None:
    pr = await _bn(k, FAPI, "/fapi/v2/positionRisk", {"symbol": sym})
    for p in pr if isinstance(pr, list) else []:
        if _f(p.get("positionAmt")) and (not ps or ps == "BOTH" or p.get("positionSide") == ps):
            return p
    return None


async def bn_fut_close(k, a) -> dict:
    _need(await bn_trade_perms(k), "fut")
    sym = _sym(a)
    frac = _pos(a, "frac", hi=1.0)
    ps = str(a.get("ps") or "BOTH").upper()
    p = await _bn_position(k, sym, ps)
    if p is None:
        raise ApiErr("nopos", sym)
    amt = _dec(p["positionAmt"])
    fx = await bn_filters("fut", sym)
    qty = abs(amt) if frac >= 0.999 else _floor(abs(amt) * _dec(frac), fx["mstep"])
    if qty <= 0:
        raise ApiErr("small", "qty")
    o = {"symbol": sym, "side": "SELL" if amt > 0 else "BUY", "type": "MARKET",
         "quantity": _s(qty), "newOrderRespType": "RESULT"}
    pps = p.get("positionSide") or "BOTH"
    if pps != "BOTH":
        o["positionSide"] = pps
    else:
        o["reduceOnly"] = "true"
    d = await _bn_send(k, FAPI, "/fapi/v1/order", "POST", o)
    return {"id": d.get("orderId"), "status": d.get("status"), "qty": float(qty),
            "avg": _f(d.get("avgPrice")), "sym": sym}


async def bn_fut_open(k, a=None) -> list:
    reg, alg = await asyncio.gather(_bn(k, FAPI, "/fapi/v1/openOrders"),
                                    _bn(k, FAPI, "/fapi/v1/openAlgoOrders"), return_exceptions=True)
    out = []
    for o in reg if isinstance(reg, list) else []:
        out.append({"sym": o["symbol"], "id": o["orderId"], "algo": False, "side": o["side"].lower(),
                    "type": o.get("type", "").lower(), "price": _f(o.get("price")),
                    "trigger": _f(o.get("stopPrice")) or None, "qty": _f(o.get("origQty")),
                    "close": bool(o.get("closePosition")), "ps": o.get("positionSide") or "BOTH",
                    "t": int(o.get("time") or 0)})
    lst = alg if isinstance(alg, list) else (alg.get("orders") or alg.get("data") or []) if isinstance(alg, dict) else []
    for o in lst:
        out.append({"sym": o.get("symbol"), "id": o.get("algoId"), "algo": True,
                    "side": str(o.get("side") or "").lower(),
                    "type": str(o.get("orderType") or o.get("type") or "").lower(),
                    "price": _f(o.get("price")), "trigger": _f(o.get("triggerPrice") or o.get("stopPrice")) or None,
                    "qty": _f(o.get("quantity")), "close": str(o.get("closePosition")).lower() == "true",
                    "ps": o.get("positionSide") or "BOTH", "t": int(o.get("createTime") or 0)})
    out.sort(key=lambda x: -x["t"])
    return out


async def bn_fut_cancel(k, a) -> dict:
    sym = _sym(a)
    oid = int(_pos(a, "id"))
    if a.get("algo"):
        d = await _bn_send(k, FAPI, "/fapi/v1/algoOrder", "DELETE", {"algoId": oid})
    else:
        d = await _bn_send(k, FAPI, "/fapi/v1/order", "DELETE", {"symbol": sym, "orderId": oid})
    return {"id": oid, "status": (d or {}).get("status") if isinstance(d, dict) else None}


async def bn_fut_tpsl(k, a) -> dict:
    """Pozitsiya TP/SL: eski TP/SL (closePosition shartli orderlar) bekor qilinadi,
    berilganlari yangidan qo'yiladi. Bo'sh — olib tashlanadi."""
    _need(await bn_trade_perms(k), "fut")
    sym = _sym(a)
    ps = str(a.get("ps") or "BOTH").upper()
    tp, sl = _pos(a, "tp", False), _pos(a, "sl", False)
    p = await _bn_position(k, sym, ps)
    if p is None:
        raise ApiErr("nopos", sym)
    side = "long" if _f(p["positionAmt"]) > 0 else "short"
    pps = p.get("positionSide") or "BOTH"
    for o in await bn_fut_open(k):
        if o["sym"] == sym and o["trigger"] and (o["close"] or o["type"] in ("take_profit_market", "stop_market")) \
                and (pps == "BOTH" or o["ps"] == pps):
            try:
                await bn_fut_cancel(k, {"sym": sym, "id": o["id"], "algo": o["algo"]})
            except ApiErr as e:
                log.info("Eski TP/SL bekor qilinmadi (%s): %s", sym, e.text[:120])
    fx = await bn_filters("fut", sym)
    warn = await _bn_set_tpsl(k, sym, side, tp, sl, pps, fx)
    return {"sym": sym, "tp": tp, "sl": sl, "warn": warn}


async def bn_depth(k, a) -> dict:
    """339: order book (10 daraja) + 24 soatlik o'zgarish — ochiq ma'lumot, imzosiz."""
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    if mkt == "spot":
        d, t = await asyncio.gather(_get(SAPI + "/api/v3/depth", {}, f"symbol={sym}&limit=10"),
                                    _get(SAPI + "/api/v3/ticker/24hr", {}, f"symbol={sym}"))
    else:
        d, t = await asyncio.gather(_get(FAPI + "/fapi/v1/depth", {}, f"symbol={sym}&limit=10"),
                                    _get(FAPI + "/fapi/v1/ticker/24hr", {}, f"symbol={sym}"))
    cv = lambda L: [[_f(x[0]), _f(x[1])] for x in (L or [])[:10]]
    return {"sym": sym, "mkt": mkt, "bids": cv(d.get("bids")), "asks": cv(d.get("asks")),
            "last": _f(t.get("lastPrice")), "chg": _f(t.get("priceChangePercent"))}


async def bn_fut_modify(k, a) -> dict:
    """342: futures limit order narxini o'zgartirish (grafikda chiziqni surish) — PUT /fapi/v1/order."""
    _need(await bn_trade_perms(k), "fut")
    sym = _sym(a)
    oid = int(_pos(a, "id"))
    fx = await bn_filters("fut", sym)
    price = _s(_round(_pos(a, "price"), fx["tick"]))
    o = await _bn(k, FAPI, "/fapi/v1/order", {"symbol": sym, "orderId": oid})
    if str(o.get("type")).upper() != "LIMIT":
        raise ApiErr("bad", "faqat LIMIT orderni surish mumkin")
    d = await _bn_send(k, FAPI, "/fapi/v1/order", "PUT", {
        "symbol": sym, "orderId": oid, "side": o["side"], "quantity": o["origQty"], "price": price})
    return {"id": oid, "price": _f(price), "status": (d or {}).get("status") if isinstance(d, dict) else None}


async def bn_spot_modify(k, a) -> dict:
    """342: spot limit order narxini o'zgartirish — cancelReplace (bekor qilish + yangi, bir so'rovda)."""
    _need(await bn_trade_perms(k), "spot")
    sym = _sym(a)
    oid = int(_pos(a, "id"))
    fx = await bn_filters("spot", sym)
    price = _s(_round(_pos(a, "price"), fx["tick"]))
    o = await _bn(k, SAPI, "/api/v3/order", {"symbol": sym, "orderId": oid})
    if str(o.get("type")).upper() not in ("LIMIT", "LIMIT_MAKER"):
        raise ApiErr("bad", "faqat LIMIT orderni surish mumkin")
    qty = _floor(_f(o.get("origQty")) - _f(o.get("executedQty")), fx["step"])
    if qty <= 0:
        raise ApiErr("small", sym)
    d = await _bn_send(k, SAPI, "/api/v3/order/cancelReplace", "POST", {
        "symbol": sym, "side": o["side"], "type": "LIMIT", "timeInForce": "GTC",
        "cancelReplaceMode": "STOP_ON_FAILURE", "cancelOrderId": oid,
        "quantity": _s(qty), "price": price})
    nr = (d or {}).get("newOrderResponse") or {} if isinstance(d, dict) else {}
    return {"id": nr.get("orderId"), "price": _f(price), "status": nr.get("status")}


# ─── 343: boshqa birjalar order book'i (ochiq, imzosiz) — Savdo ekrani uchun ───
def _lv(L, mul=1.0) -> list:
    out = []
    for x in L or []:
        try:
            p, q = float(x[0]), float(x[1]) * mul
        except (TypeError, ValueError, IndexError):
            continue
        if p > 0:
            out.append([p, q])
    return out


def _book(sym, mkt, bids, asks, last, chg) -> dict:
    bids = sorted(bids, key=lambda x: -x[0])[:10]
    asks = sorted(asks, key=lambda x: x[0])[:10]
    if not last and bids and asks:
        last = (bids[0][0] + asks[0][0]) / 2
    return {"sym": sym, "mkt": mkt, "bids": bids, "asks": asks, "last": last, "chg": round(chg or 0.0, 2)}


def _chg(last, opn, ratio=None) -> float:
    last, opn = _f(last), _f(opn)
    if last and opn:
        return (last / opn - 1) * 100
    return _f(ratio) * 100 if ratio is not None else 0.0


def _data(d):
    return d.get("data") if isinstance(d, dict) else None


def _first(x):
    return (x[0] if x else {}) if isinstance(x, list) else (x or {})


BGAPI, MXAPI, MXFAPI, BXAPI = ("https://api.bitget.com", "https://api.mexc.com",
                               "https://contract.mexc.com", "https://open-api.bingx.com")


async def bg_depth(k, a) -> dict:
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    if mkt == "spot":
        d, t = await asyncio.gather(_get(BGAPI + "/api/v2/spot/market/orderbook", {}, f"symbol={sym}&type=step0&limit=15"),
                                    _get(BGAPI + "/api/v2/spot/market/tickers", {}, f"symbol={sym}"))
    else:
        q = f"symbol={sym}&productType=USDT-FUTURES"
        d, t = await asyncio.gather(_get(BGAPI + "/api/v2/mix/market/merge-depth", {}, q + "&limit=15"),
                                    _get(BGAPI + "/api/v2/mix/market/ticker", {}, q))
    b, tk = _data(d) or {}, _first(_data(t))
    if not b:
        raise ApiErr("api", json.dumps(d)[:200])
    return _book(sym, mkt, _lv(b.get("bids")), _lv(b.get("asks")), _f(tk.get("lastPr")),
                 _chg(tk.get("lastPr"), tk.get("open") or tk.get("open24h"), tk.get("change24h")))


async def mx_depth(k, a) -> dict:
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    if mkt == "spot":
        d, t = await asyncio.gather(_get(MXAPI + "/api/v3/depth", {}, f"symbol={sym}&limit=10"),
                                    _get(MXAPI + "/api/v3/ticker/24hr", {}, f"symbol={sym}"))
        if not isinstance(d, dict) or "bids" not in d:
            raise ApiErr("api", json.dumps(d)[:200])
        return _book(sym, mkt, _lv(d.get("bids")), _lv(d.get("asks")), _f(t.get("lastPrice")),
                     _chg(t.get("lastPrice"), t.get("openPrice"), t.get("priceChangePercent")))
    cs = sym[:-4] + "_USDT"
    d, t = await asyncio.gather(_get(MXFAPI + "/api/v1/contract/depth/" + cs, {}, "limit=10"),
                                _get(MXFAPI + "/api/v1/contract/ticker", {}, "symbol=" + cs))
    b, tk = _data(d) or {}, _first(_data(t))
    if not b:
        raise ApiErr("api", json.dumps(d)[:200])
    m = await _mx_contract_size(cs)
    return _book(sym, mkt, _lv(b.get("bids"), m), _lv(b.get("asks"), m), _f(tk.get("lastPrice")),
                 _chg(None, None, tk.get("riseFallRate")))


async def bx_depth(k, a) -> dict:
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    bs = sym[:-4] + "-" + sym[-4:]
    ts = f"&timestamp={_ms()}"
    if mkt == "spot":
        d, t = await asyncio.gather(_get(BXAPI + "/openApi/spot/v1/market/depth", {}, f"symbol={bs}&limit=10" + ts),
                                    _get(BXAPI + "/openApi/spot/v1/ticker/24hr", {}, f"symbol={bs}" + ts))
    else:
        d, t = await asyncio.gather(_get(BXAPI + "/openApi/swap/v2/quote/depth", {}, f"symbol={bs}&limit=10" + ts),
                                    _get(BXAPI + "/openApi/swap/v2/quote/ticker", {}, f"symbol={bs}" + ts))
    b, tk = _data(d) or {}, _first(_data(t))
    if not b:
        raise ApiErr("api", json.dumps(d)[:200])
    pc = str(tk.get("priceChangePercent") or "").rstrip("%")
    return _book(sym, mkt, _lv(b.get("bids")), _lv(b.get("asks")), _f(tk.get("lastPrice")),
                 _chg(tk.get("lastPrice"), tk.get("openPrice"), (_f(pc) / 100) if pc else None))


DEPTH_EX = {"binance": None, "bitget": bg_depth, "mexc": mx_depth, "bingx": bx_depth}


# ═══════════════════ 355: Bitget, BingX, MEXC — ilova ichida savdo (Binance bilan teng) ═══════════════════
# Javob shakllari Binance'nikidek: info {mkt,sym,price,fx,perm,avail,lev,dual}, order {id,status,...,warn},
# open [{sym,id,algo,side,type,price,trigger,qty,close,ps,t,filled}]. Order ID — MATN (Bitget/BingX 19 xonali).

def _oid(a) -> str:
    v = str(a.get("id") or "").strip()
    if not v or len(v) > 40 or not all(ch.isalnum() or ch in "_-" for ch in v) or not v.isascii():
        raise ApiErr("bad", "id")
    return v


def _prec_step(p) -> float:
    """Aniqlik (xonalar soni) → qadam: 4 → 0.0001."""
    try:
        n = int(float(p))
    except (TypeError, ValueError):
        return 0.0
    return 10 ** (-n) if n >= 0 else 0.0


async def _xprice(ex: str, mkt: str, sym: str) -> float:
    d = await DEPTH_EX[ex](None, {"mkt": mkt, "sym": sym})
    return _f(d.get("last"))


# ─────────────── Bitget v2 (yozish: JSON body bilan imzo) ───────────────

async def _bg_send(k, path, body: dict | None = None, method="POST", params: dict | None = None):
    q = urlencode(params or {})
    raw = json.dumps(body or {}, separators=(",", ":")) if method != "GET" else ""
    ts = str(_ms())
    pre = ts + method + path + ("?" + q if q else "") + raw
    sign = base64.b64encode(hmac.new(k["secret"].encode(), pre.encode(), hashlib.sha256).digest()).decode()
    d = await _req(method, "https://api.bitget.com" + path,
                   {"ACCESS-KEY": k["key"], "ACCESS-SIGN": sign, "ACCESS-TIMESTAMP": ts,
                    "ACCESS-PASSPHRASE": k.get("pass") or "", "Content-Type": "application/json",
                    "locale": "en-US"}, q, raw or None)
    if not isinstance(d, dict) or d.get("code") != "00000":
        code = str(d.get("code")) if isinstance(d, dict) else ""
        raise ApiErr("auth" if code in ("40006", "40009", "40012", "40037", "40038", "40014") else "api",
                     json.dumps(d)[:200] if isinstance(d, dict) else str(d)[:200])
    return d.get("data")


_BG_PT = {"productType": "USDT-FUTURES"}


async def bg_trade_perms(k) -> dict:
    try:
        d = await _bg(k, "/api/v2/spot/account/info") or {}
    except ApiErr as e:
        if e.code == "auth":
            raise
        return {"spot": True, "fut": True}
    auth = [str(a).lower() for a in (d.get("authorities") or [])]
    if not auth:
        return {"spot": True, "fut": True}
    spot = any(a in ("stow", "trade", "spot_trade") or a.startswith("stow") for a in auth)
    fut = any(a in ("coow", "trade", "contract_trade", "mix_trade") or a.startswith("coow") for a in auth)
    return {"spot": spot, "fut": fut}


async def bg_filters(mkt: str, sym: str) -> dict:
    hit = _FX.get(("bg" + mkt, sym))
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    if mkt == "spot":
        d = await _get("https://api.bitget.com/api/v2/spot/public/symbols", {}, "symbol=" + sym)
        lst = d.get("data") or []
        if not lst:
            raise ApiErr("api", f"{sym}: Bitget Spot'da bunday juftlik yo'q")
        s = lst[0]
        fx = {"step": _prec_step(s.get("quantityPrecision")), "tick": _prec_step(s.get("pricePrecision")),
              "min_qty": _f(s.get("minTradeAmount")), "min_notional": _f(s.get("minTradeUSDT")),
              "base": s.get("baseCoin"), "quote": s.get("quoteCoin")}
    else:
        d = await _get("https://api.bitget.com/api/v2/mix/market/contracts", {},
                       urlencode({**_BG_PT, "symbol": sym}))
        lst = d.get("data") or []
        if not lst:
            raise ApiErr("api", f"{sym}: Bitget Futures'da bunday juftlik yo'q")
        s = lst[0]
        mult = _f(s.get("sizeMultiplier")) or _prec_step(s.get("volumePlace"))
        fx = {"step": mult, "tick": _prec_step(s.get("pricePlace")) * (_f(s.get("priceEndStep")) or 1),
              "min_qty": _f(s.get("minTradeNum")), "min_notional": _f(s.get("minTradeUSDT")),
              "base": s.get("baseCoin"), "quote": "USDT"}
    fx["mstep"] = fx["step"]
    _FX[("bg" + mkt, sym)] = (time.time(), fx)
    return fx


async def _bg_facc(k, sym) -> dict:
    return await _bg(k, "/api/v2/mix/account/account", {**_BG_PT, "symbol": sym, "marginCoin": "USDT"}) or {}


async def bg_info(k, a) -> dict:
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    fx, px, perms = await asyncio.gather(bg_filters(mkt, sym), _xprice("bitget", mkt, sym), bg_trade_perms(k))
    out = {"mkt": mkt, "sym": sym, "price": px, "fx": fx, "perm": perms}
    if mkt == "spot":
        bal = await bg_spot(k)
        out["avail"] = {"quote": bal.get(fx["quote"] or "USDT", 0.0), "base": bal.get(fx["base"] or "", 0.0)}
    else:
        acc = await _bg_facc(k, sym)
        out["avail"] = {"quote": _f(acc.get("crossedMaxAvailable") or acc.get("available"))}
        out["lev"] = int(_f(acc.get("crossedMarginLeverage") or acc.get("fixedLongLeverage"))) or None
        out["dual"] = acc.get("posMode") == "hedge_mode"
    return out


async def bg_spot_order(k, a) -> dict:
    _need(await bg_trade_perms(k), "spot")
    sym = _sym(a)
    side = "buy" if a.get("side") == "buy" else "sell"
    typ = "limit" if a.get("type") == "limit" else "market"
    fx = await bg_filters("spot", sym)
    b = {"symbol": sym, "side": side, "orderType": typ, "force": "gtc"}
    if typ == "limit":
        price = _round(_pos(a, "price"), fx["tick"])
        qty = (_floor(_dec(_pos(a, "quote")) / price, fx["step"]) if side == "buy" and a.get("qty") in (None, "")
               else _floor(_pos(a, "qty"), fx["step"]))
        if qty <= 0:
            raise ApiErr("small", "qty")
        b["price"], b["size"] = _s(price), _s(qty)
    elif side == "buy" and a.get("qty") in (None, ""):
        b["size"] = _s(_floor(_pos(a, "quote"), "0.01"))         # market buy — USDT summasi
    else:
        qty = _floor(_pos(a, "qty"), fx["step"])
        if qty <= 0:
            raise ApiErr("small", "qty")
        b["size"] = _s(qty)
    d = await _bg_send(k, "/api/v2/spot/trade/place-order", b) or {}
    return {"id": str(d.get("orderId") or ""), "status": "NEW", "sym": sym, "side": side, "type": typ}


async def bg_spot_open(k, a=None) -> list:
    d = await _bg(k, "/api/v2/spot/trade/unfilled-orders") or []
    return [{"sym": o.get("symbol"), "id": str(o.get("orderId")), "side": str(o.get("side") or "").lower(),
             "type": str(o.get("orderType") or "").lower(), "price": _f(o.get("priceAvg") or o.get("price")),
             "qty": _f(o.get("size")), "filled": _f(o.get("baseVolume")), "t": int(_f(o.get("cTime")))}
            for o in (d if isinstance(d, list) else [])]


async def bg_spot_cancel(k, a) -> dict:
    sym, oid = _sym(a), _oid(a)
    await _bg_send(k, "/api/v2/spot/trade/cancel-order", {"symbol": sym, "orderId": oid})
    return {"id": oid, "status": "CANCELED"}


async def bg_spot_modify(k, a) -> dict:
    _need(await bg_trade_perms(k), "spot")
    sym, oid = _sym(a), _oid(a)
    fx = await bg_filters("spot", sym)
    o = next((x for x in await bg_spot_open(k) if x["id"] == oid), None)
    if o is None:
        raise ApiErr("bad", "order")
    qty = _floor(o["qty"] - o["filled"], fx["step"])
    if qty <= 0:
        raise ApiErr("small", sym)
    price = _s(_round(_pos(a, "price"), fx["tick"]))
    d = await _bg_send(k, "/api/v2/spot/trade/cancel-replace-order",
                       {"symbol": sym, "orderId": oid, "price": price, "size": _s(qty)}) or {}
    return {"id": str(d.get("orderId") or oid), "price": _f(price), "status": "NEW"}


async def _bg_position(k, sym, ps=None) -> dict | None:
    d = await _bg(k, "/api/v2/mix/position/single-position", {**_BG_PT, "symbol": sym, "marginCoin": "USDT"}) or []
    for p in d if isinstance(d, list) else []:
        if _f(p.get("total")) and (not ps or ps == "BOTH" or str(p.get("holdSide")).upper() == ps):
            return p
    return None


async def bg_fut_order(k, a) -> dict:
    _need(await bg_trade_perms(k), "fut")
    sym = _sym(a)
    side = "long" if a.get("side") == "long" else "short"
    typ = "limit" if a.get("type") == "limit" else "market"
    margin, lev = _pos(a, "margin"), int(_pos(a, "lev", hi=125))
    tp, sl = _pos(a, "tp", False), _pos(a, "sl", False)
    fx, acc = await asyncio.gather(bg_filters("fut", sym), _bg_facc(k, sym))
    hedge = acc.get("posMode") == "hedge_mode"
    await _bg_send(k, "/api/v2/mix/account/set-leverage",
                   {**_BG_PT, "symbol": sym, "marginCoin": "USDT", "leverage": str(lev)})
    price = _round(_pos(a, "price"), fx["tick"]) if typ == "limit" else _dec(await _xprice("bitget", "fut", sym))
    if price <= 0:
        raise ApiErr("api", "price")
    qty = _floor(_dec(margin) * lev / price, fx["step"])
    if qty <= 0 or float(qty) < fx["min_qty"]:
        raise ApiErr("small", f"min {fx['min_qty']}")
    b = {**_BG_PT, "symbol": sym, "marginMode": "crossed", "marginCoin": "USDT", "size": _s(qty),
         "side": "buy" if side == "long" else "sell", "orderType": typ, "force": "gtc"}
    if hedge:
        b["tradeSide"] = "open"
    if typ == "limit":
        b["price"] = _s(price)
    if tp:
        b["presetStopSurplusPrice"] = _s(_round(tp, fx["tick"]))
    if sl:
        b["presetStopLossPrice"] = _s(_round(sl, fx["tick"]))
    d = await _bg_send(k, "/api/v2/mix/order/place-order", b) or {}
    return {"id": str(d.get("orderId") or ""), "status": "NEW", "qty": float(qty), "sym": sym, "side": side,
            "type": typ, "lev": lev, "warn": []}


async def bg_fut_close(k, a) -> dict:
    _need(await bg_trade_perms(k), "fut")
    sym = _sym(a)
    frac = _pos(a, "frac", hi=1.0)
    ps = str(a.get("ps") or "BOTH").upper()
    p = await _bg_position(k, sym, ps)
    if p is None:
        raise ApiErr("nopos", sym)
    hold = str(p.get("holdSide") or "long").lower()
    if frac >= 0.999:
        b = {**_BG_PT, "symbol": sym}
        if p.get("posMode") == "hedge_mode":
            b["holdSide"] = hold
        await _bg_send(k, "/api/v2/mix/order/close-positions", b)
        return {"id": "", "status": "FILLED", "qty": _f(p.get("total")), "sym": sym}
    fx = await bg_filters("fut", sym)
    qty = _floor(_dec(p.get("total")) * _dec(frac), fx["step"])
    if qty <= 0:
        raise ApiErr("small", "qty")
    b = {**_BG_PT, "symbol": sym, "marginMode": p.get("marginMode") or "crossed", "marginCoin": "USDT",
         "size": _s(qty), "orderType": "market"}
    if p.get("posMode") == "hedge_mode":
        b.update(side="buy" if hold == "long" else "sell", tradeSide="close")
    else:
        b.update(side="sell" if hold == "long" else "buy", reduceOnly="YES")
    d = await _bg_send(k, "/api/v2/mix/order/place-order", b) or {}
    return {"id": str(d.get("orderId") or ""), "status": "NEW", "qty": float(qty), "sym": sym}


async def bg_fut_open(k, a=None) -> list:
    reg, plan = await asyncio.gather(
        _bg(k, "/api/v2/mix/order/orders-pending", dict(_BG_PT)),
        _bg(k, "/api/v2/mix/order/orders-plan-pending", {**_BG_PT, "planType": "profit_loss"}),
        return_exceptions=True)
    out = []
    for o in ((reg or {}).get("entrustedList") or []) if isinstance(reg, dict) else []:
        out.append({"sym": o.get("symbol"), "id": str(o.get("orderId")), "algo": False,
                    "side": str(o.get("side") or "").lower(), "type": str(o.get("orderType") or "").lower(),
                    "price": _f(o.get("price")), "trigger": None, "qty": _f(o.get("size")),
                    "close": False, "ps": str(o.get("posSide") or "BOTH").upper() if o.get("tradeSide") else "BOTH",
                    "t": int(_f(o.get("cTime")))})
    for o in ((plan or {}).get("entrustedList") or []) if isinstance(plan, dict) else []:
        pt = str(o.get("planType") or "")
        typ = "take_profit_market" if "profit" in pt else "stop_market" if "loss" in pt else pt
        out.append({"sym": o.get("symbol"), "id": str(o.get("orderId")), "algo": True,
                    "side": str(o.get("side") or "").lower(), "type": typ, "price": _f(o.get("executePrice")),
                    "trigger": _f(o.get("triggerPrice")) or None, "qty": _f(o.get("size")),
                    "close": pt.startswith("pos_"), "ps": str(o.get("posSide") or "BOTH").upper(),
                    "plan": pt, "t": int(_f(o.get("cTime")))})
    out.sort(key=lambda x: -x["t"])
    return out


async def bg_fut_cancel(k, a) -> dict:
    sym, oid = _sym(a), _oid(a)
    if a.get("algo"):
        await _bg_send(k, "/api/v2/mix/order/cancel-plan-order",
                       {**_BG_PT, "symbol": sym, "marginCoin": "USDT", "orderIdList": [{"orderId": oid}]})
    else:
        await _bg_send(k, "/api/v2/mix/order/cancel-order", {**_BG_PT, "symbol": sym, "orderId": oid})
    return {"id": oid, "status": "CANCELED"}


async def bg_fut_tpsl(k, a) -> dict:
    _need(await bg_trade_perms(k), "fut")
    sym = _sym(a)
    ps = str(a.get("ps") or "BOTH").upper()
    tp, sl = _pos(a, "tp", False), _pos(a, "sl", False)
    p = await _bg_position(k, sym, ps)
    if p is None:
        raise ApiErr("nopos", sym)
    hold = str(p.get("holdSide") or "long").lower()
    for o in await bg_fut_open(k):
        if o["sym"] == sym and o["algo"] and o.get("plan") in ("pos_profit", "pos_loss", "profit_plan", "loss_plan") \
                and (o["ps"] in ("BOTH", hold.upper()) or not o["ps"]):
            try:
                await bg_fut_cancel(k, {"sym": sym, "id": o["id"], "algo": True})
            except ApiErr as e:
                log.info("Bitget eski TP/SL bekor qilinmadi (%s): %s", sym, e.text[:120])
    fx = await bg_filters("fut", sym)
    warn = []
    if tp or sl:
        b = {**_BG_PT, "symbol": sym, "marginCoin": "USDT", "holdSide": hold}
        if tp:
            b.update(stopSurplusTriggerPrice=_s(_round(tp, fx["tick"])), stopSurplusTriggerType="mark_price")
        if sl:
            b.update(stopLossTriggerPrice=_s(_round(sl, fx["tick"])), stopLossTriggerType="mark_price")
        try:
            await _bg_send(k, "/api/v2/mix/order/place-pos-tpsl", b)
        except ApiErr as e:
            warn.append("TP/SL: " + e.text[:120])
    return {"sym": sym, "tp": tp, "sl": sl, "warn": warn}


async def bg_fut_modify(k, a) -> dict:
    _need(await bg_trade_perms(k), "fut")
    sym, oid = _sym(a), _oid(a)
    fx = await bg_filters("fut", sym)
    o = next((x for x in await bg_fut_open(k) if x["id"] == oid and not x["algo"]), None)
    if o is None or o["type"] != "limit":
        raise ApiErr("bad", "faqat LIMIT orderni surish mumkin")
    price = _s(_round(_pos(a, "price"), fx["tick"]))
    await _bg_send(k, "/api/v2/mix/order/modify-order",
                   {**_BG_PT, "symbol": sym, "marginCoin": "USDT", "orderId": oid,
                    "newClientOid": "tc" + str(_ms()), "newPrice": price, "newSize": _s(_dec(o["qty"]))})
    return {"id": oid, "price": _f(price), "status": "NEW"}


# ─────────────── BingX (yozish: imzolangan query, POST/DELETE) ───────────────

async def _bx_send(k, path, params: dict, method="POST"):
    q = urlencode({**params, "timestamp": _ms(), "recvWindow": 10000})
    q += "&signature=" + _hex(k["secret"], q)
    d = await _req(method, "https://open-api.bingx.com" + path, {"X-BX-APIKEY": k["key"]}, q)
    if not isinstance(d, dict) or d.get("code") not in (0, "0"):
        code = d.get("code") if isinstance(d, dict) else None
        raise ApiErr("auth" if code in (100001, 100413, 100419, 100410) else "api",
                     json.dumps(d)[:200] if isinstance(d, dict) else str(d)[:200])
    return d.get("data")


def _bxs(sym: str) -> str:
    return sym[:-4] + "-" + sym[-4:] if sym.endswith("USDT") else sym


async def bx_trade_perms(k) -> dict:
    try:
        d = await _bx(k, "/openApi/v1/account/apiPermissions") or {}
    except ApiErr as e:
        if e.code == "auth":
            raise
        return {"spot": True, "fut": True}
    perms = [str(x).lower() for x in (d.get("permissions") or [])] if isinstance(d, dict) else []
    if not perms:
        return {"spot": True, "fut": True}
    # BingX ruxsat kodlari: 1 — spot savdo, 2 — o'qish, 3 — perpetual savdo, ...
    return {"spot": any(x in ("1", "spot", "spot_trade") for x in perms),
            "fut": any(x in ("3", "perpetual", "swap", "futures") for x in perms)}


async def bx_filters(mkt: str, sym: str) -> dict:
    hit = _FX.get(("bx" + mkt, sym))
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    if mkt == "spot":
        d = await _get("https://open-api.bingx.com/openApi/spot/v1/common/symbols", {},
                       f"symbol={_bxs(sym)}&timestamp={_ms()}")
        lst = (d.get("data") or {}).get("symbols") or []
        if not lst:
            raise ApiErr("api", f"{sym}: BingX Spot'da bunday juftlik yo'q")
        s = lst[0]
        fx = {"step": _f(s.get("stepSize")), "tick": _f(s.get("tickSize")), "min_qty": _f(s.get("minQty")),
              "min_notional": _f(s.get("minNotional")), "base": sym[:-4], "quote": "USDT"}
    else:
        d = await _get("https://open-api.bingx.com/openApi/swap/v2/quote/contracts", {}, f"timestamp={_ms()}")
        s = next((x for x in (d.get("data") or []) if x.get("symbol") == _bxs(sym)), None)
        if not s:
            raise ApiErr("api", f"{sym}: BingX Futures'da bunday juftlik yo'q")
        fx = {"step": _prec_step(s.get("quantityPrecision")), "tick": _prec_step(s.get("pricePrecision")),
              "min_qty": _f(s.get("tradeMinQuantity")), "min_notional": _f(s.get("tradeMinUSDT")),
              "base": sym[:-4], "quote": "USDT"}
    fx["mstep"] = fx["step"]
    _FX[("bx" + mkt, sym)] = (time.time(), fx)
    return fx


async def _bx_dual(k) -> bool:
    try:
        d = await _bx(k, "/openApi/swap/v1/positionSide/dual") or {}
        return str(d.get("dualSidePosition")).lower() == "true"
    except ApiErr:
        return True        # BingX standarti — hedge rejim


async def bx_info(k, a) -> dict:
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    fx, px, perms = await asyncio.gather(bx_filters(mkt, sym), _xprice("bingx", mkt, sym), bx_trade_perms(k))
    out = {"mkt": mkt, "sym": sym, "price": px, "fx": fx, "perm": perms}
    if mkt == "spot":
        bal = await bx_spot(k)
        out["avail"] = {"quote": bal.get("USDT", 0.0), "base": bal.get(fx["base"], 0.0)}
    else:
        bal, lv, dual = await asyncio.gather(_bx(k, "/openApi/swap/v2/user/balance"),
                                             _bx(k, "/openApi/swap/v2/trade/leverage", {"symbol": _bxs(sym)}),
                                             _bx_dual(k), return_exceptions=True)
        b = bal.get("balance") if isinstance(bal, dict) else None
        if isinstance(b, list):
            b = next((x for x in b if x.get("asset") == "USDT"), b[0] if b else {})
        out["avail"] = {"quote": _f((b or {}).get("availableMargin"))}
        out["lev"] = int(_f(lv.get("longLeverage"))) or None if isinstance(lv, dict) else None
        out["dual"] = dual if isinstance(dual, bool) else True
    return out


async def bx_spot_order(k, a) -> dict:
    _need(await bx_trade_perms(k), "spot")
    sym = _sym(a)
    side = "BUY" if a.get("side") == "buy" else "SELL"
    typ = "LIMIT" if a.get("type") == "limit" else "MARKET"
    fx = await bx_filters("spot", sym)
    p = {"symbol": _bxs(sym), "side": side, "type": typ}
    if typ == "LIMIT":
        price = _round(_pos(a, "price"), fx["tick"])
        qty = (_floor(_dec(_pos(a, "quote")) / price, fx["step"]) if side == "BUY" and a.get("qty") in (None, "")
               else _floor(_pos(a, "qty"), fx["step"]))
        if qty <= 0:
            raise ApiErr("small", "qty")
        p.update(price=_s(price), quantity=_s(qty), timeInForce="GTC")
    elif side == "BUY" and a.get("qty") in (None, ""):
        p["quoteOrderQty"] = _s(_floor(_pos(a, "quote"), "0.01"))
    else:
        qty = _floor(_pos(a, "qty"), fx["step"])
        if qty <= 0:
            raise ApiErr("small", "qty")
        p["quantity"] = _s(qty)
    d = await _bx_send(k, "/openApi/spot/v1/trade/order", p) or {}
    return {"id": str(d.get("orderId") or ""), "status": d.get("status"), "filled": _f(d.get("executedQty")),
            "sym": sym, "side": side.lower(), "type": typ.lower()}


async def bx_spot_open(k, a=None) -> list:
    d = await _bx(k, "/openApi/spot/v1/trade/openOrders") or {}
    return [{"sym": str(o.get("symbol") or "").replace("-", ""), "id": str(o.get("orderId")),
             "side": str(o.get("side") or "").lower(), "type": str(o.get("type") or "").lower(),
             "price": _f(o.get("price")), "qty": _f(o.get("origQty")), "filled": _f(o.get("executedQty")),
             "t": int(_f(o.get("time")))} for o in (d.get("orders") or [] if isinstance(d, dict) else [])]


async def bx_spot_cancel(k, a) -> dict:
    sym, oid = _sym(a), _oid(a)
    await _bx_send(k, "/openApi/spot/v1/trade/cancel", {"symbol": _bxs(sym), "orderId": oid})
    return {"id": oid, "status": "CANCELED"}


async def bx_spot_modify(k, a) -> dict:
    """BingX'da spot o'zgartirish yo'q — bekor qilib, qolgan miqdor bilan yangi narxda qo'yiladi."""
    _need(await bx_trade_perms(k), "spot")
    sym, oid = _sym(a), _oid(a)
    o = next((x for x in await bx_spot_open(k) if x["id"] == oid), None)
    if o is None or o["type"] != "limit":
        raise ApiErr("bad", "faqat LIMIT orderni surish mumkin")
    fx = await bx_filters("spot", sym)
    qty = _floor(o["qty"] - o["filled"], fx["step"])
    if qty <= 0:
        raise ApiErr("small", sym)
    await bx_spot_cancel(k, {"sym": sym, "id": oid})
    r = await bx_spot_order(k, {"sym": sym, "side": o["side"], "type": "limit", "price": _pos(a, "price"),
                                "qty": float(qty)})
    return {"id": r["id"], "price": _pos(a, "price"), "status": "NEW"}


def _bx_cond(kind: str, price) -> str:
    return json.dumps({"type": "TAKE_PROFIT_MARKET" if kind == "tp" else "STOP_MARKET",
                       "stopPrice": float(price), "price": float(price), "workingType": "MARK_PRICE"},
                      separators=(",", ":"))


async def bx_fut_order(k, a) -> dict:
    _need(await bx_trade_perms(k), "fut")
    sym = _sym(a)
    side = "long" if a.get("side") == "long" else "short"
    typ = "LIMIT" if a.get("type") == "limit" else "MARKET"
    margin, lev = _pos(a, "margin"), int(_pos(a, "lev", hi=125))
    tp, sl = _pos(a, "tp", False), _pos(a, "sl", False)
    fx, dual = await asyncio.gather(bx_filters("fut", sym), _bx_dual(k))
    ps = ("LONG" if side == "long" else "SHORT") if dual else "BOTH"
    await _bx_send(k, "/openApi/swap/v2/trade/leverage", {"symbol": _bxs(sym), "side": ps, "leverage": lev})
    price = _round(_pos(a, "price"), fx["tick"]) if typ == "LIMIT" else _dec(await _xprice("bingx", "fut", sym))
    if price <= 0:
        raise ApiErr("api", "price")
    qty = _floor(_dec(margin) * lev / price, fx["step"])
    if qty <= 0 or float(qty) < fx["min_qty"]:
        raise ApiErr("small", f"min {fx['min_qty']}")
    p = {"symbol": _bxs(sym), "side": "BUY" if side == "long" else "SELL", "positionSide": ps,
         "type": typ, "quantity": _s(qty)}
    if typ == "LIMIT":
        p["price"] = _s(price)
    if tp:
        p["takeProfit"] = _bx_cond("tp", _round(tp, fx["tick"]))
    if sl:
        p["stopLoss"] = _bx_cond("sl", _round(sl, fx["tick"]))
    d = await _bx_send(k, "/openApi/swap/v2/trade/order", p) or {}
    o = d.get("order") if isinstance(d, dict) else {}
    return {"id": str((o or {}).get("orderId") or ""), "status": (o or {}).get("status"), "qty": float(qty),
            "sym": sym, "side": side, "type": typ.lower(), "lev": lev, "warn": []}


async def _bx_position(k, sym, ps=None) -> dict | None:
    d = await _bx(k, "/openApi/swap/v2/user/positions", {"symbol": _bxs(sym)}) or []
    for p in d if isinstance(d, list) else []:
        if _f(p.get("positionAmt")) and (not ps or ps == "BOTH" or str(p.get("positionSide")).upper() == ps):
            return p
    return None


async def bx_fut_close(k, a) -> dict:
    _need(await bx_trade_perms(k), "fut")
    sym = _sym(a)
    frac = _pos(a, "frac", hi=1.0)
    ps = str(a.get("ps") or "BOTH").upper()
    p = await _bx_position(k, sym, ps)
    if p is None:
        raise ApiErr("nopos", sym)
    pps = str(p.get("positionSide") or "BOTH").upper()
    amt = abs(_dec(p.get("positionAmt")))
    long_ = pps == "LONG" or (pps == "BOTH" and _f(p.get("positionAmt")) > 0)
    fx = await bx_filters("fut", sym)
    qty = amt if frac >= 0.999 else _floor(amt * _dec(frac), fx["step"])
    if qty <= 0:
        raise ApiErr("small", "qty")
    o = {"symbol": _bxs(sym), "side": "SELL" if long_ else "BUY", "positionSide": pps, "type": "MARKET",
         "quantity": _s(qty)}
    if pps == "BOTH":
        o["reduceOnly"] = "true"
    d = await _bx_send(k, "/openApi/swap/v2/trade/order", o) or {}
    oo = d.get("order") if isinstance(d, dict) else {}
    return {"id": str((oo or {}).get("orderId") or ""), "status": (oo or {}).get("status"), "qty": float(qty), "sym": sym}


async def bx_fut_open(k, a=None) -> list:
    d = await _bx(k, "/openApi/swap/v2/trade/openOrders") or {}
    out = []
    for o in (d.get("orders") or []) if isinstance(d, dict) else []:
        typ = str(o.get("type") or "").lower()
        trig = _f(o.get("stopPrice")) or None
        out.append({"sym": str(o.get("symbol") or "").replace("-", ""), "id": str(o.get("orderId")),
                    "algo": False, "side": str(o.get("side") or "").lower(), "type": typ,
                    "price": _f(o.get("price")), "trigger": trig if typ not in ("limit", "market") else None,
                    "qty": _f(o.get("origQty")), "close": bool(o.get("closePosition")) or typ in (
                        "take_profit_market", "stop_market"),
                    "ps": str(o.get("positionSide") or "BOTH").upper(), "t": int(_f(o.get("time")))})
    out.sort(key=lambda x: -x["t"])
    return out


async def bx_fut_cancel(k, a) -> dict:
    sym, oid = _sym(a), _oid(a)
    await _bx_send(k, "/openApi/swap/v2/trade/order", {"symbol": _bxs(sym), "orderId": oid}, method="DELETE")
    return {"id": oid, "status": "CANCELED"}


async def bx_fut_tpsl(k, a) -> dict:
    _need(await bx_trade_perms(k), "fut")
    sym = _sym(a)
    ps = str(a.get("ps") or "BOTH").upper()
    tp, sl = _pos(a, "tp", False), _pos(a, "sl", False)
    p = await _bx_position(k, sym, ps)
    if p is None:
        raise ApiErr("nopos", sym)
    pps = str(p.get("positionSide") or "BOTH").upper()
    long_ = pps == "LONG" or (pps == "BOTH" and _f(p.get("positionAmt")) > 0)
    for o in await bx_fut_open(k):
        if o["sym"] == sym and o["trigger"] and o["type"] in ("take_profit_market", "stop_market") \
                and o["ps"] == pps:
            try:
                await bx_fut_cancel(k, {"sym": sym, "id": o["id"]})
            except ApiErr as e:
                log.info("BingX eski TP/SL bekor qilinmadi (%s): %s", sym, e.text[:120])
    fx = await bx_filters("fut", sym)
    warn = []
    for kind, val in (("tp", tp), ("sl", sl)):
        if val is None:
            continue
        o = {"symbol": _bxs(sym), "side": "SELL" if long_ else "BUY", "positionSide": pps,
             "type": "TAKE_PROFIT_MARKET" if kind == "tp" else "STOP_MARKET",
             "stopPrice": _s(_round(val, fx["tick"])), "workingType": "MARK_PRICE", "closePosition": "true"}
        try:
            await _bx_send(k, "/openApi/swap/v2/trade/order", o)
        except ApiErr as e:
            warn.append(kind.upper() + ": " + e.text[:120])
    return {"sym": sym, "tp": tp, "sl": sl, "warn": warn}


async def bx_fut_modify(k, a) -> dict:
    """BingX: limitni o'zgartirish — bekor qilib, o'sha miqdor/tomon bilan yangi narxda."""
    _need(await bx_trade_perms(k), "fut")
    sym, oid = _sym(a), _oid(a)
    o = next((x for x in await bx_fut_open(k) if x["id"] == oid), None)
    if o is None or o["type"] != "limit":
        raise ApiErr("bad", "faqat LIMIT orderni surish mumkin")
    fx = await bx_filters("fut", sym)
    price = _s(_round(_pos(a, "price"), fx["tick"]))
    await bx_fut_cancel(k, {"sym": sym, "id": oid})
    d = await _bx_send(k, "/openApi/swap/v2/trade/order",
                       {"symbol": _bxs(sym), "side": o["side"].upper(), "positionSide": o["ps"], "type": "LIMIT",
                        "quantity": _s(_dec(o["qty"])), "price": price}) or {}
    oo = d.get("order") if isinstance(d, dict) else {}
    return {"id": str((oo or {}).get("orderId") or ""), "price": _f(price), "status": "NEW"}


# ─────────────── MEXC — Spot (Binance v3 ga o'xshash). Futures buyurtma API'si oddiy foydalanuvchilarga yopiq ───────────────

async def _mx_send(k, path, params: dict, method="POST"):
    q = urlencode({**params, "recvWindow": 10000, "timestamp": _ms()})
    q += "&signature=" + _hex(k["secret"], q)
    d = await _req(method, "https://api.mexc.com" + path,
                   {"X-MEXC-APIKEY": k["key"], "Content-Type": "application/json"}, q)
    if isinstance(d, dict) and d.get("code") not in (None, 0, 200) and "orderId" not in d:
        code = d.get("code")
        raise ApiErr("auth" if code in (700002, 700003, 10072, 700001) else "api", json.dumps(d)[:200])
    return d


async def mx_trade_perms(k) -> dict:
    d = await _mx_spot(k, "/api/v3/account")
    return {"spot": bool(d.get("canTrade", True)), "fut": False}


async def mx_filters(mkt: str, sym: str) -> dict:
    if mkt != "spot":
        raise ApiErr("noperm", "fut")
    hit = _FX.get(("mxspot", sym))
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    d = await _get("https://api.mexc.com/api/v3/exchangeInfo", {}, "symbol=" + sym)
    lst = d.get("symbols") or []
    if not lst:
        raise ApiErr("api", f"{sym}: MEXC Spot'da bunday juftlik yo'q")
    s = lst[0]
    fx = {"step": _f(s.get("baseSizePrecision")) or _prec_step(s.get("baseAssetPrecision")),
          "tick": _prec_step(s.get("quotePrecision")), "min_qty": 0.0,
          "min_notional": _f(s.get("quoteAmountPrecision")), "base": s.get("baseAsset"), "quote": s.get("quoteAsset")}
    fx["mstep"] = fx["step"]
    _FX[("mxspot", sym)] = (time.time(), fx)
    return fx


async def mx_info(k, a) -> dict:
    mkt = "fut" if a.get("mkt") == "fut" else "spot"
    sym = _sym(a)
    perms = await mx_trade_perms(k)
    if mkt == "fut":
        return {"mkt": mkt, "sym": sym, "price": await _xprice("mexc", "fut", sym), "fx": {}, "perm": perms,
                "avail": {"quote": 0.0}, "lev": None, "dual": False, "note": "mexc_fut"}
    fx, px = await asyncio.gather(mx_filters("spot", sym), _xprice("mexc", "spot", sym))
    bal = await mx_spot(k)
    return {"mkt": mkt, "sym": sym, "price": px, "fx": fx, "perm": perms,
            "avail": {"quote": bal.get(fx["quote"] or "USDT", 0.0), "base": bal.get(fx["base"] or "", 0.0)}}


async def mx_spot_order(k, a) -> dict:
    _need(await mx_trade_perms(k), "spot")
    sym = _sym(a)
    side = "BUY" if a.get("side") == "buy" else "SELL"
    typ = "LIMIT" if a.get("type") == "limit" else "MARKET"
    fx = await mx_filters("spot", sym)
    p = {"symbol": sym, "side": side, "type": typ}
    if typ == "LIMIT":
        price = _round(_pos(a, "price"), fx["tick"])
        qty = (_floor(_dec(_pos(a, "quote")) / price, fx["step"]) if side == "BUY" and a.get("qty") in (None, "")
               else _floor(_pos(a, "qty"), fx["step"]))
        if qty <= 0:
            raise ApiErr("small", "qty")
        p.update(price=_s(price), quantity=_s(qty))
    elif side == "BUY" and a.get("qty") in (None, ""):
        p["quoteOrderQty"] = _s(_floor(_pos(a, "quote"), "0.01"))
    else:
        qty = _floor(_pos(a, "qty"), fx["step"])
        if qty <= 0:
            raise ApiErr("small", "qty")
        p["quantity"] = _s(qty)
    d = await _mx_send(k, "/api/v3/order", p)
    return {"id": str(d.get("orderId") or ""), "status": d.get("status") or "NEW", "sym": sym,
            "side": side.lower(), "type": typ.lower()}


async def mx_spot_open(k, a=None) -> list:
    """MEXC openOrders juftlik talab qiladi — balansdagi coinlar va asosiy juftliklar bo'yicha."""
    bal = await mx_spot(k)
    syms = {c + "USDT" for c, q in bal.items() if q > 0 and c not in STABLE}
    if a and a.get("sym"):
        syms.add(_sym(a))
    out = []
    for sym in list(syms)[:15]:
        try:
            d = await _mx_spot(k, "/api/v3/openOrders", {"symbol": sym})
        except ApiErr:
            continue
        for o in d if isinstance(d, list) else []:
            out.append({"sym": o.get("symbol"), "id": str(o.get("orderId")), "side": str(o.get("side") or "").lower(),
                        "type": str(o.get("type") or "").lower(), "price": _f(o.get("price")),
                        "qty": _f(o.get("origQty")), "filled": _f(o.get("executedQty")), "t": int(_f(o.get("time")))})
    return out


async def mx_spot_cancel(k, a) -> dict:
    sym, oid = _sym(a), _oid(a)
    await _mx_send(k, "/api/v3/order", {"symbol": sym, "orderId": oid}, method="DELETE")
    return {"id": oid, "status": "CANCELED"}


async def mx_spot_modify(k, a) -> dict:
    _need(await mx_trade_perms(k), "spot")
    sym, oid = _sym(a), _oid(a)
    o = next((x for x in await mx_spot_open(k, {"sym": sym}) if x["id"] == oid), None)
    if o is None or o["type"] != "limit":
        raise ApiErr("bad", "faqat LIMIT orderni surish mumkin")
    fx = await mx_filters("spot", sym)
    qty = _floor(o["qty"] - o["filled"], fx["step"])
    if qty <= 0:
        raise ApiErr("small", sym)
    await mx_spot_cancel(k, {"sym": sym, "id": oid})
    r = await mx_spot_order(k, {"sym": sym, "side": o["side"], "type": "limit", "price": _pos(a, "price"),
                                "qty": float(qty)})
    return {"id": r["id"], "price": _pos(a, "price"), "status": "NEW"}


async def _mx_fut_closed(k, a):
    raise ApiErr("noperm", "fut")


async def _no_open(k, a=None) -> list:
    return []


# ─────────────── birja → amallar ───────────────

TRADE_IMPL = {
    "bitget": {"info": bg_info, "spot_order": bg_spot_order, "spot_open": bg_spot_open, "spot_cancel": bg_spot_cancel,
               "spot_modify": bg_spot_modify, "fut_order": bg_fut_order, "fut_close": bg_fut_close,
               "fut_open": bg_fut_open, "fut_cancel": bg_fut_cancel, "fut_tpsl": bg_fut_tpsl,
               "fut_modify": bg_fut_modify},
    "bingx": {"info": bx_info, "spot_order": bx_spot_order, "spot_open": bx_spot_open, "spot_cancel": bx_spot_cancel,
              "spot_modify": bx_spot_modify, "fut_order": bx_fut_order, "fut_close": bx_fut_close,
              "fut_open": bx_fut_open, "fut_cancel": bx_fut_cancel, "fut_tpsl": bx_fut_tpsl,
              "fut_modify": bx_fut_modify},
    "mexc": {"info": mx_info, "spot_order": mx_spot_order, "spot_open": mx_spot_open, "spot_cancel": mx_spot_cancel,
             "spot_modify": mx_spot_modify, "fut_order": _mx_fut_closed, "fut_close": _mx_fut_closed,
             "fut_open": _no_open, "fut_cancel": _mx_fut_closed, "fut_tpsl": _mx_fut_closed,
             "fut_modify": _mx_fut_closed},
}
TRADE_PERMS = {"binance": None, "bitget": bg_trade_perms, "bingx": bx_trade_perms, "mexc": mx_trade_perms}


TRADE_OPS = {
    "depth": bn_depth,
    "info": bn_info, "spot_order": bn_spot_order, "spot_open": bn_spot_open,
    "spot_cancel": bn_spot_cancel, "fut_order": bn_fut_order, "fut_close": bn_fut_close,
    "fut_open": bn_fut_open, "fut_cancel": bn_fut_cancel, "fut_tpsl": bn_fut_tpsl,
    "fut_modify": bn_fut_modify, "spot_modify": bn_spot_modify,
}
TRADE_READ = ("info", "spot_open", "fut_open", "depth")


async def trade(ex: str, k: dict, op: str, a: dict):
    if op == "hist_sync":                       # 335: boshqa birjalar tarixi (statistika)
        if ex not in HIST_EX:
            raise ApiErr("noex", ex)
        return await HIST_EX[ex](k, a or {})
    if op == "depth" and ex != "binance" and DEPTH_EX.get(ex):   # 343: ochiq order book
        return await DEPTH_EX[ex](k, a or {})
    if ex != "binance" and op in TRADE_IMPL.get(ex, {}):      # 355: boshqa birjalar savdosi
        return await TRADE_IMPL[ex][op](k, a or {})
    if ex not in TRADE_EX:
        raise ApiErr("noex", ex)
    f = TRADE_OPS.get(op) or HIST_OPS.get(op)
    if f is None:
        raise ApiErr("bad", op)
    return await f(k, a or {})


# ─────────────────────────── 334: savdo tarixi sinxronizatsiyasi (bazaga) ───────────────────────────
# Binance futures `income` oddiy API ~3 oy beradi; undan eskisi — asinxron yuklab olish
# (`/fapi/v1/income/asyn`, oyiga 5 so'rov, 1 yilgacha oraliq) → CSV havola.

async def bn_income_raw(k, a) -> list:
    """[start, end] (ms) oralig'idagi income yozuvlari, 7 kunlik oynalar, xom ko'rinishda."""
    start, end = int(a["start"]), int(a["end"])
    out, t = [], start
    while t < end:
        b = min(t + 7 * 86_400_000 - 1, end)
        s2 = t
        for _ in range(10):
            d = await _bn(k, FAPI, "/fapi/v1/income", {"startTime": s2, "endTime": b, "limit": 1000})
            if not isinstance(d, list) or not d:
                break
            out += d
            if len(d) < 1000:
                break
            s2 = int(d[-1]["time"]) + 1
        t = b + 1
    return [{"key": "i" + str(x.get("tranId") or ""), "type": x.get("incomeType"), "sym": x.get("symbol") or "",
             "amt": _f(x.get("income")), "asset": x.get("asset"), "t": int(x.get("time") or 0),
             "trade": str(x.get("tradeId") or "")} for x in out if x.get("tranId")]


async def bn_income_async_req(k, a) -> dict:
    d = await _bn(k, FAPI, "/fapi/v1/income/asyn", {"startTime": int(a["start"]), "endTime": int(a["end"])})
    return {"id": str(d.get("downloadId") or "")}


async def bn_income_async_get(k, a) -> dict:
    d = await _bn(k, FAPI, "/fapi/v1/income/asyn/id", {"downloadId": str(a["id"])})
    return {"status": str(d.get("status") or ""), "url": d.get("url") or d.get("s3Link") or "",
            "expired": bool(d.get("isExpired"))}


def _norm(h: str) -> str:
    return "".join(ch for ch in str(h).lower() if ch.isalnum())


def _parse_income_csv(raw: bytes) -> list:
    """Binance income CSV (zip ichida bo'lishi mumkin) → xom yozuvlar. Ustun nomlari
    moslashuvchan aniqlanadi (time/date, type, amount/income, symbol, asset, tranId)."""
    import csv, io, zipfile, hashlib as _h
    from datetime import datetime, timezone
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), z.namelist()[0])
            raw = z.read(name)
    text = raw.decode("utf-8-sig", errors="replace")
    rd = csv.reader(io.StringIO(text))
    rows = list(rd)
    if not rows:
        return []
    hdr = [_norm(h) for h in rows[0]]

    def col(*names):
        for n in names:
            if n in hdr:
                return hdr.index(n)
        for i, h in enumerate(hdr):
            if any(n in h for n in names):
                return i
        return None
    ct, cy, ca = col("time", "date", "dateutc", "timeutc"), col("incometype", "type"), col("income", "amount", "change")
    cs, cas, cid = col("symbol", "pair", "contract"), col("asset", "coin"), col("tranid", "transactionid", "id")
    ctr = col("tradeid")
    if ct is None or cy is None or ca is None:
        log.warning("Income CSV ustunlari tanilmadi: %s", rows[0][:12])
        return []
    out = []
    for r in rows[1:]:
        if len(r) <= max(ct, cy, ca):
            continue
        tv = r[ct].strip()
        try:
            tm = int(float(tv)) if tv.replace(".", "").isdigit() else int(
                datetime.strptime(tv[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
        ty = r[cy].strip().upper().replace(" ", "_")
        if "REALIZED" in ty:
            ty = "REALIZED_PNL"
        elif "FUNDING" in ty:
            ty = "FUNDING_FEE"
        elif "COMMISSION" in ty or ty in ("FEE", "TRADING_FEE"):
            ty = "COMMISSION"
        sym = r[cs].strip().upper() if cs is not None and cs < len(r) else ""
        tid = r[cid].strip() if cid is not None and cid < len(r) else ""
        key = "i" + tid if tid else "h" + _h.sha1(f"{tm}|{ty}|{sym}|{r[ca]}".encode()).hexdigest()[:20]
        out.append({"key": key, "type": ty, "sym": sym, "amt": _f(r[ca]),
                    "asset": r[cas].strip() if cas is not None and cas < len(r) else "",
                    "t": tm, "trade": r[ctr].strip() if ctr is not None and ctr < len(r) else ""})
    log.info("Income CSV: %s qator, ustunlar %s", len(out), rows[0][:10])
    return out


async def bn_income_async_fetch(k, a) -> list:
    url = str(a.get("url") or "")
    if not url.startswith("https://"):
        raise ApiErr("bad", "url")
    try:
        r = await _http.get(url, timeout=60)
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise ApiErr("net", type(e).__name__)
    if r.status_code >= 400:
        raise ApiErr("api", f"HTTP {r.status_code}")
    return _parse_income_csv(r.content)


async def bn_spot_candidates(k, a=None) -> list:
    """Spot savdo bo'lishi mumkin bo'lgan juftliklar: hozirgi + 30 kunlik suratlar aktivlari × kotirovkalar."""
    assets = set()
    try:
        for x, q in (await bn_spot(k)).items():
            if q > 0:
                assets.add(x)
    except ApiErr as e:
        if e.code == "auth":
            raise
    try:
        snap = await _bn(k, SAPI, "/sapi/v1/accountSnapshot", {"type": "SPOT", "limit": 30})
        for v in snap.get("snapshotVos") or []:
            for b in (v.get("data") or {}).get("balances") or []:
                if _f(b.get("free")) + _f(b.get("locked")) > 0:
                    assets.add(b.get("asset"))
    except ApiErr:
        pass
    assets = {x for x in assets if x and x not in STABLE}
    return [x + q for x in sorted(assets)[:40] for q in QUOTES]


async def bn_spot_mytrades(k, a) -> list:
    """Bitta juftlik savdolari `from_id` dan (eskidan yangiga), 1000 tagacha."""
    sym = _sym(a)
    p = {"symbol": sym, "limit": 1000}
    if a.get("from_id") is not None:
        p["fromId"] = int(a["from_id"])
    try:
        d = await _bn(k, SAPI, "/api/v3/myTrades", p)
    except ApiErr as e:
        if e.code == "auth":
            raise
        return []
    return [{"key": f"s{sym}:{x.get('id')}", "id": int(x.get("id") or 0), "sym": sym, "oid": x.get("orderId"),
             "side": "buy" if x.get("isBuyer") else "sell", "qty": _f(x.get("qty")), "quote": _f(x.get("quoteQty")),
             "price": _f(x.get("price")), "fee": _f(x.get("commission")), "fee_a": x.get("commissionAsset"),
             "t": int(x.get("time") or 0)} for x in (d if isinstance(d, list) else [])]


async def bn_spot_sync(k, a) -> dict:
    """Ko'p juftlik bir so'rovda: {syms: {SYM: from_id}} → savdolar (eskidan yangiga, juftlikka 5×1000 gacha),
    yangi kursorlar va mavjud bo'lmagan juftliklar (bad)."""
    cur = {str(x).upper(): (int(v) if v is not None else None) for x, v in (a.get("syms") or {}).items()}
    rows, cursors, bad = [], {}, []
    sem = asyncio.Semaphore(5)

    async def one(sym, fid):
        async with sem:
            got = []
            for _ in range(5):
                p = {"symbol": sym, "limit": 1000, "fromId": fid if fid is not None else 0}
                try:
                    d = await _bn(k, SAPI, "/api/v3/myTrades", p)
                except ApiErr as e:
                    if e.code == "auth":
                        raise
                    if "-1121" in e.text or "Invalid symbol" in e.text:
                        bad.append(sym)
                    return got
                lst = d if isinstance(d, list) else []
                got += lst
                if len(lst) < 1000:
                    break
                fid = int(lst[-1]["id"]) + 1
            return got
    res = await asyncio.gather(*(one(sy, fi) for sy, fi in cur.items()), return_exceptions=True)
    for (sy, fi), r in zip(cur.items(), res):
        if isinstance(r, ApiErr) and r.code == "auth":
            raise r
        if not isinstance(r, list):
            continue
        last = fi - 1 if fi else None
        for x in r:
            rows.append({"key": f"s{sy}:{x.get('id')}", "sym": sy, "oid": str(x.get("orderId")),
                         "side": "buy" if x.get("isBuyer") else "sell", "qty": _f(x.get("qty")),
                         "quote": _f(x.get("quoteQty")), "fee": _f(x.get("commission")),
                         "fee_a": x.get("commissionAsset"), "t": int(x.get("time") or 0)})
            last = max(last or 0, int(x.get("id") or 0))
        if last is not None:
            cursors[sy] = last
    return {"rows": rows, "cursors": cursors, "bad": bad}


HIST_OPS = {
    "spot_sync": bn_spot_sync,
    "inc_raw": bn_income_raw, "inc_async_req": bn_income_async_req, "inc_async_get": bn_income_async_get,
    "inc_async_fetch": bn_income_async_fetch, "spot_cands": bn_spot_candidates, "spot_mytrades": bn_spot_mytrades,
}


# ─────────────────────────── 335: MEXC / Bitget / BingX savdo tarixi ───────────────────────────
# Natija Binance bilan bir xil ko'rinishda: inc — REALIZED_PNL / COMMISSION / FUNDING_FEE yozuvlari,
# spot — fill'lar. Har birja o'zi bergancha (ko'pincha ~90 kun) — keyin har soat bazaga yig'iladi.
# Har qadam alohida try: bitta endpoint ishlamasa qolganlari baribir saqlanadi, xato `errs` da.
_DAY = 86_400_000


async def _spot_cands_generic(spot_fn, k) -> list:
    try:
        bal = await spot_fn(k)
    except ApiErr as e:
        if e.code == "auth":
            raise
        return []
    return sorted(a for a, q in bal.items() if q > 0 and a not in STABLE)[:30]


def _spot_row(key, sym, oid, side, qty, quote, fee, fee_a, t):
    return {"key": key, "sym": sym, "oid": str(oid or ""), "side": side, "qty": qty, "quote": quote,
            "fee": abs(fee), "fee_a": fee_a, "t": int(t)}


async def mx_hist(k, a) -> dict:
    since, now, errs = int(a.get("since") or 0), _ms(), []
    ys = int(a.get("year_from") or since)        # spot: yangi juftlik — davr boshidan
    inc, spot, spot_t = [], [], dict(a.get("spot_t") or {})
    try:
        for page in range(1, 51):
            d = await _mx_fut(k, "/api/v1/private/position/list/history_positions",
                              {"page_num": page, "page_size": 100})
            lst = d if isinstance(d, list) else ((d or {}).get("resultList") or (d or {}).get("list") or [])
            old = False
            for p in lst:
                t = int(p.get("updateTime") or p.get("createTime") or 0)
                if t < since:
                    old = True
                    continue
                pid = str(p.get("positionId") or "")
                inc.append({"key": "m" + pid, "type": "REALIZED_PNL", "sym": str(p.get("symbol", "")).replace("_", ""),
                            "amt": _f(p.get("realised")), "asset": "USDT", "t": t, "trade": pid})
            if old or len(lst) < 100:
                break
    except ApiErr as e:
        if e.code == "auth":
            raise
        errs.append("fut: " + e.text[:120])
    for base in await _spot_cands_generic(mx_spot, k):
        sym = base + "USDT"
        # 337: avval davr boshidan (since) so'raladi — birja rad etsa so'nggi 29 kun
        st = max(int(spot_t.get(sym) or 0) + 1, ys)
        d = None
        for st_try in (st, max(st, now - 29 * _DAY)):
            try:
                d = await _mx_spot(k, "/api/v3/myTrades", {"symbol": sym, "startTime": st_try, "limit": 1000})
                break
            except ApiErr as e:
                if e.code == "auth":
                    raise
                d = None
        for x in d if isinstance(d, list) else []:
            t = int(x.get("time") or 0)
            spot.append(_spot_row(f"m{sym}:{x.get('id')}", sym, x.get("orderId"), "buy" if x.get("isBuyer") else "sell",
                                  _f(x.get("qty")), _f(x.get("quoteQty")), _f(x.get("commission")),
                                  x.get("commissionAsset"), t))
            spot_t[sym] = max(int(spot_t.get(sym) or 0), t)
    return {"inc": inc, "spot": spot, "spot_t": spot_t, "errs": errs, "depth": "MEXC: spot ~30 kun"}


async def bg_hist(k, a) -> dict:
    since, now, errs = int(a.get("since") or 0), _ms(), []
    ys = int(a.get("year_from") or since)        # spot: yangi juftlik — davr boshidan
    inc, spot, spot_t = [], [], dict(a.get("spot_t") or {})
    t_end = now
    try:
        while t_end > since:
            t_start = max(since, t_end - 89 * _DAY)
            cursor = None
            for _ in range(30):
                p = {"productType": "USDT-FUTURES", "startTime": t_start, "endTime": t_end, "limit": 100}
                if cursor:
                    p["idLessThan"] = cursor
                try:
                    d = await _bg(k, "/api/v2/mix/position/history-position", p) or {}
                except ApiErr as e:
                    if e.code == "auth":
                        raise
                    errs.append("fut: " + e.text[:120])
                    t_start = since          # eski oraliq qo'llab-quvvatlanmaydi — to'xtash
                    break
                lst = d.get("list") or []
                for x in lst:
                    pid, t = str(x.get("positionId") or ""), int(x.get("utime") or x.get("ctime") or 0)
                    sym = str(x.get("symbol") or "").upper()
                    inc.append({"key": "b" + pid, "type": "REALIZED_PNL", "sym": sym, "amt": _f(x.get("pnl")),
                                "asset": "USDT", "t": t, "trade": pid})
                    fee = abs(_f(x.get("openFee"))) + abs(_f(x.get("closeFee")))
                    if fee:
                        inc.append({"key": "bf" + pid, "type": "COMMISSION", "sym": sym, "amt": -fee,
                                    "asset": "USDT", "t": t, "trade": pid})
                    if _f(x.get("totalFunding")):
                        inc.append({"key": "bu" + pid, "type": "FUNDING_FEE", "sym": sym,
                                    "amt": _f(x.get("totalFunding")), "asset": "USDT", "t": t, "trade": ""})
                if len(lst) < 100 or not d.get("endId"):
                    break
                cursor = d.get("endId")
            t_end = t_start - 1
    except ApiErr as e:
        if e.code == "auth":
            raise
        errs.append("fut: " + e.text[:120])
    for base in await _spot_cands_generic(bg_spot, k):
        sym = base + "USDT"
        # 337: 89 kunlik oynalar bilan ortga — davr boshigacha yoki birja rad etguncha; oyna ichida idLessThan
        lo = max(int(spot_t.get(sym) or 0) + 1, ys)
        d, we = [], now
        while we > lo:
            ws = max(lo, we - 89 * _DAY)
            cur_id, stop = None, False
            for _ in range(20):
                p = {"symbol": sym, "startTime": ws, "endTime": we, "limit": 100}
                if cur_id:
                    p["idLessThan"] = cur_id
                try:
                    part = await _bg(k, "/api/v2/spot/trade/fills", p)
                except ApiErr as e:
                    if e.code == "auth":
                        raise
                    stop = True
                    break
                part = part if isinstance(part, list) else []
                d += part
                if len(part) < 100:
                    break
                cur_id = part[-1].get("tradeId")
            if stop:
                break
            we = ws - 1
        for x in d:
            t = int(x.get("cTime") or 0)
            fd = x.get("feeDetail") or {}
            spot.append(_spot_row(f"b{sym}:{x.get('tradeId')}", sym, x.get("orderId"),
                                  "buy" if str(x.get("side")).lower() == "buy" else "sell", _f(x.get("size")),
                                  _f(x.get("amount")), _f(fd.get("totalFee")), fd.get("feeCoin"), t))
            spot_t[sym] = max(int(spot_t.get(sym) or 0), t)
    return {"inc": inc, "spot": spot, "spot_t": spot_t, "errs": errs, "depth": "Bitget: ~90 kun"}


async def bx_hist(k, a) -> dict:
    since, now, errs = int(a.get("since") or 0), _ms(), []
    ys = int(a.get("year_from") or since)        # spot: yangi juftlik — davr boshidan
    inc, spot, spot_t = [], [], dict(a.get("spot_t") or {})
    t, empty_old = max(since, now - 365 * _DAY), 0
    while t < now:
        b = min(t + 7 * _DAY - 1, now)
        s2 = t
        try:
            for _ in range(10):
                d = await _bx(k, "/openApi/swap/v2/user/income", {"startTime": s2, "endTime": b, "limit": 1000}) or []
                lst = d if isinstance(d, list) else []
                for x in lst:
                    ty = str(x.get("incomeType") or "").upper()
                    ty = "COMMISSION" if ty in ("TRADING_FEE", "COMMISSION") else ty
                    inc.append({"key": "x" + str(x.get("tranId") or f"{x.get('time')}{ty}{x.get('symbol')}"),
                                "type": ty, "sym": str(x.get("symbol") or "").replace("-", "").upper(),
                                "amt": _f(x.get("income")), "asset": x.get("asset"), "t": int(x.get("time") or 0),
                                "trade": str(x.get("tradeId") or "")})
                if len(lst) < 1000:
                    break
                s2 = int(lst[-1].get("time") or b) + 1
        except ApiErr as e:
            if e.code == "auth":
                raise
            if b > now - 85 * _DAY:
                errs.append("fut: " + e.text[:120])
        t = b + 1
    for base in await _spot_cands_generic(bx_spot, k):
        sym = base + "-USDT"
        # 337: davr boshidan 7 kunlik oynalar — eski oyna rad etilsa keyingisiga o'tiladi (yangi oynalar baribir so'raladi)
        st0 = max(int(spot_t.get(base + "USDT") or 0) + 1, ys)
        w = st0
        while w < now:
            we = min(w + 7 * _DAY - 1, now)
            try:
                d = await _bx(k, "/openApi/spot/v1/trade/myTrades", {"symbol": sym, "startTime": w, "endTime": we, "limit": 500}) or {}
            except ApiErr as e:
                if e.code == "auth":
                    raise
                w = we + 1
                continue
            lst = d.get("fills") if isinstance(d, dict) else d
            for x in lst or []:
                tt = int(x.get("time") or 0)
                spot.append(_spot_row(f"x{base}USDT:{x.get('id')}", base + "USDT", x.get("orderId"),
                                      "buy" if x.get("isBuyer") else "sell", _f(x.get("qty")), _f(x.get("quoteQty")),
                                      _f(x.get("commission")), x.get("commissionAsset"), tt))
                spot_t[base + "USDT"] = max(int(spot_t.get(base + "USDT") or 0), tt)
            w = we + 1
    return {"inc": inc, "spot": spot, "spot_t": spot_t, "errs": errs, "depth": "BingX: spot ~30 kun"}


HIST_EX = {"mexc": mx_hist, "bitget": bg_hist, "bingx": bx_hist}
