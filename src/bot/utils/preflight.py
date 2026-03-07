from __future__ import annotations

from bot.config import Settings


def preflight(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env")

    if settings.deriv_app_id <= 0:
        raise RuntimeError("Invalid DERIV_APP_ID in .env (must be positive int)")

    if settings.admin_telegram_user_id < 0:
        raise RuntimeError("ADMIN_TELEGRAM_USER_ID must be >= 0")