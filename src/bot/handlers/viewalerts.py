from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.symbols import display_name_for_symbol


async def myalerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        await update.message.reply_text("You have no active alerts.")
        return

    lines = []

    for a in alerts:
        lines.append(
            f"#{a.id} {display_name_for_symbol(a.symbol)}\n"
            f"Price: {a.price}\n"
            f"Direction: {a.direction}\n"
            f"Mode: {a.mode}\n"
        )

    text = "Your active alerts:\n\n" + "\n".join(lines)

    await update.message.reply_text(text)


async def deletealert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        await update.message.reply_text("You have no alerts to delete.")
        return

    rows = []

    for a in alerts:

        label = f"{display_name_for_symbol(a.symbol)} @ {a.price}"

        rows.append(
            [InlineKeyboardButton(label, callback_data=f"del:{a.id}")]
        )

    keyboard = InlineKeyboardMarkup(rows)

    await update.message.reply_text(
        "Select alert to delete:",
        reply_markup=keyboard,
    )


async def deletealert_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    data = q.data

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

    await q.edit_message_text("Alert deleted successfully.")


def build_alert_handlers():

    return [
        CommandHandler("myalerts", myalerts_cmd),
        CommandHandler("deletealert", deletealert_cmd),
        CallbackQueryHandler(deletealert_cb, pattern=r"^del:")
    ]