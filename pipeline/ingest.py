"""Kobo ingestion: store submissions verbatim (raw), transform them into visits and quotes (core),
run quality checks, and notify listeners.

Two entry points feed the same idempotent path:
  - the webhook (Kobo REST Service → POST /ingest/kobo), fast but best-effort
  - the poller, which asks Kobo for anything newer than the last stored _id (safety net)
"""
import json
import logging
from datetime import date, datetime

import httpx
from psycopg.types.json import Jsonb

from pipeline import config, qc
from pipeline.db import connect

log = logging.getLogger("ingest")
PROCESS_LOCK = 4242


def store_raw(conn, payload: dict, source: str) -> bool:
    """Insert one submission; returns False if it was already stored (duplicate delivery)."""
    row = conn.execute(
        "INSERT INTO raw.kobo_submissions (kobo_id, uuid, source, payload) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING RETURNING kobo_id",
        (payload["_id"], payload["_uuid"], source, Jsonb(payload))).fetchone()
    return row is not None


def poll_once(conn, client: httpx.Client) -> int:
    """Fetch every submission with _id above the highest one stored. Returns how many were new."""
    last = conn.execute("SELECT coalesce(max(kobo_id), 0) FROM raw.kobo_submissions").fetchone()[0]
    query, start, new = json.dumps({"_id": {"$gt": last}}), 0, 0
    while True:
        r = client.get(f"{config.KOBO_URL}/api/v2/assets/{config.KOBO_ASSET_UID}/data/",
                       params={"format": "json", "query": query, "start": start, "limit": 1000,
                               "sort": json.dumps({"_id": 1})},
                       headers={"Authorization": f"Token {config.KOBO_TOKEN}"})
        r.raise_for_status()
        body = r.json()
        for s in body["results"]:
            new += store_raw(conn, s, "poll")
        conn.commit()
        if not body["next"]:
            return new
        start += len(body["results"])


def _lookups(cur):
    return {
        "markets": {c: (i, lat, lon) for c, i, lat, lon in cur.execute("SELECT code, id, lat, lon FROM ref.markets")},
        "enumerators": dict(cur.execute("SELECT code, id FROM ref.enumerators").fetchall()),
        "commodities": {c: (i, float(s)) for c, i, s in
                        cur.execute("SELECT code, id, std_per_price_unit FROM ref.commodities")},
        "vendors": dict(cur.execute("SELECT code, id FROM ref.vendors").fetchall()),
    }


def _pilot_window(cur):
    row = cur.execute("SELECT value FROM ops.settings WHERE key = 'pilot_window'").fetchone()
    if not row:
        return None
    a, b = row[0]
    return date.fromisoformat(a), date.fromisoformat(b)


def transform(cur, lk, kobo_uuid: str, p: dict, pilot) -> dict:
    mkt_id, mlat, mlon = lk["markets"][p["market"]]
    started = datetime.fromisoformat(p["start"])
    ended = datetime.fromisoformat(p["end"])
    lat, lon = (p.get("_geolocation") or [None, None])[:2]
    dist = qc.haversine_m(lat, lon, mlat, mlon) if lat is not None else None
    photo_c = lk["commodities"].get(p.get("photo_commodity"), (None,))[0]
    visit = dict(kobo_uuid=kobo_uuid, market_id=mkt_id, enumerator_id=lk["enumerators"][p["enumerator"]],
                 visit_date=date.fromisoformat(p["visit_date"]), session=p.get("session", "AM"), started_at=started, ended_at=ended,
                 duration_s=int((ended - started).total_seconds()), lat=lat, lon=lon, dist_m=dist,
                 device_id=p.get("deviceid"), photo_commodity_id=photo_c, photo_hash=p.get("photo_phash"))
    visit["id"] = cur.execute(
        """INSERT INTO core.visits (kobo_uuid, market_id, enumerator_id, visit_date, session, started_at, ended_at,
               duration_s, lat, lon, dist_m, device_id, photo_commodity_id, photo_hash)
           VALUES (%(kobo_uuid)s, %(market_id)s, %(enumerator_id)s, %(visit_date)s, %(session)s, %(started_at)s, %(ended_at)s,
               %(duration_s)s, %(lat)s, %(lon)s, %(dist_m)s, %(device_id)s, %(photo_commodity_id)s, %(photo_hash)s)
           RETURNING id""", visit).fetchone()[0]

    quotes, unknown = [], []
    for g in p.get("commodities", []):
        c_id, per_unit = lk["commodities"][g["commodities/commodity"]]
        if g.get("commodities/available") != "yes":
            quotes.append(dict(commodity_id=c_id, vendor_id=0, available=False, price_rwf=None, price_std=None))
            continue
        for q in g.get("commodities/quotes", []):
            v_id = lk["vendors"].get(q["commodities/quotes/vendor"])
            price = int(float(q["commodities/quotes/price"]))
            if v_id is None:
                unknown.append(q["commodities/quotes/vendor"])
                continue
            quotes.append(dict(commodity_id=c_id, vendor_id=v_id, available=True, price_rwf=price,
                               price_std=price / per_unit))

    visit.update(makeup=p.get("makeup") == "yes",
                 local_start_hour=started.hour + started.minute / 60)
    result = qc.run(cur, visit, quotes, pilot)
    for code in unknown:
        result.flags.append(qc.Flag("unknown_vendor", "flag", {"vendor": code}))

    status = "held" if result.held else "ok"
    held_quotes = result.held_quotes()
    with cur.copy("COPY core.price_quotes (observed_at, visit_id, market_id, commodity_id, vendor_id, "
                  "available, price_rwf, price_std, status) FROM STDIN") as cp:
        for q in quotes:
            q_status = "held" if status == "held" or (q["commodity_id"], q["vendor_id"]) in held_quotes else "ok"
            cp.write_row((started, visit["id"], mkt_id, q["commodity_id"], q["vendor_id"], q["available"],
                          q["price_rwf"], q["price_std"], q_status))
    for f in result.flags:
        cur.execute("INSERT INTO core.qc_flags (visit_id, commodity_id, vendor_id, rule, severity, detail) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (visit["id"], f.commodity_id, f.vendor_id, f.rule, f.severity, Jsonb(f.detail)))
    if status == "held":
        cur.execute("UPDATE core.visits SET status = 'held' WHERE id = %s", (visit["id"],))
    return {"visit_id": visit["id"], "market": p["market"], "date": p["visit_date"], "status": status,
            "flags": [f.rule for f in result.flags]}


def process_pending(conn, batch: int = 200) -> list[dict]:
    """Transform unprocessed raw submissions in _id order. Serialised with an advisory lock so the
    webhook handler and the poller never process the same submission twice."""
    done = []
    while True:
        with conn.transaction():
            cur = conn.cursor()
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (PROCESS_LOCK,))
            rows = cur.execute("SELECT kobo_id, uuid, payload FROM raw.kobo_submissions "
                               "WHERE processed_at IS NULL ORDER BY kobo_id LIMIT %s", (batch,)).fetchall()
            if not rows:
                break
            lk, pilot = _lookups(cur), _pilot_window(cur)
            for kobo_id, kobo_uuid, payload in rows:
                try:
                    with conn.transaction():
                        done.append(transform(cur, lk, kobo_uuid, payload, pilot))
                    cur.execute("UPDATE raw.kobo_submissions SET processed_at = now(), process_error = NULL "
                                "WHERE kobo_id = %s", (kobo_id,))
                except Exception as e:   # keep the raw row; record why it failed so it can be re-run
                    log.exception("failed to process %s", kobo_id)
                    cur.execute("UPDATE raw.kobo_submissions SET processed_at = now(), process_error = %s "
                                "WHERE kobo_id = %s", (str(e)[:500], kobo_id))
    if done:
        notify(conn, {"event": "visits", "count": len(done),
                      "latest_date": max(d["date"] for d in done),
                      "markets": sorted({d["market"] for d in done})})
    return done


def notify(conn, payload: dict) -> None:
    conn.execute("SELECT pg_notify('prices', %s)", (json.dumps(payload)[:7900],))
    conn.commit()
