from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo


def _is_admin(update: Update, settings: Settings) -> bool:
    if settings.admin_telegram_user_id <= 0:
        return False
    return int(update.effective_user.id) == int(settings.admin_telegram_user_id)


async def setplan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]

    if not _is_admin(update, settings):
        await update.message.reply_text("Unauthorized.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /setplan <user_id> <free|premium>")
        return

    try:
        user_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("Invalid user_id.")
        return

    plan = context.args[1].strip().lower()
    if plan not in ("free", "premium"):
        await update.message.reply_text("Plan must be: free or premium")
        return

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    try:
        repo = Repo(conn)
        await repo.set_user_plan(user_id, plan)
    finally:
        await conn.close()

    await update.message.reply_text(f"Updated user {user_id} plan -> {plan}")


async def premium_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.args = (context.args or [])
    context.args = [*context.args[:1], "premium"] if context.args else []
    await setplan_cmd(update, context)


async def free_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.args = (context.args or [])
    context.args = [*context.args[:1], "free"] if context.args else []
    await setplan_cmd(update, context)