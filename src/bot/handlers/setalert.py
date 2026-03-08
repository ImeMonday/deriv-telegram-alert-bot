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


async def _edit_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup,
) -> None:
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=reply_markup,
    )


def _forex_symbols(all_symbols) -> list:
    out = []
    for s in all_symbols:
        symbol = str(getattr(s, "symbol", "") or "")
        display_name = str(getattr(s, "display_name", "") or "")
        if "/" in display_name or symbol.upper().startswith("FRX"):
            out.append(s)
    return out


def _synthetic_symbols(all_symbols) -> list:
    out = []
    for s in all_symbols:
        symbol = str(getattr(s, "symbol", "") or "")
        if is_synthetic_symbol(symbol):
            out.append(s)
    return out


def _search_symbols(items: list, query: str) -> list:
    q = (query or "").strip().lower()
    if not q:
        return items

    out = []
    for s in items:
        symbol = str(getattr(s, "symbol", "") or "")
        display_name = str(getattr(s, "display_name", "") or "")
        full_name = display_name_for_symbol(symbol)
        hay = f"{symbol} {display_name} {full_name}".lower()
        if q in hay:
            out.append(s)
    return out


def _paginate(items: list, page: int, page_size: int = 12) -> tuple[list, int]:
    if not items:
        return [], 1

    total_pages = (len(items) + page_size - 1) // page_size
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    end = start + page_size
    return items[start:end], total_pages


def _build_symbol_page(*, all_symbols, group: str, query: str, page: int, page_size: int = 12):
    if group == "forex":
        items = _forex_symbols(all_symbols)
        title = "Forex Pairs"
        sort_key = lambda s: str(getattr(s, "display_name", "") or getattr(s, "symbol", "")).lower()
    else:
        items = _synthetic_symbols(all_symbols)
        title = "Synthetic Indices"
        sort_key = lambda s: display_name_for_symbol(str(getattr(s, "symbol", "") or "")).lower()

    items = sorted(items, key=sort_key)
    filtered = _search_symbols(items, query)
    page_items, total_pages = _paginate(filtered, page, page_size=page_size)

    rows = []
    row = []
    for s in page_items:
        symbol = str(getattr(s, "symbol", "") or "")
        if group == "synthetic":
            label = display_name_for_symbol(symbol)
        else:
            label = str(getattr(s, "display_name", "") or symbol)

        row.append(InlineKeyboardButton(label, callback_data=f"sym:{symbol}"))
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    show_prev = page > 0
    show_next = page < (total_pages - 1)
    nav = nav_keyboard(show_prev=show_prev, show_next=show_next, show_refresh=True, show_back=True)
    for r in nav.inline_keyboard:
        rows.append(r)

    if not filtered:
        text = (
            f"{title}\n"
            f"Search: {query if query else '(type to search)'}\n"
            f"Page: 1/1\n\n"
            "No symbols found. Type to search again or tap Back."
        )
    else:
        text = (
            f"{title}\n"
            f"Search: {query if query else '(type to search)'}\n"
            f"Page: {page + 1}/{total_pages}\n\n"
            "Pick a symbol:"
        )

    return text, InlineKeyboardMarkup(rows), page, total_pages


async def setalert_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return ConversationHandler.END

    settings: Settings = context.application.bot_data["settings"]
    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    try:
        repo = Repo(conn)
        uid = int(update.effective_user.id)
        await repo.upsert_user(uid)
        plan = await repo.get_user_plan(uid)
        active_count = await repo.count_active_alerts(uid)
    finally:
        await conn.close()

    chk = can_create_alert(plan, active_count)
    if not chk.allowed:
        await update.message.reply_text(chk.reason)
        return ConversationHandler.END

    for k in (
        KEY_GROUP,
        KEY_SYMBOL,
        KEY_SYMBOL_NAME,
        KEY_PRICE,
        KEY_DIRECTION,
        KEY_MODE,
        KEY_LIST_MSG_ID,
    ):
        context.user_data.pop(k, None)

    context.user_data[KEY_PAGE] = 0
    context.user_data[KEY_QUERY] = ""

    await update.message.reply_text("Choose market group:", reply_markup=_group_keyboard())
    return int(SetAlertState.CHOOSE_GROUP)


async def cancel_from_group_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END

    await q.answer()
    await q.edit_message_text("Cancelled.")
    return ConversationHandler.END


async def choose_group_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END

    await q.answer()
    data = q.data or ""
    LOG.info("choose_group_cb callback_data=%s", data)

    if data == "grp:forex":
        context.user_data[KEY_GROUP] = "forex"
    elif data == "grp:synthetic":
        context.user_data[KEY_GROUP] = "synthetic"
    else:
        await q.edit_message_text("Invalid selection. Use /setalert again.")
        return ConversationHandler.END

    context.user_data[KEY_PAGE] = 0
    context.user_data[KEY_QUERY] = ""

    cache: SymbolCache = context.application.bot_data["symbol_cache"]
    snap = await cache.get()

    text, markup, page, _ = _build_symbol_page(
        all_symbols=snap.all_symbols,
        group=str(context.user_data.get(KEY_GROUP)),
        query=str(context.user_data.get(KEY_QUERY, "")),
        page=int(context.user_data.get(KEY_PAGE, 0)),
    )
    context.user_data[KEY_PAGE] = page

    await q.edit_message_text(text, reply_markup=markup)

    if q.message:
        context.user_data[KEY_LIST_MSG_ID] = q.message.message_id

    return int(SetAlertState.CHOOSE_SYMBOL)


async def symbol_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END

    await q.answer()
    data = q.data or ""

    if data == "nav:cancel":
        await q.edit_message_text("Cancelled.")
        return ConversationHandler.END

    if data == "nav:back":
        await q.edit_message_text("Choose market group:", reply_markup=_group_keyboard())
        return int(SetAlertState.CHOOSE_GROUP)

    if data == "nav:refresh":
        cache: SymbolCache = context.application.bot_data["symbol_cache"]
        snap = await cache.refresh()
        context.user_data[KEY_PAGE] = 0

        text, markup, page, _ = _build_symbol_page(
            all_symbols=snap.all_symbols,
            group=str(context.user_data.get(KEY_GROUP)),
            query=str(context.user_data.get(KEY_QUERY, "")),
            page=int(context.user_data.get(KEY_PAGE, 0)),
        )
        context.user_data[KEY_PAGE] = page
        await q.edit_message_text(text, reply_markup=markup)
        return int(SetAlertState.CHOOSE_SYMBOL)

    if data == "nav:next":
        context.user_data[KEY_PAGE] = int(context.user_data.get(KEY_PAGE, 0)) + 1
    elif data == "nav:prev":
        context.user_data[KEY_PAGE] = max(0, int(context.user_data.get(KEY_PAGE, 0)) - 1)

    if data.startswith("nav:"):
        cache: SymbolCache = context.application.bot_data["symbol_cache"]
        snap = await cache.get()

        text, markup, page, _ = _build_symbol_page(
            all_symbols=snap.all_symbols,
            group=str(context.user_data.get(KEY_GROUP)),
            query=str(context.user_data.get(KEY_QUERY, "")),
            page=int(context.user_data.get(KEY_PAGE, 0)),
        )
        context.user_data[KEY_PAGE] = page
        await q.edit_message_text(text, reply_markup=markup)
        return int(SetAlertState.CHOOSE_SYMBOL)

    if data.startswith("sym:"):
        symbol = data.split(":", 1)[1].strip()
        context.user_data[KEY_SYMBOL] = symbol
        context.user_data[KEY_SYMBOL_NAME] = display_name_for_symbol(symbol)

        await q.edit_message_text(
            f"Selected: {display_name_for_symbol(symbol)}\n\n"
            "Send the price level as a number.\n"
            "Example: 1.2500 or 250.5\n\n"
            "Send /cancel to stop."
        )
        return int(SetAlertState.ENTER_PRICE)

    await q.edit_message_text("Invalid action. Use /setalert again.")
    return ConversationHandler.END


async def symbol_search_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    text_in = (update.message.text or "").strip()
    context.user_data[KEY_QUERY] = text_in
    context.user_data[KEY_PAGE] = 0

    msg_id = context.user_data.get(KEY_LIST_MSG_ID)
    chat = update.effective_chat
    if not chat or not isinstance(msg_id, int):
        await update.message.reply_text("Pick a symbol from the list.")
        return int(SetAlertState.CHOOSE_SYMBOL)

    cache: SymbolCache = context.application.bot_data["symbol_cache"]
    snap = await cache.get()

    text, markup, page, _ = _build_symbol_page(
        all_symbols=snap.all_symbols,
        group=str(context.user_data.get(KEY_GROUP)),
        query=str(context.user_data.get(KEY_QUERY, "")),
        page=int(context.user_data.get(KEY_PAGE, 0)),
    )
    context.user_data[KEY_PAGE] = page

    await _edit_message(context, chat.id, msg_id, text, markup)

    try:
        await update.message.delete()
    except Exception:
        pass

    return int(SetAlertState.CHOOSE_SYMBOL)


async def price_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END

    raw = (update.message.text or "").strip()
    try:
        price = float(raw)
        if price <= 0:
            raise ValueError("non-positive")
    except Exception:
        await update.message.reply_text("Invalid price. Send a positive number like 1.2500 or 250.5.")
        return int(SetAlertState.ENTER_PRICE)

    context.user_data[KEY_PRICE] = price

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Above", callback_data="dir:above"),
                InlineKeyboardButton("Below", callback_data="dir:below"),
            ],
            [
                InlineKeyboardButton("Back", callback_data="nav:back_price"),
                InlineKeyboardButton("Cancel", callback_data="nav:cancel"),
            ],
        ]
    )
    await update.message.reply_text("Choose direction:", reply_markup=kb)
    return int(SetAlertState.CHOOSE_DIRECTION)


async def direction_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END

    await q.answer()
    data = q.data or ""

    if data == "nav:cancel":
        await q.edit_message_text("Cancelled.")
        return ConversationHandler.END

    if data == "nav:back_price":
        await q.edit_message_text("Send the price level as a number.")
        return int(SetAlertState.ENTER_PRICE)

    if data not in ("dir:above", "dir:below"):
        await q.edit_message_text("Invalid. Use /setalert again.")
        return ConversationHandler.END

    context.user_data[KEY_DIRECTION] = data.split(":", 1)[1]

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("One-time", callback_data="mode:once"),
                InlineKeyboardButton("Repeat", callback_data="mode:repeat"),
            ],
            [
                InlineKeyboardButton("Back", callback_data="nav:back_dir"),
                InlineKeyboardButton("Cancel", callback_data="nav:cancel"),
            ],
        ]
    )
    await q.edit_message_text("Choose alert mode:", reply_markup=kb)
    return int(SetAlertState.CHOOSE_MODE)


async def mode_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END

    await q.answer()
    data = q.data or ""

    if data == "nav:cancel":
        await q.edit_message_text("Cancelled.")
        return ConversationHandler.END

    if data == "nav:back_dir":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Above", callback_data="dir:above"),
                    InlineKeyboardButton("Below", callback_data="dir:below"),
                ],
                [
                    InlineKeyboardButton("Back", callback_data="nav:back_price"),
                    InlineKeyboardButton("Cancel", callback_data="nav:cancel"),
                ],
            ]
        )
        await q.edit_message_text("Choose direction:", reply_markup=kb)
        return int(SetAlertState.CHOOSE_DIRECTION)

    if data not in ("mode:once", "mode:repeat"):
        await q.edit_message_text("Invalid. Use /setalert again.")
        return ConversationHandler.END

    context.user_data[KEY_MODE] = data.split(":", 1)[1]

    symbol_name = context.user_data.get(KEY_SYMBOL_NAME) or context.user_data.get(KEY_SYMBOL)
    price = context.user_data.get(KEY_PRICE)
    direction = context.user_data.get(KEY_DIRECTION)
    mode = context.user_data.get(KEY_MODE)

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Confirm & Save", callback_data="cnf:save")],
            [
                InlineKeyboardButton("Back", callback_data="nav:back_mode"),
                InlineKeyboardButton("Cancel", callback_data="nav:cancel"),
            ],
        ]
    )

    await q.edit_message_text(
        "Confirm alert:\n"
        f"Symbol: {symbol_name}\n"
        f"Price: {price}\n"
        f"Direction: {str(direction).upper()}\n"
        f"Mode: {mode}\n",
        reply_markup=kb,
    )
    return int(SetAlertState.CONFIRM)


async def confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q or not update.effective_user:
        return ConversationHandler.END

    await q.answer()
    data = q.data or ""

    if data == "nav:cancel":
        await q.edit_message_text("Cancelled.")
        return ConversationHandler.END

    if data == "nav:back_mode":
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("One-time", callback_data="mode:once"),
                    InlineKeyboardButton("Repeat", callback_data="mode:repeat"),
                ],
                [
                    InlineKeyboardButton("Back", callback_data="nav:back_dir"),
                    InlineKeyboardButton("Cancel", callback_data="nav:cancel"),
                ],
            ]
        )
        await q.edit_message_text("Choose alert mode:", reply_markup=kb)
        return int(SetAlertState.CHOOSE_MODE)

    if data != "cnf:save":
        await q.edit_message_text("Invalid. Use /setalert again.")
        return ConversationHandler.END

    user_id = int(update.effective_user.id)
    symbol = str(context.user_data.get(KEY_SYMBOL))
    symbol_name = str(context.user_data.get(KEY_SYMBOL_NAME) or symbol)
    price = float(context.user_data.get(KEY_PRICE))
    direction = str(context.user_data.get(KEY_DIRECTION))
    mode = str(context.user_data.get(KEY_MODE))

    settings: Settings = context.application.bot_data["settings"]
    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    try:
        repo = Repo(conn)
        await repo.upsert_user(user_id)

        plan = await repo.get_user_plan(user_id)
        active_count = await repo.count_active_alerts(user_id)
        chk = can_create_alert(plan, active_count)
        if not chk.allowed:
            await q.edit_message_text(chk.reason)
            return ConversationHandler.END

        alert_id = await repo.create_alert(
            user_id=user_id,
            symbol=symbol,
            price=price,
            direction=direction,
            mode=mode,
            cooldown_seconds=30,
        )
    finally:
        await conn.close()

    await q.edit_message_text(
        f"Saved alert #{alert_id} ✅\n\n"
        f"Symbol: {symbol_name}\n"
        f"Price: {price}\n"
        f"Direction: {direction.upper()}\n"
        f"Mode: {mode}\n\n"
        "Use /myalerts to see your alerts."
    )
    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


def build_setalert_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setalert", setalert_start)],
        states={
            int(SetAlertState.CHOOSE_GROUP): [
                CallbackQueryHandler(choose_group_cb, pattern=r"^grp:(forex|synthetic)$"),
                CallbackQueryHandler(cancel_from_group_cb, pattern=r"^nav:cancel$"),
            ],
            int(SetAlertState.CHOOSE_SYMBOL): [
                CallbackQueryHandler(symbol_cb, pattern=r"^(sym:|nav:)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, symbol_search_msg),
            ],
            int(SetAlertState.ENTER_PRICE): [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_msg),
            ],
            int(SetAlertState.CHOOSE_DIRECTION): [
                CallbackQueryHandler(direction_cb, pattern=r"^(dir:|nav:)"),
            ],
            int(SetAlertState.CHOOSE_MODE): [
                CallbackQueryHandler(mode_cb, pattern=r"^(mode:|nav:)"),
            ],
            int(SetAlertState.CONFIRM): [
                CallbackQueryHandler(confirm_cb, pattern=r"^(cnf:|nav:)"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        allow_reentry=True,
        per_message=False,
    )