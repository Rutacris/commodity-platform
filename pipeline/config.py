import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://demo:demo@127.0.0.1:55432/commodities_demo")
KOBO_URL = os.environ.get("KOBO_URL", "http://127.0.0.1:8001")
KOBO_TOKEN = os.environ.get("KOBO_TOKEN", "demo-token")
KOBO_ASSET_UID = os.environ.get("KOBO_ASSET_UID", "aDemoPriceForm")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "30"))
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL", "")      # e.g. https://hc-ping.com/<uuid>
MIGRATIONS_DIR = os.environ.get("MIGRATIONS_DIR",
                                os.path.join(os.path.dirname(__file__), "..", "db", "migrations"))
INCLUDE_DEMO_MIGRATIONS = os.environ.get("DEMO", "1") == "1"   # 9xx files hold demo-only tables
