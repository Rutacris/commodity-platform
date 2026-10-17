# Kigali Retail Price Monitoring — Pilot Methodology

Scope (fixed): retail prices, **Nyabugogo, Kimironko, Kabuga**, one enumerator per market at **50,000 RWF/month**, KoboToolbox, one home server (Postgres/TimescaleDB, FastAPI, Tailscale). This document makes the *method* rigorous; it does not widen the scope.

Labels: **[S]** sourced (link given) · **[J]** judgement · **[P]** to be settled by pilot data, not by argument.

Companion: `PLATFORM_PLAN.md` (architecture, product). Where the two disagree, this document wins on collection and statistics.

---

## 1. Decision and precision

### Users and decisions [J]
| User | Decision the price informs | What they need |
|---|---|---|
| Small traders / retailers | Which of the 3 markets to buy from this week | Market-to-market differences, current week |
| Households, NGOs, journalists | Is food getting more expensive? | Week-on-week and month-on-month change per commodity |
| Owner (platform) | Is a price move real or noise? | Known error band on every published number |

### Precision targets [J — revisit after pilot]
Work in **log prices** so all targets are percentages.
- **T1 (change):** detect a **5% week-on-week change** in a commodity's price in one market, 80% power, two-sided α = 0.05.
- **T2 (difference):** detect a **10% difference** between two markets in the same week.
- **T3 (publish rule):** every published weekly figure carries a 95% interval; if its half-width is > 7.5%, the figure is shown as "low confidence".

Everything below — number of vendors, number of days, commodity list length — is chosen to meet T1–T3 at the lowest enumerator workload.

---

## 2. Pilot protocol (Week 0 + 3 weeks dense collection)

### Week 0 — set-up (owner + 3 enumerators, 3–4 days)
1. **Stall census** per market: walk every section, count retail stalls selling each candidate commodity, sketch sections, give each stall a code (`NYB-S03-017` = market-section-stall). No names collected at this stage.
2. **Fixed vendor panel:** per commodity per market, randomly draw **5 stalls** from the census (random numbers, not enumerator choice) + **3 reserves** in rank order.
   - Replacement rule: a panel vendor absent **2 consecutive visits** or quitting is replaced by the next reserve in the same section; the replacement is logged with a date (the series treats it as a new vendor, see §5).
3. **Consent** from each panel vendor (script in §8); ask optionally for a phone number for back-checks.
4. **Unit weighing study:** for every commodity sold in local measures (basin/*umufuka*/heap/bunch/*agaseke*), buy-or-borrow and weigh **≥ 10 units per commodity per market** on a digital scale (± 5 g). Record mean, SD, CV. Repeat once per season (Season A/B) [J].
5. **Specification sheets** (§4) finalised with reference photos taken this week.
6. Train enumerators on the Kobo form (half day), do one supervised practice visit each.

### Weeks 1–3 — dense collection [J]
To estimate variance without exhausting enumerators, the pilot uses two tiers:

| Tier | Commodities | Vendors | Sessions | Days |
|---|---|---|---|---|
| **Design tier** | 10 (2 per food group, incl. tomatoes, beans, Irish potatoes, rice, maize flour, onions, cooking bananas, eggs, cooking oil, sugar) | **5** fixed panel | **AM 08:00–10:00 daily; PM 15:00–17:00 for the 5 perishables only** | Mon–Sat |
| **Routine tier** | remaining ~10 | 2 | AM only | Mon/Wed/Fri |

Workload: ≈ 50 AM design quotes + 20 routine quotes + 25 PM quotes → ~60 min AM, ~25 min PM [J — measure actual time from Kobo audit, §6].

### Pilot budget (one-off, estimates to replace with real quotes) [J]
| Item | RWF |
|---|---|
| Enumerator pilot pay, 3 × (Week 0 + 3 weeks intensive) | 3 × 60,000 = 180,000 |
| Digital scales, 3 | ~60,000 |
| Second enumerator for validation (§7.3), 2 weeks | ~40,000 |
| Airtime/data for back-checks and enumerators | ~20,000 |
| **Total** | **≈ 300,000** |

After the pilot, the routine design returns to 50,000 RWF/enumerator/month.

### Kobo form design
- One submission per market per session; repeat group per commodity; inside it a repeat per vendor (stall code pre-loaded from the panel list via `choice_filter`, so the enumerator picks, not types).
- Fields per quote: price (integer RWF), unit (choice), quantity of units, `not_available` flag.
- Metadata: `start`, `end`, `deviceid`, required `geopoint`, and the **`audit`** meta question with location and change tracking (e.g. `location-priority=balanced`, `track-changes=true`) — parameter names per a secondary source ([robotoolbox audit vignette](https://dickoa.r-universe.dev/robotoolbox/doc/audit-data.html)) [S, verify against ODK XLSForm docs before use].
- One randomly selected commodity per session requires a photo (`once(random())`-based calculate) [J].

---

## 3. Pilot analysis plan

Unit of analysis: one commodity in one market. Response `y = log(price per kg or per standard unit)`.

### 3.1 Variance decomposition [S for method, P for values]
Model per commodity × market:

```
y_vds = μ + session_s + u_v + w_d + e_vds
u_v  ~ N(0, σ²_vendor)        persistent vendor level (cancels in changes with a fixed panel)
w_d  ~ N(0, σ²_day)           market-wide day shock (true price movement + common noise)
e_vds ~ N(0, σ²_resid)        vendor×day noise (what the panel cannot remove)
```

statsmodels (crossed random effects via a single group + variance components):

```python
import numpy as np, pandas as pd, statsmodels.formula.api as smf

def decompose(df):                      # df: one commodity × market; cols price, vendor, day, session
    df = df.assign(y=np.log(df.price), g=1)
    m = smf.mixedlm("y ~ C(session)", df, groups="g",
                    vc_formula={"vendor": "0 + C(vendor)", "day": "0 + C(day)"},
                    re_formula="0").fit(reml=True)
    vc = dict(zip(m.model.exog_vc.names, m.vcomp))
    return {"s2_vendor": vc["vendor"], "s2_day": vc["day"], "s2_resid": m.scale,
            "session_effect": m.fe_params.get("C(session)[T.PM]", np.nan)}
```

### 3.2 From variances to number of vendors (k) and days (d) [J — standard design algebra]
With a **fixed panel**, the vendor effect cancels in week-on-week change. The weekly mean over d visits and k vendors has, for change between two weeks:

```
SE(Δ) ≈ sqrt( 2 * ( σ²_resid / (k·d)  +  σ²_dayNoise / d ) )
MDE   = (1.96 + 0.84) · SE(Δ)          # 80% power, α = 0.05
```

`σ²_dayNoise` = part of σ²_day that is not persistent within a week (estimate as the within-week variance of daily means after removing a weekly mean). Choose the **smallest k·d meeting MDE ≤ 5%** (T1), and check T2 using σ²_vendor for between-market comparisons.

Output table **[P]**: for each design-tier commodity, required (k, d) pairs, e.g. (2,3), (3,3), (2,6).

### 3.3 Thinning test — is 3 days/week enough? [J]
1. "Truth" = weekly mean using all days, all 5 vendors, AM.
2. Resample designs: days ∈ {Mon/Wed/Fri, Tue/Thu/Sat, 2 random days}, vendors ∈ {2, 3} drawn from the panel, 500 bootstrap draws.
3. Metrics: RMSE (%) of weekly mean vs truth; RMSE of week-on-week change; for perishables, share of daily moves > 10% that the design would have caught within the same week.
4. Decision rule: adopt the cheapest design with RMSE(change) ≤ 2.5% for staples and ≤ 5% for perishables **[P]**.

### 3.4 AM vs PM [P]
If the session effect is < 2% and not significant for all perishables → **AM only** (current plan). Otherwise add a short PM visit for those items only.

### 3.5 Limitation
Three weeks cannot show seasonality or rare spikes. Spike frequency is estimated from WFP's historical Kigali series (§7.1) instead.

---

## 4. Commodity specification sheets

One sheet per commodity, frozen before Week 1. Kinyarwanda names below are drafts **to be reviewed by a native speaker and by vendors during Week 0** [J].

| # | English | Kinyarwanda (draft) | Français | Spec (variety / grade) | Pricing unit | Std unit |
|---|---|---|---|---|---|---|
| 1 | Maize grain, dry | Ibigori byumye | Maïs grain | white, loose, clean | kg | kg |
| 2 | Maize flour | Kawunga | Farine de maïs | loose (not branded pack) | kg | kg |
| 3 | Rice, local | Umuceri wo mu Rwanda | Riz local | most common local variety [P] | kg | kg |
| 4 | Rice, imported | Umuceri utumizwa hanze | Riz importé | long grain, loose | kg | kg |
| 5 | Sorghum | Amasaka | Sorgho | red, dry | kg | kg |
| 6 | Wheat flour | Ifu y'ingano | Farine de blé | most common 2 kg brand [P] | pack | kg |
| 7 | Cassava flour | Ifu y'imyumbati | Farine de manioc | white, loose | kg | kg |
| 8 | Beans, dry | Ibishyimbo | Haricots secs | mixed, dry (and 1 named variety [P]) | kg | kg |
| 9 | Peas, dry | Amashaza | Petits pois secs | dry | kg | kg |
| 10 | Groundnuts | Ubunyobwa | Arachides | shelled, raw | kg | kg |
| 11 | Irish potatoes | Ibirayi | Pommes de terre | medium size, most common variety [P] | kg / basin | kg |
| 12 | Sweet potatoes | Ibijumba | Patates douces | medium, fresh | kg / heap | kg |
| 13 | Cassava, fresh | Imyumbati mibisi | Manioc frais | fresh roots | kg / heap | kg |
| 14 | Cooking bananas | Ibitoki | Bananes à cuire | medium bunch → weigh | bunch / kg | kg |
| 15 | Tomatoes | Inyanya | Tomates | fresh, medium, grade 1 | kg / basin | kg |
| 16 | Onions | Ibitunguru | Oignons | red, medium | kg | kg |
| 17 | Cabbage | Amashu | Chou | medium head | head | kg |
| 18 | Carrots | Karoti | Carottes | medium | kg | kg |
| 19 | Eggs | Amagi | Œufs | tray of 30, medium | tray | egg |
| 20 | Milk, fresh | Amata | Lait frais | loose or 500 ml pack [P] | litre | litre |
| 21 | Beef | Inyama z'inka | Viande de bœuf | with bone, standard cut | kg | kg |
| 22 | Cooking oil | Amavuta yo guteka | Huile de cuisine | most common brand, 1 L [P] | litre | litre |
| 23 | Sugar | Isukari | Sucre | white, loose | kg | kg |
| 24 | Salt | Umunyu | Sel | iodised, 1 kg pack | kg | kg |

Each sheet also holds: reference photo, accepted substitutes (none by default), local units with weights from the Week 0 study, and "how to ask the price" wording. Charcoal is dropped from the pilot (not food, sack sizes vary widely) [J].

---

## 5. Rules for building the price series

### 5.1 Elementary price (one commodity, one market, one visit)
- Convert each quote to price per standard unit using the Week 0 weights.
- **Visit price = geometric mean of vendor prices.** Change between visits uses the **matched-sample Jevons index**: `exp(mean over vendors quoted in both visits of log(p_t / p_{t-1}))`. Geometric (Jevons/Dutot) elementary indices are preferred over Carli in the revised CPI Manual ([IMF summary](https://www.imf.org/-/media/files/data/cpi/2019/overview-of-updated-cpi-manual.pdf.md), [Statistics Canada](https://www150.statcan.gc.ca/n1/pub/62-553-x/2019001/chap-6-eng.htm)) [S].
- Replacement vendor: enters the matched set from its second visit (no link on first visit) [J].

### 5.2 Missing data
| Case | Rule |
|---|---|
| One panel vendor missing | Impute by the mean change of the other matched vendors (equivalent to excluding it from the matched index) — "class-mean" style imputation discussed in the CPI Manual's missing-price chapter ([ILO ch.9](https://webapps.ilo.org/CPI/doc/ch9_rev_1c.pdf)) [S, exact preferred method to confirm in the 2020 Manual]. |
| Commodity "not available" in market | **No price** for that visit; publish "not available" (it is information). Never carry forward. |
| Whole visit missed | Make-up visit next day allowed (flagged). Otherwise gap; weekly figure uses remaining visits if ≥ 2 of 3, else "insufficient data". |
| Fewer than 2 vendors quoted | Not published; kept internally. |

### 5.3 Weekly and monthly figures
- Weekly market price = geometric mean of visit prices in the ISO week; national (3-market) figure = geometric mean of the 3 market prices (equal weights; no expenditure weights exist for these markets) [J].
- Monthly = geometric mean of weekly prices.

### 5.4 Seasonality and spikes
- Seasonal adjustment needs ≥ 3 years of own data. Until then use **STL** on WFP's historical Kigali series for the same commodity to obtain seasonal factors, and apply them to own data as provisional [J].
- **Spike flag:** WFP's ALPS method estimates a seasonal trend and measures the gap between the observed and estimated price, scaled by its historical variability ([WFP ALPS guidance](https://vamresources.manuals.wfp.org/docs/alps-calculation-and-use-of-the-alert-for-price-spikes-indicator), [2014 technical note](https://documents.wfp.org/stellent/groups/public/documents/manual_guide_proced/wfp264186.pdf)) [S for steps]. The category cut-offs (Normal/Stress/Alert/Crisis) were **not verified** in this research — read them from the WFP note before implementing.
- Until ALPS is calibrated: weekly robust z-score of week-on-week change (median/MAD of the commodity's own history + WFP history) with |z| > 3 = "unusual" [J].

---

## 6. Data-quality system

### 6.1 Automatic checks per submission (thresholds are starting values; recalibrate from pilot [P])
| Check | Rule | Action |
|---|---|---|
| Location | geopoint missing or > 300 m from market centroid | hold for review |
| Timing | `start` outside session window | hold |
| Speed | form duration < 40% of the enumerator's median duration (from audit log) | hold |
| Copy-paste | ≥ 60% of quotes identical to the same vendor's previous visit (staples) / ≥ 40% (perishables) | flag |
| Vendor spread | all vendor quotes identical for a commodity on ≥ 3 consecutive visits; or max/min ratio > 2 | flag |
| Digit preference | share of prices ending in "00" > enumerator's pilot baseline + 20 pts over a week | flag |
| Outlier | |log p − rolling median| > 4 × MAD (vendor) or market price deviates > 30% from the other two markets' median (non-perishables) | hold |
| Photo | missing when required; perceptual hash equal to any earlier photo; EXIF time > 2 h from `start` | hold |
| Edits | audit log shows a price changed > 2 times | flag |

### 6.2 As code (pandera, runs in the ingest worker) [J]
```python
import pandera as pa
from pandera import Column, Check

quotes = pa.DataFrameSchema({
    "market":    Column(str, Check.isin(["NYB", "KIM", "KAB"])),
    "commodity": Column(str),
    "vendor":    Column(str, Check.str_matches(r"^(NYB|KIM|KAB)-S\d{2}-\d{3}$")),
    "price_rwf": Column(int, Check.in_range(10, 50_000)),          # per-commodity ranges loaded from spec sheets
    "unit":      Column(str),
    "dist_m":    Column(float, Check.le(300), nullable=False),
    "duration_ratio": Column(float, Check.ge(0.4)),
}, checks=[
    Check(lambda d: d.groupby(["commodity", "visit_id"]).price_rwf.nunique().gt(1).mean() >= 0.5,
          error="too many commodities with identical vendor quotes"),
])
```
Failures write a row to `core.qc_flags(submission_id, rule, value, threshold)`; the review queue in Metabase lists them.

### 6.3 Back-checks [S for rates]
- IPA recommends back-checking **≥ 10% of surveys (or 40/week)**, **≥ 1 per enumerator per week**, done **within 3 days** ([IPA back-checks](https://data.poverty-action.org/data-quality/backchecks.html)); DIME suggests 10–20%, with **20% in the first two weeks** ([DIME Wiki](https://dimewiki.worldbank.org/Back_Checks)) [S].
- Applied here [J]: unit = one vendor quote. **Pilot:** 20% of design-tier vendor-visits in Weeks 1–2, 10% in Week 3. **Routine:** ≥ 2 quotes per enumerator per week, by phone **same day** (prices move), random selection weighted towards flagged rows.
- Match criterion: back-check price within **±10%** of the reported price.
- Enumerator thresholds: match rate ≥ 85% = good; 75–85% = coaching; < 75% in a month = warning; two consecutive months < 75% = replace.

### 6.4 Spot checks
Unannounced, every 2 weeks, one market chosen at random, ~5 commodities, same panel vendors, within 1 h of the enumerator's visit. Same ±10% criterion.

### 6.5 Enumerator scorecard (monthly)
Completeness 30% · on-time 15% · photo compliance 10% · QC-flag rate (inverse) 15% · back-check match 20% · spot-check match 10% → 0–100; bonus = score/100 × 5,000 RWF [J].

---

## 7. External validation

### 7.1 Raw sources to obtain
| Source | What to request | How | Status |
|---|---|---|---|
| **NISR** CPI price microdata, Kigali food items | item-level monthly prices, outlet type, collection dates | written request to NISR (statistics.gov.rw); NISR historically collects prices monthly in all regions incl. Kigali, on business days of weeks 1 and 3 ([ILO metadata, 2013](https://webapps.ilo.org/ilostat-files/SSM/SSM1_NEW/E/RWA_CPI_Descriptions%20-2013.pdf)) [S, may be outdated] | No public microdata portal found |
| **WFP** Data Bridges | market-level Kigali price records (not HDX aggregates) | credentials from wfp.vaminfo@wfp.org; Python wrapper `data_bridges_knots` ([repo](https://github.com/WFP-VAM/DataBridgesKnots)) [S] | Request now |
| **MINAGRI e-Soko** | raw daily market series for Kigali markets | request to MINAGRI | Unknown availability [J] |
| **RURA** | official fuel pump price announcements | website notices, scrape/manual | [J] |
| **BNR** | daily RWF exchange rates | website tables | [J] |

### 7.2 Comparison tolerances (levels differ because of outlet and specification; compare *changes*) [J]
Over the first 6 months, per commodity with an overlapping series:
- correlation of monthly % changes ≥ 0.6, and sign agreement ≥ 70%;
- ratio of levels (own / NISR or WFP) stable: CV of the monthly ratio ≤ 15%;
- any month with a > 15-point divergence in % change gets a written explanation.

### 7.3 Inter-rater check (second enumerator, 2 weeks during routine phase) [J for design, S for statistic]
- A fourth, independent person collects the same panel vendors in each market on 4 visits (rotating markets), within 1 h of the regular enumerator, without seeing their data.
- Statistic: **ICC(2,1)** on log price per commodity (`pingouin.intraclass_corr`) and median absolute % difference.
- Targets: ICC ≥ 0.90 (staples), ≥ 0.80 (perishables); median |diff| ≤ 5%.

### 7.4 Outside reviewers
Send the methodology (this document) and pilot results for review to: **WFP Rwanda VAM unit**, **NISR price statistics unit**, **IFPRI Rwanda** (has run training on e-Soko price data), **University of Rwanda – College of Agriculture (agricultural economics)**. Also ask **3–5 Nyabugogo/Kimironko traders** monthly whether published prices are plausible.

---

## 8. Data-protection checklist (Law No. 058/2021) [S for law points via secondary sources; verify against the official gazette]
- [ ] **Register with NCSA** as data controller (art. 29); application covers identity, data categories, purposes, recipients, transfers (art. 30). Operating without registration risks a fine of **2–5 million RWF** ([DLA Piper](https://www.dlapiperdataprotection.com/?c=RW&t=law), [Digital Policy Alert](https://digitalpolicyalert.org/event/24878-implemented-law-no-0582021-relating-to-the-protection-of-personal-data-and-privacy-including-business-registration-requirements)).
- [ ] Designate a responsible person (DPO role) — the owner initially.
- [ ] **Vendors:** identify by stall code only. Phone number only with explicit consent and only for back-checks; stored in a separate, encrypted table, never published, deleted when the vendor leaves the panel.
- [ ] **Consent script** (Kinyarwanda, read aloud): who we are, why we ask prices, that prices are published only as market averages, that names are not recorded, optional phone for verification calls, right to stop.
- [ ] **Enumerators:** name, phone, MoMo number and GPS traces are personal data; written agreement stating use (payment, quality control); restrict access.
- [ ] **Photos:** produce and price only; no faces; strip EXIF location after QC.
- [ ] Publish only aggregates of ≥ 2 vendors; never per-vendor prices.
- [ ] Retention: raw submissions 5 years; vendor contacts until panel exit; GPS traces 12 months [J].
- [ ] Check claims of data-localisation and breach-notification deadlines against the official law text (only a vendor source reports them) — relevant because backups go to cloud storage.

---

## 9. Pass/fail criteria (fixed before Week 1)

The pilot "passes" and the platform goes public only if **all** hold:

| # | Criterion | Threshold |
|---|---|---|
| 1 | Completeness (scheduled visits submitted) | ≥ 90% per market |
| 2 | Precision: design chosen in §3.2 achieves MDE ≤ 5% week-on-week | ≥ 8 of 10 design-tier commodities |
| 3 | Thinning test | chosen routine design meets §3.3 RMSE rule |
| 4 | Back-check match (±10%) | ≥ 85% overall, no enumerator < 75% |
| 5 | Spot-check match (±10%) | ≥ 85% |
| 6 | Inter-rater ICC (log price) | ≥ 0.90 staples, ≥ 0.80 perishables |
| 7 | QC holds | ≤ 10% of quotes held in Week 3 |
| 8 | Unit weights | CV ≤ 20% for every local unit kept; otherwise that unit is dropped and weighing required |
| 9 | Workload | median routine visit ≤ 45 min (from audit log) |
| 10 | NCSA registration | filed |

Failing any criterion → fix, then extend the pilot by 2 weeks and re-test that criterion only.

---

## 10. Timeline

| Week | Activity |
|---|---|
| −2 to −1 | NCSA registration filed; data requests to NISR, WFP, MINAGRI; Kobo form; scales bought; enumerators recruited |
| 0 | Census, panel draw, consent, weighing, spec sheets, training |
| 1–3 | Dense pilot, daily QC, back-checks |
| 4 | Analysis (§3), choose routine design, write up |
| 5–6 | Routine design live internally; inter-rater check (§7.3) |
| 7 | Pass/fail review (§9) → public launch or extension |

---

## Sources
- KoboToolbox limits: https://support.kobotoolbox.org/account_usage_limits.html
- Kobo audit parameters (secondary): https://dickoa.r-universe.dev/robotoolbox/doc/audit-data.html
- IMF CPI Manual update summary: https://www.imf.org/-/media/files/data/cpi/2019/overview-of-updated-cpi-manual.pdf.md
- ILO CPI Manual ch. 9: https://webapps.ilo.org/CPI/doc/ch9_rev_1c.pdf
- Statistics Canada CPI reference: https://www150.statcan.gc.ca/n1/pub/62-553-x/2019001/chap-6-eng.htm
- WFP ALPS: https://vamresources.manuals.wfp.org/docs/alps-calculation-and-use-of-the-alert-for-price-spikes-indicator ; https://documents.wfp.org/stellent/groups/public/documents/manual_guide_proced/wfp264186.pdf
- IPA back-checks: https://data.poverty-action.org/data-quality/backchecks.html ; IPA HFC: https://github.com/PovertyAction/high-frequency-checks
- DIME back-checks: https://dimewiki.worldbank.org/Back_Checks
- NISR CPI metadata (2013): https://webapps.ilo.org/ilostat-files/SSM/SSM1_NEW/E/RWA_CPI_Descriptions%20-2013.pdf
- WFP DataBridgesKnots: https://github.com/WFP-VAM/DataBridgesKnots
- Rwanda data protection: https://www.dlapiperdataprotection.com/?c=RW&t=law ; https://digitalpolicyalert.org/event/24878-implemented-law-no-0582021-relating-to-the-protection-of-personal-data-and-privacy-including-business-registration-requirements
