"""Texnik indikatorlar — sof Python, tashqi kutubxonasiz.

Hozircha faqat MACD. Alohida modul qilinishining sababi: `chart.py` uni
CHIZISH uchun, `bot.py` esa SKANERLASH uchun ishlatadi — ikkalasida ham
takrorlanmasligi va bitta joyda sinaladigan bo'lishi kerak.
"""
from __future__ import annotations

FAST = 12
SLOW = 26
SIGNAL = 9


def ema(values: list[float], period: int) -> list[float]:
    """Eksponensial o'rtacha. Birinchi qiymat — oddiy o'rtacha (SMA), keyin
    standart EMA formulasi. Qaytadigan ro'yxat uzunligi kiruvchi bilan bir
    xil: `period`gacha bo'lgan joylar `None` emas, balki shu paytgacha
    hisoblangan SMA bilan to'ldiriladi (grafikda uzilish bo'lmasligi
    uchun) — MACD hisobida esa baribir birinchi `SLOW` ta qiymat
    ishonchsiz deb hisoblanadi va chaqiruvchi ularni tashlab yuboradi."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out: list[float] = []
    run = 0.0
    for i, v in enumerate(values):
        if i == 0:
            run = v
        elif i < period:
            # `period`gacha — oddiy yig'ilib boruvchi o'rtacha
            run = (run * i + v) / (i + 1)
        else:
            run = v * k + run * (1 - k)
        out.append(run)
    return out


def macd(closes: list[float], fast: int = FAST, slow: int = SLOW,
         signal: int = SIGNAL) -> tuple[list[float], list[float], list[float]]:
    """(macd_line, signal_line, histogram) — uchtasi ham `closes` bilan bir
    xil uzunlikda."""
    if len(closes) < 2:
        n = len(closes)
        return [0.0] * n, [0.0] * n, [0.0] * n
    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    line = [f - s for f, s in zip(fast_e, slow_e)]
    sig = ema(line, signal)
    hist = [m - s for m, s in zip(line, sig)]
    return line, sig, hist


def crossover(line: list[float], sig: list[float], idx: int = -1) -> str | None:
    """`idx` shamida MACD chizig'i signal chizig'ini kesib o'tdimi.

    "bullish" — MACD signaldan PASTDA edi, endi USTIDA (xarid tomon).
    "bearish" — teskarisi.
    Kesishmasa `None`.
    """
    n = len(line)
    if n < 2 or n != len(sig):
        return None
    i = idx if idx >= 0 else n + idx
    if i <= 0 or i >= n:
        return None
    prev_diff = line[i - 1] - sig[i - 1]
    cur_diff = line[i] - sig[i]
    if prev_diff <= 0 < cur_diff:
        return "bullish"
    if prev_diff >= 0 > cur_diff:
        return "bearish"
    return None


def is_strong(line: list[float], sig: list[float], hist: list[float],
              direction: str, idx: int = -1) -> bool:
    """Kesishma "kuchli" (super) sanaladimi.

    Ikkita shart birga:
      1) Kesishma NOL CHIZIG'INING to'g'ri tomonida sodir bo'ldi —
         bullish uchun MACD > 0 (ya'ni qisqa muddatli trend allaqachon
         uzoq muddatlidan tepada), bearish uchun MACD < 0. Bu "trend
         yo'nalishi bo'yicha" kesishma degani, teskari (qarshi trend)
         kesishmalardan ancha ishonchliroq.
      2) Gistogramma o'zgarishi sezilarli — oxirgi ustun o'zidan oldingi
         20 tasining o'rtacha MUTLAQ qiymatidan katta (ya'ni bu shunchaki
         nol atrofidagi shovqin emas).
    """
    n = len(line)
    i = idx if idx >= 0 else n + idx
    if i <= 0 or i >= n:
        return False
    if direction == "bullish" and line[i] <= 0:
        return False
    if direction == "bearish" and line[i] >= 0:
        return False
    window = [abs(h) for h in hist[max(0, i - 20):i]]
    if not window:
        return False
    avg = sum(window) / len(window)
    return abs(hist[i]) > avg
