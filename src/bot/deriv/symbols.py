from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List

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
        self._cache: List[SymbolItem] = []

    async def fetch_active_symbols(self) -> List[SymbolItem]:

        requests = [
            {"active_symbols": "full"},
            {"active_symbols": "full", "product_type": "basic"},
            {"active_symbols": "full", "product_type": "advanced"},
        ]

        seen = {}
        out: List[SymbolItem] = []

        for req in requests:

            try:
                resp = await self.client.request(req)
                items = resp.get("active_symbols") or []
            except Exception as e:
                LOG.warning("active_symbols request failed: %s", e)
                continue

            for it in items:

                symbol = str(it.get("symbol", "")).upper()

                if not symbol:
                    continue

                if symbol in seen:
                    continue

                seen[symbol] = True

                out.append(
                    SymbolItem(
                        symbol=symbol,
                        display_name=str(it.get("display_name", "")),
                        market=it.get("market"),
                        submarket=it.get("submarket"),
                    )
                )

        if not out:

            LOG.warning("Deriv returned empty active_symbols")

            if self._cache:
                LOG.warning(
                    "Using cached symbols instead (%d symbols)", len(self._cache)
                )
                return self._cache

            LOG.error("No cached symbols available")
            return []

        self._cache = out

        LOG.info("Fetched %d symbols", len(out))

        return out


def display_name_for_symbol(symbol: str) -> str:
    symbol = (symbol or "").upper()

    mapping = {
        "R_10": "Volatility 10 Index",
        "R_25": "Volatility 25 Index",
        "R_50": "Volatility 50 Index",
        "R_75": "Volatility 75 Index",
        "R_100": "Volatility 100 Index",

        "R_10_1S": "Volatility 10 (1s)",
        "R_25_1S": "Volatility 25 (1s)",
        "R_50_1S": "Volatility 50 (1s)",
        "R_75_1S": "Volatility 75 (1s)",
        "R_100_1S": "Volatility 100 (1s)",

        "JD10": "Jump 10 Index",
        "JD25": "Jump 25 Index",
        "JD50": "Jump 50 Index",
        "JD75": "Jump 75 Index",
        "JD100": "Jump 100 Index",

        "BOOM500": "Boom 500",
        "BOOM1000": "Boom 1000",
        "CRASH500": "Crash 500",
        "CRASH1000": "Crash 1000",

        "STEPINDEX": "Step Index",

        "RANGE100": "Range Break 100",
        "RANGE200": "Range Break 200",

        "RDBULL": "Bull Market Index",
        "RDBEAR": "Bear Market Index",
    }

    return mapping.get(symbol, symbol)


def is_synthetic_symbol(symbol: str) -> bool:
    s = (symbol or "").upper()

    synthetic_prefixes = (
        "R_",
        "1HZ",
        "JD",
        "JUMP",
        "BOOM",
        "CRASH",
        "STEP",
        "RANGE",
        "DEX",
        "DRIFT",
        "BULL",
        "BEAR",
    )

    return s.startswith(synthetic_prefixes)


def forex_pairs(items: Iterable[SymbolItem]) -> List[SymbolItem]:

    out: List[SymbolItem] = []

    for s in items:

        m = (s.market or "").lower()
        sm = (s.submarket or "").lower()

        if "forex" in m or "forex" in sm:
            out.append(s)

    return sorted(out, key=lambda x: x.display_name)


def volatility_indices(items: Iterable[SymbolItem]) -> List[SymbolItem]:

    out: List[SymbolItem] = []

    for s in items:
        if is_synthetic_symbol(s.symbol):
            out.append(s)

    return sorted(out, key=lambda x: display_name_for_symbol(x.symbol))