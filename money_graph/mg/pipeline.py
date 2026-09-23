"""Single analytical entry point. No HTTP or input/output file operations."""
from dataclasses import dataclass
import time
import numpy as np
import pandas as pd
from .dataset import Dataset
from .features import build_graph, compute_features
from .taint import TaintModel
from .cutoff import estimate_onward
from .roles import assign_roles
from .clusters import cluster, cluster_table
from .quality import capabilities

@dataclass
class Results:
    nodes: pd.DataFrame
    clusters: pd.DataFrame
    top: pd.DataFrame
    requests: pd.DataFrame
    resilience: pd.DataFrame
    summary: dict
    config: dict

def pct(s):
    return s.rank(pct=True, method='average').fillna(0)

def priority(df, cfg, has_seeds):
    w = dict(cfg['priority_weights'])
    if not has_seeds:
        w.update(tainted_in=0, seed_sources=0)
    total = sum(w.values())
    w = {k: v / total for k, v in w.items()} if total else {k: 0 for k in w}
    columns = {'tainted_in': 'tainted_in_kzt', 'block_impact': 'block_impact', 'betweenness': 'betweenness', 'seed_sources': 'seed_sources', 'turnover': 'turnover'}
    raw = w['role'] * df.role.map(cfg['role_weight'])
    for key, col in columns.items():
        raw += w[key] * pct(df[col].where(df[col] > 0))
    return (raw / raw.max()).fillna(0).round(4) if raw.max() > 0 else raw * 0

def run_pipeline(dataset: Dataset, config: dict, progress_cb=None) -> Results:
    t0 = time.perf_counter()
    progress = progress_cb or (lambda stage, percent: None)
    p = dataset.profile
    cfg = {**config, 'max_depth': p.max_depth, 'period_end': p.period_end, 'currency': p.currency, 'collection_threshold': p.collection_threshold}
    edges, nodes, tx = dataset.legacy_tables()
    progress('features', 25)
    g = build_graph(edges, nodes)
    df = compute_features(g, edges, nodes, tx, cfg)
    progress('taint', 42)
    tm = TaintModel(edges, df, cfg['taint_iterations'])
    taint, incoming, total = tm.propagate()
    df['taint_share'], df['tainted_in_kzt'] = taint, incoming
    progress('blocking', 50)
    candidates = None
    if len(df) > 20000:
        preliminary = pct(df.turnover) + pct(df.betweenness) + pct(df.in_deg) + pct(df.tainted_in_kzt)
        candidates = df.index.get_indexer(preliminary.nlargest(cfg.get('block_top_k', 1000)).index)
    df['block_impact'] = tm.block_impact(candidates)
    progress('cutoff', 62)
    df['p_onward'], cutoff = estimate_onward(df, p.period_end, p.max_depth)
    progress('roles', 68)
    df = df.join(assign_roles(df, cfg))
    df['priority_score'] = priority(df, cfg, p.has_seeds)
    df['role_base'] = df.role.replace({'truncated': 'peripheral'})
    progress('clusters', 78)
    labels = cluster(g, cfg)
    df['cluster_id'] = labels
    clusters = cluster_table(edges, df, df[['role']], labels, df.priority_score, cfg)
    order = df.sort_values('priority_score', ascending=False).index.tolist()
    top = df.loc[order[:cfg['top_n']]].reset_index()[['gid', 'role', 'priority_score', 'evidence']].rename(columns={'evidence': 'why'})
    top.insert(0, 'rank', range(1, len(top)+1))
    req = []
    truncated = df[df.role.eq('truncated')].assign(weight=lambda d: d.p_onward.fillna(0) * d.tainted_in_kzt).sort_values('weight', ascending=False)
    for gid, r in truncated.iterrows():
        req.append((gid, 'next_hop_outgoing', float(r.weight), f'Запросить исходящие следующего хопа; глубина {p.max_depth}'))
    for gid, r in df[df.role.isin(['coordinator', 'consolidator'])].iterrows():
        req.append((gid, 'incoming_external', float(r.tainted_in_kzt), f'Запросить внешние входящие; приоритет {r.priority_score:.2f}'))
    for gid in df[df.is_seed & df.out_deg.eq(0)].index:
        req.append((gid, 'seed_no_outgoing', 0., 'Проверить полноту выгрузки для seed без исходящих'))
    requests = pd.DataFrame(req, columns=['gid', 'request_type', 'weight', 'reason'])
    progress('resilience', 87)
    res = tm.resilience_curve(order, cfg['resilience_max_n'], n_random=20 if len(df) <= 20000 else 5)
    caps = capabilities(dataset)
    caps.append({'key': 'cutoff_model', 'enabled': bool(cutoff.get('enabled')), 'message': 'Модель обрезки доступна' if cutoff.get('enabled') else 'Недостаточно данных для оценки обрезки'})
    caps.append({'key': 'block_all', 'enabled': candidates is None, 'message': 'Блокировка рассчитана для всех узлов' if candidates is None else f'Блокировка рассчитана для {len(candidates)} кандидатов; остальные значения не оценены'})
    if len(df) > 5000:
        caps.append({'key': 'approximate_betweenness', 'enabled': True, 'message': f'Посредничество оценено по {cfg.get("betweenness_samples", 500)} источникам'})
    if len(df) > 200000:
        caps.append({'key': 'large_graph', 'enabled': False, 'message': 'Louvain на крупном графе может потребовать значительное время'})
    summary = {'nodes': len(df), 'edges': len(edges), 'transactions': p.n_tx, 'period_start': p.period_start, 'period_end': p.period_end, 'max_depth': p.max_depth, 'seeds': int(df.is_seed.sum()), 'min_tx_kzt': p.collection_threshold, 'currency': p.currency, 'roles': df.role.value_counts().to_dict(), 'clusters': len(clusters), 'multiseed_clusters': int(clusters.n_seed.gt(1).sum()), 'tainted_flow_kzt': round(float(total)) if p.has_seeds else None, 'total_amount': p.total_amount, 'flow_basis': 'tainted' if p.has_seeds else 'total', 'cutoff_model': cutoff, 'runtime_sec': round(time.perf_counter()-t0, 2), 'profile': p.to_dict(), 'capabilities': caps, 'resilience': res.to_dict('records')}
    k = min(20, len(res)-1)
    summary['insight'] = {'n': k, 'removed_share': round(1-float(res.iloc[k].tainted_flow_left), 4), 'multiseed_clusters': summary['multiseed_clusters']}
    progress('exports', 96)
    return Results(df, clusters, top, requests, res, summary, cfg)
