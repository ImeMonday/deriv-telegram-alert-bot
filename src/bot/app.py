from __future__ import annotations

import logging
import traceback

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.config import Settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo
from bot.deriv.client import DerivWsClient
from bot.handlers.admin import free_cmd, premium_cmd, setplan_cmd, adminstats_cmd
from bot.handlers.deletealert import deletealert_cb, deletealert_cmd
from bot.handlers.setalert import build_setalert_conversation
from bot.handlers.start import start_cmd
from bot.handlers.upgrade import upgrade_cmd
from bot.handlers.viewalerts import viewalerts_cmd
from bot.services.alert_engine import AlertEngine
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


def build_app(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.bot_data["settings"] = settings

    deriv_client = DerivWsClient(settings.deriv_ws_url, settings.deriv_app_id)
    app.bot_data["deriv_client"] = deriv_client

    symbol_cache = SymbolCache(deriv_client)
    app.bot_data["symbol_cache"] = symbol_cache

    engine = AlertEngine(app)
    app.bot_data["alert_engine"] = engine

    async def _on_start(app: Application):
        LOG.info("Bot starting...")

        # Ensure DB schema is fully up to date before any handler/service uses it
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

        LOG.info("Bot started.")

    async def _on_stop(app: Application):
        LOG.info("Bot stopping...")

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

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("viewalerts", viewalerts_cmd))
    app.add_handler(CommandHandler("upgrade", upgrade_cmd))
    app.add_handler(CommandHandler("adminstats", adminstats_cmd))
    app.add_handler(CommandHandler("deletealert", deletealert_cmd))
    app.add_handler(CommandHandler("setplan", setplan_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("free", free_cmd))
    app.add_handler(CommandHandler("cancel", lambda u, c: u.message.reply_text("Cancelled.")))

    # Debug callback logger
    app.add_handler(CallbackQueryHandler(log_any_callback, pattern=r".*", block=False), group=0)

    # Main conversation
    app.add_handler(build_setalert_conversation(), group=1)

    # Other callback handlers
    app.add_handler(CallbackQueryHandler(deletealert_cb, pattern=r"^(tog:|act:)"), group=2)

    return app