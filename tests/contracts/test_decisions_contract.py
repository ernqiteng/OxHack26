"""Shared contract for `decisions` batches (plan.md section 5). Producer: run_decision (Part A).
Consumers: Ayo's replay/audit and dashboard, Ernqi's self-grade. No DB: checks the row builder."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from tempo.decide.engine import ACTIONS, decision_rows

T = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def frames(n=48, mw=None, reason=None):
    idx = pd.date_range(T, periods=n + 1, freq="30min", tz=UTC)[1:]
    idx.name = "target_time"
    mw = np.zeros(n) if mw is None else np.asarray(mw, float)
    action = np.where(mw > 0, "charge", np.where(mw < 0, "discharge", "hold"))
    plan = pd.DataFrame(
        {
            "action": action,
            "mw": mw,
            "expected_spread": np.where(mw != 0, 12.0, np.nan),
            "reason": reason
            if reason is not None
            else np.where(mw != 0, "trade", "hold: spread 3 < cost 18"),
        },
        index=idx,
    )
    q = pd.DataFrame({"p10": 40.0, "p50": 50.0, "p90": 60.0}, index=idx)
    return plan, q


def test_batch_shape_and_fields():
    mw = np.zeros(48)
    mw[2:6], mw[34:38] = 1.0, -1.0
    rows = decision_rows(*frames(mw=mw), T, "live")
    assert len(rows) == 48 and rows.decided_at.nunique() == 1 and rows.run_id.unique().tolist() == ["live"]
    assert set(rows.action) <= set(ACTIONS)
    assert ((rows.action == "charge") == (rows.mw > 0)).all()
    assert ((rows.action == "discharge") == (rows.mw < 0)).all()
    assert ((rows.action == "hold") == (rows.mw == 0)).all()
    assert (rows.loc[rows.action == "hold", "reason"].str.len() > 0).all()
    assert {"p10", "p50", "p90"} <= set(rows.columns)


def test_hold_without_reason_gets_one():
    plan, q = frames(reason=[""] * 48)
    rows = decision_rows(plan, q, T, "live")
    assert (rows.reason.str.startswith("hold")).all()


def test_sign_mismatch_rejected():
    plan, q = frames(mw=np.r_[1.0, np.zeros(47)])
    plan.loc[plan.index[0], "action"] = "discharge"
    with pytest.raises(ValueError, match="mw sign"):
        decision_rows(plan, q, T, "live")


def test_unknown_action_rejected():
    plan, q = frames()
    plan.loc[plan.index[0], "action"] = "wait"
    with pytest.raises(ValueError, match="unknown actions"):
        decision_rows(plan, q, T, "live")


def test_index_mismatch_rejected():
    plan, q = frames()
    with pytest.raises(ValueError, match="same target_time"):
        decision_rows(plan.iloc[:47], q, T, "live")
