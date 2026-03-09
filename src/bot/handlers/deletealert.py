from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.symbols import display_name_for_symbol


# ---------------------------------------------------------
# /deletealert command
# ---------------------------------------------------------

async def deletealert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id

    settings: Settings = context.application.bot_data["settings"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)

        alerts = await repo.list_user_alerts(user_id)

    finally:
        await conn.close()

    if not alerts:
        await update.message.reply_text(
            "You have no alerts to delete."
        )
        return

    rows = []

    for a in alerts:

        label = (
            f"{display_name_for_symbol(a.symbol)} "
            f"@ {a.price}"
        )

        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"del:{a.id}",
                )
            ]
        )

    keyboard = InlineKeyboardMarkup(rows)

    await update.message.reply_text(
        "Select alert to delete:",
        reply_markup=keyboard,
    )


# ---------------------------------------------------------
# button pressed
# ---------------------------------------------------------

async def deletealert_button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    data = query.data

    if not data.startswith("del:"):
        return

    alert_id = int(data.split(":")[1])

    settings: Settings = context.application.bot_data["settings"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:

        repo = Repo(conn)

        await repo.deactivate_alert(alert_id)

    finally:
        await conn.close()

    await query.edit_message_text(
        "Alert deleted successfully."
    )


# ---------------------------------------------------------
# register handlers
# ---------------------------------------------------------

def build_deletealert_handlers():

    return [
        CommandHandler(
            "deletealert",
            deletealert_cmd,
        ),
        CallbackQueryHandler(
            deletealert_button,
            pattern=r"^del:",
        ),
    ]