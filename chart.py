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

BG = "#101013"      # Whale uslubi: sahifa foni bilan bir xil oila
GRID = "#28282E"
# Kichik grafik KARTA ichida turadi — foni karta rangida bo'lsa, rasm
# chegarasi ko'rinmaydi va grafik kartaning bir qismidek o'qiladi.
CARD_BG = "#17171B"
TXT = "#9aa4b2"
TITLE = "#e6e9ef"
GREEN = "#26a69a"
RED = "#ef5350"
ACC = "#DADDE2"     # kumush — kirish darajasi chizig'i
SILVER = "#8a8f99"
VP_COLOR = "#d4a636"    # kumush emas, mo''jaz oltin — hajm profili shamlardan ajralib turishi uchun

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


def align(start_ms: int, tf: str) -> int:
    """`startTime` ni sham chegarasiga tushiradi.

    MEXC chegaraga tushmagan `startTime` ga 200 OK bilan BO'SH ro'yxat
    qaytaradi — grafik esa jimgina chizilmay qolardi. Kuzatuv (tracker) bu
    muammoga duch kelmaydi, chunki uning vaqti sham ochilish vaqtidan olinadi
    va allaqachon chegarada; grafikda esa `opened_at` — ixtiyoriy soniya."""
    step = TF_MINUTES[tf] * 60_000
    return start_ms - (start_ms % step)


async def _fetch(market: str, symbol: str, start_ms: int, limit: int, tf: str,
                 end_ms: int | None = None):
    """Shamlarni olish. Xato bo'lsa None — grafik shunchaki chizilmaydi va
    chaqiruvchi oddiy matn/rasm yo'liga qaytadi.

    end_ms O'TMISHDAGI oyna uchun SHART: MEXC faqat startTime berilganda
    oraliqning oxiridan `limit` ta sham qaytaradi va so'ralgan oyna emas,
    eng so'nggi shamlar kelib qoladi."""
    try:
        return await tracker.provider(market).klines(symbol, start_ms, limit=limit,
                                                     tf=tf, end_ms=end_ms)
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


def _draw_candles(ax, candles, hi: float, lo: float) -> None:
    """Shamlarni chizadi (fitil + tana). `_render()` va `news_chart()`
    ikkalasida ham ishlatiladi — vizual uslub bir xil bo'lishi uchun."""
    width = 0.62
    for i, c in enumerate(candles):
        up = c.close >= c.open
        col = GREEN if up else RED
        ax.plot([i, i], [c.low, c.high], color=col, lw=0.9, zorder=2, solid_capstyle="round")
        body_lo, body_hi = (c.open, c.close) if up else (c.close, c.open)
        h = max(body_hi - body_lo, (hi - lo) * 0.0015)
        ax.add_patch(Rectangle((i - width / 2, body_lo), width, h, facecolor=col,
                                edgecolor=col, lw=0, zorder=3))


def _draw_volume_profile(ax, candles, lo: float, hi: float,
                         vp_left: float, vp_right: float) -> None:
    """Hajm profili — GRAFIKDA KO'RINAYOTGAN BARCHA shamlarning (anchor
    nuqtadan oldingilari HAM, keyingilari HAM) narx darajalari bo'yicha
    hajm taqsimoti, savdo platformalaridagi kabi o'ng chekkaga tirab,
    ichkariga qarab o'sadigan gorizontal ustunlar bilan. `_render()`/
    `news_chart()` ikkalasida ham ishlatiladi — grafik doim shu chapqirog'da
    (o'ng chetda) ko'rinsin uchun ATAYLAB alohida, mustaqil "zona"
    (candle'lardan keyingi bo'sh joydan SO'NG), ular bilan aralashib
    ketmasligi uchun.

    ESLATMA: dastlab FAQAT anchor (News/Portlash/Entry) nuqtasidan buyon
    bo'lgan hajm hisoblangan edi ("Anchored" VP semantikasi) — lekin
    yangi post qilingan yangilikda anchordan keyin hali 1-2 ta sham
    bo'lgani uchun profil deyarli bo'sh/yupqa chiqardi. Foydalanuvchi
    buni ko'rib "avvalgi charti volumesini ham olish kerak" dedi —
    shuning uchun endi BUTUN ko'rinadigan oyna hisobga olinadi.

    Hajm ma'lumoti yo'q bo'lsa (masalan forex — markazlashtirilmagan bozor,
    Twelve Data ko'pincha 0/yo'q qaytaradi) HECH NARSA chizilmaydi — bo'sh
    zona qoldirish, "hajm 0" degan yolg'on taassurot berishdan yaxshiroq."""
    if not candles:
        return
    total_vol = sum(c.volume for c in candles)
    if total_vol <= 0:
        return
    n_bins = 60
    bin_size = (hi - lo) / n_bins or 1.0
    bins = [0.0] * n_bins
    for c in candles:
        idx = int((c.close - lo) / bin_size)
        idx = max(0, min(n_bins - 1, idx))
        bins[idx] += c.volume
    peak = max(bins) or 1.0
    width_span = vp_right - vp_left
    for i, v in enumerate(bins):
        if v <= 0:
            continue
        frac = v / peak
        y0 = lo + i * bin_size
        w = frac * width_span
        # Alpha ham hajmga qarab o'zgaradi — ko'p savdo qilingan narxlar
        # (nodalar) yorqinroq, kamlari xiraroq ko'rinadi (gradient taassurot).
        ax.barh(y0 + bin_size / 2, w, height=bin_size * 0.96, left=vp_right - w,
                color=VP_COLOR, alpha=0.22 + 0.5 * frac, zorder=0.5,
                edgecolor="none")


def _render(candles, *, header: str, side: str, entry: float, sl: float,
            tps: list[float], tp_hit: int, exit_idx: int | None,
            exit_price: float | None, pnl, r, ws_name: str,
            bot_username: str | None, tf: str, note: str | None,
            entry_idx: int | None = None) -> io.BytesIO:
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

    _draw_candles(ax, candles, hi, lo)

    # Oxirgi shamdan keyin bo'sh joy — savdo platformalaridagi kabi ("right
    # offset"), YIRIKROQ qilingan (0.10 -> 0.45): joriy sham ramka
    # markaziga yaqinroq chiqishi, yorliqlar esa shamlar bilan ustma-ust
    # tushmasligi uchun (foydalanuvchi: "yozuvlar chartga aralashib
    # ketyabti", "hozirgi shamni ramka markaziga chiqarish kerak"). Undan
    # KEYIN — alohida, doimiy ko'rinadigan hajm profili zonasi.
    right_pad = max(10.0, len(candles) * 0.45)
    vp_width = max(10.0, len(candles) * 0.22)
    gap_end = len(candles) - 1 + right_pad
    x_max = gap_end + vp_width
    _draw_volume_profile(ax, candles, lo, hi, vp_left=gap_end, vp_right=x_max)

    # Yorliqlar QISQA — so'z o'rniga belgi (Entry ●, SL ✕, TP ▲{n}) —
    # "Entry 0.00157" o'rniga "● 0.00157" kabi (foydalanuvchi so'zlarni
    # ikonkaga almashtirishga rozi bo'ldi).
    def hline(y, color, label, ls="--", lw=1.3, alpha=1.0):
        ax.axhline(y, color=color, lw=lw, ls=ls, alpha=alpha, zorder=1)
        ax.text(gap_end - right_pad * 0.06, y, label, color=color, fontsize=8.5,
                fontweight="bold", va="center", ha="right", zorder=6,
                bbox=dict(facecolor=BG, edgecolor="none", alpha=0.72, pad=1.4))

    # Kirish: agar ANIQ qaysi shamda ochilgani ma'lum bo'lsa (yopilgan
    # savdo) — "pozitsiya izi" uslubida, o'sha shamning O'ZIGA yo'nalish
    # ko'rsatkichi (uchburchak) qo'yiladi, butun kenglikdagi chiziq/yorliq
    # YO'Q (TradingView referensidagi kabi — kirish/chiqish nuqtalari
    # to'g'ridan-to'g'ri shamlar ustida). Hali OCHILMAGAN (setup) signalda
    # kirish shami yo'q — o'sha holda avvalgidek butun kenglikdagi chiziq.
    if entry_idx is not None:
        entry_marker = "^" if side == "LONG" else "v"
        ax.scatter([entry_idx], [entry], marker=entry_marker, color=ACC, s=85,
                   zorder=5, edgecolor=BG, linewidth=1.3)
    else:
        hline(entry, ACC, f"● {_fmt(entry)}")
    hline(sl, RED, f"✕ {_fmt(sl)}", alpha=0.85)
    for n, tp in enumerate(tps, start=1):
        hit = n <= tp_hit
        hline(tp, GREEN, f"▲{n} {_fmt(tp)}", alpha=1.0 if hit else 0.4,
              ls="--" if hit else ":")

    if exit_idx is not None and exit_price is not None:
        exit_col = GREEN if (pnl or 0) >= 0 else RED
        exit_marker = "v" if side == "LONG" else "^"
        ax.scatter([exit_idx], [exit_price], marker=exit_marker, color=exit_col,
                   s=85, zorder=5, edgecolor=BG, linewidth=1.3)
        pnl_txt = f"{pnl:+.2f}%" if pnl is not None else ""
        ax.annotate(
            f"  {_fmt(exit_price)}  ({pnl_txt})", xy=(exit_idx, exit_price),
            xytext=(0, -22 if side == "LONG" else 18), textcoords="offset points",
            color=exit_col, fontsize=10, fontweight="bold", ha="center",
        )

    ax.set_xlim(-1.5, x_max)
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
    start_ms = align(int(datetime.now(timezone.utc).timestamp() * 1000) - span_ms, tf)
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


def _synthetic_line(entry: float, exit_price: float, n: int = 20) -> list[float]:
    """Haqiqiy sham topilmagan signal uchun kirish->chiqish oddiy chizig'i
    (masalan MEXC'da yo'q eski sinov tikeri, yoki birja vaqtincha
    javob bermadi). Tebranish qo'shilmaydi — bu haqiqiy narx harakati emas,
    shunday ko'rsatish yolg'on migqiqlikni haqiqiyga o'xshatib qo'yardi."""
    if n < 2:
        return [entry, exit_price]
    return [entry + (exit_price - entry) * i / (n - 1) for i in range(n)]


async def mini_chart(sig) -> io.BytesIO | None:
    """Yopilgan savdoning KICHIK grafigi (veb sahifadagi ro'yxat uchun).

    Ataylab soddalashtirilgan: o'q ham, yozuv ham yo'q — faqat narx chizig'i,
    kirish darajasi va chiqish nuqtasi. Bu o'lchamda shamlar o'qilmaydi,
    chiziq esa savdoning shaklini bir qarashda ko'rsatadi.

    Rasm 320x110 — to'liq grafikdan ~5 barobar yengil, chunki bitta sahifada
    o'nlab shunday rasm bo'ladi."""
    opened_at, closed_at = sig["opened_at"], sig["closed_at"]
    if not opened_at or not closed_at:
        return None

    entry = float(sig["entry"])
    exit_price = float(sig["exit_price"]) if sig["exit_price"] is not None else None
    pnl = float(sig["pnl_pct"]) if sig["pnl_pct"] is not None else 0.0
    col = GREEN if pnl >= 0 else RED

    tf = norm_tf(sig["chart_tf"] if "chart_tf" in sig.keys() else None)
    tf_ms = TF_MINUTES[tf] * 60_000
    span_bars = max(1, int((closed_at - opened_at).total_seconds() * 1000 // tf_ms))
    pad_bars = max(3, (30 - span_bars) // 2)
    start_ms = align(int(opened_at.timestamp() * 1000) - pad_bars * tf_ms, tf)
    end_ms = int(closed_at.timestamp() * 1000) + pad_bars * tf_ms
    limit = min(MAX_CANDLES, span_bars + 2 * pad_bars + 5)

    candles = await _fetch(sig["market"], sig["symbol"], start_ms, limit, tf,
                           end_ms=end_ms)
    if candles:
        n_raw = len(candles)
        candles = [c for c in candles if c.open_ms <= end_ms]
        if len(candles) < 3:
            log.info("Kichik grafik: #%s %s — %s shamdan %s tasi oraliqqa tushdi",
                     sig["id"], sig["symbol"], n_raw, len(candles))
            candles = None

    if candles:
        closes = [c.close for c in candles]
        # Kirish chizig'i FAQAT shamlar diapazoniga tushsa chiziladi. Eski
        # sinov signallarida narxlar qo'lda o'ylab yozilgan ("kirish 100"),
        # shamlar esa haqiqiy bozordan keladi — bunday kirish miqyosni
        # o'ziga tortib, haqiqiy narx harakatini tep-tekis chiziqqa
        # aylantirardi. Grafikning o'zi baribir chiziladi.
        c_lo, c_hi = min(closes), max(closes)
        show_entry = c_lo * 0.9 <= entry <= c_hi * 1.1
        exit_idx = None
        if exit_price is not None:
            closed_ms = int(closed_at.timestamp() * 1000)
            exit_idx = min(range(len(candles)),
                           key=lambda i: abs(candles[i].close_ms - closed_ms))
    else:
        # Birjada bu tiker yo'q (eski sinov signali) yoki narx vaqtincha
        # olinmadi — ro'yxatda bo'sh joy qoldirish o'rniga kirish->chiqish
        # narxidan sun'iy chiziq chizamiz. Kirish/chiqish matn ostida
        # baribir ko'rsatiladi, shuning uchun bu hech narsani yashirmaydi.
        log.info("Kichik grafik: #%s %s uchun sham topilmadi — sun'iy chiziq",
                 sig["id"], sig["symbol"])
        if exit_price is None:
            return None
        closes = _synthetic_line(entry, exit_price)
        show_entry = False
        exit_idx = len(closes) - 1

    xs = list(range(len(closes)))
    fig, ax = plt.subplots(figsize=(3.2, 1.1), dpi=100)
    fig.patch.set_facecolor(CARD_BG)
    ax.set_facecolor(CARD_BG)

    ax.plot(xs, closes, color=col, lw=1.6, zorder=3)
    ax.fill_between(xs, closes, min(closes), color=col, alpha=0.13, zorder=2)
    if show_entry:
        ax.axhline(entry, color=ACC, lw=1.0, ls="--", alpha=0.75, zorder=1)
    if exit_idx is not None:
        ax.scatter([exit_idx], [closes[exit_idx]], color=col, s=26, zorder=4,
                   edgecolor=CARD_BG, linewidth=1.2)

    # Miqyos: kirish chizig'i ko'rsatilsagina u ham hisobga olinadi. Aks
    # holda (mos kelmaydigan eski narx) u butun kadrni o'ziga tortib,
    # haqiqiy narx harakati tekis chiziqqa aylanib qolardi.
    c_lo, c_hi = min(closes), max(closes)
    lo, hi = (min(c_lo, entry), max(c_hi, entry)) if show_entry else (c_lo, c_hi)
    pad = (hi - lo) * 0.12 or hi * 0.005
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-0.5, len(closes) - 0.5)
    ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.97, bottom=0.03)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=CARD_BG)
    plt.close(fig)
    buf.seek(0)
    return buf


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
    start_ms = align(int(opened_at.timestamp() * 1000) - pad_bars * tf_ms, tf)
    end_ms = int(closed_at.timestamp() * 1000) + pad_bars * tf_ms

    candles = await _fetch(sig["market"], sig["symbol"], start_ms, limit, tf,
                           end_ms=end_ms)
    if not candles:
        return None

    candles = [c for c in candles if c.open_ms <= end_ms]
    if len(candles) < 3:
        return None

    exit_price = float(sig["exit_price"]) if sig["exit_price"] is not None else None
    exit_idx = None
    if exit_price is not None:
        closed_ms = int(closed_at.timestamp() * 1000)
        exit_idx = min(range(len(candles)), key=lambda i: abs(candles[i].close_ms - closed_ms))

    # Kirish shami — "pozitsiya izi" uslubi uchun: kirish TO'LIQ KENGLIKDAGI
    # chiziq o'rniga aynan shu shamning ustiga qo'yilgan belgi bilan
    # ko'rsatiladi (`_render()`ga qarang).
    opened_ms = int(opened_at.timestamp() * 1000)
    entry_idx = min(range(len(candles)), key=lambda i: abs(candles[i].close_ms - opened_ms))

    return _render(
        candles, header=f"#{sig['id']} {sig['symbol']}", side=sig["side"],
        entry=float(sig["entry"]), sl=float(sig["sl_initial"]),
        tps=[float(x) for x in sig["tps"]], tp_hit=sig["tp_hit"],
        exit_idx=exit_idx, exit_price=exit_price,
        pnl=sig["pnl_pct"], r=sig["r_multiple"],
        ws_name=ws_name, bot_username=bot_username, tf=tf, note=None,
        entry_idx=entry_idx,
    )


def news_chart(candles, news_idx: int, symbol: str, live_pct: float,
               label: str = "News", marker_color: str | None = None,
               tf: str | None = None) -> io.BytesIO:
    """News Trade AI grafigi — Entry/SL/TP yo'q, faqat aynan qaysi shamdan
    yangilik (yoki boshqa hodisa — masalan hajm portlashi) chiqqanini
    ko'rsatuvchi belgi va joriy % o'zgarish. `label` shu belgi ostidagi
    matn — surge.py "Portlash" kabi boshqa so'z bilan ham ishlatadi.
    `marker_color` — belgi (chiziq/nuqta/yorliq) rangi; berilmasa ACC
    (kumush, standart). Likvidatsiya kabi ANIQ yo'nalishi bor hodisalar
    uchun GREEN/RED beriladi (masalan long ustun bo'lsa RED — narx
    pasaygani uchun). `tf` — `_render()`dagi kabi sarlavha ostida
    ko'rsatiladi (grafik qaysi shamda chizilganini bildiradi).

    `_render()`dan ataylab ALOHIDA: u yerda entry/sl majburiy parametr va
    y-o'qi hisobiga kiradi — bu yerda ular umuman yo'q. Shamlarni chizish
    (`_draw_candles`) ikkalasida ham baravar ishlatiladi."""
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    pad = (hi - lo) * 0.08 or hi * 0.01
    lo -= pad
    hi += pad

    _draw_candles(ax, candles, hi, lo)

    mark_col = marker_color or ACC
    news_idx = max(0, min(news_idx, len(candles) - 1))
    news_price = candles[news_idx].close
    news_col = GREEN if live_pct >= 0 else RED
    ax.axvline(news_idx, color=mark_col, lw=1.1, ls="--", alpha=0.8, zorder=1)
    ax.scatter([news_idx], [news_price], color=mark_col, s=60, zorder=5,
               edgecolor=BG, linewidth=1.3)
    ax.annotate(label, xy=(news_idx, news_price), xytext=(0, -20),
                textcoords="offset points", color=mark_col, fontsize=10,
                fontweight="bold", ha="center")

    # Sham blokidan keyin bo'sh joy (kattalashtirildi — `_render()`dagi
    # bilan bir xil sabab: joriy sham ramka markaziga yaqinroq chiqsin),
    # so'ng — doimiy hajm profili zonasi (BUTUN ko'rinadigan oyna bo'yicha,
    # pastdagi `_draw_volume_profile` izohiga qarang).
    right_pad = max(10.0, len(candles) * 0.45)
    vp_width = max(10.0, len(candles) * 0.22)
    gap_end = len(candles) - 1 + right_pad
    x_max = gap_end + vp_width
    _draw_volume_profile(ax, candles, lo, hi, vp_left=gap_end, vp_right=x_max)

    ax.set_xlim(-1.5, x_max)
    ax.set_ylim(lo, hi)
    ax.grid(True, color=GRID, lw=0.6, alpha=0.6)
    ax.set_xticks([])
    ax.tick_params(colors=TXT, labelsize=9.5)
    for spine in ax.spines.values():
        spine.set_color(GRID)

    fig.text(0.045, 0.955, symbol, fontsize=16, fontweight="bold", color=TITLE)
    if tf:
        fig.text(0.045, 0.925, f"· {tf}", fontsize=11, color=TXT)
    fig.text(0.97, 0.955, f"{live_pct:+.2f}%", fontsize=17, fontweight="bold",
              color=news_col, ha="right")

    fig.subplots_adjust(left=0.062, right=0.985, top=0.88, bottom=0.08)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf


# --- Likvidatsiya heatmap ---
# CoinGlass'ning mashhur narx-klaster heatmap'i Professional tarifdan
# ($699/oy) boshlab ochiladi, Hyblock Capital ham amalda pullik bo'lib
# chiqdi — ikkalasi ham rad etildi. Foydalanuvchi keyin CoinAnk'ning
# (coinank.com) bepul veb-sahifasi ortidagi ichki JSON so'rovini
# DevTools orqali topdi (`coinank.py`) — bu funksiya manba QAYSI
# bo'lishidan qat'i nazar bir xil oddiy shaklni kutadi: `{startingPrice,
# timestamp, size}` (narx darajasi, vaqt, taxminiy majburan yopilish
# hajmi) — oddiy shamli grafik EMAS, shuning uchun `_draw_candles`/
# `news_chart`dan butunlay ALOHIDA chiziladi.
import numpy as np

HEATMAP_CMAP = "inferno"


def liquidation_heatmap_chart(buckets: list[dict], coin: str,
                              interval: str) -> io.BytesIO | None:
    """`buckets` — `{startingPrice, timestamp, size}` ro'yxati (manba
    modul — `coinank.py` va h.k. — shu shaklga o'giradi). Narx (Y) va
    vaqt (X) bo'yicha panjara yasab, `size`ni rang intensivligi
    sifatida chizadi (bir xil narx+vaqt katagida bir nechta qator
    bo'lsa, ularning `size`lari QO'SHILADI — bu yerda yo'nalish emas,
    UMUMIY klaster zichligi ko'rsatiladi). Ma'lumot yetarli bo'lmasa
    (masalan barcha `size=0` yoki bo'sh ro'yxat) `None` — chaqiruvchi
    shunda oddiy shamli grafikka qaytadi."""
    if not buckets:
        return None

    times = sorted({int(b["timestamp"]) for b in buckets})
    # Narx darajasi kaliti sifatida `startingPrice` ishlatiladi (har bir
    # bucket kengligi bir xil deb taxmin qilinadi).
    prices = sorted({float(b["startingPrice"]) for b in buckets})
    if len(times) < 2 or len(prices) < 2:
        return None
    t_idx = {t: i for i, t in enumerate(times)}
    p_idx = {p: i for i, p in enumerate(prices)}

    grid = np.zeros((len(prices), len(times)))
    for b in buckets:
        try:
            size = float(b.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if size <= 0:
            continue
        ti = t_idx.get(int(b["timestamp"]))
        pi = p_idx.get(float(b["startingPrice"]))
        if ti is None or pi is None:
            continue
        grid[pi, ti] += size

    if not grid.any():
        return None

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    # `pcolormesh` chegaralari kataklar SONIDAN bittaga ko'p bo'lishi kerak
    # — shuning uchun har ikki o'qqa ham bitta qo'shimcha "yakuniy chegara"
    # qo'shiladi (oxirgi katak kengligi avvalgisi bilan bir xil deb olinadi).
    t_edges = list(times) + [times[-1] + (times[-1] - times[-2] if len(times) > 1 else 1)]
    p_edges = list(prices) + [prices[-1] + (prices[-1] - prices[-2] if len(prices) > 1 else 1)]
    mesh = ax.pcolormesh(t_edges, p_edges, grid, cmap=HEATMAP_CMAP, shading="flat")

    ax.set_xticks([])
    ax.tick_params(colors=TXT, labelsize=9.5)
    for spine in ax.spines.values():
        spine.set_color(GRID)

    cbar = fig.colorbar(mesh, ax=ax, pad=0.012, fraction=0.035)
    cbar.ax.tick_params(colors=TXT, labelsize=8)
    cbar.outline.set_edgecolor(GRID)

    fig.text(0.045, 0.955, coin, fontsize=16, fontweight="bold", color=TITLE)
    fig.text(0.045, 0.925, f"· Likvidatsiya heatmap · {interval}", fontsize=11, color=TXT)

    fig.subplots_adjust(left=0.062, right=0.93, top=0.88, bottom=0.08)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf
