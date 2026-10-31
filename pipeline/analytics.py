"""Weekly price metrics, following docs/PILOT_METHODOLOGY.md §5.

- Level: geometric mean of the routine vendor panel (ranks 1-2), so pilot weeks with 5 vendors
  do not shift the level.
- Change: matched-sample Jevons index — mean log change over vendors quoted in both weeks.
- National (market_id 0): geometric mean of market levels; change = mean of market changes.
- Anomaly (ALPS-style, after WFP's Alert for Price Spikes): for each week, fit trend + two seasonal
  harmonics to the series' earlier weeks (at least 52), and express the gap between the observed and
  predicted level in residual standard deviations. Watch >= 2, unusual >= 3. Series with less than a
  year of history fall back to a robust z-score of the 4-week change. The WFP category cut-offs were
  not verified; these thresholds are provisional.

Every metric for week W uses only weeks <= W, so after new data arrives only weeks from the earliest
affected week onward are recomputed (recompute(from_date=...)); earlier rows cannot change.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from pipeline.db import connect

ANALYTICS_LOCK = 4343
MIN_HISTORY = 12
MIN_SEASONAL_HISTORY = 52


def load_quotes(conn) -> pd.DataFrame:
    rows = conn.execute(
        """SELECT v.visit_date, q.commodity_id, q.market_id, q.vendor_id, q.price_std::float
           FROM core.price_quotes q
           JOIN core.visits v ON v.id = q.visit_id
           JOIN ref.vendors r ON r.id = q.vendor_id
           WHERE q.status = 'ok' AND q.available AND q.price_std > 0
             AND v.session = 'AM' AND r.panel_rank <= 2""").fetchall()
    df = pd.DataFrame(rows, columns=["visit_date", "commodity_id", "market_id", "vendor_id", "price"])
    if df.empty:
        return df
    df["week"] = pd.to_datetime(df["visit_date"]).dt.to_period("W-SUN").dt.start_time.dt.date
    df["lp"] = np.log(df["price"])
    return df


def matched_change(vw: pd.DataFrame, lag: int) -> pd.Series:
    """vw: vendor-week mean log prices with columns commodity_id, market_id, vendor_id, week, lp.
    Returns the mean log change vs `lag` weeks earlier over matched vendors, indexed by (c, m, week)."""
    a = vw.copy()
    b = vw.copy()
    b["week"] = (pd.to_datetime(b["week"]) + pd.Timedelta(weeks=lag)).dt.date
    j = a.merge(b, on=["commodity_id", "market_id", "vendor_id", "week"], suffixes=("", "_prev"))
    j["d"] = j["lp"] - j["lp_prev"]
    return j.groupby(["commodity_id", "market_id", "week"])["d"].mean()


def robust_z(changes: pd.Series) -> pd.Series:
    """Robust z-score of each value against the previous 52 positions (median/MAD, NaNs skipped,
    at least MIN_HISTORY values), computed for all positions at once."""
    vals = changes.to_numpy(dtype=float)
    n = len(vals)
    if n == 0:
        return pd.Series(dtype=float, index=changes.index)
    win = sliding_window_view(np.concatenate([np.full(52, np.nan), vals]), 52)[:n]   # row i = vals[i-52:i]
    count = (~np.isnan(win)).sum(axis=1)
    ok = (count >= MIN_HISTORY) & ~np.isnan(vals)
    out = np.full(n, np.nan)
    if ok.any():
        w = win[ok]
        med = np.nanmedian(w, axis=1)
        mad = np.nanmedian(np.abs(w - med[:, None]), axis=1) * 1.4826
        out[ok] = (vals[ok] - med) / np.maximum(mad, 0.01)
    return pd.Series(out, index=changes.index)


def seasonal_z(weeks: pd.Series, lp: pd.Series, from_week: date | None = None) -> pd.Series:
    """Out-of-sample residual z-score of each week against trend + 2 harmonics fitted on earlier weeks.
    Weeks before from_week are left NaN (not needed by an incremental recompute)."""
    t = (pd.to_datetime(weeks) - pd.Timestamp("2000-01-03")).dt.days.to_numpy() / 7.0
    w = 2 * np.pi * t / 52.18
    X = np.column_stack([np.ones_like(t), t, np.sin(w), np.cos(w), np.sin(2 * w), np.cos(2 * w)])
    y = lp.to_numpy()
    out = np.full(len(y), np.nan)
    first = MIN_SEASONAL_HISTORY
    if from_week is not None:
        first = max(first, int(np.searchsorted(np.array(list(weeks), dtype=object), from_week)))
    for i in range(first, len(y)):
        Xh, yh = X[max(0, i - 156):i], y[max(0, i - 156):i]
        beta, *_ = np.linalg.lstsq(Xh, yh, rcond=None)
        resid = yh - Xh @ beta
        sd = max(resid.std(ddof=X.shape[1]), 0.01)
        out[i] = (y[i] - X[i] @ beta) / sd
    return pd.Series(out, index=lp.index)


def compute(df: pd.DataFrame, from_week: date | None = None) -> pd.DataFrame:
    """Weekly metrics for every (commodity, market, week); with from_week, only rows for weeks
    >= from_week are returned (all history is still used as input)."""
    vw = df.groupby(["commodity_id", "market_id", "vendor_id", "week"], as_index=False)["lp"].mean()
    level = vw.groupby(["commodity_id", "market_id", "week"]).agg(
        lp=("lp", "mean"), n_vendors=("vendor_id", "nunique"))
    level["n_quotes"] = df.groupby(["commodity_id", "market_id", "week"]).size()
    level["d1"] = matched_change(vw, 1)
    level["d4"] = matched_change(vw, 4)
    level = level.reset_index()

    nat = level.groupby(["commodity_id", "week"]).agg(
        lp=("lp", "mean"), n_vendors=("n_vendors", "sum"), n_quotes=("n_quotes", "sum"),
        d1=("d1", "mean"), d4=("d4", "mean"), n_markets=("market_id", "nunique")).reset_index()
    nat["market_id"] = 0
    out = pd.concat([level, nat.drop(columns="n_markets")], ignore_index=True)
    out = out.sort_values(["commodity_id", "market_id", "week"])
    out = out.reset_index(drop=True)
    out["z_level"] = np.nan
    for idx in out.groupby(["commodity_id", "market_id"]).groups.values():
        out.loc[idx, "z_level"] = seasonal_z(out.loc[idx, "week"], out.loc[idx, "lp"], from_week).to_numpy()
    g = out.groupby(["commodity_id", "market_id"], group_keys=False)
    out["d1z"] = g["d1"].apply(robust_z)
    out["z"] = out["z_level"].fillna(g["d4"].apply(robust_z))
    out["anomaly"] = np.select(
        [out["z"].isna(), out["z"].abs() >= 3, out["z"].abs() >= 2],
        ["insufficient", "unusual", "watch"], default="normal")
    out["price"] = np.exp(out["lp"])
    out["pct_wow"] = np.expm1(out["d1"]) * 100
    out["pct_4w"] = np.expm1(out["d4"]) * 100
    if from_week is not None:
        out = out[out["week"] >= from_week]
    return out


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def recompute(from_date: date | str | None = None) -> int:
    """Rebuild weekly metrics; with from_date, only weeks from that date's week onward."""
    if isinstance(from_date, str):
        from_date = date.fromisoformat(from_date)
    from_week = week_start(from_date) if from_date else None
    with connect() as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (ANALYTICS_LOCK,))
            df = load_quotes(conn)
            if from_week is None:
                conn.execute("DELETE FROM serving.weekly_metrics")
            else:
                conn.execute("DELETE FROM serving.weekly_metrics WHERE week >= %s", (from_week,))
            if df.empty:
                return 0
            out = compute(df, from_week)
            with conn.cursor().copy(
                    "COPY serving.weekly_metrics (week, commodity_id, market_id, price, pct_wow, pct_4w, "
                    "n_quotes, n_vendors, z_change, z_level, anomaly) FROM STDIN") as cp:
                for r in out.itertuples(index=False):
                    cp.write_row((r.week, int(r.commodity_id), int(r.market_id), float(r.price),
                                  None if pd.isna(r.pct_wow) else float(r.pct_wow),
                                  None if pd.isna(r.pct_4w) else float(r.pct_4w),
                                  int(r.n_quotes), int(r.n_vendors),
                                  None if pd.isna(r.d1z) else float(r.d1z),
                                  None if pd.isna(r.z) else float(r.z), r.anomaly))
        conn.execute("SELECT pg_notify('prices', '{\"event\": \"metrics\"}')")
        return len(out)


if __name__ == "__main__":
    print("weekly metric rows:", recompute())
