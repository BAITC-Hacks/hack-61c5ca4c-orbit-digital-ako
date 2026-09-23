from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Event
from uuid import uuid4
import time
import traceback
from fastapi import HTTPException
from mg.pipeline import run_pipeline
from mg.export import export_results
from . import storage as s

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='analysis')
JOBS = {}
LOCK = Lock()

def busy(pid):
    return any(j['project_id'] == pid and j['status'] in ('queued','running') for j in JOBS.values())

def require_idle(pid):
    if busy(pid):
        raise HTTPException(409, 'Дождитесь завершения или отмените расчёт')
    if s.read(s.folder(pid)/'project.json').get('status') == 'editing':
        raise HTTPException(409, 'Дождитесь завершения загрузки или сопоставления')

def start(pid):
    with LOCK:
        require_idle(pid)
        path = s.folder(pid)
        config = s.read(path/'config.json')
        if not s.read(path/'quality.json', {}).get('ok'):
            raise HTTPException(422, 'Исправьте ошибки качества данных')
        key = s.digest(path, config)
        jid = uuid4().hex
        job = {'id': jid, 'project_id': pid, 'status': 'queued', 'stage': 'reading', 'percent': 0, 'events': [], 'cancel': Event(), 'started': time.time()}
        JOBS[jid] = job
        def progress(stage, percent):
            if job['cancel'].is_set():
                raise InterruptedError('Расчёт отменён')
            job.update(stage=stage, percent=percent)
            job['events'].append({'stage': stage, 'percent': percent, 'elapsed': round(time.time()-job['started'], 2)})
        def work():
            job['status'] = 'running'
            meta = s.read(path/'project.json')
            meta['status'] = 'running'
            s.write(path/'project.json', meta)
            try:
                output = path/'results'/key
                if not (output/'complete.json').exists():
                    progress('reading', 5)
                    data = s.dataset(path)
                    progress('mapping', 10)
                    progress('quality', 15)
                    result = run_pipeline(data, config, progress)
                    export_results(result, data, output)
                    for name in ('nodes', 'edges', 'transactions'):
                        getattr(data, name).to_parquet(output/f'dataset_{name}.parquet', index=False)
                    s.write(output/'profile.json', data.profile.to_dict())
                    s.write(output/'config.json', result.config)
                    s.write(output/'complete.json', {'finished': s.now()})
                else:
                    job['cached'] = True
                progress('complete', 100)
                s.write(path/'current.json', {'hash': key})
                job['status'] = 'complete'
                meta.update(status='ready', summary=s.read(output/'summary.json'))
            except InterruptedError:
                job.update(status='cancelled', stage='cancelled')
                meta['status'] = 'cancelled'
            except Exception:
                traceback.print_exc()
                job.update(status='error', message='Не удалось выполнить расчёт. Проверьте качество и параметры; подробности в локальном журнале.')
                meta['status'] = 'error'
            finally:
                s.write(path/'project.json', meta)
        POOL.submit(work)
        return {'job_id': jid}

def public(job):
    return {**{k: v for k, v in job.items() if k not in ('cancel', 'events')}, 'timeline': list(job['events'])}
