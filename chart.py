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

import exchange
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

# Volume/Volume Delta panellari (foydalanuvchi so'rovi — Hyblock Capital
# veb-sahifasi uslubi) uchun — HAQIQIY MEXC savdolaridan (`exchange.
# volume_delta_profile()`). Faqat KRIPTO uchun (aksiya/forex'da bunday
# ochiq tarixiy savdo ma'lumoti yo'q) va faqat JURNAL signal grafiklari
# (`setup_chart()`/`signal_chart()`) uchun — bular signal ochilganda va
# yopilganda BIR MARTA chiziladi, News Trade AI'ning har-4-soniyalik
# jonli yangilanishidek TAKROR chaqirilmaydi, shuning uchun MEXC tezlik
# chegarasiga xavf yo'q. 48 soat — 30 kunlik oynadan farqli, bu chinakam
# amalga oshiriladigan chegara (MEXC bir so'rovda MAKSIMUM 1000 savdo
# qaytaradi — 30 kun minglab so'rov talab qilardi, CLAUDE.md #107'ga
# qarang).
DELTA_WINDOW_MS = 48 * 3_600_000
DELTA_BINS = 30


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


def _idx_for_ms(candles, target_ms: int) -> int:
    """Berilgan vaqt TUSHADIGAN shamning indeksini topadi — shamning
    `[open_ms, close_ms]` oralig'ini O'Z ICHIGA olganini qidiradi, "eng
    yaqin `close_ms`" (mutlaq farq) o'rniga.

    Sabab: displaydagi timeframe (masalan 15m) kuzatuvning ichki 1
    daqiqalik aniqligidan KATTA bo'lganda, "eng yaqin close_ms" usuli
    XRONOLOGIK TARTIBSIZ sham tanlashi mumkin edi — masalan `entry_idx`
    va `exit_idx` mustaqil hisoblanib, natijada ENTRY belgisi grafikda
    EXIT belgisidan KEYIN chiqib qolardi (foydalanuvchi #131 LINEAUSDT
    skrinshotida ko'rsatdi — "TP orqada, kirish oldinda bo'lib qolgan"),
    garchi haqiqiy hisob-kitob (pnl/R, tracker.py'dan, mustaqil va
    to'g'ri xronologik tartibda) TO'G'RI bo'lsa ham."""
    for i, c in enumerate(candles):
        if c.open_ms <= target_ms <= c.close_ms:
            return i
    # Oraliqqa umuman tushmasa (masalan so'ralgan oyna chetida) — eng
    # yaqin chegaraga qaytadi (avvalgi xatti-harakat, faqat fallback sifatida).
    return min(range(len(candles)), key=lambda i: abs(candles[i].close_ms - target_ms))


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


def _draw_side_profiles(ax_vol, ax_delta, vol_bins: list[float], delta_bins: list[float],
                        bin_lo: float, bin_size: float, lo: float, hi: float) -> None:
    """`_render()`/`surge_profile_chart()` uchun umumiy — HAQIQIY MEXC
    savdolaridan (`exchange.volume_delta_profile()`) olingan narx darajasi
    bo'yicha Volume va Volume Delta (xarid-sotuv) panellari, alohida
    o'qlarga (`ax_vol`/`ax_delta`) chiziladi — ikkalasi ham chaqiruvchi
    tomonidan narx (`ax_price`) bilan BIR XIL `sharey` ga ega bo'lishi
    kerak."""
    peak_vol = max(vol_bins) or 1.0
    for i, v in enumerate(vol_bins):
        if v <= 0:
            continue
        y0 = bin_lo + i * bin_size
        ax_vol.barh(y0 + bin_size / 2, v, height=bin_size * 0.92, color=VP_COLOR,
                   alpha=0.25 + 0.55 * (v / peak_vol), edgecolor="none")
    ax_vol.set_xlim(0, peak_vol * 1.08)
    ax_vol.set_ylim(lo, hi)
    ax_vol.tick_params(colors=TXT, labelsize=8)
    ax_vol.set_title("Volume", color=TXT, fontsize=10, pad=6)

    peak_delta = max((abs(d) for d in delta_bins), default=0.0) or 1.0
    for i, d in enumerate(delta_bins):
        if d == 0:
            continue
        y0 = bin_lo + i * bin_size
        color = GREEN if d >= 0 else RED
        ax_delta.barh(y0 + bin_size / 2, d, height=bin_size * 0.92, color=color, alpha=0.8)
    ax_delta.axvline(0, color=GRID, lw=0.8)
    ax_delta.set_xlim(-peak_delta * 1.1, peak_delta * 1.1)
    ax_delta.set_ylim(lo, hi)
    ax_delta.tick_params(colors=TXT, labelsize=8)
    ax_delta.set_title("Volume Delta", color=TXT, fontsize=10, pad=6)


def _render(candles, *, header: str, side: str, entry: float, sl: float | None,
            tps: list[float], tp_hit: int, exit_idx: int | None,
            exit_price: float | None, pnl, r, ws_name: str,
            bot_username: str | None, tf: str, note: str | None,
            entry_idx: int | None = None,
            vol_bins: list[float] | None = None, delta_bins: list[float] | None = None,
            bin_lo: float | None = None, bin_size: float | None = None) -> io.BytesIO:
    """`vol_bins`/`delta_bins`/`bin_lo`/`bin_size` — ixtiyoriy, berilsa
    (`exchange.volume_delta_profile()`dan, faqat kripto uchun) narx
    grafigi yoniga HAQIQIY Volume/Volume Delta panellari (uch ustunli
    joylashuv, `surge_profile_chart()`dagi bilan bir xil uslub)
    qo'shiladi — berilmasa (standart, aksariyat chaqiruvlar), avvalgidek
    BITTA o'qli, ichki hajm profili bilan chiziladi (xatti-harakat
    o'ZGARMAYDI)."""
    has_profile = vol_bins is not None and delta_bins is not None
    if has_profile:
        fig = plt.figure(figsize=(11, 5.6), dpi=160)
        gs = fig.add_gridspec(1, 3, width_ratios=[5, 1.15, 1.15], wspace=0.05)
        ax = fig.add_subplot(gs[0])
        ax_vol = fig.add_subplot(gs[1], sharey=ax)
        ax_delta = fig.add_subplot(gs[2], sharey=ax)
        for extra_ax in (ax_vol, ax_delta):
            extra_ax.set_facecolor(BG)
            extra_ax.set_xticks([])
            for spine in extra_ax.spines.values():
                spine.set_color(GRID)
    else:
        fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    # `sl` NULL bo'lishi mumkin — limit-keyin-TP/SL oqimida entry hali
    # TP/SL'siz e'lon qilinadi (`setup_chart()`), stop chizig'i hali
    # chizib bo'lmaydi.
    levels = [entry, *([sl] if sl is not None else []), *tps]
    if exit_price is not None:
        levels.append(exit_price)
    lo = min(lo, *levels)
    hi = max(hi, *levels)
    if has_profile:
        lo = min(lo, bin_lo)
        hi = max(hi, bin_lo + len(vol_bins) * bin_size)
    pad = (hi - lo) * 0.08 or hi * 0.01
    lo -= pad
    hi += pad

    _draw_candles(ax, candles, hi, lo)

    # Oxirgi shamdan keyin bo'sh joy — savdo platformalaridagi kabi ("right
    # offset"), YIRIKROQ qilingan (0.10 -> 0.45): joriy sham ramka
    # markaziga yaqinroq chiqishi, yorliqlar esa shamlar bilan ustma-ust
    # tushmasligi uchun (foydalanuvchi: "yozuvlar chartga aralashib
    # ketyabti", "hozirgi shamni ramka markaziga chiqarish kerak"). Undan
    # KEYIN — alohida, doimiy ko'rinadigan hajm profili zonasi — FAQAT
    # `has_profile=False` bo'lganda shu o'qning ICHIDA (aks holda haqiqiy
    # Volume/Delta panellari ALOHIDA o'qlarda chiziladi, pastga qarang).
    right_pad = max(10.0, len(candles) * 0.45)
    gap_end = len(candles) - 1 + right_pad
    if has_profile:
        x_max = gap_end
    else:
        vp_width = max(10.0, len(candles) * 0.22)
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
    if sl is not None:
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

    if has_profile:
        _draw_side_profiles(ax_vol, ax_delta, vol_bins, delta_bins, bin_lo, bin_size, lo, hi)

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


async def _delta_profile(market: str, symbol: str, lo: float, hi: float,
                         end_ms: int) -> tuple[list[float], list[float], float, float] | None:
    """`setup_chart()`/`signal_chart()` uchun umumiy — faqat KRIPTO uchun
    (aksiya/forex'da bunday tarixiy savdo darajasidagi ma'lumot yo'q),
    oxirgi `DELTA_WINDOW_MS` (48 soat) ichidagi HAQIQIY MEXC savdolaridan
    Volume/Volume Delta profilini hisoblaydi. Har qanday xato yoki mos
    kelmaslik — `None` (chaqiruvchi shunda ODDIY, profilsiz grafikka
    qaytadi, xato hech qachon ko'tarilmaydi)."""
    if market != "crypto" or hi <= lo:
        return None
    try:
        result = await exchange.volume_delta_profile(
            symbol, end_ms - DELTA_WINDOW_MS, end_ms, lo, hi, n_bins=DELTA_BINS)
    except Exception:
        log.warning("Volume delta profili olinmadi (%s)", symbol, exc_info=True)
        return None
    if result is None:
        return None
    vol_bins, delta_bins = result
    bin_size = (hi - lo) / DELTA_BINS
    return vol_bins, delta_bins, lo, bin_size


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
    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    profile = await _delta_profile(market, symbol, lo, hi, now_ms)
    vol_bins, delta_bins, bin_lo, bin_size = profile if profile else (None, None, None, None)
    return _render(
        candles, header=symbol, side=draft["side"],
        entry=float(draft["entry"]),
        sl=float(draft["sl"]) if draft.get("sl") is not None else None,
        tps=[float(x) for x in draft["tps"]] if draft.get("tps") else [], tp_hit=0,
        exit_idx=None, exit_price=None, pnl=None, r=None,
        ws_name=ws_name, bot_username=bot_username, tf=tf,
        note="ochildi" if mode == "market" else "kutilmoqda",
        vol_bins=vol_bins, delta_bins=delta_bins, bin_lo=bin_lo, bin_size=bin_size,
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
            exit_idx = _idx_for_ms(candles, closed_ms)
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
        exit_idx = _idx_for_ms(candles, closed_ms)

    # Kirish shami — "pozitsiya izi" uslubi uchun: kirish TO'LIQ KENGLIKDAGI
    # chiziq o'rniga aynan shu shamning ustiga qo'yilgan belgi bilan
    # ko'rsatiladi (`_render()`ga qarang).
    opened_ms = int(opened_at.timestamp() * 1000)
    entry_idx = _idx_for_ms(candles, opened_ms)

    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    profile = await _delta_profile(sig["market"], sig["symbol"], lo, hi,
                                   int(closed_at.timestamp() * 1000))
    vol_bins, delta_bins, bin_lo, bin_size = profile if profile else (None, None, None, None)

    return _render(
        candles, header=f"#{sig['id']} {sig['symbol']}", side=sig["side"],
        entry=float(sig["entry"]), sl=float(sig["sl_initial"]),
        tps=[float(x) for x in sig["tps"]], tp_hit=sig["tp_hit"],
        exit_idx=exit_idx, exit_price=exit_price,
        pnl=sig["pnl_pct"], r=sig["r_multiple"],
        ws_name=ws_name, bot_username=bot_username, tf=tf, note=None,
        entry_idx=entry_idx,
        vol_bins=vol_bins, delta_bins=delta_bins, bin_lo=bin_lo, bin_size=bin_size,
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


# --- Hajm portlashi uchun: Volume + Volume Delta panellari ---
# Foydalanuvchi Hyblock Capital'ning veb-sahifasidagi ko'rinishni
# yoqtirdi (narx grafigi yonida, bir xil narx o'qini baham ko'ruvchi
# Volume/Volume Delta panellari). Likvidatsiya/Liquidations Delta
# panellarini narx darajasi bo'yicha bepul olib bo'lmagani uchun
# (uchta manba ham muvaffaqiyatsiz — CLAUDE.md #98-#107) ULAR
# QURILMAYDI — faqat Volume/Volume Delta, chunki bular HAQIQIY MEXC
# savdo ma'lumotidan (`exchange.volume_delta_profile()`) hisoblanadi.
# Foydalanuvchi qarori bo'yicha bu FAQAT "hajm portlashi" postida
# ishlatiladi (har 4s yangilanadigan boshqa post turlarida emas —
# MEXC tezlik chegarasi xavfi).
def surge_profile_chart(candles, news_idx: int, symbol: str, live_pct: float,
                        vol_bins: list[float], delta_bins: list[float],
                        bin_lo: float, bin_size: float,
                        label: str = "Portlash", tf: str | None = None) -> io.BytesIO:
    """`vol_bins`/`delta_bins` — `exchange.volume_delta_profile()` natijasi,
    BIR MARTA (post vaqtida) hisoblanadi va bazada saqlanadi — har jonli
    yangilanish tikida QAYTA so'ralmaydi (faqat shamlar/narx yangilanadi,
    savdo profili o'zgarmasdan qoladi). `bin_lo`/`bin_size` — profil
    ustunlarining narx chegaralari (`bin_lo + i*bin_size` — i-ustun
    boshlanishi).

    Uch ustunli (GridSpec) joylashuv: narx (shamlar), Volume, Volume
    Delta — barchasi BIR XIL narx (Y) o'qini baham ko'radi. `news_chart()`
    dan ATAYLAB ALOHIDA — u yerdagi ichki (bitta o'qli) hajm profilidan
    farqli, bu yerda alohida pastki o'qlar (subplot'lar) kerak."""
    n_bins = len(vol_bins)
    hi_bin = bin_lo + n_bins * bin_size

    lo = min(min(c.low for c in candles), bin_lo)
    hi = max(max(c.high for c in candles), hi_bin)
    pad = (hi - lo) * 0.04 or hi * 0.01
    lo -= pad
    hi += pad

    fig = plt.figure(figsize=(11, 5.6), dpi=160)
    fig.patch.set_facecolor(BG)
    gs = fig.add_gridspec(1, 3, width_ratios=[5, 1.15, 1.15], wspace=0.05)
    ax_price = fig.add_subplot(gs[0])
    ax_vol = fig.add_subplot(gs[1], sharey=ax_price)
    ax_delta = fig.add_subplot(gs[2], sharey=ax_price)

    for ax in (ax_price, ax_vol, ax_delta):
        ax.set_facecolor(BG)
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_color(GRID)

    _draw_candles(ax_price, candles, hi, lo)

    mark_col = ACC
    news_idx = max(0, min(news_idx, len(candles) - 1))
    news_price = candles[news_idx].close
    news_col = GREEN if live_pct >= 0 else RED
    ax_price.axvline(news_idx, color=mark_col, lw=1.1, ls="--", alpha=0.8, zorder=1)
    ax_price.scatter([news_idx], [news_price], color=mark_col, s=60, zorder=5,
                     edgecolor=BG, linewidth=1.3)
    ax_price.annotate(label, xy=(news_idx, news_price), xytext=(0, -20),
                      textcoords="offset points", color=mark_col, fontsize=10,
                      fontweight="bold", ha="center")

    # O'ng tomonda bo'sh joy (`_render()`/`news_chart()`dagi `right_pad` bilan
    # bir xil sabab) — buni QO'YMASAK oxirgi (joriy) sham va "Portlash" yorlig'i
    # to'g'ridan-to'g'ri Volume panelining chetiga TIQILIB qolardi (foydalanuvchi:
    # "hammasi tiqilib qolgan, chartni o'rtaroqqa surish kerak").
    right_pad = max(6.0, len(candles) * 0.3)
    ax_price.set_xlim(-1.5, len(candles) - 1 + right_pad)
    ax_price.set_ylim(lo, hi)
    ax_price.grid(True, color=GRID, lw=0.6, alpha=0.6)
    ax_price.tick_params(colors=TXT, labelsize=9.5)

    _draw_side_profiles(ax_vol, ax_delta, vol_bins, delta_bins, bin_lo, bin_size, lo, hi)

    fig.text(0.045, 0.965, symbol, fontsize=16, fontweight="bold", color=TITLE)
    if tf:
        fig.text(0.045, 0.935, f"· {tf}", fontsize=11, color=TXT)
    fig.text(0.35, 0.965, f"{live_pct:+.2f}%", fontsize=17, fontweight="bold",
             color=news_col)

    fig.subplots_adjust(left=0.05, right=0.985, top=0.86, bottom=0.06)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf


# --- MACD kesishmasi uchun: narx + MACD paneli ---
# Foydalanuvchi namunasi (Bulltard.com kanali): yuqorida sham grafigi,
# pastida alohida MACD paneli (MACD chizig'i, signal chizig'i va
# gistogramma). `news_chart()`dan farqi — bu yerda IKKI panel bor va
# ular bir xil x-o'qini baham ko'radi; hajm profili chizilmaydi (MACD
# paneli uchun joy kerak va bu yerda profilning ma'nosi yo'q).
def macd_chart(candles, symbol: str, tf: str, direction: str,
               macd_line: list[float], signal_line: list[float],
               hist: list[float], strong: bool = False) -> io.BytesIO:
    """`macd_line`/`signal_line`/`hist` — `indicators.macd()` natijasi,
    uzunligi `candles` bilan BIR XIL bo'lishi kerak (chaqiruvchi ikkalasini
    ham bir xil manbadan hisoblaydi). `direction` — "bullish"/"bearish",
    kesishma belgisi va sarlavha rangi shunga qarab tanlanadi."""
    fig, (ax, axm) = plt.subplots(
        2, 1, figsize=(9, 6.2), dpi=160, sharex=True,
        gridspec_kw={"height_ratios": [2.6, 1], "hspace": 0.06})
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    axm.set_facecolor(BG)

    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    pad = (hi - lo) * 0.08 or hi * 0.01
    lo -= pad
    hi += pad

    _draw_candles(ax, candles, hi, lo)

    col = GREEN if direction == "bullish" else RED
    idx = len(candles) - 1

    # Kesishma shami — ikkala panelda ham bir xil vertikal chiziq bilan
    # belgilanadi (foydalanuvchi qaysi shamda sodir bo'lganini darhol
    # ko'rishi uchun).
    for a in (ax, axm):
        a.axvline(idx, color=col, lw=1.1, ls="--", alpha=0.85, zorder=1)

    last_close = candles[-1].close
    ax.scatter([idx], [last_close], color=col, s=70, zorder=5,
               edgecolor=BG, linewidth=1.3)

    # --- MACD paneli ---
    xs = list(range(len(candles)))
    axm.axhline(0, color=GRID, lw=0.9, alpha=0.9)
    for i, h in enumerate(hist):
        axm.bar(i, h, width=0.7, color=(GREEN if h >= 0 else RED), alpha=0.55,
                linewidth=0)
    axm.plot(xs, macd_line, color=ACC, lw=1.3, zorder=3)
    axm.plot(xs, signal_line, color="#f0a12e", lw=1.2, zorder=3)

    ax.set_ylim(lo, hi)
    for a in (ax, axm):
        # O'ngdan bo'sh joy: oxirgi sham ramkaning chekkasiga TIQILIB
        # qolmasligi kerak (foydalanuvchi: "chart burchakka tiqilib
        # qolgan, ozroq o'rtaroqqa surish kerak") — 12% zaxira kesishma
        # shamini va uning belgisini bemalol ko'rsatadi.
        a.set_xlim(-1.5, len(candles) - 1 + max(4.0, len(candles) * 0.12))
        a.grid(True, color=GRID, lw=0.6, alpha=0.6)
        a.set_xticks([])
        a.tick_params(colors=TXT, labelsize=9)
        # Narx yorliqlari O'NG tomonda — foydalanuvchi namunasidagi
        # (Bulltard/TradingView) kabi: trader oxirgi narxni grafikning
        # o'ng chetida, joriy sham yonida ko'rishga o'rgangan.
        a.yaxis.tick_right()
        a.yaxis.set_label_position("right")
        for spine in a.spines.values():
            spine.set_color(GRID)

    axm.text(0.012, 0.86, "MACD 12·26·9", transform=axm.transAxes,
             color=TXT, fontsize=8.5, fontweight="bold")

    title = "MACD Bullish crossover" if direction == "bullish" else "MACD Bearish crossover"
    if strong:
        title = ("MACD Super bullish crossover" if direction == "bullish"
                 else "MACD Super bearish crossover")
    fig.text(0.045, 0.958, symbol, fontsize=16, fontweight="bold", color=TITLE)
    fig.text(0.045, 0.928, f"· {tf}", fontsize=11, color=TXT)
    fig.text(0.97, 0.955, title, fontsize=13, fontweight="bold", color=col,
             ha="right")

    # Narx yorliqlari o'ngga ko'chgani uchun chap chekka torayadi, o'ng
    # chekkada esa ularga joy ochiladi.
    fig.subplots_adjust(left=0.022, right=0.925, top=0.885, bottom=0.05)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    return buf
