from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from bot.deriv.client import DerivWsClient
from bot.deriv.symbols import SymbolCatalog, SymbolItem

LOG = logging.getLogger("bot.services.symbol_cache")


@dataclass
class SymbolSnapshot:
    fetched_at: float
    all_symbols: list[SymbolItem]


class SymbolCache:
    def __init__(self, client: DerivWsClient):
        self._catalog = SymbolCatalog(client)
        self._lock = asyncio.Lock()
        self._snapshot: SymbolSnapshot | None = None
        LOG.debug("SymbolCache initialized")

    async def get(self) -> SymbolSnapshot:
        """Get cached symbols snapshot (lazy load on first call)"""
        async with self._lock:
            if self._snapshot is None:
                LOG.debug("Snapshot is None, fetching from catalog...")
                items = await self._catalog.fetch_active_symbols()
                self._snapshot = SymbolSnapshot(fetched_at=time.time(), all_symbols=items)
                LOG.info("Initial snapshot loaded: %d symbols", len(items))
            return self._snapshot

    async def refresh(self) -> SymbolSnapshot:
        """Force refresh symbol cache from Deriv API"""
        async with self._lock:
            try:
                LOG.debug("Refreshing symbol cache from API...")
                items = await self._catalog.fetch_active_symbols()
                self._snapshot = SymbolSnapshot(fetched_at=time.time(), all_symbols=items)
                LOG.info("Symbol cache refreshed: %d symbols", len(items))
                return self._snapshot
            except Exception as e:
                LOG.exception("Failed to refresh symbol cache: %s", e)
                raise

    async def start(self) -> None:
        """Initialize symbol cache on bot startup"""
        try:
            LOG.info("Starting symbol cache...")
            await self.refresh()
            LOG.info("Symbol cache started successfully")
        except Exception as e:
            LOG.exception("Failed to start symbol cache: %s", e)
            raise

    async def stop(self) -> None:
        """Cleanup symbol cache on bot shutdown"""
        try:
            LOG.info("Stopping symbol cache...")
            # Clear the snapshot
            async with self._lock:
                self._snapshot = None
            LOG.info("Symbol cache stopped")
        except Exception as e:
            LOG.exception("Failed to stop symbol cache: %s", e)