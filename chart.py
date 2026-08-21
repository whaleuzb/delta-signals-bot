"""Yopilgan signal uchun narx grafigi.

Har bir TP/SL yopilishida guruhga matn bilan birga real shamlar grafigi
yuboriladi: entry/TP/SL chiziqlari va aniq chiqish nuqtasi bilan — bu
reklama banneri emas, signalning haqiqiy natijasini ko'rsatadigan dalil.
Rasm chetiga workspace nomi va bot havolasi qo'yiladi, chunki bunday
rasmlar ko'pincha guruhdan tashqarida ham qayta ulashiladi.
"""
import io
import logging

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import tracker

log = logging.getLogger("chart")

BG = "#0e1117"
GRID = "#2a2f3a"
TXT = "#9aa4b2"
TITLE = "#e6e9ef"
GREEN = "#26a69a"
RED = "#ef5350"
ACC = "#4da3ff"
SILVER = "#8a8f99"

PAD_MIN = 10          # opened_at/closed_at atrofida necha daqiqalik shamcha qo'shiladi
MAX_CANDLES = 1200    # bitta so'rovda so'raladigan eng ko'p shamlar soni


async def signal_chart(sig, ws_name: str, bot_username: str | None) -> io.BytesIO | None:
    """sig — db.get_signal() natijasi (yopilgan holatda). Shamlar topilmasa yoki
    ular yetarli bo'lmasa None qaytaradi — chaqiruvchi shu holda oddiy matn
    xabariga qaytadi, hech narsa buzilmaydi."""
    opened_at = sig["opened_at"]
    closed_at = sig["closed_at"]
    if not opened_at or not closed_at:
        return None

    span_min = max(1, int((closed_at - opened_at).total_seconds() // 60))
    limit = min(MAX_CANDLES, span_min + 2 * PAD_MIN + 5)
    start_ms = int(opened_at.timestamp() * 1000) - PAD_MIN * 60_000

    try:
        candles = await tracker.provider(sig["market"]).klines(sig["symbol"], start_ms, limit=limit)
    except Exception:
        log.warning("Grafik uchun shamlar olinmadi (#%s %s)", sig["id"], sig["symbol"], exc_info=True)
        return None

    end_ms = int(closed_at.timestamp() * 1000) + PAD_MIN * 60_000
    candles = [c for c in candles if c.open_ms <= end_ms]
    if len(candles) < 3:
        return None

    entry = float(sig["entry"])
    sl_initial = float(sig["sl_initial"])
    tps = [float(x) for x in sig["tps"]]
    tp_hit = sig["tp_hit"]
    exit_price = float(sig["exit_price"]) if sig["exit_price"] is not None else None
    side = sig["side"]
    pnl = sig["pnl_pct"]

    exit_idx = min(
        range(len(candles)),
        key=lambda i: abs(candles[i].close_ms - int(closed_at.timestamp() * 1000)),
    )

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    levels = [entry, sl_initial, *tps]
    if exit_price is not None:
        levels.append(exit_price)
    lo = min(lo, *levels)
    hi = max(hi, *levels)
    pad = (hi - lo) * 0.08 or hi * 0.01
    lo -= pad
    hi += pad

    width = 0.62
    for i, c in enumerate(candles):
        up = c.close >= c.open
        col = GREEN if up else RED
        ax.plot([i, i], [c.low, c.high], color=col, lw=0.9, zorder=2, solid_capstyle="round")
        body_lo, body_hi = (c.open, c.close) if up else (c.close, c.open)
        h = max(body_hi - body_lo, (hi - lo) * 0.0015)
        ax.add_patch(Rectangle((i - width / 2, body_lo), width, h, facecolor=col,
                                edgecolor=col, lw=0, zorder=3))

    def hline(y, color, label, ls="--", lw=1.3, alpha=1.0):
        ax.axhline(y, color=color, lw=lw, ls=ls, alpha=alpha, zorder=1)
        ax.text(len(candles) - 0.5, y, f"  {label}", color=color, fontsize=9.5,
                fontweight="bold", va="center", ha="left", clip_on=False)

    hline(entry, ACC, f"Entry {_fmt(entry)}")
    hline(sl_initial, RED, f"SL {_fmt(sl_initial)}", alpha=0.85)
    for n, tp in enumerate(tps, start=1):
        hit = n <= tp_hit
        hline(tp, GREEN, f"TP{n} {_fmt(tp)}", alpha=1.0 if hit else 0.4,
              ls="--" if hit else ":")

    if exit_price is not None:
        exit_col = GREEN if (pnl or 0) >= 0 else RED
        ax.scatter([exit_idx], [exit_price], color=exit_col, s=70, zorder=5,
                   edgecolor=BG, linewidth=1.5)
        pnl_txt = f"{pnl:+.2f}%" if pnl is not None else ""
        ax.annotate(
            f"  Chiqish {_fmt(exit_price)}  ({pnl_txt})", xy=(exit_idx, exit_price),
            xytext=(0, -22 if side == "LONG" else 18), textcoords="offset points",
            color=exit_col, fontsize=10, fontweight="bold", ha="center",
        )

    ax.set_xlim(-1.5, len(candles) - 0.5)
    ax.set_ylim(lo, hi)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.6)
    ax.set_xticks([])
    ax.tick_params(colors=TXT, labelsize=9.5)
    for spine in ax.spines.values():
        spine.set_color(GRID)

    side_col = GREEN if side == "LONG" else RED
    fig.text(0.045, 0.955, f"#{sig['id']} {sig['symbol']}", fontsize=16,
              fontweight="bold", color=TITLE)
    fig.text(0.045, 0.925, side, fontsize=11, fontweight="bold", color=side_col)
    if pnl is not None:
        fig.text(0.97, 0.955, f"{pnl:+.2f}%", fontsize=17, fontweight="bold",
                  color=GREEN if pnl >= 0 else RED, ha="right")
        if sig["r_multiple"] is not None:
            fig.text(0.97, 0.925, f"{float(sig['r_multiple']):+.2f}R", fontsize=10.5,
                      color=TXT, ha="right")

    fig.text(0.045, 0.02, ws_name, fontsize=9.5, color=SILVER)
    if bot_username:
        fig.text(0.97, 0.02, f"t.me/{bot_username}", fontsize=9.5, color=SILVER, ha="right")

    fig.subplots_adjust(left=0.06, right=0.86, top=0.88, bottom=0.08)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf


def _fmt(p: float) -> str:
    if p >= 100:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.4g}"
    return f"{p:.6g}"
