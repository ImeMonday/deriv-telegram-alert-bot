from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from telegram.ext import Application

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.stream import DerivTickStream
from bot.deriv.symbols import display_name_for_symbol


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
            self._settings.deriv_ws_url,
            self._settings.deriv_app_id
        )

        self._db = Database(DbConfig(path=self._settings.db_path))

        self._conn = None
        self._repo: Repo | None = None

        self._task: asyncio.Task | None = None
        self._sub_task: asyncio.Task | None = None

        self._running = False

        # 🔥 less aggressive refresh
        self._refresh_every_sec = 10

        self._last_symbols: set[str] = set()
        self._alerts_cache: dict[str, list] = {}

        # 🔥 NEW: store last price per symbol (for crossing logic)
        self._last_price: dict[str, float] = {}

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

        if self._task:
            self._task.cancel()

        await self._stream.close()

        if self._conn:
            await self._conn.close()

        self._log.info("Alert engine stopped.")

    async def _main_loop(self):

        await self._stream.connect()

        await self._refresh_subscriptions()

        await self._stream.run(self._on_tick)

    async def _subscription_loop(self):

        while self._running:

            try:
                await asyncio.sleep(self._refresh_every_sec)
                await self._refresh_subscriptions()

            except asyncio.CancelledError:
                return

            except Exception as e:
                self._log.warning("Subscription refresh failed: %s", e)

    async def _refresh_subscriptions(self):

        assert self._repo is not None

        symbols = await self._repo.active_symbols()
        new_set = set(symbols)

        if new_set != self._last_symbols:
            self._last_symbols = new_set

            await self._stream.unsubscribe_all()

            for s in symbols:
                await self._stream.subscribe(s)

        alerts = await self._repo.list_active_alerts()

        cache: dict[str, list] = {}
        for alert in alerts:
            cache.setdefault(alert.symbol, []).append(alert)

        self._alerts_cache = cache

        self._log.info("Loaded %d alerts into cache", sum(len(v) for v in cache.values()))

    async def _on_tick(self, symbol: str, price: float):

        assert self._repo is not None

        try:
            prev_price = self._last_price.get(symbol)

            # 🔥 restart-safe: first tick just initializes
            if prev_price is None:
                self._last_price[symbol] = price
                return

            self._last_price[symbol] = price

            alerts = self._alerts_cache.get(symbol, [])

            self._log.info(f"{symbol} price={price} alerts={len(alerts)}")

            for alert in list(alerts):  # copy to avoid mutation issues

                self._log.info(
                    f"CHECK {symbol} | prev={prev_price} price={price} "
                    f"target={alert.price} dir={alert.direction}"
                )

                if not self._should_trigger(alert, price, prev_price):
                    continue

                if not self._cooldown_ok(alert):
                    continue

                self._log.info(
                    f"TRIGGERED {symbol} | user={alert.user_id} "
                    f"price={price} target={alert.price}"
                )

                await self._notify(
                    alert.user_id,
                    symbol=symbol,
                    price=price,
                    direction=alert.direction,
                    target=alert.price,
                    mode=alert.mode,
                )

                # 🔥 prevent duplicate trigger in same cycle
                if symbol in self._alerts_cache:
                    if alert in self._alerts_cache[symbol]:
                        self._alerts_cache[symbol].remove(alert)

                if alert.mode == "once":
                    await self._repo.deactivate_alert(alert.id)
                else:
                    await self._repo.update_triggered(alert.id)

        except Exception as e:
            self._log.warning("Tick handling failed (%s): %s", symbol, e)

    def _should_trigger(self, alert, price: float, prev_price: float | None) -> bool:

        if prev_price is None:
            return False

        target = float(alert.price)

        if target <= 0:
            return False

        if alert.direction == "above":
            return prev_price < target and price >= target

        if alert.direction == "below":
            return prev_price > target and price <= target

        return False

    def _cooldown_ok(self, alert) -> bool:

        if not alert.last_triggered_at:
            return True

        last = _parse_sqlite_ts(str(alert.last_triggered_at))
        if not last:
            return True

        now = datetime.now(timezone.utc)

        return (now - last).total_seconds() >= alert.cooldown_seconds

    async def _notify(
        self,
        user_id: int,
        *,
        symbol: str,
        price: float,
        direction: str,
        target: float,
        mode: str,
    ):
        name = display_name_for_symbol(symbol)

        if target > 0:
            pct = abs((price - target) / target) * 100
            pct_str = f"{pct:.2f}%"
        else:
            pct_str = "N/A"

        direction_emoji = "📈" if direction == "above" else "📉"

        text = (
            f"🎯 <b>Alert Triggered</b>\n\n"
            f"Symbol: <b>{name}</b>\n"
            f"Current Price: <b>{price}</b>\n"
            f"Target: <b>{target}</b>\n"
            f"Direction: {direction_emoji} {direction.title()}\n"
            f"Distance from target: <b>{pct_str}</b>\n"
            f"Mode: {mode.title()}"
        )

        try:
            await self._app.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML",
            )

        except Exception as e:
            self._log.warning("Notify failed for %s: %s", user_id, e)