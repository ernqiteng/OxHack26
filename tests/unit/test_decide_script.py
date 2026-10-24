"""scripts/decide.py: cycle timing and argument guards. No DB."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "decide_script", Path(__file__).resolve().parents[2] / "scripts" / "decide.py"
)
decide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decide)


@pytest.mark.parametrize(
    "now, expected",
    [
        ("12:00:30", "12:01"),
        ("12:01:00", "12:31"),
        ("12:29:59", "12:31"),
        ("12:31:00", "13:01"),
        ("12:59:00", "13:01"),
    ],
)
def test_next_slot_is_a_minute_past_the_next_half_hour(now, expected):
    t = datetime.strptime(f"2026-10-24 {now}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    slot = decide.next_slot(t)
    assert slot.strftime("%H:%M") == expected and slot > t


def test_missing_model_is_a_clear_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMPO_DATABASE_URL", "postgres://x:y@localhost:1/db")
    from tempo.config import settings

    settings.cache_clear()
    assert decide.main(["--once", "--models", str(tmp_path)]) == 2
    settings.cache_clear()
