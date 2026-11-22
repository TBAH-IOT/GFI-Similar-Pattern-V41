"""Select an intact historical OHLC sequence near the group mean."""
import numpy as np


def _shape_metrics(values, side):
    """Measure whether an intact source path has a usable finish and turns.

    The renderer must not invent a pullback.  It can, however, choose a
    different *real* analogue when the closest path to the mean finishes on
    the wrong side of Entry or is effectively monotone.  The small noise
    floor keeps one-tick jitter from being mistaken for a visual turn.
    """
    closes = values[:, 3]
    deltas = np.diff(closes)
    nonzero = deltas[np.abs(deltas) > 1e-9]
    if len(nonzero) < 2:
        return 0, False, 0.0
    noise = max(float(np.median(np.abs(nonzero))) * 0.12, 1e-8)
    signs = np.sign(np.where(np.abs(deltas) >= noise, deltas, 0.0))
    signs = signs[signs != 0]
    turns = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0
    endpoint_delta = float(closes[-1] - 1.0)
    direction_ok = endpoint_delta > noise if side == 'up' else endpoint_delta < -noise
    return turns, bool(direction_ok), endpoint_delta


def _median(values):
    values = sorted(float(value) for value in values if np.isfinite(value))
    if not values:
        return 0.0
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _rendered_turns(values, side, target):
    """Mirror the renderer's target-aware transform for ranking only.

    This never returns a path and never changes a candle.  It answers one
    narrow question: after the real source sequence is aligned to its branch
    target, does it still contain visible reversals before first touch?
    """
    if not np.isfinite(target) or target <= 0:
        return 0
    closes = np.r_[1.0, values[:, 3]]
    raw_end_delta = closes[-1] - 1.0
    target_delta = target - 1.0
    floor = max(0.00005, 1e-9)
    raw_scale = target_delta / raw_end_delta if abs(raw_end_delta) > floor else None
    proportional = max(.25, min(4.0, raw_scale)) if raw_scale is not None and raw_scale > 0 else None
    projected = []
    for index, close in enumerate(closes):
        if proportional is not None:
            value = 1.0 + (close - 1.0) * proportional
        else:
            value = close + index / max(1, len(closes) - 1) * (target - closes[-1])
        value = min(target, max(1.0, value)) if side == 'up' else max(target, min(1.0, value))
        projected.append(value)
    for index in range(1, len(projected)):
        if (side == 'up' and projected[index] >= target) or (side == 'down' and projected[index] <= target):
            projected = projected[:index + 1]
            projected[index] = target
            break
    moves = [abs(projected[index] - projected[index - 1]) for index in range(1, len(projected))]
    ranges = []
    for index, row in enumerate(values[:len(projected) - 1]):
        ranges.append(max(float(row[1]) - float(row[2]), abs(float(row[1]) - projected[index + 1]),
                           abs(float(row[2]) - projected[index + 1])))
    limit = max(_median(moves) * .2, _median(ranges) * .04, .00002)
    state, extreme, pivots = 'down', 0, []
    for index in range(1, len(projected)):
        price, current = projected[index], projected[extreme]
        if state == 'down':
            if price <= current:
                extreme = index
            elif price >= current * (1 + limit):
                pivots.append(extreme); state, extreme = 'up', index
        else:
            if price >= current:
                extreme = index
            elif price <= current * (1 - limit):
                pivots.append(extreme); state, extreme = 'down', index
    return len(pivots)


def representative_path(items, horizon, side, preferred_symbol=None, target=None):
    """Return one actual case, never a mixture of candles from different cases.

    `items` are (similarity_distance, negative_time, is_up, path, symbol).
    Rank using distance to mean OHLC plus distance to the group's average
    adverse excursion and its timing. Neither the endpoint nor a pullback
    is imposed. Use same-coin observations when that branch has any.
    """
    usable = [item for item in items if len(item[3]) >= horizon]
    if not usable:
        return None
    local = [item for item in usable if item[4] == preferred_symbol]
    pool = local or usable
    valid, arrays, shapes, rendered = [], [], [], []
    for item in pool:
        values = np.array([[row[key] for key in ('open', 'high', 'low', 'close')]
                           for row in item[3][:horizon]], dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            continue
        if (values[:, 1] < np.maximum(values[:, 0], values[:, 3])).any() or \
           (values[:, 2] > np.minimum(values[:, 0], values[:, 3])).any():
            continue
        valid.append(item)
        arrays.append(values)
        shapes.append(_shape_metrics(values, side))
        rendered.append(_rendered_turns(values, side, target))
    if not arrays:
        return None
    # Prefer an intact historical sequence that ends in the branch direction
    # and contains at least one genuine reversal.  This is a selection rule,
    # not a synthetic adjustment: every returned candle still comes from one
    # actual historical occurrence.  If the exact group has no such case we
    # retain the full valid pool as a transparent fallback.
    directional = [i for i, shape in enumerate(shapes) if shape[1]]
    turning = [i for i in directional if rendered[i] >= 2] if target is not None else []
    if not turning:
        turning = [i for i in directional if shapes[i][0] >= 2]
    eligible = turning or directional or list(range(len(valid)))
    paths = np.stack(arrays)
    mean = paths.mean(axis=0)
    lows_or_highs = paths[:, :, 2 if side == 'up' else 1]
    indices = np.argmin(lows_or_highs, axis=1) if side == 'up' else np.argmax(lows_or_highs, axis=1)
    extremes = lows_or_highs[np.arange(len(paths)), indices]
    adverse = np.maximum(0, 1-extremes if side == 'up' else extremes-1)
    # A case without adverse excursion has no pullback timing.
    phases = np.where(adverse > 0, indices/max(1, horizon-1), 0)
    volatility = max(float(np.mean(paths[:, :, 1]-paths[:, :, 2])), 1e-9)
    distance = np.mean((paths-mean)**2, axis=(1, 2))
    distance += 4 * (adverse-float(adverse.mean()))**2
    distance += .1 * volatility**2 * (phases-float(phases.mean()))**2
    winner = min(eligible, key=lambda i: (float(distance[i]), valid[i][0], valid[i][1]))
    selected = valid[winner]
    rows = selected[3][:horizon]
    return {
        'basis': 'closest_real_path_to_group_mean_with_directional_turns',
        'source_symbol': selected[4], 'source_time': -int(selected[1]),
        'sample_count': len(valid), 'distance_to_mean': float(distance[winner]),
        'source_turns': int(shapes[winner][0]),
        'rendered_turns': int(rendered[winner]),
        'source_direction_aligned': bool(shapes[winner][1]),
        'pullback_pct': float(adverse[winner]),
        'pullback_bar': int(indices[winner])+1 if adverse[winner] > 0 else None,
        'mean_pullback_pct': float(adverse.mean()),
        'mean_pullback_phase': float(phases.mean()),
        # Preserve full source precision, including wickless candles.
        'candles': [{'time_offset': i+1, **{key: float(row[key]) for key in ('open', 'high', 'low', 'close')}}
                    for i, row in enumerate(rows)],
    }
