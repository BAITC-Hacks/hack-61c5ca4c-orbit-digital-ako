"""Проверка, что выгрузки пайплайна соответствуют схеме ТЗ (must-have #2, #4, #5).

Запускает money_graph/run.py во временную папку и проверяет nodes_roles.csv,
clusters.csv, top_nodes.csv по документированной схеме стартового кода.
Это локальная проверка, а не неизвестный внешний валидатор жюри. Запускается через
`pytest -q`.

Запуск:
    pytest -q tests/test_output_schema.py
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MONEY_GRAPH = ROOT / "money_graph"
DATA_DIR = MONEY_GRAPH / "data"
sys.path.insert(0, str(MONEY_GRAPH))

from check import check
from run import analyze

ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
EXPECTED_N_NODES = 2248
EVIDENCE_MAX_CHARS = 200
TOP_NODES_MIN_ROWS = 20

@pytest.fixture(scope="module")
def output_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("schema-output")
    cfg = json.loads((MONEY_GRAPH / "config.json").read_text(encoding="utf-8"))
    analyze(DATA_DIR, out, cfg)
    return out


@pytest.fixture(scope="module")
def nodes_roles(output_dir) -> pd.DataFrame:
    return pd.read_csv(output_dir / "nodes_roles.csv")


@pytest.fixture(scope="module")
def clusters(output_dir) -> pd.DataFrame:
    return pd.read_csv(output_dir / "clusters.csv")


@pytest.fixture(scope="module")
def top_nodes(output_dir) -> pd.DataFrame:
    return pd.read_csv(output_dir / "top_nodes.csv")


def test_nodes_roles_has_exact_row_count(nodes_roles):
    assert len(nodes_roles) == EXPECTED_N_NODES


def test_nodes_roles_covers_every_gid_from_input(nodes_roles):
    nodes = pd.read_parquet(DATA_DIR / "nodes.parquet")
    assert set(nodes_roles["gid"].astype("int64")) == set(nodes["gid"].astype("int64"))


def test_nodes_roles_required_columns_are_filled(nodes_roles):
    required = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
    for col in required:
        assert col in nodes_roles.columns, f"нет колонки {col}"
        assert not nodes_roles[col].isna().any(), f"есть пропуски в {col}"


def test_role_is_within_documented_vocabulary(nodes_roles):
    bad = set(nodes_roles["role"]) - ROLES
    assert not bad, f"role вне строгого словаря ТЗ: {bad}"


def test_role_base_is_strictly_within_tz_vocabulary(nodes_roles):
    # role_base — подстраховка для механической проверки без учёта расширения словаря
    assert "role_base" in nodes_roles.columns
    bad = set(nodes_roles["role_base"]) - ROLES
    assert not bad, f"role_base вне словаря ТЗ (6 значений): {bad}"


def test_scores_are_in_unit_range(nodes_roles):
    assert nodes_roles["role_score"].between(0, 1).all()
    assert nodes_roles["priority_score"].between(0, 1).all()


def test_evidence_is_short_and_has_numbers(nodes_roles):
    evidence = nodes_roles["evidence"].astype(str)
    assert (evidence.str.len() <= EVIDENCE_MAX_CHARS).all()
    assert evidence.str.contains(r"\d").all(), "evidence без единой цифры — не объяснение, а лозунг"
    assert not evidence.str.strip().eq("").any()


def test_every_cluster_id_in_nodes_roles_has_a_cluster_row(nodes_roles, clusters):
    missing = set(nodes_roles["cluster_id"]) - set(clusters["cluster_id"])
    assert not missing, f"cluster_id без строки в clusters.csv: {sorted(missing)[:5]}"


def test_clusters_have_a_hypothesis(clusters):
    required = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
    for col in required:
        assert col in clusters.columns, f"нет колонки {col}"
    assert not clusters["hypothesis"].astype(str).str.strip().eq("").any()


def test_top_nodes_has_minimum_rows_and_is_sorted(top_nodes):
    assert len(top_nodes) >= TOP_NODES_MIN_ROWS
    assert (top_nodes["priority_score"].diff().dropna() <= 1e-9).all(), "top_nodes.csv не отсортирован по убыванию приоритета"


def test_strict_checker_on_fresh_outputs(output_dir):
    assert check(output_dir, DATA_DIR) == []


def test_export_mapping_preserves_boundary_nodes(nodes_roles, top_nodes, output_dir):
    for frame in (nodes_roles, top_nodes):
        assert frame.role.isin(ROLES).all()
        assert frame.role.eq(frame.role_base).all()
        assert frame.role_detail.replace({"truncated": "peripheral"}).eq(frame.role).all()
        assert frame.is_truncated.eq(frame.role_detail.eq("truncated")).all()
    assert nodes_roles.is_truncated.sum() == 444
    requests = pd.read_csv(output_dir / "requests.csv")
    assert (requests.request_type == "next_hop_outgoing").sum() == 444
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["roles"]["truncated"] == 444


def test_incoming_shares_and_known_seed_explanation(nodes_roles, top_nodes):
    positive = nodes_roles.in_kzt > 0
    expected = nodes_roles.loc[positive, "tainted_in_kzt"] / nodes_roles.loc[positive, "in_kzt"]
    assert (nodes_roles.loc[positive, "taint_share"] - expected).abs().max() < 1e-12
    assert nodes_roles.loc[~positive, "taint_share"].isna().all()
    gid = 100000003684369100
    node = nodes_roles.set_index("gid").loc[gid]
    assert node.taint_state_share == 1.0
    assert node.taint_share == pytest.approx(0.7960395131)
    why = top_nodes.set_index("gid").loc[gid, "why"]
    assert "79.6%" in why and "100%" not in why
    assert "3848436.00 KZT" in why
