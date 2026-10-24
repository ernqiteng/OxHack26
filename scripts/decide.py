#!/usr/bin/env python3
"""Run the live decision engine: one 48-period batch now, or one every half hour forever.

    .venv/bin/python scripts/decide.py --once            # one batch at now, print the decision_id
    .venv/bin/python scripts/decide.py                   # loop: a batch just after every half hour
    .venv/bin/python scripts/decide.py --optimiser lp    # LP instead of greedy
    .venv/bin/python scripts/decide.py --at 2026-10-24T12:00:00Z --run-id rehearsal   # a past batch

Owner: Ernqi (Part A, docs/a.md item 4), written by Ayo. Runs on the backend box under
deploy/systemd/tempo-decider.service once models/ holds a trained model (scripts/train.py).

Only this script writes run_id 'live'. Each cycle waits until a minute past the half hour so the newest
settlement period's price (available period end + MID delay) can be in the features, then calls
run_decision(now). A failed cycle logs and waits for the next one; it never kills the loop.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tempo.config import REPO_ROOT, settings  # noqa: E402

log = logging.getLogger("decide")
MODELS = REPO_ROOT / "models"


def load_parts(models_dir: Path, optimiser_name: str):
    from tempo.forecast.lgbm import LightGBMQuantileForecaster
    from tempo.optimise.greedy import GreedyOptimiser
    from tempo.optimise.lp import LPOptimiser

    forecaster = LightGBMQuantileForecaster.load(models_dir)
    optimiser = LPOptimiser() if optimiser_name == "lp" else GreedyOptimiser()
    return forecaster, optimiser


def next_slot(now: datetime, offset_min: int = 1) -> datetime:
    """The next (half hour + offset) strictly after now."""
    base = now.replace(second=0, microsecond=0)
    base = base.replace(minute=0 if base.minute < 30 else 30)
    slot = base + timedelta(minutes=offset_min)
    while slot <= now:
        slot += timedelta(minutes=30)
    return slot


def one_cycle(url: str, forecaster, optimiser, at: datetime, run_id: str) -> int:
    import psycopg

    from tempo.decide.engine import run_decision

    with psycopg.connect(url, connect_timeout=15, autocommit=True) as conn:
        t0 = time.monotonic()
        did = run_decision(conn, at, forecaster, optimiser, run_id=run_id)
        summary = conn.execute(
            "SELECT count(*) FILTER (WHERE action = 'charge'), count(*) FILTER (WHERE action = 'discharge'), "
            "count(*) FILTER (WHERE action = 'hold') FROM decisions WHERE decided_at = %s AND run_id = %s",
            (at, run_id),
        ).fetchone()
    log.info(
        "batch at %s (%s): decision_id %d, %d charge / %d discharge / %d hold, %.1fs",
        at.strftime("%Y-%m-%d %H:%M"),
        run_id,
        did,
        *summary,
        time.monotonic() - t0,
    )
    return did


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--at", help="decision time, ISO 8601 with timezone (implies --once)")
    ap.add_argument("--run-id", default="live")
    ap.add_argument("--optimiser", choices=["greedy", "lp"], default="greedy")
    ap.add_argument("--models", type=Path, default=MODELS)
    ap.add_argument("--db", default=None, help="DSN; default TEMPO_DATABASE_URL")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    url = args.db or settings().database_url
    if not url:
        print("no database: set TEMPO_DATABASE_URL")
        return 2
    if not (args.models / "lgbm_p50.joblib").exists():
        print(f"no model in {args.models}: run scripts/train.py first")
        return 2
    forecaster, optimiser = load_parts(args.models, args.optimiser)
    log.info("model from %s, optimiser %s, run_id %s", args.models, args.optimiser, args.run_id)

    if args.at or args.once:
        at = datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else datetime.now(tz=UTC)
        if at.tzinfo is None:
            print("--at needs a timezone, e.g. 2026-10-24T12:00:00Z")
            return 2
        did = one_cycle(url, forecaster, optimiser, at, args.run_id)
        print(f"decision_id {did}")
        return 0

    while True:
        slot = next_slot(datetime.now(tz=UTC))
        wait = (slot - datetime.now(tz=UTC)).total_seconds()
        log.info("next batch at %s UTC (in %.0fs)", slot.strftime("%H:%M"), wait)
        time.sleep(max(wait, 0))
        try:
            one_cycle(url, forecaster, optimiser, datetime.now(tz=UTC), args.run_id)
        except Exception as exc:  # noqa: BLE001 - log and keep the loop alive
            log.exception("cycle failed: %s", exc)
            time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
