from fastapi import FastAPI, Request
from bot.db.repo import Repo
from bot.db.base import Database, DbConfig
from bot.config import load_settings

app = FastAPI()

settings = load_settings()


@app.post("/paystack/webhook")
async def paystack_webhook(request: Request):

    body = await request.json()

    if body["event"] != "charge.success":
        return {"status": "ignored"}

    metadata = body["data"]["metadata"]

    user_id = metadata["telegram_user_id"]

    db = Database(DbConfig(path=settings.db_path))
    conn = await db.connect()

    try:
        repo = Repo(conn)
        await repo.set_user_plan(user_id, "premium")
    finally:
        await conn.close()

    return {"status": "ok"}