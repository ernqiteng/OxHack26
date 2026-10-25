"""The JSON API for web/ answers every endpoint on synthetic data, with the shapes the frontend reads."""

import pytest
from fastapi.testclient import TestClient

from tempo.api import server
from tempo.dashboard.data import SyntheticSource


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "source", lambda: (SyntheticSource(), "synthetic for tests"))
    return TestClient(server.app)


def test_read_endpoints(client):
    assert client.get("/api/status").json()["source"] == "synthetic"
    live = client.get("/api/live").json()
    assert len(live["plan"]) == 48 and {"p10", "p50", "p90", "action"} <= live["plan"][0].keys()
    dec = client.get("/api/decisions").json()
    assert dec["decisions"] and dec["prices"]
    assert client.get("/api/replay").json()["rows"]
    honesty = client.get("/api/honesty").json()
    assert honesty["captured_pct"] > 0 and honesty["summary"]


def test_summary_and_audit(client):
    did = client.get("/api/decisions").json()["decisions"][3]["decision_id"]
    summary = client.get(f"/api/decisions/{did}/summary").json()
    assert "Tempo decided" in summary["text"]
    audit = client.post(f"/api/decisions/{did}/audit").json()
    assert [r["shift"] for r in audit["rows"]] == [-2, -1, 0, 1, 2]
    assert audit["sentence"]


def test_unknown_decision_is_404(client):
    assert client.get("/api/decisions/1/summary").status_code == 404
