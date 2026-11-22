"""Extend intact r59 source cases; freeze a causal, error-budgeted display horizon."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
import threading

import numpy as np
import pandas as pd

FLOOR = 10
DELTA = .25
CAPS = {'15m': 96, '1h': 48, '4h': 15}
STEPS = {'15m': 900, '1h': 3600, '4h': 14400}
FIELDS = ('open', 'high', 'low', 'close')

def true_ranges(values):
    previous = np.r_[values[0, 0], values[:-1, 3]]
    return np.maximum(values[:, 1] - values[:, 2],
                      np.maximum(abs(values[:, 1] - previous), abs(values[:, 2] - previous)))

class HistoryStore:
    def __init__(self, root):
        self.root = Path(root); self.lock = threading.RLock(); self.data = {}

    def load(self, symbol, tf):
        key = symbol, tf
        with self.lock:
            if key not in self.data:
                frame = pd.read_csv(self.root / f'runtime/history/{symbol}_{tf}.csv.gz').drop_duplicates('time', keep='last').sort_values('time')
                times = frame.time.to_numpy(dtype=np.int64)
                values = frame[list(FIELDS)].to_numpy(dtype=float)
                gaps = np.r_[0, np.cumsum(np.diff(times) != STEPS[tf])]
                self.data[key] = (times, values, gaps)
            return self.data[key]

    def window(self, symbol, tf, start, length, before=None):
        times, values, gaps = self.load(symbol, tf)
        index = int(np.searchsorted(times, start)); end = index + length
        if index >= len(times) or times[index] != start or end > len(times): return None
        if gaps[end - 1] != gaps[index]: return None
        if before is not None and times[end - 1] + STEPS[tf] > before: return None
        return values[index:end]

    def extend_case(self, case, tf, horizon, before):
        rows = self.window(case['source_symbol'], tf, int(case['source_time']), horizon, before)
        if rows is None: return None
        old = case['candles']
        divisor = rows[0, 0] / old[0]['open']
        normalized = rows / divisor
        prefix = np.array([[row[k] for k in FIELDS] for row in old[:FLOOR]])
        if not np.allclose(normalized[:len(prefix)], prefix, rtol=0, atol=1e-9): return None
        candles = [dict(time_offset=i+1, **dict(zip(FIELDS, map(float, row)))) for i, row in enumerate(normalized)]
        candles[:FLOOR] = [dict(row) for row in old[:FLOOR]]
        return {**case, 'candles': candles,
                'extended_from_same_source': True}

def longest_prefix(curve, delta=DELTA):
    """Never relax delta or skip a failed intermediate prefix."""
    limit = float(curve[FLOOR-1]) * (1 + delta)
    chosen = FLOOR
    for offset in range(FLOOR, len(curve)):
        if not np.isfinite(curve[offset]) or curve[offset] > limit: break
        chosen = offset + 1
    return chosen

class HorizonService:
    def __init__(self, root):
        self.root = Path(root); self.store = HistoryStore(root)
        path = self.root / 'runtime/horizon/report.json'
        self.report = json.loads(path.read_text()) if path.exists() else {'markets': {}}
        self.cache = {}; self.lock = threading.RLock()

    def extend(self, signal, symbol, tf):
        prediction = signal.get('prediction')
        if not prediction or tf not in CAPS: return signal
        market = self.report['markets'].get(f'{symbol}:{tf}', {})
        decision = market.get('selected_horizon', FLOOR)
        if market.get('policy_as_of', float('inf')) > signal['available_at']:
            decision = FLOOR
        key = (symbol, tf, signal['id'], signal.get('entry'), decision,
               tuple((prediction.get(side+'_representative') or {}).get('source_time') for side in ('up', 'down')))
        with self.lock:
            saved = self.cache.get(key)
            if saved is None:
                chosen = max(FLOOR, min(CAPS[tf], int(decision)))
                branches = {}
                while chosen > FLOOR:
                    for side in ('up', 'down'):
                        case = prediction.get(side+'_representative')
                        branches[side] = self.store.extend_case(case, tf, chosen, signal['available_at']) if case else None
                    if all(branches.values()): break
                    chosen -= 1
                metadata = {'floor': FLOOR, 'selected_bars': chosen, 'market_bars': decision,
                            'cap': CAPS[tf], 'delta': DELTA, 'anchor': 'original_entry',
                            'policy_as_of': market.get('policy_as_of'),
                            'calibration_samples': market.get('calibration_samples', 0),
                            'verification_samples': market.get('verification_samples', 0),
                            'verification_passed': market.get('verification_passed', False),
                            'reason': 'source_window_limits_extension' if chosen < decision else market.get('reason', 'not_evaluated'),
                            'preserves_first_ten': True, 'score': 'balanced_scenario_close_mae_atr'}
                saved = {'candle_horizon_bars': chosen, 'horizon_policy': metadata}
                if chosen > FLOOR:
                    saved.update({side+'_representative': branches[side] for side in ('up', 'down')})
                self.cache[key] = saved
            # Never cache probabilities/Entry: those belong to the current signal.
            return {**signal, 'prediction': {**prediction, **saved}}

def audit_market(root, symbol, tf, maximum_targets=120):
    """70/30 chronological split; nonoverlapping targets; no target outcome selects a branch."""
    root = Path(root); store = HistoryStore(root); step = STEPS[tf]; cap = CAPS[tf]
    with gzip.open(root / f'demo-data/{symbol}_{tf}.json.gz', 'rt', encoding='utf-8') as f:
        snapshot = json.load(f)
    # Freeze before the EARLIEST displayed Entry, including all verification outcomes.
    as_of = min(signal['available_at'] for signal in snapshot['signals']) - step
    with gzip.open(root / f'runtime/{symbol}_{tf}-forecast-paths.json.gz', 'rt', encoding='utf-8') as f:
        document = json.load(f)
    groups = {}; all_cases = []
    for group in document['groups']:
        base, method, variant = group['key']
        if variant != 'direct': continue
        rows = sorted(group['rows'], key=lambda row: row['available_at'])
        groups.setdefault(base, []).extend(rows)
        all_cases.extend((row['available_at'], base, method, row) for row in rows
                         if row['available_at'] + (cap+1)*step <= as_of and row.get('resolved_at', as_of) + step <= as_of)
    for rows in groups.values(): rows.sort(key=lambda row: row['available_at'])
    all_cases.sort(key=lambda row: (row[0], row[1], row[2]))
    times, values, gaps = store.load(symbol, tf)
    candidates = []; last = 0
    for timestamp, base, method, row in all_cases:
        if timestamp < last + (cap+1)*step: continue
        index = int(np.searchsorted(times, timestamp))
        if index < 33 or index + cap >= len(times): continue
        if gaps[index+cap] != gaps[index-33]: continue
        candidates.append((timestamp, base, method, index)); last = timestamp
    if len(candidates) > maximum_targets:
        candidates = [candidates[int(i)] for i in np.linspace(0, len(candidates)-1, maximum_targets)]
    errors = []; stamps = []; skipped = 0
    for timestamp, base, method, index in candidates:
        prior = groups[base]
        matrices = {True: [], False: []}; futures = {True: [], False: []}
        for case in prior:
            if case['available_at'] + FLOOR*step > timestamp: break
            if case.get('resolved_at', timestamp) + step > timestamp: continue
            prefix = store.window(symbol, tf, case['available_at'], FLOOR, timestamp)
            if prefix is None: continue
            whole = store.window(symbol, tf, case['available_at'], cap, timestamp)
            matrices[bool(case['is_up'])].append(prefix / prefix[0, 0])
            futures[bool(case['is_up'])].append(whole / whole[0, 0] if whole is not None else None)
        if any(len(matrices[side]) < 5 for side in (True, False)):
            skipped += 1; continue
        forecast = []
        atr = float(np.median(true_ranges(values[index-33:index])[1:]))
        if atr <= 0: continue
        for side in (True, False):
            stack = np.stack(matrices[side]); mean = stack.mean(axis=0)
            extremes = stack[:, :, 2].min(axis=1) if side else stack[:, :, 1].max(axis=1)
            adverse = np.maximum(0, 1-extremes if side else extremes-1)
            phase = (stack[:, :, 2].argmin(axis=1) if side else stack[:, :, 1].argmax(axis=1)) / (FLOOR-1)
            phase = np.where(adverse > 0, phase, 0)
            volatility = max(float(np.mean(stack[:, :, 1]-stack[:, :, 2])), 1e-9)
            distance = ((stack-mean)**2).mean(axis=(1, 2)) + 4*(adverse-adverse.mean())**2 + .1*volatility**2*(phase-phase.mean())**2
            chosen = futures[side][int(np.argmin(distance))]
            if chosen is None: break
            source_tr = float(np.median(true_ranges(chosen[:FLOOR])))
            forecast.append((chosen[:, 3]-1) / max(source_tr, 1e-12))
        if len(forecast) != 2:
            skipped += 1; continue
        actual = (values[index+1:index+cap+1, 3]-values[index, 0]) / atr
        # Both scenario paths are scored, with fixed equal weights. We do NOT
        # pick whichever branch happened to win using the target's future.
        loss = .5 * (abs(forecast[0]-actual) + abs(forecast[1]-actual))
        errors.append(np.cumsum(loss) / np.arange(1, cap+1)); stamps.append(timestamp)
    data = np.asarray(errors)
    split = int(len(data)*.7)
    result = {'symbol': symbol, 'timeframe': tf, 'policy_as_of': as_of, 'floor': FLOOR,
              'cap': cap, 'delta': DELTA, 'score': 'balanced_scenario_close_mae_atr',
              'calibration_samples': split, 'verification_samples': len(data)-split,
              'nonoverlap_bars': cap+1, 'skipped_insufficient_analogues': skipped,
              'selected_horizon': FLOOR, 'verification_passed': False}
    if split < 30 or len(data)-split < 15:
        return {**result, 'reason': 'insufficient_chronological_evaluation_samples'}
    calibration = data[:split].mean(axis=0); verification = data[split:].mean(axis=0)
    candidate = longest_prefix(calibration)
    passed = bool(np.all(verification[FLOOR-1:candidate] <= verification[FLOOR-1]*(1+DELTA)))
    return {**result, 'selected_horizon': candidate if passed else FLOOR,
            'calibration_candidate': candidate, 'verification_passed': passed,
            'reason': 'fixed_delta_verified' if passed else 'verification_rejected_extension',
            'calibration_curve': calibration.tolist(), 'verification_curve': verification.tolist(),
            'calibration_last_target': stamps[split-1], 'verification_first_target': stamps[split],
            'verification_last_target': stamps[-1],
            'no_target_oracle_branch_selection': True,
            'validation_used_only_as_pass_fail_gate': True}
