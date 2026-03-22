from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telegram.ext import Application

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo

LOG = logging.getLogger("bot.expiry_notifier")

CHECK_INTERVAL_SECONDS = 60 * 60  # check every hour
WARN_DAYS_BEFORE = 3              # warn 3 days before expiry


class ExpiryNotifier:

    def __init__(self, app: Application):
        self._app = app
        self._settings: Settings = app.bot_data["settings"]
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        LOG.info("Expiry notifier started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        LOG.info("Expiry notifier stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_expiring()
            except asyncio.CancelledError:
                return
            except Exception as e:
                LOG.warning("Expiry check failed: %s", e)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _check_expiring(self) -> None:

        conn = await Database(DbConfig(path=self._settings.db_path)).connect()

        try:
            repo = Repo(conn)
            users = await repo.get_expiring_premium_users(days=WARN_DAYS_BEFORE)
        finally:
            await conn.close()

        for user_id, renews_at in users:
            try:
                await self._app.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⚠️ Premium Expiring Soon\n\n"
                        f"Your premium access expires on {renews_at[:10]}.\n\n"
                        "Use /upgrade to renew and keep your unlimited alerts."
                    ),
                )
                LOG.info("Expiry warning sent to %s", user_id)
            except Exception as e:
                LOG.warning("Failed to notify %s: %s", user_id, e)