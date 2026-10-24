"""create_backend.py --deploy ships the stored replay week (docs/b.md item 3).

models/ is excluded from the rsync (the LightGBM joblibs are big and machine-local), and the deploy used to
scp only lgbm_*.joblib + training.json, and only when at least 3 of them existed. So the replay week
(models/replay_week.parquet) never reached the box and the live Replay tab showed the synthetic fallback.
These tests run the deploy with SSH, scp and the health check stubbed: no network.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_backend.py"
spec = importlib.util.spec_from_file_location("create_backend", SCRIPT)
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

REPLAY = ("replay_week.parquet", "replay_week.json")


def test_the_repo_has_the_replay_week_and_deploy_lists_it():
    _, data = cb.deploy_files(cb.REPO_ROOT / "models")
    assert sorted(p.name for p in data) == sorted(REPLAY)


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """Run deploy() against a fake models/ dir; record every scp'd file and ssh command."""
    calls = {"scp": [], "ssh": []}

    def fake_run(args, **kwargs):
        if args[0] == "scp":
            calls["scp"].extend(Path(a).name for a in args[1:-1] if not a.startswith("-") and "=" not in a)

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(cb, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cb, "rsync_repo", lambda ip, key: None)
    monkeypatch.setattr(cb, "ssh", lambda ip, key, cmd, **kw: calls["ssh"].append(cmd) or "ok\n")
    monkeypatch.setattr(cb.subprocess, "run", fake_run)
    monkeypatch.setattr(cb.httpx, "get", lambda *a, **k: type("R", (), {"text": "ok"})())
    (tmp_path / "models").mkdir()
    (tmp_path / ".env").write_text("X=1\n")
    return tmp_path / "models", calls


def test_replay_week_is_copied_even_without_model_files(stubbed):
    models, calls = stubbed
    for name in REPLAY:
        (models / name).write_bytes(b"x")
    cb.deploy("1.2.3.4", Path("key"), 0.0, enable_poller=True)
    assert set(REPLAY) <= set(calls["scp"])
    units = next(c for c in calls["ssh"] if c.startswith("systemctl enable"))
    assert "tempo-decider" not in units  # no models here: the decider is left as it is on the box


def test_models_and_replay_week_are_copied_together(stubbed):
    models, calls = stubbed
    for name in (*REPLAY, "training.json", "lgbm_p10.joblib", "lgbm_p50.joblib", "lgbm_p90.joblib"):
        (models / name).write_bytes(b"x")
    cb.deploy("1.2.3.4", Path("key"), 0.0, enable_poller=True)
    assert {*REPLAY, "training.json", "lgbm_p50.joblib"} <= set(calls["scp"])
    units = next(c for c in calls["ssh"] if c.startswith("systemctl enable"))
    assert "tempo-decider" in units
