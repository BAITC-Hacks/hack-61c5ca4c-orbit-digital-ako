#!/usr/bin/env python3
"""Локальная строгая проверка схемы стартового кода, не валидатор жюри.
Запускать после каждого run.py:

    python run.py && python check.py

Ничего не чинит, только сообщает проблемы; exit code 1 при провале.
"""
import sys
from pathlib import Path

import pandas as pd

ROLES = ["consolidator", "transit", "distributor", "terminal", "coordinator", "peripheral"]
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

    nr = pd.read_csv(nodes_path, dtype={"gid": str})
    cl = pd.read_csv(clusters_path)
    tn = pd.read_csv(top_path, dtype={"gid": str})

    schemas = [
        ("nodes_roles.csv", nr, ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]),
        ("clusters.csv", cl, ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]),
        ("top_nodes.csv", tn, ["rank", "gid", "role", "priority_score", "why"]),
    ]
    missing_columns = False
    for name, frame, columns in schemas:
        for column in columns:
            if column not in frame:
                errors.append(f"{name}: отсутствует обязательная колонка {column}")
                missing_columns = True
            elif frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
                errors.append(f"{name}: есть пропуски в колонке {column}")
    if missing_columns:
        return errors

    valid_ids = True
    for name, frame in (("nodes_roles.csv", nr), ("top_nodes.csv", tn)):
        ids = frame.gid.fillna("")
        if not ids.str.fullmatch(r"-?\d{1,19}").all() or not all(
            -(2 ** 63) <= int(g) < 2 ** 63 for g in ids if str(g).lstrip("-").isdigit()
        ):
            errors.append(f"{name}: gid должен быть целым int64 без потери точности")
            valid_ids = False
        if frame.gid.duplicated().any():
            errors.append(f"{name}: повторяющиеся gid")
        if not frame.role.isin(ROLES).all():
            errors.append(f"{name}: role вне словаря ТЗ (6 значений)")
        for score in ("role_score", "priority_score"):
            if score in frame and not pd.to_numeric(frame[score], errors="coerce").between(0, 1).all():
                errors.append(f"{name}: {score} вне диапазона [0,1]")
        if "role_base" in frame and not frame.role_base.eq(frame.role).all():
            errors.append(f"{name}: role_base не совпадает с role")
        if "role_detail" in frame:
            if not frame.role_detail.isin(ROLES + ["truncated"]).all() or not frame.role_detail.replace({"truncated": "peripheral"}).eq(frame.role).all():
                errors.append(f"{name}: role_detail не соответствует role")
            if "is_truncated" in frame and (not pd.api.types.is_bool_dtype(frame.is_truncated) or not frame.is_truncated.eq(frame.role_detail.eq("truncated")).all()):
                errors.append(f"{name}: is_truncated не соответствует role_detail")

    # --- nodes_roles.csv ---------------------------------------------------
    if len(nr) != EXPECTED_N_NODES:
        errors.append(f"nodes_roles.csv: {len(nr)} строк, ожидалось {EXPECTED_N_NODES}")

    nodes_gids = set(pd.read_parquet(data_dir / "nodes.parquet")["gid"].astype("int64"))
    if valid_ids and set(nr["gid"].map(int)) != nodes_gids:
        errors.append("nodes_roles.csv: набор gid не совпадает с nodes.parquet")

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
    if "cluster_id" in nr.columns and "cluster_id" in cl.columns:
        missing = set(nr["cluster_id"]) - set(cl["cluster_id"])
        if missing:
            errors.append(f"clusters.csv: нет строк для cluster_id из nodes_roles.csv: {sorted(missing)[:5]}...")

    if "hypothesis" in cl.columns and cl["hypothesis"].astype(str).str.strip().eq("").any():
        errors.append("clusters.csv: есть пустые hypothesis")

    # --- top_nodes.csv ----------------------------------------------------------
    if len(tn) < TOP_NODES_MIN_ROWS:
        errors.append(f"top_nodes.csv: {len(tn)} строк, требуется >= {TOP_NODES_MIN_ROWS}")

    if not set(tn.gid).issubset(set(nr.gid)):
        errors.append("top_nodes.csv: gid отсутствует в nodes_roles.csv")
    elif nr.gid.is_unique and tn.gid.is_unique:
        reference = nr.set_index("gid").loc[tn.gid]
        for column in ("role", "priority_score", "role_detail", "role_base", "is_truncated"):
            if column in tn and column in reference:
                if not tn[column].reset_index(drop=True).eq(reference[column].reset_index(drop=True)).all():
                    errors.append(f"top_nodes.csv: {column} не совпадает с nodes_roles.csv")

    if not tn.why.astype(str).str.contains(r"\d").all():
        errors.append("top_nodes.csv: why должен содержать числовое объяснение")

    if "priority_score" in tn.columns:
        if not (pd.to_numeric(tn["priority_score"], errors="coerce").diff().dropna() <= 1e-9).all():
            errors.append("top_nodes.csv: не отсортирован по priority_score по убыванию")

    if "rank" in tn.columns:
        expected_rank = list(range(1, len(tn) + 1))
        if tn["rank"].tolist() != expected_rank:
            errors.append("top_nodes.csv: rank не идёт подряд 1..N")

    return errors


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
    print("OK: локальная проверка строгой схемы пройдена")


if __name__ == "__main__":
    main()
