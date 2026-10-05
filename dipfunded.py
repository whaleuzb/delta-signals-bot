"""Dip Funded (whaleuzb/delta-prop, dipfunded.com) bilan ulanish.

NEGA: egasining talabi — "tradecontrbot ga ham ulaylik. Hisobni boshqarish
imkoniyati va bot ichidagi imkoniyatlar". Foydalanuvchi shu botning
o'zidan Dip Funded challenge hisoblarini ko'radi va savdo qiladi (market/
limit xarid, sotish, SL/TP, limitni bekor qilish).

Dip Funded tomonida `/api/tc/*` (tcapi.py). Kalit — `config.DIPFUNDED_API_KEY`
(Dip Funded'dagi `TC_API_KEY` bilan bir xil). Foydalanuvchi Telegram id
bo'yicha topiladi: u Telegram'ini dipfunded.com kabinetida (Dip Funded
boti orqali) ULAGAN bo'lishi shart — boshqa yo'l bilan begona hisobga
yetib bo'lmaydi.

Uch xil xato ATAYLAB ajratilgan (paymembers.py andozasi):
  * `NotLinked`   — Dip Funded "bu Telegram bizda ulanmagan" dedi;
  * `ApiError`    — amal rad etildi (kod + foydalanuvchi tilidagi matn);
  * `Unavailable` — javob olinmadi (tarmoq, kalit, 5xx).
"""
import httpx

import config


class Unavailable(Exception):
    """Dip Funded'dan aniq javob olinmadi."""


class NotLinked(Exception):
    """Telegram Dip Funded akkauntiga ulanmagan (yoki profil to'liq emas)."""

    def __init__(self, code: str = "not_linked"):
        super().__init__(code)
        self.code = code


class ApiError(Exception):
    def __init__(self, code: str, text: str):
        super().__init__(code)
        self.code = code
        self.text = text


def enabled() -> bool:
    return bool(config.DIPFUNDED_API_KEY)


def site_url(path: str = "") -> str:
    return f"{config.DIPFUNDED_URL}{path}"


async def _req(method: str, path: str, tg_id: int, body: dict | None = None) -> dict:
    if not enabled():
        raise Unavailable("DIPFUNDED_API_KEY sozlanmagan")
    url = f"{config.DIPFUNDED_URL}/api/tc{path}"
    headers = {"X-Api-Key": config.DIPFUNDED_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            if method == "GET":
                r = await c.get(url, params={"tg_id": tg_id}, headers=headers)
            else:
                r = await c.post(url, json={**(body or {}), "tg_id": tg_id}, headers=headers)
    except httpx.HTTPError as e:
        raise Unavailable(f"tarmoq xatosi: {type(e).__name__}") from e
    return _result(r)


def _result(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise Unavailable(f"HTTP {r.status_code}")
    if data.get("ok"):
        return data
    code = str(data.get("code") or "")
    if code in ("not_linked", "profile"):
        raise NotLinked(code)
    if data.get("error"):
        raise ApiError(code, str(data["error"]))
    if code:
        raise ApiError(code, "")
    raise Unavailable(f"HTTP {r.status_code}")


async def accounts(tg_id: int) -> dict:
    return await _req("GET", "/accounts", tg_id)


async def account(tg_id: int, acc_id: int) -> dict:
    return await _req("GET", f"/accounts/{acc_id}", tg_id)


async def buy(tg_id: int, acc_id: int, symbol: str, amount: float,
              limit: float | None = None, sl: float | None = None,
              tp: float | None = None) -> dict:
    body = {"symbol": symbol, "amount": str(amount)}
    for k, v in (("limit", limit), ("sl", sl), ("tp", tp)):
        if v is not None:
            body[k] = str(v)
    return await _req("POST", f"/accounts/{acc_id}/buy", tg_id, body)


async def sell(tg_id: int, acc_id: int, symbol: str, fraction: float) -> dict:
    return await _req("POST", f"/accounts/{acc_id}/sell", tg_id,
                      {"symbol": symbol, "fraction": str(fraction)})


async def protect(tg_id: int, acc_id: int, symbol: str, changes: dict) -> dict:
    """`changes`: {"sl": narx | None, "tp": ...} — kalit yo'q = o'zgarmaydi,
    None = olib tashlash."""
    body = {"symbol": symbol}
    for k in ("sl", "tp"):
        if k in changes:
            body[k] = None if changes[k] is None else str(changes[k])
    return await _req("POST", f"/accounts/{acc_id}/protect", tg_id, body)


async def cancel(tg_id: int, acc_id: int, order_id: int) -> dict:
    return await _req("POST", f"/accounts/{acc_id}/cancel", tg_id, {"order_id": order_id})


async def modify(tg_id: int, acc_id: int, order_id: int, changes: dict) -> dict:
    """Limit buyurtma: {"limit": narx, "sl": narx | None, "tp": ...}."""
    body: dict = {"order_id": order_id}
    for k in ("limit", "sl", "tp"):
        if k in changes:
            body[k] = None if changes[k] is None else str(changes[k])
    return await _req("POST", f"/accounts/{acc_id}/modify", tg_id, body)


async def stats(tg_id: int, acc_id: int, limit: int = 20, offset: int = 0) -> dict:
    if not enabled():
        raise Unavailable("DIPFUNDED_API_KEY sozlanmagan")
    url = f"{config.DIPFUNDED_URL}/api/tc/accounts/{acc_id}/stats"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url, params={"tg_id": tg_id, "limit": limit, "offset": offset},
                            headers={"X-Api-Key": config.DIPFUNDED_API_KEY})
    except httpx.HTTPError as e:
        raise Unavailable(f"tarmoq xatosi: {type(e).__name__}") from e
    return _result(r)


# ─────────────────────────── Matnni o'qish ───────────────────────────

def _num(raw: str) -> float | None:
    raw = raw.strip().replace(",", ".").lstrip("$").rstrip("$")
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 and v == v and v != float("inf") else None


def symbol(raw: str) -> str | None:
    s = raw.strip().upper().lstrip("#$").replace("/", "").replace("_", "").replace("-", "")
    if s.endswith("USDT") and len(s) > 4:
        s = s[:-4]
    return s if s.isalnum() and 1 <= len(s) <= 12 else None


def level(raw: str, kind: str, ref: float | None = None) -> float | None:
    """Bitta daraja: aniq narx yoki `ref`ga nisbatan foiz.
    SL uchun "3%" / "-3%" -> ref × 0.97; TP uchun "5%" / "+5%" -> ref × 1.05.
    (Spot, faqat long — SL doim pastda, TP doim yuqorida.)"""
    raw = raw.strip()
    if raw.endswith("%"):
        if not ref:
            return None
        num = _num(raw[:-1].lstrip("+-"))
        if num is None or num >= 100:
            return None
        return ref * (1 - num / 100) if kind == "sl" else ref * (1 + num / 100)
    return _num(raw)


def parse_protect(text: str, ref: float | None = None, allow_limit: bool = False) -> dict | None:
    """"sl 58000 tp 70000"; "sl -3% tp 5%" (`ref`ga nisbatan); "-" yoki "0" —
    olib tashlash ("sl -"). `allow_limit` — limit buyurtmani tahrirlashda
    "limit 2750" ham. Qaytaradi: {"sl": float|None, ...} (faqat berilganlar)."""
    tokens = text.split()
    if not tokens or len(tokens) % 2:
        return None
    keys = {"sl": "sl", "stop": "sl", "tp": "tp", "take": "tp"}
    if allow_limit:
        keys.update({"limit": "limit", "l": "limit", "lmt": "limit"})
    out: dict = {}
    for k, v in zip(tokens[::2], tokens[1::2]):
        key = keys.get(k.lower().rstrip(":"))
        if key is None or key in out:
            return None
        if key != "limit" and v.strip() in ("-", "0", "—", "off"):
            out[key] = None
            continue
        base = out.get("limit") or ref
        num = _num(v) if key == "limit" else level(v, key, base)
        if num is None:
            return None
        out[key] = num
    return out or None
