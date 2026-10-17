"""Background worker: poll Kobo, process new submissions, refresh metrics, send a heartbeat.

Usage: python -m pipeline.worker            (loop)
       python -m pipeline.worker --once     (single pass, used by the demo seed step)
"""
import argparse
import logging
import time

import httpx

from pipeline import analytics, config, ingest
from pipeline.db import connect

log = logging.getLogger("worker")


def refresh_aggregates(conn) -> None:
    # Backfilled rows can be older than the continuous-aggregate policy window; refresh fully.
    conn.autocommit = True
    conn.execute("CALL refresh_continuous_aggregate('serving.daily_prices', NULL, NULL)")
    conn.autocommit = False


def run_once(client: httpx.Client, full_refresh: bool = False) -> dict:
    with connect() as conn:
        fetched = ingest.poll_once(conn, client)
        done = ingest.process_pending(conn)
        if full_refresh or len(done) > 100:   # large backfill: older than the refresh policy window
            refresh_aggregates(conn)
    metrics = analytics.recompute() if done else 0
    return {"fetched": fetched, "processed": len(done), "metric_rows": metrics}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    with httpx.Client(timeout=60) as client:
        if a.once:
            print(run_once(client, full_refresh=True))
            return
        while True:
            try:
                r = run_once(client)
                if r["processed"]:
                    log.info("%s", r)
                if config.HEALTHCHECK_URL:
                    client.get(config.HEALTHCHECK_URL)
            except Exception:   # keep looping; the next poll retries from the last stored _id
                log.exception("worker pass failed")
            time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    main()
