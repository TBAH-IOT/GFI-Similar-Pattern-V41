"""Directional display probabilities from resolved TP/SL outcomes."""

def directional_outcome_prediction(signal, metrics):
    prediction = signal.get('prediction')
    if not prediction or signal.get('accuracy_source') == 'frozen_btc':
        return prediction
    metric = metrics.get((signal['name'], signal['method']))
    if not metric:
        return prediction
    wins, losses = metric.get('wins', 0), metric.get('opposite_wins', 0)
    total = wins + losses
    if not total:
        return prediction
    success = wins / total
    up = success if signal['direction'] == 'LONG' else 1 - success
    return {**prediction, 'up_probability': up, 'down_probability': 1 - up,
            'sample_count': total, 'basis': 'tp_sl_first_hit_resolved',
            'probability_population': 'completed_unambiguous_tp_sl_only'}
