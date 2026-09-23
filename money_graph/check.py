#!/usr/bin/env python3
"""Проверка выгрузок на соответствие схеме ТЗ — то, что скорее всего
механически проверит жюри. Запускать после каждого run.py:

    python run.py && python check.py

Ничего не чинит, только сообщает проблемы; exit code 1 при провале.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]
EXTENDED_ROLES = ROLES + ["truncated"]  # "truncated" — расширение словаря, задокументировано в README
EXPECTED_N_NODES = 2248
EVIDENCE_MAX_CHARS = 200
TOP_NODES_MIN_ROWS = 20


def check(out_dir: Path, data_dir: Path) -> list[str]:
    errors: list[str] = []

    nodes_path = out_dir / "nodes_roles.csv"
    clusters_path = out_dir / "clusters.csv"
    top_path = out_dir / "top_nodes.csv"

    for p in (nodes_path, clusters_path, top_path):
        if not p.exists():
            errors.append(f"файл отсутствует: {p}")
    if errors:
        return errors

    nr = pd.read_csv(nodes_path)
    cl = pd.read_csv(clusters_path)
    tn = pd.read_csv(top_path)

    # --- nodes_roles.csv ---------------------------------------------------
    if len(nr) != EXPECTED_N_NODES:
        errors.append(f"nodes_roles.csv: {len(nr)} строк, ожидалось {EXPECTED_N_NODES}")

    nodes_gids = set(pd.read_parquet(data_dir / "nodes.parquet")["gid"].astype("int64"))
    if set(nr["gid"].astype("int64")) != nodes_gids:
        errors.append("nodes_roles.csv: набор gid не совпадает с nodes.parquet")

    required_cols = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
    for c in required_cols:
        if c not in nr.columns:
            errors.append(f"nodes_roles.csv: отсутствует обязательная колонка {c}")
        elif nr[c].isna().any():
            errors.append(f"nodes_roles.csv: есть пропуски в колонке {c}")

    if "role" in nr.columns and not nr["role"].isin(EXTENDED_ROLES).all():
        bad = sorted(set(nr.loc[~nr["role"].isin(EXTENDED_ROLES), "role"]))
        errors.append(f"nodes_roles.csv: role вне словаря ТЗ (даже с расширением): {bad}")

    # role_base — подстраховка на случай строгой проверки без учёта расширения
    if "role_base" in nr.columns and not nr["role_base"].isin(ROLES).all():
        bad = sorted(set(nr.loc[~nr["role_base"].isin(ROLES), "role_base"]))
        errors.append(f"nodes_roles.csv: role_base вне словаря ТЗ (6 значений): {bad}")

    if "role_score" in nr.columns and not nr["role_score"].between(0, 1).all():
        errors.append("nodes_roles.csv: role_score вне диапазона [0,1]")
    if "priority_score" in nr.columns and not nr["priority_score"].between(0, 1).all():
        errors.append("nodes_roles.csv: priority_score вне диапазона [0,1]")

    if "evidence" in nr.columns:
        too_long = nr["evidence"].astype(str).str.len() > EVIDENCE_MAX_CHARS
        if too_long.any():
            errors.append(f"nodes_roles.csv: evidence длиннее {EVIDENCE_MAX_CHARS} симв. у {too_long.sum()} строк")
        no_digit = ~nr["evidence"].astype(str).str.contains(r"\d")
        if no_digit.any():
            errors.append(f"nodes_roles.csv: evidence без единой цифры у {no_digit.sum()} строк")
        empty = nr["evidence"].astype(str).str.strip().eq("")
        if empty.any():
            errors.append(f"nodes_roles.csv: пустой evidence у {empty.sum()} строк")

    # --- clusters.csv ---------------------------------------------------------
    required_cluster_cols = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
    for c in required_cluster_cols:
        if c not in cl.columns:
            errors.append(f"clusters.csv: отсутствует обязательная колонка {c}")

    if "cluster_id" in nr.columns and "cluster_id" in cl.columns:
        missing = set(nr["cluster_id"]) - set(cl["cluster_id"])
        if missing:
            errors.append(f"clusters.csv: нет строк для cluster_id из nodes_roles.csv: {sorted(missing)[:5]}...")

    if "hypothesis" in cl.columns and cl["hypothesis"].astype(str).str.strip().eq("").any():
        errors.append("clusters.csv: есть пустые hypothesis")

    # --- top_nodes.csv ----------------------------------------------------------
    if len(tn) < TOP_NODES_MIN_ROWS:
        errors.append(f"top_nodes.csv: {len(tn)} строк, требуется >= {TOP_NODES_MIN_ROWS}")

    if "priority_score" in tn.columns:
        if not (tn["priority_score"].diff().dropna() <= 1e-9).all():
            errors.append("top_nodes.csv: не отсортирован по priority_score по убыванию")

    if "rank" in tn.columns:
        expected_rank = list(range(1, len(tn) + 1))
        if tn["rank"].tolist() != expected_rank:
            errors.append("top_nodes.csv: rank не идёт подряд 1..N")

    return errors


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--data", default="data")
    a = ap.parse_args()

    errors = check(Path(a.out), Path(a.data))
    if errors:
        print(f"НЕ ПРОШЛО ({len(errors)} проблем):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("OK: все выгрузки соответствуют схеме ТЗ")


if __name__ == "__main__":
    main()
