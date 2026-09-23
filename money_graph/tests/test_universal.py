import json
import sys
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mg.dataset import Dataset
from mg.ingest import read_table,propose,map_table
from mg.quality import clean_table
from mg.pipeline import run_pipeline
from mg.explain import rules_for,explain_row
from mg.export import safe_csv
from tools.make_synthetic import generate

@pytest.fixture(scope='module')
def config():
    return json.loads((ROOT/'config.json').read_text(encoding='utf-8'))

@pytest.fixture(scope='module')
def baseline(config):
    dataset=Dataset.normalize(pd.read_parquet(ROOT/'data/transactions.parquet'),pd.read_parquet(ROOT/'data/edges.parquet'),pd.read_parquet(ROOT/'data/nodes.parquet'),settings={**config,'collection_threshold':config['min_tx_kzt']})
    return run_pipeline(dataset,config)

def test_baseline(baseline):
    s=baseline.summary
    assert s['roles']==dict(peripheral=1162,truncated=444,terminal=358,transit=154,consolidator=67,distributor=46,coordinator=17)
    assert (s['nodes'],s['edges'],s['transactions'])==(2248,3119,4840)
    assert s['tainted_flow_kzt']==253083784
    assert s['clusters']==71 and s['multiseed_clusters']==9
    assert s['cutoff_model']['cv_auc']==.66
    assert s['cutoff_model']['train_nodes']==1723
    assert baseline.top.gid.head(3).tolist()==['100000003684369100','100000008165763100','100000003115284100']
    for n,target in [(5,.83),(10,.78),(20,.43)]:
        assert round(baseline.resilience.iloc[n].tainted_flow_left,2)==target

def test_trace_uses_actual_rules(baseline):
    rules,_=rules_for(baseline.nodes,baseline.config)
    for _,r in baseline.nodes.iterrows():
        ex=explain_row(r,rules,baseline.config)
        assert ex['role']==r.role
        assert sum(t['matched'] for t in ex['trace'])==1

def test_degradation(config):
    d=Dataset.normalize(edges=pd.DataFrame({'src':['001','002'],'dst':['002','003'],'amount':[100,90]}),settings={'currency':'EUR'})
    r=run_pipeline(d,config)
    assert r.nodes.index.tolist()==['001','002','003']
    assert r.summary['flow_basis']=='total'
    assert r.nodes.p_onward.isna().all()
    assert not r.nodes.role.eq('truncated').any()
    assert not next(c for c in r.summary['capabilities'] if c['key']=='temporal')['enabled']
    assert r.nodes.loc['002','role']=='transit'

def test_quality_and_csv():
    frame=pd.DataFrame({'src':['a']*20+[''],'dst':['b']*21,'amount':['1 200,50']*21})
    mapped=map_table(frame,{'src':'src','dst':'dst','amount':'amount'})
    result,findings=clean_table(mapped,'transactions')
    assert len(result)==20 and findings[0]['level']=='warning'
    assert result.amount.iloc[0]==1200.5
    assert safe_csv(pd.DataFrame({'id':['=1+1',' @x','001']})).id.tolist()==["'=1+1","' @x",'001']

def test_synthetic_mapping(tmp_path,config):
    generate(tmp_path)
    for name in ['syn_en.csv','syn_ru.xlsx','syn_ru_cp1251.csv','syn_no_dates.parquet']:
        frame,meta=read_table(tmp_path/name)
        proposal=propose(frame)
        assert {'src','dst','amount'} <= set(proposal['fields'])
        mapped=map_table(frame,{k:v['column'] for k,v in proposal['fields'].items()},True)
        cleaned,findings=clean_table(mapped,proposal['kind'])
        assert not any(f['level']=='error' for f in findings)
        d=Dataset.normalize(**{proposal['kind']:cleaned},seeds=['A0000030','A0000031','A0000032'] if name=='syn_en.csv' else [],settings={'currency':'USD'})
        r=run_pipeline(d,config)
        assert len(r.nodes)==len(d.nodes)
        if name=='syn_en.csv':
            truth=json.loads((tmp_path/'truth.json').read_text())
            assert set(truth['syn_en']['consolidators']) <= set(r.nodes.nlargest(50,'priority_score').index)

def test_local_api_and_path_guards(tmp_path,monkeypatch):
    from api import storage
    from api.main import app
    monkeypatch.setattr(storage,'PROJECTS',tmp_path)
    with TestClient(app) as client:
        assert client.get('/api/health').status_code==200
        assert client.post('/api/projects',json={'name':'bad'},headers={'origin':'https://evil.example'}).status_code==403
        project=client.post('/api/projects',json={'name':'Private local case'}).json()
        pid=project['id']
        assert client.get('/api/projects/not-an-id').status_code==404
        csv=b'sender,receiver,amount,timestamp\na,b,100,2025-01-01\nb,c,90,2025-01-02\n'
        uploaded=client.post(f'/api/projects/{pid}/files',files=[('files',('../../sample.csv',csv,'text/csv'))])
        assert uploaded.status_code==200
        preview=client.get(f'/api/projects/{pid}/preview').json()[0]
        mapping={'files':[{'file_id':preview['id'],'kind':'transactions','fields':{k:v['column'] for k,v in preview['proposal']['fields'].items()}}],'currency':'USD','confirmed':True}
        response=client.put(f'/api/projects/{pid}/mapping',json=mapping)
        assert response.status_code==200 and response.json()['ok']
        assert client.delete(f'/api/projects/{pid}').status_code==200
