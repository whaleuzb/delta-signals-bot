"""matplotlib'ni faqat birinchi grafik chizilganda yuklash.

Bot ishga tushganda matplotlib + numpy ~50 MB xotira oladi, garchi grafik faqat
ba'zi buyruqlarda kerak bo'lsa ham. Shu proksilar orqali modul birinchi murojaatda
import qilinadi (Agg backend va text.parse_math=False — avvalgidek)."""
import importlib


class _Lazy:
    def __init__(self, name: str):
        self._name, self._mod = name, None

    def _load(self):
        if self._mod is None:
            import matplotlib
            matplotlib.use("Agg")
            # "$\x$" kabi nom matplotlib'ni ParseFatalException bilan yiqitardi
            matplotlib.rcParams["text.parse_math"] = False
            self._mod = importlib.import_module(self._name)
        return self._mod

    def __getattr__(self, attr):
        return getattr(self._load(), attr)


plt = _Lazy("matplotlib.pyplot")
ticker = _Lazy("matplotlib.ticker")
patches = _Lazy("matplotlib.patches")
lines = _Lazy("matplotlib.lines")



# 441: xotirani OS'ga qaytarish. Grafik/karta chizilgandan keyin Python bo'shatgan xotira glibc'da
# qolib, jarayon RSS'i (Railway xotira hisobi) cho'qqida qolardi. gc + malloc_trim(0), 15 s da ko'pi bilan bir marta.
_TRIM = [0.0]


def memtrim(force: bool = False) -> None:
    import time
    now = time.monotonic()
    if not force and now - _TRIM[0] < 15:
        return
    _TRIM[0] = now
    try:
        import gc
        gc.collect()
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
