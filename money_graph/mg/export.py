"""Filesystem adapter for Results, separate from analytical computation."""
import json
from pathlib import Path
import pandas as pd
from .viewer import write_viewer

CONTRACT_ROLES = frozenset({'consolidator', 'transit', 'distributor', 'terminal', 'coordinator', 'peripheral'})


def contract_roles(frame):
    """Keep analytical detail, but export only the six required role values."""
    frame = frame.copy()
    detail = frame['role_detail'] if 'role_detail' in frame else frame['role']
    if not detail.isin(CONTRACT_ROLES | {'truncated'}).all():
        raise ValueError('Cannot export an unknown or missing role')
    frame['role_detail'] = detail
    frame['is_truncated'] = detail.eq('truncated')
    frame['role'] = detail.replace({'truncated': 'peripheral'})
    frame['role_base'] = frame['role']
    return frame


def role_csv_bytes(path):
    """Normalize cached CSVs without rounding string IDs or numeric evidence."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    # Stored exports are already escaped by safe_csv. Reapplying it after reading
    # all values as strings would turn legitimate negative metrics into text.
    return contract_roles(frame).to_csv(index=False).encode('utf-8-sig')


def safe_csv(frame):
    frame = frame.copy()
    for col in frame.select_dtypes(include=['object', 'string']).columns:
        frame[col] = frame[col].map(lambda x: "'" + x if isinstance(x, str) and x.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else x)
    return frame

def export_results(result, dataset, out, viewer=False, cli=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result.nodes.to_parquet(out / 'nodes.parquet')
    tables = {'nodes_roles': result.nodes.reset_index().sort_values('priority_score', ascending=False), 'clusters': result.clusters, 'top_nodes': result.top, 'requests': result.requests, 'resilience': result.resilience}
    for name, frame in tables.items():
        frame = frame.copy()
        if name in ('nodes_roles', 'top_nodes'):
            frame = contract_roles(frame)
        if name == 'nodes_roles':
            frame['role_score'] = frame.role_score.round(3)
        if cli and 'gid' in frame:
            try:
                converted = frame.gid.astype('int64')
                if (converted.astype(str) == frame.gid.astype(str)).all():
                    frame['gid'] = converted
            except (ValueError, OverflowError):
                pass
        safe_csv(frame).to_csv(out / f'{name}.csv', index=False)
    (out / 'summary.json').write_text(json.dumps(result.summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if viewer:
        write_viewer(out/'viewer.html', result.nodes, dataset.legacy_tables()[0], result.clusters, result.top, result.resilience, result.summary, Path(__file__).resolve().parents[1]/'vendor'/'vis-network.min.js', result.requests, result.config)
