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
        if "paystack_customer_code" not in user_cols:
            await self._conn.execute("ALTER TABLE users ADD COLUMN paystack_customer_code TEXT")
        if "paystack_subscription_code" not in user_cols:
            await self._conn.execute("ALTER TABLE users ADD COLUMN paystack_subscription_code TEXT")
        if "paystack_email_token" not in user_cols:
            await self._conn.execute("ALTER TABLE users ADD COLUMN paystack_email_token TEXT")
        if "premium_renews_at" not in user_cols:
            await self._conn.execute("ALTER TABLE users ADD COLUMN premium_renews_at TEXT")
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

        await self._conn.execute(
            """
            UPDATE users
            SET plan = 'free'
            WHERE plan IS NULL
            """
        )

        await self._conn.execute(
            """
            UPDATE users
            SET premium_status = 'inactive'
            WHERE premium_status IS NULL
            """
        )

        await self._conn.execute(
            """
            UPDATE users
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
            """
        )

        await self._conn.execute(
            """
            UPDATE alerts
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
            """
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
        await self._normalize_plan_if_needed(user_id)

        async with self._conn.execute(
            "SELECT plan FROM users WHERE user_id = ?",
            (int(user_id),),
        ) as cur:
            row = await cur.fetchone()

        return str(row[0]) if row else "free"

    async def _normalize_plan_if_needed(self, user_id: int) -> None:
        async with self._conn.execute(
            """
            SELECT plan, premium_status
            FROM users
            WHERE user_id = ?
            """,
            (int(user_id),),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            return

        plan = str(row[0] or "free")
        premium_status = str(row[1] or "inactive")

        if plan == "premium" and premium_status not in {"active", "cancelling"}:
            await self._conn.execute(
                """
                UPDATE users
                SET plan = 'free'
                WHERE user_id = ?
                """,
                (int(user_id),),
            )
            await self._conn.commit()

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

    async def list_user_alerts(self, user_id: int) -> list[Alert]:
        async with self._conn.execute(
            """
            SELECT id, user_id, symbol, price, direction, mode, cooldown_seconds,
                   active, last_triggered_at, created_at
            FROM alerts
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (int(user_id),),
        ) as cur:
            rows = await cur.fetchall()

        return [self._row_to_alert(r) for r in rows]

    async def list_active_alerts_for_symbols(self, symbols: list[str]) -> list[Alert]:
        if not symbols:
            return []

        placeholders = ",".join(["?"] * len(symbols))
        sql = f"""
            SELECT id, user_id, symbol, price, direction, mode, cooldown_seconds,
                   active, last_triggered_at, created_at
            FROM alerts
            WHERE active = 1
              AND symbol IN ({placeholders})
            ORDER BY id ASC
        """

        async with self._conn.execute(sql, tuple(symbols)) as cur:
            rows = await cur.fetchall()

        return [self._row_to_alert(r) for r in rows]

    async def update_triggered(self, alert_id: int, *, deactivate: bool) -> None:
        now = _utc_now_iso()
        active = 0 if deactivate else 1

        await self._conn.execute(
            """
            UPDATE alerts
            SET last_triggered_at = ?, active = ?
            WHERE id = ?
            """,
            (now, active, int(alert_id)),
        )
        await self._conn.commit()

    async def active_symbols(self) -> list[str]:
        async with self._conn.execute(
            """
            SELECT DISTINCT symbol
            FROM alerts
            WHERE active = 1
            ORDER BY symbol ASC
            """
        ) as cur:
            rows = await cur.fetchall()

        return [str(r[0]) for r in rows]

    async def deactivate_alerts(self, user_id: int, alert_ids: list[int]) -> int:
        if not alert_ids:
            return 0

        placeholders = ",".join(["?"] * len(alert_ids))
        sql = f"""
            UPDATE alerts
            SET active = 0
            WHERE user_id = ?
              AND id IN ({placeholders})
              AND active = 1
        """
        params: tuple[Any, ...] = (int(user_id), *[int(x) for x in alert_ids])

        cur = await self._conn.execute(sql, params)
        await self._conn.commit()
        return int(cur.rowcount or 0)

    async def count_users(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM users") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def count_alerts_total(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM alerts") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def count_alerts_active_total(self) -> int:
        async with self._conn.execute("SELECT COUNT(*) FROM alerts WHERE active = 1") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def top_symbols(self, limit: int = 8) -> list[tuple[str, int]]:
        async with self._conn.execute(
            """
            SELECT symbol, COUNT(*) AS n
            FROM alerts
            WHERE active = 1
            GROUP BY symbol
            ORDER BY n DESC, symbol ASC
            LIMIT ?
            """,
            (int(limit),),
        ) as cur:
            rows = await cur.fetchall()

        return [(str(r[0]), int(r[1])) for r in rows]

    async def activate_subscription(
        self,
        *,
        user_id: int,
        customer_code: str | None,
        subscription_code: str | None,
        email_token: str | None,
        renews_at: str | None,
    ) -> None:
        await self.upsert_user(user_id)
        await self._conn.execute(
            """
            UPDATE users
            SET plan = 'premium',
                premium_status = 'active',
                paystack_customer_code = COALESCE(?, paystack_customer_code),
                paystack_subscription_code = COALESCE(?, paystack_subscription_code),
                paystack_email_token = COALESCE(?, paystack_email_token),
                premium_renews_at = COALESCE(?, premium_renews_at)
            WHERE user_id = ?
            """,
            (
                customer_code,
                subscription_code,
                email_token,
                renews_at,
                int(user_id),
            ),
        )
        await self._conn.commit()

    async def mark_subscription_failed(
        self,
        *,
        user_id: int | None = None,
        subscription_code: str | None = None,
    ) -> None:
        await self._update_subscription_status(
            new_plan="premium",
            new_status="past_due",
            user_id=user_id,
            subscription_code=subscription_code,
        )

    async def mark_subscription_cancelling(
        self,
        *,
        user_id: int | None = None,
        subscription_code: str | None = None,
    ) -> None:
        await self._update_subscription_status(
            new_plan="premium",
            new_status="cancelling",
            user_id=user_id,
            subscription_code=subscription_code,
        )

    async def disable_subscription(
        self,
        *,
        user_id: int | None = None,
        subscription_code: str | None = None,
    ) -> None:
        await self._update_subscription_status(
            new_plan="free",
            new_status="inactive",
            user_id=user_id,
            subscription_code=subscription_code,
            clear_subscription=True,
        )

    async def find_user_id_by_subscription_code(self, subscription_code: str) -> int | None:
        async with self._conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE paystack_subscription_code = ?
            """,
            (subscription_code,),
        ) as cur:
            row = await cur.fetchone()

        return int(row[0]) if row else None

    async def find_user_id_by_customer_code(self, customer_code: str) -> int | None:
        async with self._conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE paystack_customer_code = ?
            """,
            (customer_code,),
        ) as cur:
            row = await cur.fetchone()

        return int(row[0]) if row else None

    async def mark_event_processed(self, event_key: str) -> bool:
        try:
            await self._conn.execute(
                """
                INSERT INTO processed_paystack_events (event_key)
                VALUES (?)
                """,
                (event_key,),
            )
            await self._conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def _update_subscription_status(
        self,
        *,
        new_plan: str,
        new_status: str,
        user_id: int | None = None,
        subscription_code: str | None = None,
        clear_subscription: bool = False,
    ) -> None:
        target_user_id = user_id

        if target_user_id is None and subscription_code:
            target_user_id = await self.find_user_id_by_subscription_code(subscription_code)

        if target_user_id is None:
            return

        if clear_subscription:
            await self._conn.execute(
                """
                UPDATE users
                SET plan = ?,
                    premium_status = ?,
                    premium_renews_at = NULL,
                    paystack_subscription_code = NULL,
                    paystack_email_token = NULL
                WHERE user_id = ?
                """,
                (new_plan, new_status, int(target_user_id)),
            )
        else:
            await self._conn.execute(
                """
                UPDATE users
                SET plan = ?,
                    premium_status = ?
                WHERE user_id = ?
                """,
                (new_plan, new_status, int(target_user_id)),
            )

        await self._conn.commit()

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