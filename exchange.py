"""MEXC Spot public API. API key kerak emas.

Binance Futures (fapi.binance.com) Railway serverining hududini 451 bilan
bloklagani uchun MEXC'ga o'tildi. MEXC'ning /api/v3 spot API'si Binance
spot API bilan deyarli bir xil shaklda javob beradi (klines, exchangeInfo,
ticker/price) — shu sabab bu fayl tuzilishi saqlanib qoldi.
"""
import time
import logging
from dataclasses import dataclass

import httpx
import config

log = logging.getLogger(__name__)
_client = httpx.AsyncClient(base_url=config.EXCHANGE_BASE, timeout=15)
# Faqat `volume_ticker_24hr()` uchun — Binance Futures (fapi.binance.com)
# ilgari Railway hududini 451 bilan bloklagan edi (yuqoridagi izohga
# qarang), lekin bu SPOT API (api.binance.com), boshqa domen — foydalanuvchi
# so'rovi bilan sinaladi ("Binance'da pul ko'p aylanadi" — savdo hajmi
# portlashini Binance ma'lumotidan aniqlash MEXC'dan ancha aniqroq).
_binance_client = httpx.AsyncClient(base_url="https://api.binance.com", timeout=15)

_symbols: set[str] = set()
_symbols_ts: float = 0.0


@dataclass
class Candle:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    close_ms: int
    volume: float = 0.0


async def valid_symbols() -> set[str]:
    """exchangeInfo 1 soatga keshlanadi."""
    global _symbols, _symbols_ts
    if _symbols and time.time() - _symbols_ts < 3600:
        return _symbols
    r = await _client.get("/api/v3/exchangeInfo")
    r.raise_for_status()
    # status: MEXC "1" qaytaradi, lekin hujjatlarda "ENABLED" ham uchraydi —
    # ikkalasini ham qabul qilamiz. Agar bir kun yozilishi yana o'zgarsa,
    # butun ro'yxat bo'shab qolib BARCHA signallar rad etilishi mumkin edi;
    # asosiy shart baribir isSpotTradingAllowed.
    _symbols = {
        s["symbol"] for s in r.json()["symbols"]
        if s.get("isSpotTradingAllowed")
        and str(s.get("status", "")).upper() in ("1", "ENABLED", "TRADING")
    }
    _symbols_ts = time.time()
    return _symbols


def normalize(raw: str) -> str:
    """btc, Btc, BTC/USDT, "BTC USDT", BTC_USDT, BTCUSDT.P -> BTCUSDT

    Ajratgichlar (bo'sh joy, _, /, -, :) tashlanadi — odamlar juftlikni
    juda xilma-xil yozadi va ularning hammasi bir xil narsani bildiradi."""
    s = raw.upper().strip()
    for ch in ("/", "-", ":", "_", " ", "\t", " "):
        s = s.replace(ch, "")
    for suf in (".P", "PERP"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if not s.endswith(config.QUOTE):
        s += config.QUOTE
    return s


async def resolve(raw: str) -> str | None:
    s = normalize(raw)
    return s if s in await valid_symbols() else None


# Ichki timeframe kodi -> MEXC interval nomi. MEXC 1 soatni "60m" deb ataydi.
_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
              "1h": "60m", "4h": "4h", "1d": "1d"}
# Sham davomiyligi (ms) — close_ms ni hisoblash uchun.
_TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
          "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


async def klines(symbol: str, start_ms: int, limit: int = 500,
                  tf: str = "1m", end_ms: int | None = None) -> list[Candle]:
    """Shamlar. Standart 1m — KUZATUV (tracker.py) aynan shuni ishlatadi va
    o'zgartirilmasligi kerak: 1m'dan yirikroq shamda TP/SL teginishi sham
    ichida yashirinib qolishi mumkin. tf faqat KO'RSATISH (grafik) uchun.

    end_ms — oynaning oxiri. MUHIM: MEXC faqat `startTime` berilganda
    oraliqning BOSHIDAN emas, OXIRIDAN `limit` ta sham qaytaradi (Binance'dan
    farqi shu). Ya'ni o'tmishdagi savdo uchun so'ralgan oyna o'rniga eng
    so'nggi shamlar kelib qolardi va grafik chizilmasdi. `endTime` berilsa
    oyna aniq cheklanadi. Kuzatuv buni sezmaydi — u doim "hozirgacha"
    o'qiydi, shuning uchun end_ms'siz ham to'g'ri ishlaydi."""
    interval = _INTERVALS.get(tf, "1m")
    dur = _TF_MS.get(tf, 60_000)
    params = {"symbol": symbol, "interval": interval, "startTime": start_ms,
              "limit": limit}
    if end_ms is not None:
        params["endTime"] = end_ms
    r = await _client.get("/api/v3/klines", params=params)
    if r.status_code == 429:
        log.warning("MEXC rate limit — kutamiz")
        return []
    if 400 <= r.status_code < 500:
        # Odatda juftlik ro'yxatdan chiqarilgan yoki nomi o'zgargan. Bu xato
        # emas, ma'lumot yo'q — traceback ko'tarish o'rniga bo'sh ro'yxat
        # qaytaramiz. Chaqiruvchilar buni allaqachon to'g'ri ishlatadi.
        log.warning("MEXC %s: %s %s uchun ma'lumot yo'q", r.status_code, symbol, interval)
        return []
    r.raise_for_status()
    out = []
    for k in r.json():
        open_ms = int(k[0])
        # k[5] — sham hajmi (baza aktivda, masalan BTC, USDT'da emas). Hajm
        # profili (Anchored Volume Profile) uchun ishlatiladi — narx emas,
        # shuning uchun MEXC/Binance formatidagi joylashuvi barqaror.
        volume = float(k[5]) if len(k) > 5 else 0.0
        out.append(Candle(open_ms, float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                          open_ms + dur - 1, volume))
    return out


_PRICE_TTL = 5.0
_price_cache: dict[str, tuple[float, float]] = {}


async def last_price(symbol: str, fresh: bool = False) -> float | None:
    """Qisqa muddatli (5 s) kesh. Sabab: /stats, /symbols, /open kabi buyruqlar
    HAR ochiq signal uchun alohida so'rov yuboradi — 20 ta ochiq signal bo'lsa
    bitta tugma bosilishi 20 ta so'rov demak. Foydalanuvchi buyruqni tez-tez
    bossa MEXC IP bo'yicha rate-limit qo'yadi va bu kuzatuv siklini
    (poll_job → klines) ham buzadi. Kesh shu portlashni bitta so'rovga
    yig'adi, ko'rsatiladigan narx esa eng ko'pi bilan 5 s eskiradi.

    fresh=True — keshni chetlab o'tish; qo'lda yopishda (tracker.close_now)
    ishlatiladi, chunki u yerda narx savdoning YAKUNIY natijasiga yoziladi."""
    if not fresh:
        hit = _price_cache.get(symbol)
        if hit and (time.monotonic() - hit[0]) < _PRICE_TTL:
            return hit[1]
    r = await _client.get("/api/v3/ticker/price", params={"symbol": symbol})
    if r.status_code != 200:
        return None
    price = float(r.json()["price"])
    _price_cache[symbol] = (time.monotonic(), price)
    return price


def _parse_ticker_24hr(data: list) -> dict[str, float]:
    """MEXC va Binance spot API'lari `/api/v3/ticker/24hr` uchun bir xil
    maydon nomlarini (`symbol`/`quoteVolume`) qaytaradi — shu sabab ikkalasi
    ham shu bitta funksiyadan foydalanadi."""
    out: dict[str, float] = {}
    for t in data:
        sym = t.get("symbol", "")
        if not sym.endswith(config.QUOTE):
            continue
        try:
            out[sym] = float(t["quoteVolume"])
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def ticker_24hr() -> dict[str, float]:
    """BARCHA USDT juftliklarining 24 soatlik savdo hajmi (USDT'da),
    BITTA so'rovda — MEXC'dan. Hajm portlashini kuzatish uchun — minglab
    juftlikning har biriga alohida so'rov yubormaslik kerak."""
    r = await _client.get("/api/v3/ticker/24hr")
    r.raise_for_status()
    return _parse_ticker_24hr(r.json())


async def volume_ticker_24hr() -> dict[str, float]:
    """Hajm portlashini kuzatish (`surge_scan_job`) uchun — imkon qadar
    Binance'dan (dunyodagi eng katta savdo hajmi — "pul qayerda ko'p
    aylanishi" shu yerda eng aniq ko'rinadi). Binance so'rovi
    muvaffaqiyatsiz bo'lsa (masalan Railway hududi 451 bilan bloklasa —
    Futures API'da bu ilgari tasdiqlangan, Spot API boshqa domen bo'lgani
    uchun alohida sinaladi) — MEXC'ga jimgina qaytadi, hech narsa
    to'xtamaydi."""
    try:
        r = await _binance_client.get("/api/v3/ticker/24hr")
        r.raise_for_status()
        return _parse_ticker_24hr(r.json())
    except Exception:
        log.warning("Binance hajm surati olinmadi, MEXC'ga qaytilmoqda", exc_info=True)
        return await ticker_24hr()


# --- Xarid/sotuv (Volume Delta) profili haqiqiy savdolardan ---
# Shamlarning umumiy hajmi (Candle.volume) xarid va sotuvni AJRATMAYDI —
# buning uchun har bir savdoning "agressor tomoni" kerak, bu faqat
# individual savdolar (`/aggTrades`) darajasida bor. MUHIM CHEKLOV:
# MEXC bir so'rovda MAKSIMUM 1000 ta savdo qaytaradi — likvid tangada
# 30 kun (foydalanuvchi avval so'ragan) MINGLAB so'rov (yuz minglab-
# millionlab savdo) talab qilardi, bu IMKONSIZ (MEXC IP tezlik
# chegarasiga zarba berib, botning boshqa qismlarini — narx kuzatuvi,
# signal skaneri — buzib qo'yardi). Shu sabab foydalanuvchi bilan
# kelishilgan holda oyna 48 SOATGA cheklandi (portlash nomzodlari
# odatda kichikroq hajmli tangalar bo'lgani uchun bu amalda ham
# yetarlicha tez). `max_trades` — qo'shimcha xavfsizlik devori.
AGG_TRADES_MAX = 60_000


async def _agg_trades(symbol: str, start_ms: int, end_ms: int) -> list[dict]:
    """`start_ms`/`end_ms` oralig'idagi BARCHA agregatsiyalangan
    savdolarni sahifalab (`startTime`ni oxirgi olingan savdodan keyingiga
    surib) oladi. Tarmoq xatosi, tezlik chegarasi (429) yoki
    `AGG_TRADES_MAX`ga yetish — QISMAN natija bilan JIMGINA to'xtaydi
    (chaqiruvchi buni "yetarli" deb hisoblaydi, xato emas)."""
    out: list[dict] = []
    cur_start = start_ms
    while cur_start < end_ms and len(out) < AGG_TRADES_MAX:
        try:
            r = await _client.get("/api/v3/aggTrades", params={
                "symbol": symbol, "startTime": cur_start, "endTime": end_ms,
                "limit": 1000,
            })
        except Exception:
            log.warning("MEXC aggTrades so'rovi xato (%s)", symbol, exc_info=True)
            break
        if r.status_code == 429:
            log.warning("MEXC rate limit (aggTrades, %s) — %d savdo bilan to'xtatildi",
                       symbol, len(out))
            break
        if 400 <= r.status_code < 500:
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        out.extend(batch)
        try:
            last_ts = int(batch[-1]["T"])
        except (KeyError, TypeError, ValueError):
            break
        if last_ts < cur_start:
            break   # kutilmagan/orqaga ketuvchi vaqt — cheksiz halqadan himoya
        cur_start = last_ts + 1
        if len(batch) < 1000:
            break   # oxirgi sahifa
    return out


async def volume_delta_profile(symbol: str, start_ms: int, end_ms: int,
                               lo: float, hi: float,
                               n_bins: int = 40) -> tuple[list[float], list[float]] | None:
    """Narx darajasi (`lo`..`hi`, `n_bins` ustunga bo'lingan) bo'yicha
    HAQIQIY xarid/sotuv hajmi profili. `aggTrades`ning `m` maydoni
    (`isBuyerMaker`) — Binance/MEXC standart konventsiyasi: `True` bo'lsa
    xaridor MARKET-MAKER, ya'ni bu savdoni SOTUVCHI boshlagan (bozor
    sotuvi); `False` bo'lsa xaridor boshlagan (bozor xaridi). Natija:
    `(vol_bins, delta_bins)` — ikkalasi ham `n_bins` uzunlikda,
    `delta_bins[i] = xarid_hajmi[i] - sotuv_hajmi[i]`. Savdo topilmasa
    yoki oraliq noto'g'ri (`hi <= lo`) bo'lsa `None`."""
    if hi <= lo:
        return None
    trades = await _agg_trades(symbol, start_ms, end_ms)
    if not trades:
        return None
    bin_size = (hi - lo) / n_bins
    vol_bins = [0.0] * n_bins
    delta_bins = [0.0] * n_bins
    for t in trades:
        try:
            price = float(t["p"])
            qty = float(t["q"])
            is_sell = bool(t["m"])
        except (KeyError, TypeError, ValueError):
            continue
        idx = int((price - lo) / bin_size)
        idx = max(0, min(n_bins - 1, idx))
        vol_bins[idx] += qty
        delta_bins[idx] += -qty if is_sell else qty
    if not any(vol_bins):
        return None
    return vol_bins, delta_bins


async def close() -> None:
    await _binance_client.aclose()
    await _client.aclose()
