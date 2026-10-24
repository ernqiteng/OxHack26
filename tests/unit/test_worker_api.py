"""Worker HTTP API: health, and fast clear failures on bad input. No DB needed."""

import time

from fastapi.testclient import TestClient

from tempo.worker.main import app

client = TestClient(app)


def test_health(monkeypatch):
    monkeypatch.setenv("WORKER_ID", "tempo-worker-3")
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["worker_id"] == "tempo-worker-3" and body["simulator"]


def test_replay_bad_dsn_is_500_not_hang():
    t0 = time.monotonic()
    r = client.post(
        "/replay",
        json={"database_url": "postgres://x:y@127.0.0.1:1/db", "decision_id": 1, "shift": 0, "run_id": "t"},
    )
    assert r.status_code == 500
    assert "cannot connect to database" in r.json()["detail"]
    assert time.monotonic() - t0 < 10


def test_replay_unroutable_host_times_out_under_10s():
    t0 = time.monotonic()
    r = client.post(
        "/replay",
        json={
            "database_url": "postgres://x:y@10.255.255.1:5432/db",
            "decision_id": 1,
            "shift": 0,
            "run_id": "t",
        },
    )
    assert r.status_code == 500
    assert time.monotonic() - t0 < 10


def test_replay_validates_body():
    r = client.post("/replay", json={"database_url": "", "decision_id": 1, "shift": 99, "run_id": "t"})
    assert r.status_code == 422


def test_replay_requires_token_when_set(monkeypatch):
    monkeypatch.setenv("TEMPO_WORKER_TOKEN", "s3cret")
    body = {"database_url": "postgres://x:y@127.0.0.1:1/db", "decision_id": 1, "shift": 0, "run_id": "t"}
    assert client.post("/replay", json=body).status_code == 401
    assert client.post("/replay", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.post("/replay", json=body, headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 500 and "cannot connect" in ok.json()["detail"]  # past auth, fails on the DSN
    assert client.get("/health").json()["auth"] is True
