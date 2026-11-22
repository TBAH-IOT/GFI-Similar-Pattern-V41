"""Terminal identities for repeated observations of one price structure.

Raw detector/research observations remain untouched. A five-pivot template
has four fixed anchor pivots and one terminal pivot that can extend as new
candles close. Direction flips and tail extensions do not create new entries.
"""
import math
import re

PIVOT_METHOD = re.compile(r'^(EMA Peaks|Pivot Window|ZigZag(?: Limit)?)(?: Calibrated)?$')


def structure_key(signal):
    points = signal.get('points') or []
    pivot_signature = []
    for point in points:
        time, value = point.get('time'), point.get('value')
        if not isinstance(time, (int, float)) or not math.isfinite(time):
            return ('id', signal.get('id'))
        value = round(float(value), 8) if isinstance(value, (int, float)) and math.isfinite(value) else None
        pivot_signature.append((int(time), value))
    method = signal.get('method') or ''
    rolling = len(points) == 5 and bool(PIVOT_METHOD.fullmatch(method)) and all(p[1] is not None for p in pivot_signature)
    if rolling:
        pivot_signature = pivot_signature[:-1]
    name = (signal.get('base_pattern') or signal.get('name') or '').removesuffix('__Inverse')
    return (signal.get('symbol') or signal.get('ticker'), signal.get('tf'), method, name,
            'pivot_core' if rolling else 'exact', tuple(pivot_signature))


def _rank(signal):
    rate = signal.get('configured_win_rate')
    samples = signal.get('validation_samples')
    qualified = bool(signal.get('actionable')) or (isinstance(rate, (int, float)) and rate > .55 and
                isinstance(samples, (int, float)) and samples >= (signal.get('minimum_samples') or 0))
    return (int(qualified), rate if isinstance(rate, (int, float)) else -1,
            float(signal.get('similarity') or 0))


def collapse_occurrences(signals):
    """Freeze the entire FIRST confirmation; later matches add metadata only.

    Ranking is used only between simultaneous first confirmations. Never
    choose a later entry/direction because its score or outcome improved.
    """
    ordered = sorted(signals, key=lambda s: (s.get('available_at', s.get('detected_at', 0)),
                     tuple(-v for v in _rank(s)), s.get('id', '')))
    groups = {}
    passthrough = []
    for signal in ordered:
        if not signal.get('points') or signal.get('is_demo'):
            passthrough.append(signal)
            continue
        key = structure_key(signal)
        ids = list(dict.fromkeys([signal['id'], *signal.get('occurrence_aliases', [])]))
        seen = signal.get('last_seen_at') or signal.get('available_at') or signal.get('detected_at', 0)
        if key not in groups:
            groups[key] = {**signal, 'occurrence_aliases': ids, 'last_seen_at': seen}
        else:
            first = groups[key]
            first['occurrence_aliases'] = list(dict.fromkeys([*first['occurrence_aliases'], *ids]))
            first['last_seen_at'] = max(first['last_seen_at'], seen)
    result = passthrough + list(groups.values())
    for signal in groups.values():
        signal['occurrence_revisions'] = len(signal['occurrence_aliases'])
    return sorted(result, key=lambda s: (s.get('available_at', s.get('detected_at', 0)), s.get('id', '')), reverse=True)
