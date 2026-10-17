"""Mock KoboToolbox server.

Imitates the parts of the Kobo API v2 the platform uses:
  GET /api/v2/assets/{uid}/data/?format=json&query={"_id":{"$gt":N}}&start=&limit=&sort=
and the REST Service (webhook) that pushes each new submission to the platform.

Submissions come from the synthetic generator and are "released" by a simulated clock:
everything up to SIM_START is available at startup; POST /demo/advance releases the next
collection day; with LIVE_SECONDS > 0 the clock advances by itself.

Field names imitate Kobo's export format; validate against a real Kobo test project before going live.
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date

import httpx
from fastapi import FastAPI, Header, HTTPException, Query

DATA = os.environ.get("SYNTH_DATA", "demo/data/submissions.jsonl")
TOKEN = os.environ.get("KOBO_TOKEN", "demo-token")
ASSET_UID = os.environ.get("KOBO_ASSET_UID", "aDemoPriceForm")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")          # e.g. http://api:8000/ingest/kobo
WEBHOOK_SECRET = os.environ.get("WEBHOOK_HEADER_SECRET", "")   # Kobo REST Services can add a custom header
SIM_START = date.fromisoformat(os.environ.get("SIM_START", "2026-10-16"))
LIVE_SECONDS = float(os.environ.get("LIVE_SECONDS", "0"))

log = logging.getLogger("mock_kobo")


class State:
    def __init__(self):
        with open(DATA) as f:
            self.all = [json.loads(line) for line in f]
        self.all.sort(key=lambda s: s["_id"])
        self.sim_date = SIM_START
        self.webhook_fail = False
        self.webhook_log: list[dict] = []

    def released(self):
        return [s for s in self.all if s["visit_date"] <= self.sim_date.isoformat()]

    def next_visit_date(self):
        later = sorted({s["visit_date"] for s in self.all if s["visit_date"] > self.sim_date.isoformat()})
        return date.fromisoformat(later[0]) if later else None


state = State()


async def push_webhooks(subs):
    if not WEBHOOK_URL:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        for s in subs:
            if state.webhook_fail:
                state.webhook_log.append({"_id": s["_id"], "status": "failed (switched off)"})
                continue
            try:
                headers = {"X-Webhook-Secret": WEBHOOK_SECRET} if WEBHOOK_SECRET else {}
                r = await client.post(WEBHOOK_URL, json=s, headers=headers)
                state.webhook_log.append({"_id": s["_id"], "status": r.status_code})
            except httpx.HTTPError as e:   # like Kobo, a failed delivery is logged, not queued forever
                state.webhook_log.append({"_id": s["_id"], "status": f"error {type(e).__name__}"})
    state.webhook_log[:] = state.webhook_log[-200:]


async def advance(days: int = 1):
    released = []
    for _ in range(days):
        nxt = state.next_visit_date()
        if nxt is None:
            break
        before = {s["_id"] for s in state.released()}
        state.sim_date = nxt
        released += [s for s in state.released() if s["_id"] not in before]
    await push_webhooks(released)
    return released


async def live_loop():
    while True:
        await asyncio.sleep(LIVE_SECONDS)
        await advance(1)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(live_loop()) if LIVE_SECONDS > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Mock KoboToolbox", lifespan=lifespan)


def check_token(authorization: str | None):
    if authorization != f"Token {TOKEN}":
        raise HTTPException(401, "Invalid token")


@app.get("/api/v2/assets/{uid}/data/")
def data(uid: str, query: str = "{}", start: int = 0, limit: int = Query(1000, le=30000),
         sort: str = '{"_id": 1}', authorization: str | None = Header(None)):
    check_token(authorization)
    if uid != ASSET_UID:
        raise HTTPException(404, "Asset not found")
    rows = state.released()
    gt = json.loads(query).get("_id", {}).get("$gt")
    if gt is not None:
        rows = [s for s in rows if s["_id"] > gt]
    if json.loads(sort).get("_id", 1) == -1:
        rows = rows[::-1]
    page = rows[start:start + limit]
    nxt = start + limit < len(rows)
    return {"count": len(rows),
            "next": f"?query={query}&start={start + limit}&limit={limit}" if nxt else None,
            "previous": None, "results": page}


@app.get("/demo/status")
def status():
    return {"sim_date": state.sim_date.isoformat(), "released": len(state.released()), "total": len(state.all),
            "webhook_url": WEBHOOK_URL or None, "webhook_fail": state.webhook_fail,
            "live_seconds": LIVE_SECONDS, "recent_webhooks": state.webhook_log[-10:]}


@app.post("/demo/advance")
async def advance_endpoint(days: int = 1):
    released = await advance(days)
    return {"sim_date": state.sim_date.isoformat(), "released_now": len(released)}


@app.post("/demo/webhook")
def webhook_switch(fail: bool):
    state.webhook_fail = fail
    return {"webhook_fail": fail}
