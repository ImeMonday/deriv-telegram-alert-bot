from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from bot.deriv.client import DerivWsClient
from bot.deriv.types import ActiveSymbolsResponse


@dataclass(frozen=True)
class SymbolItem:
    symbol: str
    display_name: str
    market: str
    submarket: str
    symbol_type: str


class SymbolCatalog:
    def __init__(self, client: DerivWsClient):
        self._client = client
        self._log = logging.getLogger("deriv.symbols")

    async def fetch_active_symbols(self) -> list[SymbolItem]:
        resp = await self._client.request(
            {"active_symbols": "brief", "product_type": "basic"},
            timeout=25.0,
        )
        data: ActiveSymbolsResponse = resp  

        if data.get("error"):
            err = data["error"]
            raise RuntimeError(f"Deriv error: {err.get('code')} {err.get('message')}")

        items: list[SymbolItem] = []
        for s in data.get("active_symbols", []) or []:
            symbol = (s.get("symbol") or "").strip()
            if not symbol:
                continue
            items.append(
                SymbolItem(
                    symbol=symbol,
                    display_name=(s.get("display_name") or symbol).strip(),
                    market=(s.get("market") or "").strip(),
                    submarket=(s.get("submarket") or "").strip(),
                    symbol_type=(s.get("symbol_type") or "").strip(),
                )
            )
        self._log.info("Fetched %d active symbols", len(items))
        return items

    @staticmethod
    def forex_pairs(symbols: Iterable[SymbolItem]) -> list[SymbolItem]:
        out = [s for s in symbols if s.symbol.lower().startswith("frx")]
        return sorted(out, key=lambda x: x.display_name.lower())

    @staticmethod
    def volatility_indices(symbols: Iterable[SymbolItem]) -> list[SymbolItem]:
        out: list[SymbolItem] = []
        for s in symbols:
            dn = s.display_name.lower()
            if "volatility" in dn or s.symbol.upper().startswith(("R_", "1HZ", "CRASH", "BOOM")):
                out.append(s)

        seen = set()
        uniq: list[SymbolItem] = []
        for s in out:
            if s.symbol in seen:
                continue
            seen.add(s.symbol)
            uniq.append(s)

        return sorted(uniq, key=lambda x: x.display_name.lower())

    @staticmethod
    def search(items: list[SymbolItem], query: str) -> list[SymbolItem]:
        q = query.strip().lower()
        if not q:
            return items
        return [s for s in items if q in s.display_name.lower() or q in s.symbol.lower()]

    @staticmethod
    def paginate(items: list[SymbolItem], page: int, page_size: int = 12) -> tuple[list[SymbolItem], int]:
        if page < 0:
            page = 0
        total = len(items)
        total_pages = max(1, (total + page_size - 1) // page_size)
        if page >= total_pages:
            page = total_pages - 1
        start = page * page_size
        end = start + page_size
        return items[start:end], total_pages