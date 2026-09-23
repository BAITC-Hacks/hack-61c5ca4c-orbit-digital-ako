"""Ordered explainable rules, with shared evaluation and localized evidence."""
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd
from .explain import rules_for, explain_row

@lru_cache
def templates(language='ru'):
    return json.loads((Path(__file__).parent / 'i18n' / f'{language if language in ("ru", "kk", "en") else "ru"}.json').read_text(encoding='utf-8'))

def kzt(value):
    # Compatibility name; values are currency-neutral.
    return f'{value:,.0f}'.replace(',', ' ')

def _clip(value):
    return float(np.clip(value, .05, 1))

def _above(value, threshold):
    return _clip(.5 + .5 * (value - threshold) / max(threshold, 1e-9))

def assign_roles(df, cfg):
    rules, c = rules_for(df, cfg)
    t = templates(cfg.get('language', 'ru'))
    bc_pct = df.betweenness.rank(pct=True)
    rows = []
    for gid, r in df.iterrows():
        trace = explain_row(r, rules, cfg)
        key = next(x['rule'] for x in trace['trace'] if x['matched'])
        role = trace['role']
        pt = r.pass_through
        fs = 0 if pd.isna(r.fast_share) else r.fast_share
        if key in ('isolated', 'truncated'):
            score = 1.
        elif role == 'coordinator':
            score = _clip((_above(r.in_deg, c['coordinator_min_in_deg']) + _above(r.out_deg, c['coordinator_min_out_deg'])) / 2)
        elif role == 'distributor':
            score = _above(r.out_deg, c['distributor_min_out_deg'])
        elif role == 'consolidator':
            score = _above(r.in_deg, c['consolidator_min_in_deg'])
            if not r.is_seed and pd.notna(pt) and pt <= c['consolidator_max_pass_through']:
                score = _clip(score + .15)
        elif role == 'transit':
            score = _clip(.4 + .3 * (1 - min(abs(pt - 1), 1)) + .3 * fs)
        elif role == 'terminal':
            score = _clip(.5 + .25 * min(r.in_deg / 4, 1) + .25 * min(r.in_kzt / 1e6, 1))
        else:
            score = .8
        threshold = cfg.get('collection_threshold')
        currency = cfg.get('currency', '')
        pt_txt = f'{pt:.0%}' if pd.notna(pt) else t['unknown']
        if pd.notna(pt) and pt > c['transit_pt_high']:
            pt_txt = t['external'].format(pt=pt_txt)
        values = dict(incoming=f'{kzt(r.in_kzt)} {currency}', outgoing=f'{kzt(r.out_kzt)} {currency}', in_deg=int(r.in_deg), out_deg=int(r.out_deg), out_tx=int(r.out_tx), sync=int(r.sync_payers_max), pt=pt_txt, depth=int(r.depth) if pd.notna(r.depth) else t['unknown'], onward=f'{r.p_onward:.0%}' if pd.notna(r.p_onward) else t['unknown'], seed_sources=int(r.seed_sources), bc_top=max(1, round((1-bc_pct[gid])*100)), threshold=f' ≥{kzt(threshold)} {currency}' if threshold is not None else '', seed_note=t['seed_note'] if r.is_seed else '', temporal=t['temporal'].format(fast=round(fs*100), lag=cfg['fast_lag_days']) if pd.notna(r.fast_share) else '')
        rows.append((role, score, t[key].format(**values)[:200]))
    return pd.DataFrame(rows, index=df.index, columns=['role', 'role_score', 'evidence'])
