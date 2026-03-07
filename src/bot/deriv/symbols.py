from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from bot.deriv.client import DerivWsClient

LOG = logging.getLogger("bot.deriv.symbols")


@dataclass(frozen=True)
class SymbolItem:
    symbol: str
    display_name: str
    market: str | None
    submarket: str | None


class SymbolCatalog:
    def __init__(self, client: DerivWsClient):
        self.client = client
        LOG.debug("SymbolCatalog initialized")

    async def fetch_active_symbols(self) -> list[SymbolItem]:
        """Fetch active symbols from Deriv API"""
        try:
            LOG.debug("Fetching active symbols from Deriv API...")
            resp = await self.client.request(
                {
                    "active_symbols": "brief",
                    "product_type": "basic",
                }
            )
            items = resp.get("active_symbols") or []
            LOG.debug("API returned %d items", len(items))
            
            out: list[SymbolItem] = []
            for it in items:
                try:
                    item = SymbolItem(
                        symbol=str(it.get("symbol", "")).upper(),
                        display_name=str(it.get("display_name", "")),
                        market=it.get("market"),
                        submarket=it.get("submarket"),
                    )
                    out.append(item)
                except Exception as e:
                    LOG.warning("Failed to parse symbol item: %s", e)
                    continue
            
            LOG.info("Fetched %d valid symbols", len(out))
            return out
        except Exception as e:
            LOG.exception("Failed to fetch active symbols: %s", e)
            raise

    @staticmethod
    def forex_pairs(items: Iterable[SymbolItem]) -> list[SymbolItem]:
        """Filter symbols to show only forex pairs"""
        out = []
        for s in items:
            m = (s.market or "").lower()
            sm = (s.submarket or "").lower()
            if "forex" in m or "forex" in sm:
                out.append(s)
        
        result = sorted(out, key=lambda x: x.display_name)
        LOG.debug("Filtered to %d forex pairs", len(result))
        return result

    @staticmethod
    def volatility_indices(items: Iterable[SymbolItem]) -> list[SymbolItem]:
        """Filter symbols to show only volatility indices"""
        # Deriv naming varies. This heuristic matches common "Volatility", "Boom", "Crash", "Step", "Range", etc.
        keys = ("volatility", "boom", "crash", "step", "range")
        out = []
        for s in items:
            name = s.display_name.lower()
            if any(k in name for k in keys):
                out.append(s)
        
        result = sorted(out, key=lambda x: x.display_name)
        LOG.debug("Filtered to %d volatility indices", len(result))
        return result

    @staticmethod
    def search(items: list[SymbolItem], q: str) -> list[SymbolItem]:
        """Search symbols by name or symbol code"""
        q = (q or "").strip().lower()
        if not q:
            LOG.debug("Empty query, returning all %d items", len(items))
            return items
        
        result = [s for s in items if q in s.display_name.lower() or q in s.symbol.lower()]
        LOG.debug("Search for '%s' returned %d results", q, len(result))
        return result

    @staticmethod
    def paginate(items: list[SymbolItem], page: int, page_size: int = 12) -> tuple[list[SymbolItem], int]:
        """Paginate items into pages"""
        if page_size <= 0:
            page_size = 12
            LOG.warning("Invalid page_size, using default 12")
        
        # Calculate total pages
        total = max(1, (len(items) + page_size - 1) // page_size)
        
        # Ensure page is within bounds
        page = max(0, min(page, total - 1))
        
        # Get slice
        start = page * page_size
        end = start + page_size
        page_items = items[start:end]
        
        LOG.debug("Paginate: page=%d, page_size=%d, total_pages=%d, items_on_page=%d", 
                 page, page_size, total, len(page_items))
        
        return page_items, total
