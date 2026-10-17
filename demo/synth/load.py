"""Load generator output that does not travel through Kobo: vendor panel, enumerators,
external series (stand-in for the WFP/RURA/BNR/CHIRPS jobs) and the hidden truth tables.

Usage: python -m demo.synth.load --data demo/data
"""
import argparse
import csv
import json
import os

from demo.synth import params as P
from pipeline.db import connect


def load(data: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        markets = dict(cur.execute("SELECT code, id FROM ref.markets").fetchall())
        commodities = dict(cur.execute("SELECT code, id FROM ref.commodities").fetchall())
        for i, (code, m) in enumerate(P.ENUMERATORS.items(), 1):
            cur.execute("INSERT INTO ref.enumerators (id, code, market_id) VALUES (%s, %s, %s) "
                        "ON CONFLICT (id) DO NOTHING", (i, code, markets[m]))
        with open(os.path.join(data, "vendors.csv")) as f:
            for r in csv.DictReader(f):
                cur.execute("INSERT INTO ref.vendors (code, market_id, commodity_id, panel_rank) "
                            "VALUES (%s, %s, %s, %s) ON CONFLICT (code) DO NOTHING",
                            (r["code"], markets[r["market"]], commodities[r["commodity"]], int(r["panel_rank"])))
        with cur.copy("COPY core.external_values (series_code, ts, value) FROM STDIN") as cp, \
                open(os.path.join(data, "external.csv")) as f:
            for r in csv.DictReader(f):
                cp.write_row((r["series_code"], r["ts"], r["value"]))

        cur.execute("INSERT INTO ops.settings VALUES ('pilot_window', %s) ON CONFLICT (key) DO UPDATE "
                    "SET value = excluded.value", (json.dumps([P.PILOT_START.isoformat(), P.PILOT_END.isoformat()]),))

        t = os.path.join(data, "truth")
        with open(os.path.join(t, "params.json")) as f:
            for k, v in json.load(f).items():
                cur.execute("INSERT INTO truth.params VALUES (%s, %s)", (k, json.dumps(v)))
        for table, cols in [("true_prices", "day, commodity, market, price"),
                            ("misconduct", "kobo_uuid, enumerator, kind"),
                            ("typos", "kobo_uuid, commodity, vendor"),
                            ("events", "code, commodity, market, start_date, end_date, description")]:
            with cur.copy(f"COPY truth.{table} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER true)") as cp, \
                    open(os.path.join(t, f"{table}.csv"), "rb") as f:
                while chunk := f.read(1 << 16):
                    cp.write(chunk)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="demo/data")
    load(ap.parse_args().data)
    print("loaded reference panel, external series and truth tables")
