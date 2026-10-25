"""create_backend.py --deploy ships the stored replay week (docs/b.md item 3).

models/ is excluded from the rsync (the LightGBM joblibs are big and machine-local), and the deploy used to
scp only lgbm_*.joblib + training.json, and only when at least 3 of them existed. So the replay week
(models/replay_week.parquet) never reached the box and the live Replay tab showed the synthetic fallback.
These tests run the real deploy() with SSH, scp and the health check stubbed: no network.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "create_backend.py"
spec = importlib.util.spec_from_file_location("create_backend", SCRIPT)
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

REPLAY = ("replay_week.parquet", "replay_week.json")


def test_the_repo_has_the_replay_week():
    models = Path(__file__).resolve().parents[2] / "models"
    assert all((models / name).exists() for name in REPLAY)


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

    # Answer every health check at once: Streamlit wants the text "ok", the API a json source, the sites html.
    def fake_get(url, **kwargs):
        text = "ok" if url.endswith("/_stcore/health") else "<html>"
        return type("R", (), {"text": text, "status_code": 200, "json": lambda self: {"source": "tiger"}})()

    monkeypatch.setattr(cb.httpx, "get", fake_get)
    monkeypatch.setattr(
        cb, "rsync_dir", lambda src, ip, key, dest: calls.setdefault("sites", []).append(dest)
    )
    (tmp_path / "models").mkdir()
    (tmp_path / ".env").write_text("X=1\n")
    return tmp_path / "models", calls


def test_replay_week_is_copied_even_without_model_files(stubbed):
    """The laptop that deploys usually has no joblibs (they live where the model was trained)."""
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


def test_sites_are_built_here_and_copied_to_var_www(stubbed, monkeypatch, tmp_path):
    """The box has no Node: the two websites are exported on the laptop and mirrored to nginx's roots."""
    _, calls = stubbed
    built = [
        (tmp_path / "presentation" / "out", "/var/www/tempo/presentation/"),
        (tmp_path / "pitch" / "out", "/var/www/tempo/app/"),
    ]
    monkeypatch.setattr(cb, "build_sites", lambda t0: built)
    cb.deploy("1.2.3.4", Path("key"), 0.0, enable_poller=True, sites=True)
    assert calls["sites"] == [dest for _, dest in built]
    units = next(c for c in calls["ssh"] if c.startswith("systemctl enable"))
    assert "tempo-api" in units and units.endswith("nginx")
    assert any("chown -R www-data" in c for c in calls["ssh"])


def test_default_deploy_touches_no_sites(stubbed):
    """Without sites=True (and in the older callers) nothing is built and /var/www is left alone."""
    _, calls = stubbed
    cb.deploy("1.2.3.4", Path("key"), 0.0, enable_poller=False)
    assert "sites" not in calls
    assert "tempo-api" in next(c for c in calls["ssh"] if c.startswith("systemctl enable"))
