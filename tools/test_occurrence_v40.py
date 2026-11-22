"""V41 contract: V40 occurrence horizon uses the current 10-bar floor."""
import copy
import gzip
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from occurrence_horizon_v40 import OccurrenceHorizonV40, stop_at_sigma, CAPS, STEPS, FLOOR, VERSION

ROOT = Path(__file__).resolve().parents[1]
assert FLOOR == 10
assert stop_at_sigma([0] * 30 + [2] * 10, 1)['bars'] == 30
assert stop_at_sigma([2] * 40, 1) == {
    'bars': 10, 'first_breach_bar': 1,
    'censored_at_cap': False, 'floor_overrides_breach': True
}
assert min(CAPS.values()) >= FLOOR

with gzip.open(ROOT / 'demo-data/BTCUSDT_15m.json.gz', 'rt', encoding='utf-8') as source:
    data = json.load(source)
signal = copy.deepcopy(next(row for row in data['signals'] if row.get('prediction')))
with tempfile.TemporaryDirectory(prefix='gfi-v41-occurrence-') as folder:
    database = Path(folder) / 'choices.sqlite3'
    service = OccurrenceHorizonV40(ROOT, database)
    service.as_of['BTCUSDT', '15m'] = signal['available_at'] + STEPS['15m']
    first = service.extend(signal, 'BTCUSDT', '15m')['prediction']
    assert first['horizon_policy']['version'] == VERSION
    assert first['horizon_policy']['floor'] == FLOOR
    assert first['horizon_policy']['mode'] == 'past_neighbors_estimate'
    for side in ('up', 'down'):
        count = first[side + '_horizon_bars']
        assert FLOOR <= count <= CAPS['15m']
        assert len(first[side + '_representative']['candles']) == count
        for evidence in first['horizon_policy']['branches'][side].get('evidence', []):
            assert evidence['known_at'] <= signal['available_at']
    service.as_of['BTCUSDT', '15m'] = 2**62
    assert service.extend(signal, 'BTCUSDT', '15m')['prediction'] == first
    service.db.close()
    reopened = OccurrenceHorizonV40(ROOT, database)
    assert reopened.extend(signal, 'BTCUSDT', '15m')['prediction'] == first
    reopened.db.close()
print('PASS: 10-bar floor, causal evidence, immutable per-occurrence N across price update/reload', flush=True)
