"""Finite-horizon explanations and strict submission contract regressions."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))

import check as contract
from mg.features import temporal_features
from mg.taint import TaintModel
from run import explain_priority


def test_seed_state_is_not_incoming_fraction():
    # Seed 1 receives 25 from seed 2 and 75 from an unseeded source.
    edges = pd.DataFrame({"src": [2, 3, 1], "dst": [1, 1, 4], "sum_kzt": [25., 75., 100.]})
    nodes = pd.DataFrame({"is_seed": [True, True, False, False]}, index=[1, 2, 3, 4])
    model = TaintModel(edges, nodes, 2)
    state, incoming, total = model.propagate()
    assert state[0] == 1.0
    assert incoming[0] == 25.0
    assert total == incoming.sum() == 125.0
    row = pd.Series({"evidence": "Получил 100 KZT.", "tainted_in_kzt": incoming[0],
                     "in_kzt": 100., "taint_share": state[0], "block_impact": .1, "cluster_id": 1})
    why = explain_priority(row, 2, 2)
    assert "25.00 KZT из 100.00 KZT" in why and "25.0%" in why
    assert "100.0%" not in why
    assert "2 итераций" in why and "не уникальные средства" in why
    assert "порядок переводов в один день неизвестен" in why


def test_returned_incoming_uses_final_state_edge_flow():
    edges = pd.DataFrame({"src": [1, 2, 3], "dst": [2, 3, 4], "sum_kzt": [100., 100., 100.]})
    nodes = pd.DataFrame({"is_seed": [True, False, False, False]}, index=[1, 2, 3, 4])
    model = TaintModel(edges, nodes, 1)
    state, incoming, total = model.propagate()
    np.testing.assert_array_equal(state, [1., 1., 0., 0.])
    np.testing.assert_array_equal(incoming, [0., 100., 100., 0.])
    assert total == 200.
    # Node 3 illustrates why incoming fraction must not reuse state_H[3].
    assert incoming[2] / 100. == 1. and state[2] == 0.
    assert TaintModel(edges, nodes, 2).propagate()[2] == 300.


def test_no_observed_incoming_has_no_percentage():
    row = pd.Series({"evidence": "Вход 0 KZT.", "tainted_in_kzt": 0., "in_kzt": 0.,
                     "block_impact": 0., "cluster_id": 0})
    assert "доля модельного входа не определена" in explain_priority(row, 8, 2)


def test_temporal_proxy_does_not_claim_amount_matching_or_same_day_order():
    tx = pd.DataFrame({"src": [1, 2, 2], "dst": [2, 3, 4],
                       "date": pd.to_datetime(["2026-07-01"] * 3),
                       "sum_kzt": [5000., 500000., 500000.]})
    # Kept deliberately as a date-proximity feature, not a conserved cash flow.
    assert temporal_features(tx, 2).loc[2, "fast_share"] == 1.


@pytest.fixture
def contract_case(tmp_path, monkeypatch):
    monkeypatch.setattr(contract, "EXPECTED_N_NODES", 3)
    monkeypatch.setattr(contract, "TOP_NODES_MIN_ROWS", 2)
    gids = [100000003684369100, 100000003684369101, 100000003684369102]
    pd.DataFrame({"gid": gids}).to_parquet(tmp_path / "nodes.parquet")
    nodes = pd.DataFrame({"gid": gids, "role": ["peripheral"] * 3,
                          "role_score": [.8] * 3, "cluster_id": [1] * 3,
                          "priority_score": [.9, .8, .7], "evidence": ["Вход 1 KZT."] * 3})
    clusters = pd.DataFrame({"cluster_id": [1], "n_nodes": [3], "n_seed": [1],
                             "sum_kzt_internal": [1.], "top_gids": [str(gids[0])],
                             "hypothesis": ["Группа из 3 узлов"]})
    top = nodes.head(2)[["gid", "role", "priority_score"]].copy()
    top["rank"] = [1, 2]
    top["why"] = "Вход 1 KZT."
    nodes.to_csv(tmp_path / "nodes_roles.csv", index=False)
    clusters.to_csv(tmp_path / "clusters.csv", index=False)
    top.to_csv(tmp_path / "top_nodes.csv", index=False)
    return tmp_path, nodes, top


def test_checker_accepts_strict_contract_and_large_integer_gids(contract_case):
    path, _, _ = contract_case
    assert contract.check(path, path) == []


@pytest.mark.parametrize("column", ["rank", "gid", "role", "priority_score", "why"])
def test_checker_rejects_missing_top_columns(contract_case, column):
    path, _, top = contract_case
    top.drop(columns=column).to_csv(path / "top_nodes.csv", index=False)
    assert any(column in error for error in contract.check(path, path))


@pytest.mark.parametrize("column,value,fragment", [
    ("gid", 999, "gid отсутствует"),
    ("gid", "100000003684369100.0", "int64"),
    ("role", "truncated", "role вне словаря"),
    ("role", "terminal", "role не совпадает"),
    ("priority_score", float("inf"), "вне диапазона"),
    ("priority_score", .95, "priority_score не совпадает"),
    ("why", "", "пропуски"),
    ("why", "Объяснение без чисел", "числовое объяснение"),
    ("rank", 2, "rank не идёт"),
])
def test_checker_rejects_invalid_top_rows(contract_case, column, value, fragment):
    path, _, top = contract_case
    top[column] = top[column].astype(object)
    top.at[0, column] = value
    top.to_csv(path / "top_nodes.csv", index=False)
    assert any(fragment in error for error in contract.check(path, path))


def test_checker_rejects_duplicate_top_gid(contract_case):
    path, _, top = contract_case
    top.loc[1, "gid"] = top.loc[0, "gid"]
    top.to_csv(path / "top_nodes.csv", index=False)
    assert any("повторяющиеся gid" in error for error in contract.check(path, path))


def test_checker_rejects_extended_primary_role(contract_case):
    path, nodes, _ = contract_case
    nodes.loc[2, "role"] = "truncated"
    nodes.to_csv(path / "nodes_roles.csv", index=False)
    assert any("nodes_roles.csv: role вне словаря" in error for error in contract.check(path, path))


def test_checker_reports_missing_node_gid_without_crashing(contract_case):
    path, nodes, _ = contract_case
    nodes.drop(columns="gid").to_csv(path / "nodes_roles.csv", index=False)
    assert any("nodes_roles.csv: отсутствует обязательная колонка gid" in error
               for error in contract.check(path, path))
