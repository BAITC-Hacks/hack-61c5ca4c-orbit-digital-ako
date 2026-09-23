"""Reproducible performance check; generated data stays in ignored local storage."""
import argparse
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mg.ingest import read_table, map_table, propose
from mg.dataset import Dataset
from mg.pipeline import run_pipeline
from tools.make_synthetic import generate

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--big',action='store_true')
    args=parser.parse_args()
    output=ROOT/'.local/synthetic'
    generate(output,args.big)
    name='syn_big' if args.big else 'syn_en'
    file=output/(name+('.parquet' if args.big else '.csv'))
    config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    started=time.perf_counter()
    frame,_=read_table(file)
    mapped=map_table(frame,{k:v['column'] for k,v in propose(frame)['fields'].items()})
    truth=json.loads((output/'truth.json').read_text())
    data=Dataset.normalize(transactions=mapped,seeds=truth['seed_ids'],settings={'currency':truth[name]['currency']})
    result=run_pipeline(data,config,lambda stage,percent:print(f'{time.perf_counter()-started:.1f}s {stage} {percent}%',flush=True))
    elapsed=time.perf_counter()-started
    top=result.nodes.nlargest(50,'priority_score').index.tolist()
    assert set(truth[name]['consolidators']).issubset(top)
    report={'elapsed_sec':elapsed,'nodes':len(data.nodes),'transactions':len(data.transactions),'planted_in_top50':True,'summary':result.summary}
    (ROOT/'.local'/f'{name}-benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{elapsed:.2f}s; planted structures found in top 50')
    if args.big:
        assert elapsed<300, f'Performance requirement exceeded: {elapsed:.1f}s'

if __name__=='__main__':
    main()
