from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from bot.config import load_settings
from bot.db.base import Database, DbConfig
from bot.db.repo import Repo

LOG = logging.getLogger("payment.server")

app = FastAPI(title="Deriv Alert Bot Payments")
settings = load_settings()

PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"


def _user_email(user_id: int) -> str:
    return f"tguser_{user_id}@derivalertbot.local"


async def _repo() -> Repo:
    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()
    repo = Repo(conn)
    await repo.ensure_schema()
    return repo


async def _close_repo(repo: Repo) -> None:
    await repo._conn.close()  # noqa: SLF001


def _build_event_key(
    *,
    event: str,
    reference: str | None,
    subscription_code: str | None,
    customer_code: str | None,
) -> str:
    return f"{event}:{reference or ''}:{subscription_code or ''}:{customer_code or ''}"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/pay/{user_id}")
async def pay(user_id: int):
    if not settings.paystack_secret_key:
        raise HTTPException(status_code=500, detail="PAYSTACK_SECRET_KEY is not configured")
    if not settings.paystack_plan_code:
        raise HTTPException(status_code=500, detail="PAYSTACK_PLAN_CODE is not configured")
    if not settings.payment_base_url:
        raise HTTPException(status_code=500, detail="PAYMENT_BASE_URL is not configured")

    payload: dict[str, Any] = {
        "email": _user_email(user_id),
        "plan": settings.paystack_plan_code,
        "callback_url": f"{settings.payment_base_url}/payment/success",
        "metadata": {
            "telegram_user_id": user_id,
            "product": "deriv_alert_bot_premium",
            "source": "telegram_upgrade",
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(PAYSTACK_INITIALIZE_URL, json=payload, headers=headers)
    except Exception as e:
        LOG.exception("Failed to initialize Paystack subscription: %s", e)
        raise HTTPException(status_code=502, detail="Failed to initialize payment")

    try:
        data = resp.json()
    except Exception:
        LOG.error("Invalid JSON response from Paystack: %s", resp.text[:500])
        raise HTTPException(status_code=502, detail="Invalid response from Paystack")

    if resp.status_code != 200 or not data.get("status"):
        LOG.error("Paystack initialize failed: %s", data)
        raise HTTPException(
            status_code=502,
            detail=data.get("message", "Payment initialization failed"),
        )

    auth_url = data["data"]["authorization_url"]
    return RedirectResponse(url=auth_url, status_code=302)


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request):
    if not settings.paystack_secret_key:
        raise HTTPException(status_code=500, detail="PAYSTACK_SECRET_KEY is not configured")

    raw_body = await request.body()
    received_sig = request.headers.get("x-paystack-signature", "")

    expected_sig = hmac.new(
        settings.paystack_secret_key.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    if not received_sig or not hmac.compare_digest(received_sig, expected_sig):
        LOG.warning("Invalid Paystack webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        body = await request.json()
    except Exception as e:
        LOG.exception("Invalid webhook JSON: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = str(body.get("event", ""))
    data = body.get("data", {}) or {}
    metadata = data.get("metadata", {}) or {}
    subscription = data.get("subscription", {}) or {}
    customer = data.get("customer", {}) or {}

    telegram_user_id = metadata.get("telegram_user_id")
    subscription_code = subscription.get("subscription_code") or data.get("subscription_code")
    email_token = subscription.get("email_token") or data.get("email_token")
    customer_code = customer.get("customer_code") or data.get("customer_code")
    renews_at = (
        subscription.get("next_payment_date")
        or data.get("next_payment_date")
        or data.get("paid_at")
    )
    reference = data.get("reference")

    LOG.info(
        "Paystack webhook event=%s telegram_user_id=%s subscription_code=%s customer_code=%s reference=%s",
        event,
        telegram_user_id,
        subscription_code,
        customer_code,
        reference,
    )

    repo = await _repo()
    try:
        event_key = _build_event_key(
            event=event,
            reference=str(reference) if reference is not None else None,
            subscription_code=str(subscription_code) if subscription_code is not None else None,
            customer_code=str(customer_code) if customer_code is not None else None,
        )

        is_new = await repo.mark_event_processed(event_key)
        if not is_new:
            LOG.info("Duplicate webhook ignored: %s", event_key)
            return JSONResponse({"status": "ok", "action": "duplicate_ignored"})

        # 1) Initial success or recurring success
        if event == "charge.success":
            if telegram_user_id is None and customer_code:
                telegram_user_id = await repo.find_user_id_by_customer_code(str(customer_code))

            if telegram_user_id is None:
                LOG.warning("charge.success received with no mapped telegram user")
                return JSONResponse({"status": "ignored", "reason": "no telegram user mapping"})

            await repo.activate_subscription(
                user_id=int(telegram_user_id),
                customer_code=str(customer_code) if customer_code else None,
                subscription_code=str(subscription_code) if subscription_code else None,
                email_token=str(email_token) if email_token else None,
                renews_at=str(renews_at) if renews_at else None,
            )
            return JSONResponse({"status": "ok", "action": "activated"})

        # 2) Subscription created
        if event == "subscription.create":
            if telegram_user_id is None and customer_code:
                telegram_user_id = await repo.find_user_id_by_customer_code(str(customer_code))

            if telegram_user_id is None:
                LOG.warning("subscription.create received with no mapped telegram user")
                return JSONResponse({"status": "ignored", "reason": "no telegram user mapping"})

            await repo.activate_subscription(
                user_id=int(telegram_user_id),
                customer_code=str(customer_code) if customer_code else None,
                subscription_code=str(subscription_code) if subscription_code else None,
                email_token=str(email_token) if email_token else None,
                renews_at=str(renews_at) if renews_at else None,
            )
            return JSONResponse({"status": "ok", "action": "subscription_created"})

        # 3) Renewal failed
        if event == "invoice.payment_failed":
            await repo.mark_subscription_failed(
                user_id=int(telegram_user_id) if telegram_user_id is not None else None,
                subscription_code=str(subscription_code) if subscription_code else None,
            )
            return JSONResponse({"status": "ok", "action": "marked_failed"})

        # 4) Will not renew
        if event == "subscription.not_renew":
            await repo.mark_subscription_cancelling(
                user_id=int(telegram_user_id) if telegram_user_id is not None else None,
                subscription_code=str(subscription_code) if subscription_code else None,
            )
            return JSONResponse({"status": "ok", "action": "marked_cancelling"})

        # 5) Disabled or ended
        if event == "subscription.disable":
            await repo.disable_subscription(
                user_id=int(telegram_user_id) if telegram_user_id is not None else None,
                subscription_code=str(subscription_code) if subscription_code else None,
            )
            return JSONResponse({"status": "ok", "action": "disabled"})

        return JSONResponse({"status": "ignored", "event": event})

    finally:
        await _close_repo(repo)


@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success() -> str:
    return """
    <html>
        <head><title>Payment Successful</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px;">
            <h2>Payment received</h2>
            <p>Your premium access will activate automatically.</p>
            <p>You can now return to Telegram and continue using the bot.</p>
        </body>
    </html>
    """


@app.get("/payment/cancelled", response_class=HTMLResponse)
async def payment_cancelled() -> str:
    return """
    <html>
        <head><title>Payment Cancelled</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px;">
            <h2>Payment cancelled</h2>
            <p>No payment was completed.</p>
            <p>You can return to Telegram and try again with /upgrade.</p>
        </body>
    </html>
    """