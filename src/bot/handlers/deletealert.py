from __future__ import annotations

import aiosqlite
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db.repo import Alert, Repo
from bot.deriv.symbols import display_name_for_symbol


def _active_alert_buttons(alerts: list[Alert]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for alert in alerts[:30]:
        label = f"❌ #{alert.id} {display_name_for_symbol(alert.symbol)}"
        rows.append([InlineKeyboardButton(label, callback_data=f"del:{alert.id}")])

    rows.append([InlineKeyboardButton("❌ Delete all active alerts", callback_data="del:all")])
    rows.append([InlineKeyboardButton("Close", callback_data="del:close")])
    return InlineKeyboardMarkup(rows)


async def deletealert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = int(update.effective_user.id)
    settings: Settings = context.application.bot_data["settings"]

    conn = await aiosqlite.connect(settings.db_path)
    try:
        repo = Repo(conn)
        await repo.ensure_schema()
        await repo.upsert_user(user_id)
        alerts = await repo.list_user_alerts(user_id)
        active_alerts = [a for a in alerts if a.active == 1]
    finally:
        await conn.close()

    if not active_alerts:
        await update.message.reply_text("No active alerts to delete.")
        return

    await update.message.reply_text(
        "Select the alert you want to delete:",
        reply_markup=_active_alert_buttons(active_alerts),
    )


async def deletealert_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return

    await q.answer()

    user = q.from_user
    if not user:
        return

    data = q.data or ""
    if not data.startswith("del:"):
        return

    action = data.removeprefix("del:")
    if action == "close":
        await q.edit_message_text("Closed.")
        return

    settings: Settings = context.application.bot_data["settings"]

    conn = await aiosqlite.connect(settings.db_path)
    try:
        repo = Repo(conn)
        await repo.ensure_schema()

        if action == "all":
            alerts = await repo.list_user_alerts(user.id)
            active_ids = [a.id for a in alerts if a.active == 1]
            deleted = await repo.deactivate_alerts(user.id, active_ids)
            await q.edit_message_text(f"Deleted {deleted} active alert(s).")
            return

        try:
            alert_id = int(action)
        except ValueError:
            await q.edit_message_text("Invalid alert selection.")
            return

        deleted = await repo.deactivate_alerts(user.id, [alert_id])
        if deleted == 0:
            await q.edit_message_text("That alert was not found or is already inactive.")
            return

        alerts = await repo.list_user_alerts(user.id)
        active_alerts = [a for a in alerts if a.active == 1]

        if not active_alerts:
            await q.edit_message_text(f"Alert #{alert_id} deleted. No active alerts left.")
            return

        await q.edit_message_text(
            f"Alert #{alert_id} deleted.\n\nSelect another alert to delete:",
            reply_markup=_active_alert_buttons(active_alerts),
        )
    finally:
        await conn.close()