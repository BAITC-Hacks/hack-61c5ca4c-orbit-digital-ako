"""Project-owned paths and atomic JSON writes; raw filenames are display labels only."""
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import hashlib
import json
import os
import re
import pandas as pd
import numpy as np
from fastapi import HTTPException
from mg.ingest import read_table, map_table
from mg.dataset import Dataset, DatasetProfile
from mg.quality import clean_table, quality_report

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = Path(os.getenv('MONEY_GRAPH_PROJECTS', str(ROOT/'projects'))).resolve()

def now():
    return datetime.now(timezone.utc).isoformat()

def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NaT or value is pd.NA:
        return None
    return value

def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)

def folder(pid):
    if not re.fullmatch(r'[a-f0-9]{32}', pid):
        raise HTTPException(404, 'Проект не найден')
    path = (PROJECTS/pid).resolve()
    if path.parent != PROJECTS or not (path/'project.json').exists():
        raise HTTPException(404, 'Проект не найден')
    return path

def defaults():
    return read(ROOT/'config.json')

def create(name):
    pid = uuid4().hex
    path = PROJECTS/pid
    meta = {'id': pid, 'name': name, 'created': now(), 'status': 'draft', 'files': [], 'revision': 0}
    write(path/'project.json', meta)
    config = defaults()
    config.update(max_depth=None, collection_threshold=None)
    write(path/'config.json', config)
    return meta

def prepare(path, mapping, persist=True):
    files = {f['id']: f for f in read(path/'project.json')['files']}
    tables, findings, seeds = {}, [], list(mapping['seeds'])
    for spec in mapping['files']:
        if spec['kind'] == 'ignore':
            continue
        file = files.get(spec['file_id'])
        if not file:
            raise ValueError('Файл сопоставления не найден')
        raw, _ = read_table(path/'raw'/file['stored'], spec.get('sheet'))
        frame = map_table(raw, spec['fields'], mapping.get('dayfirst', True))
        frame, found = clean_table(frame, spec['kind'])
        findings.extend({**f, 'file': file['name']} for f in found)
        if spec['kind'] == 'seeds':
            if 'id' in frame:
                seeds.extend(frame.id.dropna().astype(str))
        else:
            tables.setdefault(spec['kind'], []).append(frame)
    if any(f['level'] == 'error' for f in findings):
        return None, {'ok': False, 'findings': findings}
    tables = {k: pd.concat(v, ignore_index=True) for k, v in tables.items()}
    if 'transactions' in tables and 'edges' in tables:
        grouped = tables['transactions'].groupby(['src','dst']).amount.sum()
        supplied = tables['edges'].groupby(['src','dst']).amount.sum()
        aligned = pd.concat([grouped, supplied], axis=1).fillna(-1)
        if not np.allclose(aligned.iloc[:,0], aligned.iloc[:,1]):
            findings.append({'level': 'warning', 'code': 'edge_mismatch', 'count': 1, 'message': 'Рёбра расходятся с транзакциями; для расчёта использована агрегация транзакций'})
    tx = tables.get('transactions')
    if tx is not None and 'date' in tx:
        outside = pd.Series(False, index=tx.index)
        if mapping.get('expected_start'):
            outside |= tx.date < pd.Timestamp(mapping['expected_start'])
        if mapping.get('expected_end'):
            outside |= tx.date > pd.Timestamp(mapping['expected_end'])
        if outside.any():
            findings.append({'level': 'warning', 'code': 'period', 'count': int(outside.sum()), 'message': 'Даты вне ожидаемого периода; строки сохранены'})
    dataset = Dataset.normalize(tx, tables.get('edges'), tables.get('nodes'), seeds, mapping)
    report = quality_report(dataset, findings)
    report['seeds'] = {'requested': len(set(seeds)), 'in_edges': len(set(seeds) & (set(dataset.edges.src) | set(dataset.edges.dst)))}
    if persist:
        for name in ('nodes', 'edges', 'transactions'):
            getattr(dataset, name).to_parquet(path/f'{name}.parquet', index=False)
        write(path/'profile.json', dataset.profile.to_dict())
        write(path/'quality.json', report)
    return dataset, report

def dataset(path):
    profile = read(path/'profile.json')
    if not profile:
        raise HTTPException(409, 'Сначала подтвердите сопоставление колонок')
    return Dataset(*(pd.read_parquet(path/f'{name}.parquet') for name in ('nodes', 'edges', 'transactions')), DatasetProfile(**profile))

def digest(path, config):
    h = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    h.update(b'pipeline-v3')
    for name in ('nodes', 'edges', 'transactions'):
        with (path/f'{name}.parquet').open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                h.update(block)
    return h.hexdigest()

def result_dir(path):
    current = read(path/'current.json')
    if not current:
        raise HTTPException(409, 'Расчёт ещё не завершён')
    return path/'results'/current['hash']

def frame_records(frame):
    return clean(frame.to_dict('records'))
