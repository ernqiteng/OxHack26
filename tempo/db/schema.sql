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

-- TODO (Girik, Phase 1): continuous aggregates prices_hh -> prices_daily -> prices_weekly
-- TODO (Girik, Phase 3): compression policy on grid_raw chunks older than 7 days

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
