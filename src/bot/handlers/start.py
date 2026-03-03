from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = user.first_name if user else "there"
    await update.message.reply_text(
        "Deriv Alert Bot is running.\n\n"
        "Commands:\n"
        "/setalert - create a new price alert\n"
        "/viewalerts - view saved alerts (Step 5)\n"
        "/deletealert - delete alerts (Step 5)\n"
        "/cancel - cancel current action\n\n"
        f"Hi {name}."
    )