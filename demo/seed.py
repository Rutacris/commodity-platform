"""Prepare the demo database: migrate, generate the synthetic world (deterministic), load the
non-Kobo parts (vendor panel, external series, truth). Kobo submissions arrive later through
the mock Kobo server and the normal ingest path.

Usage: python -m demo.seed [--data demo/data] [--reset]
"""
import argparse
import os

import psycopg

from demo.synth import generate, load
from pipeline import config, db


def reset_database() -> None:
    info = psycopg.conninfo.conninfo_to_dict(config.DATABASE_URL)
    name = info.pop("dbname")
    if "demo" not in name:   # refuse to wipe anything that is not a demo database
        raise SystemExit(f"refusing to reset non-demo database {name!r}")
    with psycopg.connect(psycopg.conninfo.make_conninfo(**info, dbname="postgres"), autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("SYNTH_DIR", "demo/data"))
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    if a.reset:
        reset_database()
    print("migrations:", db.migrate() or "up to date")
    with db.connect() as conn:
        seeded = conn.execute("SELECT count(*) FROM ref.vendors").fetchone()[0]
    if not os.path.exists(os.path.join(a.data, "submissions.jsonl")):
        print("generated:", generate.write_all(a.data))
    if seeded:
        print("already seeded")
        return
    load.load(a.data)
    print("seeded reference panel, external series and truth")


if __name__ == "__main__":
    main()
