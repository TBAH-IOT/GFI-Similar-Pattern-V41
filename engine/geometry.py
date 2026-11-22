"""Causal, scale-independent research definitions for classical price geometry.

These numerical tolerances are explicit engineering conventions, not a claim
that discretionary chart-pattern literature has one universal formal grammar.
All breakouts require a close crossing; pivots are supplied already confirmed.
"""
import numpy as np

SOURCE='https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-patterns'
BOUNDARY_NAMES=(
 'Ascending_Triangle','Descending_Triangle','Symmetrical_Triangle_Bullish','Symmetrical_Triangle_Bearish',
 'Rising_Wedge','Falling_Wedge','Rectangle_Bullish','Rectangle_Bearish',
 'Ascending_Channel_Bullish','Ascending_Channel_Bearish','Descending_Channel_Bullish','Descending_Channel_Bearish',
 'Symmetrical_Broadening_Bullish','Symmetrical_Broadening_Bearish',
 'Ascending_Broadening_Bullish','Ascending_Broadening_Bearish',
 'Descending_Broadening_Bullish','Descending_Broadening_Bearish',
 'Right_Angled_Ascending_Broadening_Bullish','Right_Angled_Ascending_Broadening_Bearish',
 'Right_Angled_Descending_Broadening_Bullish','Right_Angled_Descending_Broadening_Bearish')
REVERSALS=('Double_Top','Double_Bottom','Triple_Top','Triple_Bottom','Head_and_Shoulders_Top',
 'Head_and_Shoulders_Bottom','Complex_Head_and_Shoulders_Top','Complex_Head_and_Shoulders_Bottom')
OTHERS=('Flag_Bullish','Flag_Bearish','Pennant_Bullish','Pennant_Bearish','Diamond_Top','Diamond_Bottom',
 'Rounding_Bottom','Rounding_Top','Cup_and_Handle',
 'Inverted_Cup_and_Handle','Bump_and_Run_Top','Bump_and_Run_Bottom')
DEFINITIONS=[dict(name='Geometry_'+name,display_name=name.replace('_',' ')+' · Geometry',family='geometry',
    direction='confirmed close breakout',risk_rule='pattern_height',source=SOURCE,
    implementation='confirmed pivots / close crossings; geometry.py',
    minimum_confirmed_pivots=4,
    rule_group='boundary' if name in BOUNDARY_NAMES else 'reversal' if name in REVERSALS else 'structural')
    for name in BOUNDARY_NAMES+REVERSALS+OTHERS]
RULES={
 'pivot_window_bars':120,'minimum_confirmed_pivots':4,'minimum_boundary_touches_per_side':3,'boundary_fit_max_error':.12,
 'flat_slope_max':.12,'trend_slope_min':.18,'parallel_slope_difference_max':.20,
 'contraction_width_ratio':[.25,.85],'expansion_width_ratio':[1.25,3.5],
 'level_tolerance':.15,'head_prominence_min':.15,'pole_to_consolidation_min':1.5,
 'curve_windows':[20,40,80],'curve_sampling_stride':4,'confirmation':'previous close inside, current close outside',
 'volume_filter':False,'session_gap_rule':'actual high/low price gaps only, no fabricated market sessions'}

def _fit(points,side,start,span,height,minimum=3):
    p=[p for p in points if p[3]==side]
    if len(p)<minimum:return None
    x=np.array([(v[0]-start)/span for v in p]); y=np.array([v[2] for v in p])
    slope,intercept=np.polyfit(x,y,1)
    if max(abs(y-(slope*x+intercept)))>.12*height:return None
    return float(slope),float(intercept)

def _setup(name,p,sign,boundary,height,span=None):
    return dict(name='Geometry_'+name,points=p,sign=sign,boundary=boundary,height=float(height),
                start=p[0][0],span=span or max(1,p[-1][0]-p[0][0]))

def pivot_setups(points,history):
    if len(points)<5:return []
    output=[]
    def line_setup(name,p,sign,line,height):
        output.append(_setup(name,p,sign,line,height))
    # Six touches distinguish a boundary fit from a five-value shape template.
    if len(points)>=6:
        p=points[-6:]; h=max(v[2] for v in p)-min(v[2] for v in p); span=p[-1][0]-p[0][0]
        if h>0 and span>=8:
            up=_fit(p,1,p[0][0],span,h); lo=_fit(p,-1,p[0][0],span,h)
            if up and lo:
                su,bu=up; sl,bl=lo; w0=bu-bl; w1=su+bu-sl-bl
                if min(w0,w1)>.08*h:
                    u,l=su/h,sl/h; ratio=w1/w0
                    flat_u,flat_l=abs(u)<=.12,abs(l)<=.12
                    contract=.25<=ratio<=.85; expand=1.25<=ratio<=3.5
                    parallel=abs(u-l)<=.20
                    names=[]
                    if contract:
                        if flat_u and l>.18:names+=[('Ascending_Triangle',1)]
                        if flat_l and u<-.18:names+=[('Descending_Triangle',-1)]
                        if u<-.12 and l>.12:names += [('Symmetrical_Triangle_Bullish',1),('Symmetrical_Triangle_Bearish',-1)]
                        if u>.18 and l>u:names += [('Rising_Wedge',-1)]
                        if l<-.18 and u<l:names += [('Falling_Wedge',1)]
                    if flat_u and flat_l:names += [('Rectangle_Bullish',1),('Rectangle_Bearish',-1)]
                    if parallel and min(u,l)>.18:names += [('Ascending_Channel_Bullish',1),('Ascending_Channel_Bearish',-1)]
                    if parallel and max(u,l)<-.18:names += [('Descending_Channel_Bullish',1),('Descending_Channel_Bearish',-1)]
                    if expand:
                        if u>.12 and l<-.12:stem='Symmetrical_Broadening'
                        elif flat_l and u>.18:stem='Right_Angled_Ascending_Broadening'
                        elif flat_u and l<-.18:stem='Right_Angled_Descending_Broadening'
                        elif u>l>.12:stem='Ascending_Broadening'
                        elif l<u<-.12:stem='Descending_Broadening'
                        else:stem=None
                        if stem:names += [(stem+'_Bullish',1),(stem+'_Bearish',-1)]
                    for name,sign in names:line_setup(name,p,sign,up if sign==1 else lo,h)
                    if len(points)>=8:
                        pole=points[-8:-6]; impulse=pole[1][2]-pole[0][2]
                        if abs(impulse)>=1.5*h:
                            sign=1 if impulse>0 else -1
                            if parallel and (u+l)*sign<0:
                                line_setup('Flag_'+('Bullish' if sign==1 else 'Bearish'),points[-8:],sign,
                                           up if sign==1 else lo,abs(impulse))
                                output[-1].update(start=p[0][0],span=span)
                            if contract and u<0<l:
                                line_setup('Pennant_'+('Bullish' if sign==1 else 'Bearish'),points[-8:],sign,
                                           up if sign==1 else lo,abs(impulse))
                                output[-1].update(start=p[0][0],span=span)
    for length in (5,7,9):
        if len(points)<length:continue
        p=points[-length:]; h=max(v[2] for v in p)-min(v[2] for v in p)
        if h<=0:continue
        outer=p[::2]; inner=p[1::2]; side=p[0][3]
        sign=-side; levels=np.array([v[2] for v in outer]); oriented=levels*side
        level_range=float(np.ptp(levels))
        name=None
        if length==5 and level_range<=.15*h:name='Double_Top' if side==1 else 'Double_Bottom'
        if length==7 and level_range<=.15*h:name='Triple_Top' if side==1 else 'Triple_Bottom'
        if length==5 and oriented[1]>max(oriented[0],oriented[2])+.15*h and abs(levels[0]-levels[2])<=.20*h:
            name='Head_and_Shoulders_Top' if side==1 else 'Head_and_Shoulders_Bottom'
        if length==9 and oriented[2]>max(np.delete(oriented,2))+.15*h and np.ptp(np.delete(levels,2))<=.25*h:
            name='Complex_Head_and_Shoulders_Top' if side==1 else 'Complex_Head_and_Shoulders_Bottom'
        if name:
            # Reversal requires a pre-pattern trend, then a neckline crossing.
            earlier=[b['close'] for i,b in history if p[0][0]-20<=i<p[0][0]]
            if earlier and (p[0][2]-float(np.mean(earlier)))*side>.25*h:
                span=p[-1][0]-p[0][0]
                neck=_fit(inner,-side,p[0][0],span,h,minimum=2)
                if neck:line_setup(name,p,sign,neck,h)
    if len(points)>=9:
        p=points[-9:]; h=max(v[2] for v in p)-min(v[2] for v in p); span=p[-1][0]-p[0][0]
        if h>0 and span>0:
            fits=[_fit(q,s,p[0][0],span,h,2) for q in (p[:5],p[-5:]) for s in (1,-1)]
            if all(fits):
                leftu,leftl,rightu,rightl=fits
                if leftu[0]>.12*h and leftl[0]<-.12*h and rightu[0]<-.12*h and rightl[0]>.12*h:
                    for name,sign,line in [('Diamond_Top',-1,rightl),('Diamond_Bottom',1,rightu)]:
                        line_setup(name,p,sign,line,h)
    return output

def confirmed(setup,index,bar,previous):
    slope,intercept=setup['boundary']; span=setup['span']; start=setup['start']; sign=setup['sign']
    boundary=slope*(index-start)/span+intercept
    previous_boundary=slope*(index-1-start)/span+intercept
    return (bar['close']-boundary)*sign>0 and (previous['close']-previous_boundary)*sign<=0

def curve_matches(history):
    """Closed-price curves, pole/rollover and real island gaps; no future bars."""
    output=[]; index,bar=history[-1]; previous=history[-2][1]
    for size in ((20,40,80) if index%4==0 else ()):
        if len(history)<size+1:continue
        items=history[-size-1:-1]; y=np.array([b['close'] for _,b in items]); h=float(np.ptp(y))
        if h<=0:continue
        z=(y-y.min())/h; x=np.linspace(-1,1,size); a,b,c=np.polyfit(x,z,2)
        error=float(np.sqrt(np.mean((z-(a*x*x+b*x+c))**2)))
        picks=np.linspace(0,size-1,9).astype(int)
        points=[(items[j][0],items[j][1]['time'],items[j][1]['close'],0) for j in picks]
        def emit(name,sign,level):
            if (bar['close']-level)*sign>0 and (previous['close']-level)*sign<=0:
                output.append(dict(name='Geometry_'+name,points=points,sign=sign,height=h))
        if error<.13 and abs(b)<.20:
            if a>.65 and max(z[:size//4])>.65 and max(z[-size//4:])>.65:
                emit('Rounding_Bottom',1,max(y[:size//4]))
            if a<-.65 and min(z[:size//4])<.35 and min(z[-size//4:])<.35:
                emit('Rounding_Top',-1,min(y[:size//4]))
        # Cup occupies 80% of the window; a shallow handle follows the right rim.
        k=int(size*.8); cup=y[:k]; handle=y[k:]; xx=np.linspace(-1,1,k)
        aa,bb,cc=np.polyfit(xx,(cup-y.min())/h,2)
        cup_error=float(np.sqrt(np.mean(((cup-y.min())/h-(aa*xx*xx+bb*xx+cc))**2)))
        if cup_error<.14 and abs(bb)<.25:
            if aa>.6 and abs(cup[0]-cup[-1])<.25*h and .08*h<max(cup)-min(handle)<.45*h:
                emit('Cup_and_Handle',1,max(cup))
            if aa<-.6 and abs(cup[0]-cup[-1])<.25*h and .08*h<max(handle)-min(cup)<.45*h:
                emit('Inverted_Cup_and_Handle',-1,min(cup))
        # Scale-independent approximation of lead-in / accelerated bump / run.
        k=size//3; t=np.arange(size); s0,b0=np.polyfit(t[:k],y[:k],1); s1,_=np.polyfit(t[k:2*k],y[k:2*k],1)
        baseline=s0*t+b0; lead=max(abs(y[:k]-baseline[:k])); bump=max(abs(y[k:]-baseline[k:]))
        if lead>.01*h and bump>=2*lead and abs(s0)*size>.2*h and abs(s1)>1.5*abs(s0) and s0*s1>0:
            sign=-1 if s0>0 else 1
            if (bar['close']-(s0*size+b0))*sign>0 and (previous['close']-baseline[-1])*sign<=0:
                output.append(dict(name='Geometry_Bump_and_Run_'+('Top' if sign==-1 else 'Bottom'),points=points,sign=sign,height=h))
    return output
