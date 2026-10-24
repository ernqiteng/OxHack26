"""backtest_results contract (docs/plan.md 2.1): Ernqi writes it, Ayo's honesty panel reads it.

Checks run_all's rows against the live schema in tempo/db/schema.sql, and the <= 100% rule:
no strategy may beat perfect foresight, which on real data would mean a lookahead leak.
"""

import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tempo.backtest.walkforward import make_windows, prices_hh_from_grid_raw, run_all
from tests.fixtures.synthetic import make_synthetic_market

SCHEMA = Path(__file__).resolve().parents[2] / "tempo" / "db" / "schema.sql"


def schema_columns(table: str) -> dict[str, str]:
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA.read_text(), re.S).group(1)
    cols = {}
    for line in body.splitlines():
        m = re.match(r"\s*(\w+)\s+(\w+(?: precision)?)", line)
        if m and m.group(1).upper() != "PRIMARY":
            cols[m.group(1)] = m.group(2)
    return cols


@pytest.fixture(scope="module")
def results():
    grid = make_synthetic_market()
    start = pd.Timestamp("2026-01-05", tz="UTC")
    return run_all(prices_hh_from_grid_raw(grid), grid, make_windows(start, start + pd.Timedelta(days=60)), run_id="contract")


def test_columns_match_schema(results):
    assert list(results.columns) == list(schema_columns("backtest_results"))


def test_types_match_schema(results):
    types = schema_columns("backtest_results")
    for col, sql_type in types.items():
        sample = results[col].iloc[0]
        if sql_type == "text":
            assert isinstance(sample, str) or (col == "regime" and sample is None)
        elif sql_type == "date":
            assert type(sample) is date
        elif sql_type == "double precision":
            assert isinstance(sample, float)


def test_not_null_columns_filled(results):
    for col in ("run_id", "week_start", "strategy", "pnl_gbp", "perfect_pnl_gbp", "pct_of_perfect"):
        assert results[col].notna().all()


def test_primary_key_unique(results):
    assert not results.duplicated(["run_id", "week_start", "strategy"]).any()


def test_never_above_100_pct(results):
    assert (results.pct_of_perfect <= 100.0).all()  # exact: no float slack, the dashboard checks this too
    assert (results[results.strategy == "perfect"].pct_of_perfect == 100.0).all()
