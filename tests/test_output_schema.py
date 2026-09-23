"""Проверка, что выгрузки пайплайна соответствуют схеме ТЗ (must-have #2, #4, #5).

Запускает money_graph/run.py во временную папку и проверяет nodes_roles.csv,
clusters.csv, top_nodes.csv так же, как это будет делать жюри. Это то же самое,
что money_graph/check.py, но как pytest-тест — чтобы он подхватывался обычным
`pytest -q`.

Запуск:
    cd money_graph && python run.py   # один раз, чтобы посчитать out/
    pytest -q tests/test_output_schema.py
"""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MONEY_GRAPH = ROOT / "money_graph"
OUT_DIR = MONEY_GRAPH / "out"
DATA_DIR = MONEY_GRAPH / "data"

ROLES = {"consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"}
EXTENDED_ROLES = ROLES | {"truncated"}  # расширение словаря, задокументировано в README
EXPECTED_N_NODES = 2248
EVIDENCE_MAX_CHARS = 200
TOP_NODES_MIN_ROWS = 20

pytestmark = pytest.mark.skipif(
    not (OUT_DIR / "nodes_roles.csv").exists(),
    reason="out/ ещё не посчитан — сначала запустите money_graph/run.py",
)


@pytest.fixture(scope="module")
def nodes_roles() -> pd.DataFrame:
    return pd.read_csv(OUT_DIR / "nodes_roles.csv")


@pytest.fixture(scope="module")
def clusters() -> pd.DataFrame:
    return pd.read_csv(OUT_DIR / "clusters.csv")


@pytest.fixture(scope="module")
def top_nodes() -> pd.DataFrame:
    return pd.read_csv(OUT_DIR / "top_nodes.csv")


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
    bad = set(nodes_roles["role"]) - EXTENDED_ROLES
    assert not bad, f"role вне словаря ТЗ (даже с расширением): {bad}"


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
