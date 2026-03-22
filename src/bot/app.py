from __future__ import annotations

import logging
import traceback

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.client import DerivWsClient
from bot.handlers.admin import adminstats_cmd, free_cmd, premium_cmd, setplan_cmd
from bot.handlers.broadcast import build_broadcast_conversation
from bot.handlers.deletealert import deletealert_cb, deletealert_cmd
from bot.handlers.help import build_help_handlers
from bot.handlers.setalert import build_setalert_conversation
from bot.handlers.start import start_cmd
from bot.handlers.status import build_status_handlers
from bot.handlers.upgrade import build_upgrade_handlers
from bot.handlers.viewalerts import myalerts_cmd
from bot.services.alert_engine import AlertEngine
from bot.services.expiry_notifier import ExpiryNotifier
from bot.services.symbol_cache import SymbolCache

LOG = logging.getLogger("bot.app")


async def on_error(update, context) -> None:
    LOG.exception("UNHANDLED ERROR: %s", context.error)
    traceback.print_exc()


async def log_any_callback(update, context) -> None:

    q = getattr(update, "callback_query", None)
    if not q:
        return

    LOG.info(
        "RAW CALLBACK: data=%s from_user=%s chat=%s msg_id=%s",
        q.data,
        getattr(getattr(q, "from_user", None), "id", None),
        getattr(getattr(getattr(q, "message", None), "chat", None), "id", None),
        getattr(getattr(q, "message", None), "message_id", None),
    )


async def cancel_cmd(update: Update, context) -> None:
    if update.message:
        await update.message.reply_text("Cancelled.")


def build_app(settings: Settings) -> Application:

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.bot_data["settings"] = settings

    deriv_client = DerivWsClient(settings.deriv_ws_url, settings.deriv_app_id)
    app.bot_data["deriv_client"] = deriv_client

    symbol_cache = SymbolCache(deriv_client)
    app.bot_data["symbol_cache"] = symbol_cache

    engine = AlertEngine(app)
    app.bot_data["alert_engine"] = engine

    expiry_notifier = ExpiryNotifier(app)
    app.bot_data["expiry_notifier"] = expiry_notifier


    async def _on_start(app: Application):

        LOG.info("Bot starting...")

        db = Database(DbConfig(path=settings.db_path))
        conn = await db.connect()

        try:
            repo = Repo(conn)
            await repo.ensure_schema()
        finally:
            await conn.close()

        await app.bot_data["symbol_cache"].start()

        try:
            await app.bot_data["symbol_cache"].refresh()
        except Exception:
            LOG.exception("Symbol cache warmup failed")

        await app.bot_data["alert_engine"].start()
        await app.bot_data["expiry_notifier"].start()

        LOG.info("Bot started.")


    async def _on_stop(app: Application):

        LOG.info("Bot stopping...")

        try:
            await app.bot_data["expiry_notifier"].stop()
        except Exception:
            LOG.exception("Error stopping expiry notifier")

        try:
            await app.bot_data["alert_engine"].stop()
        except Exception:
            LOG.exception("Error stopping alert engine")

        try:
            await app.bot_data["symbol_cache"].stop()
        except Exception:
            LOG.exception("Error stopping symbol cache")

        LOG.info("Bot stopped.")


    app.post_init = _on_start
    app.post_shutdown = _on_stop

    app.add_error_handler(on_error)

    # ------------------------
    # COMMAND HANDLERS
    # ------------------------

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("myalerts", myalerts_cmd))
    app.add_handler(CommandHandler("deletealert", deletealert_cmd))
    app.add_handler(CommandHandler("adminstats", adminstats_cmd))
    app.add_handler(CommandHandler("setplan", setplan_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("free", free_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))

    for handler in build_status_handlers():
        app.add_handler(handler)

    for handler in build_help_handlers():
        app.add_handler(handler)

    # ------------------------
    # UPGRADE HANDLERS
    # ------------------------

    for handler in build_upgrade_handlers():
        app.add_handler(handler)

    # ------------------------
    # DEBUG CALLBACK LOGGER
    # ------------------------

    app.add_handler(
        CallbackQueryHandler(log_any_callback, pattern=r".*", block=False),
        group=0,
    )

    # ------------------------
    # SET ALERT CONVERSATION
    # ------------------------

    app.add_handler(
        build_setalert_conversation(),
        group=1,
    )

    # ------------------------
    # BROADCAST CONVERSATION
    # ------------------------

    app.add_handler(
        build_broadcast_conversation(),
        group=1,
    )

    # ------------------------
    # DELETE ALERT BUTTON
    # ------------------------

    app.add_handler(
        CallbackQueryHandler(deletealert_cb, pattern=r"^del:"),
        group=2,
    )

    return app