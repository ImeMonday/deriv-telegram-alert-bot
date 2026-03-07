from __future__ import annotations

import hashlib
import hmac
import json
import os

import aiosqlite
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.bot.db.repo import Repo

load_dotenv("/opt/telegram-bot/.env")

app = FastAPI()

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_PLAN_CODE = os.getenv("PAYSTACK_PLAN_CODE", "")
PAYMENT_BASE_URL = os.getenv("PAYMENT_BASE_URL", "https://derivalertbot.xyz")

DB_PATH = os.getenv("DB_PATH", "data/bot.db")
DB_ABS_PATH = DB_PATH if DB_PATH.startswith("/") else f"/opt/telegram-bot/{DB_PATH}"


async def _get_repo() -> tuple[aiosqlite.Connection, Repo]:
    conn = await aiosqlite.connect(DB_ABS_PATH)
    repo = Repo(conn)
    await repo.ensure_schema()
    return conn, repo


def _event_key(event: dict) -> str:
    data = event.get("data") or {}
    event_name = str(event.get("event") or "")

    customer = data.get("customer") or {}
    subscription = data.get("subscription") or {}

    candidates = [
        data.get("id"),
        data.get("reference"),
        data.get("subscription_code"),
        subscription.get("subscription_code") if isinstance(subscription, dict) else None,
        customer.get("customer_code") if isinstance(customer, dict) else None,
    ]

    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return f"{event_name}:{candidate}"

    raw = json.dumps(event, sort_keys=True, default=str)
    return f"{event_name}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _extract_user_id_from_metadata(data: dict) -> int | None:
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None

    raw = metadata.get("user_id")
    if raw is None:
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_customer_code(data: dict) -> str | None:
    customer = data.get("customer") or {}
    if isinstance(customer, dict):
        code = customer.get("customer_code")
        if code:
            return str(code)
    return None


def _extract_subscription_code(data: dict) -> str | None:
    code = data.get("subscription_code")
    if code:
        return str(code)

    subscription = data.get("subscription") or {}
    if isinstance(subscription, dict):
        code = subscription.get("subscription_code")
        if code:
            return str(code)

    return None


def _extract_email_token(data: dict) -> str | None:
    email_token = data.get("email_token")
    if email_token:
        return str(email_token)

    subscription = data.get("subscription") or {}
    if isinstance(subscription, dict):
        email_token = subscription.get("email_token")
        if email_token:
            return str(email_token)

    return None


def _extract_next_payment_date(data: dict) -> str | None:
    for key in ("next_payment_date", "paid_at"):
        value = data.get(key)
        if value:
            return str(value)

    subscription = data.get("subscription") or {}
    if isinstance(subscription, dict):
        value = subscription.get("next_payment_date")
        if value:
            return str(value)

    return None


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/pay/{user_id}")
async def pay(user_id: int):
    if not PAYSTACK_SECRET_KEY:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "missing PAYSTACK_SECRET_KEY"},
        )

    url = "https://api.paystack.co/transaction/initialize"

    payload = {
        "email": f"user{user_id}@telegram.local",
        "amount": 500000,
        "callback_url": f"{PAYMENT_BASE_URL}/pay/callback",
        "metadata": {
            "user_id": user_id,
            "source": "telegram_bot",
        },
    }

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)

    try:
        data = resp.json()
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "invalid paystack response", "text": resp.text},
        )

    if resp.status_code >= 400 or not data.get("status"):
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "paystack initialize failed", "details": data},
        )

    auth_url = data.get("data", {}).get("authorization_url")
    if not auth_url:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "missing authorization_url", "details": data},
        )

    return RedirectResponse(auth_url, status_code=302)


@app.get("/pay/callback")
async def pay_callback(reference: str | None = None):
    message = "Payment received. Your access will be updated shortly."
    if reference:
        message += f" Reference: {reference}"
    return JSONResponse({"ok": True, "message": message})


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not PAYSTACK_SECRET_KEY:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "missing PAYSTACK_SECRET_KEY"},
        )

    expected = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "error": "invalid signature"},
        )

    event = await request.json()
    event_name = str(event.get("event") or "")
    data = event.get("data") or {}

    conn, repo = await _get_repo()
    try:
        event_key = _event_key(event)
        inserted = await repo.mark_event_processed(event_key)
        if not inserted:
            return {"ok": True, "duplicate": True}

        user_id = _extract_user_id_from_metadata(data)
        customer_code = _extract_customer_code(data)
        subscription_code = _extract_subscription_code(data)
        email_token = _extract_email_token(data)
        renews_at = _extract_next_payment_date(data)

        if user_id is None and subscription_code:
            user_id = await repo.find_user_id_by_subscription_code(subscription_code)

        if user_id is None and customer_code:
            user_id = await repo.find_user_id_by_customer_code(customer_code)

        if event_name in {"charge.success", "subscription.create"}:
            if user_id is not None:
                await repo.activate_subscription(
                    user_id=user_id,
                    customer_code=customer_code,
                    subscription_code=subscription_code,
                    email_token=email_token,
                    renews_at=renews_at,
                )

        elif event_name in {"invoice.payment_failed"}:
            await repo.mark_subscription_failed(
                user_id=user_id,
                subscription_code=subscription_code,
            )

        elif event_name in {"subscription.not_renew", "subscription.disable"}:
            await repo.mark_subscription_cancelling(
                user_id=user_id,
                subscription_code=subscription_code,
            )

        elif event_name in {"subscription.expiring_cards", "subscription.disable_complete"}:
            await repo.disable_subscription(
                user_id=user_id,
                subscription_code=subscription_code,
            )

        print(
            {
                "paystack_event": event_name,
                "user_id": user_id,
                "customer_code": customer_code,
                "subscription_code": subscription_code,
                "renews_at": renews_at,
            }
        )

        return {"ok": True}

    finally:
        await conn.close()