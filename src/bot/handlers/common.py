from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

LOG = logging.getLogger("bot.handlers.common")


def nav_keyboard(
    *,
    show_prev: bool,
    show_next: bool,
    show_refresh: bool = True,
    show_back: bool = True,
) -> InlineKeyboardMarkup:
    """
    Build navigation keyboard for pagination and control.
    
    Args:
        show_prev: Show previous page button
        show_next: Show next page button
        show_refresh: Show refresh button (default: True)
        show_back: Show back button (default: True)
    
    Returns:
        InlineKeyboardMarkup with navigation buttons
    """
    rows = []

    # Navigation row (Prev/Next)
    nav_row = []
    if show_prev:
        nav_row.append(InlineKeyboardButton("◀ Prev", callback_data="nav:prev"))
    if show_next:
        nav_row.append(InlineKeyboardButton("Next ▶", callback_data="nav:next"))
    if nav_row:
        rows.append(nav_row)

    # Utility row (Refresh/Back/Cancel)
    util_row = []
    if show_refresh:
        util_row.append(InlineKeyboardButton("🔄 Refresh", callback_data="nav:refresh"))
    if show_back:
        util_row.append(InlineKeyboardButton("↩ Back", callback_data="nav:back"))
    util_row.append(InlineKeyboardButton("❌ Cancel", callback_data="nav:cancel"))
    rows.append(util_row)

    LOG.debug("Built nav_keyboard with %d rows", len(rows))
    return InlineKeyboardMarkup(rows)
