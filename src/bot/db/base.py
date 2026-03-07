from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(slots=True)
class DbConfig:
    path: Path


class Database:

    def __init__(self, cfg: DbConfig):
        self.cfg = cfg

    async def connect(self) -> aiosqlite.Connection:

        db_path: Path = self.cfg.path

        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(str(db_path))

        conn.row_factory = aiosqlite.Row

        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA busy_timeout=5000;")

        return conn