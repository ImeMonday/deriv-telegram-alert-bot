from __future__ import annotations

from typing import Any, Literal, TypedDict


class DerivError(TypedDict, total=False):
    code: str
    message: str


class DerivResponse(TypedDict, total=False):
    msg_type: str
    req_id: int
    error: DerivError
    echo_req: dict[str, Any]


class ActiveSymbol(TypedDict, total=False):
    symbol: str
    display_name: str
    market: str
    market_display_name: str
    submarket: str
    submarket_display_name: str
    symbol_type: str
    exchange_is_open: int
    is_trading_suspended: int


class ActiveSymbolsResponse(DerivResponse, total=False):
    active_symbols: list[ActiveSymbol]