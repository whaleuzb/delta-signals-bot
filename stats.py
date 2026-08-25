"""Statistika hisobotlari va equity curve."""
import io
import logging
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
import stocks
import tracker

TZ = ZoneInfo(config.TZ)
log = logging.getLogger("stats")

# Grafik ranglari (bot xabarlaridagi qorong'i mavzuga mos)
BG = "#101013"      # veb sahifadagi karta foni bilan bir oila
GRID = "#28282E"
TXT = "#9aa4b2"
TITLE = "#e6e9ef"
GREEN = "#26a69a"
RED = "#ef5350"


def _provider(market: str):
    """market bo'yicha narx manbai: forex/aksiya — Twelve Data, aks holda MEXC."""
    if market == "forex":
        return forex
    if market == "stock":
        return stocks
    return exchange


async def _safe_price(market: str, symbol: str):
    """Narx manbasi javob bermasa None qaytaradi, xato ko'tarmaydi.

    Muhim: YOPILGAN signallar statistikasi jonli narxga umuman bog'liq emas.
    Himoyasiz qoldirilsa, birjadagi bir soniyalik uzilish butun /stats yoki
    /symbols hisobotini yiqitardi — foydalanuvchi ma'lumotini bekorga
    yo'qotardi."""
    try:
        return await _provider(market).last_price(symbol)
    except Exception:
        log.warning("Narx olinmadi (%s %s)", market, symbol, exc_info=True)
        return None
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
            price = await _safe_price(r["market"], r["symbol"])
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
        # [:4] — [:3] bo'lsa "Iyun" va "Iyul" ikkalasi ham "Iyu" bo'lib qolardi.
        name = f"{MONTHS_UZ[m.month - 1][:4]} {m.year}"
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
            price = await _safe_price(pos["market"], sym)
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


def _equity_curve(rows, deposit):
    """equity_series() qatorlaridan balans egri chizig'ini hisoblaydi.
    equity_chart() va pdf_report() ikkalasi ham shu yerdan foydalanadi —
    hisob ikki joyda takrorlanib, keyin bir-biridan ajralib ketmasligi uchun.

    Qaytaradi: (weighted, base, eq, deltas)
      weighted — deposit berilganmi (ya'ni REAL pulda hisoblanganmi)
      base     — boshlang'ich balans, eq — har savdodan keyingi balans
      deltas   — har savdoning hissasi (weighted bo'lsa pulda, aks holda %)"""
    weighted = deposit is not None
    eq, deltas = [], []
    if weighted:
        deposit = float(deposit)
        deltas = [float(r["pnl_pct"]) / 100 * float(r["alloc_amount"])
                  if r["alloc_amount"] is not None else 0.0
                  for r in rows]
        # Boshlang'ich balans joriy depozitdan orqaga qarab topiladi.
        cur = base = deposit - sum(deltas)
        for d in deltas:
            cur += d
            eq.append(cur)
    else:
        cur = base = 100.0
        for r in rows:
            deltas.append(float(r["pnl_pct"]))
            cur *= (1 + float(r["pnl_pct"]) / 100)
            eq.append(cur)
    return weighted, base, eq, deltas


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
    weighted, base, eq, deltas = _equity_curve(rows, deposit)
    n = len(rows)

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


# ─────────────────────────── PDF hisobot ───────────────────────────
# Chop etish/ulashish uchun ataylab OQ fon: bot grafiklaridagi qorong'i mavzu
# hujjatda siyohni yeydi va bosmada yomon chiqadi.
P_TXT, P_MUTED, P_GRID = "#1a1a1a", "#666666", "#dddddd"
P_GREEN, P_RED = "#12805c", "#c0392b"


def _pdf_metrics(s, rows, deposit, show_money):
    """PDF ning 1-sahifasidagi ko'rsatkichlar: (yorliq, qiymat, rang) ro'yxati."""
    total = s["total"]
    wr = s["wins"] / total * 100 if total else 0.0
    out = [
        ("Signallar", f"{total}", P_TXT),
        ("Winrate", f"{wr:.1f}%", P_GREEN if wr >= 50 else P_RED),
        ("Foydali / Zararli", f"{s['wins']} / {s['losses']}", P_TXT),
    ]

    weighted = None
    if deposit:
        weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                    for r in rows
                    if r["pnl_pct"] is not None and r["alloc_amount"] is not None]
    if weighted:
        tot = sum(weighted)
        out.append(("Jami natija (depozitdan)", f"{tot:+.2f}%", P_GREEN if tot >= 0 else P_RED))
        comp = _compound(weighted)
        out.append(("Kompaund", f"{comp:+.2f}%", P_GREEN if comp >= 0 else P_RED))
        if show_money and s["real_pnl_money"] is not None:
            m = float(s["real_pnl_money"])
            out.append(("Real natija", f"{m:+,.2f}", P_GREEN if m >= 0 else P_RED))
    else:
        sp = float(s["sum_pct"])
        out.append(("Jami foiz (hajmsiz)", f"{sp:+.2f}%", P_GREEN if sp >= 0 else P_RED))
        pcts = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
        comp = _compound(pcts)
        out.append(("Kompaund", f"{comp:+.2f}%", P_GREEN if comp >= 0 else P_RED))

    out.append(("O'rtacha R", f"{float(s['avg_r']):+.2f}R", P_TXT))
    out.append(("O'rt. foyda / zarar",
                f"{float(s['avg_win']):+.2f}% / {float(s['avg_loss']):+.2f}%", P_TXT))
    if s["avg_loss"] and s["losses"]:
        gl = abs(float(s["avg_loss"])) * s["losses"]
        if gl:
            pf = float(s["avg_win"]) * s["wins"] / gl
            out.append(("Profit factor", f"{pf:.2f}", P_GREEN if pf >= 1 else P_RED))
    return out


async def pdf_report(workspace_id: int, ws_name: str, deposit=None,
                      show_money: bool = True) -> io.BytesIO | None:
    """Butun davr bo'yicha PDF hisobot: 1-sahifa — ko'rsatkichlar + balans
    egri chizig'i, 2-sahifa — juftliklar va oylar kesimi. Yopilgan signal
    bo'lmasa None qaytaradi."""
    from matplotlib.backends.backend_pdf import PdfPages

    s = await db.period_stats(workspace_id)
    if not s or s["total"] == 0:
        return None
    rows = await db.equity_series(workspace_id)
    syms = await db.top_symbols(workspace_id)
    months = await db.monthly_breakdown(workspace_id, 12)
    now = datetime.now(TZ)

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # ── 1-sahifa ──
        fig = plt.figure(figsize=(8.27, 11.69))  # A4
        fig.patch.set_facecolor("white")
        fig.text(0.06, 0.955, "Trade Controller", fontsize=20, fontweight="bold", color=P_TXT)
        fig.text(0.06, 0.932, ws_name, fontsize=13, color=P_MUTED)
        fig.text(0.94, 0.955, f"{now:%d.%m.%Y %H:%M}", fontsize=9, color=P_MUTED, ha="right")
        fig.add_artist(plt.Line2D([0.06, 0.94], [0.921, 0.921], color=P_GRID, lw=1))

        y = 0.885
        for label, value, color in _pdf_metrics(s, rows, deposit, show_money):
            fig.text(0.06, y, label, fontsize=11, color=P_MUTED)
            fig.text(0.94, y, value, fontsize=11, fontweight="bold", color=color, ha="right")
            y -= 0.030

        if len(rows) >= 2:
            weighted, base, eq, _ = _equity_curve(rows, deposit)
            ax = fig.add_axes([0.10, 0.06, 0.84, max(0.25, y - 0.11)])
            ax.set_facecolor("white")
            ax.grid(color=P_GRID, lw=0.6)
            ax.tick_params(colors=P_MUTED, labelsize=9)
            for sp_ in ax.spines.values():
                sp_.set_color(P_GRID)
            col = P_GREEN if eq[-1] >= base else P_RED
            x = range(1, len(eq) + 1)
            ax.plot(x, eq, color=col, lw=2)
            ax.fill_between(x, base, eq, color=col, alpha=0.12)
            ax.axhline(base, color=P_MUTED, lw=0.9, ls="--")
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
            ax.set_xlabel("Savdo tartibi", color=P_MUTED, fontsize=9)
            ax.set_ylabel("Balans" if weighted else "Balans (boshlanish = 100)",
                          color=P_MUTED, fontsize=9)
            ax.set_title("Balans o'zgarishi", color=P_TXT, fontsize=12,
                         fontweight="bold", pad=8)
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)

        # ── 2-sahifa: jadvallar ──
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.patch.set_facecolor("white")
        fig.text(0.06, 0.955, "Juftliklar kesimi", fontsize=16, fontweight="bold", color=P_TXT)
        hdr = f"{'Juftlik':<16}{'N':>6}{'WR':>9}{'Foiz':>13}"
        y = 0.925
        fig.text(0.06, y, hdr, fontsize=11, fontweight="bold",
                 color=P_MUTED, family="monospace")
        y -= 0.022
        for r in syms[:26]:
            wr = r["wins"] / r["closed"] * 100 if r["closed"] else 0
            sp_ = float(r["sum_pct"])
            fig.text(0.06, y,
                     f"{r['symbol'][:16]:<16}{r['closed']:>6}{wr:>8.0f}%{sp_:>+13.2f}",
                     fontsize=11, color=P_GREEN if sp_ >= 0 else P_RED, family="monospace")
            y -= 0.021
            if y < 0.34:
                break

        # Ro'yxat kalta bo'lsa darhol ostidan boshlanadi; uzun bo'lsa pastki
        # chegaraga tiraladi (avval doim 0.30 ga qadalib, katta bo'sh joy qolardi).
        y = min(y - 0.045, 0.86)
        fig.text(0.06, y, "Oylik natijalar", fontsize=16, fontweight="bold", color=P_TXT)
        y -= 0.034
        fig.text(0.06, y, f"{'Oy':<16}{'N':>6}{'WR':>9}{'Foiz':>13}",
                 fontsize=11, fontweight="bold", color=P_MUTED, family="monospace")
        y -= 0.022
        for r in months:
            m = r["month"]
            # To'liq oy nomi: 3 harfga qisqartirilsa "Iyun" va "Iyul" ikkalasi
            # ham "Iyu" bo'lib, qaysi oy ekani bilinmay qolardi.
            name = f"{MONTHS_UZ[m.month - 1]} {m.year}"
            wr = r["wins"] / r["total"] * 100 if r["total"] else 0
            sp_ = float(r["sum_pct"])
            fig.text(0.06, y, f"{name:<16}{r['total']:>6}{wr:>8.0f}%{sp_:>+13.2f}",
                     fontsize=11, color=P_GREEN if sp_ >= 0 else P_RED, family="monospace")
            y -= 0.021
            if y < 0.04:
                break
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)

    buf.seek(0)
    return buf


def pdf_table_report(title: str, subtitle: str, header: str,
                      lines: list[tuple[str, str]]) -> io.BytesIO:
    """Monospace jadvalli ko'p sahifali PDF (admin ro'yxatlari uchun).
    lines — (matn, rang) juftliklari; sahifa to'lganda avtomatik yangisi
    ochiladi, shuning uchun qatorlar soni cheklanmagan."""
    from matplotlib.backends.backend_pdf import PdfPages

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        i, page = 0, 1
        while True:
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.patch.set_facecolor("white")
            fig.text(0.06, 0.955, title, fontsize=18, fontweight="bold", color=P_TXT)
            if subtitle:
                fig.text(0.06, 0.932, subtitle, fontsize=11, color=P_MUTED)
            fig.text(0.94, 0.955, f"{datetime.now(TZ):%d.%m.%Y %H:%M}",
                     fontsize=9, color=P_MUTED, ha="right")
            fig.add_artist(plt.Line2D([0.06, 0.94], [0.921, 0.921], color=P_GRID, lw=1))

            y = 0.895
            fig.text(0.06, y, header, fontsize=10, fontweight="bold",
                     color=P_MUTED, family="monospace")
            y -= 0.023
            while i < len(lines) and y > 0.04:
                txt, col = lines[i]
                fig.text(0.06, y, txt, fontsize=10, color=col, family="monospace")
                y -= 0.020
                i += 1
            fig.text(0.94, 0.022, str(page), fontsize=9, color=P_MUTED, ha="right")
            pdf.savefig(fig, facecolor="white")
            plt.close(fig)
            if i >= len(lines):
                break
            page += 1
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
