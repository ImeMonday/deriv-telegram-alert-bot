from __future__ import annotations

import json
import time

from fastapi import FastAPI, Request

from bot.db.repo import Repo
from bot.db.base import Database, DbConfig
from bot.config import load_settings

from payment_server.paystack_app.paystack_verify import verify_paystack_signature


app = FastAPI()

settings = load_settings()

START_TIME = time.time()


@app.get("/health")
async def health():

    db = Database(DbConfig(path=settings.db_path))

    try:
        conn = await db.connect()

        async with conn.execute("SELECT 1") as cur:
            await cur.fetchone()

        await conn.close()

        return {
            "status": "ok",
            "service": "paystack-webhook",
            "database": "connected",
            "uptime_seconds": int(time.time() - START_TIME),
        }

    except Exception as e:
        return {
            "status": "degraded",
            "service": "paystack-webhook",
            "database": "error",
            "error": str(e),
        }


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request):

    raw_body = await request.body()

    signature = request.headers.get("x-paystack-signature")

    if not verify_paystack_signature(settings.paystack_secret_key, raw_body, signature):
        return {"status": "invalid signature"}

    body = json.loads(raw_body)

    event = body.get("event")

    if event != "charge.success":
        return {"status": "ignored"}

    data = body.get("data", {})
    metadata = data.get("metadata", {})

    user_id = metadata.get("telegram_user_id")

    if not user_id:
        return {"status": "missing telegram_user_id"}

    event_key = str(data.get("id"))

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)

        processed = await repo.mark_event_processed(event_key)

        if not processed:
            return {"status": "duplicate"}

        await repo.set_user_plan(int(user_id), "premium")

    finally:
        await conn.close()

    return {"status": "ok"}