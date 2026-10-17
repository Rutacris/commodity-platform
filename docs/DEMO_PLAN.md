# End-to-End Demo with Synthetic Data — Plan

> **Status:** the 2-week version is built — see [`demo/README.md`](../demo/README.md) for how to run it and the results.
> Differences from this plan: no Metabase yet (review queue and scorecard are in the dashboard), no MinIO backup drill,
> photos are represented by a hash, and the stack runs on TimescaleDB's own scheduler/real-time aggregates rather than pg_cron.

Goal: run the **whole architecture** from `PLATFORM_PLAN.md` on one machine, with no real enumerators, no real Kobo account and no internet dependency, and show that every stage works: collection → ingest → QC → storage → analytics → live UI → resilience.

Principle: **only the data is fake.** The ingest worker, database, QC rules, analytics jobs, API and frontend are the real code, unchanged. A mock Kobo server stands in for KoboToolbox, so switching to production means changing one URL and one token.

Second principle: **we know the truth.** The generator stores the true prices, the effects it injected and which enumerator misbehaved. The demo then proves the platform *recovers* that truth — a stronger demonstration than nice charts.

Labels: **[J]** judgement; price levels in this demo are illustrative, not real Kigali prices.

---

## 1. What runs

```
 ┌───────────────── docker compose --profile demo up ──────────────────┐
 │                                                                     │
 │  synth-generator ──writes──► truth.* tables (ground truth, hidden)  │
 │        │                                                            │
 │        │ produces Kobo-shaped submissions (JSON + photos)           │
 │        ▼                                                            │
 │  mock-kobo (FastAPI)                                                │
 │    GET /api/v2/assets/{uid}/data/?query=…   ◄── poller (every 30 s) │
 │    POST webhook to ingest  ──────────────────► /ingest/kobo         │
 │        (can be told to "fail" to test the poller safety net)        │
 │                                                                     │
 │  ingest worker (real code) → raw.kobo_submissions → QC → core.*     │
 │  Postgres 17 + TimescaleDB (caggs, pg_cron metrics)                 │
 │  analytics worker (real code): STL, anomaly, correlations           │
 │  FastAPI REST + SSE  ─►  frontend PWA (SYNTHETIC banner)            │
 │  Metabase (QC review queue, enumerator scorecard)                   │
 │  backup job (pg_dump → local MinIO bucket instead of B2/R2)         │
 │  healthcheck mock (instead of Healthchecks.io)                      │
 └─────────────────────────────────────────────────────────────────────┘
```

Swaps for the demo only: mock-kobo ↔ KoboToolbox, MinIO ↔ Backblaze/R2, local healthcheck ↔ Healthchecks.io. Tailscale Funnel optional (to show the demo on a phone).

---

## 2. Synthetic data model

### 2.1 Reference data (same tables as production)
3 markets (Nyabugogo, Kimironko, Kabuga) with approximate GPS, 24 commodities from the spec sheets, local units with weights, 3 synthetic enumerators, a fixed panel of 5 vendors per commodity per market (stall codes only).

### 2.2 True price process (per commodity c, market m, day t, vendor v, session s) [J]
```
log P_true = base_c                        # illustrative level, e.g. beans 1,000 RWF/kg
           + market_m                      # Nyabugogo −5%, Kabuga −3%, Kimironko +7%
           + season_c(t)                   # harvest dips for maize/beans after Season A and B; perishables more volatile
           + trend(t)                      # slow inflation ~0.5%/month
           + β_c · fuel(t − lag_c)         # pass-through from synthetic diesel price
           + x_c,m(t)                      # AR(1) day shock, persistence 0.8
           + vendor_v                      # persistent vendor level, sd 4–8%
           + session_s                     # PM −2% for perishables
           + ε                             # vendor×day noise, sd 2–4%
```
Parameters are written to `truth.params` so the pilot-analysis notebook can check its estimates against them.

### 2.3 Injected events (scripted, dated, stored in `truth.events`)
| Event | Effect | What the demo should show |
|---|---|---|
| Tomato shortage | +45% over 2 weeks, all markets, then decays | anomaly badge, top mover, alert fires |
| Fuel price hike | synthetic diesel +12% on a date | maize flour, rice, cooking oil rise with lag; correlation view |
| Nyabugogo supply glut (Irish potatoes) | −20% at Nyabugogo only | "cheapest market" / landed-cost view changes; spread chart |
| Beans harvest | gradual −15% after Season B | seasonality decomposition |
| Commodity unavailable | eggs missing at Kabuga 3 visits | "not available" shown, no carried-forward price |

### 2.4 Enumerator behaviour (measurement layer)
| Enumerator | Market | Behaviour injected |
|---|---|---|
| E1 | Kimironko | Honest, occasional typo (extra zero) |
| E2 | Kabuga | **Lazy**: from week 6 copies ~70% of previous prices; rounds to 00 |
| E3 | Nyabugogo | **Fabricator** on 4 dates: submits from home (GPS 4 km away), form done in 3 min, reused photo |

Plus realistic noise: 5% missed visits, late make-up visits, photos (generated placeholder images with varying hashes, one deliberately duplicated).

### 2.5 External drivers (synthetic, same tables as real sources)
Diesel price (monthly steps, RURA-style), RWF/USD (slow drift + noise), daily rainfall per district (seasonal pattern, one dry-spell anomaly), "WFP-like" monthly Kigali benchmark (true price + offset + noise) to exercise the external-validation comparison.

### 2.6 Time
- **Backfill:** 2 years of history (Mon/Wed/Fri routine design, plus a 3-week dense "pilot" block) generated in under a minute, delivered through mock-kobo in pages, so ingest is exercised at volume.
- **Live mode:** a compressed clock — one collection day every 2 minutes (configurable). Each market's submission arrives at a slightly different moment, so viewers watch the UI update.

Deterministic: one `SEED` value reproduces the same dataset; the demo is identical every run.

---

## 3. Demo script (≈ 15 minutes)

| # | Show | Proves |
|---|---|---|
| 1 | Architecture diagram + `docker compose ps` | one box, all services up |
| 2 | Trigger live mode; a submission appears in mock-kobo → `raw` → `core` → home screen updates within seconds (SSE) | ingest + real-time path |
| 3 | Home: watchlist, top movers, food heatmap, "as of" stamp, SYNTHETIC banner | product surface |
| 4 | Tomatoes page during the shortage: range band, anomaly badge, alert sent (logged to console / mock SMS) | analytics + alerts |
| 5 | Irish potatoes: cheapest market with landed cost; spread Nyabugogo vs Kimironko | sourcing feature |
| 6 | Compare: maize flour vs diesel, indexed to 100; correlation with lag | external drivers |
| 7 | Metabase review queue: E2's copy-paste flags, E3's off-site / too-fast / duplicate-photo holds; scorecard ranks E1 > E2 > E3 | data-quality system |
| 8 | Truth report: QC precision/recall vs injected misconduct; variance components and fuel pass-through recovered vs `truth.params`; thinning test on the dense block | the method works on known truth |
| 9 | Resilience: stop the API container, set mock-kobo webhook to fail, let 3 submissions arrive; restart → poller backfills, no duplicates | no data loss |
| 10 | Backup: run backup job, drop the DB, restore from MinIO, UI back | recoverability |

---

## 4. Acceptance criteria (the demo "passes" when) [J]
1. `docker compose --profile demo up` from a clean checkout reaches healthy state in < 10 min, no internet needed after images are pulled.
2. End-to-end latency, submission in mock-kobo → visible in UI: **< 10 s** (webhook path), **< 60 s** (poll-only path).
3. Zero lost or duplicated submissions across the resilience test (counts in `raw` = counts generated).
4. QC catches **≥ 90%** of injected misconduct with **≤ 10%** false flags on honest data.
5. Recovered parameters within tolerance of truth: vendor/day/residual variance within ±30%, fuel pass-through sign correct and within ±50%, every injected event flagged within one week.
6. Published series never show a price for "not available" visits.
7. Restore from backup reproduces identical row counts.
8. Every page shows the SYNTHETIC banner; demo data lives in a separate database (`commodities_demo`) and cannot be written by the production pipeline.

---

## 5. Repository layout (new parts)
```
demo/
  synth/                 generator: params.yaml, price_process.py, behaviours.py, events.py, external.py
  mock_kobo/             FastAPI app mimicking Kobo API v2 data endpoints + webhook sender
  notebooks/             pilot_analysis.ipynb, truth_report.ipynb
  README.md              how to run the demo and the script above
docker-compose.demo.yml  profile "demo": mock-kobo, synth, minio, healthcheck-mock
backend/ ... (real code: ingest, QC, API, SSE — shared with production)
db/migrations/           schema used by both demo and production
```

---

## 6. Build order and rough effort (one developer) [J]

| Step | Deliverable | Effort |
|---|---|---|
| 1 | Phase 0 of the platform: Postgres 17 + TimescaleDB, migrations, reference data | 2–3 days |
| 2 | Synthetic generator (true process, events, behaviours, external series, truth tables) | 3 days |
| 3 | Mock Kobo (data API with paging and `_id` filter, webhook, failure switch) | 1–2 days |
| 4 | Ingest worker (poll + webhook, idempotent) and QC rules | 3 days |
| 5 | Continuous aggregates, pg_cron metrics, anomaly flags, SSE | 2–3 days |
| 6 | API + minimal PWA (home, commodity, market, compare) | 4–5 days |
| 7 | Metabase dashboards (review queue, scorecard) | 1 day |
| 8 | Notebooks: pilot analysis + truth report | 2 days |
| 9 | Backup/restore, healthcheck, resilience script, demo README | 1–2 days |
| | **Total** | **≈ 4 weeks** |

A thinner first cut (steps 1–5 + a single dashboard page + truth report) is possible in **≈ 2 weeks** and already shows the full data path.

---

## 7. What the demo does not prove
- Real price levels, real seasonality or real fuel pass-through (all synthetic).
- How real enumerators behave, or how much the routine design costs in practice.
- Kobo-specific details (exact JSON field names, audit log format, rate limits) beyond what the mock imitates — validate against a free Kobo test project before going live.
- Load beyond one machine (not needed at pilot scale).

The pilot in `PILOT_METHODOLOGY.md` remains the real test; the demo proves the system is ready to receive it.
