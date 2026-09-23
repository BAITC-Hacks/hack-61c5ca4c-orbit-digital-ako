"""Filesystem adapter for Results, separate from analytical computation."""
import json
from pathlib import Path
import pandas as pd
from .viewer import write_viewer

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
