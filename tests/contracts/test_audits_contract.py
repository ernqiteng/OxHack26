"""Shared contract for `audits` rows (plan.md section 5). Producer: Ayo. Consumers: dashboard, Ernqi's
self-grade. No DB needed: checks the schema text, the row shape, and the five-shift / zero-delta rules."""

import re
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tempo.audit.orchestrator import SHIFTS, AuditRow, check_audit_rows, fill_deltas, run_audit

SCHEMA = (Path(__file__).resolve().parents[2] / "tempo/db/schema.sql").read_text()


def audits_columns() -> set[str]:
    body = re.search(r"CREATE TABLE IF NOT EXISTS audits \((.*?)\n\);", SCHEMA, re.S).group(1)
    cols = set()
    for line in body.splitlines():
        line = line.strip()
        if line and not line.upper().startswith("PRIMARY KEY"):
            cols.add(line.split()[0])
    return cols


def test_schema_has_every_stored_field():
    stored = {f.name for f in fields(AuditRow)} - {"error"}
    assert stored == audits_columns()


def test_schema_constrains_shift_and_mode():
    assert "CHECK (shift BETWEEN -2 AND 2)" in SCHEMA
    assert "CHECK (mode IN ('inprocess', 'fork'))" in SCHEMA
    assert list(SHIFTS) == [-2, -1, 0, 1, 2]


def fake_rows(pnls, mode="inprocess"):
    t = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        AuditRow(7, s, p, None, mode, t, t + timedelta(seconds=1)) for s, p in zip(SHIFTS, pnls, strict=True)
    ]
    return fill_deltas(rows)


def test_run_audit_rows_satisfy_contract():
    pnl = {-2: 90.0, -1: 101.5, 0: 110.0, 1: 96.0, 2: 80.25}
    rows = run_audit(None, 7, replay=lambda c, d, s, r: pnl[s], write=False)
    check_audit_rows(rows)
    assert [r.pnl_delta_gbp for r in rows] == [-20.0, -8.5, 0.0, -14.0, -29.75]
    assert [r.mode for r in rows] == ["inprocess"] * 5


def test_failed_shift_has_null_pnl_and_delta():
    rows = fake_rows([90.0, None, 110.0, 96.0, 80.0])
    check_audit_rows(rows)
    assert rows[1].pnl_delta_gbp is None


def test_failed_shift_zero_nulls_every_delta():
    rows = fake_rows([90.0, 100.0, None, 96.0, 80.0])
    check_audit_rows(rows)
    assert all(r.pnl_delta_gbp is None for r in rows)


def test_contract_rejects_bad_sets():
    with pytest.raises(AssertionError):
        check_audit_rows(fake_rows([1.0, 2.0, 3.0, 4.0, 5.0])[:4])
    bad = fake_rows([1.0, 2.0, 3.0, 4.0, 5.0])
    bad[2].pnl_delta_gbp = 0.5
    with pytest.raises(AssertionError):
        check_audit_rows(bad)


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        run_audit(None, 1, mode="cloud")
