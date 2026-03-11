from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    deriv_ws_url: str
    deriv_app_id: int
    db_path: Path
    log_level: str
    admin_telegram_user_ids: list[int]

    paystack_secret_key: str
    paystack_public_key: str
    payment_base_url: str
    paystack_plan_code: str


def load_settings() -> Settings:

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    deriv_ws_url = os.getenv(
        "DERIV_WS_URL",
        "wss://ws.derivws.com/websockets/v3",
    ).strip()

    deriv_app_id = int(os.getenv("DERIV_APP_ID", "0"))

    db_path = Path(os.getenv("DB_PATH", "data/bot.db").strip())

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    admin_telegram_user_ids = [
        int(x.strip())
        for x in os.getenv("ADMIN_TELEGRAM_USER_IDS", "").split(",")
        if x.strip()
    ]

    paystack_secret_key = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
    paystack_public_key = os.getenv("PAYSTACK_PUBLIC_KEY", "").strip()
    payment_base_url = os.getenv("PAYMENT_BASE_URL", "").strip().rstrip("/")
    paystack_plan_code = os.getenv("PAYSTACK_PLAN_CODE", "").strip()

    return Settings(
        telegram_bot_token=telegram_bot_token,
        deriv_ws_url=deriv_ws_url,
        deriv_app_id=deriv_app_id,
        db_path=db_path,
        log_level=log_level,
        admin_telegram_user_ids=admin_telegram_user_ids,
        paystack_secret_key=paystack_secret_key,
        paystack_public_key=paystack_public_key,
        payment_base_url=payment_base_url,
        paystack_plan_code=paystack_plan_code,
    )