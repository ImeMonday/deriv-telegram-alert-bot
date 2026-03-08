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
            LOG.debug("Fetching active symbols from Deriv API")

            resp = await self.client.request(
                {
                    "active_symbols": "brief",
                    "product_type": "basic",
                }
            )

            items = resp.get("active_symbols") or []

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

            LOG.info("Fetched %d symbols", len(out))

            return out

        except Exception as e:
            LOG.exception("Failed to fetch active symbols: %s", e)
            raise



def display_name_for_symbol(symbol: str) -> str:
    """
    Return readable display name for a symbol
    """

    symbol = (symbol or "").upper()

    mapping = {
        "R_10": "Volatility 10 Index",
        "R_25": "Volatility 25 Index",
        "R_50": "Volatility 50 Index",
        "R_75": "Volatility 75 Index",
        "R_100": "Volatility 100 Index",
        "RDBULL": "Bull Market Index",
        "RDBEAR": "Bear Market Index",
    }

    return mapping.get(symbol, symbol)


def is_synthetic_symbol(symbol: str) -> bool:
    """
    Identify Deriv synthetic indices
    """

    s = (symbol or "").upper()

    keys = (
        "R_",
        "BOOM",
        "CRASH",
        "STEP",
        "RANGE",
        "BULL",
        "BEAR",
    )

    return any(k in s for k in keys)


def forex_pairs(items: Iterable[SymbolItem]) -> list[SymbolItem]:
    """Filter forex pairs"""
    out = []

    for s in items:
        m = (s.market or "").lower()
        sm = (s.submarket or "").lower()

        if "forex" in m or "forex" in sm:
            out.append(s)

    return sorted(out, key=lambda x: x.display_name)


def volatility_indices(items: Iterable[SymbolItem]) -> list[SymbolItem]:
    """Filter volatility / synthetic indices"""

    keys = ("volatility", "boom", "crash", "step", "range")

    out = []

    for s in items:
        name = s.display_name.lower()

        if any(k in name for k in keys):
            out.append(s)

    return sorted(out, key=lambda x: x.display_name)



def search(items: list[SymbolItem], q: str) -> list[SymbolItem]:
    q = (q or "").strip().lower()

    if not q:
        return items

    return [
        s
        for s in items
        if q in s.display_name.lower()
        or q in s.symbol.lower()
    ]



def paginate(items: list[SymbolItem], page: int, page_size: int = 12) -> tuple[list[SymbolItem], int]:

    if page_size <= 0:
        page_size = 12

    total_pages = max(1, (len(items) + page_size - 1) // page_size)

    page = max(0, min(page, total_pages - 1))

    start = page * page_size
    end = start + page_size

    return items[start:end], total_pages