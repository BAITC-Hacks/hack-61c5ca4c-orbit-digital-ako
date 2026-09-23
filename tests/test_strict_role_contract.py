"""Exercise the CSV checker independently of shared, regenerated output files."""
import pandas as pd
import pytest

from money_graph.check import check


@pytest.fixture
def strict_export(tmp_path):
    data = tmp_path / "data"
    out = tmp_path / "out"
    data.mkdir()
    out.mkdir()
    roles = ["peripheral", "consolidator", "transit", "distributor", "terminal", "coordinator"]
    nodes = pd.DataFrame({
        "gid": range(1, 2249),
        "role": [roles[i % len(roles)] for i in range(2248)],
        "role_score": 0.5,
        "cluster_id": 0,
        "priority_score": [1 - i / 2248 for i in range(2248)],
        "evidence": "1 observed transfer",
    })
    nodes["role_base"] = nodes["role"]
    nodes["role_detail"] = nodes["role"]
    nodes["is_truncated"] = False
    nodes.loc[0, ["role_detail", "is_truncated"]] = ["truncated", True]
    nodes[["gid"]].to_parquet(data / "nodes.parquet", index=False)
    nodes.to_csv(out / "nodes_roles.csv", index=False)
    top = nodes.head(20).drop(columns=["role_score", "cluster_id"]).rename(columns={"evidence": "why"})
    top.insert(0, "rank", range(1, 21))
    top.to_csv(out / "top_nodes.csv", index=False)
    pd.DataFrame([{
        "cluster_id": 0, "n_nodes": 2248, "n_seed": 0,
        "sum_kzt_internal": 0, "top_gids": "1;2;3", "hypothesis": "Review 1 cluster",
    }]).to_csv(out / "clusters.csv", index=False)
    return out, data


@pytest.mark.parametrize("with_details", [False, True])
def test_checker_accepts_strict_roles_with_optional_truncation_details(strict_export, with_details):
    out, data = strict_export
    if not with_details:
        for filename in ("nodes_roles.csv", "top_nodes.csv"):
            frame = pd.read_csv(out / filename).drop(columns=["role_detail", "is_truncated"])
            frame.to_csv(out / filename, index=False)
    assert check(out, data) == []


@pytest.mark.parametrize("filename", ["nodes_roles.csv", "top_nodes.csv"])
@pytest.mark.parametrize("invalid_role", ["truncated", "unknown", None])
def test_checker_rejects_invalid_role_even_with_peripheral_role_base(strict_export, filename, invalid_role):
    out, data = strict_export
    frame = pd.read_csv(out / filename)
    frame.loc[0, "role"] = invalid_role
    frame.loc[0, "role_base"] = "peripheral"
    frame.to_csv(out / filename, index=False)
    errors = check(out, data)
    assert any(error.startswith(f"{filename}: role вне словаря ТЗ") for error in errors), errors


@pytest.mark.parametrize("filename", ["nodes_roles.csv", "top_nodes.csv"])
def test_checker_requires_role_even_with_valid_role_base(strict_export, filename):
    out, data = strict_export
    frame = pd.read_csv(out / filename).drop(columns=["role"])
    frame.to_csv(out / filename, index=False)
    errors = check(out, data)
    assert f"{filename}: отсутствует обязательная колонка role" in errors
