"""FastAPI worker: POST /replay {database_url, decision_id, shift, run_id}, GET /health.

Owner: Ayo. See docs/ayo.md Phase 2 task 1.

Runs on each Vultr worker under systemd (deploy/systemd/tempo-worker.service). It is stateless: the
orchestrator sends the fork's DSN with every request, so the worker reads nothing from the environment
except its own id (WORKER_ID, else the hostname) and its shared token (TEMPO_WORKER_TOKEN). A bad DSN fails
fast with a 500 and a message, never a hang.

When TEMPO_WORKER_TOKEN is set, /replay requires `Authorization: Bearer <token>`. Without it, a worker on a
public IP would run replays against any database anyone points it at. The Vultr image always sets it.

    uvicorn tempo.worker.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import hmac
import os
import socket
import threading
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from tempo.audit.refsim import resolve_sim
from tempo.audit.shifts import ReplayError, replay_shift

CONNECT_TIMEOUT_S = 8


def worker_id() -> str:
    return os.environ.get("WORKER_ID") or socket.gethostname()


class ReplayRequest(BaseModel):
    database_url: str = Field(min_length=1)
    decision_id: int
    shift: int = Field(ge=-47, le=47)
    run_id: str = Field(min_length=1)


class ReplayResponse(BaseModel):
    pnl_gbp: float
    started_at: datetime
    finished_at: datetime
    worker_id: str
    simulator: str


app = FastAPI(title="tempo-worker")
_state = {"busy": 0, "served": 0}
_lock = threading.Lock()


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "worker_id": worker_id(),
        "simulator": resolve_sim()[1],
        "auth": bool(os.environ.get("TEMPO_WORKER_TOKEN")),
        "busy": _state["busy"],
        "served": _state["served"],
    }


def check_token(authorization: str | None) -> None:
    expected = os.environ.get("TEMPO_WORKER_TOKEN", "")
    if not expected:
        return
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "missing or wrong worker token")


@app.post("/replay", response_model=ReplayResponse)
def replay(req: ReplayRequest, authorization: str | None = Header(default=None)) -> ReplayResponse:
    import psycopg

    check_token(authorization)

    started = datetime.now(tz=UTC)
    with _lock:
        _state["busy"] += 1
    try:
        try:
            conn = psycopg.connect(req.database_url, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"cannot connect to database: {type(exc).__name__}: {exc}") from exc
        try:
            pnl = replay_shift(conn, req.decision_id, req.shift, req.run_id)
        except ReplayError as exc:
            raise HTTPException(422, f"replay failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"replay crashed: {type(exc).__name__}: {exc}") from exc
        finally:
            conn.close()
    finally:
        with _lock:
            _state["busy"] -= 1
            _state["served"] += 1
    return ReplayResponse(
        pnl_gbp=pnl,
        started_at=started,
        finished_at=datetime.now(tz=UTC),
        worker_id=worker_id(),
        simulator=resolve_sim()[1],
    )
