from __future__ import annotations

import subprocess


def upgrade_head() -> None:

    subprocess.check_call(["alembic", "upgrade", "head"])