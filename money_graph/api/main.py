"""Local-only API and offline SPA. Start with python serve.py."""
import asyncio
import io
import json
import shutil
import zipfile
from collections import deque
from functools import lru_cache
from uuid import uuid4
import numpy as np
import pandas as pd
import networkx as nx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from starlette.middleware.trustedhost import TrustedHostMiddleware
from mg.ingest import read_table, propose, map_table
from mg.explain import rules_for, explain_row
from mg.roles import assign_roles
from mg.pipeline import priority
from mg.paths import money_paths
from mg.taint import TaintModel
from mg.report import render_report
from mg.export import safe_csv
from mg.features import temporal_features
from . import storage as s, jobs
from .schemas import ProjectCreate, Mapping, Selection, Feedback, Case, ConfigPatch, PreviewMapping

load_dotenv(s.ROOT/'.env', override=False)

app = FastAPI(title='Money Graph · Local investigation API', docs_url=None, redoc_url=None, openapi_url='/api/openapi.json')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

@app.middleware('http')
async def security(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and (origin and origin != str(request.base_url).rstrip('/') or request.headers.get('sec-fetch-site') == 'cross-site'):
        return JSONResponse({'detail': 'Разрешены только запросы с локальной страницы приложения'}, 403)
    response = await call_next(request)
    response.headers.update({'X-Content-Type-Options':'nosniff', 'X-Frame-Options':'DENY', 'Referrer-Policy':'no-referrer', 'Cache-Control':'no-store'})
    if not request.url.path.startswith('/api/docs'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response

@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, 422)

@app.get('/api/health')
def health():
    return {'ok': True, 'offline': True, 'default_currency': s.defaults()['currency'], 'demo_available': (s.ROOT/'data'/'transactions.parquet').exists()}

@app.get('/api/docs', include_in_schema=False)
def docs():
    return get_swagger_ui_html(openapi_url='/api/openapi.json', title='Money Graph API', swagger_js_url='/docs-assets/swagger-ui-bundle.js', swagger_css_url='/docs-assets/swagger-ui.css', swagger_favicon_url='/docs-assets/favicon-32x32.png')

@app.get('/api/projects')
def projects():
    return sorted([s.read(p) for p in s.PROJECTS.glob('*/project.json')], key=lambda p:p['created'], reverse=True)

@app.post('/api/projects', status_code=201)
def create(body: ProjectCreate):
    return s.create(body.name.strip())

@app.get('/api/projects/{pid}')
def project(pid: str):
    path = s.folder(pid)
    return {**s.read(path/'project.json'), 'config': s.read(path/'config.json'), 'mapping': s.read(path/'mapping.json')}

@app.delete('/api/projects/{pid}')
def delete(pid: str):
    jobs.require_idle(pid)
    path = s.folder(pid)
    # folder() validates identifier, resolved parent, and project marker before recursion.
    loaded.cache_clear()
    shutil.rmtree(path)
    return {'deleted': True}

@app.post('/api/projects/{pid}/files')
async def upload(pid: str, files: list[UploadFile] = File(...)):
    jobs.require_idle(pid)
    path = s.folder(pid)
    meta = s.read(path/'project.json')
    if len(meta['files']) + len(files) > 20:
        raise HTTPException(413, 'Не более 20 файлов на проект')
    meta['status'] = 'editing'
    s.write(path/'project.json', meta)
    limit = s.defaults().get('upload_limit_mb', 500) * 1024**2
    added = []
    try:
        for file in files:
            name = (file.filename or 'table')[:200]
            suffix = s.Path(name).suffix.lower()
            if suffix not in ('.csv','.parquet','.xlsx'):
                raise HTTPException(422, 'Допустимы CSV, Parquet и XLSX')
            fid = uuid4().hex
            stored = fid+suffix
            raw = path/'raw'/stored
            raw.parent.mkdir(exist_ok=True)
            size = 0
            added.append({'id':fid, 'name':name, 'stored':stored, 'size':0})
            with raw.open('wb') as stream:
                while block := await file.read(1024*1024):
                    size += len(block)
                    if size > limit:
                        raise HTTPException(413, 'Превышен лимит размера файла')
                    stream.write(block)
            added[-1]['size'] = size
            # Validate format before accepting the upload. Restrict XLSX expansion as well.
            if suffix == '.xlsx':
                with zipfile.ZipFile(raw) as archive:
                    if sum(i.file_size for i in archive.infolist()) > limit * 4:
                        raise HTTPException(413, 'Слишком большой распакованный XLSX')
            try:
                read_table(raw, limit=1)
            except HTTPException:
                raise
            except Exception as exc:
                raise ValueError(f'Не удалось прочитать таблицу {name}') from exc
        meta['files'].extend(added)
        meta.update(status='mapping', revision=meta['revision']+1)
        s.write(path/'project.json', meta)
        # Invalidate normalized data until the newly uploaded sources are confirmed.
        s.write(path/'quality.json', {'ok':False, 'findings':[]})
        return {'files': meta['files']}
    except Exception:
        for file in added:
            (path/'raw'/file['stored']).unlink(missing_ok=True)
        meta['status'] = 'draft'
        s.write(path/'project.json', meta)
        raise
    finally:
        for file in files:
            await file.close()

@app.get('/api/projects/{pid}/preview')
def preview(pid: str, file_id: str | None = None, sheet: str | None = None):
    path = s.folder(pid)
    output = []
    for file in s.read(path/'project.json')['files']:
        if file_id and file['id'] != file_id:
            continue
        frame, meta = read_table(path/'raw'/file['stored'], sheet=sheet, limit=50)
        output.append({**file, **meta, 'columns':list(frame.columns), 'rows':s.frame_records(frame), 'proposal':propose(frame)})
    return output

@app.put('/api/projects/{pid}/mapping')
def mapping(pid: str, body: Mapping):
    jobs.require_idle(pid)
    path = s.folder(pid)
    data = body.model_dump()
    meta = s.read(path/'project.json')
    meta['status'] = 'editing'
    s.write(path/'project.json', meta)
    s.write(path/'quality.json', {'ok':False, 'findings':[]})
    try:
        dataset, report = s.prepare(path, data)
    finally:
        meta['status'] = 'draft'
        s.write(path/'project.json', meta)
    s.write(path/'mapping.json', data)
    s.write(path/'quality.json', report)
    if dataset is not None:
        config = s.read(path/'config.json')
        config.update({k: data[k] for k in ('currency','max_depth','collection_threshold','language')})
        s.write(path/'config.json', config)
    return report

@app.post('/api/projects/{pid}/preview')
def normalized_preview(pid: str, body: PreviewMapping):
    path = s.folder(pid)
    files = {f['id']:f for f in s.read(path/'project.json')['files']}
    output = []
    for spec in body.files:
        if spec.kind == 'ignore':
            continue
        if spec.file_id not in files:
            raise HTTPException(422,'Файл отсутствует в проекте')
        raw,_ = read_table(path/'raw'/files[spec.file_id]['stored'], sheet=spec.sheet, limit=50)
        mapped = map_table(raw,spec.fields,body.dayfirst)
        output.append({'file_id':spec.file_id,'columns':list(mapped.columns),'rows':s.frame_records(mapped)})
    return output

@app.get('/api/projects/{pid}/quality')
def quality(pid: str):
    return s.read(s.folder(pid)/'quality.json', {'ok':False, 'findings':[]})

@app.post('/api/projects/{pid}/run')
def run(pid: str):
    return jobs.start(pid)

@app.get('/api/jobs/{jid}')
def job(jid: str):
    if jid not in jobs.JOBS:
        raise HTTPException(404, 'Задача не найдена; после перезапуска запустите расчёт снова')
    return jobs.public(jobs.JOBS[jid])

@app.post('/api/jobs/{jid}/cancel')
def cancel(jid: str):
    job(jid)
    jobs.JOBS[jid]['cancel'].set()
    return {'cancelling': True}

@app.get('/api/jobs/{jid}/events')
async def events(jid: str, request: Request):
    job(jid)
    async def stream():
        previous = None
        while not await request.is_disconnected():
            current = job(jid)
            payload = json.dumps(current, ensure_ascii=False)
            if payload != previous:
                yield f'data: {payload}\n\n'
                previous = payload
            if current['status'] in ('complete','error','cancelled'):
                break
            await asyncio.sleep(.25)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering':'no'})

@app.post('/api/demo')
def demo():
    meta = s.create('Граф денег · пример')
    path = s.folder(meta['id'])
    specs = []
    for name in ('nodes', 'edges', 'transactions'):
        fid = uuid4().hex
        (path/'raw').mkdir(exist_ok=True)
        shutil.copyfile(s.ROOT/'data'/f'{name}.parquet', path/'raw'/f'{fid}.parquet')
        meta['files'].append({'id':fid,'name':name+'.parquet','stored':fid+'.parquet'})
        frame, _ = read_table(path/'raw'/f'{fid}.parquet', limit=50)
        fields = {k:v['column'] for k,v in propose(frame)['fields'].items()}
        specs.append({'file_id':fid,'kind':name,'fields':fields,'sheet':None})
    s.write(path/'project.json',meta)
    cfg = s.defaults()
    mapping(meta['id'], Mapping(files=specs, currency=cfg['currency'], max_depth=cfg['max_depth'], collection_threshold=cfg['min_tx_kzt'], confirmed=True))
    return {'project_id':meta['id'], **jobs.start(meta['id'])}

@lru_cache(maxsize=3)
def loaded(pid, key):
    path = s.folder(pid)
    out = path/'results'/key
    nodes = pd.read_parquet(out/'nodes.parquet')
    nodes.index = nodes.index.astype(str)
    if (out/'profile.json').exists():
        data = s.Dataset(*(pd.read_parquet(out/f'dataset_{name}.parquet') for name in ('nodes','edges','transactions')), s.DatasetProfile(**s.read(out/'profile.json')))
    else:
        data = s.dataset(path)
    return nodes, data, s.read(out/'summary.json'), s.read(out/'config.json'), pd.read_csv(out/'clusters.csv')

def context(pid):
    path = s.folder(pid)
    current = s.read(path/'current.json')
    if not current:
        raise HTTPException(409, 'Сначала запустите анализ')
    return loaded(pid, current['hash'])

@app.get('/api/projects/{pid}/summary')
def summary(pid: str):
    return context(pid)[2]

@app.get('/api/projects/{pid}/nodes')
def nodes(pid: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=5000), q: str = '', role: str = '', cluster: int | None = None, depth: int | None = None, min_priority: float = 0, min_amount: float = 0, max_amount: float | None = None, sort: str = 'priority_score', desc: bool = True, seed_path: bool = False):
    df = context(pid)[0]
    mask = df.index.str.contains(q, regex=False)
    if role:
        mask &= df.role.isin(role.split(','))
    if cluster is not None:
        mask &= df.cluster_id.eq(cluster)
    if depth is not None:
        mask &= df.depth.eq(depth)
    mask &= df.priority_score.ge(min_priority) & df.turnover.ge(min_amount)
    if max_amount is not None:
        mask &= df.turnover.le(max_amount)
    if seed_path:
        mask &= df.seed_sources.gt(0) | df.is_seed
    result = df.loc[mask].reset_index()
    if sort in result.columns:
        result = result.sort_values(sort, ascending=not desc, kind='stable', na_position='last')
    return {'total':len(result), 'items':s.frame_records(result.iloc[offset:offset+limit])}

def row(pid, nid):
    df = context(pid)[0]
    if nid not in df.index:
        raise HTTPException(404, 'Узел не найден')
    return df.loc[nid]

@app.get('/api/projects/{pid}/nodes/{nid}')
def node(pid: str, nid: str):
    r = row(pid,nid)
    e = context(pid)[1].edges
    counterparties = e[e.src.eq(nid) | e.dst.eq(nid)].sort_values('amount', ascending=False).head(20)
    return s.clean({'gid':nid, **r.to_dict(), 'counterparties':s.frame_records(counterparties)})

@app.get('/api/projects/{pid}/nodes/{nid}/explain')
def explain(pid: str, nid: str):
    df, _, _, cfg, _ = context(pid)
    return s.clean(explain_row(row(pid,nid), rules_for(df,cfg)[0], cfg))

def subgraph(pid, ids, limit=3000, start=None, end=None):
    df, data, _, _, _ = context(pid)
    ids = list(dict.fromkeys(ids))
    available = len(ids)
    ids = ids[:limit]
    e = data.edges
    if start or end:
        tx = data.transactions
        if tx.empty or not data.profile.has_dates:
            raise HTTPException(422, 'В данных нет дат')
        tx = tx.loc[(tx.date >= pd.Timestamp(start) if start else tx.date.notna()) & (tx.date <= pd.Timestamp(end)+pd.Timedelta(days=1)-pd.Timedelta(microseconds=1) if end else tx.date.notna())]
        e = tx.groupby(['src','dst']).agg(amount=('amount','sum'), n_tx=('amount','size')).reset_index()
    e = e[e.src.isin(ids) & e.dst.isin(ids)]
    return {'nodes':s.frame_records(df.loc[df.index.intersection(ids)].reset_index()), 'edges':s.frame_records(e), 'available':available, 'limited':available>limit}

@app.post('/api/projects/{pid}/graph')
def selection_graph(pid: str, body: Selection):
    return subgraph(pid, body.ids)

@app.get('/api/projects/{pid}/nodes/{nid}/ego')
def ego(pid: str, nid: str, hops: int = Query(1, ge=1, le=3), limit: int = Query(150, ge=1, le=3000), start: str | None = None, end: str | None = None):
    row(pid,nid)
    df, data, *_ = context(pid)
    g = nx.Graph()
    g.add_edges_from(zip(data.edges.src,data.edges.dst))
    seen, frontier = {nid}, {nid}
    for _ in range(hops):
        nxt = {v for u in frontier if u in g for v in g[u]} - seen
        seen.update(nxt)
        frontier = nxt
        if len(seen) > 10000:
            break
    ranked = [nid] + df.loc[df.index.intersection(seen-{nid})].sort_values('priority_score', ascending=False).index.tolist()
    return subgraph(pid,ranked,limit,start,end)

@app.get('/api/projects/{pid}/nodes/{nid}/timeline')
def timeline(pid: str, nid: str):
    row(pid,nid)
    tx = context(pid)[1].transactions
    tx = tx[tx.src.eq(nid) | tx.dst.eq(nid)].dropna(subset=['date']).copy()
    tx['day'] = tx.date.dt.strftime('%Y-%m-%d')
    inc = tx[tx.dst.eq(nid)].groupby('day').amount.sum().rename('incoming')
    out = tx[tx.src.eq(nid)].groupby('day').amount.sum().rename('outgoing')
    return s.frame_records(pd.concat([inc,out],axis=1).fillna(0).reset_index())

@app.get('/api/projects/{pid}/transactions')
def transactions(pid: str, src: str, dst: str, offset: int = Query(0,ge=0), limit: int = Query(50,ge=1,le=500)):
    tx = context(pid)[1].transactions
    selected = tx[tx.src.eq(src)&tx.dst.eq(dst)].sort_values('date')
    return {'total':len(selected), 'items':s.frame_records(selected.iloc[offset:offset+limit])}

@app.get('/api/projects/{pid}/timeline')
def project_timeline(pid: str):
    tx = context(pid)[1].transactions.dropna(subset=['date']).copy()
    tx['day'] = tx.date.dt.strftime('%Y-%m-%d')
    grouped = tx.groupby('day').agg(amount=('amount','sum'),n_tx=('amount','size')).reset_index()
    return s.frame_records(grouped)

@app.get('/api/projects/{pid}/clusters')
def clusters(pid: str):
    return s.frame_records(context(pid)[4].sort_values(['n_seed','sum_kzt_internal'],ascending=False))

@app.get('/api/projects/{pid}/clusters/{cid}/graph')
def cluster_graph(pid: str, cid: int, limit: int = Query(500,ge=1,le=3000)):
    df = context(pid)[0]
    return subgraph(pid,df[df.cluster_id.eq(cid)].sort_values('priority_score',ascending=False).index.tolist(),limit)

@app.get('/api/projects/{pid}/overview-graph')
def overview(pid: str):
    df,data,_,_,cl = context(pid)
    e = data.edges.assign(src=data.edges.src.map(df.cluster_id).astype(str),dst=data.edges.dst.map(df.cluster_id).astype(str))
    e = e[e.src.ne(e.dst)].groupby(['src','dst']).agg(amount=('amount','sum'),n_tx=('n_tx','sum')).reset_index()
    return {'nodes':[{'gid':str(r.cluster_id),'label':f'Кластер {r.cluster_id}', 'role':'coordinator' if r.n_seed>1 else 'peripheral','priority_score':min(1,r.n_nodes/100),'is_seed':r.n_seed>0} for r in cl.itertuples()], 'edges':s.frame_records(e), 'available':len(cl), 'limited':False, 'overview':True}

@app.get('/api/projects/{pid}/network-graph')
def network_graph(pid: str, limit: int = Query(3000,ge=1,le=3000)):
    df = context(pid)[0]
    return subgraph(pid, df.sort_values('priority_score',ascending=False).index.tolist(), limit)

@app.get('/api/projects/{pid}/paths')
def paths(pid: str, source: str = Query(alias='from'), target: str = Query(alias='to'), k: int = Query(5,ge=1,le=10)):
    df,data,*_ = context(pid)
    return money_paths(data.edges,source,target,k,df.taint_share.to_dict() if data.profile.has_seeds else None)

@app.post('/api/projects/{pid}/simulate/block')
def simulate(pid: str, body: Selection):
    df,data,summary,cfg,_ = context(pid)
    ids = list(dict.fromkeys(body.ids))
    if not set(ids).issubset(df.index):
        raise HTTPException(422,'Выбраны отсутствующие узлы')
    tm = TaintModel(data.legacy_tables()[0],df,cfg['taint_iterations'])
    removed = df.index.isin(ids)
    _,_,before = tm.propagate()
    _,_,after = tm.propagate(removed)
    rng = np.random.default_rng(42)
    random_left = []
    for _ in range(20):
        rnd = np.zeros(len(df),dtype=bool)
        rnd[rng.choice(len(df),len(ids),replace=False)] = True
        random_left.append(tm.propagate(rnd)[2])
    g = nx.Graph()
    g.add_nodes_from(df.index)
    g.add_edges_from(zip(data.edges.src,data.edges.dst))
    before_components = nx.number_connected_components(g)
    g.remove_nodes_from(ids)
    comps = list(nx.connected_components(g))
    changed = []
    for cid in df.loc[ids,'cluster_id'].unique():
        members = df.index[df.cluster_id.eq(cid)]
        pieces = nx.number_connected_components(g.subgraph(members))
        changed.append({'cluster_id':int(cid),'remaining_nodes':len(set(members)-set(ids)),'fragments':pieces})
    return {'ids':ids,'basis':summary['flow_basis'],'before':float(before),'after':float(after),'remaining_share':float(after/before) if before else 0, 'random_share':float(np.mean(random_left)/before) if before else 0,'components_before':before_components,'components_after':len(comps),'largest_component':max(map(len,comps),default=0),'clusters':changed, 'destinations':{'before':tm.destination_flows(),'after':tm.destination_flows(removed)}, 'sankey':{'nodes':[{'name':'До'},{'name':'Сохранилось'},{'name':'Исключено'}],'links':[{'source':0,'target':1,'value':max(0,float(after))},{'source':0,'target':2,'value':max(0,float(before-after))}]}}

def patched(cfg, body):
    patch = body.model_dump(exclude_none=True)
    result = {**cfg, **patch}
    for key in ('roles','priority_weights'):
        if key in patch:
            if set(patch[key])-set(cfg[key]) or any(not np.isfinite(v) or v < 0 for v in patch[key].values()):
                raise HTTPException(422,'Неизвестный порог или некорректное значение')
            result[key] = {**cfg[key], **patch[key]}
    if not 0 <= result['roles']['coordinator_min_betweenness_pct'] <= 1 or result['roles']['transit_pt_low'] > result['roles']['transit_pt_high']:
        raise HTTPException(422,'Проверьте диапазоны порогов')
    total = sum(result['priority_weights'].values())
    if total <= 0:
        raise HTTPException(422,'Хотя бы один вес должен быть положительным')
    result['priority_weights'] = {k:v/total for k,v in result['priority_weights'].items()}
    return result

@app.post('/api/projects/{pid}/config/preview')
def config_preview(pid: str, body: ConfigPatch):
    df,data,_,cfg,_ = context(pid)
    updated = patched(cfg,body)
    base = df.drop(columns=['role','role_score','evidence'])
    if updated['fast_lag_days'] != cfg['fast_lag_days'] and data.profile.has_dates:
        temporal = temporal_features(data.legacy_tables()[2].dropna(subset=['date']), updated['fast_lag_days'])
        for column in temporal:
            base[column] = temporal[column].reindex(base.index)
        base['sync_payers_max'] = base.sync_payers_max.fillna(0).astype(int)
    new = assign_roles(base,updated)
    changed = df.role.ne(new.role)
    return {'counts':new.role.value_counts().to_dict(),'before':df.role.value_counts().to_dict(),'changed_count':int(changed.sum()),'changed':s.frame_records(pd.DataFrame({'gid':df.index[changed], 'before':df.loc[changed,'role'].values,'after':new.loc[changed,'role'].values}).head(500)), 'config':updated}

@app.put('/api/projects/{pid}/config')
def config_save(pid: str, body: ConfigPatch):
    jobs.require_idle(pid)
    path = s.folder(pid)
    cfg = patched(s.read(path/'config.json'),body)
    s.write(path/'config.json',cfg)
    return jobs.start(pid)

@app.post('/api/projects/{pid}/feedback')
def feedback(pid: str, body: Feedback):
    row(pid,body.id)
    path = s.folder(pid)/'feedback.json'
    records = s.read(path,{})
    records[body.id] = {**body.model_dump(), 'date':s.now()}
    s.write(path,records)
    return records[body.id]

@app.get('/api/projects/{pid}/feedback')
def feedback_list(pid: str):
    return list(s.read(s.folder(pid)/'feedback.json',{}).values())

@app.get('/api/projects/{pid}/calibration')
def calibration(pid: str):
    df,_,_,cfg,_ = context(pid)
    feedback = [f for f in feedback_list(pid) if f['id'] in df.index and f['verdict'] != 'unsure']
    def score(config):
        rules,_ = rules_for(df,config)
        matches = 0
        for mark in feedback:
            predicted = explain_row(df.loc[mark['id']], rules, config)['role']
            expected = mark.get('role') or df.loc[mark['id'],'role']
            matches += predicted == expected if mark['verdict']=='confirm' or mark.get('role') else predicted != expected
        return int(matches)
    baseline = score(cfg)
    suggestions = []
    for key,metric in [('consolidator_min_in_deg','in_deg'),('distributor_min_out_deg','out_deg'),('coordinator_min_in_deg','in_deg'),('coordinator_min_out_deg','out_deg')]:
        values = sorted({max(1,int(df.loc[f['id'],metric])+delta) for f in feedback for delta in (-1,0,1)})[:100]
        for value in values:
            candidate = {**cfg,'roles':{**cfg['roles'],key:value}}
            matched = score(candidate)
            if matched > baseline:
                suggestions.append({'parameter':key,'before':cfg['roles'][key],'after':value,'matches':matched,'total':len(feedback)})
    return {'feedback_count':len(feedback),'current_matches':baseline,'suggestions':sorted(suggestions,key=lambda x:(-x['matches'],abs(x['after']-x['before'])))[:5], 'applied':False}

@app.get('/api/projects/{pid}/cases')
def cases(pid: str):
    return s.read(s.folder(pid)/'cases.json',[])

@app.post('/api/projects/{pid}/cases',status_code=201)
def save_case(pid: str, body: Case):
    path = s.folder(pid)/'cases.json'
    if not set(body.ids).issubset(context(pid)[0].index):
        raise HTTPException(422,'Узел дела отсутствует в проекте')
    records = s.read(path,[])
    record = {'id':uuid4().hex, 'created':s.now(), 'result_hash':s.read(s.folder(pid)/'current.json')['hash'], **body.model_dump()}
    records.append(record)
    s.write(path,records)
    return record

@app.get('/api/projects/{pid}/cases/{cid}/report',response_class=HTMLResponse)
def report(pid: str, cid: str):
    record = next((c for c in cases(pid) if c['id']==cid),None)
    if record is None:
        raise HTTPException(404,'Дело не найдено')
    df,data,summary,cfg,_ = loaded(pid,record['result_hash']) if record.get('result_hash') else context(pid)
    output = s.folder(pid)/'results'/record['result_hash'] if record.get('result_hash') else s.result_dir(s.folder(pid))
    requests = pd.read_csv(output/'requests.csv',dtype={'gid':str})
    return render_report(record,df,data.edges,summary,cfg,requests)

@app.post('/api/projects/{pid}/export/selection.csv')
def export_selection(pid: str, body: Selection):
    df = context(pid)[0]
    ids = list(dict.fromkeys(body.ids))
    if any(gid not in df.index for gid in ids):
        raise HTTPException(422, 'Выбранный узел отсутствует в проекте')
    content = safe_csv(df.loc[ids].reset_index()).to_csv(index=False).encode('utf-8-sig')
    return StreamingResponse(io.BytesIO(content), media_type='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename=selected_nodes.csv'})

@app.get('/api/projects/{pid}/export/{kind}')
def export(pid: str, kind: str):
    output = s.result_dir(s.folder(pid))
    allowed = ['nodes_roles.csv','clusters.csv','top_nodes.csv','requests.csv','resilience.csv','summary.json']
    if kind == 'all.zip':
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in allowed:
                archive.write(output/name,name)
        buffer.seek(0)
        return StreamingResponse(buffer,media_type='application/zip',headers={'Content-Disposition':'attachment; filename=analysis.zip'})
    if kind not in allowed:
        raise HTTPException(404,'Выгрузка не найдена')
    return FileResponse(output/kind,filename=kind)

from .assistant import router as assistant_router
app.include_router(assistant_router(loaded))

dist = s.ROOT/'web'/'dist'
if (s.ROOT/'vendor'/'swagger').exists():
    app.mount('/docs-assets',StaticFiles(directory=s.ROOT/'vendor'/'swagger'),name='docs-assets')
if (dist/'assets').exists():
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
if (dist/'fonts').exists():
    app.mount('/fonts',StaticFiles(directory=dist/'fonts'),name='fonts')

@app.get('/{path:path}',include_in_schema=False)
def spa(path: str):
    if path.startswith('api/'):
        raise HTTPException(404,'API маршрут не найден')
    if not (dist/'index.html').exists():
        raise HTTPException(503,'Сначала соберите web: npm ci && npm run build')
    return FileResponse(dist/'index.html')
