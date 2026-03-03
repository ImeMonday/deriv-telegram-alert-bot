from __future__ import annotations

import asyncio
import logging

from bot.app import build_app
from bot.config import load_settings
from bot.utils.logging import setup_logging


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("bot")

    app = build_app(settings)

    log.info("Starting polling (Step 9).")
    await app.run_polling(close_loop=False)


if __name__ == "__main__":
    asyncio.run(main())