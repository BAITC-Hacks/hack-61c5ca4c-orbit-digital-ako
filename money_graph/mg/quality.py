"""Explicit quality findings; never silently reinterpret refunds as transfers."""
import numpy as np
import networkx as nx

def clean_table(frame, kind):
    findings = []
    required = ['src', 'dst', 'amount'] if kind in ('edges', 'transactions') else ['id']
    missing = set(required) - set(frame)
    if missing:
        return frame, [{'level': 'error', 'code': 'columns', 'count': len(missing), 'message': 'Не сопоставлены: ' + ', '.join(sorted(missing))}]
    bad = frame[required].isna().any(axis=1)
    if 'amount' in frame:
        bad |= ~np.isfinite(frame.amount)
    if bad.any():
        findings.append({'level': 'error' if bad.mean() > .05 else 'warning', 'code': 'missing', 'count': int(bad.sum()), 'message': 'Строки с пропусками обязательных полей исключены'})
        frame = frame.loc[~bad].copy()
    if kind in ('edges', 'transactions'):
        for mask, code, message in [(frame.src.eq(frame.dst), 'loops', 'Переводы самому себе'), (frame.duplicated(), 'duplicates', 'Совпадающие строки; сохранены, проверьте источник'), (frame.amount.le(0), 'nonpositive', 'Нулевые и отрицательные суммы исключены; возвраты требуют отдельной интерпретации')]:
            if mask.any():
                findings.append({'level': 'warning', 'code': code, 'count': int(mask.sum()), 'message': message})
        frame = frame.loc[frame.amount.gt(0)].copy()
        if 'date' in frame and frame.date.isna().any():
            findings.append({'level': 'warning', 'code': 'dates', 'count': int(frame.date.isna().sum()), 'message': 'Пропуски дат: временные метрики используют только датированные строки'})
        if 'n_tx' in frame and (frame.n_tx.isna() | frame.n_tx.le(0) | frame.n_tx.mod(1).ne(0)).any():
            findings.append({'level': 'error', 'code': 'counts', 'count': 1, 'message': 'Количество переводов должно быть положительным целым числом'})
    if frame.empty:
        findings.append({'level': 'error', 'code': 'empty', 'count': 0, 'message': 'После очистки не осталось строк'})
    return frame, findings

def quality_report(dataset, findings=()):
    p = dataset.profile
    g = nx.Graph()
    g.add_nodes_from(dataset.nodes.id)
    g.add_edges_from(zip(dataset.edges.src, dataset.edges.dst))
    comps = sorted((len(c) for c in nx.connected_components(g)), reverse=True)
    findings = list(findings)
    isolated = [s for s in dataset.nodes.loc[dataset.nodes.is_seed, 'id'] if g.degree(s) == 0]
    if isolated:
        findings.append({'level': 'warning', 'code': 'isolated_seeds', 'count': len(isolated), 'message': 'Seed без переводов в выборке'})
    cutoff = dataset.nodes.depth.eq(p.max_depth) & ~dataset.nodes.id.isin(dataset.edges.src) if p.max_depth is not None else dataset.nodes.id.isna()
    return {'ok': not any(f['level'] == 'error' for f in findings), 'findings': findings, 'profile': p.to_dict(), 'components': len(comps), 'largest_component': comps[0] if comps else 0, 'cutoff_share': float(cutoff.mean()), 'capabilities': capabilities(dataset)}

def capabilities(dataset):
    p = dataset.profile
    return [
        {'key': 'temporal', 'enabled': p.has_dates, 'message': 'Временные признаки доступны' if p.has_dates else 'Нет дат — временные признаки отключены'},
        {'key': 'taint', 'enabled': p.has_seeds, 'message': 'Поток прослеживается от seed' if p.has_seeds else 'Без seed приоритет считается по структуре и оборотам; блокировка — по общему потоку'},
        {'key': 'cutoff', 'enabled': p.has_depth and p.max_depth is not None and p.has_dates, 'message': 'Граница обхода задана' if p.max_depth is not None else 'Граница сбора не задана — обрезка не оценивается'},
        {'key': 'depth', 'enabled': p.has_depth, 'message': 'Глубина вычислена от seed' if p.depth_computed else 'Глубина из данных' if p.has_depth else 'Глубина не задана'},
    ]
