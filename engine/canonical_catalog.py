"""Exact, versioned binary64 prototypes shared by model, registry and API.

No runtime sin/interpolation/normalization constructs model constants here.
The values are the bit-exact prototypes of the validated r59 catalogue.
"""
from functools import lru_cache
import json
import math
from pathlib import Path

SCHEMA = 'gfi-price-prototypes-binary64-v1'
CATALOG_PATH = Path(__file__).with_name('canonical_price_catalog.json')

def decode_binary64(value):
    if '__binary64__' not in value:
        return value
    if set(value) != {'__binary64__'} or not isinstance(value['__binary64__'], str):
        raise ValueError('Invalid canonical binary64 value')
    number = float.fromhex(value['__binary64__'])
    if not math.isfinite(number) or number.hex() != value['__binary64__']:
        raise ValueError('Nonfinite/noncanonical binary64 encoding')
    return number

def reject_constant(value):
    raise ValueError('Nonfinite JSON constant: ' + value)

@lru_cache(maxsize=1)
def load_catalog():
    document = json.loads(CATALOG_PATH.read_text(encoding='utf-8'),
                          object_hook=decode_binary64, parse_constant=reject_constant)
    if document.get('schema') != SCHEMA:
        raise ValueError('Unsupported canonical price catalogue schema')
    patterns = document['patterns']
    if len({p['name'] for p in patterns}) != len(patterns):
        raise ValueError('Duplicate canonical price-pattern names')
    for pattern in patterns:
        values, times = pattern['template'], pattern['template_times']
        if len(values) != len(times) or len(values) < 4:
            raise ValueError('Invalid prototype dimensions: ' + pattern['name'])
        if not all(isinstance(v, (int,float)) and math.isfinite(v) for v in values+times):
            raise ValueError('Invalid prototype numbers: ' + pattern['name'])
        if times[0] != 0 or times[-1] != 1 or any(a>=b for a,b in zip(times,times[1:])):
            raise ValueError('Invalid prototype time grid: ' + pattern['name'])
    curves = [p['name'] for p in patterns if p['status']=='searchable' and p['recognition']=='curve_similarity']
    matrices = document['curve_matrices']
    if matrices['names'] != curves or len(matrices['grid']) != 32:
        raise ValueError('Canonical curve order/grid does not match catalogue')
    grid = matrices['grid']
    if grid[0]!=0 or grid[-1]!=1 or not all(math.isfinite(v) for v in grid) or any(a>=b for a,b in zip(grid,grid[1:])):
        raise ValueError('Invalid canonical dense-curve grid')
    for name in ('templates','centered'):
        if len(matrices[name]) != len(curves) or any(len(row)!=32 for row in matrices[name]):
            raise ValueError('Invalid canonical curve matrix: ' + name)
        if not all(math.isfinite(value) for row in matrices[name] for value in row):
            raise ValueError('Nonfinite canonical curve matrix: ' + name)
    if len(matrices['norms']) != len(curves) or any(not math.isfinite(v) or v<=0 for v in matrices['norms']):
        raise ValueError('Invalid canonical curve norms')
    return document
