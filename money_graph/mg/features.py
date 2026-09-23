"""Загрузка данных и метрики узлов: структура, суммы, время, связь с seed."""
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


def load(data_dir: Path):
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    return edges, nodes, tx


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(nodes.gid)  # 19 seed без рёбер тоже должны быть в графе
    for r in edges.itertuples(index=False):
        G.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx))
    return G


def temporal_features(tx: pd.DataFrame, lag_days: int) -> pd.DataFrame:
    """Сквозной транзит: какая доля исходящих сумм ушла в течение lag_days после входящего."""
    inc = tx[["dst", "date", "src"]].rename(columns={"dst": "gid", "date": "in_date", "src": "payer"})
    out = tx[["src", "date", "sum_kzt"]].rename(columns={"src": "gid", "date": "out_date"})
    out = out.reset_index().rename(columns={"index": "tx_id"})

    # для каждой исходящей транзакции — ближайший предшествующий входящий перевод
    inc_s = inc.sort_values("in_date")
    out_s = out.sort_values("out_date")
    m = pd.merge_asof(out_s, inc_s[["gid", "in_date"]], left_on="out_date", right_on="in_date",
                      by="gid", direction="backward")
    m["lag"] = (m.out_date - m.in_date).dt.days
    m["fast"] = m.lag.le(lag_days)

    f = m.groupby("gid").apply(
        lambda d: pd.Series({
            "fast_share": d.loc[d.fast, "sum_kzt"].sum() / d.sum_kzt.sum(),
            "median_lag": d.lag.median(),
        }), include_groups=False)

    # синхронные поступления: сколько разных плательщиков прислали в один день
    sync = inc.groupby(["gid", "in_date"]).payer.nunique().groupby("gid").max().rename("sync_payers_max")
    first_last = inc.groupby("gid").in_date.agg(["min", "max"]).rename(columns={"min": "first_in", "max": "last_in"})
    return f.join(sync, how="outer").join(first_last, how="outer")


def compute_features(G, edges, nodes, tx, cfg) -> pd.DataFrame:
    seeds = set(nodes.loc[nodes.is_seed, "gid"])
    df = nodes[["gid", "depth", "is_seed"]].set_index("gid")

    df["in_deg"] = pd.Series(dict(G.in_degree()))
    df["out_deg"] = pd.Series(dict(G.out_degree()))
    df["in_kzt"] = pd.Series(dict(G.in_degree(weight="sum_kzt")))
    df["out_kzt"] = pd.Series(dict(G.out_degree(weight="sum_kzt")))
    df["in_tx"] = pd.Series(dict(G.in_degree(weight="n_tx")))
    df["out_tx"] = pd.Series(dict(G.out_degree(weight="n_tx")))
    df["pass_through"] = df.out_kzt / df.in_kzt.replace(0, np.nan)
    df["truncated_by_depth"] = (df.depth == cfg.get("max_depth", 4)) & (df.out_deg == 0)

    # сколько разных seed-клиентов прямо платили узлу / косвенно достают до него
    df["seed_payers"] = edges[edges.src.isin(seeds)].groupby("dst").src.nunique()
    anc = {v: 0 for v in G}
    for s in seeds:
        for d in nx.descendants(G, s):
            anc[d] += 1
    df["seed_sources"] = pd.Series(anc)
    # возвратный поток: узел переводит деньги обратно seed-клиенту
    df["pays_to_seed"] = edges[edges.dst.isin(seeds)].groupby("src").dst.nunique()

    # посредничество (направленное, без весов — «сколько кратчайших маршрутов идёт через узел»)
    bc = nx.betweenness_centrality(G, normalized=True)
    df["betweenness"] = pd.Series(bc)
    try:
        hubs, auth = nx.hits(G, max_iter=500)
    except (nx.PowerIterationFailedConvergence, ValueError):
        hubs, auth = ({v: 0.0 for v in G}, {v: 0.0 for v in G})
    df["hub"] = pd.Series(hubs)
    df["authority"] = pd.Series(auth)

    # короткие циклы (≤4 звена): деньги возвращаются к отправителю
    cyc_count = {}
    for c in nx.simple_cycles(G, length_bound=4):
        for v in c:
            cyc_count[v] = cyc_count.get(v, 0) + 1
    df["cycles_le4"] = pd.Series(cyc_count)

    wcc = {v: i for i, comp in enumerate(sorted(nx.weakly_connected_components(G), key=len, reverse=True))
           for v in comp}
    df["component"] = pd.Series(wcc)

    df = df.join(temporal_features(tx, cfg["fast_lag_days"]))
    fill0 = ["in_deg", "out_deg", "in_kzt", "out_kzt", "in_tx", "out_tx", "seed_payers", "seed_sources",
             "pays_to_seed", "cycles_le4", "sync_payers_max"]
    df[fill0] = df[fill0].fillna(0)
    for c in ["in_deg", "out_deg", "in_tx", "out_tx", "seed_payers", "seed_sources", "pays_to_seed",
              "cycles_le4", "sync_payers_max"]:
        df[c] = df[c].astype(int)
    df["turnover"] = df.in_kzt + df.out_kzt
    return df
