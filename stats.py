"""Statistika hisobotlari va equity curve."""
import io
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
# Formula tahlili ($...$) O'CHIQ (191): guruh nomi va username rasmlarga
# tushadi; "$\x$" kabi nom matplotlib'ni ParseFatalException bilan yiqitardi
# (grafik, karta, PDF eksport yo'qolardi), "1,000$ … 2,000$" esa formula
# bo'lib buzilardi. Loyihada formulalar ataylab ishlatilmaydi.
matplotlib.rcParams["text.parse_math"] = False
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D

import config
import db
import exchange
import forex
import i18n
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
_MONTHS = {
    "uz": MONTHS_UZ,
    "ru": ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
           "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
}


# Sana oralig'i uchun QISQA shakl. To'liq nom sanada g'aliz chiqadi:
# ruschada "9 Август" emas, "9 авг" bo'lishi kerak (to'g'ri shakli
# "9 августа" — qaratqich kelishigi, lekin qisqasi bu muammoni butunlay
# chetlab o'tadi va uchala tilda ham tabiiy o'qiladi).
_MONTHS_SHORT = {
    "uz": ["Yan", "Fev", "Mar", "Apr", "May", "Iyun",
           "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"],
    "ru": ["янв", "фев", "мар", "апр", "мая", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def months_short(lang: str | None = None) -> list[str]:
    """Oyning qisqa nomi — faqat sana oralig'ida ishlatiladi."""
    return _MONTHS_SHORT[i18n.normalize(lang)]


def months(lang: str | None = None) -> list[str]:
    """Oy nomlari — tanlangan tilda. `MONTHS_UZ` eski chaqiruvchilar uchun
    qoldirildi (o'zbekcha ro'yxatning AYNAN o'zi)."""
    return _MONTHS[i18n.normalize(lang)]


def net_vs_start(sum_weighted_pct: float) -> float:
    """Depozitga nisbatan natijani BOSHLANG'ICH kapitalga qayta hisoblaydi.

    ⚠️ Muammo shu yerda edi. `sum_weighted` (bazadagi va Python'dagi
    ikkala hisob ham) har savdoning pul natijasini JORIY depozitga
    bo'ladi:

        sum_weighted = 100 · Σ(foyda) / depozit_HOZIRGI

    Depozit esa har yopilgan savdodan keyin o'sib boradi
    (`apply_deposit_delta`), ya'ni bo'luvchi — YAKUNIY balans. Natijada
    100 000 dan 164 000 ga chiqqan hisob "+40.18%" ko'rsatardi, chunki
    65 915 / 164 036 = 40.18%. To'g'ri javob 65 915 / 98 121 = 67.2% —
    foyda BOSHLANG'ICH kapitalga bo'linishi kerak.

    Qayta hisob qo'shimcha ma'lumotsiz, sof algebra bilan chiqadi.
    w = sum_weighted/100 = foyda/depozit bo'lsa:

        boshlang'ich = depozit − foyda = depozit·(1 − w)
        natija       = foyda / boshlang'ich = w / (1 − w)

    Bu grafikdagi (`_equity_curve`) hisob bilan AYNAN bir xil javob
    beradi — ilgari grafik va plitka ikki xil son ko'rsatardi."""
    w = sum_weighted_pct / 100.0
    if w >= 1.0:
        # Boshlang'ich kapital nol yoki manfiy — bo'lib bo'lmaydi.
        # Amalda uchramaydi (butun balans bitta savdodan kelgan bo'lishi
        # kerak), lekin nol bo'linishdan himoya shart.
        return sum_weighted_pct
    return w / (1.0 - w) * 100.0


def _compound(pcts: list[float]) -> float:
    """Har savdoda bir xil ulush ishlatilsa — kompaund natija."""
    eq = 1.0
    for p in pcts:
        eq *= (1 + p / 100)
    return (eq - 1) * 100


async def _open_summary(workspace_id: int, deposit, show_money: bool,
                         lang: str | None = None) -> str | None:
    """Hali yopilmagan (PENDING/ACTIVE) pozitsiyalar qisqacha holati — /symbols'dagi
    kabi hisobot davri "joriy"ga tegishli bo'lsa summary() shuni ham qo'shadi,
    aks holda foydalanuvchi "nega ochiq pozitsiyalar hisobotda yo'q" deb
    chalkashishi mumkin edi."""
    rows = await db.live_signals(workspace_id)
    pending = [r for r in rows if r["status"] == "PENDING"]
    active = [r for r in rows if r["status"] == "ACTIVE"]
    if not pending and not active:
        return None

    lines = [i18n.t("st.open_head", lang)]
    if pending:
        lines.append(i18n.t("st.open_pending", lang, n=len(pending)))

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
            lines.append(i18n.t("st.open_noprice", lang, n=len(active)))
        elif deposit:
            txt = i18n.t("st.open_live", lang, n=live_count, p=live_sum_pct)
            if show_money:
                txt += f"  ({live_money:+,.2f})"
            lines.append(txt)
        else:
            lines.append(i18n.t("st.open_no_dep", lang, n=live_count))

    return "\n".join(lines)


async def summary(workspace_id: int, since=None, until=None, title=None,
                   deposit=None, show_money: bool = True,
                   lang: str | None = None) -> str:
    """deposit — workspace'ning joriy umumiy depoziti. Bo'lsa, "Jami natija"/
    "Kompaund" har bir signalning haqiqiy pozitsiya hajmiga (alloc_amount)
    qarab depozitga nisbatan hisoblanadi — narx harakati foizi emas, depozitning
    necha foizga o'sgani ko'rsatiladi (aks holda har savdo butun depozit bilan
    kirilgandek hisoblanib, natija sun'iy shishib ketardi). Deposit
    belgilanmagan bo'lsa — eski, pozitsiya hajmisiz (raw) narx-harakati foizi
    ko'rsatiladi. show_money — real summani ko'rsatish kerakmi (guruh
    a'zolariga faqat foiz, admin/shaxsiy egasiga pul ham)."""
    if title is None:
        title = i18n.t("st.title_all", lang)
    s = await db.period_stats(workspace_id, since, until)
    show_open = since is None or until is None or until > datetime.now(timezone.utc)

    if not s or s["total"] == 0:
        t = [f"<b>{title}</b>", "", i18n.t("st.no_closed", lang)]
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
        t.append(i18n.t("st.signals", lang, n=total, w=s["wins"],
                        l=s["losses"], b=s["be"]))
        t.append(i18n.t("st.winrate", lang, wr=wr))

        if weighted:
            real_sum_pct = net_vs_start(sum(weighted))
            t.append(i18n.t("st.total_dep", lang, p=real_sum_pct))
            # "Kompaund" ATAYLAB faqat depozitsiz rejimda ko'rsatiladi.
            # Depozit rejimida har savdo o'sha paytdagi balansga qo'shiladi,
            # ya'ni natija ALLAQACHON kompaund: Π(1 + d/b) telescopiyalanib
            # yakuniy/boshlang'ich ga teng bo'ladi — bu esa yuqoridagi
            # qatorning o'zi. Ikkita bir xil sonni ikki nom bilan
            # ko'rsatish faqat chalkashtirardi.
            if show_money and s["real_pnl_money"] is not None:
                t.append(i18n.t("st.real_money", lang, m=float(s["real_pnl_money"])))
        else:
            pcts = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
            t.append(i18n.t("st.total_raw", lang, p=float(s["sum_pct"])))
            t.append(i18n.t("st.compound", lang, p=_compound(pcts)))

        t.append(i18n.t("st.avg_r", lang, avg=float(s["avg_r"]), tot=float(s["sum_r"])))
        t.append(i18n.t("st.avg_win_loss", lang, w=float(s["avg_win"]),
                        l=float(s["avg_loss"])))
        if pf:
            t.append(i18n.t("st.profit_factor", lang, pf=pf))

    if show_open:
        open_txt = await _open_summary(workspace_id, deposit, show_money, lang)
        if open_txt:
            t += ["", open_txt]

    return "\n".join(t)


async def monthly_table(workspace_id: int, limit: int = 12,
                         lang: str | None = None) -> str:
    rows = await db.monthly_breakdown(workspace_id, limit)
    if not rows:
        return i18n.t("st.no_data", lang)
    mon = months(lang)
    t = [i18n.t("st.monthly_head", lang), "<pre>"]
    t.append(f"{i18n.t('st.col_month', lang):<12}{'N':>4}{'WR':>7}"
             f"{i18n.t('st.col_pct', lang):>9}{'R':>7}")
    for r in rows:
        m = r["month"]
        # [:4] — [:3] bo'lsa "Iyun" va "Iyul" ikkalasi ham "Iyu" bo'lib qolardi.
        name = f"{mon[m.month - 1][:4]} {m.year}"
        wr = r["wins"] / r["total"] * 100 if r["total"] else 0
        t.append(f"{name:<12}{r['total']:>4}{wr:>6.0f}%{float(r['sum_pct']):>+9.2f}{float(r['avg_r']):>+7.2f}")
    t.append("</pre>")
    return "\n".join(t)


async def symbols_table(workspace_id: int, since=None, until=None,
                         title: str | None = None,
                         lang: str | None = None) -> str:
    """since/until berilmasa — butun davr. Berilsa — shu oraliqda yopilganlar
    (o'tgan, tugagan oylarda ochiq pozitsiya ko'rinmaydi — yopilganda avtomatik
    o'z oyiga tushadi). Joriy (hali davom etayotgan) davrda — hozir ochiq
    pozitsiyalar ham ko'rinadi: ⏳ allaqachon ochilgan (joriy foizi bilan),
    🕐 hali entry/limitga tegmagan (foizsiz — hisoblash uchun asos yo'q)."""
    if title is None:
        title = i18n.t("st.all_period", lang)
    show_open = since is None or until is None or until > datetime.now(timezone.utc)
    rows = await db.top_symbols(workspace_id, since, until)
    open_data = await db.open_signals_summary(workspace_id) if show_open else {}
    symbols = {r["symbol"] for r in rows} | set(open_data)
    if not symbols:
        return (i18n.t("st.symbols_head", lang, title=title) + "\n\n"
                + i18n.t("st.no_data", lang))

    by_sym = {r["symbol"]: r for r in rows}
    ordered = sorted(symbols, key=lambda s: -float(by_sym[s]["sum_pct"]) if s in by_sym else 0)

    def badge(icon: str, n: int) -> str:
        return icon if n == 1 else f"{icon}{n}"

    t = [i18n.t("st.symbols_head", lang, title=title), ""]
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
            parts.append(i18n.t("st.running", lang, p=live_sum))
        pct_txt = "  ".join(parts) if parts else i18n.t("st.open_word", lang)

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


async def equity_chart(workspace_id: int, deposit=None,
                        lang: str | None = None) -> io.BytesIO | None:
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
    axb.set_ylabel(i18n.t("rep.eq_y_dep" if weighted else "rep.eq_y_raw", lang),
                   color=TXT, fontsize=12, labelpad=10)
    axb.margins(y=0.26)

    axb.annotate(f"{i18n.t('rep.eq_start', lang)}  {base:,.0f}", xy=(n, base),
                 xytext=(-4, 8), textcoords="offset points",
                 color=TXT, fontsize=11, ha="right", va="bottom")
    axb.annotate(f"{eq[-1]:,.0f}", xy=(n, eq[-1]),
                 xytext=(-6, 16), textcoords="offset points",
                 color=line_col, fontsize=15, fontweight="bold", ha="right")

    # Cho'qqi yozuvi faqat oxirgi nuqtadan yetarlicha uzoq bo'lsa — aks holda
    # yakuniy balans yozuvi bilan ustma-ust tushadi.
    pi = eq.index(max(eq))
    if n - 1 - pi >= 3:
        axb.annotate(f"{i18n.t('rep.eq_peak', lang)} {max(eq):,.0f}", xy=(pi + 1, eq[pi]),
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
    axd.set_ylabel(i18n.t("rep.eq_bar_money" if weighted else "rep.eq_bar_pct", lang),
                   color=TXT, fontsize=12, labelpad=10)
    axd.set_xlabel(i18n.t("rep.eq_x", lang), color=TXT, fontsize=12, labelpad=8)
    axd.margins(y=0.26)
    if n <= 20:
        axd.set_xticks(x)
    else:
        axd.xaxis.set_major_locator(mticker.MaxNLocator(integer=True, nbins=20))

    leg = axb.legend(handles=[
        Line2D([0], [0], color=line_col, lw=2.8, marker="o", markerfacecolor=BG,
               markeredgewidth=2, label=i18n.t("rep.eq_leg_line", lang)),
        Line2D([0], [0], color=GREEN, lw=9, alpha=0.75,
               label=i18n.t("rep.eq_leg_win", lang)),
        Line2D([0], [0], color=RED, lw=9, alpha=0.75,
               label=i18n.t("rep.eq_leg_loss", lang)),
    ], loc="upper left", fontsize=10.5, facecolor=BG, edgecolor=GRID, framealpha=0.9)
    for t in leg.get_texts():
        t.set_color(TXT)

    change = eq[-1] - base
    change_pct = (eq[-1] / base - 1) * 100 if base else 0.0
    # Oy nomi ATAYLAB `%b` bilan emas: u tizim lokalidan keladi va doim
    # inglizcha chiqardi. `months()` esa tanlangan tilni beradi.
    mons = months_short(lang)
    a, b = rows[0]["closed_at"].astimezone(TZ), rows[-1]["closed_at"].astimezone(TZ)
    period = f"{a.day} {mons[a.month - 1]} — {b.day} {mons[b.month - 1]} {b.year}"
    fig.suptitle(i18n.t("rep.eq_title_dep" if weighted else "rep.eq_title_raw", lang),
                 color=TITLE, fontsize=17, fontweight="bold", y=0.975)
    chg = (f"{change:+,.0f}  ({change_pct:+.1f}%)" if weighted
           else f"{change_pct:+.1f}%")
    fig.text(0.5, 0.928,
             i18n.t("rep.eq_sub", lang, n=n, period=period, chg=chg, dd=max_dd),
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


def _pdf_metrics(s, rows, deposit, show_money, lang: str | None = None):
    """PDF ning 1-sahifasidagi ko'rsatkichlar: (yorliq, qiymat, rang) ro'yxati."""
    def L(key):
        return i18n.t(key, lang)

    total = s["total"]
    wr = s["wins"] / total * 100 if total else 0.0
    out = [
        (L("rep.pdf_signals"), f"{total}", P_TXT),
        (L("rep.pdf_winrate"), f"{wr:.1f}%", P_GREEN if wr >= 50 else P_RED),
        (L("rep.pdf_win_loss"), f"{s['wins']} / {s['losses']}", P_TXT),
    ]

    weighted = None
    if deposit:
        weighted = [float(r["pnl_pct"]) * float(r["alloc_amount"]) / float(deposit)
                    for r in rows
                    if r["pnl_pct"] is not None and r["alloc_amount"] is not None]
    if weighted:
        tot = net_vs_start(sum(weighted))
        out.append((L("rep.pdf_total_dep"), f"{tot:+.2f}%", P_GREEN if tot >= 0 else P_RED))
        # Kompaund yo'q — `summary()` dagi izohga qarang (depozit rejimida
        # natijaning o'zi kompaund).
        if show_money and s["real_pnl_money"] is not None:
            m = float(s["real_pnl_money"])
            out.append((L("rep.pdf_real"), f"{m:+,.2f}", P_GREEN if m >= 0 else P_RED))
    else:
        sp = float(s["sum_pct"])
        out.append((L("rep.pdf_total_raw"), f"{sp:+.2f}%", P_GREEN if sp >= 0 else P_RED))
        pcts = [float(r["pnl_pct"]) for r in rows if r["pnl_pct"] is not None]
        comp = _compound(pcts)
        out.append((L("rep.pdf_compound"), f"{comp:+.2f}%", P_GREEN if comp >= 0 else P_RED))

    out.append((L("rep.pdf_avg_r"), f"{float(s['avg_r']):+.2f}R", P_TXT))
    out.append((L("rep.pdf_avg_wl"),
                f"{float(s['avg_win']):+.2f}% / {float(s['avg_loss']):+.2f}%", P_TXT))
    if s["avg_loss"] and s["losses"]:
        gl = abs(float(s["avg_loss"])) * s["losses"]
        if gl:
            pf = float(s["avg_win"]) * s["wins"] / gl
            out.append((L("rep.pdf_pf"), f"{pf:.2f}", P_GREEN if pf >= 1 else P_RED))
    return out


async def pdf_report(workspace_id: int, ws_name: str, deposit=None,
                      show_money: bool = True,
                      lang: str | None = None) -> io.BytesIO | None:
    """Butun davr bo'yicha PDF hisobot: 1-sahifa — ko'rsatkichlar + balans
    egri chizig'i; keyin TO'LIQ juftliklar va oylar kesimi, so'ng har bir
    pozitsiya sana-vaqti bilan (192). Yopilgan signal bo'lmasa None."""
    from matplotlib.backends.backend_pdf import PdfPages

    s = await db.period_stats(workspace_id)
    if not s or s["total"] == 0:
        return None
    rows = await db.equity_series(workspace_id)
    syms = await db.top_symbols(workspace_id)
    month_rows = await db.monthly_breakdown(workspace_id, 1200)   # butun davr
    positions = await db.report_positions(workspace_id)
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
        for label, value, color in _pdf_metrics(s, rows, deposit, show_money, lang):
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
            ax.set_xlabel(i18n.t("rep.pdf_x", lang), color=P_MUTED, fontsize=9)
            ax.set_ylabel(i18n.t("rep.pdf_y_dep" if weighted else "rep.eq_y_raw", lang),
                          color=P_MUTED, fontsize=9)
            ax.set_title(i18n.t("rep.pdf_eq_title", lang), color=P_TXT, fontsize=12,
                         fontweight="bold", pad=8)
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)

        # ── Jadvallar (192): endi TO'LIQ — sig'masa keyingi sahifaga ──
        # Avval juftliklar 26 qatorda va sahifaning yarmida kesilar, oylar
        # esa faqat so'nggi 12 tasi edi ("butun davrdagini to'liq
        # ko'rsatmayapti").
        cols = (f"{i18n.t('rep.col_n', lang):>6}{i18n.t('rep.col_wr', lang):>9}"
                f"{i18n.t('rep.col_pct', lang):>13}")
        lines = []
        for r in syms:
            wr = r["wins"] / r["closed"] * 100 if r["closed"] else 0
            sp_ = float(r["sum_pct"])
            lines.append((f"{r['symbol'][:16]:<16}{r['closed']:>6}{wr:>8.0f}%{sp_:>+13.2f}",
                          P_GREEN if sp_ >= 0 else P_RED))
        _paged_lines(pdf, i18n.t("rep.pdf_syms", lang), ws_name,
                     f"{i18n.t('rep.col_pair', lang):<16}{cols}", lines, fontsize=11)

        lines = []
        for r in month_rows:
            m = r["month"]
            # To'liq oy nomi: 3 harfga qisqartirilsa "Iyun" va "Iyul" ikkalasi
            # ham "Iyu" bo'lib, qaysi oy ekani bilinmay qolardi.
            name = f"{months(lang)[m.month - 1]} {m.year}"
            wr = r["wins"] / r["total"] * 100 if r["total"] else 0
            sp_ = float(r["sum_pct"])
            lines.append((f"{name:<16}{r['total']:>6}{wr:>8.0f}%{sp_:>+13.2f}",
                          P_GREEN if sp_ >= 0 else P_RED))
        _paged_lines(pdf, i18n.t("rep.pdf_months", lang), ws_name,
                     f"{i18n.t('rep.col_month', lang):<16}{cols}", lines, fontsize=11)

        # ── Barcha pozitsiyalar (192) — albom sahifalarda, sana-vaqt bilan ──
        header, lines = _position_lines(positions, show_money, lang)
        _paged_lines(pdf, i18n.t("rep.pdf_positions", lang, n=len(positions)), ws_name,
                     header, lines, fontsize=8, landscape=True,
                     footnote=i18n.t("rep.pdf_pos_note", lang, tz=str(TZ)))

    buf.seek(0)
    return buf


def _fp(x) -> str:
    """Narx — ixcham, lekin aniq (kichik tangalarda ham raqamlar yo'qolmasin)."""
    if x is None:
        return "—"
    x = float(x)
    if x >= 1000:
        return f"{x:,.2f}"
    if x >= 1:
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".")


def _position_lines(rows, show_money: bool, lang: str | None) -> tuple[str, list]:
    """"Barcha pozitsiyalar" jadvali: sarlavha va (qator, rang) ro'yxati."""
    t = lambda k: i18n.t(k, lang)
    header = (f"{'#':<7}{t('rep.col_pair'):<13}{t('rep.c_side'):<6}{t('rep.c_open'):<16}"
              f"{t('rep.c_close'):<16}{t('rep.c_entry'):>13}{t('rep.c_exit'):>12}"
              f"{t('rep.c_stop'):>12}{'TP':>6}{t('rep.c_status'):>8}{t('rep.c_res'):>10}{'R':>7}")
    if show_money:
        header += f"{t('rep.c_amt'):>11}{t('rep.c_profit'):>11}"
    out = []
    for r in rows:
        st = r["status"]
        closed = st in ("TP", "SL", "BREAKEVEN")
        opened = r["opened_at"] or r["created_at"]
        o = f"{opened.astimezone(TZ):%d.%m.%y %H:%M}" if opened else "—"
        c = f"{r['closed_at'].astimezone(TZ):%d.%m.%y %H:%M}" if r["closed_at"] else "—"
        entry = _fp(r["entry"]) + ("*" if r["entry_first"] is not None else "")
        tps = r["tps"] or []
        tp = f"{r['tp_hit']}/{len(tps)}" if tps else "—"
        label = {"TP": "TP", "SL": "SL", "BREAKEVEN": "BE"}.get(st) or t(
            "rep.st_open" if st == "ACTIVE" else "rep.st_pending")
        pnl = float(r["pnl_pct"]) if (closed and r["pnl_pct"] is not None) else None
        res = f"{pnl:+.2f}%" if pnl is not None else "—"
        rr = f"{float(r['r_multiple']):+.2f}" if (closed and r["r_multiple"] is not None) else "—"
        line = (f"{'#' + str(r['id']):<7}{r['symbol'][:12]:<13}{r['side'][:5]:<6}{o:<16}{c:<16}"
                f"{entry:>13}{_fp(r['exit_price']) if closed else '—':>12}"
                f"{_fp(r['sl']):>12}{tp:>6}{label[:7]:>8}{res:>10}{rr:>7}")
        if show_money:
            amt = float(r["alloc_amount"]) if r["alloc_amount"] is not None else None
            prof = pnl / 100 * amt if (pnl is not None and amt is not None) else None
            line += (f"{f'{amt:,.0f}' if amt is not None else '—':>11}"
                     f"{f'{prof:+,.2f}' if prof is not None else '—':>11}")
        col = (P_GREEN if pnl > 0 else P_RED if pnl < 0 else P_MUTED) if pnl is not None \
            else (P_TXT if st == "ACTIVE" else P_MUTED)
        out.append((line, col))
    return header, out


def _paged_lines(pdf, title: str, subtitle: str, header: str, lines: list[tuple[str, str]],
                 fontsize: float = 10, landscape: bool = False,
                 footnote: str | None = None) -> None:
    """Monospace jadvalni kerakli miqdordagi sahifalarga yozadi (192).
    Qatorlar soni CHEKLANMAGAN — sig'maganda yangi sahifa, sarlavha va
    jadval boshi har sahifada qaytariladi. Bo'sh ro'yxatda hech narsa
    yozilmaydi."""
    if not lines:
        return
    size = (11.69, 8.27) if landscape else (8.27, 11.69)
    step = fontsize / 72 / size[1] * 1.45          # qator balandligi (fig ulushi)
    i, page = 0, 1
    while i < len(lines):
        fig = plt.figure(figsize=size)
        fig.patch.set_facecolor("white")
        fig.text(0.05, 0.95, title + (f" ({page})" if page > 1 else ""),
                 fontsize=16, fontweight="bold", color=P_TXT)
        if subtitle:
            fig.text(0.05, 0.922, subtitle, fontsize=10, color=P_MUTED)
        fig.text(0.95, 0.95, f"{datetime.now(TZ):%d.%m.%Y %H:%M}",
                 fontsize=9, color=P_MUTED, ha="right")
        fig.add_artist(plt.Line2D([0.05, 0.95], [0.905, 0.905], color=P_GRID, lw=1))
        y = 0.88
        fig.text(0.05, y, header, fontsize=fontsize, fontweight="bold",
                 color=P_MUTED, family="monospace")
        y -= step * 1.3
        bottom = 0.075 if footnote else 0.05
        while i < len(lines) and y > bottom:
            txt, col = lines[i]
            fig.text(0.05, y, txt, fontsize=fontsize, color=col, family="monospace")
            y -= step
            i += 1
        if footnote:
            fig.text(0.05, 0.03, footnote, fontsize=8, color=P_MUTED)
        fig.text(0.95, 0.03, str(page), fontsize=9, color=P_MUTED, ha="right")
        pdf.savefig(fig, facecolor="white")
        plt.close(fig)
        page += 1


def pdf_table_report(title: str, subtitle: str, header: str,
                      lines: list[tuple[str, str]]) -> io.BytesIO:
    """Monospace jadvalli ko'p sahifali PDF (admin ro'yxatlari uchun) —
    `_paged_lines` ustida (192: ilgari o'z nusxasi bor edi)."""
    from matplotlib.backends.backend_pdf import PdfPages

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _paged_lines(pdf, title, subtitle, header, lines or [("—", P_MUTED)])
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
