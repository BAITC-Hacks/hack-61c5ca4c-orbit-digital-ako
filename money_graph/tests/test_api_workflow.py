"""Project lifecycle, cache, simulation, provenance, safe report and deletion."""
import sys
import time
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api.main import app
from api import storage
from mg.taint import TaintModel
from mg.paths import money_paths

def test_full_project(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'PROJECTS',tmp_path)
    with TestClient(app) as client:
        pid=client.post('/api/projects',json={'name':'<script>private</script>'}).json()['id']
        prefix=f'/api/projects/{pid}'
        csv='sender;receiver;amount;timestamp\n001;002;1000,00;01.03.2025\n002;003;900,00;02.03.2025\n'.encode()
        response=client.post(prefix+'/files',files=[('files',('../upload.csv',csv,'text/csv'))])
        assert response.status_code==200
        file=client.get(prefix+'/preview').json()[0]
        mapping={'files':[{'file_id':file['id'],'kind':'transactions','fields':{k:v['column'] for k,v in file['proposal']['fields'].items()}}],'seeds':['001'],'currency':'EUR','confirmed':True}
        preview=client.post(prefix+'/preview',json={'files':mapping['files'],'dayfirst':True})
        assert preview.json()[0]['rows'][0]['amount']==1000
        quality=client.put(prefix+'/mapping',json=mapping)
        assert quality.status_code==200 and quality.json()['ok']
        def run():
            response=client.post(prefix+'/run')
            assert response.status_code==200,response.text
            jid=response.json()['job_id']
            for _ in range(100):
                status=client.get('/api/jobs/'+jid).json()
                if status['status'] in ('complete','error','cancelled'):
                    break
                time.sleep(.05)
            assert status['status']=='complete',status
            return status
        run()
        assert run().get('cached') is True
        nodes=client.get(prefix+'/nodes?sort=gid&desc=false').json()
        assert [n['gid'] for n in nodes['items']]==['001','002','003']
        assert client.get(prefix+'/nodes/002/explain').json()['role']=='transit'
        assert client.get(prefix+'/timeline').status_code==200
        selected_csv = client.post(prefix+'/export/selection.csv', json={'ids':['002']})
        assert selected_csv.status_code == 200
        assert pd.read_csv(__import__('io').StringIO(selected_csv.text), dtype={'gid':str}).gid.tolist() == ['002']
        assert client.post(prefix+'/export/selection.csv', json={'ids':['unknown']}).status_code == 422
        local = client.post(prefix+'/assistant', json={'gids':['002'], 'mode':'explain'})
        assert local.status_code == 200, local.text
        assert local.json()['mode'] == 'local' and local.json()['evidence'][0]['gid'] == '002'
        assert client.post(prefix+'/assistant', json={'gids':['unknown']}).status_code == 422
        assert client.post(prefix+'/assistant', json={'gids':['002'], 'mode':'question', 'question':'Explain'}).status_code == 422
        import api.assistant as assistant_api
        monkeypatch.setattr(assistant_api, 'settings', lambda: {'configured':False, 'model':None})
        assert client.post(prefix+'/assistant', json={'gids':['002'], 'mode':'question', 'question':'Explain', 'allow_external':True}).status_code == 503
        calls = []
        async def fake_provider(graph, gids, question):
            calls.append(question)
            assert graph.currency == 'EUR'
            return graph.preset('explain', gids)
        monkeypatch.setattr(assistant_api, 'ask_openai', fake_provider)
        monkeypatch.setattr(assistant_api, 'settings', lambda: {'configured':True, 'model':'test'})
        assert client.post(prefix+'/assistant', json={'gids':['002'], 'mode':'question', 'question':'Explain', 'allow_external':True}).status_code == 200
        assert calls == ['Explain']
        async def failing_provider(*args):
            raise RuntimeError('SECRET_PROVIDER_KEY')
        monkeypatch.setattr(assistant_api, 'ask_openai', failing_provider)
        failure = client.post(prefix+'/assistant', json={'gids':['002'], 'mode':'question', 'question':'Explain', 'allow_external':True})
        assert failure.status_code == 502 and 'SECRET_PROVIDER_KEY' not in failure.text
        assert len(client.get(prefix+'/nodes/002/ego').json()['nodes'])==3
        assert client.get(prefix+'/paths?from=001&to=003').json()['paths'][0]['nodes']==['001','002','003']
        assert client.get(prefix+'/paths?from=001&to=001').json()['paths']==[]
        result=client.post(prefix+'/simulate/block',json={'ids':['002']}).json()
        assert result['after']==0
        assert result['destinations']['before']['total']==900
        assert result['destinations']['after']['total']==0
        feedback=client.post(prefix+'/feedback',json={'id':'002','verdict':'reject','role':'peripheral','comment':'review'})
        assert feedback.status_code==200
        assert client.get(prefix+'/calibration').json()['feedback_count']==1
        case=client.post(prefix+'/cases',json={'name':'Review','ids':['002'],'notes':'<script>alert(1)</script>','scenarios':[result]}).json()
        report=client.get(prefix+'/cases/'+case['id']+'/report')
        assert '<script>alert' not in report.text and '&lt;script&gt;' in report.text
        assert '<svg' in report.text
        assert client.get(prefix+'/export/all.zip').headers['content-type']=='application/zip'
        assert client.get(prefix+'/export/config.json').status_code==404
        assert client.post(prefix+'/files',files=[('files',('unsafe.exe',b'content','application/octet-stream'))]).status_code==422
        assert client.put(prefix+'/config',json={'priority_weights':{'role':-1}}).status_code==422
        assert client.delete(prefix).json()['deleted']
        assert not (tmp_path/pid).exists()

def test_seed_attribution_is_additive():
    edges=pd.DataFrame({'src':['s1','s2','a'],'dst':['a','a','z'],'sum_kzt':[60.,40.,100.],'n_tx':[1,1,1]})
    nodes=pd.DataFrame({'is_seed':[True,True,False,False]},index=['s1','s2','a','z'])
    tm=TaintModel(edges,nodes,8)
    flows=tm.destination_flows()
    assert flows['total']==100
    assert sorted(link['value'] for link in flows['links'])==[40.,60.]

def test_no_dataset_hardcodes():
    import re
    for folder in ['mg','api','web/src']:
        for path in (ROOT/folder).rglob('*'):
            if path.suffix not in ('.py','.json','.ts','.tsx','.css'):
                continue
            text=path.read_text(encoding='utf-8-sig')
            assert not re.search(r'2026-07|KZT|5 000|4-м хоп|\b\d{18}\b',text),path
