"""Integration tests run against a real TimescaleDB (default: the demo container on port 55432)
using a separate database, so they never touch the demo data."""
import os
import pathlib

import pytest

os.environ.setdefault("TEST_DATABASE_URL", "postgresql://demo:demo@127.0.0.1:55432/commodities_demo_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
DATA = pathlib.Path(__file__).parent / ".synth"
os.environ["SYNTH_DATA"] = str(DATA / "submissions.jsonl")
os.environ["KOBO_URL"] = "http://testserver"

from demo.synth import generate  # noqa: E402

if not (DATA / "submissions.jsonl").exists():
    generate.write_all(str(DATA))


@pytest.fixture(scope="session")
def seeded_db():
    from demo import seed
    from demo.synth import load
    from pipeline import db
    seed.reset_database()
    db.migrate()
    load.load(str(DATA))
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def kobo():
    from fastapi.testclient import TestClient
    from demo.mock_kobo import app as mock
    with TestClient(mock.app) as client:
        yield client, mock
