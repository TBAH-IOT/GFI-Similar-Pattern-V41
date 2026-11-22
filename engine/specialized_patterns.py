"""Causal numerical rules for the 15 specialised price-chart definitions.

Tolerances are explicit engineering conventions, not a reproduction of private
courses or every discretionary textbook condition. Weekly-only definitions
are evaluated on 1W using completed UTC weeks, never an unfinished week.
"""
from collections import deque
import numpy as np

DAY=86400
WEEK=7*DAY
WEEKLY_METHOD='Closed Weekly Context'
GAP_METHOD='Causal Gap Classification'
RULES={
 'Roof':dict(touches=3,flat_level_tolerance=.12,central_peak_prominence=.2,confirmation='close crosses one boundary'),
 'Wolfe':dict(pivots=5,overshoot_max=.25,time_leg_ratio=[.4,2.5],confirmation='confirmed point5 and close re-enters 1-3 boundary'),
 'Weekly_spikes':dict(prior_weeks=52,length_percentile=.75,level_tolerance=.15,expiry_weeks=12,confirmation='weekly close outside complete 2/3-bar pattern'),
 'Cloudbank':dict(base_weeks=104,base_slope_max=.15,base_floor_ratio_min=.9,base_touch_fraction=.08,drop_min=.4,moving_average_weeks=30,confirmation='closed week crosses 30-week mean with >=40% remaining to base'),
 'Diving_Board':dict(base_weeks=26,base_floor_ratio_min=.9,maximum_tail_weeks=26,plunge_min=.14,confirmation='weekly close above board high'),
 'Lindsay':dict(confirmed_points='3 through 27',three_peak_days=[180,300],house_days=[175,265],confirmation='close below point26 after point27; point28 is not read from the future'),
 'Gaps':dict(range_bars=20,runaway_wait_bars=2,fill_confirmation_max_bars=10,confirmation='real high/low gaps; common/exhaustion only at later reversal close; no backdating'),
}


def point(bar,side=0,index=0):
    return (index,bar['time'],float(bar['high'] if side==1 else bar['low'] if side==-1 else bar['close']),side)


def event(name,points,sign,height,method,context='chart'):
    return dict(name=name,points=points,sign=sign,height=float(height),score=1.,method=method,context=context)


def geometry(points,bar,previous,method,index):
    out=[]
    if len(points)>=5:
        p=points[-5:];h=max(q[2] for q in p)-min(q[2] for q in p)
        for sign in (1,-1):
            if h<=0 or [q[3] for q in p]!=[-sign,sign,-sign,sign,-sign]:continue
            x=[q[0] for q in p]; y=[q[2]*sign for q in p]
            if not(y[0]>y[2]>y[4] and y[1]>y[3]>y[0]):continue
            lower=(y[2]-y[0])/(x[2]-x[0]);upper=(y[3]-y[1])/(x[3]-x[1])
            if not upper<lower<0:continue
            expected=y[0]+lower*(x[4]-x[0]);overshoot=expected-y[4]
            ratio=(x[4]-x[2])/(x[2]-x[0])
            if not 0<=overshoot<=.25*h or not .4<=ratio<=2.5:continue
            boundary=y[0]+lower*(index-x[0])
            if bar['close']*sign>boundary:
                out.append(event('Wolfe_Wave_'+('Bullish' if sign==1 else 'Bearish'),p,sign,h,method))
    if len(points)>=6:
        p=points[-6:];h=max(q[2] for q in p)-min(q[2] for q in p)
        if h<=0:return out
        for flip,name in [(1,'Roof'),(-1,'Roof_Inverted')]:
            highs=[q for q in p if q[3]==flip];lows=[q for q in p if q[3]==-flip]
            if len(highs)!=3 or len(lows)!=3:continue
            hi=[q[2]*flip for q in highs];lo=[q[2]*flip for q in lows]
            if max(lo)-min(lo)>.12*h or hi[1]<max(hi[0],hi[2])+.2*h:continue
            flat=sum(lo)/3;slope=(hi[2]-hi[1])/(highs[2][0]-highs[1][0])
            upper=hi[2]+slope*(index-highs[2][0]);upper_prev=upper-slope
            current=bar['close']*flip;old=previous['close']*flip
            sign=-flip if current<flat<=old else flip if current>upper and old<=upper_prev else 0
            if sign:out.append(event(name,p,sign,h,method))
    return out


def lindsay(points,bar,previous):
    if len(points)<25:return []
    p=points[-25:] # Numbered 3..27, alternating peak/trough; 28 is future.
    if [q[3] for q in p]!=[1 if i%2==0 else -1 for i in range(25)]:return []
    v=np.array([q[2] for q in p]);h=float(np.ptp(v))
    if h<=0:return []
    at=lambda n:v[n-3]
    span1=(p[4][1]-p[0][1])/DAY;span2=(p[20][1]-p[11][1])/DAY
    if not(180<=span1<=300 and 175<=span2<=265):return []
    if np.ptp(v[[0,2,4]])>.2*h or at(10)>=min(at(4),at(6)):return []
    if np.ptp([at(10),at(12),at(14)])>.2*h:return []
    if at(15)-at(14)<.2*h or np.ptp(v[12:18])>.25*h or at(21)-at(20)<.15*h:return []
    if at(23)<=max(at(21),at(25)) or not at(26)<at(27)<at(25):return []
    if abs(at(27)-at(15))>.2*h:return []
    if bar['close']<at(26)<=previous['close']:
        return [event('Three_Peaks_and_Domed_House',p,-1,h,WEEKLY_METHOD,'weekly')]
    return []


def weekly_setups(history):
    """Build hypotheses only from already closed weeks, without performance."""
    output=[]
    if len(history)<54:return output
    for size,stem in [(2,'Pipe'),(3,'Horn')]:
        if len(history)<size+52:continue
        p=history[-size:];a,c=p[0],p[-1];h=max(b['high'] for b in p)-min(b['low'] for b in p)
        baseline=history[-size-52:-size];length=np.quantile([b['high']-b['low'] for b in baseline],.75)
        if h<=0 or min(a['high']-a['low'],c['high']-c['low'])<length:continue
        for sign in (-1,1):
            side=-sign;extreme=lambda b:b['high'] if side==1 else b['low']
            if abs(extreme(a)-extreme(c))>.15*h:continue
            trend=(a['close']-np.mean([b['close'] for b in baseline[-12:]]))*side
            if trend<=.15*h:continue
            if size==3 and min(extreme(a)*side,extreme(c)*side)<=extreme(p[1])*side+.1*h:continue
            if size==2 and min(a['high'],c['high'])-max(a['low'],c['low'])<.5*min(a['high']-a['low'],c['high']-c['low']):continue
            edge=max(b['high'] for b in p) if sign==1 else min(b['low'] for b in p)
            output.append(dict(name=stem+('_Bottom' if sign==1 else '_Top'),points=[point(b,side) for b in p],
                               sign=sign,level=edge,height=h,end=p[-1]['time'],age=0))
    return output


def long_context(history):
    out=[]
    if len(history)<56:return out
    last,previous=history[-1],history[-2]
    for tail in range(4,min(26,len(history)-26)+1):
        board=history[-tail-26:-tail];after=history[-tail:]
        lows=np.array([b['low'] for b in board]);base=float(np.quantile(lows,.2));top=max(b['high'] for b in board)
        if base<=0 or min(lows)<.9*base or np.mean(abs(lows-base)<=.04*base)<.3:continue
        if abs(np.polyfit(np.arange(26),[b['close'] for b in board],1)[0])*26>.2*base:continue
        bottom=min(b['low'] for b in after);lowpos=min(range(tail),key=lambda j:after[j]['low'])
        if bottom>.86*base or lowpos>8 or lowpos>=tail-1:continue
        # Avoid a fresh second lower plunge after recovery has started.
        rebounds=sum(after[j]['low']<after[j-1]['low'] and after[j-1]['close']>base for j in range(lowpos+1,tail))
        if rebounds or not last['close']>top>=previous['close']:continue
        p=board+after;points=[point(b,0) for b in p]
        found=event('Diving_Board',points,1,top-bottom,WEEKLY_METHOD,'weekly')
        found['episode']=after[lowpos]['time'];out.append(found);break
    if len(history)>=136:
        mean=float(np.mean([b['close'] for b in history[-30:]]));oldmean=float(np.mean([b['close'] for b in history[-31:-1]]))
        if last['close']>mean and previous['close']<=oldmean:
            for tail in range(4,min(52,len(history)-104)+1):
                board=history[-tail-104:-tail];after=history[-tail:]
                lows=np.array([b['low'] for b in board]);base=float(np.quantile(lows,.2))
                if min(lows)<.9*base or np.mean(abs(lows-base)<=.04*base)<.3:continue
                if abs(np.polyfit(np.arange(104),[b['close'] for b in board],1)[0])*104>.15*base:continue
                bottom=min(b['low'] for b in after)
                if bottom<=.6*base and bottom<last['close']<=.6*base:
                    found=event('Cloudbank',[point(b) for b in board+after],1,last['close']-bottom,WEEKLY_METHOD,'weekly')
                    found['episode']=min(after,key=lambda b:b['low'])['time'];out.append(found);break
    return out


class SpecializedScanner:
    def __init__(self,step,enable_weekly=True):
        self.step_seconds=step;self.week=None;self.week_complete=False
        self.enable_weekly=enable_weekly
        self.weeks=deque(maxlen=400);self.pending_weekly={};self.week_pivots=deque(maxlen=30)
        self.long_seen=set()
        self.gaps=[];self.last_breakaway={};self.week_index=-1

    def _weekly(self,bar):
        # UTC Monday buckets. Ignore an incomplete first week and any week
        # containing missing source bars (Scanner resets us on source gaps).
        bucket=((bar['time']+3*DAY)//WEEK)*WEEK-3*DAY
        if self.week is None or self.week['time']!=bucket:
            self.week=dict(bar,time=bucket)
            self.week_complete=bar['time']==bucket
        else:
            self.week.update(high=max(self.week['high'],bar['high']),low=min(self.week['low'],bar['low']),
                             close=bar['close'],volume=self.week['volume']+bar['volume'])
        if bar['time']+self.step_seconds!=bucket+WEEK or not self.week_complete:return []
        closed=dict(self.week);self.weeks.append(closed);self.week_index+=1
        history=list(self.weeks);out=[]
        if len(history)>=2:
            for name,s in list(self.pending_weekly.items()):
                s['age']+=1
                if (closed['close']-s['level'])*s['sign']>0 and (history[-2]['close']-s['level'])*s['sign']<=0:
                    out.append(event(name,s['points'],s['sign'],s['height'],WEEKLY_METHOD,'weekly'));del self.pending_weekly[name]
                elif s['age']>12:del self.pending_weekly[name]
        for s in weekly_setups(history):self.pending_weekly[s['name']]=s
        for found in long_context(history):
            key=(found['name'],found['episode'])
            if key not in self.long_seen:
                self.long_seen.add(key);out.append(found)
        if len(history)>=3:
            p=history[-2];left,right=history[-3],history[-1]
            side=1 if p['high']>max(left['high'],right['high']) else -1 if p['low']<min(left['low'],right['low']) else 0
            # Outside bars have unknown intrabar pivot order.
            if p['high']>max(left['high'],right['high']) and p['low']<min(left['low'],right['low']):side=0
            if side:
                pivot=point(p,side,self.week_index-1)
                if self.week_pivots and self.week_pivots[-1][3]==side:
                    if (pivot[2]-self.week_pivots[-1][2])*side>0:self.week_pivots[-1]=pivot
                else:self.week_pivots.append(pivot)
            out.extend(lindsay(list(self.week_pivots),closed,history[-2]))
        return out

    def _gaps(self,history):
        index,bar=history[-1];_,previous=history[-2];out=[]
        for g in list(self.gaps):
            age=index-g['index'];sign=g['sign'];level=g['level']
            reversal=(bar['close']-level)*sign<0
            if reversal:
                name='Gap_Exhaustion' if g['trending'] else 'Gap_Common'
                out.append(event(name,g['points']+[point(bar,0,index)],-sign,g['height'],GAP_METHOD));self.gaps.remove(g)
            elif age==2 and g['prior_breakaway'] and (bar['low']>level if sign==1 else bar['high']<level):
                out.append(event('Gap_Runaway',g['points']+[point(bar,0,index)],sign,g['height'],GAP_METHOD));self.gaps.remove(g)
            elif age>10:self.gaps.remove(g)
        sign=1 if bar['low']>previous['high'] else -1 if bar['high']<previous['low'] else 0
        if not sign or len(history)<22:return out
        rows=[b for _,b in history[-21:-1]];tr=float(np.median([b['high']-b['low'] for b in rows]));tr=max(tr,1e-12)
        high=max(b['high'] for b in rows);low=min(b['low'] for b in rows)
        trending=(previous['close']-rows[0]['close'])*sign>=2*tr
        points=[point(previous,0,index-1),point(bar,0,index)];height=max(bar['high'],previous['high'])-min(bar['low'],previous['low'])
        if not trending and high-low<=4*tr and (bar['close']>high if sign==1 else bar['close']<low):
            out.append(event('Gap_Breakaway',points,sign,height,GAP_METHOD));self.last_breakaway[sign]=index
        else:
            self.gaps.append(dict(index=index,sign=sign,level=previous['high'] if sign==1 else previous['low'],
                trending=trending,prior_breakaway=index-self.last_breakaway.get(sign,-1000)<=60,points=points,height=height))
        return out

    def step(self,history,pivots):
        out=self._weekly(history[-1][1]) if self.enable_weekly else []
        if len(history)>=2:
            index,bar=history[-1];previous=history[-2][1]
            out.extend(self._gaps(history))
            for method,p in pivots.items():out.extend(geometry(list(p),bar,previous,method,index))
        return out
