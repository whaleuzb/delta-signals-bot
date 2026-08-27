"""Hyblock Capital — Liquidation Heatmap API.

CoinGlass'ning mashhur narx-klaster likvidatsiya heatmap'i faqat
Professional tarifdan ($699/oy) boshlab ochiladi (rasmiy hujjatlardan
tasdiqlangan). Hyblock Capital esa xuddi shu turdagi (`/liquidationHeatmap`)
endpoint'ni BEPUL tarifida beradi — foydalanuvchi o'zi hisob ochib
tekshirdi va rasmiy OpenAPI spetsifikatsiyasini yubordi.

Autentifikatsiya — OAuth2 Client Credentials (`x-api-key` + Basic Auth
bilan `/oauth2/token`dan `access_token` olinadi, keyin `Authorization:
Bearer <token>` + `x-api-key` bilan haqiqiy so'rov qilinadi). Token
`expires_in` (soniyalarda) muddatga ega — xotirada keshlanadi, muddati
tugagach yoki 401 kelganda qayta so'raladi.

`HYBLOCK_API_KEY`/`HYBLOCK_CLIENT_ID`/`HYBLOCK_CLIENT_SECRET` bo'sh bo'lsa
butun modul jimgina o'chadi — likvidatsiya funksiyasi shunda oddiy
shamli grafikka (`chart.news_chart()`) qaytadi (`bot.py`da)."""
import logging
import time

import httpx

import config

log = logging.getLogger("hyblock")

BASE_URL = "https://api.hyblockcapital.com/v2"

_token: str | None = None
_token_exp: float = 0.0


def enabled() -> bool:
    return bool(config.HYBLOCK_API_KEY and config.HYBLOCK_CLIENT_ID
                and config.HYBLOCK_CLIENT_SECRET)


async def _get_token(force: bool = False) -> str:
    global _token, _token_exp
    if not force and _token and time.time() < _token_exp:
        return _token
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{BASE_URL}/oauth2/token",
            auth=(config.HYBLOCK_CLIENT_ID, config.HYBLOCK_CLIENT_SECRET),
            headers={"x-api-key": config.HYBLOCK_API_KEY},
            data={"grant_type": "client_credentials"})
        r.raise_for_status()
        data = r.json()
    _token = data["access_token"]
    # Ozgina zaxira (60s) — tokenning aynan tugash chegarasida so'rov
    # yuborib, kutilmagan 401ga uchramaslik uchun.
    _token_exp = time.time() + max(int(data.get("expires_in", 3600)) - 60, 60)
    return _token


async def liquidation_heatmap(coin: str, lookback: str = "12h") -> list[dict] | None:
    """`coin` — quote'siz baza tiker (masalan "BTC", "ETH", `bot.py`
    likvidatsiya belgisidan shu ko'rinishga o'giradi). Muvaffaqiyatsiz
    yoki modul o'chirilgan bo'lsa `None` — chaqiruvchi shunda oddiy
    shamli grafikka qaytadi. Javob — `[{startingPrice, endingPrice,
    side, size, timestamp}, ...]` (Hyblock rasmiy OpenAPI spetsifikatsiyasi,
    foydalanuvchi tomonidan tasdiqlangan)."""
    if not enabled():
        return None
    params = {"coin": coin, "lookback": lookback}
    try:
        token = await _get_token()
        async with httpx.AsyncClient(timeout=20.0) as client:
            headers = {"Authorization": f"Bearer {token}", "x-api-key": config.HYBLOCK_API_KEY}
            r = await client.get(f"{BASE_URL}/liquidationHeatmap", params=params, headers=headers)
            if r.status_code == 401:
                token = await _get_token(force=True)
                headers["Authorization"] = f"Bearer {token}"
                r = await client.get(f"{BASE_URL}/liquidationHeatmap", params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception:
        log.warning("Hyblock heatmap olinmadi (%s)", coin, exc_info=True)
        return None
    return data.get("data") or []
