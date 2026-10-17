# Rwanda Commodity Price Intelligence Platform — Plan

Status: draft plan, no code changed yet. Date: 2026-10-17.

Evidence labels: **[V]** confirmed by a source during research, **[J]** judgement / not verified.

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

- `prices` has a `date` only and `UNIQUE(commodity, market, date, source)` → **cannot store AM and PM readings**.
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
| **1 Collection** | Kobo/ODK form, webhook ingest, validation + review queue, WFP (HDX → Data Bridges), CHIRPS; pilot 5–10 markets | Reliable twice-daily data |
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

- Pilot markets and commodities (how many, which)?
- Retail only, or also wholesale and farm-gate?
- Who are enumerators (own staff, cooperatives, market committees)?
- Partnership with MINAGRI / NISR / WFP?
- Hosting: one VPS, or cloud?
