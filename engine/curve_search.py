"""Causal dense-path similarity search and actual-gap island recognition."""
import numpy as np
from chart_library import CURVES, BY_NAME
from canonical_catalog import load_catalog

WINDOWS=(24,48,96)
SAMPLES=32
METHOD='Curve Similarity 24/48/96'
_CANONICAL_CURVES=load_catalog()['curve_matrices']
GRID=np.array(_CANONICAL_CURVES['grid'],dtype=np.float64)
TEMPLATES=np.array(_CANONICAL_CURVES['templates'],dtype=np.float64)
CENTERED=np.array(_CANONICAL_CURVES['centered'],dtype=np.float64)
NORMS=np.array(_CANONICAL_CURVES['norms'],dtype=np.float64)


def candidates(history):
    index,bar=history[-1]
    if index%4:return []
    best={}
    for size in WINDOWS:
        if len(history)<size:continue
        rows=history[-size:]
        prices=np.array([b['close'] for _,b in rows]);height=float(np.ptp(prices))
        if height<=0:continue
        y=np.interp(GRID,np.linspace(0,1,size),(prices-prices.min())/height)
        centered=y-y.mean();norm=np.linalg.norm(centered)
        if norm<=1e-12:continue
        scores=1-np.sqrt(np.mean((TEMPLATES-y)**2,axis=1))
        correlations=(CENTERED@centered)/(NORMS*norm)
        for k in np.flatnonzero((scores>=.85)&(correlations>=.80)):
            item=CURVES[k];name=item['name']
            if name=='High_and_Tight_Flag' and max(prices[:size//2])/min(prices[:size//2])-1<.90:continue
            if name in best and best[name]['score']>=scores[k]:continue
            picks=np.unique(np.linspace(0,size-1,min(32,size)).astype(int))
            points=[(rows[j][0],rows[j][1]['time'],float(rows[j][1]['close']),0) for j in picks]
            best[name]=dict(item=item,points=points,score=float(scores[k]),height=height,
                            upper=float(prices.max()),lower=float(prices.min()),index=index)
    return list(best.values())


def islands(history):
    if len(history)<4:return []
    _,bar=history[-1];output=[]
    for size in range(2,min(10,len(history)-2)+1):
        rows=history[-size-1:-1];_,before=history[-size-2]
        low=min(b['low'] for _,b in rows);high=max(b['high'] for _,b in rows)
        sign=-1 if low>before['high'] and bar['high']<low else 1 if high<before['low'] and bar['low']>high else 0
        if not sign:continue
        name='Island_Reversal_'+('Bottom' if sign==1 else 'Top')
        selected=history[-size-2:]
        output.append(dict(item=BY_NAME[name],points=[(i,b['time'],float(b['close']),0) for i,b in selected],
                           score=1.,height=float(high-low),sign=sign))
    return output
