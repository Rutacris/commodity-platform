"""Parameters of the synthetic world. All price levels are illustrative, not real Kigali prices."""
from datetime import date

SEED = 20261017
START = date(2024, 10, 14)          # Monday
HISTORY_END = date(2026, 10, 16)    # Friday; released at demo start
LIVE_END = date(2026, 12, 31)       # generated ahead for live mode
COLLECTION_WEEKDAYS = (0, 2, 4)     # Mon, Wed, Fri
MISSED_VISIT_RATE = 0.05
MAKEUP_RATE = 0.5                   # share of missed visits made up the next day
ROUTINE_VENDORS = 2

# Dense pilot block: daily Mon–Sat, 5 vendors for design-tier commodities, PM visit for perishables.
PILOT_START = date(2026, 8, 31)
PILOT_END = date(2026, 9, 19)
PILOT_VENDORS = 5
DESIGN_TIER = ["TOMATO", "BEANS", "IPOT", "RICE_L", "MFLOUR", "ONION", "BANANA", "EGGS", "OIL", "SUGAR"]

MARKETS = {  # code: (log market effect, lat, lon)
    "NYB": (-0.05, -1.9386, 30.0446),
    "KIM": (0.07, -1.9496, 30.1260),
    "KAB": (-0.03, -1.9757, 30.2279),
}
ENUMERATORS = {"E1": "KIM", "E2": "KAB", "E3": "NYB"}

# code: (base RWF per price unit, price_unit size in std units, perishable, season amplitude, fuel elasticity)
COMMODITIES = {
    "MAIZE":   (450, 1, False, 0.12, 0.05),
    "MFLOUR":  (800, 1, False, 0.08, 0.15),
    "RICE_L":  (1300, 1, False, 0.04, 0.05),
    "RICE_I":  (1700, 1, False, 0.00, 0.15),
    "SORGHUM": (700, 1, False, 0.10, 0.05),
    "WFLOUR":  (2600, 2, False, 0.00, 0.15),
    "CFLOUR":  (650, 1, False, 0.05, 0.05),
    "BEANS":   (1000, 1, False, 0.12, 0.05),
    "PEAS":    (1600, 1, False, 0.08, 0.05),
    "GNUTS":   (2200, 1, False, 0.05, 0.05),
    "IPOT":    (450, 1, False, 0.15, 0.08),
    "SPOT":    (1000, 3, True, 0.10, 0.05),
    "CASSAVA": (350, 1, True, 0.06, 0.05),
    "BANANA":  (400, 1, True, 0.08, 0.05),
    "TOMATO":  (4500, 4.5, True, 0.20, 0.08),
    "ONION":   (1200, 1, True, 0.12, 0.08),
    "CABBAGE": (400, 1, True, 0.15, 0.05),
    "CARROT":  (800, 1, True, 0.12, 0.05),
    "EGGS":    (4500, 30, False, 0.03, 0.05),
    "MILK":    (500, 1, True, 0.05, 0.05),
    "BEEF":    (5000, 1, True, 0.02, 0.05),
    "OIL":     (2800, 1, False, 0.00, 0.15),
    "SUGAR":   (1600, 1, False, 0.00, 0.12),
    "SALT":    (500, 1, False, 0.00, 0.05),
}

TREND_PER_MONTH = 0.005
FUEL_LAG_DAYS = 21
AR_PERSISTENCE = 0.8
DAY_SHOCK_SD = {"perishable": 0.035, "staple": 0.012}       # AR(1) innovation sd, common to all markets
MARKET_SHOCK_SD = 0.010                                      # market-specific AR(1) innovation sd
VENDOR_SD = 0.05                                             # persistent vendor level
NOISE_SD = {"perishable": 0.05, "staple": 0.03}              # vendor × day noise
PM_EFFECT = -0.02                                            # afternoon discount on perishables
ROUND_TO = 10                                                # honest vendors quote to the nearest 10 RWF

# Scripted events (applied to the true price, stored in truth.events).
EVENTS = [
    dict(code="FUEL_HIKE", commodity=None, market=None, start=date(2026, 7, 1), end=date(2026, 12, 31),
         description="Synthetic diesel price +12% (feeds through to fuel-sensitive goods after ~3 weeks)"),
    dict(code="POTATO_GLUT_NYB", commodity="IPOT", market="NYB", start=date(2026, 8, 17), end=date(2026, 9, 13),
         description="Irish potato supply glut at Nyabugogo only: −20%"),
    dict(code="TOMATO_SHORTAGE", commodity="TOMATO", market=None, start=date(2026, 9, 28), end=date(2026, 11, 8),
         description="Tomato shortage: rises to +45% over 2 weeks, then decays"),
    dict(code="EGGS_OUT_KIM", commodity="EGGS", market="KIM", start=date(2026, 10, 5), end=date(2026, 10, 9),
         description="Eggs not available at Kimironko for 3 visits"),
]

# Enumerator misconduct.
LAZY_FROM = date(2026, 8, 3)        # E2 starts copying previous prices
LAZY_COPY_SHARE = 0.7
FABRICATION_DATES = [date(2026, 6, 10), date(2026, 7, 22), date(2026, 9, 25), date(2026, 10, 14)]  # E3
TYPO_RATE = 0.002                   # E1 extra zero
