"""Bounded best-first search, ranked by share of observed (or traced) flow."""
import heapq
import math
import networkx as nx

def money_paths(edges, source, target, k=5, taint=None, max_hops=12, budget=20000):
    if source == target:
        return {'paths': [], 'limited': False, 'message': 'Выберите разные узлы', 'basis': 'tainted_share' if taint is not None else 'amount_share'}
    g = nx.DiGraph()
    totals = edges.groupby('src').amount.sum()
    for e in edges.itertuples():
        traced = e.amount * (taint.get(e.src, 0) if taint is not None else 1)
        if traced > 0:
            g.add_edge(e.src, e.dst, amount=e.amount, traced=traced, cost=-math.log(max(1e-12, traced / totals[e.src])))
    if source not in g or target not in g:
        return {'paths': [], 'limited': False, 'basis': 'tainted_share' if taint is not None else 'amount_share'}
    heap = [(0., [source], float('inf'))]
    found, expanded = [], 0
    while heap and len(found) < k and expanded < budget:
        cost, path, bottleneck = heapq.heappop(heap)
        if path[-1] == target:
            found.append({'nodes': path, 'strength': math.exp(-cost), 'bottleneck_amount': bottleneck})
            continue
        expanded += 1
        if len(path) > max_hops:
            continue
        for nxt, data in g[path[-1]].items():
            if nxt not in path:
                heapq.heappush(heap, (cost+data['cost'], path+[nxt], min(bottleneck, data['traced'])))
        if len(heap) > budget:
            heap = heapq.nsmallest(budget//2, heap)
            heapq.heapify(heap)
    return {'paths': found, 'limited': expanded >= budget, 'max_hops': max_hops, 'basis': 'tainted_share' if taint is not None else 'amount_share'}
