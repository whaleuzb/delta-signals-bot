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

import matplotlib
import qrcode
from PIL import Image, ImageDraw, ImageFont

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
_FONT_DIR = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
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
             market: str = "crypto", qr_caption: str = "") -> io.BytesIO:
    """Ulashish kartasini chizadi va PNG bayt oqimini qaytaradi."""
    acc = PROFIT if pnl_pct >= 0 else LOSS

    img = Image.new("RGBA", (W, H), BG)
    _glow(img, acc)
    d = ImageDraw.Draw(img)

    # ── Tepa: brend va shamlar bezagi ───────────────────────────────────
    _tracked(d, (PAD, PAD), "TRADE CONTROLLER", _f(30, bold=True), TXT, spacing=4.4)
    d.text((PAD, PAD + 44), "Savdo jurnali", font=_f(24), fill=FAINT)

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
    _tracked(d, (PAD, y), "YOPILGAN SAVDO", _f(27, bold=True), MUTED, spacing=3.6)

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
    # Yelka (25X) O'RNIDA — bu spot savdo, yelka yo'q.
    d.text((x, y + 8), "SPOT" if market == "crypto" else market.upper(),
           font=f_meta, fill=TXT)

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
    rows = [("Kirish narxi", _fmt_price(entry)),
            ("Chiqish narxi", _fmt_price(exit_price))]
    if r_multiple is not None:
        rows.append(("Natija (R)", f"{float(r_multiple):+.2f}R"))
    f_k, f_v = _f(31), _f(35, bold=True)
    ky = 668
    label_w = max(_tracked_width(d, k, f_k) for k, _ in rows)
    for k, v in rows:
        d.text((PAD, ky), k, font=f_k, fill=MUTED)
        d.text((PAD + label_w + 46, ky - 3), v, font=f_v, fill=TXT)
        ky += 54

    # ── Pastki chiziq ───────────────────────────────────────────────────
    d.line((PAD, H - 232, W - PAD, H - 232), fill=LINE, width=2)

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
    # QR ustidagi yozuv — skanerlaydigan odam QAYERGA borishini bilsin.
    # Bo'sh bo'lsa umuman chizilmaydi.
    if qr_caption:
        f_cap = _f(25)
        d.text((px0 + panel - d.textlength(qr_caption, font=f_cap), py0 - 38),
               qr_caption, font=f_cap, fill=MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
