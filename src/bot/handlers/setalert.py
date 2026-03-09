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
from bot.services.state import SetAlertState
from bot.services.symbol_cache import SymbolCache
from bot.services.limits import can_create_alert

LOG = logging.getLogger("bot.setalert")

KEY_GROUP = "group"
KEY_CATEGORY = "category"
KEY_SYMBOL = "symbol"
KEY_SYMBOL_NAME = "symbol_name"
KEY_PRICE = "price"
KEY_DIRECTION = "direction"
KEY_MODE = "mode"


def group_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Forex Pairs", callback_data="grp:forex")],
            [InlineKeyboardButton("Synthetic Indices", callback_data="grp:synthetic")],
            [InlineKeyboardButton("Cancel", callback_data="nav:cancel")],
        ]
    )


def synthetic_category_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Volatility Indices", callback_data="cat:vol")],
            [InlineKeyboardButton("Boom & Crash", callback_data="cat:boom")],
            [InlineKeyboardButton("Jump Indices", callback_data="cat:jump")],
            [InlineKeyboardButton("Bull & Bear", callback_data="cat:bullbear")],
            [InlineKeyboardButton("Back", callback_data="nav:back")],
        ]
    )


def filter_forex(symbols):
    out = []
    for s in symbols:
        name = getattr(s, "display_name", "")
        sym = getattr(s, "symbol", "")
        if "/" in name or sym.startswith("FRX"):
            out.append(s)
    return sorted(out, key=lambda x: x.display_name)


def filter_synthetic(symbols, category):
    out = []
    for s in symbols:
        sym = getattr(s, "symbol", "").upper()

        if category == "vol" and sym.startswith("R_"):
            out.append(s)

        elif category == "boom" and (sym.startswith("BOOM") or sym.startswith("CRASH")):
            out.append(s)

        elif category == "jump" and sym.startswith("JD"):
            out.append(s)

        elif category == "bullbear" and (sym.startswith("RDBULL") or sym.startswith("RDBEAR")):
            out.append(s)

    return sorted(out, key=lambda x: display_name_for_symbol(x.symbol))


async def get_live_price(symbol: str):
    """
    Professional upgrade #1
    Fetch live Deriv price preview
    """

    from bot.deriv.client import DerivWsClient

    client = DerivWsClient()

    try:
        resp = await client.request(
            {
                "ticks": symbol,
                "subscribe": 0,
            }
        )

        return float(resp["tick"]["quote"])

    except Exception:
        return None


async def setalert_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "Choose market group:",
        reply_markup=group_keyboard(),
    )

    return int(SetAlertState.CHOOSE_GROUP)


async def choose_group(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    data = q.data

    if data == "grp:forex":

        context.user_data[KEY_GROUP] = "forex"

        cache: SymbolCache = context.application.bot_data["symbol_cache"]
        snap = await cache.get()

        symbols = filter_forex(snap.all_symbols)

        rows = []
        for s in symbols[:20]:
            rows.append(
                [InlineKeyboardButton(s.display_name, callback_data=f"sym:{s.symbol}")]
            )

        await q.edit_message_text(
            "Choose forex pair:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

        return int(SetAlertState.CHOOSE_SYMBOL)

    if data == "grp:synthetic":

        context.user_data[KEY_GROUP] = "synthetic"

        await q.edit_message_text(
            "Choose synthetic category:",
            reply_markup=synthetic_category_keyboard(),
        )

        return int(SetAlertState.CHOOSE_SYMBOL)


async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    cat = q.data.split(":")[1]

    context.user_data[KEY_CATEGORY] = cat

    cache: SymbolCache = context.application.bot_data["symbol_cache"]
    snap = await cache.get()

    symbols = filter_synthetic(snap.all_symbols, cat)

    rows = []

    for s in symbols[:20]:

        label = display_name_for_symbol(s.symbol)

        rows.append(
            [InlineKeyboardButton(label, callback_data=f"sym:{s.symbol}")]
        )

    await q.edit_message_text(
        "Choose symbol:",
        reply_markup=InlineKeyboardMarkup(rows),
    )

    return int(SetAlertState.CHOOSE_SYMBOL)


async def symbol_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    symbol = q.data.split(":")[1]

    context.user_data[KEY_SYMBOL] = symbol
    context.user_data[KEY_SYMBOL_NAME] = display_name_for_symbol(symbol)

    live = await get_live_price(symbol)

    price_info = ""
    if live:
        price_info = f"\nCurrent price: {live}"

    await q.edit_message_text(
        f"Selected: {display_name_for_symbol(symbol)}{price_info}\n\n"
        "Send price level."
    )

    return int(SetAlertState.ENTER_PRICE)


async def price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:
        price = float(update.message.text)
    except Exception:
        await update.message.reply_text("Send valid number.")
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


async def direction_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):

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


async def mode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    mode = q.data.split(":")[1]

    context.user_data[KEY_MODE] = mode

    symbol = context.user_data[KEY_SYMBOL]
    price = context.user_data[KEY_PRICE]
    direction = context.user_data[KEY_DIRECTION]

    live = await get_live_price(symbol)

    instant_warning = ""

    if live:
        if direction == "above" and live >= price:
            instant_warning = "\n⚠ Price already above level"

        if direction == "below" and live <= price:
            instant_warning = "\n⚠ Price already below level"

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Confirm Alert", callback_data="cnf:save")]]
    )

    await q.edit_message_text(
        f"Confirm Alert\n\n"
        f"Symbol: {display_name_for_symbol(symbol)}\n"
        f"Current Price: {live}\n"
        f"Target Price: {price}\n"
        f"Direction: {direction}\n"
        f"Mode: {mode}"
        f"{instant_warning}",
        reply_markup=kb,
    )

    return int(SetAlertState.CONFIRM)


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

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

        await repo.upsert_user(user_id)

        plan = await repo.get_user_plan(user_id)
        active = await repo.count_active_alerts(user_id)

        chk = can_create_alert(plan, active)

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
        f"Alert saved #{alert_id}\n\n"
        f"{display_name_for_symbol(symbol)}\n"
        f"Price: {price}\n"
        f"Direction: {direction}\n"
        f"Mode: {mode}"
    )

    return ConversationHandler.END


def build_setalert_conversation():

    return ConversationHandler(
        entry_points=[CommandHandler("setalert", setalert_start)],
        states={
            int(SetAlertState.CHOOSE_GROUP): [
                CallbackQueryHandler(choose_group, pattern="^grp:")
            ],
            int(SetAlertState.CHOOSE_SYMBOL): [
                CallbackQueryHandler(choose_category, pattern="^cat:"),
                CallbackQueryHandler(symbol_selected, pattern="^sym:"),
            ],
            int(SetAlertState.ENTER_PRICE): [
                MessageHandler(filters.TEXT & ~filters.COMMAND, price_entered)
            ],
            int(SetAlertState.CHOOSE_DIRECTION): [
                CallbackQueryHandler(direction_selected, pattern="^dir:")
            ],
            int(SetAlertState.CHOOSE_MODE): [
                CallbackQueryHandler(mode_selected, pattern="^mode:")
            ],
            int(SetAlertState.CONFIRM): [
                CallbackQueryHandler(confirm, pattern="^cnf:")
            ],
        },
        allow_reentry=True,
    )