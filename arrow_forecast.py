"""V40 display: extend the same historical source, with a 20-bar arrow floor."""
import hashlib
import json
import sqlite3
import threading

FLOOR = 20
CAPS = {'15m': 96, '1h': 48, '4h': 32}
VERSION = 'historical-zigzag-arrow-v1'


class ArrowForecastService:
    def __init__(self, root, occurrence_service):
        self.base = occurrence_service
        self.lock = threading.RLock()
        database = root / 'runtime/horizon/arrow-choices-v40.sqlite3'
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS choices (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.commit()

    def extend(self, signal, symbol, tf):
        prediction = signal.get('prediction')
        if tf not in CAPS or not prediction or not signal.get('entry'):
            return signal
        key = hashlib.sha256((VERSION + self.base.key(signal, symbol, tf)).encode()).hexdigest()
        with self.lock:
            saved = self.db.execute('SELECT payload FROM choices WHERE key=?', (key,)).fetchone()
            if saved:
                return {**signal, 'prediction': {**prediction, **json.loads(saved[0])}}
            payload = {}
            branches = {}
            for side in ('up', 'down'):
                case = prediction.get(side + '_representative')
                requested = max(FLOOR, min(CAPS[tf], int(prediction.get(side + '_horizon_bars') or FLOOR)))
                extended = None
                if case:
                    for count in range(requested, FLOOR - 1, -1):
                        # Read only the same contiguous historical sequence,
                        # fully observed before the queried occurrence Entry.
                        extended = self.base.store.extend_case(case, tf, count, int(signal['available_at']))
                        if extended:
                            break
                length = len(extended['candles']) if extended else 0
                payload[side + '_representative'] = extended
                payload[side + '_horizon_bars'] = length
                branches[side] = {
                    'bars': length, 'requested_bars': requested,
                    'reason': 'same_historical_source' if extended else 'insufficient_pre_entry_source',
                    'source_symbol': case.get('source_symbol') if case else None,
                    'source_time': case.get('source_time') if case else None,
                }
            payload['candle_horizon_bars'] = max(payload['up_horizon_bars'], payload['down_horizon_bars'])
            payload['arrow_policy'] = {
                'version': VERSION, 'floor': FLOOR, 'cap': CAPS[tf], 'locked': True,
                'entry_time': int(signal['available_at']), 'pre_entry_source_only': True,
                'horizon_basis': 'v39_occurrence_horizon_with_explicit_20_bar_display_floor',
                'branches': branches,
                'note': 'The display floor may extend beyond the V39 sigma stop; it is not a reliability guarantee.',
            }
            self.db.execute('INSERT INTO choices VALUES (?,?)', (key, json.dumps(payload, allow_nan=False)))
            self.db.commit()
            return {**signal, 'prediction': {**prediction, **payload}}
