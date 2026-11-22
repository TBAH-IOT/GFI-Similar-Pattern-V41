"""Validated price catalogue loaded from canonical binary64 source data.

Edit/refreeze canonical_price_catalog.json for real model changes. Runtime
libm, NumPy interpolation and platform rounding never construct prototypes.
"""
from canonical_catalog import load_catalog

_DOCUMENT = load_catalog()
GROUPS = _DOCUMENT['groups']
STOCKCHARTS, BULKOWSKI, BOOK = _DOCUMENT['sources']
CATALOG = _DOCUMENT['patterns']
SEARCHABLE = [p for p in CATALOG if p['status']=='searchable']
BY_NAME = {p['name']:p for p in CATALOG}
LEGACY = [p for p in SEARCHABLE if p['recognition']=='original_5_point_similarity']
EXTENDED = [p for p in CATALOG if p not in LEGACY]
CURVES = [p for p in SEARCHABLE if p['recognition']=='curve_similarity']
MIN_TEMPLATE_POINTS = 4
UNDER_MINIMUM_TEMPLATE_POINTS = [p['name'] for p in SEARCHABLE if len(p['template'])<MIN_TEMPLATE_POINTS]
if UNDER_MINIMUM_TEMPLATE_POINTS:
    raise ValueError('Price-pattern catalogue contains a definition with fewer than four pivots')

def coverage(baseline):
    names={n for profile in baseline['profiles'] for n in profile['patterns']}
    return dict(definitions=len(CATALOG),searchable_definitions=len(SEARCHABLE),
        reference_only_definitions=len(CATALOG)-len(SEARCHABLE),strategies=2*len(SEARCHABLE),families={'chart':len(CATALOG)},
        groups={k:sum(p['group']==k for p in CATALOG) for k in GROUPS},
        btc_baseline_covered=names<=set(BY_NAME),btc_unique_pattern_names=sorted(names),
        btc_profiles=len(baseline['profiles']),btc_source_sha256=baseline['source_sha256'],
        btc_parameters='BTC 15m/1h/4h frozen; current research is NEAR and SOL independently.',
        chart_rules=dict(catalogue='Price charts only',minimum_template_points=MIN_TEMPLATE_POINTS,
            under_minimum_template_points=UNDER_MINIMUM_TEMPLATE_POINTS,
            extra_pivot_or_visual_filters=False,
            curve_windows=[24,48,96],curve_samples=32,curve_stride=4,
            curve_score='1 - normalized RMSE; minimum correlation 0.80',actual_gap_island_bars=[2,10]),
        excluded_by_policy=['TA-Lib / Japanese candlestick patterns','Fibonacci harmonic patterns','Elliott and Wyckoff complete systems','Indicators and order flow'],
        limitations=['Finite sourced taxonomy, not every named trading setup.',
            'Similarity prototypes do not implement all textbook confirmation, volume and duration rules.',
            'All 78 have automatic detectors; specialised rules are published numerical conventions, not every discretionary/private textbook rule.',
            'Wide and Adam/Eve are subtypes; aliases and direct/inverse are not extra pattern families.'],
        sources=[STOCKCHARTS,BULKOWSKI,BOOK],exhaustive=False)
