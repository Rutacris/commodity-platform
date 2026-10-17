# Rwanda Commodity Price Intelligence Platform — Plan

Status: draft plan, no code changed yet. Date: 2026-10-17.

Evidence labels: **[V]** confirmed by a source during research, **[J]** judgement / not verified.

---

## 0. Pilot scope (decided)

| Item | Decision |
|---|---|
| Markets | **Nyabugogo, Kimironko, Kabuga** (Kigali) |
| Price type | **Retail only** (schema keeps `price_type` so wholesale can be added later) |
| Collectors | **1 enumerator per market** (3 total), recruited via market committee or cooperative |
| Institutions | None yet; public sources (WFP/HDX, CHIRPS) used without agreements |
| Hosting | **One self-hosted server at the owner's premises** |

| Frequency | **3 collection days per week, one morning visit** (not daily, not twice a day) |

Volume: 3 markets × ~25 commodities × 2 quotes × ~13 visits/month ≈ 2,000 prices/month (~24k/year).

### Collection protocol — kept light on purpose [J]
Principle: 50,000 RWF/month buys a **short, simple routine**. The enumerator collects; the **system and the owner do the checking**. Target: **≤ 45 minutes per visit**.
- Days: **Monday, Wednesday, Friday**, same days in all 3 markets (so markets are comparable). Window **08:00–11:00**. A missed day can be made up the next day, flagged as such. Last-Saturday Umuganda is not a collection day anyway.
- **2 vendors per commodity** (not 3); the platform publishes the average/median of the two.
- Same variety/grade every time; record price in the vendor's unit (kg, basin, heap…) and the platform converts. No mandatory weighing.
- One optional question, only for the ~8 staples: "where did this come from?" (district). Availability score dropped for now.
- If a commodity is not in the market that day: one tap "not available" (useful data in itself).
- Afternoon prices: only added later, if the data shows big morning/afternoon differences for perishables (e.g. tomatoes).
- Effect on the platform: charts are **3 points per week**; % change compares with the previous visit and with the same day last week; anomaly checks run weekly. Real-time updates still apply when a visit lands, but are less critical.

### Starter commodity list (≈25, to be confirmed) [J]
Cereals and flours: maize grain, maize flour (kawunga), rice local, rice imported, sorghum, wheat flour, cassava flour.
Pulses and nuts: dry beans (mixed), dry beans (yellow/"kinyobwa"), peas, groundnuts.
Roots, tubers, bananas: Irish potatoes, sweet potatoes, fresh cassava, cooking bananas.
Vegetables: tomatoes, onions, cabbage, carrots.
Animal products: eggs (tray), fresh milk (litre), beef, fish (tilapia).
Other: cooking oil (litre), sugar, salt, charcoal (sack).

---

## 0b. Data engineering infrastructure (single home server)

No domain for now. Everything runs in Docker Compose on one internet-connected server running **Tailscale**.

```
 Enumerator phones (KoboCollect, offline-capable)
          │  submit when online
          ▼
 KoboToolbox cloud (free Community plan) ── stores every submission + photos
          │ (1) REST Service webhook ──► Tailscale Funnel https://<server>.<tailnet>.ts.net/ingest/kobo   (fast path)
          │ (2) API poll every 5 min  ◄── ingest worker                                                 (safety net)
          ▼
 ┌──────────────────────── home server (docker compose) ─────────────────────────┐
 │ ingest worker (Python + APScheduler)                                          │
 │   kobo poller/webhook → raw.kobo_submissions (JSON as received, never edited) │
 │   validate + QC scoring → core.price_observations (quality flags)             │
 │   external jobs: WFP/HDX weekly, CHIRPS weekly                                │
 │ Postgres 17 + TimescaleDB  (raw → core → serving: caggs, derived_metrics)     │
 │ FastAPI (REST + SSE)  ── public pages + API via Tailscale Funnel              │
 │ Metabase (internal QC + analysis)  ── tailnet only, never on Funnel           │
 │ pg_cron (metrics), backup job (pg_dump → rclone → cloud bucket)               │
 │ Ollama (optional)                                                             │
 └───────────────────────────────────────────────────────────────────────────────┘
          │ heartbeat pings                         │ nightly encrypted backup
          ▼                                         ▼
 Healthchecks.io (free) – alerts if server/jobs stop   Backblaze B2 / Cloudflare R2 free tier
```

**Why both webhook and polling:** Kobo REST Service delivers within seconds but retries only a few times and has known timeout issues ([forum](https://community.kobotoolbox.org/t/no-retries-for-rest-service-submissions/64448), [forum](https://community.kobotoolbox.org/t/handling-rest-service-failures/24277)) [V — community reports]. The poller asks Kobo for anything submitted since the last seen ID, so outages of the server or home internet lose nothing. Ingest is idempotent on the Kobo submission UUID.

**Layers (simple "medallion"):**
- `raw` — submissions exactly as received (JSON + photo links). Allows re-processing when rules change.
- `core` — cleaned observations, reference tables (markets, commodities, units, enumerators), QC flags.
- `serving` — continuous aggregates, `derived_metrics`, what the API reads.

**Free services used**

| Service | Use | Limit to watch |
|---|---|---|
| KoboToolbox Community | forms, offline collection, storage of submissions | **5,000 submissions/month, 1 GB files** ([support](https://support.kobotoolbox.org/account_usage_limits.html), [pricing](https://kobotoolbox.org/pricing)) [V]. Design: one submission per market per session with a repeat group per commodity → ~40/month. Photos: compress, keep few per session; the server copies them out of Kobo and deletes old ones if storage fills. |
| Tailscale | private admin access (SSH, Metabase, DB) + **Funnel** for public HTTPS on a `ts.net` name, no domain, no port forwarding ([docs](https://tailscale.com/docs/use-cases/application-testing/share-local-dev-server-with-internet)) [V]. Funnel only allows ports 443/8443/10000 and has bandwidth limits [V — third-party]; confirm it is on the free plan [unverified]. | If public traffic grows → domain + Cloudflare Tunnel. |
| Healthchecks.io | dead-man switch: worker pings every 5 min; email/Telegram if it stops | free tier [J] |
| Backblaze B2 or Cloudflare R2 | off-site encrypted DB backups | ~10 GB free [J] |

**Not needed now:** Airflow/Dagster (APScheduler is enough for ~5 jobs), dbt (SQL lives in migrations), Kafka, ClickHouse, Grafana.

**Server hygiene:** UPS for server + router; Docker `restart: always`; Postgres port not published (already bound to localhost); admin tools reachable only over the tailnet; test a backup restore monthly.

---

## 0c. Enumerator honesty and data quality

Budget assumption: **50,000 RWF per enumerator per month** (150,000 RWF total for 3) [to confirm] for ~13 visits ≈ 3,800 RWF per visit. Suggested split: **45,000 base + up to 5,000 bonus**, plus a small data bundle, paid by MoMo. Keep demands low; most fraud detection happens in software, invisibly to the enumerator.

### Evidence captured automatically with each submission (Kobo form)
- **GPS** (required) — must fall within ~300 m of the market.
- **Start/end time and device ID** — submission must be inside the AM/PM window; a whole market done in 3 minutes is suspicious.
- **One photo per visit** of a commodity picked at random by the form (the enumerator cannot know which one in advance).
- **Vendor identifier optional**: stall number or section, only for the 2 quotes of the randomly-picked commodity — enough to make back-checks possible without extra work on every item.

GPS, timestamps and device ID are recorded by the phone automatically — **no extra effort** for the enumerator.

### Automatic checks on the server (per submission)
| Check | Flags |
|---|---|
| Location | GPS outside market geofence or missing |
| Timing | outside session window, form filled too fast, visit outside 08:00–11:00 on a collection day |
| Copy-paste | many prices identical to the previous session (real markets move a bit) |
| Two-vendor spread | 2 quotes always identical, or implausibly far apart |
| Digit preference | too many round numbers (all ending in 00) vs. the enumerator's history |
| Outliers | price outside plausible range or a jump vs. last session / other 2 markets (robust z-score) |
| Photo | missing, duplicated (same image hash reused), EXIF time/place mismatch |
| Cross-market | one market drifts away from the other two and from WFP Kigali prices over weeks |

Flagged rows stay in a **review queue** and are not published until accepted.

### Human verification
- **Back-checks:** each week, call or visit **2 random vendors** from that week's submissions and ask the price; compare.
- **Unannounced spot check:** every 2 weeks the owner (or a trusted person) visits one market at random on a collection day and checks ~5 commodities.
- **Rotation:** swap enumerators between markets every 2–3 months; if a market's price level jumps when the person changes, the old data was biased.
- **WhatsApp group** for questions and daily reminders; quick feedback when something is flagged.

### Enumerator scorecard (Metabase, monthly)
Completeness (visits on time), photo compliance, % submissions flagged, back-check match rate, spot-check match rate → score 0–100 → bonus. Two failed back-checks in a month = warning; repeated fabrication = replace.

---

## 1. Decisions so far

| Topic | Decision | Why |
|---|---|---|
| Store | **PostgreSQL only** (no Kafka, Debezium, ClickHouse for now) | ~10–30k rows/day ≈ 11M rows/year — small for Postgres [J]. Every CDC tool needs `wal_level=logical`, slots and WAL monitoring [V]; not worth it yet. |
| Postgres version | **Upgrade 15 → 17, image `timescale/timescaledb-ha:pg17`** | TimescaleDB 2.29 (2026-07) dropped PG15; Toolkit 1.24 was the last for PG15 [V — GitHub releases; re-check before switching]. |
| Real-time analytics | TimescaleDB hypertable + **real-time continuous aggregates** + `pg_cron` derived tables + Python worker | Writes never wait on analytics; reads include rows not yet materialized [V]. |
| Live UI updates | `LISTEN/NOTIFY` (IDs only) → one FastAPI listener → **SSE** → browser refetches | No extra services. NOTIFY payload < 8000 bytes [V]. |
| Public frontend | Custom mobile-first PWA, trilingual (rw/en/fr) | BI tools are heavy, hard to translate, poor on mobile [J]. |
| Internal analysis | Superset or Metabase on Postgres | Analysts + data-quality review [J]. |

Upgrade later only if: >~1B rows or slow multi-analyst ad-hoc queries (ClickHouse, filled by batch `INSERT … SELECT FROM postgresql(...)` [V]); several downstream consumers or thousands of writes/sec (Kafka) [J]. Avoid ClickHouse `MaterializedPostgreSQL` — experimental, no DDL replication [V].

---

## 2. Gaps in the current repo

- `prices` has a `date` only and `UNIQUE(commodity, market, date, source)` → **cannot store two readings (vendors/sessions) for the same day**.
- Commodity and market are free text → no geography, no flows, spelling duplicates.
- No price type (retail / wholesale / farm-gate), unit normalization, availability, origin, enumerator, quality flag.
- No migrations tool (add Alembic).

---

## 3. Target data model (draft)

```
markets(id, name, aliases[], district, province, lat, lon,
        market_type: rural|assembly|wholesale|retail|border, active)
commodities(id, code, name_en, name_rw, name_fr, category, default_unit, cpi_weight)
units(id, code, name_rw, kg_equivalent, commodity_id NULL)   -- local measures: basin, heap, sack…
enumerators(id, name, phone, assigned_market_ids[])

price_observations  -- hypertable on observed_at
  observed_at timestamptz, session AM|PM, market_id, commodity_id,
  price_type retail|wholesale|farmgate, price_rwf, unit_id, price_rwf_per_kg,
  availability 1–5, origin_market_id NULL, origin_district NULL,
  source (enumerator|kobo|paper_ocr|wfp|minagri|…), submission_id, enumerator_id,
  quality: pending|ok|flagged|rejected, quality_reason, photo_url
  UNIQUE(market_id, commodity_id, price_type, observed_at::date, session, source)

external_series(id, code, name, unit, frequency, source_url)   -- brent, diesel_rura, rwf_usd, cpi_food, chirps_<district>…
external_values(series_id, ts, value)                            -- hypertable

trade_flows(origin_market_id, dest_market_id, commodity_id, period, volume_t NULL,
            kind observed|reported|implied)

derived_metrics(commodity_id, market_id NULL, day, median, p10, p90, ma7, ma30,
                pct_1d, pct_7d, pct_30d, n_obs, anomaly_score, anomaly_level)
model_results(run_id, as_of, model, target, payload jsonb)
```

Continuous aggregates: `daily_prices` (median/min/max/n per commodity×market×price_type, `materialized_only=false`), then `weekly_prices` and `monthly_prices` on top of it.

---

## 4. Data collection

**Twice-daily enumerator collection [J — tooling not verified in research]**
- Primary: **KoboToolbox or ODK Central** form (offline, GPS, photo, Kinyarwanda labels). Fields: session, market, commodity, price type, quantity + local unit, price, availability, origin (district/market), photo.
- Push submissions by webhook → FastAPI `/ingest/kobo` → validation → `price_observations`.
- Validation rules: allowed range per commodity, jump vs previous session (z-score/MAD), GPS within market radius, duplicate detection. Flagged rows go to a review queue; they are not published until reviewed.
- Paper fallback: a **fixed-layout printed form** (pre-printed commodity rows, boxes for numbers). Photo → vision model extraction → human review before publishing. Handwritten Kinyarwanda OCR accuracy is **unverified** — pilot before relying on it.
- SMS fallback for enumerators with no data: structured message `BEANS NYABUGOGO R 850 KG`.

**Secondary sources**
- WFP VAM: **Data Bridges API via `data_bridges_knots`** (credentials by request from wfp.vaminfo@wfp.org); HDX CSV as open fallback [V]. Library is GPL/AGPL — run it as an isolated ingestion job [V].
- CHIRPS daily rainfall: free, public domain, ~5.5 km, from 1981, ~2–3 week lag, direct download from UCSB CHC [V]. Aggregate to districts → Season A/B rainfall anomaly.
- Unverified, to confirm: RURA pump prices (monthly), BNR RWF/USD, NISR CPI, Brent, FAO Food Price Index, FEWS NET API, EAGC RATIN, regional prices (Uganda, Tanzania, Kenya KAMIS, Burundi, DRC), MINAGRI e-Soko.

---

## 5. Analytics

| Where | What |
|---|---|
| Continuous aggregates | daily/weekly/monthly median, p10/p90, min/max, count |
| `pg_cron` every 5–15 min | MA7/MA30, % change (1d/7d/30d), cross-market spreads, rolling `corr()`, spike flags → `derived_metrics` → NOTIFY |
| Python worker (nightly) | seasonal decomposition, ALPS-style anomaly levels (Normal/Stress/Alert/Crisis vs seasonal trend), cointegration / price transmission between markets, correlation with fuel/FX/rainfall, forecasts (labelled indicative) → `model_results` |

Supply/demand proxies [J]: availability score from forms, number of markets reporting, origin mix, rainfall anomaly, seasonal calendar, wholesale–retail spread.

---

## 6. Product and screens

Borrow from trading platforms only where it helps; never imply a live market.

- **Home**: last update ("Morning 09:40"), watchlist rows (price, % vs last session and 7 days, 30-day sparkline), top movers (min. observation count), food heatmap/treemap, fuel + FX tiles, anomaly callout, Price of the Day card.
- **Commodity page**: national median line with p10–p90 band across markets (instead of candlesticks), 1W/1M/1Y/5Y, anomaly badge, market table with cheapest + **landed cost** (price + editable transport rate), compare, alert, share, CSV.
- **Market page**: every commodity vs national median, nearest alternatives, rainfall mini-chart.
- **Map / Flows**: price level / % change / anomaly layers; origin→destination arcs to hubs like Nyabugogo; implied flows labelled as inferred.
- **Compare**: overlay or indexed-to-100, spread chart, correlation on weekly returns, macro overlays.
- **Alerts & Basket**: thresholds via SMS / WhatsApp / push; personal basket vs NISR food CPI.
- **Feature phones**: USSD and SMS query in the old e-Soko style ("market + commodity"), WhatsApp daily digest. Only ~38% of Rwandans online, 19% rural [V].
- **Trust**: show n markets reporting, medians, method notes, freshness stamp on every page.

Stack: TradingView Lightweight Charts (Apache-2.0, attribution required), ECharts modular imports (treemap/Sankey), MapLibre GL + deck.gl ArcLayer (lazy-loaded), PWA with offline last-known prices, < 150 KB JS on first load [J target].

---

## 7. Phased rollout

| Phase | Scope | Outcome |
|---|---|---|
| **0 Foundations** | PG17 + TimescaleDB image, Alembic, new schema, reference data (markets with GPS, trilingual commodities, local units), migrate existing rows | Clean base |
| **1 Collection** | Kobo form (rw/en), Kobo API poller, validation + review queue, enumerator onboarding at Nyabugogo/Kimironko/Kabuga, WFP (HDX → Data Bridges), CHIRPS | Reliable twice-daily data from 3 markets |
| **2 Analytics core** | caggs, `pg_cron` metrics, anomaly flags, SSE stream, Superset for internal QA | Live, trustworthy numbers |
| **3 Public MVP** | Home, commodity, market pages, top movers, map; rw/en/fr PWA | Daily-use product |
| **4 Drivers & compare** | fuel, FX, CPI, regional prices; compare/correlate; basket | Explains *why* prices move |
| **5 Sourcing & flows** | landed cost, flow map, origin capture analysis; alerts via SMS/WhatsApp/USSD | "Where to buy" and tracing |
| **6 Forecast & scale** | indicative forecasts; scale to more markets; ClickHouse only if thresholds hit | Prediction |

---

## 8. Main risks

1. **Data quality and enumerator consistency** — biggest risk; needs training, validation, spot checks, payment/incentives.
2. **Local units** (basins, heaps, sacks) — need conversion tables per commodity and market.
3. **Data access** — WFP credentials, NISR/MINAGRI agreements; coordinate with MINAGRI/NISR (government already ran e-Soko).
4. **Kinyarwanda** — native-speaker review of names and UI; OCR of handwriting unproven.
5. **Running costs** — SMS/USSD/WhatsApp fees, hosting.
6. **Research gaps** — collection tools, most external APIs and analytics methods were not verified; confirm in Phase 0–1.

## 9. Open questions for the owner

- Confirm the starter commodity list and the exact variety/grade for each.
- Confirm 50,000 RWF is per enumerator (not total) and the base/bonus split.
- Confirm Tailscale Funnel is available on your Tailscale plan.
- Later: approach MINAGRI / NISR / WFP once the pilot has a few months of clean data.
