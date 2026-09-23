"""Smoke tests for the financial money-graph input contract.

Run with:
    pytest -q tests/test_data_contract.py
"""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "money_graph" / "data"  # data/ живёт внутри money_graph/, не в корне репозитория


def _read(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    assert path.exists(), f"Missing input file: {path}"
    frame = pd.read_parquet(path)
    assert not frame.empty, f"Input file is empty: {path}"
    assert len(frame.columns) > 0, f"Input file has no columns: {path}"
    return frame


def test_financial_input_files_are_present_and_non_empty():
    for name in ("nodes.parquet", "edges.parquet", "transactions.parquet"):
        _read(name)


def test_graph_inputs_have_identifiable_keys():
    nodes = _read("nodes.parquet")
    edges = _read("edges.parquet")
    transactions = _read("transactions.parquet")

    node_columns = {column.lower() for column in nodes.columns}
    edge_columns = {column.lower() for column in edges.columns}
    transaction_columns = {column.lower() for column in transactions.columns}

    assert any("id" in column for column in node_columns)
    assert len(edge_columns) >= 2
    assert any(
        token in column
        for column in transaction_columns
        for token in ("amount", "value", "sum")
    )
