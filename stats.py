"""Statistika hisobotlari va equity curve."""
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import config
import db

TZ = ZoneInfo(config.TZ)
MONTHS_UZ = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]


def _compound(pcts: list[float]) -> float:
    """Har savdoda bir xil ulush ishlatilsa — kompaund natija."""
    eq = 1.0
    for p in pcts:
        eq *= (1 + p / 100)
    return (eq - 1) * 100


async def summary(since=None, until=None, title="Umumiy statistika") -> str:
    s = await db.period_stats(since, until)
    if not s or s["total"] == 0:
        return f"<b>{title}</b>\n\nHali yopilgan signal yo'q."

    total = s["total"]
    wr = s["wins"] / total * 100
    pf = None
    if s["avg_loss"] and s["losses"]:
        gross_win = float(s["avg_win"]) * s["wins"]
        gross_loss = abs(float(s["avg_loss"])) * s["losses"]
        pf = gross_win / gross_loss if gross_loss else None

    rows = await db.equity_series()
    pcts = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]

    t = [f"<b>{title}</b>", ""]
    t.append(f"Signallar: <b>{total}</b>  ({s['wins']}✅ / {s['losses']}❌ / {s['be']}⚪)")
    t.append(f"Winrate: <b>{wr:.1f}%</b>")
    t.append(f"Jami foiz: <b>{float(s['sum_pct']):+.2f}%</b>")
    t.append(f"Kompaund: <b>{_compound(pcts):+.2f}%</b>")
    t.append(f"O'rtacha R: <b>{float(s['avg_r']):+.2f}R</b>   |   Jami: <b>{float(s['sum_r']):+.1f}R</b>")
    t.append(f"O'rt. foyda: {float(s['avg_win']):+.2f}%   |   O'rt. zarar: {float(s['avg_loss']):+.2f}%")
    if pf:
        t.append(f"Profit factor: <b>{pf:.2f}</b>")
    return "\n".join(t)


async def monthly_table(limit: int = 12) -> str:
    rows = await db.monthly_breakdown(limit)
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


async def symbols_table(limit: int = 8) -> str:
    rows = await db.top_symbols(limit)
    if not rows:
        return "Ma'lumot yo'q."
    t = ["<b>Juftliklar bo'yicha</b>", "<pre>"]
    t.append(f"{'Juftlik':<12}{'N':>4}{'WR':>7}{'Foiz':>9}")
    for r in rows:
        wr = r["wins"] / r["total"] * 100 if r["total"] else 0
        t.append(f"{r['symbol']:<12}{r['total']:>4}{wr:>6.0f}%{float(r['sum_pct']):>+9.2f}")
    t.append("</pre>")
    return "\n".join(t)


async def equity_chart() -> io.BytesIO | None:
    rows = await db.equity_series()
    if len(rows) < 2:
        return None

    dates, eq = [], []
    cur = 100.0
    for r in rows:
        cur *= (1 + float(r["pnl_pct"]) / 100)
        dates.append(r["closed_at"].astimezone(TZ))
        eq.append(cur)

    peak, dd = eq[0], []
    for v in eq:
        peak = max(peak, v)
        dd.append((v - peak) / peak * 100)
    max_dd = min(dd)

    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(10, 6.5), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )
    fig.patch.set_facecolor("#0e1117")
    for a in (ax, ax2):
        a.set_facecolor("#0e1117")
        a.grid(color="#2a2f3a", lw=0.6)
        a.tick_params(colors="#9aa4b2", labelsize=9)
        for sp in a.spines.values():
            sp.set_color("#2a2f3a")

    up = eq[-1] >= 100
    col = "#26a69a" if up else "#ef5350"
    ax.plot(dates, eq, color=col, lw=2)
    ax.fill_between(dates, 100, eq, color=col, alpha=0.15)
    ax.axhline(100, color="#5a6373", lw=0.8, ls="--")
    ax.set_ylabel("Balans (boshlanish = 100)", color="#9aa4b2", fontsize=9)
    ax.set_title(
        f"Equity curve  •  {len(eq)} signal  •  {eq[-1] - 100:+.1f}%  •  max DD {max_dd:.1f}%",
        color="#e6e9ef", fontsize=12, pad=12,
    )

    ax2.fill_between(dates, dd, 0, color="#ef5350", alpha=0.4)
    ax2.set_ylabel("Drawdown %", color="#9aa4b2", fontsize=9)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))

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
