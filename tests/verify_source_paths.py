"""Compare every projected source OHLC row to the supplied real market bars."""
from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
requests=defaultdict(set);cases=[];recent={}
for path in (ROOT/'demo-data').glob('*.json.gz'):
    with gzip.open(path,'rt',encoding='utf-8') as f:data=json.load(f)
    tf=data['timeframe'];coin=data['symbol'];recent[coin,tf]={bar['time']:bar for bar in data['candles']}
    if tf=='1d':continue
    step={'15m':900,'1h':3600,'4h':14400}[tf]
    for signal in data['signals']:
        for side in ['up','down']:
            case=signal['prediction'][side+'_representative'];key=(case['source_symbol'],tf)
            times=[case['source_time']+i*step for i in range(10)]
            requests[key].update(times);cases.append((key,times,case['candles'],signal['id'],side))
lookup={}
for key,times in requests.items():
    coin,tf=key;found={}
    with gzip.open(ROOT/'runtime/history'/f'{coin}_{tf}.csv.gz','rt',encoding='utf-8') as f:
        for row in csv.DictReader(f):
            time=int(row['time'])
            if time in times:found[time]={k:float(row[k]) for k in ['open','high','low','close']}
    for time in times-found.keys():
        assert time in recent.get(key,{}),(key,time,'Source price row missing')
        found[time]=recent[key][time]
    lookup[key]=found
for key,times,rows,identity,side in cases:
    actual=lookup[key]
    # Frozen BTC can anchor at preceding Close rather than next Open. Infer
    # that common divisor once; every OHLC point must use the same divisor.
    entry=actual[times[0]]['open']/rows[0]['open']
    for time,row in zip(times,rows):
        for field in ['open','high','low','close']:
            assert abs(actual[time][field]/entry-row[field])<1e-9,(identity,side,time,field)
print(f'PASS: {len(cases)} intact historical source paths / {len(cases)*10} OHLC rows match supplied exchange history; no fabricated pullback or mixed-case candles.')
