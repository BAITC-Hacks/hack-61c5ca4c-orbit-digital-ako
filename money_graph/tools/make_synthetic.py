"""Reproducible datasets with unfamiliar schemas and planted collection structures."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

def make(n, count, seed=42):
    rng = np.random.default_rng(seed)
    # Sparse forward network. Includes every ID, without dense cycles dominating runtime.
    src = np.r_[np.arange(n-1), rng.integers(10,n-1,count-(n-1))]
    dst = np.r_[np.arange(1,n), np.minimum(n-1,src[n-1:]+rng.integers(1,100,count-(n-1))) ]
    tx = pd.DataFrame({'sender':[f'A{x:07d}' for x in src], 'receiver':[f'A{x:07d}' for x in dst], 'amount':rng.integers(10,1000,len(src)).astype(float), 'timestamp':pd.Timestamp('2025-03-01')+pd.to_timedelta(rng.integers(0,60,len(src)),unit='D')})
    planted=[]
    for c in (n-4,n-3,n-2):
        gid=f'A{c:07d}'
        planted.append(gid)
        for sender in range(30,90):
            tx.loc[len(tx)] = [f'A{sender:07d}',gid,100000.,pd.Timestamp('2025-03-12')]
        tx.loc[len(tx)] = [gid,f'A{n-1:07d}',50000.,pd.Timestamp('2025-03-13')]
    # Preserve requested transaction count and planted motifs.
    tx = pd.concat([tx.iloc[:count-183],tx.iloc[-183:]],ignore_index=True)
    return tx, planted

def generate(out, big=False):
    out=Path(out)
    out.mkdir(parents=True,exist_ok=True)
    tx,planted=make(5000,15000)
    tx.to_csv(out/'syn_en.csv',index=False)
    pd.DataFrame({'account_id':['A0000030','A0000031','A0000032']}).to_csv(out/'seeds.csv',index=False)
    small=tx.iloc[-500:].copy().rename(columns={'sender':'отправитель','receiver':'получатель','amount':'сумма','timestamp':'дата_операции'})
    small['сумма']=small['сумма'].map(lambda x:f'{x:,.2f}'.replace(',',' ').replace('.',','))
    small['дата_операции']=pd.to_datetime(small['дата_операции']).dt.strftime('%d.%m.%Y')
    small.to_excel(out/'syn_ru.xlsx',index=False,sheet_name='Переводы')
    small.to_csv(out/'syn_ru_cp1251.csv',index=False,encoding='cp1251',sep=';')
    tx.groupby(['sender','receiver']).agg(value=('amount','sum'),count=('amount','size')).reset_index().rename(columns={'sender':'from_account','receiver':'to_account'}).to_parquet(out/'syn_no_dates.parquet',index=False)
    truth={'syn_en':{'consolidators':planted,'currency':'USD'},'seed_ids':['A0000030','A0000031','A0000032']}
    if big:
        large, known=make(100000,300000)
        large.to_parquet(out/'syn_big.parquet',index=False)
        truth['syn_big']={'consolidators':known,'currency':'USD'}
    (out/'truth.json').write_text(json.dumps(truth,indent=2),encoding='utf-8')
    return truth

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default='.local/synthetic')
    parser.add_argument('--big',action='store_true')
    args=parser.parse_args()
    generate(args.out,args.big)
