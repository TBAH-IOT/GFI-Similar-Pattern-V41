"""V40: V39 occurrence horizons with a separate 10-bar floor.

V39 remains the reference implementation. V40 keeps its per-occurrence,
branch-independent horizon logic and changes only the minimum source window
to fifteen candles. Endpoint amplitude alignment is a renderer concern, so
stored statistics and TP/SL data remain unchanged.
"""
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

import numpy as np
import pandas as pd

from horizon_forecast import HistoryStore, true_ranges, STEPS, FIELDS

FLOOR = 10
SOURCE_PREFIX = 10  # Preserve V39 source selection and amplitude calibration.
CAPS = {'15m': 96, '1h': 48, '4h': 32}
from occurrence_identity import structure_key

VERSION = 'occurrence-sigma-v40-floor10-r9'
SIGMA_MULTIPLIER = 1.0
MIN_NEIGHBORS = 20
MAX_NEIGHBORS = 96
MAX_CONTEXT_DISTANCE = 1.5

def stop_at_sigma(errors, delta, cap=None):
    """Stop BEFORE the first bad close; preserve the explicitly requested floor.

    A breach in the initial fifteen is reported, not hidden or certified as good.
    """
    values = np.asarray(errors, dtype=float)
    limit = min(len(values), cap or len(values))
    bad = np.flatnonzero(~np.isfinite(values[:limit]) | (values[:limit] > delta))
    breach = int(bad[0]) + 1 if len(bad) else None
    draw = max(FLOOR, min(limit, breach - 1 if breach else limit))
    return {'bars': draw, 'first_breach_bar': breach, 'censored_at_cap': breach is None,
            'floor_overrides_breach': breach is not None and breach <= FLOOR}

class ObservedHistory(HistoryStore):
    def ingest(self, symbol, tf, bars):
        times, values, gaps = self.load(symbol, tf)
        fresh = [b for b in bars if b.get('closed') and b['time'] > int(times[-1])]
        if not fresh: return
        fresh = {int(b['time']): b for b in fresh}
        stamps = sorted(fresh)
        with self.lock:
            # Only append newly closed bars. Future/unclosed quotes never enter
            # sigma, context, retrospective labels or nearest-neighbor targets.
            times, values, gaps = self.data[symbol, tf]
            stamps = [stamp for stamp in stamps if stamp > times[-1]]
            if not stamps: return
            times = np.r_[times, stamps]
            values = np.vstack([values, [[fresh[t][field] for field in FIELDS] for t in stamps]])
            gaps = np.r_[0, np.cumsum(np.diff(times) != STEPS[tf])]
            self.data[symbol, tf] = times, values, gaps

    def context(self, symbol, tf, entry_time):
        times, values, gaps = self.load(symbol, tf)
        index = int(np.searchsorted(times, entry_time))
        if index < 33 or gaps[index-1] != gaps[index-33]: return None
        before = values[index-33:index]
        atr = float(np.median(true_ranges(before)[1:]))
        sigma = float(np.std(before[-32:, 3], ddof=1))
        if not np.isfinite(atr + sigma) or atr <= 0: return None
        closes = before[-32:, 3]
        curve = (closes[np.linspace(0,31,8).astype(int)] - closes[-1]) / (4*atr)
        recent_atr = float(np.median(true_ranges(before[-9:])[1:]))
        features = np.r_[curve, np.log(max(recent_atr/atr, 1e-9)),
                         np.log1p(sigma/atr), np.median(abs(before[-32:,3]-before[-32:,0]))/atr,
                         (before[-32:,1].max()-before[-32:,2].min())/(8*atr)]
        return {'features': features, 'atr': atr, 'sigma': sigma,
                'context_last_open': int(times[index-1])}

class CaseIndex:
    def __init__(self, root, store, symbol, tf):
        self.root, self.store, self.symbol, self.tf = Path(root), store, symbol, tf
        self.step, self.cap = STEPS[tf], CAPS[tf]
        self.groups = {}; self.targets = {}; self.labels = {}; self.lock = threading.RLock()
        with gzip.open(self.root/f'runtime/{symbol}_{tf}-forecast-paths.json.gz', 'rt', encoding='utf-8') as source:
            document = json.load(source)
        raw = defaultdict(list)
        for group in document['groups']:
            base, method, variant = group['key']
            if variant != 'direct': continue
            raw[base].extend(group['rows'])
        for base, rows in raw.items():
            rows.sort(key=lambda row: row['available_at'])
            self.groups[base] = {
                'rows': rows, 'times': np.array([r['available_at'] for r in rows], dtype=np.int64),
                'resolved': np.array([r.get('resolved_at') or 2**60 for r in rows], dtype=np.int64),
                'up': np.array([r['is_up'] for r in rows], dtype=bool),
                'prefix': np.array([[[bar[field] for field in FIELDS] for bar in r['_normalized_path'][:SOURCE_PREFIX]] for r in rows]),
            }
        self.refresh_targets()

    def refresh_targets(self):
        times, values, gaps = self.store.load(self.symbol, self.tf)
        with self.lock:
            for base, group in self.groups.items():
                result = []; last = 0
                by_time = {}
                for row in group['rows']:
                    stamp = int(row['available_at'])
                    # Duplicate detectors at one instant are one validation event.
                    previous = by_time.get(stamp)
                    if previous is None or row['similarity'] > previous['similarity']:
                        by_time[stamp] = row
                for stamp, row in sorted(by_time.items()):
                    if stamp < last + (self.cap+1)*self.step: continue
                    pos = int(np.searchsorted(times, stamp))
                    if pos >= len(times) or times[pos] != stamp or pos+self.cap >= len(times): continue
                    if pos < 33 or gaps[pos+self.cap] != gaps[pos-33]: continue
                    context = self.store.context(self.symbol, self.tf, stamp)
                    if context is None: continue
                    result.append({'time':stamp, 'resolved_at':int(row['resolved_at']),
                                   'method':row['method'], 'is_up':bool(row['is_up']),
                                   'features':context['features'], 'pos':pos})
                    last = stamp
                self.targets[base] = result
            self.last_history_time = int(times[-1])

    def neighbors(self, base, features, before, method):
        times, _, _ = self.store.load(self.symbol, self.tf)
        if int(times[-1]) != self.last_history_time: self.refresh_targets()
        result = []
        for target in self.targets.get(base, []):
            # ALL of this target's actual comparison window and TP/SL label
            # must have become known before the queried occurrence's Entry.
            mature = max(target['time']+(self.cap+1)*self.step, target['resolved_at']+self.step)
            if mature > before: continue
            distance = float(np.sqrt(np.mean((target['features']-features)**2)))
            if target['method'].replace(' Calibrated','') != method.replace(' Calibrated',''):
                distance += .1
            if distance <= MAX_CONTEXT_DISTANCE:
                result.append((distance, target, self))
        return result

    def label(self, base, target):
        key = base, target['time']
        with self.lock:
            if key in self.labels: return self.labels[key]
        group = self.groups[base]; stamp = target['time']
        # A future estimate may only use cases whose complete cap window was
        # already observable before this Entry. The old implementation
        # allowed a partially mature source case to contribute a shorter
        # label, which is a subtle look-ahead and makes N change when more
        # candles arrive.
        mask = (group['times']+(self.cap+1)*self.step <= stamp) & (group['resolved']+self.step <= stamp)
        indices = np.flatnonzero(mask)
        context = self.store.context(self.symbol, self.tf, stamp)
        times, values, gaps = self.store.load(self.symbol, self.tf)
        pos = target['pos']; target_entry = float(values[pos,0])
        result = {}
        if context is not None:
            actual = values[pos+1:pos+self.cap+1,3]
            for side, is_up in [('up',True), ('down',False)]:
                usable = indices[group['up'][indices] == is_up]
                if len(usable) < 5: continue
                stack = group['prefix'][usable]; mean = stack.mean(axis=0)
                extremes = stack[:,:,2].min(axis=1) if is_up else stack[:,:,1].max(axis=1)
                adverse = np.maximum(0, 1-extremes if is_up else extremes-1)
                phase = (stack[:,:,2].argmin(axis=1) if is_up else stack[:,:,1].argmax(axis=1))/(SOURCE_PREFIX-1)
                phase = np.where(adverse > 0, phase, 0)
                volatility = max(float((stack[:,:,1]-stack[:,:,2]).mean()),1e-9)
                distance = ((stack-mean)**2).mean(axis=(1,2)) + 4*(adverse-adverse.mean())**2 + .1*volatility**2*(phase-phase.mean())**2
                source_index = int(usable[int(np.argmin(distance))])
                source_time = int(group['times'][source_index])
                # The source itself must also have the complete evaluation
                # window available before the target Entry.  Do not silently
                # fall back to a shorter, newly-completed tail.
                length = self.cap
                whole = self.store.window(self.symbol,self.tf,source_time,length,stamp)
                if whole is None: continue
                normalized = whole / whole[0,0]
                source_range = float(np.median(true_ranges(normalized[:SOURCE_PREFIX])))
                if source_range <= 0: continue
                projected = target_entry + (normalized[:,3]-1)*context['atr']/source_range
                errors = abs(projected-actual[:length])
                result[side] = stop_at_sigma(errors, context['sigma']*SIGMA_MULTIPLIER)
        with self.lock:
            self.labels[key] = result
        return result

def weighted_median(values, weights):
    ordered = np.argsort(values, kind='stable')
    values = np.asarray(values)[ordered]; weights = np.asarray(weights)[ordered]
    return int(values[np.searchsorted(np.cumsum(weights), weights.sum()/2, side='left')])

class OccurrenceHorizonV40:
    def __init__(self, root, database=None):
        self.root = Path(root); self.store = ObservedHistory(root); self.indices = {}; self.lock = threading.RLock()
        settings = json.loads((self.root/'assets.json').read_text(encoding='utf-8'))
        self.peers = settings.get('similar_assets', {})
        # V40 gets a separate persistence namespace. This prevents old V39
        # experiments from being mistaken for an immutable choice made by the
        # current policy, while still keeping the older database recoverable.
        database = Path(database) if database is not None else self.root/'runtime/horizon/occurrence-choices-v40-floor10.sqlite3'
        database.parent.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS choices (key TEXT PRIMARY KEY, symbol TEXT, tf TEXT, base TEXT, entry_time INTEGER, payload TEXT NOT NULL)')
        self.db.commit(); self.as_of = {}

    def observe(self, symbol, tf, bars):
        if tf not in CAPS: return
        with self.lock:
            self.store.ingest(symbol, tf, bars)
            closed = [int(row['time'])+STEPS[tf] for row in bars if row.get('closed')]
            if closed: self.as_of[symbol,tf] = max(closed)

    def index(self, symbol, tf):
        key = symbol,tf
        with self.lock:
            if key not in self.indices: self.indices[key] = CaseIndex(self.root,self.store,symbol,tf)
            return self.indices[key]

    @staticmethod
    def key(signal, symbol, tf):
        structure = list(structure_key(signal))
        if signal.get('points') and len(structure)>4: structure[3] = None
        identity = [VERSION,symbol,tf,int(signal['available_at']),float(signal.get('entry') or 0),structure]
        return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

    def _source(self, case, tf, before):
        if not case: return None,0
        for length in range(CAPS[tf],FLOOR-1,-1):
            try: extended = self.store.extend_case(case,tf,length,before)
            except (OSError,KeyError): extended = None
            if extended is not None: return extended,length
        return None,0

    def _estimate(self, signal, symbol, tf, context):
        base = (signal.get('base_pattern') or signal['name']).removesuffix('__Inverse')
        try:
            records = self.index(symbol,tf).neighbors(base,context['features'],signal['available_at'],signal.get('method',''))
        except (OSError,ValueError,KeyError):
            return {side:{'bars':FLOOR,'reason':'historical_case_library_unavailable','sample_count':0,'minimum_samples':MIN_NEIGHBORS,'evidence':[]} for side in ('up','down')}
        # Match same-coin events first; peer coins are an explicitly identified
        # fallback for a sparse conditional branch, not fabricated samples.
        for peer in self.peers.get(symbol, []):
            if peer not in ('BTCUSDT','NEARUSDT','SOLUSDT'): continue
            for distance,target,index in self.index(peer,tf).neighbors(base,context['features'],signal['available_at'],signal.get('method','')):
                if distance+.3 <= MAX_CONTEXT_DISTANCE: records.append((distance+.3,target,index))
        output = {}
        for side, is_up in [('up',True),('down',False)]:
            local = [item for item in records if item[1]['is_up']==is_up and item[2].symbol==symbol]
            others = [item for item in records if item[1]['is_up']==is_up and item[2].symbol!=symbol]
            pool = sorted(local,key=lambda item:(item[0],-item[1]['time']))
            if len(pool)<MIN_NEIGHBORS: pool += sorted(others,key=lambda item:(item[0],-item[1]['time']))
            pool = pool[:MAX_NEIGHBORS]
            values=[];weights=[];used=[]
            for distance,target,index in pool:
                label = index.label(base,target).get(side)
                if not label: continue
                values.append(label['bars']); weights.append(float(np.exp(-distance*distance)))
                used.append({'symbol':index.symbol,'time':target['time'],'known_at':max(target['time']+(CAPS[tf]+1)*STEPS[tf],target['resolved_at']+STEPS[tf]),'distance':distance,'stop_bars':label['bars']})
            enough = len(values)>=MIN_NEIGHBORS
            output[side] = {'bars':weighted_median(values,weights) if enough else FLOOR,
                            'reason':'similar_past_sigma_stops' if enough else 'insufficient_similar_past_cases',
                            'sample_count':len(values),'minimum_samples':MIN_NEIGHBORS,
                            'peer_samples':sum(row['symbol']!=symbol for row in used),'evidence':used}
        return output

    def extend(self, signal, symbol, tf):
        # The service is called both by the background pipeline and by HTTP
        # readers.  Serialize the complete decision, not just the final SQL
        # INSERT, so two requests cannot compute different first choices for
        # the same occurrence before either one commits it.
        with self.lock:
            return self._extend_locked(signal, symbol, tf)

    def _extend_locked(self, signal, symbol, tf):
        prediction = signal.get('prediction')
        if tf not in CAPS or not prediction or not signal.get('entry'): return signal
        key = self.key(signal,symbol,tf)
        with self.lock:
            saved = self.db.execute('SELECT payload FROM choices WHERE key=?',(key,)).fetchone()
        if saved:
            saved_payload = json.loads(saved[0])
            saved_version = (saved_payload.get('horizon_policy') or {}).get('version')
            if saved_version == VERSION:
                return {**signal,'prediction':{**prediction,**saved_payload}}
            # A representative path is part of the locked occurrence payload.
            # When the renderer/source library changes, an older choice must
            # not silently preserve stale candles or an obsolete horizon.
            with self.lock:
                self.db.execute('DELETE FROM choices WHERE key=?',(key,))
                self.db.commit()
        entry_time = int(signal['available_at']); context = self.store.context(symbol,tf,entry_time)
        as_of = self.as_of.get((symbol,tf),int(self.store.load(symbol,tf)[0][-1])+STEPS[tf])
        fully_known = entry_time+(CAPS[tf]+1)*STEPS[tf] <= as_of
        actual = self.store.window(symbol,tf,entry_time+STEPS[tf],CAPS[tf],as_of) if fully_known else None
        hindsight = actual is not None
        estimates = self._estimate(signal,symbol,tf,context) if context and not hindsight else {}
        metadata = {'version':VERSION,'locked':True,'anchor':'original_entry','entry_time':entry_time,
                    'mode':'retrospective_sigma_stop' if hindsight else 'past_neighbors_estimate',
                    'pre_entry_only':True,
                    'future_horizon_source':'realized_price_until_sigma_breach' if hindsight else 'pre_entry_similar_cases',
                    'actual_price_cutoff':as_of if hindsight else None,
                    'estimate_cutoff':entry_time if not hindsight else None,
                    'hindsight':hindsight,'sigma_multiplier':SIGMA_MULTIPLIER,
                    'sigma_basis':'sample_std_of_32_pre_entry_closes','sigma_reference_bars':32,
                    'sigma_price':context['sigma'] if context else None,'delta_price':context['sigma']*SIGMA_MULTIPLIER if context else None,
                    'floor':FLOOR,'cap':CAPS[tf],'branch_independent':True,'first_ten_preserved':True,
                    'context_last_open':context['context_last_open'] if context else None,
                    'as_of_when_first_saved':as_of,'branches':{}}
        payload = {}
        for side in ('up','down'):
            original = prediction.get(side+'_representative')
            whole,source_limit = self._source(original,tf,entry_time)
            if whole is None or source_limit < FLOOR:
                metadata['branches'][side] = {'bars':0,'reason':'insufficient_historical_source','source_limit':source_limit}
                payload[side+'_horizon_bars'] = 0
                payload[side+'_representative'] = None
                continue
            branch = {'bars':FLOOR,'reason':'insufficient_pre_entry_context'}
            if context and hindsight and whole:
                values = np.array([[r[field] for field in FIELDS] for r in whole['candles']])
                source_range = float(np.median(true_ranges(values[:SOURCE_PREFIX])))
                if source_range>0:
                    origin = 1 if prediction.get('path_start')=='entry_bar' else values[0,0]
                    projected = float(signal['entry'])+(values[:,3]-origin)*context['atr']/source_range
                    errors = abs(projected-actual[:len(projected),3])
                    stopped = stop_at_sigma(errors,metadata['delta_price'])
                    branch = {**stopped, 'reason':'observed_price_crossed_sigma' if stopped['first_breach_bar'] else 'observed_within_sigma_until_source_cap','sample_count':None}
            elif context:
                branch = estimates[side]
            count = max(FLOOR,min(int(branch['bars']),source_limit,CAPS[tf]))
            metadata['branches'][side] = {**branch,'bars':count,'source_limit':source_limit}
            payload[side+'_horizon_bars'] = count
            if whole:
                payload[side+'_representative'] = {**whole,'candles':whole['candles'][:count]}
        payload['candle_horizon_bars'] = max(payload['up_horizon_bars'],payload['down_horizon_bars'])
        payload['horizon_policy'] = metadata
        base = (signal.get('base_pattern') or signal['name']).removesuffix('__Inverse')
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO choices VALUES (?,?,?,?,?,?)',(key,symbol,tf,base,entry_time,json.dumps(payload,allow_nan=False)))
            self.db.commit()
            frozen = json.loads(self.db.execute('SELECT payload FROM choices WHERE key=?',(key,)).fetchone()[0])
        return {**signal,'prediction':{**prediction,**frozen}}

    @property
    def report(self):
        with self.lock:
            rows = self.db.execute('SELECT symbol,tf,base,entry_time,payload FROM choices').fetchall()
        markets = defaultdict(list)
        for symbol,tf,base,entry_time,payload in rows:
            choice=json.loads(payload);meta=choice['horizon_policy']
            markets[f'{symbol}:{tf}'].append({'pattern':base,'entry_time':entry_time,
                'up':choice['up_horizon_bars'],'down':choice['down_horizon_bars'],'mode':meta['mode']})
        return {'version':VERSION,'floor':FLOOR,'sigma_multiplier':SIGMA_MULTIPLIER,
                'per_occurrence':True,'independent_branches':True,'saved_occurrences':len(rows),
                'markets':dict(markets)}

