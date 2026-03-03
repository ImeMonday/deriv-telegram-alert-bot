from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo

KEY_SELECTED = "da_selected"


def _render(alerts, selected: set[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for a in alerts[:30]:
        mark = "✅" if a.id in selected else "⬜"
        label = f"{mark} #{a.id} {a.symbol} {str(a.direction).upper()} {a.price} ({a.mode})"
        rows.append([InlineKeyboardButton(label, callback_data=f"tog:{a.id}")])

    rows.append(
        [
            InlineKeyboardButton("🗑 Deactivate Selected", callback_data="act:delete"),
            InlineKeyboardButton("Clear", callback_data="act:clear"),
        ]
    )
    rows.append([InlineKeyboardButton("✖ Cancel", callback_data="act:cancel")])

    return InlineKeyboardMarkup(rows)


async def deletealert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = int(update.effective_user.id)
    context.user_data[KEY_SELECTED] = set()

    settings: Settings = context.application.bot_data["settings"]
    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    try:
        repo = Repo(conn)
        await repo.upsert_user(user_id)
        alerts = await repo.list_alerts(user_id=user_id, active_only=True)
    finally:
        await conn.close()

    if not alerts:
        await update.message.reply_text("No active alerts to delete.")
        return

    await update.message.reply_text(
        "Select alerts to deactivate. Tap to toggle:",
        reply_markup=_render(alerts, set()),
    )


async def deletealert_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    user_id = int(update.effective_user.id)
    data = q.data or ""

    selected: set[int] = context.user_data.get(KEY_SELECTED) or set()
    context.user_data[KEY_SELECTED] = selected

    settings: Settings = context.application.bot_data["settings"]
    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    try:
        repo = Repo(conn)
        alerts = await repo.list_alerts(user_id=user_id, active_only=True)

        if data.startswith("tog:"):
            aid = int(data.split(":", 1)[1])
            if aid in selected:
                selected.remove(aid)
            else:
                selected.add(aid)
            await q.edit_message_reply_markup(reply_markup=_render(alerts, selected))
            return

        if data == "act:clear":
            selected.clear()
            await q.edit_message_reply_markup(reply_markup=_render(alerts, selected))
            return

        if data == "act:cancel":
            selected.clear()
            await q.edit_message_text("Cancelled.")
            return

        if data == "act:delete":
            if not selected:
                await q.edit_message_text("No alerts selected.")
                return
            n = await repo.deactivate_alerts(user_id=user_id, alert_ids=sorted(selected))
            selected.clear()
            await q.edit_message_text(f"Deactivated {n} alert(s). Use /viewalerts to confirm.")
            return

        await q.edit_message_text("Invalid action.")
    finally:
        await conn.close()