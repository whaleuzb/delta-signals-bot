"""Kuzatuv dvigatelini sintetik shamlarda tekshirish. Baza va birja kerak emas.

Ishga tushirish:  python test_tracker.py
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "x")
os.environ.setdefault("DATABASE_URL", "postgres://x")

import config
import db
import exchange
import tracker

NOW = datetime.now(timezone.utc)
SAVED: dict = {}


def candle(i, o, h, l, c):
    ms = int((NOW + timedelta(minutes=i)).timestamp() * 1000)
    return exchange.Candle(ms, o, h, l, c, ms + 59_999)


def signal(**kw):
    d = {
        "id": 1, "workspace_id": 1, "market": "crypto", "symbol": "BTCUSDT", "side": "LONG",
        "entry": 100.0, "sl": 96.0, "sl_initial": 96.0, "tps": [104.0, 108.0, 112.0],
        "tp_hit": 0, "filled_pct": 0.0, "realized_pct": 0.0, "status": "PENDING",
        "created_at": NOW, "opened_at": None, "last_checked_ms": None,
        "ambiguous": False,
    }
    d.update(kw)
    return d


async def run(sig, candles, resolve_touch_order=None):
    exchange.klines = lambda *a, **k: _ret(candles)
    # Standart — hech qanday savdo ma'lumoti "topilmadi" (`None`), eski
    # konservativ taxminga qaytadi. Bu fayl tarmoq/baza SHART EMAS deb
    # va'da beradi (yuqoridagi docstring) — shu sabab haqiqiy tarmoqqa
    # chiqmasdan, chaqiruvchi kerak bo'lsa `resolve_touch_order` orqali
    # boshqa javob simulyatsiya qiladi.
    exchange.resolve_touch_order = lambda *a, **k: _ret(resolve_touch_order)
    db.save_progress = _save
    events = await tracker.process(sig)
    return SAVED.copy(), events


async def _ret(v):
    return v


async def _save(sig_id, f):
    SAVED.clear()
    SAVED.update(f)


def show(name, saved, events, expect_pnl=None):
    ev = " → ".join(
        e["type"] + (f"{e['n']}" if e["type"] == "TP" else "") for e in events
    ) or "—"
    pnl = saved.get("pnl_pct")
    ok = "  " if expect_pnl is None else ("✅" if abs((pnl or 0) - expect_pnl) < 0.01 else "❌")
    pnl_s = "—" if pnl is None else f"{pnl:+.2f}%"
    print(f"{ok} {name:<34} {saved['status']:<10} pnl={pnl_s:>8}"
          f"  R={saved.get('r_multiple')}  [{ev}]")


async def main():
    print(f"TP ulushlari: {tracker.allocation(3)}  |  BE ko'chirish: {config.MOVE_SL_TO_BE_AFTER_TP1}\n")

    # 1. Barcha TP lar ketma-ket
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),      # entry to'ldi
        candle(1, 100, 104.5, 100, 104),   # TP1
        candle(2, 104, 108.2, 103, 108),   # TP2
        candle(3, 108, 112.5, 107, 112),   # TP3
    ])
    # 0.5*4% + 0.3*8% + 0.2*12% = 2 + 2.4 + 2.4 = 6.8
    show("To'liq TP1+TP2+TP3", saved, ev, 6.8)

    # 2. To'g'ridan-to'g'ri stop
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 100.5, 95.5, 96),   # SL
    ])
    show("Toza stop loss", saved, ev, -4.0)

    # 3. TP1 dan keyin breakeven
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 104.5, 100, 104),   # TP1 -> stop 100 ga ko'chadi
        candle(2, 104, 105, 99.5, 100),    # BE ga qaytdi
    ])
    # 0.5*4% + 0.5*0% = 2.0
    show("TP1 keyin breakeven", saved, ev, 2.0)

    # 4. Bitta shamda TP ham SL ham — savdo ma'lumoti YO'Q (None) ->
    # eski konservativ (SL birinchi) taxminga qaytadi.
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 105, 95, 97),       # ikkalasi ham
    ])
    show("TP+SL bitta shamda (konserv.)", saved, ev, -4.0)
    assert saved["ambiguous"], "ambiguous bayrog'i qo'yilmadi"

    # 4b. Xuddi shu holat, lekin HAQIQIY savdolar TP OLDIN tegilganini
    # ko'rsatsa (OCO uslubidagi aniqlash) — endi TP1 hisoblanishi kerak
    # (faqat TP1, TP2/TP3 hali tegmagan — signal ACHIQ qoladi), konservativ
    # taxmin (SL birinchi) QO'LLANMASLIGI kerak.
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 105, 95, 97),
    ], resolve_touch_order="TP")
    show("TP+SL bitta shamda (savdo: TP oldin)", saved, ev)
    assert saved["ambiguous"], "ambiguous bayrog'i baribir qo'yilishi kerak"
    assert saved["status"] == "ACTIVE", (
        "faqat TP1 tegdi (TP2/TP3 hali yo'q) -- signal ochiq qolishi kerak edi")
    assert abs(saved["realized_pct"] - 2.0) < 1e-6, (
        f"TP1 ulushi (0.5*4%=2.0%) to'plangan bo'lishi kerak edi, {saved['realized_pct']} chiqdi")

    # 4c. Xuddi shunday, lekin savdolar SL OLDIN tegilganini ko'rsatsa —
    # natija konservativ holat bilan BIR XIL bo'lishi kerak.
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 105, 95, 97),
    ], resolve_touch_order="SL")
    show("TP+SL bitta shamda (savdo: SL oldin)", saved, ev, -4.0)

    # 4d. YAGONA TP (bitta TP) signal -- TP tegishi bilan SHU YERDA 100%
    # yopiladi. Keraksiz "BE" hodisasi (demak "stop breakeven'ga
    # ko'chirildi" xabari) EMITLANMASLIGI kerak -- pozitsiya allaqachon
    # to'liq yopilgan, stopning endi ahamiyati yo'q.
    saved, ev = await run(signal(tps=[104.0]), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 104.5, 100, 104),   # yagona TP
    ])
    show("Yagona TP -- BE hodisasi bo'lmasligi kerak", saved, ev, 4.0)
    assert not any(e["type"] == "BE" for e in ev), (
        f"yagona TP to'liq yopilganda BE hodisasi bo'lmasligi kerak edi: {ev}")
    assert saved["status"] == "TP"

    # 5. Entryga tegmadi
    saved, ev = await run(signal(), [
        candle(0, 102, 103, 101, 102),
        candle(1, 102, 104, 101.5, 103),
    ])
    show("Entry to'lmadi", saved, ev)

    # 6. Muddati o'tgan
    saved, ev = await run(signal(created_at=NOW - timedelta(days=10)), [
        candle(0, 102, 103, 101, 102),
    ])
    show("PENDING muddati tugadi", saved, ev)

    # 7. Bitta shamda ikkita TP
    saved, ev = await run(signal(), [
        candle(0, 101, 101, 99, 100),
        candle(1, 100, 109, 100, 108),    # TP1 va TP2 birga
    ])
    show("Bitta shamda TP1+TP2", saved, ev)

    # 8. SHORT
    saved, ev = await run(signal(
        side="SHORT", entry=100.0, sl=104.0, sl_initial=104.0, tps=[96.0, 92.0, 88.0]
    ), [
        candle(0, 99, 101, 99, 100),
        candle(1, 100, 100, 95.5, 96),
        candle(2, 96, 97, 91.5, 92),
        candle(3, 92, 93, 87.5, 88),
    ])
    show("SHORT to'liq TP", saved, ev, 6.8)

    # 9. Bir nechta iteratsiya (bot uxlab qolgan holat)
    sig = signal()
    exchange.klines = lambda *a, **k: _ret([candle(0, 101, 101, 99, 100)])
    db.save_progress = _save
    await tracker.process(sig)
    sig.update(SAVED)
    sig["tps"] = [104.0, 108.0, 112.0]
    sig["sl_initial"] = 96.0
    sig["symbol"], sig["side"], sig["entry"], sig["id"] = "BTCUSDT", "LONG", 100.0, 1
    sig["created_at"] = NOW
    exchange.klines = lambda *a, **k: _ret([candle(1, 100, 113, 100, 112)])
    ev = await tracker.process(sig)
    show("Uzilgan sikl (2 bosqich)", SAVED, ev, 6.8)

    # 10. Signal ENG BIRINCHI marta tekshirilyapti va birinchi qaytgan sham
    # signal YARATILISHIDAN OLDIN boshlangan (1 daqiqalik chegaraga to'liq
    # tushmagan, `created_at` odatda tasodifiy soniyada bo'lgani sabab bu
    # DEYARLI HAR DOIM shunday) -- bu sham signal HALI mavjud bo'lmagan
    # paytdagi narx harakatini o'z ichiga olishi mumkin, shuning uchun
    # e'tiborga olinmasligi (o'tkazib yuborilishi) kerak.
    created = NOW
    first_partial = exchange.Candle(
        int((created - timedelta(seconds=30)).timestamp() * 1000), 101, 101, 96, 100,
        int((created + timedelta(seconds=30)).timestamp() * 1000))  # entry(100)ga tegadi, lekin OLDIN boshlangan
    after_no_touch = candle(1, 102, 103, 101.5, 102)  # entryga tegmaydi
    saved, ev = await run(signal(created_at=created), [first_partial, after_no_touch])
    show("Yaratilishdan oldingi (chegarasiz) birinchi sham o'tkazib yuborildi", saved, ev)
    assert saved["status"] == "PENDING", (
        "birinchi (chegaraga tushmagan) sham o'tkazib yuborilib, entry hali "
        f"TO'LMAGAN deb qolishi kerak edi: {saved['status']}")
    assert not ev, f"hech qanday hodisa bo'lmasligi kerak edi: {ev}"

    # Nazorat: signal yaratilgandan KEYIN boshlangan (haqiqiy, chegaraga
    # tushgan) shamda entryga tegilsa, bu TO'G'RI aniqlanishi kerak --
    # faqat chegarasiz BIRINCHI sham o'tkazib yuboriladi, undan keyingilari
    # emas.
    after_touch = candle(1, 102, 103, 99, 102)  # bu safar entry(100)ga tegadi
    saved2, ev2 = await run(signal(created_at=created), [first_partial, after_touch])
    show("... nazorat: keyingi (haqiqiy) shamda entry to'g'ri aniqlandi", saved2, ev2)
    assert saved2["status"] == "ACTIVE", (
        f"ikkinchi (haqiqiy) shamda entryga tegish aniqlanishi kerak edi: {saved2['status']}")
    assert any(e["type"] == "OPEN" for e in ev2)

    # Xuddi shu himoya Market order (`entry_mode="market"`, ACTIVE'dan
    # to'g'ridan-to'g'ri boshlangan, "kirish shami" tushunchasi yo'q)
    # signallari uchun ham ishlashi kerak: birinchi (chegarasiz) shamda
    # SL'ga "tegilgan" bo'lib ko'ringan bo'lsa ham, bu signal HALI ACTIVE
    # bo'lmagan paytdagi (yaratilishdan oldingi) narx bo'lishi mumkin --
    # o'tkazib yuborilishi kerak.
    market_sig = signal(status="ACTIVE", opened_at=created, created_at=created)
    first_partial_sl = exchange.Candle(
        int((created - timedelta(seconds=30)).timestamp() * 1000), 100, 101, 95, 100,
        int((created + timedelta(seconds=30)).timestamp() * 1000))  # SL(96)ga tegadi, lekin OLDIN boshlangan
    after_no_touch2 = candle(1, 100, 101, 98, 100)  # SL'ga tegmaydi
    saved3, ev3 = await run(market_sig, [first_partial_sl, after_no_touch2])
    show("Market: yaratilishdan oldingi shamdagi 'SL' o'tkazib yuborildi", saved3, ev3)
    assert saved3["status"] == "ACTIVE", (
        "Market signal yaratilishidan OLDINGI shamdagi SL tegishi e'tiborga "
        f"olinmasligi kerak edi: {saved3['status']}")
    assert not ev3, f"hech qanday hodisa bo'lmasligi kerak edi: {ev3}"

    # 11. TP/SL hali kiritilmagan (limit-keyin-so'ralsin oqimi, `sl=None`):
    # entry to'lgach ham, HAR QANDAY keyingi narx harakati (garchi juda
    # keskin bo'lsa ham) TP/SL sifatida HISOBLANMASLIGI kerak -- ular hali
    # UMUMAN mavjud emas, foydalanuvchi ularni hali kiritmagan.
    saved, ev = await run(signal(sl=None, sl_initial=None, tps=[]), [
        candle(0, 101, 101, 99, 100),      # entry to'ldi
        candle(1, 100, 500, 1, 100),       # HAR QANDAY narx -- baribir tekshirilmaydi
    ])
    show("TP/SL hali kiritilmagan -- narx harakati e'tiborga olinmadi", saved, ev)
    assert saved["status"] == "ACTIVE", (
        f"TP/SL kiritilmaguncha signal ACTIVE (kutish) holatida qolishi kerak edi: {saved['status']}")
    assert saved["sl"] is None, f"sl hamon NULL qolishi kerak edi: {saved['sl']}"
    assert len(ev) == 1 and ev[0]["type"] == "OPEN" and ev[0]["needs_tpsl"] is True, ev

    # 12. #133'da HAQIQIY (Railway logi bilan isbotlangan) xato: klines()
    # `end_ms`siz chaqirilardi -- MEXC bunday holda so'ralgan startTime'ni
    # E'TIBORGA OLMAY, eng SO'NGGI 500 daqiqalik (8+ soatlik!) tarixni
    # qaytarardi, kuzatuv esa shu butun eski tarixni "signal yaratilgandan
    # keyin" deb noto'g'ri qayta o'ynatardi (entry/TP soatlab OLDINGI
    # narxlarga "tegdi" deb hisoblanardi). Endi `klines()` doim aniq
    # `end_ms` ("hozir") bilan chaqirilishi SHART.
    klines_calls = []

    async def _capture_klines(symbol, start_ms, limit=500, tf="1m", end_ms=None):
        klines_calls.append(end_ms)
        return [candle(0, 101, 101, 99, 100)]

    exchange.klines = _capture_klines
    db.save_progress = _save
    before_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    await tracker.process(signal())
    after_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert len(klines_calls) == 1 and klines_calls[0] is not None, (
        "klines() end_ms'siz chaqirilyapti -- #133'dagi xato QAYTA CHIQQAN "
        f"(MEXC eski tarixni qaytarishi mumkin): {klines_calls}")
    assert before_ms <= klines_calls[0] <= after_ms + 1000, (
        f"end_ms ({klines_calls[0]}) chaqiruv vaqtiga mos kelmayapti")
    show("klines() end_ms bilan chaqirildi (#133 tuzatishi)",
         {"status": "ACTIVE", "pnl_pct": None, "r_multiple": None}, [])

    print("\nBarcha holatlar tekshirildi.")


asyncio.run(main())
