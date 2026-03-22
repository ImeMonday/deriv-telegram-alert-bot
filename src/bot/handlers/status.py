from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    settings: Settings = context.application.bot_data["settings"]
    conn = await Database(DbConfig(path=settings.db_path)).connect()

    try:
        repo = Repo(conn)
        await repo.upsert_user(user_id)
        plan = await repo.get_user_plan(user_id)
        active = await repo.count_active_alerts(user_id)
    finally:
        await conn.close()

    if plan == "premium":
        plan_label = "Premium ⭐"
        limit = 100
    else:
        plan_label = "Free"
        limit = 3

    await update.message.reply_text(
        f"📊 Your Status\n\n"
        f"Plan: {plan_label}\n"
        f"Active Alerts: {active}/{limit}\n\n"
        f"Use /setalert to add alerts.\n"
        f"Use /upgrade to go premium."
    )


def build_status_handlers():
    return [CommandHandler("status", status_cmd)]