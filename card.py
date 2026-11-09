"""Yopilgan savdo uchun ULASHISH kartasi (1080x1080 PNG).

Birjalarning (BingX, Bybit, Binance) "PnL sharing" kartalari uslubida, lekin
SPOT savdoga moslangan: yelka (25X) yo'q, uning o'rnida "SPOT" yozuvi turadi
va foiz — real, yopilgan natija (birjalarda odatda "nereallashgan" ko'rsatiladi).

Birja brendi o'rnida: Trade Controller yozuvi, savdo egasining username'i,
guruh avatari va QR kod.

Nega matplotlib emas, Pillow: bu grafik emas, MAKET. Matnni pikselgacha aniq
joylashtirish, dumaloq avatar, QR paneli — bularning hammasi Pillow'da
to'g'ridan-to'g'ri va ancha tez chiziladi.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime

import importlib.util

import qrcode
from PIL import Image, ImageDraw, ImageFont

import i18n

log = logging.getLogger("card")

W = H = 1080
PAD = 76

BG = "#0A0A0C"
TXT = "#F3F4F6"
MUTED = "#9A9CA3"
FAINT = "#5A5B61"
LINE = "#26262C"

# Katta foiz va yo'nalish uchun ATAYLAB yorqinroq ranglar: karta qora fonda,
# telefon ekranida va Instagram'da ko'riladi — grafiklardagi bosiq #26a69a
# bu o'lchamda xira ko'rinadi. Grafiklar o'z rangida qoladi.
PROFIT = "#2BE08D"
LOSS = "#FF5F5F"

# Shriftlar matplotlib g'ildiragi ichidan olinadi — ular Railway konteynerida
# HAR DOIM bor (matplotlib allaqachon talab qilinadi). Tizim shriftlariga
# tayanib bo'lmaydi: konteynerda ular bo'lmasligi mumkin.
_FONT_DIR = os.path.join(os.path.dirname(importlib.util.find_spec("matplotlib").origin), "mpl-data", "fonts", "ttf")
_REG = os.path.join(_FONT_DIR, "DejaVuSans.ttf")
_BOLD = os.path.join(_FONT_DIR, "DejaVuSans-Bold.ttf")


def _f(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_BOLD if bold else _REG, size)


def _tracked(draw, xy, text: str, font, fill, spacing: float = 0.0) -> float:
    """Harflar orasi kengaytirilgan matn (letter-spacing).

    Pillow'da bunday imkoniyat yo'q, shuning uchun har bir belgi alohida
    chiziladi. Kichik, bosh harfli yorliqlar (YOPILGAN SAVDO) shusiz
    siqilgan va arzon ko'rinadi.
    """
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing
    return x - spacing - xy[0] if text else 0.0


def _tracked_width(draw, text: str, font, spacing: float = 0.0) -> float:
    if not text:
        return 0.0
    return sum(draw.textlength(c, font=font) for c in text) + spacing * (len(text) - 1)


def _qr(url: str, px: int) -> Image.Image:
    """Qora modulli QR, oq fonda.

    Teskari (oq modul, qora fon) QR ko'p skanerlarda o'qilmaydi — shuning
    uchun karta qora bo'lsa ham QR o'z oq paneli ustida turadi.
    """
    q = qrcode.QRCode(
        version=None, box_size=10, border=0,
        error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    img = q.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((px, px), Image.NEAREST)


def _circle_avatar(raw: bytes, px: int) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        log.warning("Avatar o'qilmadi", exc_info=True)
        return None
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize((px, px), Image.LANCZOS)
    mask = Image.new("L", (px * 4, px * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, px * 4 - 1, px * 4 - 1), fill=255)
    img.putalpha(mask.resize((px, px), Image.LANCZOS))
    return img


def _letter_avatar(letter: str, px: int) -> Image.Image:
    """Avatar bo'lmasa — nomning birinchi harfi. Veb sahifadagi bilan bir xil
    yechim: karta har doim bir xil balandlikda va tugallangan ko'rinadi."""
    img = Image.new("RGBA", (px * 4, px * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, px * 4 - 1, px * 4 - 1), fill="#1E1E23", outline=LINE, width=6)
    font = _f(int(px * 4 * 0.42), bold=True)
    bb = d.textbbox((0, 0), letter, font=font)
    d.text(((px * 4 - (bb[2] - bb[0])) / 2 - bb[0], (px * 4 - (bb[3] - bb[1])) / 2 - bb[1]),
           letter, font=font, fill=MUTED)
    return img.resize((px, px), Image.LANCZOS)


def _fmt_price(x: float) -> str:
    x = float(x)
    if x >= 100:
        return f"{x:,.2f}".replace(",", " ")
    if x >= 1:
        return f"{x:,.4f}".replace(",", " ")
    if x >= 0.01:
        return f"{x:.6f}"
    return f"{x:.8f}".rstrip("0")


def _glow(img: Image.Image, color: str) -> None:
    """Yuqori chetdagi mayin yorug'lik — natija rangida.

    Karta bir qarashda "foydami-zararmi" degan savolga javob berishi kerak;
    rang butun kartaga tarqalsa buni raqamni o'qimasdan ham bilib olasiz.
    """
    from PIL import ImageFilter
    layer = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r, g, b = Image.new("RGB", (1, 1), color).getpixel((0, 0))
    d.ellipse((-70, -130, W // 4 + 70, 96), fill=(r, g, b, 30))
    layer = layer.filter(ImageFilter.GaussianBlur(34)).resize((W, H), Image.LANCZOS)
    img.alpha_composite(layer)


def pnl_card(*, symbol: str, side: str, entry: float, exit_price: float,
             pnl_pct: float, r_multiple: float | None,
             closed_at: datetime, username: str | None, ws_name: str,
             logo: bytes | None, qr_url: str, sig_id: int | None = None,
             market: str = "crypto", qr_caption: str | None = None,
             qr_code: str | None = None, lang: str | None = None,
             leverage: int | None = None) -> io.BytesIO:
    """Ulashish kartasini chizadi va PNG bayt oqimini qaytaradi.

    `lang` — GURUH tili (`ws_lang`): karta guruh postiga biriktiriladi,
    ya'ni uning tili ham guruhning tili bo'lishi kerak, kartani yasagan
    odamning shaxsiy tili emas."""
    if qr_caption is None:
        qr_caption = i18n.t("card.ref_code", lang)
    acc = PROFIT if pnl_pct >= 0 else LOSS

    img = Image.new("RGBA", (W, H), BG)
    _glow(img, acc)
    d = ImageDraw.Draw(img)

    # ── Tepa: brend va shamlar bezagi ───────────────────────────────────
    _tracked(d, (PAD, PAD), "TRADE CONTROLLER", _f(30, bold=True), TXT, spacing=4.4)
    d.text((PAD, PAD + 44), i18n.t("card.subtitle", lang), font=_f(24), fill=FAINT)

    # O'ng yuqoridagi shamlar — birja kartalaridagi bezak o'rnida, lekin
    # ma'noli: uchta sham ko'tarilib boradi (zararda — tushib). Fitilsiz
    # to'g'ri burchakli ustunlar "pauza" belgisiga o'xshab qolgan edi.
    heights = [58, 96, 150] if pnl_pct >= 0 else [150, 96, 58]
    r0, g0, b0 = Image.new("RGB", (1, 1), acc).getpixel((0, 0))
    bx, base = W - PAD - 148, PAD + 158
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    for i, h in enumerate(heights):
        cx = bx + i * 52
        # Oxirgi (eng muhim) sham to'liq, oldingilari xiraroq — ko'z
        # o'zi natija tomonga qarab harakatlanadi.
        alpha = (110, 170, 255)[i]
        col = (r0, g0, b0, alpha)
        dd.line((cx + 13, base - h - 18, cx + 13, base + 12), fill=col, width=3)
        dd.rounded_rectangle((cx, base - h, cx + 26, base), radius=8, fill=col)
    img.alpha_composite(deco)

    # ── Sarlavha ────────────────────────────────────────────────────────
    y = 286
    _tracked(d, (PAD, y), i18n.t("card.closed", lang), _f(27, bold=True),
             MUTED, spacing=3.6)

    # ── Juftlik | yo'nalish | SPOT ──────────────────────────────────────
    y = 344
    f_sym = _f(64, bold=True)
    x = PAD
    d.text((x, y), symbol, font=f_sym, fill=TXT)
    x += d.textlength(symbol, font=f_sym) + 30
    f_meta = _f(46, bold=True)
    d.text((x, y + 8), "│", font=_f(50), fill=LINE)
    x += 32
    side_uz = "LONG" if side == "LONG" else "SHORT"
    d.text((x, y + 8), side_uz, font=f_meta, fill=PROFIT if side == "LONG" else LOSS)
    x += d.textlength(side_uz, font=f_meta) + 30
    d.text((x, y + 8), "│", font=_f(50), fill=LINE)
    x += 32
    # Spot — "SPOT"; futures (225) — yelka, masalan "10X".
    kind = (f"{leverage}X" if leverage and leverage > 1
            else ("SPOT" if market == "crypto" else market.upper()))
    d.text((x, y + 8), kind, font=f_meta, fill=TXT)

    # ── Katta foiz ──────────────────────────────────────────────────────
    pct = f"{pnl_pct:+.2f}%"
    size = 158
    f_big = _f(size, bold=True)
    # Uzun raqam (masalan -1234.56%) chetdan chiqib ketmasin.
    while d.textlength(pct, font=f_big) > W - 2 * PAD and size > 90:
        size -= 6
        f_big = _f(size, bold=True)
    d.text((PAD, 446), pct, font=f_big, fill=acc)

    # ── Narxlar ─────────────────────────────────────────────────────────
    rows = [(i18n.t("card.entry", lang), _fmt_price(entry)),
            (i18n.t("card.exit", lang), _fmt_price(exit_price))]
    if r_multiple is not None:
        rows.append((i18n.t("card.r", lang), f"{float(r_multiple):+.2f}R"))
    f_k, f_v = _f(31), _f(35, bold=True)
    ky = 668
    label_w = max(_tracked_width(d, k, f_k) for k, _ in rows)
    for k, v in rows:
        d.text((PAD, ky), k, font=f_k, fill=MUTED)
        d.text((PAD + label_w + 46, ky - 3), v, font=f_v, fill=TXT)
        ky += 54

    # ── Pastki chiziq ───────────────────────────────────────────────────
    # Chiziq faqat CHAP tomonda: o'ng tomonda endi taklif kodi turibdi,
    # chiziq uning ostidan o'tsa siqilgan ko'rinardi.
    d.line((PAD, H - 232, W - PAD - 300, H - 232), fill=LINE, width=2)

    # ── Pastki chap: avatar + username + sana ───────────────────────────
    av_px = 88
    av = _circle_avatar(logo, av_px) if logo else None
    if av is None:
        av = _letter_avatar((ws_name or "?").strip()[:1].upper(), av_px)
    ay = H - 172
    img.alpha_composite(av, (PAD, ay))

    who = f"@{username}" if username else (ws_name or "Trade Controller")
    f_who = _f(34, bold=True)
    tx = PAD + av_px + 24
    # Juda uzun username pastki o'ng burchakdagi QR ustiga chiqmasin.
    max_w = W - PAD - 300 - tx
    while d.textlength(who, font=f_who) > max_w and len(who) > 4:
        who = who[:-2] + "…"
    d.text((tx, ay + 8), who, font=f_who, fill=TXT)
    sub = closed_at.strftime("%d.%m.%Y")
    if sig_id is not None:
        sub = f"#{sig_id} · {sub}"
    d.text((tx, ay + 52), sub, font=_f(27), fill=FAINT)

    # ── Pastki o'ng: QR ─────────────────────────────────────────────────
    qr_px, quiet = 148, 14
    panel = qr_px + quiet * 2
    px0, py0 = W - PAD - panel, H - 172 - 14
    d.rounded_rectangle((px0, py0, px0 + panel, py0 + panel), radius=16, fill="white")
    img.paste(_qr(qr_url, qr_px), (px0 + quiet, py0 + quiet))
    # QR USTIDA: yorliq va TAKLIF KODI. Kod ko'rinib turishi kerak —
    # QR faqat kamerasi ochiq odam uchun; kodni esa skrinshotdan ko'chirib
    # olish yoki og'zaki aytish mumkin.
    if qr_code:
        f_code = _f(34, bold=True)
        f_cap = _f(23)
        right = px0 + panel
        if qr_caption:
            _tracked(d, (right - _tracked_width(d, qr_caption, f_cap, 2.4), py0 - 78),
                     qr_caption, f_cap, MUTED, spacing=2.4)
        _tracked(d, (right - _tracked_width(d, qr_code, f_code, 3.0), py0 - 46),
                 qr_code, f_code, TXT, spacing=3.0)
    elif qr_caption:
        f_cap = _f(25)
        d.text((px0 + panel - d.textlength(qr_caption, font=f_cap), py0 - 38),
               qr_caption, font=f_cap, fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────────────────────
# 301: OCHIQ pozitsiya ulashish kartasi — ilovaning yangi uslubida (qora fon,
# kulrang tuman, muzli shisha panellar, lime urg'u), shamli grafik bilan.
# Yopilgan savdo kartasi (`pnl_card`) o'zgarmaydi.
# ─────────────────────────────────────────────────────────────────────────────
LIME = "#C2F23A"
RED = "#FF5C5C"
OW, OH = 1080, 1420


def _rgb(c: str) -> tuple:
    return Image.new("RGB", (1, 1), c).getpixel((0, 0))


def _blob(img, box, color, alpha, blur):
    from PIL import ImageFilter
    k = 4
    layer = Image.new("RGBA", (img.width // k, img.height // k), (0, 0, 0, 0))
    r, g, b = _rgb(color)
    ImageDraw.Draw(layer).ellipse(tuple(v // k for v in box), fill=(r, g, b, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(blur)).resize(img.size, Image.LANCZOS)
    img.alpha_composite(layer)


def _glass(img, box, radius=36, fill=14, edge=40):
    """Muzli shisha panel: oq shaffof to'ldirish, ingichka hoshiya, yuqorida yorqin chiziq."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius=radius, fill=(255, 255, 255, fill), outline=(255, 255, 255, edge), width=2)
    x0, y0, x1, _ = box
    d.line((x0 + radius, y0 + 1, x1 - radius, y0 + 1), fill=(255, 255, 255, 80), width=2)
    img.alpha_composite(layer)


def _chip(img, xy, text, font, fg, bg, pad=(18, 9)):
    """Yumaloq chip; `bg` RGBA bo'lishi mumkin — alohida qatlamda chiziladi (shaffoflik saqlanadi)."""
    x, y = xy
    d0 = ImageDraw.Draw(img)
    w = d0.textlength(text, font=font)
    bb = d0.textbbox((0, 0), text, font=font)
    h = bb[3] - bb[1]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((x, y, x + w + pad[0] * 2, y + h + pad[1] * 2 + 4),
                                            radius=(h + pad[1] * 2) // 2, fill=bg)
    img.alpha_composite(layer)
    ImageDraw.Draw(img).text((x + pad[0], y + pad[1] - bb[1] + 2), text, font=font, fill=fg)
    return x + w + pad[0] * 2


def open_card(*, symbol: str, side: str, entry: float, price: float, pnl_pct: float,
              money: float | None, leverage: int | None, sl: float | None, tp: float | None,
              candles: list, tf: str | None, username: str | None, ws_name: str,
              logo: bytes | None, qr_url: str, qr_code: str | None, sig_id: int | None,
              when: datetime, lang: str | None = None, bot_logo: bytes | None = None) -> io.BytesIO:
    """Ochiq (yopilmagan) pozitsiya kartasi: Unrealized PnL (ROI), grafik, kirish/joriy/SL/TP, QR."""
    acc = LIME if pnl_pct >= 0 else RED
    img = Image.new("RGBA", (OW, OH), "#050506")
    _blob(img, (-260, -320, 760, 520), "#C8CCD6", 46, 30)
    _blob(img, (520, 640, 1500, 1500), acc, 34, 34)
    _blob(img, (-300, 900, 500, 1600), "#B4B9AE", 22, 30)
    d = ImageDraw.Draw(img, "RGBA")
    P = 64

    # Tepa: brend + "OCHIQ POZITSIYA" chipi
    bx = P
    if bot_logo:
        bl = _circle_avatar(bot_logo, 60)
        if bl is not None:
            img.alpha_composite(bl, (P, P - 14))
            d = ImageDraw.Draw(img, "RGBA")
            bx = P + 60 + 18
    _tracked(d, (bx, P), "TRADE CONTROLLER", _f(24, bold=True), TXT, spacing=4.0)
    lab = i18n.t("card.open", lang)
    fch = _f(21, bold=True)
    w = d.textlength("●  " + lab, font=fch) + 36
    _chip(img, (OW - P - w, P - 6), "●  " + lab, fch, "#050506", acc)

    # Juftlik + chiplar
    y = 150
    fs = _f(58, bold=True)
    d.text((P, y), symbol, font=fs, fill=TXT)
    x = P + d.textlength(symbol, font=fs) + 24
    fc = _f(22, bold=True)
    sc = LIME if side == "LONG" else RED
    sr, sg_, sb = _rgb(sc)
    x = _chip(img, (x, y + 12), side, fc, sc, (sr, sg_, sb, 46)) + 12
    kind = f"{leverage}X" if leverage and leverage > 1 else "SPOT"
    x = _chip(img, (x, y + 12), kind, fc, TXT, (255, 255, 255, 30)) + 12
    if tf:
        _chip(img, (x, y + 12), tf, fc, MUTED, (255, 255, 255, 20))
    d = ImageDraw.Draw(img, "RGBA")

    # Unrealized PnL
    y = 256
    _tracked(d, (P, y), i18n.t("card.upnl", lang), _f(22, bold=True), MUTED, spacing=2.4)
    pct = f"{pnl_pct:+.2f}%"
    size = 124
    fb = _f(size, bold=True)
    while d.textlength(pct, font=fb) > OW - 2 * P and size > 80:
        size -= 6
        fb = _f(size, bold=True)
    d.text((P, y + 36), pct, font=fb, fill=acc)
    if money is not None:
        m = f"{'+' if money >= 0 else '−'}${abs(money):,.2f}"
        d.text((P + 4, y + 36 + size + 14), m, font=_f(34, bold=True), fill=TXT)

    # Grafik paneli
    gx0, gy0, gx1, gy1 = P, 560, OW - P, 930
    _glass(img, (gx0, gy0, gx1, gy1), radius=34, fill=10, edge=34)
    d = ImageDraw.Draw(img, "RGBA")
    cs = [c for c in (candles or []) if c and len(c) >= 5][-64:]
    fl = _f(19, bold=True)
    lvl = [(v, c, lb) for v, c, lb in ((tp, LIME, "TP"), (sl, RED, "SL"), (entry, "#D8D8DC", "IN")) if v]
    lw = max([d.textlength(f"{lb} {_fmt_price(v)}", font=fl) for v, _c, lb in lvl] or [0]) + 16
    ix0, iy0, ix1, iy1 = gx0 + 26, gy0 + 28, gx1 - 22 - lw - 10, gy1 - 28
    if cs:
        levels = [entry, price] + [v for v in (sl, tp) if v]
        lo = min(min(c[3] for c in cs), *levels)
        hi = max(max(c[2] for c in cs), *levels)
        pad = (hi - lo) * 0.06 or hi * 0.01
        lo, hi = lo - pad, hi + pad
        Y = lambda v: iy1 - (v - lo) / (hi - lo) * (iy1 - iy0)
        n = len(cs)
        bw = (ix1 - ix0) / n
        for k, c in enumerate(cs):
            o, h_, l_, cl = c[1], c[2], c[3], c[4]
            col = LIME if cl >= o else RED
            cx = ix0 + (k + .5) * bw
            d.line((cx, Y(h_), cx, Y(l_)), fill=col, width=2)
            top, bot = min(Y(o), Y(cl)), max(Y(o), Y(cl))
            d.rectangle((cx - bw * .32, top, cx + bw * .32, max(bot, top + 2)), fill=col)

        # Chiziqlar
        for v, col, lb in lvl:
            yy = Y(v)
            if lb == "IN":
                xx = ix0
                while xx < ix1:
                    d.line((xx, yy, min(xx + 14, ix1), yy), fill=col, width=2)
                    xx += 24
            else:
                d.line((ix0, yy, ix1, yy), fill=col, width=2)
        # Yorliqlar: panel ichida, bir-biriga tegmasin
        tags = sorted([[Y(v), v, col, lb] for v, col, lb in lvl], key=lambda t: t[0])
        for k in range(1, len(tags)):
            tags[k][0] = max(tags[k][0], tags[k - 1][0] + 34)
        over = tags[-1][0] + 17 - (gy1 - 8) if tags else 0
        if over > 0:
            for t in tags:
                t[0] -= over
        lx = ix1 + 10
        for yy, v, col, lb in tags:
            t = f"{lb} {_fmt_price(v)}"
            d.rounded_rectangle((lx, yy - 15, lx + lw, yy + 15), radius=9, fill="#0A0A0C", outline=col, width=2)
            d.text((lx + 8, yy - 11), t, font=fl, fill=col)
        py = Y(price)
        d.ellipse((ix1 - 9, py - 9, ix1 + 9, py + 9), fill=acc)
    # Narxlar qatori
    y = 966
    cols = [(i18n.t("card.entry", lang), _fmt_price(entry), TXT),
            (i18n.t("card.mark", lang), _fmt_price(price), TXT),
            ("SL", _fmt_price(sl) if sl else "—", RED if sl else MUTED),
            ("TP", _fmt_price(tp) if tp else "—", LIME if tp else MUTED)]
    cw = (OW - 2 * P) / 4
    for k, (lb, v, col) in enumerate(cols):
        x = P + k * cw
        d.text((x, y), lb, font=_f(21), fill=MUTED)
        d.text((x, y + 30), v, font=_f(28, bold=True), fill=col)

    # Pastki qism: avatar + muallif + QR
    d.line((P, OH - 236, OW - P - 300, OH - 236), fill="#26262B", width=2)
    av_px = 76
    av = _circle_avatar(logo, av_px) if logo else None
    if av is None:
        av = _letter_avatar((ws_name or "?").strip()[:1].upper(), av_px)
    ay = OH - 190
    img.alpha_composite(av, (P, ay))
    d = ImageDraw.Draw(img, "RGBA")
    who = f"@{username}" if username else (ws_name or "Trade Controller")
    fw = _f(28, bold=True)
    tx = P + av_px + 22
    while d.textlength(who, font=fw) > OW - P - 300 - tx and len(who) > 4:
        who = who[:-2] + "…"
    d.text((tx, ay + 8), who, font=fw, fill=TXT)
    sub = f"{ws_name} · {when:%d.%m.%Y %H:%M}" if ws_name and username else f"{when:%d.%m.%Y %H:%M}"
    if sig_id is not None:
        sub = f"#{sig_id} · " + sub
    while d.textlength(sub, font=_f(21)) > OW - P - 300 - tx and len(sub) > 6:
        sub = sub[:-2] + "…"
    d.text((tx, ay + 46), sub, font=_f(21), fill=FAINT)
    qr_px, quiet = 150, 14
    panel = qr_px + quiet * 2
    px0, py0 = OW - P - panel, OH - P - panel
    d.rounded_rectangle((px0, py0, px0 + panel, py0 + panel), radius=18, fill="white")
    img.paste(_qr(qr_url, qr_px), (px0 + quiet, py0 + quiet))
    if qr_code:
        fcode, fcap = _f(28, bold=True), _f(19)
        cap = i18n.t("card.ref_code", lang)
        right = px0 + panel
        _tracked(d, (right - _tracked_width(d, cap, fcap, 2.4), py0 - 76), cap, fcap, MUTED, spacing=2.4)
        _tracked(d, (right - _tracked_width(d, qr_code, fcode, 3.0), py0 - 44), qr_code, fcode, TXT, spacing=3.0)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
