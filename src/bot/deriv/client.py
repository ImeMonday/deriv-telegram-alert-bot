from __future__ import annotations

import json
import logging
import os
from typing import Any

import websockets

LOG = logging.getLogger("bot.deriv.client")

MAX_RETRIES = 3
RETRY_DELAY = 1


class DerivWsClient:
    """WebSocket client for Deriv API"""

    def __init__(self, base_url: str, app_id: int):
        self.base_url = base_url.rstrip("/")
        self.app_id = int(app_id)
        self.api_token = os.getenv("DERIV_API_TOKEN")

        LOG.debug(
            "DerivWsClient initialized: base_url=%s, app_id=%d",
            self.base_url,
            self.app_id,
        )

    def _url(self) -> str:
        """Build WebSocket URL with app_id"""
        return f"{self.base_url}?app_id={self.app_id}"

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Send request to Deriv API via WebSocket.

        Args:
            payload: Request payload as dict

        Returns:
            Response as dict
        """

        url = self._url()
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                LOG.debug("WebSocket request attempt %d/%d", attempt, MAX_RETRIES)

                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:

                    # ----- AUTHORIZE WITH DERIV TOKEN -----
                    if self.api_token:
                        await ws.send(
                            json.dumps(
                                {
                                    "authorize": self.api_token
                                }
                            )
                        )

                        auth_raw = await ws.recv()
                        auth_resp = json.loads(auth_raw)

                        if "error" in auth_resp:
                            raise Exception(
                                f"Deriv authorization failed: {auth_resp}"
                            )

                        LOG.debug("Deriv authorization successful")

                    # ----- SEND ACTUAL REQUEST -----
                    await ws.send(json.dumps(payload))

                    raw = await ws.recv()
                    response = json.loads(raw)

                    LOG.debug("WebSocket request successful")
                    return response

            except Exception as e:
                last_error = e

                if attempt < MAX_RETRIES:
                    import asyncio

                    wait_time = RETRY_DELAY * attempt

                    LOG.warning(
                        "WebSocket attempt %d failed: %s. Retrying in %ds...",
                        attempt,
                        e,
                        wait_time,
                    )

                    await asyncio.sleep(wait_time)

                else:
                    LOG.exception(
                        "WebSocket request failed after %d attempts",
                        MAX_RETRIES,
                    )

        raise Exception(
            f"WebSocket request failed after {MAX_RETRIES} attempts: {last_error}"
        )