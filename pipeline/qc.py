"""Automatic quality checks run on every visit before its prices are published.

severity 'hold'  → not published until a reviewer accepts it
severity 'flag'  → published, but listed in the review queue and counted in the scorecard
Thresholds are starting values from docs/PILOT_METHODOLOGY.md §6.1; recalibrate with pilot data.
"""
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

GEOFENCE_M = 300
SPEED_RATIO = 0.4
COPY_SHARE_HOLD = 0.6
ROUND00_SHARE_FLAG = 0.5
IDENTICAL_SHARE_FLAG = 0.5
OUTLIER_MIN_LOG = 0.35
OUTLIER_MAD_K = 4
WINDOWS = {"AM": (8.0, 11.0), "PM": (14.5, 17.5)}
COLLECTION_WEEKDAYS = {0, 2, 4}


@dataclass
class Flag:
    rule: str
    severity: str
    detail: dict
    commodity_id: int | None = None
    vendor_id: int | None = None


@dataclass
class VisitQC:
    flags: list[Flag] = field(default_factory=list)

    @property
    def held(self) -> bool:
        return any(f.severity == "hold" and f.vendor_id is None for f in self.flags)

    def held_quotes(self) -> set[tuple[int, int]]:
        return {(f.commodity_id, f.vendor_id) for f in self.flags if f.severity == "hold" and f.vendor_id}


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def run(cur, visit: dict, quotes: list[dict], pilot: tuple[date, date] | None = None) -> VisitQC:
    """visit: dict with keys from core.visits (+ session, makeup, local_start_hour, n_quotes).
    quotes: list of dicts (commodity_id, vendor_id, price_rwf, available)."""
    qc = VisitQC()
    priced = [q for q in quotes if q["available"] and q["price_rwf"] is not None and q["vendor_id"]]

    # Location
    if visit["dist_m"] is None:
        qc.flags.append(Flag("gps_missing", "hold", {}))
    elif visit["dist_m"] > GEOFENCE_M:
        qc.flags.append(Flag("outside_market", "hold", {"dist_m": round(visit["dist_m"]), "limit_m": GEOFENCE_M}))

    # Timing
    lo, hi = WINDOWS[visit["session"]]
    if not lo <= visit["local_start_hour"] <= hi:
        qc.flags.append(Flag("outside_window", "flag", {"start_hour": round(visit["local_start_hour"], 2)}))
    d: date = visit["visit_date"]
    in_pilot = pilot and pilot[0] <= d <= pilot[1]
    on_schedule = d.weekday() in COLLECTION_WEEKDAYS or in_pilot or (
        visit["makeup"] and (d - timedelta(days=1)).weekday() in COLLECTION_WEEKDAYS)
    if not on_schedule:
        qc.flags.append(Flag("off_schedule", "flag", {"weekday": d.strftime("%A")}))

    # Speed: seconds per quote against the enumerator's own history
    n = max(len(priced), 1)
    hist = cur.execute(
        """SELECT v.duration_s::float / nullif(count(q.*), 0)
           FROM core.visits v JOIN core.price_quotes q ON q.visit_id = v.id AND q.vendor_id <> 0
           WHERE v.enumerator_id = %s AND v.id <> %s
           GROUP BY v.id ORDER BY v.visit_date DESC LIMIT 30""",
        (visit["enumerator_id"], visit["id"])).fetchall()
    rates = [r[0] for r in hist if r[0]]
    if len(rates) >= 5:
        own = visit["duration_s"] / n
        if own < SPEED_RATIO * median(rates):
            qc.flags.append(Flag("too_fast", "hold", {"sec_per_quote": round(own, 1),
                                                      "usual": round(median(rates), 1)}))

    # Photo
    if not visit["photo_hash"]:
        qc.flags.append(Flag("photo_missing", "flag", {}))
    else:
        dup = cur.execute("SELECT kobo_uuid FROM core.visits WHERE photo_hash = %s AND id <> %s LIMIT 1",
                          (visit["photo_hash"], visit["id"])).fetchone()
        if dup:
            qc.flags.append(Flag("photo_reused", "hold", {"also_in": dup[0]}))

    # Price patterns
    if priced:
        prev = dict(cur.execute(
            """SELECT DISTINCT ON (vendor_id) vendor_id, price_rwf FROM core.price_quotes
               WHERE vendor_id = ANY(%s) AND visit_id <> %s AND observed_at < %s AND price_rwf IS NOT NULL
               ORDER BY vendor_id, observed_at DESC""",
            ([q["vendor_id"] for q in priced], visit["id"], visit["started_at"])).fetchall())
        comparable = [q for q in priced if q["vendor_id"] in prev]
        if len(comparable) >= 10:
            same = sum(q["price_rwf"] == prev[q["vendor_id"]] for q in comparable) / len(comparable)
            if same >= COPY_SHARE_HOLD:
                qc.flags.append(Flag("copied_prices", "hold", {"share_same_as_last": round(same, 2)}))
        r00 = sum(q["price_rwf"] % 100 == 0 for q in priced) / len(priced)
        if len(priced) >= 10 and r00 > ROUND00_SHARE_FLAG:
            qc.flags.append(Flag("round_numbers", "flag", {"share_ending_00": round(r00, 2)}))
        by_c: dict[int, list[int]] = {}
        for q in priced:
            by_c.setdefault(q["commodity_id"], []).append(q["price_rwf"])
        multi = [v for v in by_c.values() if len(v) >= 2]
        if len(multi) >= 5:
            ident = sum(len(set(v)) == 1 for v in multi) / len(multi)
            if ident > IDENTICAL_SHARE_FLAG:
                qc.flags.append(Flag("identical_vendors", "flag", {"share": round(ident, 2)}))

        # Outliers against each vendor's recent accepted prices
        recent = cur.execute(
            """SELECT vendor_id, array_agg(price_rwf ORDER BY observed_at DESC) FROM (
                 SELECT vendor_id, price_rwf, observed_at,
                        row_number() OVER (PARTITION BY vendor_id ORDER BY observed_at DESC) rn
                 FROM core.price_quotes
                 WHERE vendor_id = ANY(%s) AND status = 'ok' AND observed_at < %s AND price_rwf > 0) t
               WHERE rn <= 6 GROUP BY vendor_id""",
            ([q["vendor_id"] for q in priced], visit["started_at"])).fetchall()
        recent = dict(recent)
        for q in priced:
            h = recent.get(q["vendor_id"])
            if not h or len(h) < 3 or q["price_rwf"] <= 0:
                continue
            logs = [math.log(x) for x in h]
            med = median(logs)
            mad = median(abs(x - med) for x in logs) * 1.4826
            dev = abs(math.log(q["price_rwf"]) - med)
            if dev > max(OUTLIER_MAD_K * mad, OUTLIER_MIN_LOG):
                qc.flags.append(Flag("price_outlier", "hold",
                                     {"price": q["price_rwf"], "recent_median": round(math.exp(med))},
                                     q["commodity_id"], q["vendor_id"]))
    return qc
