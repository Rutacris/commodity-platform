"""Compare what the platform published with the synthetic ground truth.

Usage: python -m demo.truth_report            (prints Markdown)
       GET /api/truth                         (same numbers as JSON)
"""
import json
import math

import numpy as np
import pandas as pd
import psycopg
import statsmodels.formula.api as smf

from demo.synth import params as P
from pipeline.db import connect


def _df(conn, sql, params=None) -> pd.DataFrame:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return pd.DataFrame(cur.execute(sql, params).fetchall())


def qc_scores(conn) -> dict:
    v = _df(conn, """SELECT coalesce(m.kind, 'honest') AS kind, v.status = 'held' AS held
                     FROM core.visits v LEFT JOIN truth.misconduct m ON m.kobo_uuid = v.kobo_uuid""")
    by = v.groupby("kind")["held"].agg(["sum", "count"])
    bad = by.drop(index="honest", errors="ignore")
    caught, total_bad = int(bad["sum"].sum()), int(bad["count"].sum())
    honest_held = int(by.loc["honest", "sum"]) if "honest" in by.index else 0
    honest_n = int(by.loc["honest", "count"]) if "honest" in by.index else 0
    t = _df(conn, """
        SELECT count(*) AS typos, count(*) FILTER (WHERE q.status <> 'ok') AS caught
        FROM truth.typos t JOIN core.visits v ON v.kobo_uuid = t.kobo_uuid
        JOIN ref.vendors r ON r.code = t.vendor JOIN ref.commodities c ON c.code = t.commodity
        JOIN core.price_quotes q ON q.visit_id = v.id AND q.vendor_id = r.id AND q.commodity_id = c.id""")
    fp = _df(conn, """
        SELECT count(*) AS n FROM core.qc_flags f JOIN core.visits v ON v.id = f.visit_id
        JOIN ref.vendors r ON r.id = f.vendor_id JOIN ref.commodities c ON c.id = f.commodity_id
        LEFT JOIN truth.misconduct m ON m.kobo_uuid = v.kobo_uuid
        LEFT JOIN truth.typos t ON t.kobo_uuid = v.kobo_uuid AND t.vendor = r.code AND t.commodity = c.code
        WHERE f.rule = 'price_outlier' AND m.kind IS NULL AND t.kobo_uuid IS NULL""")
    return {
        "by_kind": {k: {"held": int(r["sum"]), "visits": int(r["count"])} for k, r in by.iterrows()},
        "misconduct_recall": round(caught / total_bad, 3) if total_bad else None,
        "honest_false_hold_rate": round(honest_held / honest_n, 4) if honest_n else None,
        "typos": int(t["typos"][0]), "typos_caught": int(t["caught"][0]),
        "false_outlier_holds": int(fp["n"][0]),
        "pass": (total_bad == 0 or caught / total_bad >= 0.9) and (honest_n == 0 or honest_held / honest_n <= 0.1),
    }


def events(conn) -> list[dict]:
    out = []
    ev = _df(conn, "SELECT * FROM truth.events ORDER BY start_date")
    for e in ev.to_dict("records"):
        e = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in e.items()}
        if e["code"] == "EGGS_OUT_KIM":
            r = _df(conn, """SELECT count(*) FILTER (WHERE NOT a.available) AS na,
                                    (SELECT count(*) FROM serving.daily_prices d JOIN ref.markets m ON m.id = d.market_id
                                     JOIN ref.commodities c ON c.id = d.commodity_id
                                     WHERE c.code = 'EGGS' AND m.code = 'KIM' AND d.day::date BETWEEN %(a)s AND %(b)s) AS priced
                             FROM serving.availability a JOIN ref.markets m ON m.id = a.market_id
                             JOIN ref.commodities c ON c.id = a.commodity_id
                             WHERE c.code = 'EGGS' AND m.code = 'KIM' AND a.visit_date BETWEEN %(a)s AND %(b)s""",
                    {"a": e["start_date"], "b": e["end_date"]})
            na, priced = int(r["na"][0]), int(r["priced"][0])
            out.append({"event": e["code"], "detected": na > 0 and priced == 0,
                        "evidence": f"{na} visits published as 'not available', {priced} carried-forward prices"})
            continue
        if not e["commodity"]:
            continue
        market_clause = "AND m.code = %(m)s" if e["market"] else "AND w.market_id = 0"
        r = _df(conn, f"""
            SELECT w.week, w.anomaly, w.z_level FROM serving.weekly_metrics w
            JOIN ref.commodities c ON c.id = w.commodity_id LEFT JOIN ref.markets m ON m.id = w.market_id
            WHERE c.code = %(c)s {market_clause} AND w.week BETWEEN %(a)s::date - 6 AND %(b)s
            ORDER BY w.week""", {"c": e["commodity"], "m": e["market"], "a": e["start_date"], "b": e["end_date"]})
        hit = r[r["anomaly"] == "unusual"] if not r.empty else r
        first = hit["week"].min() if not hit.empty else None
        lag = (first - e["start_date"]).days if first is not None else None
        out.append({"event": e["code"], "detected": first is not None,
                    "evidence": f"first 'unusual' week {first} ({lag} days after start)" if first is not None
                    else "no 'unusual' week in window"})
    return out


def tracking(conn) -> dict:
    """Published national weekly level vs the true national level (log-change correlation, level error)."""
    pub = _df(conn, """SELECT c.code, w.week, w.price FROM serving.weekly_metrics w
                       JOIN ref.commodities c ON c.id = w.commodity_id WHERE w.market_id = 0""")
    tru = _df(conn, """SELECT commodity AS code, date_trunc('week', day)::date AS week,
                              exp(avg(ln(price))) AS true_price
                       FROM truth.true_prices WHERE extract(isodow FROM day) IN (1, 3, 5)
                       GROUP BY 1, 2""")
    j = pub.merge(tru, on=["code", "week"])
    j["err"] = np.log(j["price"] / j["true_price"])
    j["err_c"] = j["err"] - j.groupby("code")["err"].transform("median")   # remove panel-level offset
    j = j.sort_values(["code", "week"])
    j["dp"] = j.groupby("code")["price"].transform(lambda s: np.log(s).diff())
    j["dt"] = j.groupby("code")["true_price"].transform(lambda s: np.log(s).diff())
    k = j.dropna(subset=["dp", "dt"])
    return {"weeks_compared": int(len(j)),
            "corr_weekly_change": round(float(np.corrcoef(k["dp"], k["dt"])[0, 1]), 3),
            "median_abs_level_error_pct": round(float(np.median(np.abs(np.expm1(j["err_c"])))) * 100, 2)}


def fuel_passthrough(conn) -> list[dict]:
    """Estimate the diesel elasticity per commodity: log national price on lagged log diesel, trend, season."""
    pub = _df(conn, """SELECT c.code, w.week, w.price FROM serving.weekly_metrics w
                       JOIN ref.commodities c ON c.id = w.commodity_id WHERE w.market_id = 0""")
    dsl = _df(conn, "SELECT ts, value FROM core.external_values WHERE series_code = 'DIESEL' ORDER BY ts")
    dsl["ts"] = pd.to_datetime(dsl["ts"])
    truth = json.loads(json.dumps(_df(conn, "SELECT value FROM truth.params WHERE key = 'fuel_elasticity'")
                                  ["value"][0]))
    rows = []
    for code, g in pub.groupby("code"):
        g = g.copy()
        g["t"] = (pd.to_datetime(g["week"]) - pd.Timestamp(P.START)).dt.days / 7
        lagged = pd.to_datetime(g["week"]) - pd.Timedelta(days=P.FUEL_LAG_DAYS)
        days = lambda x: ((x - pd.Timestamp(P.START)) / pd.Timedelta(days=1)).to_numpy(dtype=float)
        g["ld"] = np.log(np.interp(days(lagged), days(dsl["ts"]), dsl["value"]))
        g["y"] = np.log(g["price"])
        g["s1"], g["c1"] = np.sin(2 * np.pi * g["t"] / 52.18), np.cos(2 * np.pi * g["t"] / 52.18)
        g["s2"], g["c2"] = np.sin(4 * np.pi * g["t"] / 52.18), np.cos(4 * np.pi * g["t"] / 52.18)
        # Newey-West (HAC) errors: weekly prices are autocorrelated, plain OLS intervals would be too narrow.
        m = smf.ols("y ~ ld + t + s1 + c1 + s2 + c2", g).fit(cov_type="HAC", cov_kwds={"maxlags": 8})
        rows.append({"commodity": code, "true": truth[code], "estimated": round(float(m.params["ld"]), 3),
                     "ci95": [round(float(x), 3) for x in m.conf_int().loc["ld"]]})
    return rows


def pilot(conn) -> dict:
    """Variance decomposition on the dense pilot block, compared with the generator's parameters."""
    d = _df(conn, """
        SELECT c.code, m.code AS market, r.code AS vendor, v.visit_date, v.session, q.price_std::float AS price
        FROM core.price_quotes q JOIN core.visits v ON v.id = q.visit_id
        JOIN ref.commodities c ON c.id = q.commodity_id JOIN ref.markets m ON m.id = q.market_id
        JOIN ref.vendors r ON r.id = q.vendor_id
        WHERE q.status = 'ok' AND q.available AND v.visit_date BETWEEN %s AND %s""", (P.PILOT_START, P.PILOT_END))
    if d.empty:
        return {}
    d["y"], d["g"] = np.log(d["price"]), 1
    est = []
    for (code, mkt), g in d[d["code"].isin(P.DESIGN_TIER)].groupby(["code", "market"]):
        has_pm = g["session"].nunique() > 1
        try:
            fit = smf.mixedlm("y ~ C(session)" if has_pm else "y ~ 1", g, groups="g",
                              vc_formula={"vendor": "0 + C(vendor)", "day": "0 + C(visit_date)"},
                              re_formula="0").fit(reml=True)
        except Exception:
            continue
        vc = dict(zip(fit.model.exog_vc.names, fit.vcomp))
        perish = P.COMMODITIES[code][2]
        est.append({"commodity": code, "market": mkt, "vendor_sd": math.sqrt(max(vc["vendor"], 0)),
                    "resid_sd": math.sqrt(fit.scale), "true_resid_sd": P.NOISE_SD["perishable" if perish else "staple"],
                    "pm": fit.fe_params.get("C(session)[T.PM]", np.nan)})
    e = pd.DataFrame(est)
    thin = thinning(d)
    return {"series": len(e), "true_vendor_sd": P.VENDOR_SD,
            "median_vendor_sd": round(float(e["vendor_sd"].median()), 4),
            "median_resid_sd_ratio": round(float((e["resid_sd"] / e["true_resid_sd"]).median()), 3),
            "pm_effect_perishables": round(float(e["pm"].dropna().mean()), 4), "true_pm_effect": P.PM_EFFECT,
            "thinning": thin}


def thinning(d: pd.DataFrame) -> dict:
    """RMSE of the weekly mean level (log) of Mon/Wed/Fri x 2 vendors against all days x 5 vendors."""
    am = d[(d["session"] == "AM") & d["code"].isin(P.DESIGN_TIER)].copy()
    am["week"] = pd.to_datetime(am["visit_date"]).dt.to_period("W-SUN")
    am["dow"] = pd.to_datetime(am["visit_date"]).dt.dayofweek
    full = am.groupby(["code", "market", "week"])["y"].mean()
    out = {}
    for label, days, k in [("MWF_2_vendors", {0, 2, 4}, 2), ("MWF_3_vendors", {0, 2, 4}, 3),
                           ("daily_2_vendors", set(range(6)), 2)]:
        sub = am[am["dow"].isin(days)]
        sub = sub[sub.groupby(["code", "market"])["vendor"].transform(
            lambda s: s.isin(sorted(s.unique())[:k]))]
        est = sub.groupby(["code", "market", "week"])["y"].mean()
        diff = (est - full).dropna()
        diff = diff - diff.groupby(level=[0, 1]).transform("mean")   # vendor-panel offset is constant
        out[label] = round(float(np.sqrt((diff ** 2).mean())) * 100, 2)
    return {"rmse_weekly_level_pct": out}


def fuel_summary(rows: list[dict]) -> dict:
    """Score only fuel-sensitive goods (true elasticity >= 0.12); for the rest the true effect is too
    small to separate from price noise with two years of weekly data."""
    sens = [r for r in rows if r["true"] >= 0.12]
    ok = [r for r in sens if r["estimated"] > 0 and abs(r["estimated"] - r["true"]) <= 0.5 * r["true"]]
    covered = [r for r in rows if r["ci95"][0] <= r["true"] <= r["ci95"][1]]
    return {"fuel_sensitive": len(sens), "within_50pct": len(ok), "pass": len(ok) == len(sens),
            "ci_coverage_all": f"{len(covered)}/{len(rows)}"}


def report(conn) -> dict:
    fuel = fuel_passthrough(conn)
    return {"qc": qc_scores(conn), "events": events(conn), "tracking": tracking(conn),
            "fuel_passthrough": fuel, "fuel_summary": fuel_summary(fuel), "pilot": pilot(conn)}


def markdown(r: dict) -> str:
    qc = r["qc"]
    lines = ["# Truth report (synthetic demo)", "",
             "## Quality checks vs injected misconduct",
             f"- Misconduct visits held: **{qc['misconduct_recall']:.0%}** "
             f"({', '.join(f'{k}: {v['held']}/{v['visits']}' for k, v in qc['by_kind'].items())})",
             f"- Honest visits wrongly held: **{qc['honest_false_hold_rate']:.1%}**",
             f"- Typos caught: **{qc['typos_caught']}/{qc['typos']}**; false outlier holds: {qc['false_outlier_holds']}",
             f"- Acceptance (≥90% caught, ≤10% false holds): **{'PASS' if qc['pass'] else 'FAIL'}**", "",
             "## Injected events"]
    lines += [f"- {e['event']}: {'detected' if e['detected'] else 'NOT detected'} — {e['evidence']}" for e in r["events"]]
    t = r["tracking"]
    lines += ["", "## Published vs true prices",
              f"- Correlation of weekly changes: **{t['corr_weekly_change']}** over {t['weeks_compared']} commodity-weeks",
              f"- Median level error after removing the vendor-panel offset: **{t['median_abs_level_error_pct']}%**", "",
              "## Fuel pass-through (elasticity to diesel)",
              f"- Fuel-sensitive goods within ±50% of the true effect, correct sign: "
              f"**{r['fuel_summary']['within_50pct']}/{r['fuel_summary']['fuel_sensitive']}** "
              f"({'PASS' if r['fuel_summary']['pass'] else 'FAIL'})",
              f"- True value inside the 95% interval (all goods): {r['fuel_summary']['ci_coverage_all']}",
              "- Small effects (0.05) on volatile fresh produce are not separable from noise with two years of data.",
              "", "| commodity | true | estimated | 95% CI (HAC) |", "|---|---|---|---|"]
    lines += [f"| {f['commodity']} | {f['true']} | {f['estimated']} | {f['ci95'][0]} … {f['ci95'][1]} |"
              for f in r["fuel_passthrough"]]
    p = r["pilot"]
    if p:
        lines += ["", "## Pilot block: variance decomposition",
                  f"- Vendor sd: estimated median **{p['median_vendor_sd']}** vs true {p['true_vendor_sd']}",
                  f"- Residual sd / true: median ratio **{p['median_resid_sd_ratio']}**",
                  f"- Afternoon effect on perishables: **{p['pm_effect_perishables']}** vs true {p['true_pm_effect']}",
                  f"- Thinning test, RMSE of weekly level vs full design: {p['thinning']['rmse_weekly_level_pct']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    with connect() as c:
        print(markdown(report(c)))
