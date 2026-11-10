"""354: Delta Wear (deltawear.co) — kiyim xaridini tekshirish (DIP vazifasi).
Delta Wear backendida `POST /api/tc/purchase` (deltawear-webhook `main.py`), kalit `TC_API_KEY`
= bu yerda `DELTAWEAR_API_KEY`. Faqat TASDIQLANGAN buyurtmalar qaytadi."""
import httpx

import config


class Unavailable(Exception):
    pass


def enabled() -> bool:
    return bool(config.DELTAWEAR_API_KEY)


async def purchases(tg_id: int, order_id: int | None = None, phone: str | None = None) -> list:
    body = {"tg_id": tg_id}
    if order_id:
        body["order_id"] = order_id
    if phone:
        body["phone"] = phone
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{config.DELTAWEAR_URL}/api/tc/purchase", json=body,
                             headers={"X-Api-Key": config.DELTAWEAR_API_KEY})
    except httpx.HTTPError as e:
        raise Unavailable(type(e).__name__) from e
    if r.status_code != 200:
        raise Unavailable(f"HTTP {r.status_code}")
    d = r.json()
    if not d.get("ok"):
        raise Unavailable(str(d.get("code")))
    return d.get("orders") or []
