"""Bir martalik tekshiruv: TWELVE_DATA_API_KEY ishlayaptimi. Ishga tushirilgach o'chiriladi."""
import asyncio

import config
import forex


async def main():
    print(f"TWELVE_DATA_API_KEY bor: {bool(config.TWELVE_DATA_API_KEY)}")
    try:
        symbols = await forex.valid_symbols()
        print(f"Forex juftliklar soni: {len(symbols)}")
        print("Namuna:", sorted(symbols)[:10])
        for test in ("EURUSD", "XAUUSD", "GBPUSD"):
            print(f"resolve({test}) -> {await forex.resolve(test)}")
        price = await forex.last_price("EURUSD")
        print("EURUSD joriy narx:", price)
    except Exception as e:
        print("XATO:", repr(e))
    finally:
        await forex.close()


asyncio.run(main())
