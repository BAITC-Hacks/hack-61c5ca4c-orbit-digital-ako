"""Regression checks for user-supplied case parameters and upload types."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))

from mg.validation import InputError, validate_data
from run import analyze


@pytest.fixture
def small_case(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame({"gid": [101, 202], "depth": [0, 1], "is_seed": [True, False]}).to_parquet(data / "nodes.parquet")
    pd.DataFrame({"src": [101], "dst": [202], "sum_kzt": [100000.0], "n_tx": [1], "depth": [1]}).to_parquet(data / "edges.parquet")
    pd.DataFrame({"src": [101], "dst": [202], "date": ["2026-08-15"], "sum_kzt": [100000.0]}).to_parquet(data / "transactions.parquet")
    return data


def test_observed_depth_does_not_replace_collection_boundary(small_case, tmp_path):
    config = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
    summary = analyze(small_case, tmp_path / "out", config)
    roles = pd.read_csv(tmp_path / "out" / "nodes_roles.csv").set_index("gid")
    assert summary["max_depth"] == 4
    assert roles.loc[202, "role"] == "terminal"
    assert summary["period_end"] == "2026-08-15"


def test_upload_rejects_string_amounts(small_case):
    path = small_case / "transactions.parquet"
    tx = pd.read_parquet(path)
    tx["sum_kzt"] = tx.sum_kzt.astype(str)
    tx.to_parquet(path)
    with pytest.raises(InputError, match="числовой тип"):
        validate_data(small_case)


def test_upload_rejects_depth_outside_declared_boundary(small_case):
    path = small_case / "nodes.parquet"
    nodes = pd.read_parquet(path)
    nodes.loc[nodes.gid == 202, "depth"] = 3
    nodes.to_parquet(path)
    with pytest.raises(InputError, match="границу обхода"):
        validate_data(small_case, max_depth=2)
