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


# ─────────────────────────── Matnni o'qish ───────────────────────────

def _num(raw: str) -> float | None:
    raw = raw.strip().replace(",", ".").lstrip("$").rstrip("$")
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 and v == v and v != float("inf") else None


def _symbol(raw: str) -> str | None:
    s = raw.strip().upper().lstrip("#$").replace("/", "").replace("_", "").replace("-", "")
    if s.endswith("USDT") and len(s) > 4:
        s = s[:-4]
    return s if s.isalnum() and 1 <= len(s) <= 12 else None


def parse_buy(text: str) -> dict | None:
    """"BTC 500" — market; "BTC 500 limit 58000 sl 55000 tp 70000".
    Qaytaradi: {symbol, amount, limit?, sl?, tp?} yoki None."""
    tokens = text.split()
    if len(tokens) < 2:
        return None
    symbol, amount = _symbol(tokens[0]), _num(tokens[1])
    if not symbol or amount is None:
        return None
    out = {"symbol": symbol, "amount": amount}
    rest = tokens[2:]
    if len(rest) % 2:
        return None
    keys = {"limit": "limit", "l": "limit", "lmt": "limit", "sl": "sl", "stop": "sl",
            "tp": "tp", "take": "tp"}
    for k, v in zip(rest[::2], rest[1::2]):
        key = keys.get(k.lower().rstrip(":"))
        num = _num(v)
        if key is None or num is None or key in out:
            return None
        out[key] = num
    return out


def parse_protect(text: str) -> dict | None:
    """"sl 58000 tp 70000"; "-" yoki "0" — olib tashlash ("sl -").
    Qaytaradi: {"sl": float|None, "tp": ...} (faqat berilgan kalitlar)."""
    tokens = text.split()
    if not tokens or len(tokens) % 2:
        return None
    keys = {"sl": "sl", "stop": "sl", "tp": "tp", "take": "tp"}
    out: dict = {}
    for k, v in zip(tokens[::2], tokens[1::2]):
        key = keys.get(k.lower().rstrip(":"))
        if key is None or key in out:
            return None
        if v.strip() in ("-", "0", "—", "off"):
            out[key] = None
            continue
        num = _num(v)
        if num is None:
            return None
        out[key] = num
    return out or None
