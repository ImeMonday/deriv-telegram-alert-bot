from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Awaitable, Any

import websockets
from websockets.client import WebSocketClientProtocol


TickHandler = Callable[[str, float], Awaitable[None]]


class DerivTickStream:
    """
    Dedicated streaming client for tick subscriptions.
    Separate from request/response client for clarity.
    """

    def __init__(self, base_url: str, app_id: int):
        self._base_url = base_url.rstrip("/")
        self._app_id = int(app_id)
        self._ws: WebSocketClientProtocol | None = None
        self._log = logging.getLogger("deriv.stream")
        self._running = False
        self._subscriptions: set[str] = set()
        self._tick_handler: TickHandler | None = None

    def _url(self) -> str:
        return f"{self._base_url}?app_id={self._app_id}"

    async def connect(self) -> None:
        self._log.info("Connecting streaming WS...")
        self._ws = await websockets.connect(self._url(), ping_interval=20, ping_timeout=20)
        self._log.info("Streaming connected.")

    async def close(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def subscribe(self, symbol: str) -> None:
        if not self._ws:
            return
        if symbol in self._subscriptions:
            return
        payload = {"ticks": symbol, "subscribe": 1}
        await self._ws.send(json.dumps(payload))
        self._subscriptions.add(symbol)
        self._log.info("Subscribed to %s", symbol)

    async def unsubscribe_all(self) -> None:
        if not self._ws:
            return
        await self._ws.send(json.dumps({"forget_all": "ticks"}))
        self._subscriptions.clear()
        self._log.info("Cleared all subscriptions")

    async def run(self, tick_handler: TickHandler) -> None:
        self._tick_handler = tick_handler
        self._running = True

        while self._running:
            try:
                if not self._ws:
                    await self.connect()

                async for msg in self._ws:
                    data = json.loads(msg)

                    if data.get("msg_type") == "tick":
                        tick = data.get("tick") or {}
                        symbol = tick.get("symbol")
                        quote = tick.get("quote")
                        if symbol and quote is not None and self._tick_handler:
                            await self._tick_handler(symbol, float(quote))

            except Exception as e:
                self._log.warning("Stream error: %s. Reconnecting...", e)
                await asyncio.sleep(3)
                try:
                    await self.connect()
                    
                    for s in list(self._subscriptions):
                        await self.subscribe(s)
                except Exception as e2:
                    self._log.warning("Reconnect failed: %s", e2)
                    await asyncio.sleep(5)