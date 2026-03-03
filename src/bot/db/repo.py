from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import aiosqlite


@dataclass(frozen=True)
class UserRow:
    user_id: int
    plan: str


@dataclass(frozen=True)
class AlertRow:
    id: int
    user_id: int
    symbol: str
    price: float
    direction: str
    mode: str
    is_active: int
    cooldown_seconds: int
    last_triggered_at: str | None


class Repo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def _fetchone(self, sql: str, params: Sequence[object] = ()) -> aiosqlite.Row | None:
        cur = await self.conn.execute(sql, params)
        try:
            row = await cur.fetchone()
            return row
        finally:
            await cur.close()

    async def _fetchall(self, sql: str, params: Sequence[object] = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, params)
        try:
            rows = await cur.fetchall()
            return list(rows)
        finally:
            await cur.close()

    async def upsert_user(self, user_id: int) -> UserRow:
        await self.conn.execute(
            """
            INSERT INTO users(user_id, plan, created_at, updated_at)
            VALUES(?, 'free', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP
            """,
            (int(user_id),),
        )
        await self.conn.commit()

        row = await self._fetchone("SELECT user_id, plan FROM users WHERE user_id=?", (int(user_id),))
        if not row:
            return UserRow(user_id=int(user_id), plan="free")
        return UserRow(user_id=int(row["user_id"]), plan=str(row["plan"]))

    async def set_user_plan(self, user_id: int, plan: str) -> None:
        await self.conn.execute(
            """
            INSERT INTO users(user_id, plan, created_at, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan, updated_at=CURRENT_TIMESTAMP
            """,
            (int(user_id), str(plan)),
        )
        await self.conn.commit()

    async def get_user_plan(self, user_id: int) -> str:
        row = await self._fetchone("SELECT plan FROM users WHERE user_id=?", (int(user_id),))
        return str(row["plan"]) if row else "free"

    async def count_active_alerts(self, user_id: int) -> int:
        row = await self._fetchone(
            "SELECT COUNT(*) AS c FROM alerts WHERE user_id=? AND is_active=1",
            (int(user_id),),
        )
        return int(row["c"]) if row else 0

    async def create_alert(
        self,
        user_id: int,
        symbol: str,
        price: float,
        direction: str,
        mode: str,
        cooldown_seconds: int = 30,
        note: str | None = None,
    ) -> int:
        cur = await self.conn.execute(
            """
            INSERT INTO alerts(
                user_id, symbol, price, direction, mode, is_active,
                cooldown_seconds, last_triggered_at, created_at, updated_at, note
            )
            VALUES(?, ?, ?, ?, ?, 1, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
            """,
            (int(user_id), str(symbol), float(price), str(direction), str(mode), int(cooldown_seconds), note),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def list_alerts(self, user_id: int, active_only: bool = False) -> list[AlertRow]:
        if active_only:
            sql = """
            SELECT id, user_id, symbol, price, direction, mode, is_active, cooldown_seconds, last_triggered_at
            FROM alerts
            WHERE user_id=? AND is_active=1
            ORDER BY id DESC
            """
            params = (int(user_id),)
        else:
            sql = """
            SELECT id, user_id, symbol, price, direction, mode, is_active, cooldown_seconds, last_triggered_at
            FROM alerts
            WHERE user_id=?
            ORDER BY id DESC
            """
            params = (int(user_id),)

        rows = await self._fetchall(sql, params)
        return [
            AlertRow(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                symbol=str(r["symbol"]),
                price=float(r["price"]),
                direction=str(r["direction"]),
                mode=str(r["mode"]),
                is_active=int(r["is_active"]),
                cooldown_seconds=int(r["cooldown_seconds"]),
                last_triggered_at=r["last_triggered_at"],
            )
            for r in rows
        ]

    async def deactivate_alerts(self, user_id: int, alert_ids: Sequence[int]) -> int:
        if not alert_ids:
            return 0
        placeholders = ",".join(["?"] * len(alert_ids))
        params = (int(user_id), *[int(x) for x in alert_ids])

        cur = await self.conn.execute(
            f"""
            UPDATE alerts
            SET is_active=0, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=? AND id IN ({placeholders})
            """,
            params,
        )
        await self.conn.commit()
        return int(cur.rowcount)

    async def active_symbols(self) -> list[str]:
        rows = await self._fetchall(
            "SELECT DISTINCT symbol FROM alerts WHERE is_active=1 ORDER BY symbol ASC"
        )
        return [str(r["symbol"]) for r in rows]

    async def list_active_alerts_for_symbols(self, symbols: Sequence[str]) -> list[AlertRow]:
        
        if not symbols:
            return []
        placeholders = ",".join(["?"] * len(symbols))
        rows = await self._fetchall(
            f"""
            SELECT id, user_id, symbol, price, direction, mode, is_active, cooldown_seconds, last_triggered_at
            FROM alerts
            WHERE is_active=1 AND symbol IN ({placeholders})
            """,
            tuple(symbols),
        )
        return [
            AlertRow(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                symbol=str(r["symbol"]),
                price=float(r["price"]),
                direction=str(r["direction"]),
                mode=str(r["mode"]),
                is_active=int(r["is_active"]),
                cooldown_seconds=int(r["cooldown_seconds"]),
                last_triggered_at=r["last_triggered_at"],
            )
            for r in rows
        ]

    async def update_triggered(self, alert_id: int, deactivate: bool) -> None:
        if deactivate:
            await self.conn.execute(
                """
                UPDATE alerts
                SET last_triggered_at=CURRENT_TIMESTAMP,
                    is_active=0,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (int(alert_id),),
            )
        else:
            await self.conn.execute(
                """
                UPDATE alerts
                SET last_triggered_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (int(alert_id),),
            )
        await self.conn.commit()