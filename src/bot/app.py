from __future__ import annotations

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.config import Settings
from bot.deriv.client import DerivWsClient
from bot.handlers.admin import free_cmd, premium_cmd, setplan_cmd
from bot.handlers.deletealert import deletealert_cb, deletealert_cmd
from bot.handlers.setalert import build_setalert_conversation
from bot.handlers.start import start_cmd
from bot.handlers.viewalerts import viewalerts_cmd
from bot.services.alert_engine import AlertEngine
from bot.services.symbol_cache import SymbolCache


def build_app(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.bot_data["settings"] = settings

    deriv_client = DerivWsClient(settings.deriv_ws_url, settings.deriv_app_id)
    app.bot_data["deriv_client"] = deriv_client
    app.bot_data["symbol_cache"] = SymbolCache(deriv_client)

    engine = AlertEngine(app)
    app.bot_data["alert_engine"] = engine

    async def _on_start(app: Application):
        await app.bot_data["alert_engine"].start()

    async def _on_stop(app: Application):
        await app.bot_data["alert_engine"].stop()

    app.post_init = _on_start
    app.post_shutdown = _on_stop

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(build_setalert_conversation())

    app.add_handler(CommandHandler("viewalerts", viewalerts_cmd))
    app.add_handler(CommandHandler("deletealert", deletealert_cmd))
    app.add_handler(CallbackQueryHandler(deletealert_cb, pattern=r"^(tog:|act:)"))

    app.add_handler(CommandHandler("setplan", setplan_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("free", free_cmd))

    app.add_handler(CommandHandler("cancel", lambda u, c: u.message.reply_text("Cancelled.")))

    return app