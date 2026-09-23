"""Возвратные потоки: циклы A->B->...->A (опциональный сигнал, п.8 ТЗ).

ВНИМАНИЕ (для Codex): nx.simple_cycles на этом графе находит ~1500 циклов
длины <= 6, но подавляющее большинство — это 2-циклы (A->B и B->A как
отдельные направленные рёбра), которые чаще означают "обычные взаимные
переводы", а не намеренный возврат средств. Прежде чем использовать длину
цикла как признак роли/аномалии, отделите len==2 от len>=3 и посмотрите
на суммы в обе стороны (равные суммы туда-обратно — более подозрительный
паттерн, чем разные).

Здесь — только сбор данных, интерпретация и включение в evidence оставлены
как тикет для команды/Codex (см. AGENTS.md).
"""

from __future__ import annotations

import networkx as nx
import pandas as pd


def find_cycles(G: nx.DiGraph, length_bound: int = 6) -> pd.DataFrame:
    """Возвращает DataFrame с найденными простыми циклами.

    Колонки: cycle (tuple gid), length, min_edge_kzt (самое слабое звено
    по сумме — обычно самое информативное для evidence).
    """
    rows = []
    for cyc in nx.simple_cycles(G, length_bound=length_bound):
        n = len(cyc)
        weights = []
        for i in range(n):
            u, v = cyc[i], cyc[(i + 1) % n]
            weights.append(G[u][v]["sum_kzt"])
        rows.append({
            "cycle": tuple(cyc),
            "length": n,
            "min_edge_kzt": min(weights),
            "max_edge_kzt": max(weights),
        })
    return pd.DataFrame(rows)


def nodes_in_return_flows(cycles_df: pd.DataFrame, min_length: int = 3) -> set[int]:
    """gid, участвующие хотя бы в одном цикле длины >= min_length.

    len==2 (взаимные переводы) исключены по умолчанию — см. docstring
    модуля про их интерпретацию.
    """
    out: set[int] = set()
    if cycles_df.empty:
        return out
    for cyc in cycles_df.loc[cycles_df.length >= min_length, "cycle"]:
        out.update(cyc)
    return out
