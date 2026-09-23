"""Кластеры: Louvain на НЕориентированной проекции (вес = сумма в обе стороны).

Направление здесь сознательно отброшено: для группировки важна плотность связей,
а направление денег учитывается в ролях. Узлы без рёбер — отдельный кластер 0.
"""
import networkx as nx
import pandas as pd

from .roles import kzt, templates


def cluster(G: nx.DiGraph, cfg: dict) -> pd.Series:
    U = nx.Graph()
    for u, v, d in G.edges(data=True):
        w = U[u][v]["weight"] + d["sum_kzt"] if U.has_edge(u, v) else d["sum_kzt"]
        U.add_edge(u, v, weight=w)
    comms = nx.community.louvain_communities(U, weight="weight", resolution=cfg["louvain_resolution"],
                                             seed=cfg["louvain_seed"])
    comms = sorted(comms, key=lambda c: (-len(c), min(c)))
    labels = {v: i + 1 for i, c in enumerate(comms) for v in c}
    return pd.Series({v: labels.get(v, 0) for v in G.nodes}, name="cluster_id")


def _hypothesis(n, n_seed, roles, internal, in_kzt_total, cfg):
    rc = roles.value_counts()
    return templates(cfg.get("language", "ru"))["cluster"].format(core=int(rc.get("coordinator", 0) + rc.get("consolidator", 0)), distributors=int(rc.get("distributor", 0)), transit=int(rc.get("transit", 0)), seeds=n_seed, truncated=int(rc.get("truncated", 0)), amount=f'{kzt(internal)} {cfg.get("currency", "")}')[:300]


def cluster_table(edges, df, roles, labels, priority, cfg=None) -> pd.DataFrame:
    e = edges.assign(cs=edges.src.map(labels), cd=edges.dst.map(labels))
    internal = e[e.cs == e.cd].groupby("cs").sum_kzt.sum()
    rows = []
    for cid, members in labels.groupby(labels):
        idx = members.index
        top = priority.loc[idx].sort_values(ascending=False).head(3).index
        n, n_seed = len(idx), int(df.loc[idx, "is_seed"].sum())
        s_int = float(internal.get(cid, 0.0))
        rows.append({
            "cluster_id": int(cid), "n_nodes": n, "n_seed": n_seed,
            "sum_kzt_internal": round(s_int, 2),
            "top_gids": ";".join(str(g) for g in top),
            "hypothesis": _hypothesis(n, n_seed, roles.loc[idx, "role"], s_int, df.loc[idx, "in_kzt"].sum(), cfg or {}),
            "n_consolidator": int((roles.loc[idx, "role"] == "consolidator").sum()),
            "n_coordinator": int((roles.loc[idx, "role"] == "coordinator").sum()),
            "n_truncated": int((roles.loc[idx, "role"] == "truncated").sum()),
        })
    return pd.DataFrame(rows).sort_values("cluster_id")
