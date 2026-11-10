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
    full = url + ("?" + params if params else "")
    try:
        r = await _http.get(full, headers=headers)
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
                    "liq": _f(p.get("liquidationPrice")) or None})
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
    return {"ex": ex, "spot_usd": spot_usd, "assets": assets[:40], "fut": fut, "pos": pos,
            "total": spot_usd + (fut["eq"] if fut else 0)}


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
