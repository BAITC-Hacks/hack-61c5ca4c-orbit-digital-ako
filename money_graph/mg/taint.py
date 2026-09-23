"""«Меченые деньги» (haircut-метод) и симулятор блокировки.

Seed-клиенту приписывается доля 1.0 «меченых» денег. Каждый узел передаёт дальше ту же
долю меченых денег, какая была среди полученного им (пропорционально суммам рёбер).
Итог по узлу: сколько тенге из полученного прослеживаются к seed-клиентам.
"""
import networkx as nx
import numpy as np
import pandas as pd


class TaintModel:
    def __init__(self, edges: pd.DataFrame, df: pd.DataFrame, iterations: int):
        self.gids = df.index.to_numpy()
        self.idx = {g: i for i, g in enumerate(self.gids)}
        self.src = edges.src.map(self.idx).to_numpy()
        self.dst = edges.dst.map(self.idx).to_numpy()
        self.w = edges.sum_kzt.to_numpy(dtype=float)
        self.seed = df.is_seed.to_numpy()
        self.n = len(self.gids)
        self.iters = iterations

    def propagate(self, removed: np.ndarray | None = None):
        w = self.w
        if removed is not None and removed.any():
            w = np.where(removed[self.src] | removed[self.dst], 0.0, w)
        taint = self.seed.astype(float)
        w_in = np.bincount(self.dst, weights=w, minlength=self.n)
        for _ in range(self.iters):
            t_in = np.bincount(self.dst, weights=w * taint[self.src], minlength=self.n)
            taint = np.divide(t_in, w_in, out=np.zeros(self.n), where=w_in > 0)
            taint[self.seed] = 1.0
            if removed is not None:
                taint[removed] = 0.0
        flow = w * taint[self.src]
        tainted_in = np.bincount(self.dst, weights=flow, minlength=self.n)
        return taint, tainted_in, flow.sum()

    def block_impact(self) -> np.ndarray:
        """Доля всего меченого потока, которая исчезает, если заблокировать один узел."""
        _, _, total = self.propagate()
        impact = np.zeros(self.n)
        if total <= 0:
            return impact
        removed = np.zeros(self.n, dtype=bool)
        for i in range(self.n):
            removed[i] = True
            _, _, t = self.propagate(removed)
            impact[i] = (total - t) / total
            removed[i] = False
        return impact

    def resilience_curve(self, order_gids, max_n: int, n_random: int = 20, rng_seed: int = 42):
        """Что происходит с сетью при блокировке топ-N по приоритету против N случайных узлов."""
        _, _, total = self.propagate()
        G = nx.Graph()
        G.add_edges_from(zip(self.src, self.dst))
        rng = np.random.default_rng(rng_seed)
        active = np.unique(np.r_[self.src, self.dst])

        def state(removed_idx, with_components=True):
            removed = np.zeros(self.n, dtype=bool)
            removed[list(removed_idx)] = True
            _, _, t = self.propagate(removed)
            if not with_components:
                return (t / total if total > 0 else 0.0), None, None
            H = G.subgraph([v for v in G if not removed[v]])
            comps = [len(c) for c in nx.connected_components(H)]
            return (t / total if total > 0 else 0.0), len(comps), max(comps) if comps else 0

        max_n = min(max_n, max(0, len(active) - 1))
        order = [self.idx[g] for g in order_gids[:max_n]]
        rows = []
        for k in range(0, max_n + 1):
            share, n_comp, largest = state(order[:k])
            rnd = [state(rng.choice(active, size=k, replace=False), with_components=False)[0]
                   for _ in range(n_random)] if k else [share]
            rows.append({"n_blocked": k, "tainted_flow_left": round(share, 4),
                         "random_flow_left": round(float(np.mean(rnd)), 4),
                         "n_components": n_comp, "largest_component": largest})
        return pd.DataFrame(rows)
