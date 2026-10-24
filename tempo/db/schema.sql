-- Tempo database schema. Owner: Girik. Contract frozen at Gate 0 (docs/plan.md section 2.1).
-- Apply with: psql "$TEMPO_DATABASE_URL" -f tempo/db/schema.sql   (or scripts/dev_db.sh for local Docker)
-- All timestamps are UTC. Every hypertable is partitioned on its first column.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Raw market data, long format, one row per (period, publication, dataset, series)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grid_raw (
  start_time        timestamptz NOT NULL,
  available_at      timestamptz NOT NULL,
  dataset           text        NOT NULL,
  series            text        NOT NULL DEFAULT '',
  value             double precision NOT NULL,
  settlement_date   date,
  settlement_period smallint,
  PRIMARY KEY (start_time, available_at, dataset, series)
);
SELECT create_hypertable('grid_raw', 'start_time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS grid_raw_dataset_series_idx ON grid_raw (dataset, series, start_time DESC);
CREATE INDEX IF NOT EXISTS grid_raw_available_at_idx    ON grid_raw (available_at DESC);

-- ---------------------------------------------------------------------------
-- Hierarchical continuous aggregates: prices_hh -> prices_daily -> prices_weekly
-- WITH NO DATA so the file can run inside a transaction (and on Tiger); refresh policies fill them.
-- materialized_only = false: real-time aggregation, so the live chart includes rows newer than the last refresh.
-- MID volume is stored as its own grid_raw row with series 'APXMIDP:volume'.
-- Daily/weekly buckets are UK settlement days (Europe/London), so clock-change days are 46/50 periods.
-- These aggregates are keyed on start_time and carry no available_at; point-in-time guards live in
-- tempo/features/build.py.
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS prices_hh
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('30 minutes', start_time)                  AS bucket,
       avg(value) FILTER (WHERE series = 'APXMIDP')           AS price,
       sum(value) FILTER (WHERE series = 'APXMIDP:volume')    AS volume
FROM grid_raw
WHERE dataset = 'MID' AND series IN ('APXMIDP', 'APXMIDP:volume')
GROUP BY 1
WITH NO DATA;

-- n, sum_price, sum_sq let prices_weekly compute an exact stddev over half-hours.
CREATE MATERIALIZED VIEW IF NOT EXISTS prices_daily
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 day', bucket, 'Europe/London') AS bucket,
       avg(price)              AS mean,
       min(price)              AS min,
       max(price)              AS max,
       max(price) - min(price) AS spread,
       count(price)            AS n,
       sum(price)              AS sum_price,
       sum(price * price)      AS sum_sq
FROM prices_hh
GROUP BY 1
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS prices_weekly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 week', bucket, 'Europe/London') AS bucket,
       sum(sum_price) / NULLIF(sum(n), 0) AS mean,
       sqrt(greatest((sum(sum_sq) - sum(sum_price) * sum(sum_price) / NULLIF(sum(n), 0))
                     / NULLIF(sum(n) - 1, 0), 0)) AS stddev,
       avg(spread) AS spread_mean
FROM prices_daily
GROUP BY 1
WITH NO DATA;

SELECT add_continuous_aggregate_policy('prices_hh',
  start_offset => INTERVAL '3 days', end_offset => INTERVAL '30 minutes',
  schedule_interval => INTERVAL '5 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('prices_daily',
  start_offset => INTERVAL '4 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '30 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('prices_weekly',
  start_offset => INTERVAL '3 weeks', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);

-- Columnstore compression on grid_raw, enabled BEFORE the backfill (moved from Phase 3): uncompressed,
-- 2 years is ~1.2 GB at ~350 B/row, compressed ~120-250 MB, and the Tiger free service has ~390 MiB free.
-- segmentby dataset,series: each series compresses as its own run; a backfill of a new dataset into an
-- already-compressed chunk touches no existing segment. orderby start_time,available_at matches the PK.
ALTER TABLE grid_raw SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'dataset, series',
  timescaledb.compress_orderby   = 'start_time, available_at'
);
SELECT add_compression_policy('grid_raw', INTERVAL '7 days', if_not_exists => TRUE);

-- Backfill bookkeeping: one row per fetched window, written in the same transaction as its upsert.
-- Resume checks this table, never grid_raw: inferring coverage from rows is wrong for spill-over,
-- sparse datasets and short windows (the first 2-year run silently loaded half of MID that way).
CREATE TABLE IF NOT EXISTS ingest_log (
  dataset      text        NOT NULL,
  window_start timestamptz NOT NULL,
  window_end   timestamptz NOT NULL,
  rows         integer     NOT NULL,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (dataset, window_start, window_end)
);

-- ---------------------------------------------------------------------------
-- Forecasts and decisions
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
  forecast_id bigserial,
  decided_at  timestamptz NOT NULL,
  target_time timestamptz NOT NULL,
  p10 double precision,
  p50 double precision,
  p90 double precision,
  model text,
  run_id text NOT NULL DEFAULT 'live',
  PRIMARY KEY (decided_at, forecast_id)
);
SELECT create_hypertable('forecasts', 'decided_at', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id     bigserial,
  decided_at      timestamptz NOT NULL,
  target_time     timestamptz NOT NULL,
  action          text NOT NULL CHECK (action IN ('charge', 'discharge', 'hold')),
  mw              double precision NOT NULL DEFAULT 0,
  reason          text,
  expected_spread double precision,
  forecast_id     bigint,
  run_id          text NOT NULL DEFAULT 'live',
  PRIMARY KEY (decided_at, decision_id)
);
SELECT create_hypertable('decisions', 'decided_at', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS decisions_run_target_idx ON decisions (run_id, target_time);

CREATE TABLE IF NOT EXISTS battery_state (
  ts          timestamptz NOT NULL,
  soc_mwh     double precision NOT NULL,
  cum_pnl_gbp double precision NOT NULL,
  run_id      text NOT NULL,
  PRIMARY KEY (ts, run_id)
);
SELECT create_hypertable('battery_state', 'ts', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Timing audit and backtest output
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audits (
  audit_id        bigserial,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  decision_id     bigint NOT NULL,
  shift           smallint NOT NULL CHECK (shift BETWEEN -2 AND 2),
  pnl_gbp         double precision,
  pnl_delta_gbp   double precision,
  mode            text NOT NULL CHECK (mode IN ('inprocess', 'fork')),
  fork_service_id text,
  worker_id       text,
  PRIMARY KEY (started_at, audit_id)
);
SELECT create_hypertable('audits', 'started_at', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS backtest_results (
  run_id          text NOT NULL,
  week_start      date NOT NULL,
  strategy        text NOT NULL,
  pnl_gbp         double precision NOT NULL,
  perfect_pnl_gbp double precision NOT NULL,
  pct_of_perfect  double precision NOT NULL,
  regime          text,
  PRIMARY KEY (run_id, week_start, strategy)
);
