"""Метрики узлов: степени, обороты, центральности, охват от seed.

Отправная точка — те же базовые метрики, что в starter.py, плюс:
  * seed_reach       — от скольких РАЗНЫХ seed-клиентов есть направленный
                        путь до узла (структурный сигнал coordinator/
                        consolidator, отдельный от финансового in_deg);
  * betweenness       — считается НЕВЗВЕШЕННЫМ: networkx трактует "weight"
                        как расстояние, поэтому передача sum_kzt делает
                        переводы с большой суммой "длиннее" — это
                        противоположно тому, что нужно (см. starter README
                        ловушка #4 про направленность/веса).
  * hits hub/authority — hub ~ рассылает много (distributor-сигнал),
                        authority ~ получает от многих хабов
                        (consolidator-сигнал).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import networkx as nx


def compute_seed_reach(G: nx.DiGraph, seeds: set[int]) -> tuple[dict[int, int], dict[int, set[int]]]:
    """Для каждого узла — множество seed, от которых до него есть путь."""
    reach_seeds: dict[int, set[int]] = {n: set() for n in G.nodes()}
    for s in seeds:
        if s not in G:
            continue
        for n in nx.descendants(G, s):
            reach_seeds[n].add(s)
    reach_count = {n: len(v) for n, v in reach_seeds.items()}
    return reach_count, reach_seeds


def basic_features(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    in_kzt = dict(G.in_degree(weight="sum_kzt"))
    out_kzt = dict(G.out_degree(weight="sum_kzt"))
    in_tx = dict(G.in_degree(weight="n_tx"))
    out_tx = dict(G.out_degree(weight="n_tx"))

    pr = nx.pagerank(G, weight="sum_kzt")
    betweenness = nx.betweenness_centrality(G, weight=None, normalized=True)

    try:
        hubs, authority = nx.hits(G, max_iter=1000, normalized=True)
    except nx.PowerIterationFailedConvergence:
        hubs = {n: 0.0 for n in G.nodes()}
        authority = {n: 0.0 for n in G.nodes()}

    seeds = set(nodes.loc[nodes.is_seed, "gid"])
    seed_reach_count, seed_reach_set = compute_seed_reach(G, seeds)

    df = nodes[["gid", "depth", "is_seed"]].copy()
    df["in_deg"] = df.gid.map(in_deg).fillna(0).astype(int)
    df["out_deg"] = df.gid.map(out_deg).fillna(0).astype(int)
    df["in_kzt"] = df.gid.map(in_kzt).fillna(0.0)
    df["out_kzt"] = df.gid.map(out_kzt).fillna(0.0)
    df["in_tx"] = df.gid.map(in_tx).fillna(0).astype(int)
    df["out_tx"] = df.gid.map(out_tx).fillna(0).astype(int)
    df["pagerank"] = df.gid.map(pr).fillna(0.0)
    df["betweenness"] = df.gid.map(betweenness).fillna(0.0)
    df["hub_score"] = df.gid.map(hubs).fillna(0.0)
    df["authority_score"] = df.gid.map(authority).fillna(0.0)
    df["seed_reach"] = df.gid.map(seed_reach_count).fillna(0).astype(int)

    # pass_through = доля полученного, ушедшая дальше. НЕ используем для
    # seed-узлов при принятии решений о роли: у них in_kzt занижен, т.к.
    # граф собран ОТ них по исходящим — входящие переводы извне выборки
    # не видны (см. ТЗ п.6, "У seed-клиентов входящие суммы занижены").
    df["pass_through"] = np.where(
        df.in_kzt > 0, df.out_kzt / df.in_kzt.replace(0, np.nan), np.nan
    )

    # ЛОВУШКА КЕЙСА: depth==4 и out_deg==0 не значит "деньги осели" — это
    # может быть просто обрыв обхода на 4-м колене. depth<4 и out_deg==0
    # означает, что обход ДОСМОТРЕЛ этот узел и исходящих не нашёл — это
    # куда более надёжный сигнал терминальности. См. roles.py TERMINAL.
    df["truncated_by_depth"] = (df.depth == 4) & (df.out_deg == 0)

    df["seed_reach_list"] = df.gid.map(lambda g: sorted(seed_reach_set.get(g, set())))

    return df
