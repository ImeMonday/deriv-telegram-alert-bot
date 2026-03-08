from __future__ import annotations

import aiosqlite
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db.repo import Alert, Repo
from bot.deriv.symbols import display_name_for_symbol


def _fmt_direction(direction: str) -> str:
    d = direction.lower().strip()
    if d == "above":
        return "Above"
    if d == "below":
        return "Below"
    return direction.title()


def _fmt_mode(mode: str) -> str:
    m = mode.lower().strip()
    if m == "repeat":
        return "Repeat"
    if m == "once":
        return "Once"
    return mode.title()


def _fmt_alert(alert: Alert) -> str:
    status = "🟢 Active" if alert.active == 1 else "⚪ Inactive"
    return (
        f"#{alert.id}  {display_name_for_symbol(alert.symbol)}\n"
        f"Direction: {_fmt_direction(alert.direction)}\n"
        f"Target: {alert.price}\n"
        f"Mode: {_fmt_mode(alert.mode)}\n"
        f"Cooldown: {alert.cooldown_seconds}s\n"
        f"Status: {status}"
    )


async def myalerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = int(update.effective_user.id)
    settings: Settings = context.application.bot_data["settings"]

    conn = await aiosqlite.connect(settings.db_path)
    try:
        repo = Repo(conn)
        await repo.ensure_schema()
        await repo.upsert_user(user_id)
        alerts = await repo.list_user_alerts(user_id)
    finally:
        await conn.close()

    if not alerts:
        await update.message.reply_text("No alerts yet. Use /setalert to create one.")
        return

    text = "My Alerts\n\n" + "\n\n".join(_fmt_alert(alert) for alert in alerts[:50])
    if len(alerts) > 50:
        text += f"\n\n...and {len(alerts) - 50} more."

    await update.message.reply_text(text)


viewalerts_cmd = myalerts_cmd