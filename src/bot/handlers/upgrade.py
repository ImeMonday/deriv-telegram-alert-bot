from __future__ import annotations

import re

import aiosqlite
from telegram import ForceReply, Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from bot.config import Settings
from bot.db.repo import Repo

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

    conn = await aiosqlite.connect(settings.db_path)
    try:
        repo = Repo(conn)
        await repo.ensure_schema()

        saved_email = await repo.get_user_email(user.id)

        if saved_email:
            payment_link = f"{settings.payment_base_url}/pay/{user.id}"
            await update.message.reply_text(
                "Premium Plan\n\n"
                "Unlimited alerts\n"
                "Price: $5/month\n\n"
                f"Email: {saved_email}\n\n"
                f"Pay here:\n{payment_link}"
            )
            return
    finally:
        await conn.close()

    context.user_data["awaiting_upgrade_email"] = True

    await update.message.reply_text(
        "Send the email you want to use for payment.",
        reply_markup=ForceReply(selective=True),
    )


async def upgrade_email_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if not context.user_data.get("awaiting_upgrade_email"):
        return

    user = update.effective_user
    if not user:
        return

    email = (update.message.text or "").strip().lower()

    if not EMAIL_RE.match(email):
        await update.message.reply_text("Invalid email. Send a valid email address.")
        return

    settings: Settings = context.application.bot_data["settings"]

    conn = await aiosqlite.connect(settings.db_path)
    try:
        repo = Repo(conn)
        await repo.ensure_schema()
        await repo.set_user_email(user.id, email)
    finally:
        await conn.close()

    context.user_data["awaiting_upgrade_email"] = False

    payment_link = f"{settings.payment_base_url}/pay/{user.id}"

    await update.message.reply_text(
        "Email saved.\n\n"
        "Premium Plan\n"
        "Unlimited alerts\n"
        "Price: $5/month\n\n"
        f"Pay here:\n{payment_link}"
    )


def build_upgrade_handlers():
    return [
        CommandHandler("upgrade", upgrade_cmd),
        MessageHandler(filters.TEXT & ~filters.COMMAND, upgrade_email_reply),
    ]