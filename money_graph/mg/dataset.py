"""Canonical, string-ID dataset shared by CLI and HTTP adapters."""
from dataclasses import dataclass, asdict
from collections import deque
import pandas as pd
import networkx as nx


@dataclass
class DatasetProfile:
    period_start: str | None
    period_end: str | None
    period_label: str
    currency: str
    collection_threshold: float | None
    max_depth: int | None
    has_dates: bool
    has_seeds: bool
    has_depth: bool
    n_nodes: int
    n_edges: int
    n_tx: int
    total_amount: float
    depth_computed: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class Dataset:
    nodes: pd.DataFrame
    edges: pd.DataFrame
    transactions: pd.DataFrame
    profile: DatasetProfile

    @classmethod
    def normalize(cls, transactions=None, edges=None, nodes=None, seeds=(), settings=None):
        settings = settings or {}
        tx = transactions.copy() if transactions is not None else pd.DataFrame(columns=['src', 'dst', 'amount', 'date'])
        e = edges.copy() if edges is not None else None
        for frame in (tx, e):
            if frame is not None:
                frame.rename(columns={'sum_kzt': 'amount'}, inplace=True)
                for c in ('src', 'dst'):
                    frame[c] = frame[c].astype('string').str.strip()
        if 'date' not in tx:
            tx['date'] = pd.NaT
        tx['date'] = pd.to_datetime(tx.date, errors='coerce', format='mixed', utc=True).dt.tz_localize(None)
        if len(tx):
            aggregated = tx.groupby(['src', 'dst'], sort=True).agg(amount=('amount', 'sum'), n_tx=('amount', 'size')).reset_index()
            # Keep declared edge order for reproducible Louvain / legacy tie ordering.
            if e is not None and not e.duplicated(['src', 'dst']).any() and set(zip(e.src, e.dst)) == set(zip(aggregated.src, aggregated.dst)):
                e = e[['src', 'dst']].merge(aggregated, on=['src', 'dst'], sort=False)
            else:
                e = aggregated
        if e is None or e.empty:
            raise ValueError('Нужна непустая таблица транзакций или рёбер')
        if 'n_tx' not in e:
            e['n_tx'] = 1
        e['amount'] = e.amount.astype(float)
        e['n_tx'] = e.n_tx.astype(int)
        n = nodes.copy().rename(columns={'gid': 'id'}) if nodes is not None else pd.DataFrame({'id': pd.unique(e[['src', 'dst']].values.ravel())})
        n['id'] = n.id.astype('string').str.strip()
        if n.id.duplicated().any() or n.id.isna().any() or n.id.eq('').any():
            raise ValueError('Идентификаторы узлов должны быть непустыми и уникальными')
        missing = set(e.src) | set(e.dst) | set(map(str, seeds))
        missing -= set(n.id)
        if missing:
            n = pd.concat([n, pd.DataFrame({'id': sorted(missing)})], ignore_index=True)
        if 'is_seed' not in n:
            n['is_seed'] = False
        n['is_seed'] = n.is_seed.fillna(False).astype(str).str.lower().isin(['true', '1', 'yes', 'да']) | n.id.isin(set(map(str, seeds)))
        computed = False
        if 'depth' not in n or n.depth.isna().all():
            depths = {}
            if n.is_seed.any():
                g = nx.DiGraph()
                g.add_edges_from(zip(e.src, e.dst))
                depths = {s: 0 for s in n.loc[n.is_seed, 'id']}
                queue = deque(depths)
                while queue:
                    u = queue.popleft()
                    for v in g.successors(u) if u in g else ():
                        if v not in depths:
                            depths[v] = depths[u] + 1
                            queue.append(v)
                computed = True
            n['depth'] = n.id.map(depths).astype(float)
        else:
            n['depth'] = pd.to_numeric(n.depth, errors='coerce')
        dates = tx.date.dropna()
        start, end = (dates.min().date().isoformat(), dates.max().date().isoformat()) if len(dates) else (None, None)
        profile = DatasetProfile(start, end, f'{start} — {end}' if start else '—', settings['currency'], settings.get('collection_threshold'), settings.get('max_depth'), bool(len(dates)), bool(n.is_seed.any()), bool(n.depth.notna().any()), len(n), len(e), len(tx) if len(tx) else int(e.n_tx.sum()), float(e.amount.sum()), computed)
        return cls(n.reset_index(drop=True), e.reset_index(drop=True), tx.reset_index(drop=True), profile)

    def legacy_tables(self):
        return (self.edges.rename(columns={'amount': 'sum_kzt'}), self.nodes.rename(columns={'id': 'gid'}), self.transactions.rename(columns={'amount': 'sum_kzt'}))
