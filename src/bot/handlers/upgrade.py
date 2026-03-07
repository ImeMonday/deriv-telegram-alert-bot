from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings


async def upgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    user = update.effective_user
    if not user:
        return

    settings: Settings = context.application.bot_data["settings"]

    if not settings.payment_base_url:
        await update.message.reply_text("Upgrade is not configured yet.")
        return

    payment_link = f"{settings.payment_base_url}/pay/{user.id}"

    await update.message.reply_text(
        "Premium Plan\n\n"
        "Unlimited alerts\n"
        "Price: $5/month\n\n"
        f"Pay here:\n{payment_link}"
    )