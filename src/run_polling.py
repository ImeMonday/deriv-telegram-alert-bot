from __future__ import annotations

import logging

from telegram import Update

from bot.app import build_app
from bot.config import load_settings
from bot.utils.logging import setup_logging
from bot.utils.preflight import preflight


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    preflight(settings)

    log = logging.getLogger("bot")
    app = build_app(settings)

    log.info("Starting polling.")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()