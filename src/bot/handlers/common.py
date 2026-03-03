from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def nav_keyboard(
    *,
    show_prev: bool,
    show_next: bool,
    show_refresh: bool = True,
    show_back: bool = True,
) -> InlineKeyboardMarkup:
    row = []
    if show_prev:
        row.append(InlineKeyboardButton("⬅ Prev", callback_data="nav:prev"))
    if show_next:
        row.append(InlineKeyboardButton("Next ➡", callback_data="nav:next"))

    rows = []
    if row:
        rows.append(row)

    util_row = []
    if show_refresh:
        util_row.append(InlineKeyboardButton("🔄 Refresh", callback_data="nav:refresh"))
    if show_back:
        util_row.append(InlineKeyboardButton("⬅ Back", callback_data="nav:back"))
    util_row.append(InlineKeyboardButton("✖ Cancel", callback_data="nav:cancel"))
    rows.append(util_row)

    return InlineKeyboardMarkup(rows)