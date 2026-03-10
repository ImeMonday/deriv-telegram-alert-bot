from __future__ import annotations

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.symbols import display_name_for_symbol, is_synthetic_symbol
from bot.handlers.common import nav_keyboard
from bot.services.limits import can_create_alert
from bot.services.state import SetAlertState
from bot.services.symbol_cache import SymbolCache

LOG = logging.getLogger("bot.setalert")

KEY_GROUP = "sa_group"
KEY_SYMBOL = "sa_symbol"
KEY_SYMBOL_NAME = "sa_symbol_name"
KEY_PRICE = "sa_price"
KEY_DIRECTION = "sa_direction"
KEY_MODE = "sa_mode"
KEY_PAGE = "sa_page"
KEY_QUERY = "sa_query"
KEY_LIST_MSG_ID = "sa_list_msg_id"


def _group_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Forex Pairs", callback_data="grp:forex")],
            [InlineKeyboardButton("Synthetic Indices", callback_data="grp:synthetic")],
            [InlineKeyboardButton("Cancel", callback_data="nav:cancel")],
        ]
    )


def _forex_symbols(all_symbols):
    out = []
    for s in all_symbols:
        symbol = str(getattr(s, "symbol", "") or "")
        display_name = str(getattr(s, "display_name", "") or "")

        if "/" in display_name or symbol.startswith("FRX"):
            out.append(s)

    return sorted(out, key=lambda x: x.display_name)


def _synthetic_symbols(all_symbols):
    out = []

    for s in all_symbols:
        market = str(getattr(s, "market", "") or "").lower()

        
        if market == "synthetic_index":
            out.append(s)

    return sorted(out, key=lambda x: getattr(x, "display_name", ""))

def _search_symbols(items, query):

    q = (query or "").strip().lower()

    if not q:
        return items

    out = []

    for s in items:

        symbol = str(getattr(s, "symbol", "") or "")
        name = str(getattr(s, "display_name", "") or "")
        full = display_name_for_symbol(symbol)

        hay = f"{symbol} {name} {full}".lower()

        if q in hay:
            out.append(s)

    return out


def _paginate(items, page, page_size=12):

    if not items:
        return [], 1

    total_pages = (len(items) + page_size - 1) // page_size

    page = max(0, min(page, total_pages - 1))

    start = page * page_size
    end = start + page_size

    return items[start:end], total_pages


def _build_symbol_page(*, all_symbols, group, query, page):

    if group == "forex":
        items = _forex_symbols(all_symbols)
        title = "Forex Pairs"
    else:
        items = _synthetic_symbols(all_symbols)
        title = "Synthetic Indices"

    filtered = _search_symbols(items, query)

    page_items, total_pages = _paginate(filtered, page)

    rows = []
    row = []

    for s in page_items:

        symbol = str(getattr(s, "symbol", "") or "")

        if group == "synthetic":
            label = display_name_for_symbol(symbol)
        else:
            label = str(getattr(s, "display_name", "") or symbol)

        row.append(
            InlineKeyboardButton(label, callback_data=f"sym:{symbol}")
        )

        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    show_prev = page > 0
    show_next = page < total_pages - 1

    nav = nav_keyboard(
        show_prev=show_prev,
        show_next=show_next,
        show_refresh=True,
        show_back=True,
    )

    for r in nav.inline_keyboard:
        rows.append(r)

    text = (
        f"{title}\n"
        f"Search: {query if query else '(type to search)'}\n"
        f"Page: {page+1}/{total_pages}\n\n"
        "Pick a symbol:"
    )

    return text, InlineKeyboardMarkup(rows), page


async def setalert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.effective_user:
        return ConversationHandler.END

    settings: Settings = context.application.bot_data["settings"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)

        uid = update.effective_user.id

        await repo.upsert_user(uid)

        plan = await repo.get_user_plan(uid)

        active = await repo.count_active_alerts(uid)

    finally:
        await conn.close()

    chk = can_create_alert(plan, active)

    if not chk.allowed:
        await update.message.reply_text(chk.reason)
        return ConversationHandler.END

    context.user_data.clear()

    context.user_data[KEY_PAGE] = 0
    context.user_data[KEY_QUERY] = ""

    await update.message.reply_text(
        "Choose market group:",
        reply_markup=_group_keyboard(),
    )

    return int(SetAlertState.CHOOSE_GROUP)


async def choose_group_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    data = q.data

    if data == "grp:forex":
        context.user_data[KEY_GROUP] = "forex"

    elif data == "grp:synthetic":
        context.user_data[KEY_GROUP] = "synthetic"

    else:
        await q.edit_message_text("Invalid selection.")
        return ConversationHandler.END

    cache: SymbolCache = context.application.bot_data["symbol_cache"]

    snap = await cache.get()

    text, markup, page = _build_symbol_page(
        all_symbols=snap.all_symbols,
        group=context.user_data[KEY_GROUP],
        query="",
        page=0,
    )

    context.user_data[KEY_PAGE] = page

    await q.edit_message_text(text, reply_markup=markup)

    context.user_data[KEY_LIST_MSG_ID] = q.message.message_id

    return int(SetAlertState.CHOOSE_SYMBOL)


async def symbol_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    data = q.data

    if data.startswith("sym:"):

        symbol = data.split(":")[1]

        context.user_data[KEY_SYMBOL] = symbol
        context.user_data[KEY_SYMBOL_NAME] = display_name_for_symbol(symbol)

        await q.edit_message_text(
            f"Selected: {display_name_for_symbol(symbol)}\n\n"
            "Send the price level."
        )

        return int(SetAlertState.ENTER_PRICE)

    if data == "nav:cancel":
        await q.edit_message_text("Cancelled.")
        return ConversationHandler.END

    if data == "nav:back":

        await q.edit_message_text(
            "Choose market group:",
            reply_markup=_group_keyboard(),
        )

        return int(SetAlertState.CHOOSE_GROUP)

    cache: SymbolCache = context.application.bot_data["symbol_cache"]

    snap = await cache.get()

    page = context.user_data.get(KEY_PAGE, 0)

    if data == "nav:next":
        page += 1

    if data == "nav:prev":
        page = max(0, page - 1)

    context.user_data[KEY_PAGE] = page

    text, markup, page = _build_symbol_page(
        all_symbols=snap.all_symbols,
        group=context.user_data[KEY_GROUP],
        query=context.user_data.get(KEY_QUERY, ""),
        page=page,
    )

    context.user_data[KEY_PAGE] = page

    await q.edit_message_text(text, reply_markup=markup)

    return int(SetAlertState.CHOOSE_SYMBOL)


async def price_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):

    raw = update.message.text.strip()

    try:
        price = float(raw)
    except Exception:
        await update.message.reply_text("Send a valid number.")
        return int(SetAlertState.ENTER_PRICE)

    context.user_data[KEY_PRICE] = price

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Above", callback_data="dir:above"),
                InlineKeyboardButton("Below", callback_data="dir:below"),
            ]
        ]
    )

    await update.message.reply_text(
        "Choose direction:",
        reply_markup=kb,
    )

    return int(SetAlertState.CHOOSE_DIRECTION)


async def direction_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    direction = q.data.split(":")[1]

    context.user_data[KEY_DIRECTION] = direction

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("One-time", callback_data="mode:once"),
                InlineKeyboardButton("Repeat", callback_data="mode:repeat"),
            ]
        ]
    )

    await q.edit_message_text(
        "Choose alert mode:",
        reply_markup=kb,
    )

    return int(SetAlertState.CHOOSE_MODE)


async def mode_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    mode = q.data.split(":")[1]

    context.user_data[KEY_MODE] = mode

    symbol = context.user_data[KEY_SYMBOL]
    price = context.user_data[KEY_PRICE]
    direction = context.user_data[KEY_DIRECTION]

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Confirm", callback_data="cnf:save")]]
    )

    await q.edit_message_text(
        f"Confirm alert\n\n"
        f"Symbol: {display_name_for_symbol(symbol)}\n"
        f"Price: {price}\n"
        f"Direction: {direction}\n"
        f"Mode: {mode}",
        reply_markup=kb,
    )

    return int(SetAlertState.CONFIRM)


async def confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    if q.data != "cnf:save":
        return ConversationHandler.END

    user_id = update.effective_user.id

    symbol = context.user_data[KEY_SYMBOL]
    price = context.user_data[KEY_PRICE]
    direction = context.user_data[KEY_DIRECTION]
    mode = context.user_data[KEY_MODE]

    settings: Settings = context.application.bot_data["settings"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:

        repo = Repo(conn)

        alert_id = await repo.create_alert(
            user_id=user_id,
            symbol=symbol,
            price=price,
            direction=direction,
            mode=mode,
        )

    finally:
        await conn.close()

    await q.edit_message_text(
        f"Alert saved #{alert_id}\n\n"
        f"Symbol: {display_name_for_symbol(symbol)}\n"
        f"Price: {price}\n"
        f"Direction: {direction}\n"
        f"Mode: {mode}"
    )

    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Cancelled.")
    elif update.message:
        await update.message.reply_text("Cancelled.")

    return ConversationHandler.END


def build_setalert_conversation() -> ConversationHandler:

    return ConversationHandler(

        entry_points=[
            CommandHandler("setalert", setalert_start)
        ],

        states={

            int(SetAlertState.CHOOSE_GROUP): [
                CallbackQueryHandler(choose_group_cb, pattern=r"^grp:(forex|synthetic)$"),
                CallbackQueryHandler(cancel_cmd, pattern=r"^nav:cancel$")
            ],

            int(SetAlertState.CHOOSE_SYMBOL): [
                CallbackQueryHandler(symbol_cb, pattern=r"^(sym:|nav:)")
            ],

            int(SetAlertState.ENTER_PRICE): [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_msg)
            ],

            int(SetAlertState.CHOOSE_DIRECTION): [
                CallbackQueryHandler(direction_cb, pattern=r"^dir:")
            ],

            int(SetAlertState.CHOOSE_MODE): [
                CallbackQueryHandler(mode_cb, pattern=r"^mode:")
            ],

            int(SetAlertState.CONFIRM): [
                CallbackQueryHandler(confirm_cb, pattern=r"^cnf:")
            ],
        },

        fallbacks=[
            CommandHandler("cancel", cancel_cmd)
        ],

        allow_reentry=True,
    )