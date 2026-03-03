from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from bot.deriv.client import DerivWsClient
from bot.deriv.symbols import SymbolCatalog, SymbolItem


@dataclass
class SymbolSnapshot:
    fetched_at: float
    all_symbols: list[SymbolItem]


class SymbolCache:
    def __init__(self, client: DerivWsClient):
        self._catalog = SymbolCatalog(client)
        self._lock = asyncio.Lock()
        self._snapshot: SymbolSnapshot | None = None

    async def get(self) -> SymbolSnapshot:
        async with self._lock:
            if self._snapshot is None:
                items = await self._catalog.fetch_active_symbols()
                self._snapshot = SymbolSnapshot(fetched_at=time.time(), all_symbols=items)
            return self._snapshot

    async def refresh(self) -> SymbolSnapshot:
        async with self._lock:
            items = await self._catalog.fetch_active_symbols()
            self._snapshot = SymbolSnapshot(fetched_at=time.time(), all_symbols=items)
            return self._snapshot