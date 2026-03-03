from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo


def _fmt_alert(a) -> str:
    status = "ACTIVE" if a.is_active else "OFF"
    direction = str(a.direction).upper()
    mode = str(a.mode)
    return f"#{a.id} [{status}] {a.symbol} {direction} {a.price} ({mode})"


async def viewalerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = int(update.effective_user.id)
    settings: Settings = context.application.bot_data["settings"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    try:
        repo = Repo(conn)
        await repo.upsert_user(user_id)
        alerts = await repo.list_alerts(user_id=user_id, active_only=False)
    finally:
        await conn.close()

    if not alerts:
        await update.message.reply_text("No alerts yet. Use /setalert to create one.")
        return

    lines = ["Your alerts:"]

    for a in alerts[:50]:
        lines.append(_fmt_alert(a))

    if len(alerts) > 50:
        lines.append(f"...and {len(alerts) - 50} more.")

    await update.message.reply_text("\n".join(lines))