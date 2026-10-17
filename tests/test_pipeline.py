"""End to end: mock Kobo → poll → raw → QC → core → metrics, checked against the generator's truth."""
import json

import pytest

from pipeline import analytics, ingest
from pipeline.db import connect


def test_mock_kobo_paging(kobo):
    client, mock = kobo
    h = {"Authorization": "Token demo-token"}
    first = client.get("/api/v2/assets/aDemoPriceForm/data/", params={"limit": 5}, headers=h).json()
    assert first["count"] == len(mock.state.released()) and len(first["results"]) == 5
    gt = first["results"][-1]["_id"]
    rest = client.get("/api/v2/assets/aDemoPriceForm/data/",
                      params={"query": json.dumps({"_id": {"$gt": gt}}), "limit": 3}, headers=h).json()
    assert all(s["_id"] > gt for s in rest["results"])
    assert client.get("/api/v2/assets/aDemoPriceForm/data/").status_code == 401


@pytest.fixture(scope="module")
def ingested(seeded_db, kobo):
    client, _ = kobo
    with connect() as conn:
        n = ingest.poll_once(conn, client)
        done = ingest.process_pending(conn)
    analytics.recompute()
    return n, done


def test_everything_released_is_ingested_once(ingested, kobo):
    n, done = ingested
    _, mock = kobo
    assert n == len(done) == len(mock.state.released())
    with connect() as conn:
        assert conn.execute("SELECT count(*) FROM raw.kobo_submissions WHERE process_error IS NOT NULL").fetchone()[0] == 0


def test_duplicate_delivery_is_ignored(ingested, kobo):
    _, mock = kobo
    payload = mock.state.released()[0]
    with connect() as conn:
        assert ingest.store_raw(conn, payload, "webhook") is False
        before = conn.execute("SELECT count(*) FROM core.visits").fetchone()[0]
        assert ingest.process_pending(conn) == []
        assert conn.execute("SELECT count(*) FROM core.visits").fetchone()[0] == before


def test_qc_catches_injected_misconduct_without_false_holds(ingested):
    with connect() as conn:
        rows = dict(conn.execute("""
            SELECT coalesce(m.kind, 'honest'), avg((v.status = 'held')::int)
            FROM core.visits v LEFT JOIN truth.misconduct m ON m.kobo_uuid = v.kobo_uuid GROUP BY 1""").fetchall())
    assert rows["fabricated"] == 1.0
    assert rows["lazy"] >= 0.9
    assert rows["honest"] == 0.0


def test_every_typo_is_held(ingested):
    with connect() as conn:
        total, caught = conn.execute("""
            SELECT count(*), count(*) FILTER (WHERE q.status = 'held')
            FROM truth.typos t JOIN core.visits v ON v.kobo_uuid = t.kobo_uuid
            JOIN ref.vendors r ON r.code = t.vendor JOIN ref.commodities c ON c.code = t.commodity
            JOIN core.price_quotes q ON q.visit_id = v.id AND q.vendor_id = r.id AND q.commodity_id = c.id""").fetchone()
    assert total > 0 and caught == total


def test_not_available_is_published_without_a_price(ingested):
    with connect() as conn:
        na = conn.execute("""SELECT count(*) FROM serving.availability a JOIN ref.commodities c ON c.id = a.commodity_id
                             JOIN ref.markets m ON m.id = a.market_id
                             WHERE c.code = 'EGGS' AND m.code = 'KIM' AND NOT a.available""").fetchone()[0]
        priced = conn.execute("""SELECT count(*) FROM core.price_quotes q JOIN ref.commodities c ON c.id = q.commodity_id
                                 JOIN ref.markets m ON m.id = q.market_id JOIN core.visits v ON v.id = q.visit_id
                                 WHERE c.code = 'EGGS' AND m.code = 'KIM' AND v.visit_date BETWEEN '2026-10-05' AND '2026-10-09'
                                   AND q.price_rwf IS NOT NULL""").fetchone()[0]
    assert na == 3 and priced == 0


def test_tomato_shortage_flagged(ingested):
    with connect() as conn:
        flags = [r[0] for r in conn.execute("""
            SELECT w.anomaly FROM serving.weekly_metrics w JOIN ref.commodities c ON c.id = w.commodity_id
            WHERE c.code = 'TOMATO' AND w.market_id = 0 AND w.week BETWEEN '2026-09-28' AND '2026-10-12'""")]
    assert "unusual" in flags


def test_accepting_a_visit_keeps_flagged_outliers_out(ingested):
    from fastapi.testclient import TestClient
    from pipeline.api import app
    with connect() as conn:
        visit_id, c_id, v_id = conn.execute("""
            SELECT f.visit_id, f.commodity_id, f.vendor_id FROM core.qc_flags f JOIN core.visits v ON v.id = f.visit_id
            WHERE f.rule = 'price_outlier' AND v.status = 'ok' LIMIT 1""").fetchone()
    with TestClient(app) as client:
        assert client.post(f"/api/qc/visits/{visit_id}/accept").status_code == 200
    with connect() as conn:
        statuses = dict(conn.execute("SELECT (commodity_id, vendor_id) = (%s, %s), array_agg(DISTINCT status) "
                                     "FROM core.price_quotes WHERE visit_id = %s GROUP BY 1", (c_id, v_id, visit_id)))
    assert statuses[True] == ["rejected"] and statuses[False] == ["ok"]
