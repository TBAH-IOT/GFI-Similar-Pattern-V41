"""No network: data integrity, model identity, live bootstrap and portability."""
import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
from occurrence_identity import collapse_occurrences,structure_key
from directional_prediction import directional_outcome_prediction
from path_integrity import contiguous_path_groups

manifest=json.loads((ROOT/'demo-data/manifest.json').read_text(encoding='utf-8'))
assert manifest['model_hash']==server.MODEL_HASH
baseline=json.loads((ROOT/'btc-baseline.json').read_text(encoding='utf-8'))
assert hashlib.sha256((ROOT/'engine/similar_engine.py').read_bytes()).hexdigest()==baseline['source_sha256']
registry=json.loads((ROOT/'runtime/research-registry.json').read_text(encoding='utf-8'))
assert registry['model_hash']==server.MODEL_HASH
assert registry['evaluation_hash']==hashlib.sha256((ROOT/'research_runner.py').read_bytes()).hexdigest()

total=0
for row in manifest['datasets']:
    with gzip.open(ROOT/'demo-data'/row['file'],'rt',encoding='utf-8') as f:data=json.load(f)
    assert data['mode']=='snapshot'
    assert data['symbol']==row['symbol'] and data['timeframe']==row['timeframe']
    signals=data['signals'];total+=len(signals)
    assert len(signals)==row['patterns']
    assert len({structure_key(s) for s in signals})==len(signals)
    assert collapse_occurrences(signals)==signals
    if row['timeframe']=='1d':assert not signals;continue
    assert signals, row
    for s in signals:
        p=s['prediction'];assert abs(p['up_probability']+p['down_probability']-1)<1e-6
        for side in ('up','down'):
            case=p[side+'_representative'];assert case and len(case['candles'])==10,(row,s['id'],side)
            step={'15m':900,'1h':3600,'4h':14400}[row['timeframe']]
            assert case['source_time']+10*step<=s['available_at']
            for bar in case['candles']:
                assert bar['low']>0 and bar['low']<=min(bar['open'],bar['close'])<=max(bar['open'],bar['close'])<=bar['high']
assert total==279,total
times=set(range(0,20000,100))
case={'available_at':13000,'resolved_at':13500}
assert contiguous_path_groups({('test',):[case]},times,100)[('test',)]==[case]
assert not contiguous_path_groups({('test',):[case]},times-{13200},100)[('test',)],'Missing source candle must invalidate an analogue path'

class Worker:
    status='backfilling'
    def snapshot(self):return [],{'status':self.status,'pattern_count':0}

for symbol in ['BTCUSDT','NEARUSDT','SOLUSDT']:
    with gzip.open(ROOT/'demo-data'/f'{symbol}_1h.json.gz','rt',encoding='utf-8') as f:data=json.load(f)
    worker=Worker()
    with patch.dict(server.PIPELINES,{(symbol,'1h'):worker}):
        server.SIGNAL_RESPONSE_CACHE.clear()
        signals=server.live_signals('1h',data['candles'],symbol,True)
        assert signals and all(s['bootstrap_snapshot'] and not s['actionable'] for s in signals)
        assert all(s['statistics_as_of']==data['snapshot_as_of'] for s in signals)
        worker.status='live'
        assert not server.live_signals('1h',data['candles'],symbol,True),'No stale cache may resurrect a pattern after a ready worker rejects it'

worker=Worker();worker.status='live'
with patch.dict(server.PIPELINES,{('BTCUSDT','1h'):worker}), patch.object(server,'_compute_live_signals',return_value=[]) as compute:
    server.SIGNAL_RESPONSE_CACHE.clear();bars=[{'time':1,'closed':True}]
    server.live_signals('1h',bars,'BTCUSDT',True);server.live_signals('1h',bars,'BTCUSDT',True)
    assert compute.call_count==1,'Viewers must share projections for the same closed bar'
    server.live_signals('1h',bars+[{'time':2,'closed':True}],'BTCUSDT',True)
    assert compute.call_count==2

with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='tmp-handoff-') as directory:
    root=Path(directory);source=root/'runtime/history/BTCUSDT_4h.csv.gz';source.parent.mkdir(parents=True)
    source.write_bytes(b'portable source bytes')
    cache=root/'runtime/BTCUSDT_4h-forecast-paths.json.gz'
    doc={'version':server.PATH_CACHE_VERSION,'model_hash':server.MODEL_HASH,'source_mtime':0,'path_contiguity_checked':True,
         'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'last_time':123,
         'groups':[{'key':['A','B','direct'],'rows':[{'valid_cache':True}]}]}
    with gzip.open(cache,'wt',encoding='utf-8') as f:json.dump(doc,f)
    server.FULL_PATH_CACHE.clear();server.FULL_PATH_FUTURES.clear()
    with patch.object(server,'ROOT',root):
        assert server._full_historical_paths('BTCUSDT','4h')=={('A','B','direct'):[{'valid_cache':True}]}
        assert not server.FULL_PATH_FUTURES,'Extraction mtime changes must not cause a historical rescan'

signal={'name':'X','method':'M','direction':'LONG','prediction':{'basis':'legacy','up_probability':0,'down_probability':1}}
fixed=directional_outcome_prediction(signal,{('X','M'):{'wins':3,'opposite_wins':7}})
assert fixed['up_probability']==.3 and fixed['sample_count']==10
assert directional_outcome_prediction({**signal,'accuracy_source':'frozen_btc'}, {})==signal['prediction']

spec=importlib.util.spec_from_file_location('add_coin',ROOT/'tools/add_coin.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='tmp-handoff-') as directory:
    root=Path(directory)
    for name in ['assets.json','research-settings.json']:(root/name).write_bytes((ROOT/name).read_bytes())
    before=json.loads((root/'assets.json').read_text(encoding='utf-8'))['assets']['BTCUSDT']
    module.register(root,'AVAXUSDT','Avalanche','A',['SOLUSDT'])
    after=json.loads((root/'assets.json').read_text(encoding='utf-8'))
    assert after['assets']['BTCUSDT']==before and 'AVAXUSDT' in after['assets']
    assert 'AVAXUSDT' in json.loads((root/'research-settings.json').read_text())['symbols']

html=(ROOT/'static/index.html').read_text(encoding='utf-8')
assert 'id="signal-history"' not in html and 'class="page-foot"' not in html
print('PASS: 279 pre-scanned patterns / 5580 projected OHLC rows; model and registry identity; canonical Entries; causal source cutoff; non-actionable bootstrap; live handover; response cache; portable SHA cache; TP/SL probabilities; config-driven coin registration; chart-only UI.')
