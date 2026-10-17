-- Core schema for the price monitoring platform (shared by production and demo).
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS serving;
CREATE SCHEMA IF NOT EXISTS ops;

-- Operational settings, e.g. pilot_window = ["2026-08-31", "2026-09-19"] (daily collection allowed)
CREATE TABLE ops.settings (key text PRIMARY KEY, value jsonb NOT NULL);

-- ── Reference data ────────────────────────────────────────────────────────────
CREATE TABLE ref.markets (
    id        smallint PRIMARY KEY,
    code      text UNIQUE NOT NULL,          -- NYB, KIM, KAB
    name      text NOT NULL,
    district  text NOT NULL,
    lat       double precision NOT NULL,
    lon       double precision NOT NULL
);

CREATE TABLE ref.commodities (
    id          smallint PRIMARY KEY,
    code        text UNIQUE NOT NULL,
    name_en     text NOT NULL,
    name_rw     text NOT NULL,              -- draft names, to be reviewed by a native speaker
    name_fr     text NOT NULL,
    category    text NOT NULL,
    std_unit    text NOT NULL,              -- unit prices are normalised to (kg, litre, egg, head)
    price_unit  text NOT NULL,              -- unit vendors quote in
    std_per_price_unit numeric NOT NULL,    -- e.g. 1 basin of tomatoes = 4.5 kg
    perishable  boolean NOT NULL DEFAULT false
);

CREATE TABLE ref.enumerators (
    id        smallint PRIMARY KEY,
    code      text UNIQUE NOT NULL,
    market_id smallint NOT NULL REFERENCES ref.markets(id)
);

CREATE TABLE ref.vendors (
    id           serial PRIMARY KEY,
    code         text UNIQUE NOT NULL,      -- stall code, e.g. KIM-S02-004; no names stored
    market_id    smallint NOT NULL REFERENCES ref.markets(id),
    commodity_id smallint NOT NULL REFERENCES ref.commodities(id),
    panel_rank   smallint NOT NULL          -- 1..5; routine collection uses ranks 1-2
);

-- ── Raw layer: submissions exactly as received ────────────────────────────────
CREATE TABLE raw.kobo_submissions (
    kobo_id       bigint PRIMARY KEY,
    uuid          text UNIQUE NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    source        text NOT NULL CHECK (source IN ('webhook', 'poll')),
    payload       jsonb NOT NULL,
    processed_at  timestamptz,
    process_error text
);
CREATE INDEX raw_unprocessed_idx ON raw.kobo_submissions (kobo_id) WHERE processed_at IS NULL;

-- ── Core layer: cleaned observations ──────────────────────────────────────────
CREATE TABLE core.visits (
    id            bigserial PRIMARY KEY,
    kobo_uuid     text UNIQUE NOT NULL REFERENCES raw.kobo_submissions(uuid),
    market_id     smallint NOT NULL REFERENCES ref.markets(id),
    enumerator_id smallint NOT NULL REFERENCES ref.enumerators(id),
    visit_date    date NOT NULL,
    session       text NOT NULL DEFAULT 'AM' CHECK (session IN ('AM', 'PM')),
    started_at    timestamptz NOT NULL,
    ended_at      timestamptz NOT NULL,
    duration_s    integer NOT NULL,
    lat           double precision,
    lon           double precision,
    dist_m        double precision,
    device_id     text,
    photo_commodity_id smallint REFERENCES ref.commodities(id),
    photo_hash    text,
    status        text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'held', 'rejected')),
    reviewed_at   timestamptz
);
CREATE INDEX visits_market_date_idx ON core.visits (market_id, visit_date);

CREATE TABLE core.price_quotes (
    observed_at   timestamptz NOT NULL,
    visit_id      bigint NOT NULL,
    market_id     smallint NOT NULL,
    commodity_id  smallint NOT NULL,
    vendor_id     integer NOT NULL DEFAULT 0, -- 0 = commodity-level row (e.g. not available)
    available     boolean NOT NULL,
    price_rwf     integer,                  -- as quoted, per price_unit
    price_std     numeric,                  -- RWF per std_unit
    status        text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'held', 'rejected')),
    PRIMARY KEY (observed_at, visit_id, commodity_id, vendor_id)
);
SELECT create_hypertable('core.price_quotes', 'observed_at', chunk_time_interval => INTERVAL '1 month');
CREATE INDEX quotes_lookup_idx ON core.price_quotes (commodity_id, market_id, observed_at DESC);
CREATE INDEX quotes_vendor_idx ON core.price_quotes (vendor_id, observed_at DESC);

CREATE TABLE core.qc_flags (
    id         bigserial PRIMARY KEY,
    visit_id   bigint NOT NULL REFERENCES core.visits(id),
    commodity_id smallint,
    vendor_id  integer,
    rule       text NOT NULL,
    severity   text NOT NULL CHECK (severity IN ('hold', 'flag')),
    detail     jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX qc_flags_visit_idx ON core.qc_flags (visit_id);

CREATE TABLE core.external_series (
    code      text PRIMARY KEY,
    name      text NOT NULL,
    unit      text NOT NULL,
    frequency text NOT NULL
);
CREATE TABLE core.external_values (
    series_code text NOT NULL REFERENCES core.external_series(code),
    ts          date NOT NULL,
    value       double precision NOT NULL,
    PRIMARY KEY (series_code, ts)
);

-- ── Serving layer ─────────────────────────────────────────────────────────────
-- Daily price per commodity × market: geometric mean of accepted vendor quotes.
-- Real-time: rows not yet materialised are aggregated at query time.
CREATE MATERIALIZED VIEW serving.daily_prices
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket(INTERVAL '1 day', observed_at) AS day,
       commodity_id,
       market_id,
       exp(avg(ln(price_std)))  AS price,
       min(price_std)           AS price_min,
       max(price_std)           AS price_max,
       count(*)                 AS n_quotes
FROM core.price_quotes
WHERE status = 'ok' AND available AND price_std > 0
GROUP BY 1, 2, 3
WITH NO DATA;

SELECT add_continuous_aggregate_policy('serving.daily_prices',
    start_offset => INTERVAL '120 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '5 minutes');

-- Weekly metrics written by the analytics job (matched-sample Jevons changes, anomaly flags).
CREATE TABLE serving.weekly_metrics (
    week          date NOT NULL,
    commodity_id  smallint NOT NULL,
    market_id     smallint NOT NULL,            -- 0 = national (3-market) figure
    price         double precision NOT NULL,
    pct_wow       double precision,
    pct_4w        double precision,
    n_quotes      integer NOT NULL,
    n_vendors     integer NOT NULL,
    z_change      double precision,           -- robust z of the 1-week change
    z_level       double precision,           -- ALPS-style seasonal residual z (drives `anomaly`)
    anomaly       text NOT NULL DEFAULT 'normal' CHECK (anomaly IN ('normal', 'watch', 'unusual', 'insufficient')),
    computed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (week, commodity_id, market_id)
);

-- Availability per visit (published "not available" instead of a carried-forward price).
CREATE VIEW serving.availability AS
SELECT v.visit_date, q.market_id, q.commodity_id, bool_or(q.available) AS available
FROM core.price_quotes q JOIN core.visits v ON v.id = q.visit_id
WHERE q.status = 'ok'
GROUP BY 1, 2, 3;
