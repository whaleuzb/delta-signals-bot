"""Rasm captionidan yoki matndan signalni o'qish.

Qo'llab-quvvatlanadigan ko'rinishlar (registr ahamiyatsiz):
    BTCUSDT LONG 65000 tp 67000 68500 sl 64000
    BTC/USDT
    Entry: 65 000
    TP1 67000  TP2 68500
    Stop: 64000

Matnda "market" yoki "bozor" so'zi bo'lsa — entry_mode='market' (signal darhol
ACTIVE, narxni kutmaydi). Bo'lmasa standart — entry_mode='limit' (hozirgidek,
narx kirish darajasiga tegguncha kutadi).
"""
import re

# Ikkita variant kerak:
#   NUM  — "65 000" kabi bo'sh joyli minglikni tushunadi (bitta qiymat kutilgan joyda)
#   NUMS — bo'sh joyni ajratgich deb biladi, ya'ni "172 168" = ikkita raqam
#          (bir nechta qiymat ketma-ket kelishi mumkin bo'lgan joyda)
NUM = r"[-+]?\d+(?:[ ,]\d{3}(?!\d))*(?:\.\d+)?"
NUMS = r"[-+]?\d+(?:,\d{3}(?!\d))*(?:\.\d+)?"


def _f(raw: str) -> float:
    return float(raw.replace(" ", "").replace(",", ""))


def _nums(text: str) -> list[float]:
    """Ketma-ket kelgan raqamlarni ajratib oladi (bo'sh joy = ajratgich)."""
    out = []
    for m in re.finditer(NUMS, text):
        try:
            out.append(_f(m.group()))
        except ValueError:
            pass
    return out


# Juftlik bo'la olmaydigan so'zlar — nomzodlar ro'yxatini toza saqlaydi.
# To'liq bo'lishi SHART EMAS: ro'yxatga tushmagan begona so'z baribir birjada
# topilmaydi va chaqiruvchi keyingi nomzodga o'tadi.
_NOT_SYMBOL = {
    "long", "short", "buy", "sell", "entry", "enter", "tp", "sl", "stop",
    "stoploss", "target", "take", "profit", "kirish", "chiqish", "maqsad",
    "signal", "spot", "market", "bozor", "limit", "oddiy", "narx", "price",
    "zarar", "yangi", "bugun", "hozir", "va", "ва",
}

# Juftlik: 2-12 harf, ixtiyoriy ajratgich + kotirovka (USDT/USD/PERP),
# ixtiyoriy ".P". Ajratgich va kotirovka BIRGA ixtiyoriy — shu sabab
# "btc long" da faqat "btc" olinadi, bo'sh joy yutib yuborilmaydi.
_SYM_RE = re.compile(r"\b([A-Za-z]{2,12}(?:[/\-_ ]?(?:USDT|USD|PERP))?(?:\.P)?)\b", re.I)

MAX_SYMBOL_CANDIDATES = 6


def symbol_candidates(text: str) -> list[str]:
    """Matndagi juftlikka o'xshash so'zlar — matnda uchrash tartibida.

    Bittasini tanlab olmaydi: qaysi biri haqiqiy juftlik ekanini FAQAT birja
    biladi. Avval faqat birinchi so'z olinardi va "Yangi signal: btc long..."
    kabi oddiy xabarda juftlik "Yangi" bo'lib chiqardi."""
    out: list[str] = []
    for m in _SYM_RE.finditer(text or ""):
        w = m.group(1).strip()
        if w.lower().replace(" ", "") in _NOT_SYMBOL or w.lower() in _NOT_SYMBOL:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= MAX_SYMBOL_CANDIDATES:
            break
    return out


def parse(text: str) -> dict | None:
    """Muvaffaqiyatli bo'lsa {symbol, symbols, side, entry, sl, tps} qaytaradi.

    `symbols` — juftlik nomzodlari (tartibda). Chaqiruvchi ularni birjada
    birma-bir tekshiradi; `symbol` shunchaki birinchisi."""
    if not text:
        return None
    t = text.replace("\u00a0", " ")
    low = t.lower()

    # --- tomon ---
    if re.search(r"\b(short|sell|sotish)\b", low):
        side = "SHORT"
    else:
        side = "LONG"

    # --- kirish rejimi: market (darhol ACTIVE) yoki limit (standart — narxni kutadi) ---
    entry_mode = "market" if re.search(r"\b(market|bozor)\b", low) else "limit"

    # --- juftlik ---
    cands = symbol_candidates(t)
    if not cands:
        return None
    symbol = cands[0]

    # --- SL ---
    sl = None
    m = re.search(r"(?:sl|stop\s*loss|stop|stoploss|zarar)\D{0,6}(" + NUM + ")", low)
    if m:
        sl = _f(m.group(1))

    # --- Entry ---
    entry = None
    m = re.search(r"(?:entry|enter|kirish|buy|narx|price)\D{0,6}(" + NUM + ")", low)
    if m:
        entry = _f(m.group(1))

    # --- TP lar ---
    # 1-usul: indeksli yorliqlar — "TP1: 67 000", "TP2 68500". Indeks tp ga yopishgan
    # bo'lishi shart, shuning uchun bu yerda bitta qiymat kutiladi (bo'sh joyli minglik ok).
    tps: list[float] = [
        _f(m.group(1))
        for m in re.finditer(r"(?:tp\d|take\s*profit\s*\d)\D{0,6}(" + NUM + ")", low)
    ]
    # 2-usul: indekssiz — "tp 67000 68500" yoki "maqsad 0.92 0.98"
    if not tps:
        m = re.search(
            r"(?:tp|take\s*profit|target|maqsad)\s*[:\-=]?\s*((?:" + NUMS + r"[\s,]*)+)", low
        )
        if m:
            tps = _nums(m.group(1))

    # --- kalit so'zsiz qisqa format: SYMBOL SIDE e tp... sl ---
    if entry is None or sl is None or not tps:
        nums = _nums(re.sub(r"[A-Za-z]+", " ", t))
        if entry is None and sl is None and not tps and len(nums) >= 3:
            entry, *mid, sl = nums[0], *nums[1:-1], nums[-1]
            tps = mid

    if entry is None or sl is None or not tps:
        return None

    tps = sorted(set(tps), reverse=(side == "SHORT"))
    return {"symbol": symbol, "symbols": cands, "side": side, "entry": entry,
            "sl": sl, "tps": tps, "entry_mode": entry_mode}


def parse_tp_sl(text: str) -> dict | None:
    """Faqat TP/SL matnini o'qiydi — symbol/side/entry ALLAQACHON ma'lum
    bo'lgan holatda ishlatiladi (limit signal to'lib, TP/SL SO'RALGANDA,
    `bot.py`ning AWAITING_TPSL oqimida). `parse()`dagi bilan bir xil
    regex andozalari (SL/TP qismi) qayta ishlatiladi — faqat symbol/entry
    qidirilmaydi."""
    if not text:
        return None
    low = text.replace(" ", " ").lower()

    sl = None
    m = re.search(r"(?:sl|stop\s*loss|stop|stoploss|zarar)\D{0,6}(" + NUM + ")", low)
    if m:
        sl = _f(m.group(1))

    tps: list[float] = [
        _f(m.group(1))
        for m in re.finditer(r"(?:tp\d|take\s*profit\s*\d)\D{0,6}(" + NUM + ")", low)
    ]
    if not tps:
        m = re.search(
            r"(?:tp|take\s*profit|target|maqsad)\s*[:\-=]?\s*((?:" + NUMS + r"[\s,]*)+)", low
        )
        if m:
            tps = _nums(m.group(1))

    # Kalit so'zsiz qisqa format: "67000 68500 64000" — oxirgisi SL,
    # qolganlari TP (`parse()`dagi qisqa format bilan bir xil andoza).
    if sl is None or not tps:
        nums = _nums(re.sub(r"[A-Za-z]+", " ", text))
        if sl is None and not tps and len(nums) >= 2:
            *tps, sl = nums

    if sl is None or not tps:
        return None
    return {"sl": sl, "tps": tps}


def validate(d: dict) -> str | None:
    """Mantiqiy xatolarni tutadi. Xato bo'lsa matn qaytaradi."""
    e, sl, tps = d["entry"], d["sl"], d["tps"]
    if e <= 0 or sl <= 0 or any(t <= 0 for t in tps):
        return "Narxlar musbat bo'lishi kerak."
    if d["side"] == "LONG":
        if sl >= e:
            return f"LONG uchun SL ({sl}) entry ({e}) dan past bo'lishi kerak."
        if any(t <= e for t in tps):
            return f"LONG uchun barcha TP entry ({e}) dan yuqori bo'lishi kerak."
    else:
        if sl <= e:
            return f"SHORT uchun SL ({sl}) entry ({e}) dan yuqori bo'lishi kerak."
        if any(t >= e for t in tps):
            return f"SHORT uchun barcha TP entry ({e}) dan past bo'lishi kerak."
    risk = abs(e - sl) / e * 100
    if risk > 25:
        return f"Risk juda katta ({risk:.1f}%) — darajalar to'g'ri o'qildimi?"
    return None
