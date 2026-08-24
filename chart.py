"""Signal grafiklari — narx shamlari ustiga entry/TP/SL darajalari.

Ikki holatda ishlatiladi:
  1. `setup_chart()` — signal E'LON QILINAYOTGANDA. Foydalanuvchi o'z rasmini
     yubormasa (yoki yubormoqchi bo'lmasa) bot oxirgi shamlarni o'zi olib,
     rejalashtirilgan darajalarni chizib beradi.
  2. `signal_chart()` — signal YOPILGANDA. O'sha savdoning haqiqiy yo'li:
     kirishdan chiqishgacha bo'lgan shamlar va aniq chiqish nuqtasi.

Ikkalasi ham bitta `_render()` dan foydalanadi — guruhdagi rasmlar bir xil
uslubda ko'rinsin uchun. Bu reklama banneri emas: raqamlar haqiqiy bozor
ma'lumotidan olinadi.
"""
import io
import logging
from datetime import datetime, timezone

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

# Tanlanadigan timeframe'lar va ularning daqiqadagi uzunligi.
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
TF_LABELS = {"1m": "1 daqiqa", "5m": "5 daqiqa", "15m": "15 daqiqa",
             "30m": "30 daqiqa", "1h": "1 soat", "4h": "4 soat", "1d": "1 kun"}
DEFAULT_TF = "15m"     # tf berilmagan (eski) signallar uchun

SETUP_BARS = 120       # yangi signal grafigida ko'rsatiladigan sham soni
PAD_BARS = 8           # yopilgan signalda kirish/chiqish atrofidagi zaxira shamlar
MIN_BARS = 40          # natija grafigi juda "yalang'och" bo'lib qolmasligi uchun
MAX_CANDLES = 1000     # bitta klines chaqiruvidagi eng ko'p sham


def norm_tf(tf: str | None) -> str:
    return tf if tf in TF_MINUTES else DEFAULT_TF


async def _fetch(market: str, symbol: str, start_ms: int, limit: int, tf: str):
    """Shamlarni olish. Xato bo'lsa None — grafik shunchaki chizilmaydi va
    chaqiruvchi oddiy matn/rasm yo'liga qaytadi."""
    try:
        return await tracker.provider(market).klines(symbol, start_ms, limit=limit, tf=tf)
    except Exception:
        log.warning("Grafik uchun shamlar olinmadi (%s %s %s)", market, symbol, tf,
                    exc_info=True)
        return None


def _fmt(p: float) -> str:
    if p >= 100:
        return f"{p:,.0f}"
    if p >= 1:
        return f"{p:,.4g}"
    return f"{p:.6g}"


def _render(candles, *, header: str, side: str, entry: float, sl: float,
            tps: list[float], tp_hit: int, exit_idx: int | None,
            exit_price: float | None, pnl, r, ws_name: str,
            bot_username: str | None, tf: str, note: str | None) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    levels = [entry, sl, *tps]
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
        # Yorliq grafik ICHIDA, o'ng chekkada. Avval u tashqarida turardi va
        # o'zi uchun kengligning ~15% ini yeb, shamlarni chapga siqib qo'yardi.
        # Yarim shaffof fon ostida u chiziq ustida ham bemalol o'qiladi.
        ax.text(len(candles) - 1.5, y, label, color=color, fontsize=9,
                fontweight="bold", va="center", ha="right", zorder=6,
                bbox=dict(facecolor=BG, edgecolor="none", alpha=0.72, pad=1.6))

    hline(entry, ACC, f"Entry {_fmt(entry)}")
    hline(sl, RED, f"SL {_fmt(sl)}", alpha=0.85)
    for n, tp in enumerate(tps, start=1):
        hit = n <= tp_hit
        hline(tp, GREEN, f"TP{n} {_fmt(tp)}", alpha=1.0 if hit else 0.4,
              ls="--" if hit else ":")

    if exit_idx is not None and exit_price is not None:
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
    fig.text(0.045, 0.955, header, fontsize=16, fontweight="bold", color=TITLE)
    fig.text(0.045, 0.925, side, fontsize=11, fontweight="bold", color=side_col)
    # Timeframe — grafik qaysi masshtabda chizilganini aniq bildiradi.
    # Siljish yozuv uzunligiga bog'liq, aks holda SHORT bilan ustma-ust tushardi.
    fig.text(0.045 + 0.0135 * len(side) + 0.012, 0.925, f"· {tf}",
              fontsize=11, color=TXT)
    if pnl is not None:
        fig.text(0.97, 0.955, f"{pnl:+.2f}%", fontsize=17, fontweight="bold",
                  color=GREEN if pnl >= 0 else RED, ha="right")
        if r is not None:
            fig.text(0.97, 0.925, f"{float(r):+.2f}R", fontsize=10.5, color=TXT, ha="right")
    elif note:
        fig.text(0.97, 0.945, note, fontsize=11, color=TXT, ha="right")

    fig.text(0.045, 0.02, ws_name, fontsize=9.5, color=SILVER)
    if bot_username:
        fig.text(0.97, 0.02, f"t.me/{bot_username}", fontsize=9.5, color=SILVER, ha="right")

    # right=0.985 — yorliqlar endi ichkarida, tashqarida joy zaxiralash shart emas.
    fig.subplots_adjust(left=0.062, right=0.985, top=0.88, bottom=0.08)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf


async def setup_chart(draft: dict, ws_name: str, bot_username: str | None,
                       tf: str | None = None) -> io.BytesIO | None:
    """Yangi e'lon qilinayotgan signal uchun grafik: oxirgi shamlar va
    rejalashtirilgan Entry/TP/SL darajalari. Hali hech narsa bo'lmagani uchun
    chiqish nuqtasi ham, PnL ham yo'q.

    Bitta `klines` chaqiruvi qilinadi — forex tomonida Twelve Data bepul rejasi
    daqiqasiga 8 so'rovga cheklangani uchun bu ataylab bitta so'rov bilan
    chegaralangan (signal e'lon qilish kamdan-kam sodir bo'ladi, shu sabab
    kuzatuv siklini siqib qo'ymaydi)."""
    tf = norm_tf(tf)
    market = draft.get("market", "crypto")
    symbol = draft["symbol"]
    span_ms = SETUP_BARS * TF_MINUTES[tf] * 60_000
    start_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - span_ms
    candles = await _fetch(market, symbol, start_ms, min(MAX_CANDLES, SETUP_BARS + 5), tf)
    if not candles or len(candles) < 3:
        return None

    # Sarlavhada signal raqami yo'q: grafik signal BAZAGA YOZILISHIDAN OLDIN,
    # ko'rish uchun chiziladi — raqam hali mavjud emas. Raqam xabar matnida
    # (draft_text) baribir ko'rinadi.
    mode = draft.get("entry_mode", "limit")
    return _render(
        candles, header=symbol, side=draft["side"],
        entry=float(draft["entry"]), sl=float(draft["sl"]),
        tps=[float(x) for x in draft["tps"]], tp_hit=0,
        exit_idx=None, exit_price=None, pnl=None, r=None,
        ws_name=ws_name, bot_username=bot_username, tf=tf,
        note="ochildi" if mode == "market" else "kutilmoqda",
    )


async def signal_chart(sig, ws_name: str, bot_username: str | None) -> io.BytesIO | None:
    """Yopilgan signal uchun grafik: kirishdan chiqishgacha bo'lgan haqiqiy
    shamlar, darajalar va aniq chiqish nuqtasi. Shamlar topilmasa None —
    chaqiruvchi oddiy matn xabariga qaytadi, hech narsa buzilmaydi."""
    opened_at = sig["opened_at"]
    closed_at = sig["closed_at"]
    if not opened_at or not closed_at:
        return None

    # Signal qaysi timeframe'da e'lon qilingan bo'lsa, natija ham shunda.
    tf = norm_tf(sig["chart_tf"] if "chart_tf" in sig.keys() else None)
    tf_ms = TF_MINUTES[tf] * 60_000

    span_bars = max(1, int((closed_at - opened_at).total_seconds() * 1000 // tf_ms))
    # Savdo tanlangan timeframe'da bir necha shamgina davom etgan bo'lsa
    # (masalan 4h grafikda 40 daqiqalik savdo) grafik bo'm-bo'sh ko'rinardi —
    # shuning uchun oynani orqaga cho'zib, kamida MIN_BARS sham beramiz.
    pad_bars = max(PAD_BARS, (MIN_BARS - span_bars) // 2)
    limit = min(MAX_CANDLES, span_bars + 2 * pad_bars + 5)
    start_ms = int(opened_at.timestamp() * 1000) - pad_bars * tf_ms

    candles = await _fetch(sig["market"], sig["symbol"], start_ms, limit, tf)
    if not candles:
        return None

    end_ms = int(closed_at.timestamp() * 1000) + pad_bars * tf_ms
    candles = [c for c in candles if c.open_ms <= end_ms]
    if len(candles) < 3:
        return None

    exit_price = float(sig["exit_price"]) if sig["exit_price"] is not None else None
    exit_idx = None
    if exit_price is not None:
        closed_ms = int(closed_at.timestamp() * 1000)
        exit_idx = min(range(len(candles)), key=lambda i: abs(candles[i].close_ms - closed_ms))

    return _render(
        candles, header=f"#{sig['id']} {sig['symbol']}", side=sig["side"],
        entry=float(sig["entry"]), sl=float(sig["sl_initial"]),
        tps=[float(x) for x in sig["tps"]], tp_hit=sig["tp_hit"],
        exit_idx=exit_idx, exit_price=exit_price,
        pnl=sig["pnl_pct"], r=sig["r_multiple"],
        ws_name=ws_name, bot_username=bot_username, tf=tf, note=None,
    )
