from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo

LOG = logging.getLogger("bot.broadcast")

ADMIN_IDS = {8045631498, 1758622186}

AWAIT_MESSAGE = 1


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    if not update.message or not update.effective_user:
        return ConversationHandler.END

    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Unauthorised.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Send the message to broadcast to all users.\n\n"
        "Send /cancel to abort."
    )

    return AWAIT_MESSAGE


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    if not update.message or not update.effective_user:
        return ConversationHandler.END

    text = update.message.text

    settings: Settings = context.application.bot_data["settings"]
    conn = await Database(DbConfig(path=settings.db_path)).connect()

    try:
        repo = Repo(conn)
        user_ids = await repo.get_all_user_ids()
    finally:
        await conn.close()

    await update.message.reply_text(f"Broadcasting to {len(user_ids)} users...")

    success = 0
    failed = 0

    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            success += 1
        except Exception as e:
            LOG.warning("Broadcast failed for %s: %s", uid, e)
            failed += 1
        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"Broadcast complete.\n\nSent: {success}\nFailed: {failed}"
    )

    return ConversationHandler.END


async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Broadcast cancelled.")
    return ConversationHandler.END


def build_broadcast_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_cmd)],
        states={
            AWAIT_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)
            ],
        },
        fallbacks=[CommandHandler("cancel", broadcast_cancel)],
        allow_reentry=True,
    )