from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    deriv_app_id: int
    admin_telegram_user_id: int
    db_path: Path
    log_level: str
    deriv_ws_url: str


def load_settings() -> Settings:
    load_dotenv(override=False)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in .env")

    deriv_app_id = int(os.getenv("DERIV_APP_ID", "1089"))
    admin_id = int(os.getenv("ADMIN_TELEGRAM_USER_ID", "0"))

    db_path = Path(os.getenv("DB_PATH", "./data/bot.db")).resolve()
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    deriv_ws_url = os.getenv(
        "DERIV_WS_URL",
        "wss://ws.derivws.com/websockets/v3"
    ).strip()

    return Settings(
        telegram_bot_token=token,
        deriv_app_id=deriv_app_id,
        admin_telegram_user_id=admin_id,
        db_path=db_path,
        log_level=log_level,
        deriv_ws_url=deriv_ws_url,
    )