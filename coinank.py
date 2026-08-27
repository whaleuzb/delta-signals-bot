"""CoinAnk — Liquidation Heatmap (bepul, ro'yxatdan o'tish shart emas).

Qidiruv tarixi: CoinGlass'ning rasmiy narx-klaster heatmap API'si
Professional tarifdan ($699/oy) boshlanadi (tasdiqlangan). Muqobil
sifatida Hyblock Capital sinaldi — u ham amalda pullik bo'lib chiqdi
(foydalanuvchi o'zi tekshirdi). Foydalanuvchi keyin brauzer DevTools
(Network) orqali CoinAnk'ning (coinank.com) BEPUL veb-sahifasi
ortidagi ichki JSON so'rovini topdi va Python orqali to'g'ridan-to'g'ri
(brauzersiz) ishlashini TASDIQLADI — hatto login/token'siz ("guest")
holatda ham 200 OK qaytaradi.

MUHIM: bu RASMIY, hujjatlashtirilgan ochiq API EMAS — frontend'ning
o'z ichki chaqiruvi. `coinank-apikey` — sayt darajasidagi STATIK
"site key" (shaxsiy hisob kaliti emas), istalgan payt o'zgarishi yoki
bloklanishi mumkin. Shu sabab qattiq kodga yozilmaydi — `COINANK_API_KEY`
Railway o'zgaruvchisi sifatida saqlanadi, kerak bo'lsa DevTools orqali
qayta olib, qayta deploy qilmasdan yangilash mumkin. Bo'sh bo'lsa butun
modul jimgina o'chadi — likvidatsiya posti oddiy shamli grafikka
(`chart.news_chart()`) qaytadi.

Javob strukturasi — `data.liqHeatMap`: `data` (`[xIndex, yIndex, hajm]`
uchliklar ro'yxati — ~42 ming nuqta), `chartTimeArray` (X — vaqt
belgilari), `priceArray` (Y — narx darajalari). Bu yerda
`chart.liquidation_heatmap_chart()` kutgan umumiy `{startingPrice,
timestamp, size}` shakliga o'giriladi — chart.py hyblock/coinank/
boshqa manbadan farqni bilishi shart emas."""
import logging

import httpx

import config

log = logging.getLogger("coinank")

URL = "https://api.coinank.com/api/liqMap/getLiqHeatMap"


def enabled() -> bool:
    return bool(config.COINANK_API_KEY)


async def liquidation_heatmap(symbol: str, exchange: str = "Binance",
                              interval: str | None = None) -> list[dict] | None:
    """`symbol` — Binance/MEXC uslubidagi juftlik (masalan "BTCUSDT").
    Muvaffaqiyatsiz yoki modul o'chirilgan bo'lsa `None` — chaqiruvchi
    shunda oddiy shamli grafikka qaytadi. Natija: `[{startingPrice,
    timestamp, size}, ...]` (`endingPrice`/`side` kerak emas —
    `chart.liquidation_heatmap_chart()` faqat shu uchtasini o'qiydi)."""
    if not enabled():
        return None
    interval = interval or config.COINANK_INTERVAL
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(URL, params={
                "exchangeName": exchange, "symbol": symbol, "interval": interval,
            }, headers={
                "Accept": "application/json, text/plain, */*",
                "client": "web", "web-version": "102",
                "coinank-apikey": config.COINANK_API_KEY,
                "token": "",
                "Origin": "https://coinank.com",
                "Referer": "https://coinank.com/",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"),
            })
            r.raise_for_status()
            payload = r.json()
    except Exception:
        log.warning("CoinAnk heatmap olinmadi (%s)", symbol, exc_info=True)
        return None

    if not payload.get("success"):
        log.warning("CoinAnk heatmap muvaffaqiyatsiz javob (%s): %r", symbol, payload)
        return None

    heatmap = ((payload.get("data") or {}).get("liqHeatMap")) or {}
    points = heatmap.get("data") or []
    time_arr = heatmap.get("chartTimeArray") or []
    price_arr = heatmap.get("priceArray") or []

    buckets: list[dict] = []
    for point in points:
        try:
            x_idx, y_idx, size = int(point[0]), int(point[1]), float(point[2])
        except (TypeError, ValueError, IndexError):
            continue
        if size <= 0 or x_idx >= len(time_arr) or y_idx >= len(price_arr):
            continue
        try:
            ts = int(float(time_arr[x_idx]))
            price = float(price_arr[y_idx])
        except (TypeError, ValueError):
            continue
        buckets.append({"timestamp": ts, "startingPrice": price, "size": size})
    return buckets
