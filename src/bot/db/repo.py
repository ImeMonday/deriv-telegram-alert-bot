from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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

        await self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_paystack_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        user_cols = await self._table_columns("users")

        if "payment_email" not in user_cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN payment_email TEXT"
            )

        if "paystack_customer_code" not in user_cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN paystack_customer_code TEXT"
            )

        if "paystack_subscription_code" not in user_cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN paystack_subscription_code TEXT"
            )

        if "paystack_email_token" not in user_cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN paystack_email_token TEXT"
            )

        if "premium_renews_at" not in user_cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN premium_renews_at TEXT"
            )

        if "premium_status" not in user_cols:
            await self._conn.execute(
                "ALTER TABLE users ADD COLUMN premium_status TEXT NOT NULL DEFAULT 'inactive'"
            )

        alert_cols = await self._table_columns("alerts")

        if "cooldown_seconds" not in alert_cols:
            await self._conn.execute(
                "ALTER TABLE alerts ADD COLUMN cooldown_seconds INTEGER NOT NULL DEFAULT 30"
            )

        if "active" not in alert_cols:
            await self._conn.execute(
                "ALTER TABLE alerts ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
            )

        if "last_triggered_at" not in alert_cols:
            await self._conn.execute(
                "ALTER TABLE alerts ADD COLUMN last_triggered_at TEXT"
            )

        if "created_at" not in alert_cols:
            await self._conn.execute(
                "ALTER TABLE alerts ADD COLUMN created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )

        await self._conn.commit()


    async def _table_columns(self, table_name: str) -> set[str]:
        async with self._conn.execute(f"PRAGMA table_info({table_name})") as cur:
            rows = await cur.fetchall()
        return {str(row[1]) for row in rows}


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

        if not row:
            return None

        return row[0]


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


    async def count_active_alerts(self, user_id: int) -> int:
        async with self._conn.execute(
            """
            SELECT COUNT(*)
            FROM alerts
            WHERE user_id = ? AND active = 1
            """,
            (int(user_id),),
        ) as cur:
            row = await cur.fetchone()

        return int(row[0]) if row else 0


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