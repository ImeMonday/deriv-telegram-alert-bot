from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.symbols import display_name_for_symbol


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
        rows.append([
            InlineKeyboardButton(
                f"{display_name_for_symbol(a.symbol)} @ {a.price}",
                callback_data=f"del:{a.id}",
            )
        ])

    keyboard = InlineKeyboardMarkup(rows)

    await update.message.reply_text(
        "Select alert to delete:",
        reply_markup=keyboard,
    )


async def deletealert_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    alert_id = int(q.data.split(":")[1])

    settings: Settings = context.application.bot_data["settings"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)
        await repo.deactivate_alert(alert_id)
    finally:
        await conn.close()

    await q.edit_message_text("Alert deleted successfully.")