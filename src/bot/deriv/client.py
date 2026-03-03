from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol


class DerivWsClient:
    """
    Minimal Deriv WS client with request/response pairing via req_id.
    Subscription streaming will be added in Step 7.
    """

    def __init__(self, base_url: str, app_id: int):
        self._base_url = base_url.rstrip("/")
        self._app_id = int(app_id)
        self._ws: WebSocketClientProtocol | None = None
        self._log = logging.getLogger("deriv.ws")

        self._req_id = 1000
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def _url(self) -> str:
        return f"{self._base_url}?app_id={self._app_id}"

    async def connect(self) -> None:
        async with self._lock:
            if self.is_connected:
                return
            self._log.info("Connecting to Deriv WS...")
            self._ws = await websockets.connect(self._url(), ping_interval=20, ping_timeout=20)
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._log.info("Connected.")

    async def close(self) -> None:
        async with self._lock:
            if self._reader_task:
                self._reader_task.cancel()
                self._reader_task = None
            if self._ws:
                await self._ws.close()
                self._ws = None

        
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Deriv WS closed"))
            self._pending.clear()

    async def _reader_loop(self) -> None:
        assert self._ws is not None
        ws = self._ws
        try:
            async for msg in ws:
                data = json.loads(msg)
                req_id = data.get("req_id")
                if isinstance(req_id, int) and req_id in self._pending:
                    fut = self._pending.pop(req_id)
                    if not fut.done():
                        fut.set_result(data)
                else:
                
                    self._log.debug("Stream msg: %s", data.get("msg_type"))
        except asyncio.CancelledError:
            return
        except Exception as e:
            self._log.warning("Reader loop stopped: %s", e)

        
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError(f"Deriv WS error: {e}"))
            self._pending.clear()

    async def request(self, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
        """
        Sends a JSON request with req_id and waits for matching response.
        """
        if not self.is_connected:
            await self.connect()

        assert self._ws is not None

        self._req_id += 1
        req_id = self._req_id
        payload = {**payload, "req_id": req_id}

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut

        await self._ws.send(json.dumps(payload))

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception:
            
            self._pending.pop(req_id, None)
            raise