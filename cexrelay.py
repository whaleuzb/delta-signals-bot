"""326: birja so'rovlari servisi (Railway `cex`, Singapur hududi).

Bot, web va baza AQShda (sfo) — Binance u yerdan 451 qaytaradi, birja
serverlari esa asosan Osiyoda. Shu sabab birjaga boradigan so'rovlar shu
kichik servis orqali Singapurdan yuboriladi.

Xavfsizlik:
  - Servisning OMMAVIY MANZILI YO'Q — faqat Railway ichki tarmog'i
    (`cex.railway.internal`), ya'ni faqat shu loyihaning servislari ulana oladi.
  - Qo'shimcha: `RELAY_TOKEN` berilgan bo'lsa, har so'rovda `X-Relay-Token`
    sarlavhasi tekshiriladi.
  - Kalitlar bu yerda SAQLANMAYDI va logga yozilmaydi — so'rov bilan keladi,
    javobdan keyin unutiladi. Bazaga ulanmaydi.

API (POST, JSON):
  /verify   {"ex", "k": {"key","secret","pass"}} -> {"ok": true} | {"err": code}
  /snapshot {"ex", "k": {...}}                    -> {"snap": {...}} | {"err": code}
"""
import hmac
import logging
import os

from aiohttp import web

# `config` DATABASE_URL'ni talab qiladi — bu servis bazaga ULANMAYDI (ataylab
# berilmaydi), shuning uchun bo'sh qiymat.
os.environ.setdefault("DATABASE_URL", "")
import cex  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cexrelay")
# httpx har so'rov URL'ini INFO'da yozadi — imzolangan so'rovlar logga tushmasin.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def _auth(request) -> bool:
    tok = os.getenv("RELAY_TOKEN", "")
    return not tok or hmac.compare_digest(request.headers.get("X-Relay-Token", ""), tok)


async def _args(request):
    if not _auth(request):
        raise web.HTTPForbidden()
    try:
        b = await request.json()
    except Exception:
        raise web.HTTPBadRequest()
    ex, k = b.get("ex"), b.get("k")
    if ex not in cex.EXCHANGES or not isinstance(k, dict):
        raise web.HTTPBadRequest()
    return ex, {"key": str(k.get("key") or ""), "secret": str(k.get("secret") or ""),
                "pass": str(k.get("pass") or "")}


async def verify(request):
    ex, k = await _args(request)
    try:
        await cex.verify(ex, k)
    except cex.ApiErr as e:
        # Birja javobi (kalitsiz) — sababni ko'rish uchun logga va foydalanuvchiga.
        log.info("verify rad (%s): %s — %s", ex, e.code, e.text[:200])
        return web.json_response({"err": e.code, "msg": e.text[:200]})
    except Exception:
        log.warning("verify xato (%s)", ex, exc_info=True)
        return web.json_response({"err": "api"})
    return web.json_response({"ok": True})


async def snapshot(request):
    ex, k = await _args(request)
    try:
        return web.json_response({"snap": await cex.snapshot(ex, k)})
    except cex.ApiErr as e:
        log.info("snapshot xato (%s): %s — %s", ex, e.code, e.text[:200])
        return web.json_response({"err": e.code, "msg": e.text[:200]})
    except Exception:
        log.warning("snapshot xato (%s)", ex, exc_info=True)
        return web.json_response({"err": "api"})


async def history(request):
    ex, k = await _args(request)
    try:
        return web.json_response({"hist": await cex.history(ex, k)})
    except cex.ApiErr as e:
        log.info("history xato (%s): %s — %s", ex, e.code, e.text[:200])
        return web.json_response({"err": e.code, "msg": e.text[:200]})
    except Exception:
        log.warning("history xato (%s)", ex, exc_info=True)
        return web.json_response({"err": "api"})


async def trades(request):
    ex, k = await _args(request)
    try:
        return web.json_response({"trades": await cex.trades(ex, k)})
    except cex.ApiErr as e:
        log.info("trades xato (%s): %s — %s", ex, e.code, e.text[:200])
        return web.json_response({"err": e.code, "msg": e.text[:200]})
    except Exception:
        log.warning("trades xato (%s)", ex, exc_info=True)
        return web.json_response({"err": "api"})


async def health(_request):
    return web.Response(text="ok")


_PING = {
    "binance": "https://api.binance.com/api/v3/time",
    "binance-fut": "https://fapi.binance.com/fapi/v1/time",
    "mexc": "https://api.mexc.com/api/v3/time",
    "mexc-fut": "https://contract.mexc.com/api/v1/contract/ping",
    "bitget": "https://api.bitget.com/api/v2/public/time",
    "bingx": "https://open-api.bingx.com/openApi/swap/v2/server/time",
}


async def _selfcheck(_app):
    """Ishga tushganda: har birjaning ochiq API'si shu hududdan ochiladimi (451 = hudud bloki)."""
    import httpx
    out = []
    async with httpx.AsyncClient(timeout=10) as c:
        for name, url in _PING.items():
            try:
                r = await c.get(url)
                out.append(f"{name}={r.status_code}")
            except Exception as e:
                out.append(f"{name}={type(e).__name__}")
    log.info("Birjalarga ulanish tekshiruvi: %s", " ".join(out))


async def _start_check(app):
    import asyncio
    app["chk"] = asyncio.create_task(_selfcheck(app))


def build() -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    app.on_startup.append(_start_check)
    app.add_routes([web.post("/verify", verify), web.post("/snapshot", snapshot),
                    web.post("/history", history),
                    web.post("/trades", trades),
                    web.get("/healthz", health)])
    return app


def _hosts() -> list[str]:
    """IPv4 (Railway sog'lik tekshiruvi, yangi ichki tarmoq) + IPv6 (eski ichki tarmoq).
    `asyncio` "::" ni IPV6_V6ONLY bilan ochadi — shu sabab ikkalasi alohida.
    IPv6 yo'q muhitda (lokal sinov) — faqat "0.0.0.0"."""
    import socket
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as t:
            t.bind(("::", 0))
        return ["0.0.0.0", "::"]
    except OSError:
        return ["0.0.0.0"]


if __name__ == "__main__":
    web.run_app(build(), host=_hosts(), port=int(os.getenv("PORT", "8080")))
