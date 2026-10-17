from datetime import date

import numpy as np
import pandas as pd

from pipeline import analytics


def _quotes(rows):
    df = pd.DataFrame(rows, columns=["visit_date", "commodity_id", "market_id", "vendor_id", "price"])
    df["week"] = pd.to_datetime(df["visit_date"]).dt.to_period("W-SUN").dt.start_time.dt.date
    df["lp"] = np.log(df["price"])
    return df


def test_matched_jevons_ignores_new_vendor():
    # Vendors 1 and 2 both rise 10%; vendor 3 appears in week 2 at a much higher price.
    df = _quotes([
        (date(2026, 1, 5), 1, 1, 1, 100), (date(2026, 1, 5), 1, 1, 2, 200),
        (date(2026, 1, 12), 1, 1, 1, 110), (date(2026, 1, 12), 1, 1, 2, 220), (date(2026, 1, 12), 1, 1, 3, 900),
    ])
    out = analytics.compute(df)
    wk2 = out[(out.market_id == 1) & (out.week == date(2026, 1, 12))].iloc[0]
    assert abs(wk2.pct_wow - 10.0) < 1e-9          # the matched change is unaffected by vendor 3


def test_level_is_geometric_mean_and_national_row_exists():
    df = _quotes([(date(2026, 1, 5), 1, m, v, p) for m, v, p in [(1, 1, 100), (1, 2, 400), (2, 3, 200), (2, 4, 200)]])
    out = analytics.compute(df)
    m1 = out[(out.market_id == 1)].iloc[0]
    nat = out[(out.market_id == 0)].iloc[0]
    assert abs(m1.price - 200) < 1e-9               # sqrt(100 * 400)
    assert abs(nat.price - 200) < 1e-9              # geometric mean of 200 and 200
    assert m1.anomaly == "insufficient"


def test_seasonal_z_flags_a_jump():
    weeks = pd.Series(pd.date_range("2024-01-01", periods=80, freq="W-MON").date)
    rng = np.random.default_rng(1)
    lp = pd.Series(np.log(1000) + 0.1 * np.sin(np.arange(80) * 2 * np.pi / 52.18) + rng.normal(0, 0.02, 80))
    lp.iloc[-1] += 0.4
    z = analytics.seasonal_z(weeks, lp)
    assert z.iloc[:52].isna().all()
    assert z.iloc[-1] > 3 and abs(z.iloc[-2]) < 3
