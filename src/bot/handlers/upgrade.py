from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes

PAYMENT_BASE_URL = "https://derivalertbot.xyz"


async def upgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id
    payment_link = f"{PAYMENT_BASE_URL}/pay/{user_id}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Upgrade Now 🚀", url=payment_link)]
    ])

    await update.message.reply_text(
        "Upgrade to Premium 🚀\n\n"
        "• Unlimited alerts (no limits)\n"
        "• Real-time signals\n"
        "• Advanced alerts\n"
        "• Priority access",
        reply_markup=keyboard
    )


def build_upgrade_handlers():
    return [
        CommandHandler("upgrade", upgrade_cmd),
    ]