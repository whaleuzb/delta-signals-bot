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
