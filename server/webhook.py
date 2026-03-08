from __future__ import annotations

import json

from fastapi import FastAPI, Request

from bot.db.repo import Repo
from bot.db.base import Database, DbConfig
from bot.config import load_settings

from payment_server.paystack_app.paystack_verify import verify_paystack_signature


app = FastAPI()

settings = load_settings()


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request):

    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")

    # 1) Verify request came from Paystack
    if not verify_paystack_signature(settings.paystack_secret_key, raw_body, signature):
        return {"status": "invalid signature"}

    body = json.loads(raw_body)

    event = body.get("event")

    # 2) Only handle successful charge
    if event != "charge.success":
        return {"status": "ignored"}

    data = body.get("data", {})
    metadata = data.get("metadata", {})

    user_id = metadata.get("telegram_user_id")

    if not user_id:
        return {"status": "missing telegram id"}

    # unique id for this Paystack event
    event_key = str(data.get("id"))

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)

        # 3) Prevent duplicate processing
        processed = await repo.mark_event_processed(event_key)

        if not processed:
            return {"status": "duplicate event"}

        # 4) Activate premium
        await repo.set_user_plan(int(user_id), "premium")

    finally:
        await conn.close()

    return {"status": "ok"}