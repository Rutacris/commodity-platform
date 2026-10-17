"""Connection helper and a minimal SQL migration runner."""
import glob
import os

import psycopg

from pipeline import config


def connect(**kw) -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, **kw)


def migrate() -> list[str]:
    applied = []
    with connect(autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
        conn.execute("CREATE TABLE IF NOT EXISTS ops.schema_migrations "
                     "(name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM ops.schema_migrations")}
        for path in sorted(glob.glob(os.path.join(config.MIGRATIONS_DIR, "*.sql"))):
            name = os.path.basename(path)
            if name in done or (name.startswith("9") and not config.INCLUDE_DEMO_MIGRATIONS):
                continue
            with open(path) as f:
                sql = f.read()
            # Continuous-aggregate DDL cannot run inside a transaction block, so run as-is.
            conn.execute(sql)
            conn.execute("INSERT INTO ops.schema_migrations (name) VALUES (%s)", (name,))
            applied.append(name)
    return applied


if __name__ == "__main__":
    print("applied:", migrate() or "nothing new")
