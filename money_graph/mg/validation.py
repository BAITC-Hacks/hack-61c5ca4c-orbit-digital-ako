"""Input contract for an analyst-selected, four-hop transaction export."""

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = {
    "nodes.parquet": {"gid", "depth", "is_seed"},
    "edges.parquet": {"src", "dst", "sum_kzt", "n_tx", "depth"},
    "transactions.parquet": {"src", "dst", "date", "sum_kzt"},
}


class InputError(ValueError):
    pass


def validate_data(data_dir: Path, min_tx_kzt: int = 0) -> dict:
    tables = {}
    for name, columns in REQUIRED.items():
        path = data_dir / name
        if not path.is_file():
            raise InputError(f"Не найден {name}")
        try:
            table = pd.read_parquet(path)
        except Exception as exc:
            raise InputError(f"Не удалось прочитать {name}: {exc}") from exc
        missing = columns - set(table.columns)
        if missing:
            raise InputError(f"{name}: отсутствуют колонки {', '.join(sorted(missing))}")
        if table.empty or table[list(columns)].isna().any().any():
            raise InputError(f"{name}: пустой файл или пропуски в обязательных колонках")
        tables[name] = table

    nodes, edges, tx = (tables[name] for name in REQUIRED)
    for name, frame, fields in (
        ("nodes.parquet", nodes, ["gid", "depth"]),
        ("edges.parquet", edges, ["src", "dst", "n_tx", "depth"]),
        ("transactions.parquet", tx, ["src", "dst"]),
    ):
        for field in fields:
            if not pd.api.types.is_integer_dtype(frame[field]):
                raise InputError(f"{name}: {field} должен быть целым числом")
    if not pd.api.types.is_bool_dtype(nodes.is_seed):
        raise InputError("nodes.parquet: is_seed должен быть bool")
    if nodes.gid.duplicated().any() or edges.duplicated(["src", "dst"]).any():
        raise InputError("gid узлов и пары src/dst рёбер должны быть уникальными")
    if not nodes.depth.between(0, 4).all() or not edges.depth.between(1, 4).all():
        raise InputError("Ожидается выгрузка с глубиной обхода 0–4")
    if not nodes.is_seed.any() or (nodes.loc[nodes.is_seed, "depth"] != 0).any():
        raise InputError("Нужен хотя бы один seed с depth=0")
    gids = set(nodes.gid)
    if not set(edges.src).issubset(gids) or not set(edges.dst).issubset(gids):
        raise InputError("Рёбра ссылаются на отсутствующие gid")
    if not set(tx.src).issubset(gids) or not set(tx.dst).issubset(gids):
        raise InputError("Транзакции ссылаются на отсутствующие gid")
    for name, frame in (("edges.parquet", edges), ("transactions.parquet", tx)):
        amounts = pd.to_numeric(frame.sum_kzt, errors="coerce")
        if not np.isfinite(amounts).all() or (amounts <= 0).any():
            raise InputError(f"{name}: суммы должны быть положительными конечными числами")
    if (tx.sum_kzt < min_tx_kzt).any():
        raise InputError("transactions.parquet: есть суммы ниже указанного порога отбора")
    if (edges.n_tx <= 0).any():
        raise InputError("edges.parquet: n_tx должен быть положительным")
    dates = pd.to_datetime(tx.date, errors="coerce")
    if dates.isna().any():
        raise InputError("transactions.parquet: некорректные даты")
    grouped = tx.groupby(["src", "dst"]).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size"))
    aggregates = edges.set_index(["src", "dst"])[["sum_kzt", "n_tx"]]
    if not grouped.index.equals(aggregates.sort_index().index):
        raise InputError("Пары src/dst в edges и transactions не совпадают")
    aggregates = aggregates.loc[grouped.index]
    if not np.allclose(grouped.sum_kzt, aggregates.sum_kzt, rtol=1e-6, atol=0.01):
        raise InputError("sum_kzt в edges не совпадает с суммой transactions")
    if not (grouped.n_tx == aggregates.n_tx).all():
        raise InputError("n_tx в edges не совпадает с числом transactions")
    return {
        "nodes": len(nodes), "edges": len(edges), "transactions": len(tx),
        "seeds": int(nodes.is_seed.sum()),
        "period_start": dates.min().date().isoformat(),
        "period_end": dates.max().date().isoformat(),
        "max_depth": int(nodes.depth.max()),
    }
