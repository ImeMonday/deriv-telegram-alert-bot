from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram.ext import Application

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.stream import DerivTickStream


def _parse_sqlite_ts(value: str) -> datetime | None:
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class AlertEngine:
    def __init__(self, app: Application):
        self._app = app
        self._log = logging.getLogger("alert.engine")
        self._settings: Settings = app.bot_data["settings"]

        self._stream = DerivTickStream(
            base_url=self._settings.deriv_ws_url,
            app_id=self._settings.deriv_app_id,
        )

        self._db = Database(DbConfig(path=self._settings.db_path))
        self._conn = None
        self._repo: Repo | None = None

        self._task: asyncio.Task | None = None
        self._running = False

        self._sub_task: asyncio.Task | None = None
        self._refresh_every_sec = 10

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        self._conn = await self._db.connect()
        self._repo = Repo(self._conn)

        self._task = asyncio.create_task(self._main_loop())
        self._sub_task = asyncio.create_task(self._subscription_loop())

        self._log.info("Alert engine started.")

    async def stop(self) -> None:
        self._running = False

        if self._sub_task:
            self._sub_task.cancel()
            self._sub_task = None
        if self._task:
            self._task.cancel()
            self._task = None

        await self._stream.close()

        if self._conn:
            await self._conn.close()
            self._conn = None
            self._repo = None

        self._log.info("Alert engine stopped.")

    async def _main_loop(self) -> None:
        await self._stream.connect()
        await self._refresh_subscriptions()

        await self._stream.run(self._on_tick)

    async def _subscription_loop(self) -> None:
       
        while self._running:
            try:
                await asyncio.sleep(self._refresh_every_sec)
                await self._refresh_subscriptions()
            except asyncio.CancelledError:
                return
            except Exception as e:
                self._log.warning("Subscription refresh failed: %s", e)

    async def _refresh_subscriptions(self) -> None:
        assert self._repo is not None

        symbols = await self._repo.active_symbols()

        await self._stream.unsubscribe_all()
        for s in symbols:
            await self._stream.subscribe(s)

    async def _on_tick(self, symbol: str, price: float) -> None:
        assert self._repo is not None

        try:
            alerts = await self._repo.list_active_alerts_for_symbols([symbol])
            for a in alerts:
                if not self._should_trigger(a, price):
                    continue
                if not self._cooldown_ok(a):
                    continue

                await self._notify(a.user_id, symbol, price, a.direction, a.price)

                deactivate = (a.mode == "once")
                await self._repo.update_triggered(a.id, deactivate=deactivate)

        except Exception as e:
            self._log.warning("Tick handling failed (%s): %s", symbol, e)

    def _should_trigger(self, alert, price: float) -> bool:
        if alert.direction == "above":
            return price >= alert.price
        if alert.direction == "below":
            return price <= alert.price
        return False

    def _cooldown_ok(self, alert) -> bool:
        if not alert.last_triggered_at:
            return True

        last = _parse_sqlite_ts(str(alert.last_triggered_at))
        if not last:
            return True

        now = datetime.now(timezone.utc)
        diff = (now - last).total_seconds()
        return diff >= alert.cooldown_seconds

    async def _notify(self, user_id: int, symbol: str, price: float, direction: str, target: float) -> None:
        text = (
            "🔔 Alert Triggered\n"
            f"Symbol: {symbol}\n"
            f"Current: {price}\n"
            f"Target: {target}\n"
            f"Direction: {direction.upper()}"
        )
        try:
            await self._app.bot.send_message(chat_id=user_id, text=text)
        except Exception as e:
            self._log.warning("Notify failed for %s: %s", user_id, e)