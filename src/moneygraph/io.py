"""Загрузка parquet-файлов и проверка их консистентности.

ВАЖНО про gid: значения ~1e17, что больше 2**53 (~9.007e15) — предела
точного представления целых чисел в float64 / JS Number. Держим gid как
pandas int64 на всём пайплайне. Единственное место, где это может
незаметно сломаться — merge с последующим fillna (float64-каст) и любой
вывод в JSON/HTML для вьюера (см. app/viz.py — там gid всегда str()).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")

    for df, cols in ((edges, ("src", "dst")), (nodes, ("gid",)), (tx, ("src", "dst"))):
        for c in cols:
            df[c] = df[c].astype("int64")

    tx["date"] = pd.to_datetime(tx["date"])
    return edges, nodes, tx


def sanity_check(edges: pd.DataFrame, nodes: pd.DataFrame, tx: pd.DataFrame) -> set[int]:
    """Проверки, которые должны пройти до построения модели.

    Возвращает множество gid без единого ребра ("orphans") — они всё
    равно обязаны попасть в nodes_roles.csv (см. ТЗ п.7, must-have #2).
    """
    print("=" * 64)
    print("ПРОВЕРКА ДАННЫХ")
    print("=" * 64)
    print(f"  узлов в nodes.parquet : {len(nodes):>6}")
    print(f"  рёбер                 : {len(edges):>6}")
    print(f"  транзакций            : {len(tx):>6}")
    print(f"  seed-клиентов         : {int(nodes.is_seed.sum()):>6}")
    print(f"  оборот, KZT           : {edges.sum_kzt.sum():>14,.0f}")
    print(f"  период                : {tx.date.min().date()} - {tx.date.max().date()}")

    agg = tx.groupby(["src", "dst"]).agg(s=("sum_kzt", "sum"), c=("sum_kzt", "size")).reset_index()
    m = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    assert (m._merge == "both").all(), "edges и transactions не сходятся по парам"
    print("  edges == transactions : OK")

    in_edges = set(edges.src) | set(edges.dst)
    orphans = set(nodes.gid) - in_edges
    print(f"\n  {len(orphans)} узлов нет ни в одном ребре "
          f"(из них seed: {len(orphans & set(nodes[nodes.is_seed].gid))})")
    print("  -> они всё равно попадут в nodes_roles.csv (роль будет 'peripheral')")
    print("=" * 64, "\n")
    return orphans
