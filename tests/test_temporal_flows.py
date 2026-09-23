"""Small money trails with known results, independent of saved demo exports."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "money_graph"))
from mg.features import temporal_features
from mg.taint import TaintModel


def transactions(*rows):
    tx = pd.DataFrame(rows, columns=["src", "dst", "date", "sum_kzt"])
    tx["date"] = pd.to_datetime(tx.date)
    return tx


def model(tx, seeds=(1,)):
    gids = sorted(set(tx.src) | set(tx.dst) | set(seeds))
    df = pd.DataFrame({"is_seed": [gid in seeds for gid in gids]}, index=gids)
    edges = tx.groupby(["src", "dst"], as_index=False).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"))
    return TaintModel(edges, df, tx=tx)


def received(tm, gid):
    return tm.propagate()[1][tm.idx[gid]]


def test_outgoing_before_incoming_is_not_marked_or_fast():
    tx = transactions((2, 3, "2026-07-01", 100), (1, 2, "2026-07-02", 100))
    tm = model(tx)
    assert received(tm, 2) == 100
    assert received(tm, 3) == 0
    f = temporal_features(tx, 2)
    assert f.loc[2, "fast_share"] == 0
    assert f.loc[2, "unmatched_out_kzt"] == 100


def test_insufficient_incoming_and_repeated_spending_are_capped():
    tx = transactions((1, 2, "2026-07-01", 10), (2, 3, "2026-07-02", 30),
                      (2, 4, "2026-07-03", 20))
    tm = model(tx)
    assert received(tm, 3) == pytest.approx(10)
    assert received(tm, 4) == 0
    f = temporal_features(tx, 2)
    assert f.loc[2, "fast_share"] == pytest.approx(10 / 50)
    assert f.loc[2, "matched_out_kzt"] == 10
    assert f.loc[2, "unmatched_out_kzt"] == 40


def test_unknown_same_day_order_never_creates_a_chain_and_is_input_order_invariant():
    tx = transactions((1, 2, "2026-07-01", 100), (2, 3, "2026-07-01", 100),
                      (3, 4, "2026-07-02", 100))
    tm = model(tx)
    assert received(tm, 3) == 0
    assert received(tm, 4) == 0
    shuffled = model(tx.iloc[::-1])
    np.testing.assert_allclose(tm.propagate()[1], shuffled.propagate()[1])
    f = temporal_features(tx, 2)
    assert f.loc[2, "fast_share"] == 0
    assert f.loc[2, "same_day_overlap_kzt"] == 100


def test_same_day_outgoing_uses_prior_balance_proportionally():
    tx = transactions((1, 2, "2026-07-01", 100), (2, 3, "2026-07-02", 100),
                      (2, 4, "2026-07-02", 300))
    tm = model(tx)
    assert received(tm, 3) == pytest.approx(25)
    assert received(tm, 4) == pytest.approx(75)
    np.testing.assert_allclose(tm.propagate()[1], model(tx.iloc[::-1]).propagate()[1])


def test_prior_unmarked_inflows_dilute_marked_balance():
    tx = transactions((1, 2, "2026-07-01", 100), (5, 2, "2026-07-01", 100),
                      (2, 3, "2026-07-02", 100), (2, 4, "2026-07-03", 100))
    tm = model(tx)
    assert received(tm, 3) == pytest.approx(50)
    assert received(tm, 4) == pytest.approx(50)


def test_cycles_only_advance_chronologically_and_do_not_create_money():
    tx = transactions((1, 2, "2026-07-01", 100), (2, 3, "2026-07-02", 100),
                      (3, 2, "2026-07-03", 100), (2, 4, "2026-07-04", 200))
    tm = model(tx)
    assert received(tm, 2) == pytest.approx(200)  # Two actual receipts of the same money.
    assert received(tm, 4) == pytest.approx(100)
    assert tm.propagate()[2] == pytest.approx(400)  # Transfer volume, not unique funds.
    trace = tm.edge_trace()
    assert (trace.tainted_kzt <= trace.sum_kzt + 1e-9).all()
    assert trace.tainted_kzt.sum() == pytest.approx(tm.propagate()[2])


def test_removing_bridge_removes_onward_marked_flow_and_keeps_baseline():
    tx = transactions((1, 2, "2026-07-01", 100), (2, 3, "2026-07-02", 100))
    tm = model(tx)
    removed = np.zeros(tm.n, dtype=bool)
    removed[tm.idx[2]] = True
    assert tm.propagate(removed)[2] == 0
    assert tm.block_impact()[tm.idx[2]] == pytest.approx(1)
    assert tm.propagate()[2] == 200


def test_fast_share_consumes_old_money_before_new_money_with_fifo():
    tx = transactions((1, 2, "2026-07-01", 100), (1, 2, "2026-07-05", 100),
                      (2, 3, "2026-07-06", 100), (2, 4, "2026-07-07", 100))
    f = temporal_features(tx, 2)
    assert f.loc[2, "fast_share"] == pytest.approx(0.5)
    assert f.loc[2, "matched_out_kzt"] == 200
    assert f.loc[2, "median_lag"] == 2
    assert temporal_features(tx, 1).loc[2, "fast_share"] == 0


def test_temporal_model_requires_transaction_dates():
    with pytest.raises(ValueError, match="transactions"):
        TaintModel(pd.DataFrame(), pd.DataFrame())


def test_no_seed_outflows_produces_zero_marked_flow():
    tm = model(transactions((2, 3, "2026-07-01", 100), (3, 4, "2026-07-02", 100)))
    assert tm.propagate()[2] == 0
    assert (tm.block_impact() == 0).all()
    assert (tm.edge_trace().tainted_kzt == 0).all()


def test_seed_outgoing_marking_is_separate_from_seed_received_share():
    tx = transactions((5, 1, "2026-07-01", 100), (1, 2, "2026-07-02", 100))
    tm = model(tx)
    share, amounts, _ = tm.propagate()
    assert share[tm.idx[1]] == 0  # The observed seed receipt was unmarked.
    assert amounts[tm.idx[1]] == 0
    assert received(tm, 2) == 100  # Seed-origin outgoing transfers are marked by assumption.


def test_removal_can_increase_marked_volume_by_removing_unmarked_dilution():
    tx = transactions((1, 2, "2026-07-01", 100), (5, 2, "2026-07-01", 100),
                      (2, 3, "2026-07-02", 100), (3, 4, "2026-07-03", 100))
    tm = model(tx)
    assert tm.propagate()[2] == 200
    assert tm.block_impact()[tm.idx[5]] == pytest.approx(-0.5)
