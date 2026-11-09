"""Ochiq natijalar sahifasi — guruh statistikasini jonli havola sifatida.

Nima uchun: guruh egasi skrinshot tashlash o'rniga havola beradi va odam
haqiqiy, tekshiriladigan natijani ko'radi. Skrinshotni tahrirlash mumkin,
bu sahifani esa yo'q — u to'g'ridan-to'g'ri bazadan o'qiladi.

Xavfsizlik:
  - FAQAT o'qish. Hech bir yo'l bazaga yozmaydi.
  - Ko'rsatiladigan workspace `/top` bilan bir xil darvozadan o'tadi
    (`public` + `public_approved` + arxivlanmagan) — veb yangi ruxsat
    ochmaydi, allaqachon ommaviy bo'lgan narsanigina ko'rsatadi.
  - Har qanday matn (guruh nomi, juftlik) HTML uchun ekranlanadi.
  - Bot bilan ALOHIDA servis: bu yerda nima bo'lsa ham signal kuzatuvi
    to'xtamaydi.
"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import sys
import time
from datetime import datetime
from urllib.parse import parse_qsl

import httpx

from aiohttp import web

import chart
import config
import dipfunded
import db
import i18n
import paymembers
import tournament
import stats
import tracker
import webapp

log = logging.getLogger("web")

# Brauzer/Telegram HTML'ni SAQLAMASIN. Server keshi (CACHE_TTL) baribir
# ishlaydi, lekin Telegram WebView eski sahifani ko'rsatib turishi
# yangilanish chiqqanda foydalanuvchini adashtirardi.
NO_CACHE = {"Cache-Control": "no-store, max-age=0"}

# JSON nuqtasi boshqa domendan (to'lov botining Mini App'i) o'qiladi.
# Ma'lumot allaqachon ochiq sahifada ko'rinib turibdi — CORS yangi
# hech narsa oshkor qilmaydi, faqat o'qishni mumkin qiladi.
JSON_HEADERS = {**NO_CACHE, "Access-Control-Allow-Origin": "*"}


CACHE_TTL = 120.0          # sahifa/grafik keshi (soniya)
_cache: dict[str, tuple[float, object]] = {}


# Yopilgan savdo grafigi HECH QACHON o'zgarmaydi (savdo tugagan, shamlar
# tarixiy) — shuning uchun uzoq keshlanadi va birjaga faqat bir marta
# murojaat qilinadi. Aks holda bitta sahifa ochilishi o'nlab so'rov yuborib,
# birja limitini yeb qo'yardi va kuzatuv siklini ham buzardi.
MINI_TTL = 86400.0


def _cached(key: str, ttl: float = CACHE_TTL):
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < ttl:
        return hit[1]
    return None


def _put(key: str, value):
    # Kesh cheksiz o'smasin: eng eski yozuvlar tashlanadi.
    if len(_cache) > 200:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
            _cache.pop(k, None)
    _cache[key] = (time.monotonic(), value)
    return value


def e(x) -> str:
    return html.escape(str(x if x is not None else ""))


def fmt_price(x) -> str:
    x = float(x)
    if x >= 100:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:,.4f}"
    return f"{x:.8f}".rstrip("0")


def _cls(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "")


def post_url(ws, msg_id, members_only: bool = False) -> str | None:
    """Kanal/guruhdagi post havolasi (209, 210). @nik bo'lsa
    t.me/<nik>/<id>, aks holda t.me/c/<id>/<id> — bu faqat a'zolar
    uchun ochiladi. `members_only` — havola faqat a'zolarga ochilishi
    SHART (guruhdagi OCHIQ savdo: juftlik a'zolarning haqqi), shuning
    uchun @nikli ommaviy guruhda bunday havola berilmaydi."""
    if not msg_id:
        return None
    if ws["username"]:
        if members_only:
            return None
        return f"https://t.me/{ws['username']}/{int(msg_id)}"
    cid = str(ws["group_chat_id"] or "")
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{int(msg_id)}"
    return None


def req_lang(request, ws=None, reader_first: bool = True) -> str:
    """Sahifa tili.

    Tartib:
      1. `?lang=ru` — ODAM til tugmasini bosgan (yoki chaqiruvchi aniq
         so'ragan). Har doim ustun.
      2. brauzerning `Accept-Language` sarlavhasi — sahifani O'QIYOTGAN
         odam haqidagi yagona signal. Sahifa ochiq, marketing uchun:
         ruszabon mehmon uni ruscha ko'rgani ma'qul.
      3. guruh tili (`workspaces.lang`) — brauzer tili uchtasidan
         birortasiga to'g'ri kelmasa.
      4. o'zbekcha.

    `reader_first=False` — 2 va 3 o'rin ALMASHADI (guruh tili ustun
    bo'ladi). `stats.json` shuni ishlatadi: uni to'lov botining Mini
    App'i o'qiydi va u yerdagi yozuvlar guruh sahifasi bilan bir xil
    bo'lib qolishi kerak — shartnomani jimgina o'zgartirmaymiz.

    Avval guruh tili brauzerdan USTUN edi. Til tugmalari qo'shilgach
    bu mantiqsiz bo'lib qoldi: mehmon sahifani begona tilda ochib,
    keyin qo'lda almashtirishi kerak edi. Endi teskarisi — o'zi
    kerakli tilda ochiladi, tugma esa istalgan paytda o'zgartiradi.
    """
    q = request.query.get("lang")
    if q and i18n.normalize(q) == q.lower():
        return q.lower()

    def from_ws():
        if ws is None:
            return None
        try:
            return i18n.normalize(ws["lang"]) if ws["lang"] else None
        except (KeyError, TypeError):
            return None

    def from_browser():
        header = request.headers.get("Accept-Language", "")
        for part in header.split(","):
            code = part.split(";")[0].strip().lower()[:2]
            if code in i18n.LANGS:
                return code
        return None

    order = (from_browser, from_ws) if reader_first else (from_ws, from_browser)
    for src in order:
        got = src()
        if got:
            return got
    return i18n.DEFAULT_LANG


def net_result(r) -> float:
    """Guruh natijasi — guruh sahifasidagi AYNI usul: pozitsiya hajmi
    belgilangan bo'lsa depozitga tortilgan, aks holda sof foizlar yig'indisi."""
    if r.get("deposit") and r.get("n_alloc"):
        return stats.net_vs_start(float(r["sum_weighted"]))
    return float(r["sum_pct"])


async def _group_numbers(ws, lang: str | None = None, kind: str = "spot") -> dict:
    """Guruhning asosiy raqamlari — HTML sahifa ham, JSON ham SHU yerdan oladi.

    Ataylab bitta funksiya: to'lov boti (whale-payment-bot) Mini App'i
    `/g/<id>/stats.json`ni o'qiydi va u yerda ko'rinadigan son guruh
    sahifasidagi son bilan AYNAN bir xil bo'lishi shart. Ikki joyda ikki
    marta hisoblansa, ular vaqt o'tib bir-biridan uzilib ketardi."""
    ws_id = ws["id"]
    # 227: spot va futures ALOHIDA (futures — foiz leveraj bilan, o'z depoziti).
    with db.stats_kind(kind):
        s = await db.period_stats(ws_id)
        rows = await db.equity_series(ws_id)
    deposit = ws["fut_deposit"] if kind == "fut" else ws["deposit"]
    total = s["total"] or 0

    pnls = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
    weighted = None
    if deposit:
        weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                    for r in rows
                    if r["pnl_pct"] is not None and r["alloc_amount"] is not None]
    # ⚠️ `sum(weighted)` foydani JORIY (o'sib ketgan) depozitga bo'ladi —
    # `stats.net_vs_start()` uni boshlang'ich kapitalga qayta hisoblaydi,
    # shunda plitka va equity grafigi bir xil sonni ko'rsatadi.
    net = stats.net_vs_start(sum(weighted)) if weighted else sum(pnls)
    net_label = i18n.t("w.tile_net_dep" if weighted else "w.tile_net", lang)
    wr = (s["wins"] / total * 100) if total else 0
    avg_r = float(s["avg_r"] or 0)

    return {
        "total": total,
        "wins": s["wins"] or 0,
        "winrate": wr,
        "net": net,
        "net_label": net_label,
        "avg_r": avg_r,
        # Grafik faqat kamida ikkita nuqta bo'lsa chiziladi (chaqiruvchiga kerak).
        "n_pnl": len(pnls),
        # Plitalar — sahifadagi va JSON'dagi ro'yxat AYNAN shu.
        "tiles": [
            (i18n.t("w.tile_closed", lang), f"{total}", ""),
            (i18n.t("w.tile_winrate", lang), f"{wr:.1f}%", ""),
            (net_label, f"{net:+.2f}%", _cls(net)),
            (i18n.t("w.tile_avg_r", lang), f"{avg_r:+.2f}", _cls(avg_r)),
        ] + ([(i18n.t("w.tile_liqs", lang),      # 228/229: soni va ulushi
               f"{s['liqs']} ({s['liqs'] / total * 100:.0f}%)", "neg")]
             if kind == "fut" and s["liqs"] else []),
    }


async def stats_json(request):
    """Guruh raqamlari JSON ko'rinishida — to'lov botining Mini App'i uchun.

    Darvoza `group_page` bilan BIR XIL (`public_workspace`): bu nuqta yangi
    ruxsat ochmaydi, allaqachon ochiq sahifada ko'rinib turgan raqamlarnigina
    mashina o'qiy oladigan shaklda beradi. Shu sabab CORS ham ochiq."""
    ws_id = int(request.match_info["wid"])
    ws = await db.public_workspace(ws_id)
    if not ws:
        return web.json_response({"error": "not_public"}, status=404,
                                 headers=JSON_HEADERS)

    # `reader_first=False`: bu nuqtani to'lov botining Mini App'i o'qiydi,
    # undagi yorliqlar guruh sahifasidagi bilan bir xil bo'lib qolsin.
    lang = req_lang(request, ws, reader_first=False)
    cached = _cached(f"j{ws_id}:{lang}")
    if cached is None:
        n = await _group_numbers(ws, lang)
        # Ochiq (ACTIVE) pozitsiyalar soni — juftlik nomisiz, faqat son.
        live = [r for r in await db.live_signals(ws_id) if r["status"] == "ACTIVE"]
        cached = _put(f"j{ws_id}:{lang}", {
            "id": ws_id,
            "name": ws["name"],
            "total": n["total"],
            "wins": n["wins"],
            "winrate": round(n["winrate"], 1),
            "net_pct": round(n["net"], 2),
            "net_label": n["net_label"],
            "avg_r": round(n["avg_r"], 2),
            "open": len(live),
            # Sahifaga havola. `embed=1` — chaqiruvchi (to'lov botining Mini
            # App'i) buni O'Z ichida, iframe'da ochadi: "Barcha guruhlar"
            # havolasi ham, Telegram skripti ham chiqmaydi.
            # Til FAQAT chaqiruvchi uni aniq so'ragan bo'lsa qo'shiladi:
            # aks holda guruh sahifasi baribir guruh tilida ochiladi, ya'ni
            # `&lang=` hech narsani o'zgartirmasdi, lekin havola shaklini
            # (to'lov boti Mini App'i shu satrni ishlatadi) o'zgartirib
            # yuborardi.
            # 252: yangi sahifa (Mini App) — eski HTML sahifa yo'q.
            "url": f"/app?g={ws_id}",
            "cards": [{"label": k, "value": v} for k, v, _c in n["tiles"]],
        })
    return web.json_response(cached, headers=JSON_HEADERS)


INIT_MAX_AGE = 24 * 3600
_member_cache: dict[tuple[int, int], tuple[float, bool]] = {}
MEMBER_TTL = 300.0


def verify_init_data(init_data: str, token: str | None = None) -> int | None:
    """Telegram Mini App initData imzosi (HMAC-SHA256, kalit
    HMAC("WebAppData", BOT_TOKEN)). To'g'ri va 24 soatdan yangi bo'lsa —
    foydalanuvchi id'si."""
    token = token if token is not None else config.BOT_TOKEN
    if not token or not init_data:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None
    got = pairs.pop("hash", "")
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not got or not hmac.compare_digest(want, got):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > INIT_MAX_AGE:
            return None
        return int(json.loads(pairs.get("user", "{}"))["id"])
    except (ValueError, KeyError, TypeError):
        return None


async def is_member(ws, uid: int) -> bool:
    """Egasi, super-admin yoki guruhning JONLI a'zosi (getChatMember)."""
    if uid == ws["owner_id"] or uid in config.ADMIN_IDS:
        return True
    key = (ws["id"], uid)
    hit = _member_cache.get(key)
    if hit and time.monotonic() - hit[0] < MEMBER_TTL:
        return hit[1]
    ok = False
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"https://api.telegram.org/bot{config.BOT_TOKEN}/getChatMember",
                            params={"chat_id": ws["group_chat_id"], "user_id": uid})
        res = r.json().get("result") or {}
        st = res.get("status")
        ok = st in ("creator", "administrator", "member") or (
            st == "restricted" and bool(res.get("is_member")))
    except Exception:
        log.warning("A'zolik tekshirilmadi (ws=%s)", ws["id"], exc_info=True)
        return False          # xatoni keshlamaymiz
    _member_cache[key] = (time.monotonic(), ok)
    return ok


async def equity_png(request):
    ws_id = int(request.match_info["wid"])
    ws = await db.public_workspace(ws_id)
    if not ws:
        raise web.HTTPNotFound()
    # Grafik ichidagi yozuvlar sahifa bilan BIR XIL tilda bo'lishi kerak,
    # shuning uchun kesh kaliti ham tilni o'z ichiga oladi — aks holda
    # birinchi tashrifchi tili hammaga keshlanib qolardi.
    lang = req_lang(request, ws)
    key = f"eq{ws_id}:{lang}"
    buf = _cached(key)
    if buf is None:
        # Grafik chizish qimmat (matplotlib) — shu sabab keshlanadi.
        img = await stats.equity_chart(ws_id, ws["deposit"], lang=lang)
        if img is None:
            raise web.HTTPNotFound()
        buf = _put(key, img.getvalue())
    return web.Response(body=buf, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=120"})


async def logo_png(request):
    """Guruh logotipi (Telegram avatari). Bazadan o'qiladi — veb servisda
    BOT_TOKEN yo'q, Telegram'ga umuman murojaat qilinmaydi."""
    ws_id = int(request.match_info["wid"])
    data = await db.public_logo(ws_id)
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(data), content_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


async def avatar_jpg(request):
    """271: DIP reytingidagi odam avatari (bazadan; kalit tasodifiy)."""
    data = await db.user_avatar(request.match_info["key"])
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(data), content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=3600"})


async def task_logo_png(request):
    """294: DIP Earn vazifasi avatari (bazadan)."""
    data = await db.dip_task_logo(int(request.match_info["tid"]))
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(data), content_type="image/png",
                        headers={"Cache-Control": "public, max-age=3600"})


async def share_jpg(request):
    """300: signal natijasini ulashish rasmi (bot yaratadi, bazada 30 kun)."""
    data = await db.share_image_get(request.match_info["key"])
    if not data:
        raise web.HTTPNotFound()
    return web.Response(body=bytes(data), content_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


async def mini_png(request):
    """Bitta yopilgan savdoning kichik grafigi.

    Signal o'zi emas, uning WORKSPACE'i darvozadan o'tishi tekshiriladi —
    yopiq guruh signalini id taxmin qilib ko'rish mumkin emas."""
    sig_id = int(request.match_info["sid"])
    key = f"mini{sig_id}"
    buf = _cached(key, MINI_TTL)
    if buf is None:
        sig = await db.public_signal(sig_id)
        if not sig:
            raise web.HTTPNotFound()
        # Brauzer sahifadagi barcha rasmni BIRDAN so'raydi (25 tagacha).
        # Semafor ularni navbatga qo'yadi: birjaga bir vaqtda ko'pi bilan
        # ikkita so'rov ketadi, ya'ni bitta sahifa ochilishi rate-limit'ga
        # urilib, kuzatuv siklini ham buzib qo'ymaydi.
        async with request.app["mini_sem"]:
            buf = _cached(key, MINI_TTL)     # navbatda turganda tayyor bo'lishi mumkin
            if buf is None:
                try:
                    img = await chart.mini_chart(sig)
                except Exception:
                    log.warning("Kichik grafik yasalmadi (#%s)", sig_id, exc_info=True)
                    img = None
                if img is None:
                    raise web.HTTPNotFound()
                buf = _put(key, img.getvalue())
    return web.Response(body=buf, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


def _to_app(query: str):
    async def h(request):
        raise web.HTTPFound(f"/app?{query}")
    return h


async def _to_group(request):
    raise web.HTTPFound(f"/app?g={int(request.match_info['wid'])}")


async def healthz(request):
    return web.Response(text="ok")


async def on_start(app):
    await db.init()
    log.info("Veb: bazaga ulandi")


async def on_stop(app):
    if db._pool is not None:
        await db._pool.close()


@web.middleware
async def security_headers(request, handler):
    """Asosiy xavfsizlik sarlavhalari (191). `X-Frame-Options` ATAYLAB yo'q:
    sahifa to'lov botining Mini App'i ichida iframe'da ochiladi (`?embed=1`)."""
    resp = await handler(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


def build_app() -> web.Application:
    app = web.Application(middlewares=[security_headers])
    app["bot_username"] = os.getenv("BOT_USERNAME", "")
    # Birjaga bir vaqtda ketadigan grafik so'rovlari soni (pastda izoh).
    app["mini_sem"] = asyncio.Semaphore(2)
    app.add_routes([
        # 252: eski HTML sahifalar o'chirildi — hammasi yagona Mini App'da.
        web.get("/", _to_app("")),   # 273: Telegram ichida — Bosh; brauzerda baribir Top
        web.get("/healthz", healthz),
        web.get(r"/g/{wid:\d+}", _to_group),
        web.get(r"/g/{wid:\d+}/", _to_group),
        web.get("/t", _to_app("tab=tour")),
        web.get(r"/t/{tid:\d+}", _to_app("tab=tour")),
        web.get(r"/g/{wid:\d+}/stats.json", stats_json),
        web.get(r"/g/{wid:\d+}/equity.png", equity_png),
        web.get(r"/g/{wid:\d+}/logo.png", logo_png),
        web.get(r"/av/{key:[A-Za-z0-9_-]{8,20}}.jpg", avatar_jpg),
        web.get(r"/tl/{tid:\d+}.png", task_logo_png),
        web.get(r"/sc/{key:[A-Za-z0-9_-]{8,20}}.jpg", share_jpg),
        web.get(r"/s/{sid:\d+}/mini.png", mini_png),
    ])
    # 238: Mini App (bosh sahifa + ochiq signallar boshqaruvi).
    webapp.VERIFY = verify_init_data
    webapp.W = sys.modules[__name__]
    app.add_routes(webapp.routes())
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    # httpx har so'rov URL'ini INFO'da yozadi — Twelve Data `apikey`
    # parametri bilan birga (191). Bot servisidagi kabi o'chiriladi.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    web.run_app(build_app(), port=int(os.getenv("PORT", 8080)))
