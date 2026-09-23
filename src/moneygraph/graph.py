"""Сборка направленного взвешенного графа переводов."""

from __future__ import annotations

import networkx as nx
import pandas as pd


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame) -> nx.DiGraph:
    """Направленный граф. sum_kzt — вес ребра, n_tx — число переводов.

    Добавляем ВСЕ узлы из nodes.parquet явно (G.add_nodes_from), иначе
    19 orphan-узлов без единого ребра выпадут из графа и, соответственно,
    из всех метрик и из Louvain-кластеризации.
    """
    G = nx.DiGraph()
    G.add_nodes_from(nodes.gid.tolist())
    for r in edges.itertuples(index=False):
        G.add_edge(int(r.src), int(r.dst), sum_kzt=float(r.sum_kzt),
                   n_tx=int(r.n_tx), depth=int(r.depth))
    return G


def undirected_weighted_projection(G: nx.DiGraph) -> nx.Graph:
    """Неориентированная проекция для Louvain.

    G.to_undirected() без merge-стратегии сохраняет атрибуты только ОДНОГО
    направления у взаимных пар (A->B и B->A), т.е. часть sum_kzt теряется.
    Здесь суммы обоих направлений явно складываются в вес ребра.
    """
    UG = nx.Graph()
    UG.add_nodes_from(G.nodes())
    for u, v, data in G.edges(data=True):
        w = data.get("sum_kzt", 0.0)
        if UG.has_edge(u, v):
            UG[u][v]["sum_kzt"] += w
            UG[u][v]["n_tx"] += data.get("n_tx", 0)
        else:
            UG.add_edge(u, v, sum_kzt=w, n_tx=data.get("n_tx", 0))
    return UG
