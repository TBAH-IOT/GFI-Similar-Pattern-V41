"""One causal chart-only scanner shared by historical research and live use."""
from collections import deque
import hashlib
import json
from pathlib import Path
import numpy as np
from pattern_catalog import CATALOG,CHARTS,BY_NAME
from curve_search import candidates,islands,METHOD as CURVE_METHOD
from specialized_patterns import SpecializedScanner,WEEKLY_METHOD,GAP_METHOD

VERSION='causal-price-charts-v11-adaptive-coverage-no-weekly'
METHODS=('Pivot Window Calibrated','EMA Peaks Calibrated','ZigZag Calibrated','Close Path 20/4',CURVE_METHOD,'Actual Gap Island',WEEKLY_METHOD,GAP_METHOD)
TF_SECONDS={'15m':900,'1h':3600,'4h':14400,'1d':86400,'1w':604800}
CATALOG_HASH=hashlib.sha256(json.dumps(CATALOG,sort_keys=True).encode()).hexdigest()
MODEL_IDENTITY_SCHEMA='source-and-canonical-binary64-v1'
MODEL_SOURCE_FILES=('research_model.py','pattern_catalog.py','chart_library.py','curve_search.py',
                    'specialized_patterns.py','expanding_pipeline.py',
                    'canonical_catalog.py','canonical_price_catalog.json')
MODEL_HASH=hashlib.sha256(MODEL_IDENTITY_SCHEMA.encode()+b'\0'+b''.join(
    n.encode()+b'\0'+hashlib.sha256(Path(__file__).with_name(n).read_bytes()).digest()
    for n in MODEL_SOURCE_FILES)).hexdigest()
TEMPLATES=np.array([item['template'] for item in CHARTS])


class Scanner:
    def __init__(self,symbol,tf,models=None,candles=None,calibration=None):
        self.symbol,self.tf,self.models=symbol,tf,models
        settings=calibration or {}
        self.pivot_radius=int(settings.get('pivot_radius',4))
        self.ema_span=int(settings.get('ema_span',5))
        self.ema_radius=int(settings.get('ema_peak_radius',3))
        self.i=-1;self.bars=deque(maxlen=120);self.smooth=deque(maxlen=2*self.ema_radius+1);self.ema=None
        self.pivots={m:deque(maxlen=9) for m in METHODS[:3]}
        self.special=SpecializedScanner(TF_SECONDS[tf],enable_weekly=tf=='1w')
        self.zig_trend=-1;self.zig_ext=None;self.seen={};self.score_cache={};self.curve_pending={}
        self.candle_values=candles  # Empty compatibility matrix; never evaluated.
        self.zig_reversal_pct=(calibration or {}).get('zigzag_reversal_pct',.005)

    def _record(self,item,method,points,bar,score,height,sign,detail):
        if item['status']!='searchable' or height<=0:return None
        profile=self.models.get((item['name'],method)) if self.models is not None else None
        if self.models is not None and (not profile or score<profile['threshold']):return None
        key=(item['name'],method,sign,tuple(p[1] for p in points))
        if self.seen.get(key[:3])==key[3]:return None
        self.seen[key[:3]]=key[3]
        result=dict(index=self.i,name=item['name'],method=method,score=float(score),height=float(height),sign=sign,
                    confirmed_pivot_count=sum(p[3] in (-1,1) for p in points))
        if detail:
            stable=hashlib.sha256(repr((self.symbol,self.tf,key)).encode()).hexdigest()[:24]
            result.update(id=f'{self.symbol}-{self.tf}-{stable}',symbol=self.symbol,ticker=self.symbol[:-4],tf=self.tf,
                display_name=item['display_name'],family='chart',group=item['group'],direction='LONG' if sign==1 else 'SHORT',
                detected_at=bar['time'],available_at=bar['time']+TF_SECONDS[self.tf],similarity=float(score)*100,
                points=[dict(time=p[1],value=float(p[2]),confirmed=p[3] in (-1,1)) for p in points],
                model_version=VERSION,model_hash=MODEL_HASH,recognition=item['recognition'],
                configured_win_rate=profile['test']['win_rate'] if profile else None,
                validation_samples=profile['test']['n'] if profile else None,
                accuracy_source='expanding_oos',threshold=profile['threshold'] if profile else .85)
        return result

    def _append(self,method,pivot):
        points=self.pivots[method]
        if points and pivot[3]==points[-1][3]:
            if (pivot[2]-points[-1][2])*pivot[3]<=0:return False
            points[-1]=pivot
        elif not points or pivot[0]>points[-1][0]:points.append(pivot)
        else:return False
        return True

    def _match(self,method,points,bar,detail):
        points=points[-5:]
        if len(points)!=5 or self.i-points[0][0]>=120 or self.i-points[-1][0]>10:return []
        shape_key=tuple((p[1],p[2]) for p in points);cached=self.score_cache.get(method)
        changed=not cached or cached[0]!=shape_key
        if changed:
            values=np.array([p[2] for p in points]);height=float(np.ptp(values))
            if height<=0:return []
            scores=1-np.linalg.norm(TEMPLATES-(values-values.min())/height,axis=1)/np.sqrt(5)
            self.score_cache[method]=(shape_key,values,height,scores)
        else:_,values,height,scores=cached
        output=[]
        for k in np.flatnonzero(scores>=.85):
            item=CHARTS[k];direction=item['direction']
            if not changed and direction!='Breakout':continue
            if direction=='Breakout':
                direction='Up' if bar['close']>values.max() else 'Down' if bar['close']<values.min() else None
                if direction is None:continue
            record=self._record(item,method,points,bar,float(scores[k]),height,1 if direction=='Up' else -1,detail)
            if record:output.append(record)
        return output

    def _curves(self,bar,detail):
        history=list(self.bars);output=[]
        for name,setup in list(self.curve_pending.items()):
            if self.i-setup['index']>12:
                del self.curve_pending[name];continue
            previous=history[-2][1]['close']
            sign=1 if previous<=setup['upper']<bar['close'] else -1 if previous>=setup['lower']>bar['close'] else 0
            if sign:
                points=setup['points']+[(self.i,bar['time'],bar['close'],0)]
                record=self._record(setup['item'],CURVE_METHOD,points,bar,setup['score'],setup['height'],sign,detail)
                if record:output.append(record)
                del self.curve_pending[name]
        for setup in candidates(history):
            item=setup['item']
            if item['direction']=='Breakout':
                self.curve_pending.setdefault(item['name'],setup);continue
            record=self._record(item,CURVE_METHOD,setup['points'],bar,setup['score'],setup['height'],1 if item['direction']=='Up' else -1,detail)
            if record:output.append(record)
        for setup in islands(history):
            record=self._record(setup['item'],METHODS[5],setup['points'],bar,setup['score'],setup['height'],setup['sign'],detail)
            if record:output.append(record)
        return output

    def step(self,bar,detail=True):
        self.i+=1;self.bars.append((self.i,bar))
        self.ema=bar['close'] if self.ema is None else self.ema+(bar['close']-self.ema)*2/(self.ema_span+1)
        self.smooth.append((self.i,bar['time'],self.ema));changed=set()
        window=2*self.pivot_radius+1
        if len(self.bars)>=window:
            neighborhood=list(self.bars)[-window:];pos,center=neighborhood[self.pivot_radius]
            high=max(b['high'] for _,b in neighborhood);low=min(b['low'] for _,b in neighborhood)
            peak=center['high']==high and sum(b['high']==high for _,b in neighborhood)==1
            trough=center['low']==low and sum(b['low']==low for _,b in neighborhood)==1
            if peak!=trough and self._append(METHODS[0],(pos,center['time'],center['high'] if peak else center['low'],1 if peak else -1)):
                changed.add(METHODS[0])
        if len(self.smooth)==2*self.ema_radius+1:
            points=list(self.smooth);pos,ts,value=points[self.ema_radius]
            peak=all(value>p[2] for j,p in enumerate(points) if j!=self.ema_radius)
            trough=all(value<p[2] for j,p in enumerate(points) if j!=self.ema_radius)
            if (peak or trough) and self._append(METHODS[1],(pos,ts,value,1 if peak else -1)):changed.add(METHODS[1])
        price=bar['close'];current=(self.i,bar['time'],price,self.zig_trend)
        if self.zig_ext is None:self.zig_ext=current
        elif (price-self.zig_ext[2])*self.zig_trend>=0:self.zig_ext=current
        elif (self.zig_trend<0 and price>=self.zig_ext[2]*(1+self.zig_reversal_pct)) or (self.zig_trend>0 and price<=self.zig_ext[2]*(1-self.zig_reversal_pct)):
            if self._append(METHODS[2],self.zig_ext):changed.add(METHODS[2])
            self.zig_trend*=-1;self.zig_ext=(self.i,bar['time'],price,self.zig_trend)
        output=[]
        for setup in self.special.step(list(self.bars),self.pivots):
            record=self._record(BY_NAME[setup['name']],setup['method'],setup['points'],bar,setup['score'],setup['height'],setup['sign'],detail)
            if record:
                if detail:record['context_timeframe']='1w' if setup['context']=='weekly' else self.tf
                output.append(record)
        # Each detector checks its own required history. 120 remains the
        # maximum template span/buffer, never a shared startup delay.
        for method,points in self.pivots.items():
            output.extend(self._match(method,list(points),bar,detail))
        if len(self.bars)>=21 and self.i%4==0:
            history=list(self.bars);points=[(pos,b['time'],b['close'],0) for pos,b in history[-21::5]]
            output.extend(self._match(METHODS[3],points,bar,detail))
        # Curves independently require 24/48/96 bars; islands require >=4.
        output.extend(self._curves(bar,detail))
        return output
