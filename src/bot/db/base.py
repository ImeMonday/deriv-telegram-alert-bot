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

        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        return conn