"""Replays write only under their own run_id and never touch live rows."""

import numpy as np
import pytest

from tempo.audit.shifts import ReplayError, replay_shift

from .conftest import day_prices, targets


def test_replay_writes_no_live_rows(market):
    market.prices(targets(), day_prices())
    did = market.decisions(np.tile([1.0, -1.0], 24))
    market.start_soc(1.0)
    live_before = market.state("live")

    replay_shift(market.conn, did, 1, "x")

    assert market.state("live") == live_before
    assert len(market.state("x")) == 48


def test_replay_refuses_live_run_id(market):
    market.prices(targets(), day_prices())
    did = market.decisions(np.zeros(48))
    with pytest.raises(ReplayError, match="live"):
        replay_shift(market.conn, did, 0, "live")
