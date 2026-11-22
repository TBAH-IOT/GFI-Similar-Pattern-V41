"""Print exact model identities and optionally validate all NEAR/SOL markets."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

def inspect(root, check_registry=False):
    sys.path.insert(0,str(root/'engine'))
    import numpy as np
    import research_model as model
    import strategy_catalog as strategies
    import curve_search
    from canonical_catalog import SCHEMA
    arrays={name:hashlib.sha256(np.asarray(getattr(curve_search,name),dtype='<f8').tobytes()).hexdigest()
            for name in ('GRID','TEMPLATES','CENTERED','NORMS')}
    arrays['LEGACY_TEMPLATES']=hashlib.sha256(np.asarray(model.TEMPLATES,dtype='<f8').tobytes()).hexdigest()
    result={'python':platform.python_version(),'numpy':np.__version__,'prototype_schema':SCHEMA,
            'model_hash':model.MODEL_HASH,'catalog_hash':model.CATALOG_HASH,
            'strategy_hash':strategies.STRATEGY_HASH,'patterns':len(model.CATALOG),
            'matrices':arrays,'registry_markets':[]}
    if check_registry:
        from expanding_pipeline import ExpandingPipeline
        for symbol in ('NEARUSDT','SOLUSDT'):
            for tf in ('15m','1h','4h'):
                worker=ExpandingPipeline(tf,root/f'runtime/{symbol}_{tf}-identity-check.sqlite3',symbol)
                if not worker._load(int(time.time()*1000)):
                    raise ValueError(f'Registry market unavailable: {symbol}:{tf}')
                result['registry_markets'].append({'symbol':symbol,'timeframe':tf,'models':len(worker.models),'passed':True})
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--check-registry',action='store_true')
    args=parser.parse_args()
    try:
        print(json.dumps({'passed':True,**inspect(args.root.resolve(),args.check_registry)},indent=2))
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__,'error':str(error)}))
        raise SystemExit(2)
