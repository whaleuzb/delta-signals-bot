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
import html
import logging
import os
import time
from datetime import datetime

from aiohttp import web

import config
import db
import stats

log = logging.getLogger("web")

CACHE_TTL = 120.0          # sahifa/grafik keshi (soniya)
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str):
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < CACHE_TTL:
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


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0b0e14;--card:#141a22;--line:#232b36;--mut:#8592a3;--ink:#eef2f7;
      --acc:#4da3ff;--long:#2ecc8f;--short:#ff5c5c;--silver:#8a8f99}
body{background:var(--bg);color:var(--ink);
     font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     line-height:1.5;padding:0 20px 64px}
.wrap{max-width:980px;margin:0 auto}
header{padding:34px 0 26px;border-bottom:1px solid var(--line);margin-bottom:32px}
.brand{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;font-weight:600;
       letter-spacing:.26em;color:var(--silver);text-transform:uppercase}
h1{font-size:clamp(26px,5vw,40px);font-weight:700;letter-spacing:-.02em;margin-top:8px}
.sub{color:var(--mut);margin-top:6px;font-size:15px}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:30px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px}
.tile .k{font-size:12px;color:var(--mut);letter-spacing:.06em;text-transform:uppercase}
.tile .v{font-size:26px;font-weight:700;margin-top:6px;font-variant-numeric:tabular-nums}
.pos{color:var(--long)}.neg{color:var(--short)}
h2{font-size:19px;font-weight:600;margin:34px 0 14px}
.chart{width:100%;border:1px solid var(--line);border-radius:12px;display:block}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px}
th,td{padding:11px 12px;text-align:right;border-bottom:1px solid var(--line);
      font-variant-numeric:tabular-nums;white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:12px;letter-spacing:.05em;
   text-transform:uppercase;text-align:right}
th:first-child,td:first-child{text-align:left}
tbody tr:hover{background:#ffffff06}
.badge{display:inline-block;padding:2px 8px;border-radius:5px;font-size:12px;font-weight:600}
.b-long{background:#2ecc8f22;color:var(--long)}
.b-short{background:#ff5c5c22;color:var(--short)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.gcard{background:var(--card);border:1px solid var(--line);border-radius:12px;
       padding:18px 20px;display:block;color:inherit}
.gcard:hover{border-color:#3a4351;text-decoration:none}
.gcard .n{font-size:17px;font-weight:600}
.gcard .m{color:var(--mut);font-size:13px;margin-top:6px}
footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);
       color:var(--mut);font-size:13px;display:flex;justify-content:space-between;
       flex-wrap:wrap;gap:10px}
.empty{color:var(--mut);padding:26px 0}
"""

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600;700'
         '&display=swap">')


def page(title: str, body: str, bot: str | None) -> str:
    link = f'<a href="https://t.me/{e(bot)}">@{e(bot)}</a>' if bot else "Trade Controller"
    return (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='dark'>"
        f"<title>{e(title)}</title>{FONTS}<style>{CSS}</style></head><body>"
        f"<div class='wrap'>{body}"
        f"<footer><div>Trade Controller — {link}</div>"
        f"<div>Ma'lumot bazadan jonli o'qiladi</div></footer></div></body></html>")


def _cls(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "")


async def index(request):
    bot = request.app["bot_username"]
    cached = _cached("index")
    if cached is None:
        rows = await db.public_workspaces()
        cards = []
        for r in rows:
            total = r["total"] or 0
            wr = (r["wins"] / total * 100) if total else 0
            when = (f"oxirgi natija {r['last_closed'].astimezone(stats.TZ):%d.%m.%Y}"
                    if r["last_closed"] else "hali natija yo'q")
            cards.append(
                f"<a class='gcard' href='/g/{r['id']}'><div class='n'>{e(r['name'])}</div>"
                f"<div class='m'>{total} ta yopilgan signal · winrate {wr:.0f}%<br>{e(when)}</div></a>")
        body = (
            "<header><div class='brand'>Trade Controller</div>"
            "<h1>Ochiq natijalar</h1>"
            "<div class='sub'>Quyidagi guruhlar o'z statistikasini ommaga ochgan. "
            "Raqamlar bevosita bazadan o'qiladi va real vaqtda yangilanadi.</div></header>"
            + (f"<div class='cards'>{''.join(cards)}</div>" if cards else
               "<div class='empty'>Hozircha ochiq guruh yo'q.</div>"))
        cached = _put("index", page("Ochiq natijalar — Trade Controller", body, bot))
    return web.Response(text=cached, content_type="text/html")


async def group_page(request):
    ws_id = int(request.match_info["wid"])
    bot = request.app["bot_username"]
    ws = await db.public_workspace(ws_id)
    if not ws:
        raise web.HTTPNotFound(text="Bunday sahifa yo'q yoki u ochiq emas.")

    cached = _cached(f"g{ws_id}")
    if cached is not None:
        return web.Response(text=cached, content_type="text/html")

    s = await db.period_stats(ws_id)
    rows = await db.equity_series(ws_id)
    deposit = ws["deposit"]
    total = s["total"] or 0

    pnls = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
    weighted = None
    if deposit:
        weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                    for r in rows
                    if r["pnl_pct"] is not None and r["alloc_amount"] is not None]
    net = sum(weighted) if weighted else sum(pnls)
    net_label = "Jami natija (depozitga nisbatan)" if weighted else "Jami natija"
    wr = (s["wins"] / total * 100) if total else 0
    avg_r = float(s["avg_r"] or 0)

    tiles = [
        ("Yopilgan signallar", f"{total}", ""),
        ("Winrate", f"{wr:.1f}%", ""),
        (net_label, f"{net:+.2f}%", _cls(net)),
        ("O'rtacha R", f"{avg_r:+.2f}", _cls(avg_r)),
    ]
    tiles_html = "".join(
        f"<div class='tile'><div class='k'>{e(k)}</div>"
        f"<div class='v {c}'>{e(v)}</div></div>" for k, v, c in tiles)

    # Juftliklar
    syms = await db.top_symbols(ws_id, limit=12)
    sym_rows = "".join(
        f"<tr><td>{e(r['symbol'])}</td><td>{r['closed']}</td>"
        f"<td>{(r['wins'] / r['closed'] * 100) if r['closed'] else 0:.0f}%</td>"
        f"<td class='{_cls(float(r['sum_pct']))}'>{float(r['sum_pct']):+.2f}%</td></tr>"
        for r in syms)

    # Oylik
    months = await db.monthly_breakdown(ws_id, limit=12)
    mon_rows = "".join(
        f"<tr><td>{stats.MONTHS_UZ[r['month'].month - 1]} {r['month'].year}</td>"
        f"<td>{r['total']}</td>"
        f"<td>{(r['wins'] / r['total'] * 100) if r['total'] else 0:.0f}%</td>"
        f"<td class='{_cls(float(r['sum_pct']))}'>{float(r['sum_pct']):+.2f}%</td></tr>"
        for r in months)

    # Oxirgi savdolar
    recent = await db.recent_closed(ws_id, 25)
    rec_rows = ""
    for r in recent:
        p = float(r["pnl_pct"]) if r["pnl_pct"] is not None else 0.0
        side_cls = "b-long" if r["side"] == "LONG" else "b-short"
        when = f"{r['closed_at'].astimezone(stats.TZ):%d.%m.%y}" if r["closed_at"] else "—"
        rec_rows += (
            f"<tr><td>{e(r['symbol'])} "
            f"<span class='badge {side_cls}'>{e(r['side'])}</span></td>"
            f"<td>{fmt_price(r['entry'])}</td>"
            f"<td>{fmt_price(r['exit_price']) if r['exit_price'] is not None else '—'}</td>"
            f"<td class='{_cls(p)}'>{p:+.2f}%</td>"
            f"<td>{e(when)}</td></tr>")

    def section(title, header, body_rows):
        if not body_rows:
            return ""
        return (f"<h2>{e(title)}</h2><div class='scroll'><table><thead><tr>{header}</tr>"
                f"</thead><tbody>{body_rows}</tbody></table></div>")

    invite = ""
    if ws["invite_link"]:
        invite = (f" · <a href='{e(ws['invite_link'])}' rel='nofollow noopener'>"
                  "Guruhga qo'shilish</a>")

    body = (
        f"<header><div class='brand'>Trade Controller</div><h1>{e(ws['name'])}</h1>"
        f"<div class='sub'><a href='/'>← Barcha guruhlar</a>{invite}</div></header>"
        f"<div class='grid'>{tiles_html}</div>"
        + (f"<h2>Balans o'zgarishi</h2>"
           f"<img class='chart' src='/g/{ws_id}/equity.png' alt='Equity' loading='lazy'>"
           if len(pnls) >= 2 else "")
        + section("Juftliklar kesimi",
                  "<th>Juftlik</th><th>Savdo</th><th>Winrate</th><th>Natija</th>", sym_rows)
        + section("Oylik natijalar",
                  "<th>Oy</th><th>Savdo</th><th>Winrate</th><th>Natija</th>", mon_rows)
        + section("Oxirgi savdolar",
                  "<th>Juftlik</th><th>Kirish</th><th>Chiqish</th><th>Natija</th><th>Sana</th>",
                  rec_rows)
        + ("<div class='empty'>Hali yopilgan signal yo'q.</div>" if not total else ""))

    out = page(f"{ws['name']} — natijalar", body, bot)
    _put(f"g{ws_id}", out)
    return web.Response(text=out, content_type="text/html")


async def equity_png(request):
    ws_id = int(request.match_info["wid"])
    ws = await db.public_workspace(ws_id)
    if not ws:
        raise web.HTTPNotFound()
    key = f"eq{ws_id}"
    buf = _cached(key)
    if buf is None:
        # Grafik chizish qimmat (matplotlib) — shu sabab keshlanadi.
        img = await stats.equity_chart(ws_id, ws["deposit"])
        if img is None:
            raise web.HTTPNotFound()
        buf = _put(key, img.getvalue())
    return web.Response(body=buf, content_type="image/png",
                        headers={"Cache-Control": "public, max-age=120"})


async def healthz(request):
    return web.Response(text="ok")


async def on_start(app):
    await db.init()
    log.info("Veb: bazaga ulandi")


async def on_stop(app):
    if db._pool is not None:
        await db._pool.close()


def build_app() -> web.Application:
    app = web.Application()
    app["bot_username"] = os.getenv("BOT_USERNAME", "")
    app.add_routes([
        web.get("/", index),
        web.get("/healthz", healthz),
        web.get(r"/g/{wid:\d+}", group_page),
        web.get(r"/g/{wid:\d+}/equity.png", equity_png),
    ])
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    return app


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    web.run_app(build_app(), port=int(os.getenv("PORT", 8080)))
