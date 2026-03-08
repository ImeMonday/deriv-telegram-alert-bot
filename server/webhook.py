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

    # verify webhook came from Paystack
    if not verify_paystack_signature(settings.paystack_secret_key, raw_body, signature):
        return {"status": "invalid signature"}

    body = json.loads(raw_body)

    # only process successful charge events
    if body.get("event") != "charge.success":
        return {"status": "ignored"}

    data = body.get("data", {})

    metadata = data.get("metadata", {})

    user_id = metadata.get("telegram_user_id")

    if not user_id:
        return {"status": "missing telegram id"}

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)

        await repo.set_user_plan(int(user_id), "premium")

    finally:
        await conn.close()

    return {"status": "ok"}