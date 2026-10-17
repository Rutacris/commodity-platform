"""Platform API: dashboard data, QC review, live stream (SSE) and the Kobo webhook.

Run: uvicorn pipeline.api:app --port 8000
"""
import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import timedelta

import psycopg
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from pipeline import analytics, config, ingest
from pipeline.db import connect

log = logging.getLogger("api")
STATIC = os.path.join(os.path.dirname(__file__), "static")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DEMO = config.INCLUDE_DEMO_MIGRATIONS


# ── Live stream: one LISTEN connection fanned out to SSE subscribers ─────────────
class Broadcaster:
    def __init__(self):
        self.queues: set[asyncio.Queue] = set()

    async def listen(self):
        while True:   # reconnect forever; clients refetch on every event, so a missed one only delays
            try:
                async with await psycopg.AsyncConnection.connect(config.DATABASE_URL, autocommit=True) as conn:
                    await conn.execute("LISTEN prices")
                    async for n in conn.notifies():
                        for q in list(self.queues):
                            q.put_nowait(n.payload)
            except Exception:
                log.exception("LISTEN connection lost; retrying")
                await asyncio.sleep(3)


broadcaster = Broadcaster()


# ── Processing after webhooks: run in a thread, coalesce bursts ───────────────────
class Processor:
    def __init__(self):
        self.lock = threading.Lock()
        self.again = False

    def run(self):
        if not self.lock.acquire(blocking=False):
            self.again = True
            return
        try:
            while True:
                self.again = False
                with connect() as conn:
                    done = ingest.process_pending(conn)
                if done:
                    analytics.recompute()
                if not self.again:
                    break
        finally:
            self.lock.release()


processor = Processor()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(broadcaster.listen())
    yield
    task.cancel()


app = FastAPI(title="Kigali Price Monitor", lifespan=lifespan)


def q(sql: str, params=None) -> list[dict]:
    with connect() as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return cur.execute(sql, params).fetchall()


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/health")
def health():
    q("SELECT 1")
    return {"ok": True}


# ── Kobo webhook ──────────────────────────────────────────────────────────────────
@app.post("/ingest/kobo", status_code=201)
async def kobo_webhook(request: Request, tasks: BackgroundTasks, x_webhook_secret: str | None = Header(None)):
    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(401, "bad secret")
    payload = await request.json()
    with connect() as conn:
        new = ingest.store_raw(conn, payload, "webhook")
    tasks.add_task(processor.run)
    return {"stored": new}


# ── Dashboard data ────────────────────────────────────────────────────────────────
@app.get("/api/overview")
def overview():
    latest = q("SELECT max(week) AS week FROM serving.weekly_metrics WHERE market_id = 0")[0]["week"]
    if latest is None:
        return {"week": None, "rows": [], "movers": []}
    rows = q("""
        SELECT c.code, c.name_en, c.name_rw, c.name_fr, c.category, c.std_unit, w.price, w.pct_wow, w.pct_4w,
               w.anomaly, w.z_level, w.n_quotes,
               (SELECT json_agg(round(s.price::numeric) ORDER BY s.week) FROM serving.weekly_metrics s
                WHERE s.commodity_id = c.id AND s.market_id = 0 AND s.week > %(w)s::date - 26 * 7) AS spark
        FROM ref.commodities c
        LEFT JOIN serving.weekly_metrics w ON w.commodity_id = c.id AND w.market_id = 0 AND w.week = %(w)s
        ORDER BY c.id""", {"w": latest})
    movers = sorted([r for r in rows if r["pct_4w"] is not None], key=lambda r: r["pct_4w"])
    status = q("""
        SELECT (SELECT max(visit_date) FROM core.visits) AS last_visit,
               (SELECT max(received_at) FROM raw.kobo_submissions) AS last_received,
               (SELECT count(*) FROM core.visits WHERE status = 'held') AS held,
               (SELECT count(*) FROM core.visits) AS visits""")[0]
    ext = q("""
        SELECT s.code, s.name, s.unit, v.value, v.ts,
               (SELECT value FROM core.external_values p WHERE p.series_code = s.code AND p.ts < v.ts
                ORDER BY ts DESC LIMIT 1) AS prev
        FROM core.external_series s
        JOIN LATERAL (SELECT value, ts FROM core.external_values WHERE series_code = s.code
                      ORDER BY ts DESC LIMIT 1) v ON true
        WHERE s.code IN ('DIESEL', 'USDRWF')""")
    return {"week": latest, "rows": rows, "status": status, "external": ext, "demo": DEMO,
            "movers": {"up": movers[::-1][:5], "down": movers[:5]}}


@app.get("/api/commodity/{code}")
def commodity(code: str, days: int = 365):
    c = q("SELECT * FROM ref.commodities WHERE code = %s", (code,))
    if not c:
        raise HTTPException(404, "unknown commodity")
    cid = c[0]["id"]
    end = q("SELECT max(day) AS d FROM serving.daily_prices WHERE commodity_id = %s", (cid,))[0]["d"]
    start = end - timedelta(days=days) if end else None
    daily = q("""SELECT d.day::date AS day, m.code AS market, round(d.price::numeric, 1) AS price,
                        round(d.price_min::numeric, 1) AS lo, round(d.price_max::numeric, 1) AS hi, d.n_quotes
                 FROM serving.daily_prices d JOIN ref.markets m ON m.id = d.market_id
                 WHERE d.commodity_id = %s AND d.day >= %s ORDER BY d.day""", (cid, start))
    weekly = q("""SELECT w.week, coalesce(m.code, 'ALL') AS market, round(w.price::numeric, 1) AS price,
                         w.pct_wow, w.pct_4w, w.anomaly, w.z_level, w.n_quotes
                  FROM serving.weekly_metrics w LEFT JOIN ref.markets m ON m.id = w.market_id
                  WHERE w.commodity_id = %s AND w.week >= %s ORDER BY w.week""", (cid, start))
    latest_by_market = q("""
        SELECT DISTINCT ON (m.code) m.code AS market, m.name, w.week, round(w.price::numeric) AS price,
               w.pct_wow, w.anomaly
        FROM serving.weekly_metrics w JOIN ref.markets m ON m.id = w.market_id
        WHERE w.commodity_id = %s ORDER BY m.code, w.week DESC""", (cid,))
    availability = q("""
        SELECT DISTINCT ON (m.code) m.code AS market, a.visit_date, a.available
        FROM serving.availability a JOIN ref.markets m ON m.id = a.market_id
        WHERE a.commodity_id = %s ORDER BY m.code, a.visit_date DESC""", (cid,))
    diesel = q("""SELECT ts AS week, value FROM core.external_values
                  WHERE series_code = 'DIESEL' AND ts >= %s ORDER BY ts""", (start,))
    # A market whose latest accepted price is older than two weeks is listed as stale, never as cheapest.
    newest = max((r["week"] for r in latest_by_market), default=None)
    for r in latest_by_market:
        r["stale"] = newest is not None and (newest - r["week"]).days > 14
    ranked = sorted(latest_by_market, key=lambda r: (r["stale"], r["price"]))
    return {"commodity": c[0], "daily": daily, "weekly": weekly, "availability": availability,
            "markets": ranked, "diesel": diesel}


# ── QC review ─────────────────────────────────────────────────────────────────────
@app.get("/api/qc/queue")
def qc_queue(limit: int = 50):
    return q("""
        SELECT v.id, v.visit_date, m.code AS market, e.code AS enumerator, v.status,
               json_agg(json_build_object('rule', f.rule, 'severity', f.severity, 'detail', f.detail,
                        'commodity', c.code) ORDER BY f.severity DESC) AS flags
        FROM core.visits v
        JOIN core.qc_flags f ON f.visit_id = v.id
        JOIN ref.markets m ON m.id = v.market_id
        JOIN ref.enumerators e ON e.id = v.enumerator_id
        LEFT JOIN ref.commodities c ON c.id = f.commodity_id
        WHERE v.reviewed_at IS NULL AND (v.status = 'held' OR f.severity = 'hold')
        GROUP BY v.id, m.code, e.code ORDER BY v.visit_date DESC LIMIT %s""", (limit,))


@app.get("/api/qc/scorecard")
def scorecard(weeks: int = 8):
    return q("""
        WITH recent AS (SELECT * FROM core.visits
                        WHERE visit_date > (SELECT max(visit_date) FROM core.visits) - %s * 7)
        SELECT e.code AS enumerator, m.code AS market, count(r.*) AS visits,
               round(100.0 * count(*) FILTER (WHERE r.status = 'held') / nullif(count(r.*), 0), 1) AS pct_held,
               round(100.0 * count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.qc_flags f WHERE f.visit_id = r.id))
                     / nullif(count(r.*), 0), 1) AS pct_flagged,
               coalesce((SELECT json_object_agg(rule, n) FROM (
                   SELECT f.rule, count(*) n FROM core.qc_flags f JOIN recent r2 ON r2.id = f.visit_id
                   WHERE r2.enumerator_id = e.id GROUP BY f.rule) x), '{}') AS rules
        FROM ref.enumerators e JOIN ref.markets m ON m.id = e.market_id
        LEFT JOIN recent r ON r.enumerator_id = e.id
        GROUP BY e.id, m.code ORDER BY pct_held NULLS LAST""", (weeks,))


@app.post("/api/qc/visits/{visit_id}/{action}")
def review(visit_id: int, action: str, tasks: BackgroundTasks):
    """accept     → publish the visit, but reject quotes that carry their own outlier hold
       accept_all → publish everything, outliers included (reviewer confirmed a real price move)
       reject     → publish nothing from this visit"""
    if action not in ("accept", "accept_all", "reject"):
        raise HTTPException(400, "action must be accept, accept_all or reject")
    status = "rejected" if action == "reject" else "ok"
    with connect() as conn:
        n = conn.execute("UPDATE core.visits SET status = %s, reviewed_at = now() WHERE id = %s RETURNING id",
                         (status, visit_id)).fetchone()
        if not n:
            raise HTTPException(404, "unknown visit")
        conn.execute("UPDATE core.price_quotes SET status = %s WHERE visit_id = %s", (status, visit_id))
        if action == "accept":
            conn.execute("""UPDATE core.price_quotes q SET status = 'rejected'
                            FROM core.qc_flags f
                            WHERE f.visit_id = %(v)s AND q.visit_id = %(v)s AND f.severity = 'hold'
                              AND f.vendor_id = q.vendor_id AND f.commodity_id = q.commodity_id""", {"v": visit_id})
    tasks.add_task(analytics.recompute)
    return {"visit_id": visit_id, "status": status, "action": action}


@app.get("/api/truth")
def truth():
    if not DEMO:
        raise HTTPException(404)
    from demo import truth_report
    with connect() as conn:
        return truth_report.report(conn)


# ── Server-sent events ────────────────────────────────────────────────────────────
@app.get("/api/stream")
async def stream(request: Request):
    queue: asyncio.Queue = asyncio.Queue()
    broadcaster.queues.add(queue)

    async def events():
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.queues.discard(queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
