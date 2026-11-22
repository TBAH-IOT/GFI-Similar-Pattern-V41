"""TEST ONLY: perturb the math implementation before loading the real model."""
import argparse
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--ulp',type=int,choices=(-1,0,1),default=0)
parser.add_argument('--forbid-sine',action='store_true')
args=parser.parse_args()
import numpy as np
import pandas
import scipy.signal
import scipy.spatial.distance
original=np.sin
if args.forbid_sine:
    def forbidden(*a,**k):raise AssertionError('Runtime sine must not construct price prototypes')
    np.sin=forbidden
elif args.ulp:
    np.sin=lambda *a,**k:np.nextafter(original(*a,**k),np.inf if args.ulp>0 else -np.inf)
sys.path.insert(0,str(args.root/'tools'))
from model_identity import inspect
try:
    print(json.dumps({'passed':True,'test_sine_ulp':args.ulp,'test_forbid_sine':args.forbid_sine,**inspect(args.root,True)}))
except Exception as error:
    print(json.dumps({'passed':False,'error_type':type(error).__name__,'error':str(error)}))
    raise SystemExit(2)
