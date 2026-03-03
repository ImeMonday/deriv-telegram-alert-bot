from __future__ import annotations

import asyncio

from bot.config import load_settings
from bot.deriv.client import DerivWsClient
from bot.deriv.symbols import SymbolCatalog
from bot.utils.logging import setup_logging


async def run() -> None:
    s = load_settings()
    setup_logging(s.log_level)

    client = DerivWsClient(base_url=s.deriv_ws_url, app_id=s.deriv_app_id)
    catalog = SymbolCatalog(client)

    all_syms = await catalog.fetch_active_symbols()
    fx = catalog.forex_pairs(all_syms)
    vol = catalog.volatility_indices(all_syms)

    print(f"Total active symbols: {len(all_syms)}")
    print(f"Forex pairs: {len(fx)} (sample: {[x.display_name for x in fx[:8]]})")
    print(f"Volatility-ish: {len(vol)} (sample: {[x.display_name for x in vol[:8]]})")

    await client.close()


if __name__ == "__main__":
    asyncio.run(run())