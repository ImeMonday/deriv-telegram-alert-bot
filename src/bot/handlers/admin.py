from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo


def _is_admin(update: Update, settings: Settings) -> bool:

    user = update.effective_user
    if not user:
        return False

    return int(user.id) in settings.admin_telegram_user_ids


async def adminstats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    settings: Settings = context.application.bot_data["settings"]

    if not _is_admin(update, settings):

        if update.message:
            await update.message.reply_text("Unauthorized.")

        return

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:

        repo = Repo(conn)

        users = await repo.count_users()
        alerts_total = await repo.count_alerts_total()
        alerts_active = await repo.count_alerts_active_total()
        top = await repo.top_symbols(limit=8)

    finally:
        await conn.close()

    top_lines = "\n".join([f"{sym}: {n}" for sym, n in top]) if top else "None"

    if update.message:

        await update.message.reply_text(
            "Admin stats\n"
            f"Users: {users}\n"
            f"Alerts (total): {alerts_total}\n"
            f"Alerts (active): {alerts_active}\n\n"
            "Top active symbols:\n"
            f"{top_lines}"
        )


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

    if not context.args:
        await update.message.reply_text("Usage: /premium <user_id>")
        return

    context.args = [context.args[0], "premium"]

    await setplan_cmd(update, context)


async def free_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if not context.args:
        await update.message.reply_text("Usage: /free <user_id>")
        return

    context.args = [context.args[0], "free"]

    await setplan_cmd(update, context)