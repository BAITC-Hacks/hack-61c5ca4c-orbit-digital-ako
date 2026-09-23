"""Chronological, available-balance-capped marked flow and removal scenarios.

Dates have day precision: debit batches use only earlier-day credits, then all
credits are booked together. Incoming money is proportionally mixed (haircut).
Uncovered debits are funded by unknown/unmarked starting or external money;
they never borrow future receipts. Seed outflows are marked by definition,
including fresh seed-origin injections. This is an accounting scenario, not
proof of a specific money trail. Total flow counts money once per transfer,
so a chronological cycle can count the same money on more than one edge.
"""
import networkx as nx
import numpy as np
import pandas as pd


class TaintModel:
    def __init__(self, edges: pd.DataFrame, df: pd.DataFrame, iterations=None, *, tx=None):
        # Keep the former positional argument for callers; convergence iterations
        # have no meaning in a chronological model and are deliberately unused.
        if tx is None:
            raise ValueError("Chronological taint requires transactions (tx=...), including dates")
        self.edges = edges.reset_index(drop=True).copy()
        self.gids = df.index.to_numpy()
        self.idx = {g: i for i, g in enumerate(self.gids)}
        self.src = edges.src.map(self.idx).to_numpy()
        self.dst = edges.dst.map(self.idx).to_numpy()
        self.w = edges.sum_kzt.to_numpy(dtype=float)
        self.seed = df.is_seed.to_numpy(dtype=bool)
        self.n = len(self.gids)
        edge_ids = {(row.src, row.dst): i for i, row in enumerate(self.edges.itertuples(index=False))}
        dated = tx.assign(day=pd.to_datetime(tx.date).dt.normalize()).sort_values("day", kind="stable")
        self.days = []
        for _, part in dated.groupby("day", sort=False):
            self.days.append((part.src.map(self.idx).to_numpy(dtype=int),
                              part.dst.map(self.idx).to_numpy(dtype=int),
                              part.sum_kzt.to_numpy(dtype=float),
                              np.array([edge_ids[(s, d)] for s, d in zip(part.src, part.dst)])))
        self._baseline = None

    def _simulate(self, removed=None, trace=False):
        removed = np.zeros(self.n, dtype=bool) if removed is None else np.asarray(removed, dtype=bool)
        if removed.shape != (self.n,):
            raise ValueError("removed must contain one flag per node")
        balance, marked = np.zeros(self.n), np.zeros(self.n)
        received, tainted_in = np.zeros(self.n), np.zeros(self.n)
        edge_flow = np.zeros(len(self.edges)) if trace else None
        for src, dst, amount, edge_idx in self.days:
            w = np.where(removed[src] | removed[dst], 0.0, amount)
            outgoing = np.bincount(src, weights=w, minlength=self.n)
            # All same-day outgoing transfers share the prior available marked
            # balance proportionally, even if their total exceeds that balance.
            denominator = np.maximum(balance, outgoing)
            fraction = np.divide(marked, denominator, out=np.zeros(self.n), where=denominator > 0)
            fraction[self.seed & ~removed] = 1.0
            flow = w * np.clip(fraction[src], 0.0, 1.0)
            spent_share = np.divide(np.minimum(balance, outgoing), balance,
                                    out=np.zeros(self.n), where=balance > 0)
            marked *= 1.0 - spent_share
            balance = np.maximum(0.0, balance - outgoing)
            credited = np.bincount(dst, weights=w, minlength=self.n)
            credited_marked = np.bincount(dst, weights=flow, minlength=self.n)
            balance += credited
            marked += credited_marked
            received += credited
            tainted_in += credited_marked
            if trace:
                edge_flow += np.bincount(edge_idx, weights=flow, minlength=len(self.edges))
        share = np.divide(tainted_in, received, out=np.zeros(self.n), where=received > 0)
        return share, tainted_in, float(tainted_in.sum()), edge_flow

    def propagate(self, removed=None):
        if removed is None:
            if self._baseline is None:
                self._baseline = self._simulate(trace=True)
            share, received, total, _ = self._baseline
        else:
            share, received, total, _ = self._simulate(removed)
        return share.copy(), received.copy(), total

    def edge_trace(self):
        """Per-edge amount supported by the chronological accounting assumptions."""
        self.propagate()
        result = self.edges[["src", "dst", "sum_kzt", "n_tx"]].copy()
        result["tainted_kzt"] = self._baseline[3]
        result["taint_share"] = np.divide(result.tainted_kzt, result.sum_kzt,
                                          out=np.zeros(len(result)), where=result.sum_kzt > 0)
        return result

    def block_impact(self) -> np.ndarray:
        """Relative marked transfer volume change after removing one node.

        This counterfactual reruns the accounting model; a negative value is
        possible when removal reduces unmarked dilution elsewhere. It is not
        a prediction of prevented loss or participants' adaptive behaviour.
        """
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
