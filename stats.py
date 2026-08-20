"""Statistika hisobotlari va equity curve."""
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D

import config
import db
import exchange
import forex
import tracker

TZ = ZoneInfo(config.TZ)

# Grafik ranglari (bot xabarlaridagi qorong'i mavzuga mos)
BG = "#0e1117"
GRID = "#2a2f3a"
TXT = "#9aa4b2"
TITLE = "#e6e9ef"
GREEN = "#26a69a"
RED = "#ef5350"


def _provider(market: str):
    """market='forex' bo'lsa Twelve Data, aks holda MEXC (kripto)."""
    return forex if market == "forex" else exchange
MONTHS_UZ = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]


def _compound(pcts: list[float]) -> float:
    """Har savdoda bir xil ulush ishlatilsa — kompaund natija."""
    eq = 1.0
    for p in pcts:
        eq *= (1 + p / 100)
    return (eq - 1) * 100


async def _open_summary(workspace_id: int, deposit, show_money: bool) -> str | None:
    """Hali yopilmagan (PENDING/ACTIVE) pozitsiyalar qisqacha holati — /symbols'dagi
    kabi hisobot davri "joriy"ga tegishli bo'lsa summary() shuni ham qo'shadi,
    aks holda foydalanuvchi "nega ochiq pozitsiyalar hisobotda yo'q" deb
    chalkashishi mumkin edi."""
    rows = await db.live_signals(workspace_id)
    pending = [r for r in rows if r["status"] == "PENDING"]
    active = [r for r in rows if r["status"] == "ACTIVE"]
    if not pending and not active:
        return None

    lines = ["<b>Jarayondagi pozitsiyalar</b>"]
    if pending:
        lines.append(f"🕐 Kutilmoqda: <b>{len(pending)}</b> ta (hali limitga yetmagan)")

    if active:
        live_sum_pct = 0.0
        live_money = 0.0
        live_count = 0
        for r in active:
            price = await _provider(r["market"]).last_price(r["symbol"])
            if price is None:
                continue
            pnl = tracker.pnl_at(r["side"], float(r["entry"]), price)
            live_count += 1
            if deposit and r["alloc_amount"] is not None:
                live_money += pnl / 100 * float(r["alloc_amount"])
                live_sum_pct += pnl * float(r["alloc_amount"]) / float(deposit)

        if not live_count:
            lines.append(f"⏳ Jarayonda: <b>{len(active)}</b> ta ochiq (narx olinmadi)")
        elif deposit:
            txt = f"⏳ Jarayonda: <b>{live_count}</b> ta ochiq — joriy: <b>{live_sum_pct:+.2f}%</b>"
            if show_money:
                txt += f"  ({live_money:+,.2f})"
            lines.append(txt)
        else:
            lines.append(f"⏳ Jarayonda: <b>{live_count}</b> ta ochiq "
                          f"(joriy foiz uchun /depozit belgilang)")

    return "\n".join(lines)


async def summary(workspace_id: int, since=None, until=None, title="Umumiy statistika",
                   deposit=None, show_money: bool = True) -> str:
    """deposit — workspace'ning joriy umumiy depoziti. Bo'lsa, "Jami natija"/
    "Kompaund" har bir signalning haqiqiy pozitsiya hajmiga (alloc_amount)
    qarab depozitga nisbatan hisoblanadi — narx harakati foizi emas, depozitning
    necha foizga o'sgani ko'rsatiladi (aks holda har savdo butun depozit bilan
    kirilgandek hisoblanib, natija sun'iy shishib ketardi). Deposit
    belgilanmagan bo'lsa — eski, pozitsiya hajmisiz (raw) narx-harakati foizi
    ko'rsatiladi. show_money — real summani ko'rsatish kerakmi (guruh
    a'zolariga faqat foiz, admin/shaxsiy egasiga pul ham)."""
    s = await db.period_stats(workspace_id, since, until)
    show_open = since is None or until is None or until > datetime.now(timezone.utc)

    if not s or s["total"] == 0:
        t = [f"<b>{title}</b>", "", "Hali yopilgan signal yo'q."]
    else:
        total = s["total"]
        wr = s["wins"] / total * 100
        pf = None
        if s["avg_loss"] and s["losses"]:
            gross_win = float(s["avg_win"]) * s["wins"]
            gross_loss = abs(float(s["avg_loss"])) * s["losses"]
            pf = gross_win / gross_loss if gross_loss else None

        rows = await db.equity_series(workspace_id, since, until)
        weighted = None
        if deposit:
            weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                        for r in rows
                        if r["pnl_pct"] is not None and r["alloc_amount"] is not None]

        t = [f"<b>{title}</b>", ""]
        t.append(f"Signallar: <b>{total}</b>  ({s['wins']}✅ / {s['losses']}❌ / {s['be']}⚪)")
        t.append(f"Winrate: <b>{wr:.1f}%</b>")

        if weighted:
            real_sum_pct = sum(weighted)
            t.append(f"Jami natija (depozitga nisbatan): <b>{real_sum_pct:+.2f}%</b>")
            t.append(f"Kompaund: <b>{_compound(weighted):+.2f}%</b>")
            if show_money and s["real_pnl_money"] is not None:
                t.append(f"💰 Real natija: <b>{float(s['real_pnl_money']):+,.2f}</b>")
        else:
            pcts = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
            t.append(f"Jami foiz (pozitsiya hajmisiz): <b>{float(s['sum_pct']):+.2f}%</b>")
            t.append(f"Kompaund: <b>{_compound(pcts):+.2f}%</b>")

        t.append(f"O'rtacha R: <b>{float(s['avg_r']):+.2f}R</b>   |   Jami: <b>{float(s['sum_r']):+.1f}R</b>")
        t.append(f"O'rt. foyda: {float(s['avg_win']):+.2f}%   |   O'rt. zarar: {float(s['avg_loss']):+.2f}%")
        if pf:
            t.append(f"Profit factor: <b>{pf:.2f}</b>")

    if show_open:
        open_txt = await _open_summary(workspace_id, deposit, show_money)
        if open_txt:
            t += ["", open_txt]

    return "\n".join(t)


async def monthly_table(workspace_id: int, limit: int = 12) -> str:
    rows = await db.monthly_breakdown(workspace_id, limit)
    if not rows:
        return "Ma'lumot yo'q."
    t = ["<b>Oylik natijalar</b>", "<pre>"]
    t.append(f"{'Oy':<12}{'N':>4}{'WR':>7}{'Foiz':>9}{'R':>7}")
    for r in rows:
        m = r["month"]
        name = f"{MONTHS_UZ[m.month - 1][:3]} {m.year}"
        wr = r["wins"] / r["total"] * 100 if r["total"] else 0
        t.append(f"{name:<12}{r['total']:>4}{wr:>6.0f}%{float(r['sum_pct']):>+9.2f}{float(r['avg_r']):>+7.2f}")
    t.append("</pre>")
    return "\n".join(t)


async def symbols_table(workspace_id: int, since=None, until=None,
                         title: str = "Barcha davr") -> str:
    """since/until berilmasa — butun davr. Berilsa — shu oraliqda yopilganlar
    (o'tgan, tugagan oylarda ochiq pozitsiya ko'rinmaydi — yopilganda avtomatik
    o'z oyiga tushadi). Joriy (hali davom etayotgan) davrda — hozir ochiq
    pozitsiyalar ham ko'rinadi: ⏳ allaqachon ochilgan (joriy foizi bilan),
    🕐 hali entry/limitga tegmagan (foizsiz — hisoblash uchun asos yo'q)."""
    show_open = since is None or until is None or until > datetime.now(timezone.utc)
    rows = await db.top_symbols(workspace_id, since, until)
    open_data = await db.open_signals_summary(workspace_id) if show_open else {}
    symbols = {r["symbol"] for r in rows} | set(open_data)
    if not symbols:
        return f"<b>Juftliklar — {title}</b>\n\nMa'lumot yo'q."

    by_sym = {r["symbol"]: r for r in rows}
    ordered = sorted(symbols, key=lambda s: -float(by_sym[s]["sum_pct"]) if s in by_sym else 0)

    def badge(icon: str, n: int) -> str:
        return icon if n == 1 else f"{icon}{n}"

    t = [f"<b>Juftliklar — {title}</b>", ""]
    for sym in ordered:
        r = by_sym.get(sym)
        closed = r["closed"] if r else 0
        wins = r["wins"] if r else 0
        losses = closed - wins
        sum_pct = float(r["sum_pct"]) if r else 0.0
        od = open_data.get(sym, {"pending": 0, "active": []})
        pending_n = od["pending"]
        active_list = od["active"]

        live_sum = 0.0
        live_count = 0
        for pos in active_list:
            price = await _provider(pos["market"]).last_price(sym)
            if price:
                live_sum += tracker.pnl_at(pos["side"], pos["entry"], price)
                live_count += 1

        badges = []
        if wins:
            badges.append(badge("🟢", wins))
        if losses:
            badges.append(badge("🔴", losses))
        if active_list:
            badges.append(badge("⏳", len(active_list)))
        if pending_n:
            badges.append(badge("🕐", pending_n))
        badge_txt = " ".join(badges) if badges else "—"

        parts = []
        if closed:
            parts.append(f"<b>{sum_pct:+.2f}%</b>")
        if live_count:
            parts.append(f"<i>{live_sum:+.2f}% jarayonda</i>")
        pct_txt = "  ".join(parts) if parts else "<i>ochiq</i>"

        t.append(f"{badge_txt} <b>{sym}</b>  {pct_txt}")
    return "\n".join(t)


async def equity_chart(workspace_id: int, deposit=None) -> io.BytesIO | None:
    """Ikki panelli grafik — YUQORIDA kumulyativ balans, PASTDA har bir savdoning
    alohida hissasi. Ikkalasi bir xil x o'qini (savdo tartibi) bo'lishadi, lekin
    har biri o'z o'lchovida — ataylab twinx (ikkita y o'qi bitta panelda)
    ISHLATILMAYDI: unda ustunlar va chiziqning nol nuqtasi mos kelmay, chiziq
    ustunlar orasidan kesib o'tib chalkash ko'rinish berardi.

    deposit berilsa — hammasi REAL pulda: har savdo o'z `alloc_amount`i bo'yicha
    depozitga qo'shiladi (`summary()` bilan bir xil mantiq — `pnl_pct`ni
    to'g'ridan-to'g'ri kompaundlash emas, u har savdoni butun depozit bilan
    kirilgandek hisoblab natijani sun'iy shishirardi). Boshlang'ich balans joriy
    depozitdan shu davrdagi real natijani ayirib (orqaga qarab) topiladi.
    deposit yo'q bo'lsa — eski, pozitsiya hajmisiz ko'rinish: balans 100 dan
    boshlanadi, ustunlar esa sof `pnl_pct`."""
    rows = await db.equity_series(workspace_id)
    if len(rows) < 2:
        return None

    weighted = deposit is not None
    n = len(rows)
    deltas, eq = [], []

    if weighted:
        deposit = float(deposit)
        deltas = [float(r["pnl_pct"]) / 100 * float(r["alloc_amount"])
                  if r["alloc_amount"] is not None else 0.0
                  for r in rows]
        cur = deposit - sum(deltas)
        base = cur
        for d in deltas:
            cur += d
            eq.append(cur)
    else:
        base = 100.0
        cur = base
        for r in rows:
            deltas.append(float(r["pnl_pct"]))
            cur *= (1 + float(r["pnl_pct"]) / 100)
            eq.append(cur)

    peak, dd = base, []
    for v in eq:
        peak = max(peak, v)
        dd.append((v - peak) / peak * 100 if peak else 0.0)
    max_dd = min(dd + [0.0])

    x = list(range(1, n + 1))
    width = max(11.0, min(20.0, 4.0 + 0.62 * n))
    fig, (axb, axd) = plt.subplots(
        2, 1, figsize=(width, 8.5), sharex=True,
        gridspec_kw={"height_ratios": [2.1, 1], "hspace": 0.10},
    )
    fig.patch.set_facecolor(BG)
    for a in (axb, axd):
        a.set_facecolor(BG)
        a.grid(color=GRID, lw=0.6)
        a.tick_params(colors=TXT, labelsize=11)
        for sp in a.spines.values():
            sp.set_color(GRID)

    line_col = GREEN if eq[-1] >= base else RED

    # ─── Yuqori panel: kumulyativ balans ───
    axb.plot(x, eq, color=line_col, lw=2.8, marker="o", markersize=6,
             markerfacecolor=BG, markeredgewidth=2, zorder=3)
    axb.fill_between(x, base, eq, color=line_col, alpha=0.13, zorder=2)
    axb.axhline(base, color="#5a6373", lw=1.2, ls="--", zorder=1)
    axb.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    axb.set_ylabel("Depozit balansi" if weighted else "Balans (boshlanish = 100)",
                   color=TXT, fontsize=12, labelpad=10)
    axb.margins(y=0.26)

    axb.annotate(f"boshlang'ich  {base:,.0f}", xy=(n, base),
                 xytext=(-4, 8), textcoords="offset points",
                 color=TXT, fontsize=11, ha="right", va="bottom")
    axb.annotate(f"{eq[-1]:,.0f}", xy=(n, eq[-1]),
                 xytext=(-6, 16), textcoords="offset points",
                 color=line_col, fontsize=15, fontweight="bold", ha="right")

    # Cho'qqi yozuvi faqat oxirgi nuqtadan yetarlicha uzoq bo'lsa — aks holda
    # yakuniy balans yozuvi bilan ustma-ust tushadi.
    pi = eq.index(max(eq))
    if n - 1 - pi >= 3:
        axb.annotate(f"cho'qqi {max(eq):,.0f}", xy=(pi + 1, eq[pi]),
                     xytext=(0, 13), textcoords="offset points",
                     color=TXT, fontsize=10, ha="center")

    # ─── Pastki panel: har savdo hissasi ───
    bars = axd.bar(x, deltas, color=[GREEN if d > 0 else RED for d in deltas],
                   alpha=0.75, width=0.62, zorder=2)
    span = (max(deltas) - min(deltas)) or 1.0
    if n <= 25:  # ko'p bo'lsa yozuvlar bir-biriga tegib ketadi
        for rect, d in zip(bars, deltas):
            axd.text(rect.get_x() + rect.get_width() / 2,
                     rect.get_height() + (span * 0.04 if d >= 0 else -span * 0.04),
                     f"{d:+,.0f}" if weighted else f"{d:+.1f}%",
                     ha="center", va="bottom" if d >= 0 else "top",
                     color=GREEN if d > 0 else RED, fontsize=10.5, fontweight="bold")
    axd.axhline(0, color="#5a6373", lw=1)
    axd.set_ylabel("Har savdo (pul)" if weighted else "Har savdo (%)",
                   color=TXT, fontsize=12, labelpad=10)
    axd.set_xlabel("Savdo tartibi (eskidan → yangiga)", color=TXT, fontsize=12, labelpad=8)
    axd.margins(y=0.26)
    if n <= 20:
        axd.set_xticks(x)
    else:
        axd.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=20))

    leg = axb.legend(handles=[
        Line2D([0], [0], color=line_col, lw=2.8, marker="o", markerfacecolor=BG,
               markeredgewidth=2, label="Kumulyativ balans"),
        Line2D([0], [0], color=GREEN, lw=9, alpha=0.75, label="Foydali savdo"),
        Line2D([0], [0], color=RED, lw=9, alpha=0.75, label="Zararli savdo"),
    ], loc="upper left", fontsize=10.5, facecolor=BG, edgecolor=GRID, framealpha=0.9)
    for t in leg.get_texts():
        t.set_color(TXT)

    change = eq[-1] - base
    change_pct = (eq[-1] / base - 1) * 100 if base else 0.0
    period = (f"{rows[0]['closed_at'].astimezone(TZ):%d %b} — "
              f"{rows[-1]['closed_at'].astimezone(TZ):%d %b %Y}")
    fig.suptitle("Equity — " + ("depozit balansi" if weighted else "balans")
                 + " va har savdo hissasi",
                 color=TITLE, fontsize=17, fontweight="bold", y=0.975)
    fig.text(0.5, 0.928,
             f"{n} signal   •   {period}   •   "
             + (f"{change:+,.0f}  ({change_pct:+.1f}%)" if weighted
                else f"{change_pct:+.1f}%")
             + f"   •   max DD {max_dd:.1f}%",
             ha="center", va="top", color=GREEN if change >= 0 else RED,
             fontsize=13, fontweight="bold")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


def month_bounds(year: int, month: int):
    a = datetime(year, month, 1, tzinfo=TZ)
    b = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=TZ)
    return a.astimezone(timezone.utc), b.astimezone(timezone.utc)


def year_bounds(year: int):
    a = datetime(year, 1, 1, tzinfo=TZ)
    b = datetime(year + 1, 1, 1, tzinfo=TZ)
    return a.astimezone(timezone.utc), b.astimezone(timezone.utc)
