"""Кластеры: Louvain на НЕориентированной проекции (вес = сумма в обе стороны).

Направление здесь сознательно отброшено: для группировки важна плотность связей,
а направление денег учитывается в ролях. Узлы без рёбер — отдельный кластер 0.
"""
import networkx as nx
import pandas as pd

from .roles import kzt


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


def _hypothesis(n, n_seed, roles: pd.Series, internal, in_kzt_total):
    rc = roles.value_counts()
    g = lambda r: int(rc.get(r, 0))
    trunc_share = g("truncated") / n
    core = g("coordinator") + g("consolidator")
    if n_seed and n == n_seed and internal == 0:
        return f"Seed-клиенты без переводов ≥5 000 KZT в выгрузке ({n}). Структуру по данным не видно; нужен запрос."
    parts = []
    if core and n_seed >= 2:
        parts.append(f"Контур сбора: {g('coordinator')} коорд. и {g('consolidator')} консолид. стягивают средства "
                     f"{n_seed} seed; кандидат в ядро группы")
    elif g("distributor"):
        parts.append(f"Контур раздачи: {g('distributor')} распределит. рассылают средства по {n} счетам")
    elif core:
        parts.append(f"Точка сбора вне seed-ядра: {core} консолид./коорд.")
    if g("transit") >= 3:
        parts.append(f"{g('transit')} транзитных счетов — признаки цепочек проводки")
    if g("terminal") / n >= 0.3:
        parts.append(f"{g('terminal') / n:.0%} счетов — конечные получатели (деньги оседают)")
    if trunc_share >= 0.4:
        parts.append(f"{trunc_share:.0%} узлов обрезаны 4-м хопом — картина неполная, нужен след. хоп")
    if not parts:
        parts.append("Периферийная группа без выраженных ролей")
    return ("; ".join(parts) + f". Внутр. оборот {kzt(internal)}.")[:300]


def cluster_table(edges, df, roles, labels, priority) -> pd.DataFrame:
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
            "hypothesis": _hypothesis(n, n_seed, roles.loc[idx, "role"], s_int, df.loc[idx, "in_kzt"].sum()),
            "n_consolidator": int((roles.loc[idx, "role"] == "consolidator").sum()),
            "n_coordinator": int((roles.loc[idx, "role"] == "coordinator").sum()),
            "n_truncated": int((roles.loc[idx, "role"] == "truncated").sum()),
        })
    return pd.DataFrame(rows).sort_values("cluster_id")

