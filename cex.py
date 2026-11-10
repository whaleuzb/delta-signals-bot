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


async def _req(method: str, url: str, headers: dict, params: str = "") -> object:
    full = url + ("?" + params if params else "")
    try:
        r = await _http.request(method, full, headers=headers)
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
                    "liq": _f(p.get("liquidationPrice")) or None})
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
                    "liq": _f(p.get("liquidationPrice")) or None})
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
            out["trade"] = await bn_trade_perms(k)
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

TRADE_EX = ("binance",)
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


TRADE_OPS = {
    "info": bn_info, "spot_order": bn_spot_order, "spot_open": bn_spot_open,
    "spot_cancel": bn_spot_cancel, "fut_order": bn_fut_order, "fut_close": bn_fut_close,
    "fut_open": bn_fut_open, "fut_cancel": bn_fut_cancel, "fut_tpsl": bn_fut_tpsl,
}
TRADE_READ = ("info", "spot_open", "fut_open")


async def trade(ex: str, k: dict, op: str, a: dict):
    if ex not in TRADE_EX:
        raise ApiErr("noex", ex)
    f = TRADE_OPS.get(op)
    if f is None:
        raise ApiErr("bad", op)
    return await f(k, a or {})
