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


def _robust_z_reference(changes: pd.Series) -> pd.Series:
    """The original per-position loop, kept as the specification for the vectorised version."""
    out = pd.Series(np.nan, index=changes.index)
    vals = changes.to_numpy()
    for i in range(len(vals)):
        hist = vals[max(0, i - 52):i]
        hist = hist[~np.isnan(hist)]
        if len(hist) < analytics.MIN_HISTORY or np.isnan(vals[i]):
            continue
        med = np.median(hist)
        mad = np.median(np.abs(hist - med)) * 1.4826
        out.iloc[i] = (vals[i] - med) / max(mad, 0.01)
    return out


def test_vectorised_robust_z_matches_reference():
    rng = np.random.default_rng(7)
    vals = rng.normal(0, 0.05, 150)
    vals[rng.random(150) < 0.15] = np.nan          # gaps, as when visits are held
    vals[100] = 0.6
    s = pd.Series(vals)
    np.testing.assert_allclose(analytics.robust_z(s), _robust_z_reference(s), equal_nan=True)


def _synthetic_quotes(weeks=90, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(weeks):
        day = date(2024, 1, 1) + pd.Timedelta(weeks=w)
        for c in (1, 2):
            for m in (1, 2, 3):
                base = 500 * c * (1 + 0.1 * np.sin(w / 8.3)) * (1 + 0.05 * m)
                for v in range(2):
                    if rng.random() < 0.05:
                        continue                      # missed quote
                    rows.append((day, c, m, 100 * c + 10 * m + v, base * np.exp(rng.normal(0, 0.03))))
    return _quotes(rows)


def test_incremental_compute_equals_full_compute_for_recent_weeks():
    df = _synthetic_quotes()
    full = analytics.compute(df)
    cut = sorted(df["week"].unique())[70]
    inc = analytics.compute(df, from_week=cut)
    key = ["commodity_id", "market_id", "week"]
    expected = full[full["week"] >= cut].sort_values(key).reset_index(drop=True)
    got = inc.sort_values(key).reset_index(drop=True)
    cols = key + ["price", "pct_wow", "pct_4w", "n_quotes", "n_vendors", "z", "d1z", "anomaly"]
    pd.testing.assert_frame_equal(got[cols], expected[cols])
    assert got["z_level"].notna().any()           # the seasonal score was computed for the recent weeks
