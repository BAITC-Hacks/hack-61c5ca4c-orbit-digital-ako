"""Rule expressions are data. The same interpreter assigns and explains roles."""
import math
import operator
import pandas as pd

OPS = {'>=': operator.ge, '>': operator.gt, '<=': operator.le, '<': operator.lt, '==': operator.eq}
def check(metric, op, threshold):
    return {'metric': metric, 'op': op, 'threshold': threshold}

def rules_for(df, cfg):
    c = dict(cfg['roles'])
    if cfg.get('threshold_mode') == 'adaptive':
        for name, metric in [('consolidator_min_in_deg', 'in_deg'), ('coordinator_min_in_deg', 'in_deg'), ('coordinator_min_out_deg', 'out_deg'), ('distributor_min_out_deg', 'out_deg')]:
            c[name] = max(c[name], float(df[metric].quantile(.99)))
    bc = float(df.betweenness.quantile(c['coordinator_min_betweenness_pct']))
    rules = [
        ('isolated', 'peripheral', {'all': [check('in_deg', '==', 0), check('out_deg', '==', 0)]}),
        ('truncated', 'truncated', check('truncated_by_depth', '==', True)),
        ('coordinator', 'coordinator', {'all': [check('in_deg', '>=', c['coordinator_min_in_deg']), check('out_deg', '>=', c['coordinator_min_out_deg']), check('betweenness', '>', 0), check('betweenness', '>=', bc)]}),
        ('distributor', 'distributor', {'all': [check('out_deg', '>=', c['distributor_min_out_deg']), check('fanout_ratio', '>=', c['distributor_fanout_ratio'])]}),
        ('consolidator', 'consolidator', check('in_deg', '>=', c['consolidator_min_in_deg'])),
        ('transit', 'transit', {'all': [check('is_seed', '==', False), check('in_deg', '>', 0), check('out_deg', '>', 0), {'any': [ {'all': [check('pass_through', '>=', c['transit_pt_low']), check('pass_through', '<=', c['transit_pt_high'])]}, {'all': [check('fast_share', '>=', c['transit_min_fast_share']), check('pass_through', '>=', .5)]}]}]}),
        ('terminal', 'terminal', {'all': [check('out_deg', '==', 0), check('observed_boundary', '==', True), {'any': [check('in_kzt', '>=', c['terminal_min_in_kzt']), check('in_deg', '>=', c['terminal_min_in_deg'])]}]}),
        ('peripheral', 'peripheral', check('in_deg', '>=', 0)),
    ]
    return [{'rule': name, 'role': role, 'condition': condition} for name, role, condition in rules], c

def evaluate(expr, values):
    if 'all' in expr or 'any' in expr:
        mode = 'all' if 'all' in expr else 'any'
        parts = [evaluate(e, values) for e in expr[mode]]
        return {'mode': mode, 'ok': (all if mode == 'all' else any)(p['ok'] for p in parts), 'checks': parts}
    value = values.get(expr['metric'])
    valid = value is not None and not pd.isna(value)
    return {**expr, 'value': value if valid else None, 'ok': bool(valid and OPS[expr['op']](value, expr['threshold']))}

def explain_row(row, rules, cfg):
    values = dict(row)
    values['fanout_ratio'] = values['out_deg'] / max(values['in_deg'], 1)
    values['observed_boundary'] = cfg.get('max_depth') is None or (pd.notna(values['depth']) and values['depth'] < cfg['max_depth'])
    trace, matched = [], None
    for rule in rules:
        result = evaluate(rule['condition'], values)
        first = matched is None and result['ok']
        if first:
            matched = rule['role']
        trace.append({**rule, 'passed': result['ok'], 'matched': first, 'checks': result})
    return {'id': str(row.name), 'role': matched, 'trace': trace}
