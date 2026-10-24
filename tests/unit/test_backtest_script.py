"""scripts/backtest.py end to end on the synthetic market (no database)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backtest.py"


@pytest.fixture(scope="module")
def backtest():
    spec = importlib.util.spec_from_file_location("backtest_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_run_prints_honesty_table(backtest, capsys):
    results = backtest.main(["--source", "synthetic", "--run-id", "t"])
    out = capsys.readouterr().out
    assert "4 test weeks" in out and "Honesty table" in out and "Perfect knowledge of the future" in out
    assert "WARNING" not in out
    assert set(results.strategy) == {"simple_rule", "persistence_greedy", "tempo", "tempo_lp", "perfect"}
    assert "Tempo (LightGBM forecast + LP optimiser)" in out
    assert (results.run_id == "t").all()


def test_no_tempo_skips_training(backtest):
    results = backtest.main(["--source", "synthetic", "--run-id", "t", "--no-tempo"])
    assert set(results.strategy) == {"simple_rule", "persistence_greedy", "perfect"}


def test_write_refused_for_synthetic(backtest):
    with pytest.raises(SystemExit, match="only works with real data"):
        backtest.main(["--source", "synthetic", "--write"])
