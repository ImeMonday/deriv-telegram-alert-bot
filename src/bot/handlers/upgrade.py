from telegram import Update
from telegram.ext import CommandHandler, ContextTypes


async def upgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message:
        await update.message.reply_text(
            "Premium upgrade is temporarily disabled.\n\n"
            "All features are free while we test the bot."
        )


def build_upgrade_handlers():
    return [
        CommandHandler("upgrade", upgrade_cmd),
    ]