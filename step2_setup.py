from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run(cmd: list[str]) -> None:
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> None:
    
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    (ROOT / "src" / "bot" / "db").mkdir(parents=True, exist_ok=True)
    (ROOT / "src").mkdir(parents=True, exist_ok=True)

    
    write_text(ROOT / "src" / "__init__.py", "")
    write_text(ROOT / "src" / "bot" / "__init__.py", "")
    write_text(ROOT / "src" / "bot" / "db" / "__init__.py", "")

    models_py = """\
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Telegram user id
    plan: Mapped[str] = mapped_column(String(16), nullable=False, default="free")  # free|premium
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="user")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.user_id"), nullable=False)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False)   # e.g. "frxEURUSD", "R_100"
    price: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # above|below
    mode: Mapped[str] = mapped_column(String(8), nullable=False)       # once|repeat

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_user_active", "user_id", "is_active"),
        Index("ix_alerts_symbol_active", "symbol", "is_active"),
        Index("ix_alerts_active", "is_active"),
        UniqueConstraint("user_id", "symbol", "price", "direction", "mode", name="uq_alert_dedupe"),
    )
"""
    write_text(ROOT / "src" / "bot" / "db" / "models.py", models_py)

    base_py = """\
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import aiosqlite


@dataclass(frozen=True)
class DbConfig:
    path: Path


class Database:
    def __init__(self, cfg: DbConfig):
        self._cfg = cfg

    async def connect(self) -> aiosqlite.Connection:
        self._cfg.path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self._cfg.path.as_posix())
        conn.row_factory = aiosqlite.Row

        # Pragmas for reliability + concurrency
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        return conn
"""
    write_text(ROOT / "src" / "bot" / "db" / "base.py", base_py)

    repo_py = """\
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

    async def upsert_user(self, user_id: int) -> UserRow:
        await self.conn.execute(
            '''
            INSERT INTO users(user_id, plan, created_at, updated_at)
            VALUES(?, 'free', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET updated_at=CURRENT_TIMESTAMP
            ''',
            (user_id,),
        )
        await self.conn.commit()
        row = await self.conn.execute_fetchone("SELECT user_id, plan FROM users WHERE user_id=?", (user_id,))
        return UserRow(user_id=int(row["user_id"]), plan=str(row["plan"]))

    async def set_user_plan(self, user_id: int, plan: str) -> None:
        await self.conn.execute(
            '''
            INSERT INTO users(user_id, plan, created_at, updated_at)
            VALUES(?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan, updated_at=CURRENT_TIMESTAMP
            ''',
            (user_id, plan),
        )
        await self.conn.commit()

    async def get_user_plan(self, user_id: int) -> str:
        row = await self.conn.execute_fetchone("SELECT plan FROM users WHERE user_id=?", (user_id,))
        return str(row["plan"]) if row else "free"

    async def count_active_alerts(self, user_id: int) -> int:
        row = await self.conn.execute_fetchone(
            "SELECT COUNT(*) AS c FROM alerts WHERE user_id=? AND is_active=1",
            (user_id,),
        )
        return int(row["c"])

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
            '''
            INSERT INTO alerts(
                user_id, symbol, price, direction, mode, is_active,
                cooldown_seconds, last_triggered_at, created_at, updated_at, note
            )
            VALUES(?, ?, ?, ?, ?, 1, ?, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
            ''',
            (user_id, symbol, float(price), direction, mode, int(cooldown_seconds), note),
        )
        await self.conn.commit()
        return int(cur.lastrowid)

    async def list_alerts(self, user_id: int, active_only: bool = False) -> list[AlertRow]:
        if active_only:
            sql = '''
            SELECT id, user_id, symbol, price, direction, mode, is_active, cooldown_seconds, last_triggered_at
            FROM alerts
            WHERE user_id=? AND is_active=1
            ORDER BY id DESC
            '''
            params = (user_id,)
        else:
            sql = '''
            SELECT id, user_id, symbol, price, direction, mode, is_active, cooldown_seconds, last_triggered_at
            FROM alerts
            WHERE user_id=?
            ORDER BY id DESC
            '''
            params = (user_id,)

        rows = await self.conn.execute_fetchall(sql, params)
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
        params = (user_id, *map(int, alert_ids))
        cur = await self.conn.execute(
            f'''
            UPDATE alerts
            SET is_active=0, updated_at=CURRENT_TIMESTAMP
            WHERE user_id=? AND id IN ({placeholders})
            ''',
            params,
        )
        await self.conn.commit()
        return int(cur.rowcount)

    async def active_symbols(self) -> list[str]:
        rows = await self.conn.execute_fetchall(
            "SELECT DISTINCT symbol FROM alerts WHERE is_active=1 ORDER BY symbol ASC"
        )
        return [str(r["symbol"]) for r in rows]

    async def update_triggered(self, alert_id: int, deactivate: bool) -> None:
        if deactivate:
            await self.conn.execute(
                '''
                UPDATE alerts
                SET last_triggered_at=CURRENT_TIMESTAMP,
                    is_active=0,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                ''',
                (int(alert_id),),
            )
        else:
            await self.conn.execute(
                '''
                UPDATE alerts
                SET last_triggered_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                ''',
                (int(alert_id),),
            )
        await self.conn.commit()
"""
    write_text(ROOT / "src" / "bot" / "db" / "repo.py", repo_py)

    migrate_py = """\
from __future__ import annotations

import subprocess


def upgrade_head() -> None:
    subprocess.check_call(["alembic", "upgrade", "head"])
"""
    write_text(ROOT / "src" / "bot" / "db" / "migrate.py", migrate_py)

    
    if not (ROOT / "alembic.ini").exists() or not (ROOT / "migrations" / "env.py").exists():
    
        if not (ROOT / "migrations").exists() or not any((ROOT / "migrations").iterdir()):
            run(["alembic", "init", "migrations"])

    if (ROOT / "alembic.ini").exists():
        ini = (ROOT / "alembic.ini").read_text(encoding="utf-8", errors="ignore")
        lines = ini.splitlines()
        out = []
        replaced = False
        for line in lines:
            if line.strip().startswith("sqlalchemy.url"):
                out.append("sqlalchemy.url = sqlite:///./data/bot.db")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append("sqlalchemy.url = sqlite:///./data/bot.db")
        write_text(ROOT / "alembic.ini", "\n".join(out) + "\n")

    
    env_py = """\
from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path
import os

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load .env for DB_PATH
load_dotenv(override=False)

DB_PATH = os.getenv("DB_PATH", "./data/bot.db")
db_path = Path(DB_PATH).resolve()
db_path.parent.mkdir(parents=True, exist_ok=True)

# Build sqlite URL
sqlalchemy_url = f"sqlite:///{db_path.as_posix()}"
config.set_main_option("sqlalchemy.url", sqlalchemy_url)

# Import metadata (package-style import)
from src.bot.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""
    write_text(ROOT / "migrations" / "env.py", env_py)

    print("Step 2 scaffolding done.")
    print("")
    print("Next commands (run from project root):")
    print("  1) Set PYTHONPATH for Alembic to import src.*")
    print(r'     $env:PYTHONPATH="."')
    print('  2) Create first migration')
    print('     alembic revision --autogenerate -m "init users and alerts"')
    print('  3) Apply migration')
    print("     alembic upgrade head")
    print('  4) Verify tables')
    print(
        '     python -c "import sqlite3; con=sqlite3.connect(\'data/bot.db\'); cur=con.execute(\\"SELECT name FROM sqlite_master WHERE type=\'table\' ORDER BY name\\"); print([r[0] for r in cur.fetchall()]); con.close()"'
    )


if __name__ == "__main__":
    main()