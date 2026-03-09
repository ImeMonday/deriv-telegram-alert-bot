from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, List

import aiosqlite


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Alert:
    id: int
    user_id: int
    symbol: str
    price: float
    direction: str
    mode: str
    cooldown_seconds: int
    active: int
    last_triggered_at: str | None
    created_at: str | None


class Repo:
    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    # -----------------------------------------------------
    # SCHEMA
    # -----------------------------------------------------

    async def ensure_schema(self) -> None:

        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                plan TEXT NOT NULL DEFAULT 'free',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                payment_email TEXT,

                paystack_customer_code TEXT,
                paystack_subscription_code TEXT,
                paystack_email_token TEXT,
                premium_renews_at TEXT,
                premium_status TEXT NOT NULL DEFAULT 'inactive'
            )
            """
        )

        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                direction TEXT NOT NULL,
                mode TEXT NOT NULL,
                cooldown_seconds INTEGER NOT NULL DEFAULT 30,
                active INTEGER NOT NULL DEFAULT 1,
                last_triggered_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            """
        )

        await self._conn.commit()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    async def upsert_user(self, user_id: int) -> None:

        await self._conn.execute(
            """
            INSERT INTO users (user_id, plan, premium_status, created_at)
            VALUES (?, 'free', 'inactive', ?)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (int(user_id), _utc_now_iso()),
        )

        await self._conn.commit()

    async def get_user_plan(self, user_id: int) -> str:

        await self.upsert_user(user_id)

        async with self._conn.execute(
            "SELECT plan FROM users WHERE user_id = ?",
            (int(user_id),),
        ) as cur:
            row = await cur.fetchone()

        return str(row[0]) if row else "free"

    async def set_user_plan(self, user_id: int, plan: str) -> None:

        await self.upsert_user(user_id)

        premium_status = "active" if plan == "premium" else "inactive"

        await self._conn.execute(
            """
            UPDATE users
            SET plan = ?, premium_status = ?
            WHERE user_id = ?
            """,
            (plan, premium_status, int(user_id)),
        )

        await self._conn.commit()

    async def set_user_email(self, user_id: int, email: str) -> None:

        await self.upsert_user(user_id)

        await self._conn.execute(
            """
            UPDATE users
            SET payment_email = ?
            WHERE user_id = ?
            """,
            (email, int(user_id)),
        )

        await self._conn.commit()

    async def get_user_email(self, user_id: int) -> str | None:

        async with self._conn.execute(
            """
            SELECT payment_email
            FROM users
            WHERE user_id = ?
            """,
            (int(user_id),),
        ) as cur:
            row = await cur.fetchone()

        return row[0] if row else None

    # -----------------------------------------------------
    # ALERT COUNTS
    # -----------------------------------------------------

    async def count_active_alerts(self, user_id: int) -> int:

        async with self._conn.execute(
            """
            SELECT COUNT(*)
            FROM alerts
            WHERE user_id = ?
            AND active = 1
            """,
            (int(user_id),),
        ) as cur:
            row = await cur.fetchone()

        return int(row[0]) if row else 0

    # -----------------------------------------------------
    # CREATE ALERT
    # -----------------------------------------------------

    async def create_alert(
        self,
        *,
        user_id: int,
        symbol: str,
        price: float,
        direction: str,
        mode: str,
        cooldown_seconds: int = 30,
    ) -> int:

        await self.upsert_user(user_id)

        cur = await self._conn.execute(
            """
            INSERT INTO alerts (
                user_id,
                symbol,
                price,
                direction,
                mode,
                cooldown_seconds,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                int(user_id),
                symbol,
                float(price),
                direction,
                mode,
                int(cooldown_seconds),
                _utc_now_iso(),
            ),
        )

        await self._conn.commit()

        return int(cur.lastrowid)

    # -----------------------------------------------------
    # USER ALERT LIST
    # -----------------------------------------------------

    async def list_user_alerts(self, user_id: int) -> List[Alert]:

        async with self._conn.execute(
            """
            SELECT
                id,
                user_id,
                symbol,
                price,
                direction,
                mode,
                cooldown_seconds,
                active,
                last_triggered_at,
                created_at
            FROM alerts
            WHERE user_id = ?
            AND active = 1
            ORDER BY id DESC
            """,
            (int(user_id),),
        ) as cur:

            rows = await cur.fetchall()

        return [self._row_to_alert(r) for r in rows]

    # -----------------------------------------------------
    # ENGINE QUERY
    # -----------------------------------------------------

    async def list_active_alerts_for_symbols(
        self,
        symbols: Iterable[str],
    ) -> List[Alert]:

        symbols = list(symbols)

        if not symbols:
            return []

        placeholders = ",".join("?" for _ in symbols)

        query = f"""
            SELECT
                id,
                user_id,
                symbol,
                price,
                direction,
                mode,
                cooldown_seconds,
                active,
                last_triggered_at,
                created_at
            FROM alerts
            WHERE active = 1
            AND symbol IN ({placeholders})
        """

        async with self._conn.execute(query, tuple(symbols)) as cur:
            rows = await cur.fetchall()

        return [self._row_to_alert(r) for r in rows]

    # -----------------------------------------------------
    # SYMBOL SUBSCRIPTIONS
    # -----------------------------------------------------

    async def active_symbols(self) -> List[str]:

        async with self._conn.execute(
            """
            SELECT DISTINCT symbol
            FROM alerts
            WHERE active = 1
            """
        ) as cur:

            rows = await cur.fetchall()

        return [str(r[0]) for r in rows]

    # -----------------------------------------------------
    # DELETE ALERT
    # -----------------------------------------------------

    async def deactivate_alert(self, alert_id: int) -> None:

        await self._conn.execute(
            """
            UPDATE alerts
            SET active = 0
            WHERE id = ?
            """,
            (int(alert_id),),
        )

        await self._conn.commit()

    # -----------------------------------------------------
    # ALERT TRIGGER UPDATE
    # -----------------------------------------------------

    async def update_triggered(self, alert_id: int) -> None:

        await self._conn.execute(
            """
            UPDATE alerts
            SET last_triggered_at = ?
            WHERE id = ?
            """,
            (_utc_now_iso(), int(alert_id)),
        )

        await self._conn.commit()

    # -----------------------------------------------------
    # INTERNAL
    # -----------------------------------------------------

    def _row_to_alert(self, row: Any) -> Alert:

        return Alert(
            id=int(row[0]),
            user_id=int(row[1]),
            symbol=str(row[2]),
            price=float(row[3]),
            direction=str(row[4]),
            mode=str(row[5]),
            cooldown_seconds=int(row[6]),
            active=int(row[7]),
            last_triggered_at=row[8],
            created_at=row[9],
        )