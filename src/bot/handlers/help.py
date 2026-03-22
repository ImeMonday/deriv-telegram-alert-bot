from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, ContextTypes

SUPPORT_ADMIN_ID = 8045631498


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    if not update.message:
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Contact Support", url=f"tg://user?id={SUPPORT_ADMIN_ID}")]
    ])

    await update.message.reply_text(
        "📖 Help & Commands\n\n"
        "/start — Welcome message\n"
        "/setalert — Set a new price alert\n"
        "/myalerts — View your active alerts\n"
        "/deletealert — Delete an alert\n"
        "/status — Check your plan and alert count\n"
        "/upgrade — Upgrade to premium\n\n"
        "For complaints or support, tap the button below:",
        reply_markup=keyboard,
    )


def build_help_handlers():
    return [CommandHandler("help", help_cmd)]