"""Synthetic world generator.

Produces, deterministically from params.SEED:
  submissions.jsonl  Kobo-shaped submissions (what enumerators would send)
  vendors.csv        fixed vendor panel (stall codes)
  external.csv       diesel, exchange rate, rainfall, benchmark index
  truth/             true prices, injected events, misconduct, typos, parameters

Usage: python -m demo.synth.generate --out demo/data
"""
import argparse
import csv
import json
import math
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np

from demo.synth import params as P

KIGALI = timezone(timedelta(hours=2))


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


class World:
    def __init__(self, seed: int = P.SEED):
        self.rng = np.random.default_rng(seed)
        self.days = list(daterange(P.START, P.LIVE_END))
        self.day_index = {d: i for i, d in enumerate(self.days)}
        self.commodities = list(P.COMMODITIES)
        self.markets = list(P.MARKETS)
        self._diesel()
        self._true_prices()
        self._vendors()

    # ── external drivers ───────────────────────────────────────────────────────
    def _diesel(self):
        months = sorted({(d.year, d.month) for d in self.days})
        level, out = 1600.0, {}
        for y, m in months:
            level *= math.exp(self.rng.normal(0, 0.015))
            hike = 1.12 if (y, m) >= (2026, 7) else 1.0
            out[(y, m)] = round(level * hike)
        self.diesel_month = out
        self.diesel = np.array([out[(d.year, d.month)] for d in self.days], dtype=float)

    # ── true market prices ─────────────────────────────────────────────────────
    def _event_effect(self, c: str, m: str, d: date) -> float:
        eff = 0.0
        if c == "IPOT" and m == "NYB" and date(2026, 8, 14) <= d <= date(2026, 9, 16):
            ramp = min((d - date(2026, 8, 14)).days, (date(2026, 9, 16) - d).days, 3) / 3
            eff += math.log(0.8) * ramp
        if c == "TOMATO" and date(2026, 9, 28) <= d <= date(2026, 11, 8):
            k = (d - date(2026, 9, 28)).days
            peak = math.log(1.45)
            eff += peak * k / 14 if k <= 14 else peak * 0.5 ** ((k - 14) / 10)
        return eff

    def _true_prices(self):
        n = len(self.days)
        doy = np.array([d.timetuple().tm_yday for d in self.days])
        months = np.array([(d - P.START).days / 30.44 for d in self.days])
        lagged = np.concatenate([np.full(P.FUEL_LAG_DAYS, self.diesel[0]), self.diesel[:-P.FUEL_LAG_DAYS]])
        fuel_dev = np.log(lagged / self.diesel[0])
        self.true = {}      # (c, m) -> np.array of log price per std unit
        for c in self.commodities:
            base, size, perish, amp, beta = P.COMMODITIES[c]
            kind = "perishable" if perish else "staple"
            season = -amp * np.cos(4 * np.pi * (doy - 20) / 365.25)
            common = self._ar1(n, P.DAY_SHOCK_SD[kind])
            for m in self.markets:
                local = self._ar1(n, P.MARKET_SHOCK_SD)
                ev = np.array([self._event_effect(c, m, d) for d in self.days])
                self.true[(c, m)] = (math.log(base / size) + P.MARKETS[m][0] + season
                                     + P.TREND_PER_MONTH * months + beta * fuel_dev + common + local + ev)

    def _ar1(self, n: int, sd: float) -> np.ndarray:
        x, e = np.zeros(n), self.rng.normal(0, sd, n)
        for i in range(1, n):
            x[i] = P.AR_PERSISTENCE * x[i - 1] + e[i]
        return x

    # ── vendor panel ───────────────────────────────────────────────────────────
    def _vendors(self):
        self.vendors = {}   # (c, m) -> list of (code, effect)
        for m in self.markets:
            used = set()
            for c in self.commodities:
                panel = []
                for rank in range(P.PILOT_VENDORS):
                    while True:
                        code = f"{m}-S{self.rng.integers(1, 9):02d}-{self.rng.integers(1, 200):03d}"
                        if code not in used:
                            used.add(code)
                            break
                    panel.append((code, self.rng.normal(0, P.VENDOR_SD)))
                self.vendors[(c, m)] = panel

    # ── visits and submissions ─────────────────────────────────────────────────
    def schedule(self):
        """Yield (market, visit_date, session, commodities, n_vendors, makeup)."""
        for d in self.days:
            pilot = P.PILOT_START <= d <= P.PILOT_END and d.weekday() < 6
            routine_day = d.weekday() in P.COLLECTION_WEEKDAYS
            for m in self.markets:
                if routine_day or pilot:
                    comms = self.commodities if routine_day else P.DESIGN_TIER
                    missed = (not pilot) and self.rng.random() < P.MISSED_VISIT_RATE
                    if missed:
                        if self.rng.random() < P.MAKEUP_RATE:
                            yield m, d + timedelta(days=1), "AM", comms, P.ROUTINE_VENDORS, True
                        continue
                    yield m, d, "AM", comms, (P.PILOT_VENDORS if pilot else P.ROUTINE_VENDORS), False
                    if pilot:
                        perish = [c for c in P.DESIGN_TIER if P.COMMODITIES[c][2]]
                        yield m, d, "PM", perish, P.PILOT_VENDORS, False

    def generate(self):
        subs, misconduct, typos = [], [], []
        last_reported = {}       # vendor code -> last reported price (per price unit)
        photo_hashes = []
        enum_of = {v: k for k, v in P.ENUMERATORS.items()}
        for m, d, session, comms, n_vendors, makeup in self.schedule():
            if d > P.LIVE_END:
                continue
            e = enum_of[m]
            fabricated = e == "E3" and d in P.FABRICATION_DATES and session == "AM"
            lazy = e == "E2" and d >= P.LAZY_FROM
            i = self.day_index[d]
            n_quotes = len(comms) * n_vendors
            if session == "AM":
                start_local = datetime(d.year, d.month, d.day, 8, 10, tzinfo=KIGALI) + timedelta(
                    minutes=float(self.rng.uniform(0, 140)))
            else:
                start_local = datetime(d.year, d.month, d.day, 15, 10, tzinfo=KIGALI) + timedelta(
                    minutes=float(self.rng.uniform(0, 60)))
            duration = max(300.0, self.rng.normal(50 * n_quotes, 8 * n_quotes))   # ~50 s per quote
            lat0, lon0 = P.MARKETS[m][1], P.MARKETS[m][2]
            lat, lon = lat0 + self.rng.normal(0, 0.0005), lon0 + self.rng.normal(0, 0.0005)
            photo_c = comms[int(self.rng.integers(len(comms)))]
            phash = f"{int(self.rng.integers(0, 2**63)):016x}"
            if fabricated:
                duration = float(self.rng.uniform(150, 220))
                lat, lon = lat0 + 0.036, lon0 - 0.012           # ~4 km away
                phash = photo_hashes[int(self.rng.integers(len(photo_hashes)))]
            photo_hashes.append(phash)
            sub_uuid = str(uuid.UUID(int=int(self.rng.integers(0, 2**63)) << 64 | int(self.rng.integers(0, 2**63))))
            groups = []
            for c in comms:
                base, size, perish, _, _ = P.COMMODITIES[c]
                available = not (c == "EGGS" and m == "KIM" and date(2026, 10, 5) <= d <= date(2026, 10, 9))
                quotes = []
                if available:
                    for code, veff in self.vendors[(c, m)][:n_vendors]:
                        kind = "perishable" if perish else "staple"
                        logp = self.true[(c, m)][i] + veff + self.rng.normal(0, P.NOISE_SD[kind])
                        if session == "PM" and perish:
                            logp += P.PM_EFFECT
                        price = round(math.exp(logp) * size / P.ROUND_TO) * P.ROUND_TO
                        if fabricated and code in last_reported:
                            price = round(last_reported[code] * (1 + self.rng.normal(0, 0.01)) / 50) * 50
                        elif lazy and code in last_reported and self.rng.random() < P.LAZY_COPY_SHARE:
                            price = last_reported[code]
                        elif lazy:
                            price = round(price / 100) * 100
                        if e == "E1" and self.rng.random() < P.TYPO_RATE:
                            typos.append((sub_uuid, c, code))
                            reported = price * 10
                        else:
                            reported = price
                            last_reported[code] = price
                        quotes.append({"commodities/quotes/vendor": code,
                                       "commodities/quotes/price": str(reported)})
                groups.append({"commodities/commodity": c,
                               "commodities/available": "yes" if available else "no",
                               "commodities/quotes": quotes})
            end_local = start_local + timedelta(seconds=duration)
            submitted = end_local + timedelta(minutes=float(self.rng.uniform(1, 90)))
            subs.append({
                "_uuid": sub_uuid,
                "_submission_time": submitted.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "_submitted_by": f"{e.lower()}_{m.lower()}",
                "start": start_local.isoformat(timespec="seconds"),
                "end": end_local.isoformat(timespec="seconds"),
                "deviceid": f"collect:{e}{m}device",
                "enumerator": e, "market": m, "visit_date": d.isoformat(), "session": session,
                "makeup": "yes" if makeup else "no",
                "location": f"{lat:.6f} {lon:.6f} 1550 8",
                "_geolocation": [round(lat, 6), round(lon, 6)],
                "photo_commodity": photo_c, "photo": f"IMG_{phash[:8]}.jpg",
                "photo_phash": phash,   # demo stand-in for a hash the server would compute from the image
                "commodities": groups,
            })
            if fabricated:
                misconduct.append((sub_uuid, e, "fabricated"))
            elif lazy:
                misconduct.append((sub_uuid, e, "lazy"))
        subs.sort(key=lambda s: s["_submission_time"])
        for k, s in enumerate(subs):
            s["_id"] = 100000 + k
        return subs, misconduct, typos

    # ── external series ────────────────────────────────────────────────────────
    def external(self):
        rows, fx = [], 1300.0
        for d in self.days:
            if d > P.HISTORY_END:
                break
            i = self.day_index[d]
            if d.day == 1 or d == P.START:
                rows.append(("DIESEL", d, float(self.diesel[i])))
                basket = np.mean([np.mean([self.true[(c, m)][i] for m in self.markets]) for c in self.commodities])
                rows.append(("BENCH_WFP", d, round(100 * math.exp(basket - self._basket0()) * math.exp(
                    self.rng.normal(0, 0.01)), 2)))
            fx *= math.exp(self.rng.normal(0.0003, 0.002))
            rows.append(("USDRWF", d, round(fx, 2)))
            doy = d.timetuple().tm_yday
            wet = 0.5 + 0.5 * math.cos(2 * math.pi * (doy - 105) / 182.6)   # long rains Mar–May, short rains Sep–Dec
            rain = float(self.rng.gamma(0.6, 6 * wet)) if self.rng.random() < 0.25 + 0.5 * wet else 0.0
            rows.append(("RAIN_KGL", d, round(rain, 1)))
        return rows

    def _basket0(self):
        return np.mean([np.mean([self.true[(c, m)][0] for m in self.markets]) for c in self.commodities])


def write_all(out: str, seed: int = P.SEED) -> dict:
    w = World(seed)
    subs, misconduct, typos = w.generate()
    os.makedirs(os.path.join(out, "truth"), exist_ok=True)
    with open(os.path.join(out, "submissions.jsonl"), "w") as f:
        for s in subs:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    with open(os.path.join(out, "vendors.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["code", "market", "commodity", "panel_rank"])
        for (c, m), panel in w.vendors.items():
            for rank, (code, _) in enumerate(panel, 1):
                wr.writerow([code, m, c, rank])
    with open(os.path.join(out, "external.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["series_code", "ts", "value"])
        wr.writerows(w.external())
    t = os.path.join(out, "truth")
    with open(os.path.join(t, "true_prices.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["day", "commodity", "market", "price"])
        for (c, m), arr in w.true.items():
            for d, v in zip(w.days, arr):
                wr.writerow([d.isoformat(), c, m, round(math.exp(v), 3)])
    with open(os.path.join(t, "misconduct.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["kobo_uuid", "enumerator", "kind"])
        wr.writerows(misconduct)
    with open(os.path.join(t, "typos.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["kobo_uuid", "commodity", "vendor"])
        wr.writerows(typos)
    with open(os.path.join(t, "events.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["code", "commodity", "market", "start_date", "end_date", "description"])
        for e in P.EVENTS:
            wr.writerow([e["code"], e["commodity"] or "", e["market"] or "", e["start"], e["end"], e["description"]])
    truth_params = {
        "vendor_sd": P.VENDOR_SD, "noise_sd": P.NOISE_SD, "day_shock_sd": P.DAY_SHOCK_SD,
        "market_shock_sd": P.MARKET_SHOCK_SD, "ar_persistence": P.AR_PERSISTENCE, "pm_effect": P.PM_EFFECT,
        "fuel_elasticity": {c: v[4] for c, v in P.COMMODITIES.items()}, "fuel_lag_days": P.FUEL_LAG_DAYS,
        "market_effects": {m: v[0] for m, v in P.MARKETS.items()}, "seed": seed,
    }
    with open(os.path.join(t, "params.json"), "w") as f:
        json.dump(truth_params, f, indent=2)
    return {"submissions": len(subs), "misconduct": len(misconduct), "typos": len(typos)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="demo/data")
    ap.add_argument("--seed", type=int, default=P.SEED)
    a = ap.parse_args()
    print(write_all(a.out, a.seed))
