"""V40 restoration: arithmetic mean OHLC, at least 20 real source bars."""
import gzip
import hashlib
import json
import sqlite3
import threading

import numpy as np

FIELDS = ('open', 'high', 'low', 'close')
STEPS = {'15m':900, '1h':3600, '4h':14400}
CAPS = {'15m':96, '1h':48, '4h':32}
VERSION = 'mean-ohlc-20-v1'


class MeanForecastService:
    def __init__(self, root, occurrence_service):
        self.root, self.base = root, occurrence_service
        self.lock = threading.RLock()
        self.groups = {}
        self.peers = json.loads((root/'assets.json').read_text(encoding='utf-8')).get('similar_assets', {})
        self.db = sqlite3.connect(root/'runtime/horizon/mean-choices-v40.sqlite3', check_same_thread=False, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS choices (key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        self.db.commit()

    def cases(self, symbol, tf, base, variant):
        key = symbol,tf
        if key not in self.groups:
            with gzip.open(self.root/f'runtime/{symbol}_{tf}-forecast-paths.json.gz','rt',encoding='utf-8') as source:
                self.groups[key] = json.load(source)['groups']
        return [row for group in self.groups[key] if group['key'][0]==base and group['key'][2]==variant for row in group['rows']]

    def branch(self, signal, symbol, tf, side, requested):
        base = (signal.get('base_pattern') or signal['name']).removesuffix('__Inverse')
        variant = signal.get('variant', 'direct')
        before, step = int(signal['available_at']), STEPS[tf]
        # Preserve the earlier UI's same-pattern detector fallback. Coin and
        # detector origins remain recorded; never fabricate a missing path.
        sources = [symbol] + list(self.peers.get(symbol, []))
        for count in range(requested,19,-1):
            paths, evidence = [], []
            seen = set()
            for source_symbol in sources:
                if source_symbol != symbol and len(paths)>=20:
                    break
                for row in self.cases(source_symbol,tf,base,variant):
                    if bool(row['is_up']) != (side=='up'):
                        continue
                    stamp = int(row['available_at'])
                    resolved = row.get('resolved_at')
                    if stamp+count*step>before or not resolved or int(resolved)+step>before:
                        continue
                    identity = source_symbol,stamp,row['method'],variant
                    if identity in seen:
                        continue
                    seen.add(identity)
                    actual = self.base.store.window(source_symbol,tf,stamp,count,before)
                    if actual is None or actual[0,0]<=0 or not np.isfinite(actual).all():
                        continue
                    paths.append(actual/actual[0,0])
                    evidence.append({'symbol':source_symbol,'time':stamp,'method':row['method'],'resolved_at':int(resolved)})
            if paths:
                values = np.mean(np.stack(paths),axis=0)
                return {'basis':'arithmetic_mean_historical_ohlc','sample_count':len(paths),
                        'same_coin_samples':sum(r['symbol']==symbol for r in evidence),
                        'peer_coin_samples':sum(r['symbol']!=symbol for r in evidence),
                        'source_symbol':symbol,'evidence':evidence,
                        'candles':[{'time_offset':i+1,**dict(zip(FIELDS,map(float,row)))} for i,row in enumerate(values)]}
        return None

    def extend(self, signal, symbol, tf):
        prediction = signal.get('prediction')
        if tf not in CAPS or not prediction or not signal.get('entry'):
            return signal
        key = hashlib.sha256((VERSION+self.base.key(signal,symbol,tf)).encode()).hexdigest()
        with self.lock:
            saved = self.db.execute('SELECT payload FROM choices WHERE key=?',(key,)).fetchone()
            if saved:
                return {**signal,'prediction':{**prediction,**json.loads(saved[0])}}
            payload = {'candle_basis':'arithmetic_mean_historical_ohlc','path_start':'entry_bar'}
            for side in ('up','down'):
                requested = max(20,min(CAPS[tf],int(prediction.get(side+'_horizon_bars') or 20)))
                mean = self.branch(signal,symbol,tf,side,requested)
                payload[side+'_representative'] = mean
                payload[side+'_candles'] = mean['candles'] if mean else []
                payload[side+'_horizon_bars'] = len(mean['candles']) if mean else 0
                payload[side+'_path_count'] = mean['sample_count'] if mean else 0
            payload['candle_horizon_bars'] = max(payload['up_horizon_bars'],payload['down_horizon_bars'])
            payload['path_sample_count'] = payload['up_path_count']+payload['down_path_count']
            payload['mean_policy'] = {'version':VERSION,'floor':20,'locked':True,'pre_entry_only':True,
                                      'entry_time':int(signal['available_at']),'horizon_basis':'v39_horizon_with_20_bar_display_floor'}
            self.db.execute('INSERT INTO choices VALUES (?,?)',(key,json.dumps(payload,allow_nan=False)))
            self.db.commit()
            return {**signal,'prediction':{**prediction,**payload}}
