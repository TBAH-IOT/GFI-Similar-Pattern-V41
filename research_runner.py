"""Reproducible full-catalogue calibration. No orders/accounts are accessed."""
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import math
import shutil
from pathlib import Path
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from scipy.stats import binomtest, false_discovery_control

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"engine"))
from research_model import Scanner,CATALOG,CATALOG_HASH,MODEL_HASH,VERSION,METHODS,TF_SECONDS
from pattern_catalog import candle_matrix,coverage
from strategy_catalog import STRATEGIES,STRATEGY_HASH,variants,fixed_configurations
from eligibility import minimum_samples,SAMPLE_POLICY

HISTORY=ROOT/"runtime/history"
REGISTRY=ROOT/"runtime/research-registry.json"
REPORT=ROOT/"research-results.json"
PROGRESS=ROOT/"runtime/research-progress.json"
PREVIOUS=json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else {}
SETTINGS_PATH=ROOT/"research-settings.json"
SETTINGS=json.loads(SETTINGS_PATH.read_text(encoding="utf-8")) if SETTINGS_PATH.exists() else {}
MIN_TEST_SAMPLES_BY_TF=SETTINGS.get("activation_min_samples_by_timeframe", {"15m":100,"1h":75,"4h":50,"1d":30})
POLICY={"win_rate_gt":.55,"min_test_samples":50,"min_test_samples_by_timeframe":MIN_TEST_SAMPLES_BY_TF,"reward_risk":1,"horizon_bars":48,
        "entry":"next_candle_open","ambiguous":"non_win","expired":"non_win",
        "split":[.2,.8],"purge_bars":0,"min_validation_samples":None,
        "fixed_similarity_threshold":.85,"round_trip_cost":.003,
        "configuration_selection":"all applicable detectors and fixed similarity threshold; only the per-market sample-floor rung is selected after holdout to pursue the declared coverage target",
        "setup_uses_trade_outcomes":False,
        "warmup":"detector-specific requirements; no shared 120-bar startup gate",
        "risk_distance":"full pattern height or declared specialist rule; unchanged",
        "overlap":"all distinct detections; simultaneous observations per pattern/method/direction allowed",
        "statistical_assumption":"Wilson/binomial values are nominal; within-sample overlap correlations are not adjusted",
        "multiple_testing":"BY-adjusted nominal p-values reported; not proof of significance for dependent observations",
        "coverage_target":"at least 2 qualified configurations per coin and timeframe when the fixed evidence floor permits; not forced if accuracy fails",
        "coverage_floor_note":"The default floor is 15m=100, 1h=75, 4h=50, 1D=30. A predeclared ladder may lower it only to the allowed floors 15m=50, 1h=30, 4h=20, 1D=15 to fill the coverage target; low-N results are visibly cautioned in the UI"}
POLICY.update(configuration_fraction=.2,holdout_fraction=.8,accuracy_anchor="holdout_start",live_accuracy="expanding",deactivate_below=.55,
              split_policy_id=SETTINGS.get('split_policy_id','chronological-calibration20-test80-v1'))
POLICY['sample_policy_mode']='fixed'
POLICY['weekly_timeframe_removed']=True
POLICY['coverage_target_per_market']=int(SETTINGS.get('coverage_target_per_market',2))
POLICY['sample_ladder_by_timeframe']=SETTINGS.get('sample_ladder_by_timeframe',{
    '15m':[100,75,50],'1h':[75,50,30],
    '4h':[50,30,20],'1d':[30,20,15]})
POLICY['coverage_selection_uses_holdout_outcomes']=True

def min_test_samples(tf,anchor=0,as_of=0):
    return minimum_samples(tf,anchor,as_of,POLICY)


def apply_market_coverage_policy(report):
    """Choose a predeclared per-market sample floor to reach two qualified rows.

    This is deliberately recorded as an exploratory coverage policy: it uses
    the holdout labels to choose a rung, so it is not an independent claim of
    statistical significance. Accuracy must still be strictly above 55%.
    """
    target=int(POLICY['coverage_target_per_market'])
    selected={}; coverage={}
    for key,market in report['markets'].items():
        symbol,tf=key.split(':')
        rows=[row for row in report['results'] if row['symbol']==symbol and row['timeframe']==tf]
        base=int(MIN_TEST_SAMPLES_BY_TF[tf])
        ladder=[]
        for floor in POLICY['sample_ladder_by_timeframe'].get(tf,[base]):
            floor=int(floor)
            if floor<=base and floor not in ladder:
                ladder.append(floor)
        if base not in ladder:
            ladder.insert(0,base)
        effective=ladder[-1]
        for floor in ladder:
            count=sum(row['test']['n']>=floor and row['test']['win_rate'] is not None and row['test']['win_rate']>.55 for row in rows)
            if count>=target:
                effective=floor
                break
        qualified_count=sum(row['test']['n']>=effective and row['test']['win_rate'] is not None and row['test']['win_rate']>.55 for row in rows)
        for row in rows:
            row['minimum_test_samples']=effective
            row['qualified']=row['test']['n']>=effective and row['test']['win_rate'] is not None and row['test']['win_rate']>.55
            row['status']='qualified' if row['qualified'] else 'insufficient_test_samples' if row['test']['n']<effective else 'win_rate_not_above_55'
        selected[key]=effective
        coverage[key]={'target':target,'base_minimum':base,'effective_minimum':effective,
                       'qualified_configurations':qualified_count,'target_met':qualified_count>=target,
                       'selected_from_predeclared_ladder':True,
                       'selection_caveat':'holdout-driven coverage selection; exploratory, not an independent validation'}
        market['minimum_test_samples']=effective
    POLICY['minimum_samples_by_market']=selected
    report['coverage_by_market']=coverage


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding="utf-8")
    temp.replace(path)


def get_api(path,**params):
    url="https://data-api.binance.vision"+path+"?"+urlencode(params)
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={"User-Agent":"GFI-Pattern-Research/1.0"}),timeout=20) as response:
                return json.load(response)
        except Exception:
            if attempt==3:
                raise
            time.sleep(min(2**attempt,4))


def load_history(symbol,tf,now_ms):
    HISTORY.mkdir(parents=True,exist_ok=True)
    filename=HISTORY/f"{symbol}_{tf}.csv.gz"
    old=pd.read_csv(filename) if filename.exists() else pd.DataFrame()
    step=TF_SECONDS[tf]*1000
    first=int(get_api("/api/v3/klines",symbol=symbol,interval=tf,startTime=0,limit=1)[0][0])
    ranges=[]
    if old.empty:
        start=first
    else:
        old_first=int(old.time.iloc[0])*1000
        old_last=int(old.time.iloc[-1])*1000
        # Repair a truncated cache before appending new candles so research
        # always covers the complete listing history.
        if old_first>first:
            ranges.extend((s,min(s+1000*step-1,old_first-1)) for s in range(first,old_first,1000*step))
        start=old_last
    ranges.extend((s,min(s+1000*step-1,now_ms)) for s in range(start,now_ms+1,1000*step))
    def page(bounds):
        return get_api("/api/v3/klines",symbol=symbol,interval=tf,startTime=bounds[0],endTime=bounds[1],limit=1000)
    records=[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        for rows in executor.map(page,ranges):
            records.extend({"time":int(r[0])//1000,"open":float(r[1]),"high":float(r[2]),
                            "low":float(r[3]),"close":float(r[4]),"volume":float(r[5])}
                           for r in rows if int(r[6])<now_ms)
    fresh=pd.DataFrame(records)
    df=pd.concat([old,fresh],ignore_index=True).drop_duplicates("time",keep="last").sort_values("time").reset_index(drop=True)
    df=df[(df.time+TF_SECONDS[tf])*1000<=now_ms].reset_index(drop=True)
    numeric=df[["open","high","low","close","volume"]].to_numpy()
    if not np.isfinite(numeric).all() or (df.low<=0).any() or (df.volume<0).any() or (df.low>df[["open","close"]].min(axis=1)).any() or (df.high<df[["open","close"]].max(axis=1)).any():
        raise ValueError(f"Invalid OHLCV {symbol} {tf}")
    temp=filename.with_suffix(".tmp.gz")
    df.to_csv(temp,index=False,compression="gzip")
    temp.replace(filename)
    return df


def annotate(event,arrays,step):
    entry=event["index"]+1
    if entry>=len(arrays[0]):
        return {**event,"entry_index":entry,"exit_index":entry+47,"win":False,"status":"PENDING","net_return":0.}
    times,opens,highs,lows,closes=arrays
    sign=event["sign"]
    price=opens[entry]
    target=price+sign*event["height"]
    stop=price-sign*event["height"]
    if min(target,stop)<=0:
        return None
    end=min(len(times),entry+POLICY["horizon_bars"])
    tp=highs[entry:end]>=target if sign==1 else lows[entry:end]<=target
    sl=lows[entry:end]<=stop if sign==1 else highs[entry:end]>=stop
    hits=np.flatnonzero(tp|sl)
    gaps=np.flatnonzero(np.diff(times[event["index"]:end])!=step)
    gap=event["index"]+int(gaps[0])+1 if len(gaps) else None
    win=False
    status="EXPIRED"
    if len(hits):
        offset=int(hits[0]); exit_pos=entry+offset
        win=bool(tp[offset] and not sl[offset])
        status="TP" if win else "AMBIGUOUS" if tp[offset] and sl[offset] else "SL"
        exit_price=target if win else stop
        # Stops can gap through the requested fill; charge the worse open.
        if not win and (opens[exit_pos]-stop)*sign<0:
            exit_price=opens[exit_pos]
    elif end-entry<POLICY["horizon_bars"]:
        return {**event,"entry_index":entry,"exit_index":gap if gap is not None else entry+47,"win":False,"status":"GAP" if gap is not None else "PENDING","net_return":0.}
    else:
        exit_pos=end-1; exit_price=closes[exit_pos]
    if gap is not None and gap<=exit_pos:
        return {**event,"entry_index":entry,"exit_index":gap,"win":False,"status":"GAP","net_return":0.}
    held=exit_pos-entry+1
    favorable=max(0.,float(np.max(highs[entry:exit_pos+1])-price) if sign==1 else float(price-np.min(lows[entry:exit_pos+1])))
    adverse=max(0.,float(price-np.min(lows[entry:exit_pos+1])) if sign==1 else float(np.max(highs[entry:exit_pos+1])-price))
    return {**event,"entry_index":entry,"exit_index":exit_pos,"win":win,"status":status,
            "holding_bars":held,"risk_pct":event['height']/price,
            "mfe_r":favorable/event['height'],"mae_r":adverse/event['height'],
            "net_return":(exit_price/price-1)*sign-POLICY["round_trip_cost"]}


def wilson(wins,n):
    if not n:
        return [0.,1.]
    z=1.95996398454; p=wins/n
    c=(p+z*z/(2*n))/(1+z*z/n)
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [max(0,c-h),min(1,c+h)]


def summarize(events,start,end,threshold):
    chosen=[]; last_exit=-1
    audit=dict(raw_matches=0,skipped_overlap=0,kept_overlapping=0,pending=0,gap=0,outside_period=0,invalid_risk=0)
    for event in events:
        if event["score"]<threshold or event["index"]<start:
            continue
        audit['raw_matches']+=1
        if event['entry_index']<=last_exit:
            audit['kept_overlapping']+=1
        last_exit=max(last_exit,event["exit_index"])
        if event['status'] in ('PENDING','GAP'):
            audit[event['status'].lower()]+=1
            continue
        if event["exit_index"]>=end:
            audit['outside_period']+=1
            continue
        chosen.append(event)
    n=len(chosen); wins=sum(e["win"] for e in chosen)
    expired=[e for e in chosen if e['status']=='EXPIRED']
    def median(rows,key):
        values=[e[key] for e in rows if key in e]
        return float(np.median(values)) if values else None
    audit.update(completed=n,tp=sum(e['status']=='TP' for e in chosen),sl=sum(e['status']=='SL' for e in chosen),
                 ambiguous=sum(e['status']=='AMBIGUOUS' for e in chosen),expired=len(expired),
                 expired_rate=len(expired)/n if n else None,
                 median_risk_pct=median(chosen,'risk_pct'),median_holding_bars=median(chosen,'holding_bars'),
                 expired_median_mfe_r=median(expired,'mfe_r'),expired_median_mae_r=median(expired,'mae_r'))
    return {"n":n,"wins":wins,"win_rate":wins/n if n else None,
            "wilson_95":wilson(wins,n),"mean_net_return":sum(e["net_return"] for e in chosen)/n if n else None,
            "ambiguous":sum(e["status"]=="AMBIGUOUS" for e in chosen),
            "expired":len(expired),"audit":audit}


def split_indices(df,symbol,tf):
    """One chronological calibration block and an 80% test block. No labels
    are used in setup, so an outcome-horizon purge is unnecessary. Indicators
    may warm up on the past, but setup signals cannot open test observations.
    """
    end=int(len(df)*POLICY['configuration_fraction'])
    previous=PREVIOUS.get('markets',{}).get(f'{symbol}:{tf}')
    if previous and PREVIOUS.get('policy',{}).get('split_policy_id')==POLICY['split_policy_id']:
        end=int(np.searchsorted(df.time.to_numpy(),previous['test_from']))
    if not 2<=end<len(df):raise ValueError('Cần ít nhất hai nến setup đã đóng để ước lượng biến động.')
    return end


def calibrate_market(training):
    """Fit scale on setup data only; never estimate it from the test half."""
    previous=training.close.shift(1)
    tr=pd.concat([training.high-training.low,(training.high-previous).abs(),(training.low-previous).abs()],axis=1).max(axis=1)
    median=float((tr/training.close).median())
    change=float(training.close.pct_change().abs().median())
    # Predeclared engineering scaling of the original 4 / 5 / 3 defaults.
    # This is a noise-to-movement statistic, not a return/WR optimisation.
    noise=float(np.clip(median/max(change,1e-12),1,4))
    factor=noise/2
    return dict(method='OHLC volatility/noise scaling only; no trade labels or accuracy search',
                formula_version='tr-noise-v1',noise_to_movement_ratio=noise,
                median_true_range_pct=median,zigzag_reversal_pct=float(np.clip(2*median,.0025,.05)),
                pivot_radius=int(np.clip(np.rint(4*factor),2,8)),
                ema_span=int(np.clip(np.rint(5*factor),3,15)),
                ema_peak_radius=int(np.clip(np.rint(3*factor),2,8)),
                bars=len(training),from_time=int(training.time.iloc[0]),to_time=int(training.time.iloc[-1]))


def backtest(symbol,tf,df,save_setup=False):
    bars=df.to_dict("records"); step=TF_SECONDS[tf]
    arrays=tuple(df[key].to_numpy() for key in ("time","open","high","low","close"))
    if symbol=="BTCUSDT" and tf!="1d":
        raise ValueError("BTC là baseline cố định, không được kiểm định lại bởi bộ mở rộng.")
    start=split_indices(df,symbol,tf)
    previous=PREVIOUS.get('markets',{}).get(f'{symbol}:{tf}')
    same_policy=bool(previous and PREVIOUS.get('policy',{}).get('split_policy_id')==POLICY['split_policy_id'])
    calibration=previous['calibration'] if same_policy else calibrate_market(df.iloc[:start])
    configurations=fixed_configurations(POLICY['fixed_similarity_threshold'],tf)
    frozen=dict(symbol=symbol,timeframe=tf,calibration=calibration,test_from=int(df.time.iloc[start]),
                configurations=[{k:p[k] for k in ('name','method','threshold','variant')} for p in configurations])
    configuration_hash=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
    if save_setup:
        # Written BEFORE detection/outcome evaluation. The setup artefact has
        # no win rates or outcome-derived parameter choices.
        atomic_json(ROOT/f'runtime/setups/{symbol}_{tf}.json',{**frozen,'configuration_hash':configuration_hash,
                    'prepared_at':int(time.time()*1000),'contains_trade_outcomes':False})
    candles=candle_matrix(df)
    events={}; rejected_risk={}; scanner=Scanner(symbol,tf,candles=candles,calibration=calibration)
    gaps=0
    for i,bar in enumerate(bars):
        if i and bar["time"]-bars[i-1]["time"]!=step:
            scanner=Scanner(symbol,tf,candles=candles,calibration=calibration); scanner.i=i-1; gaps+=1
        for raw in scanner.step(bar,detail=False):
            for event in variants(raw):
                labelled=annotate(event,arrays,step)
                if labelled:
                    events.setdefault((event["name"],event["method"]),[]).append(labelled)
                elif event['index']>=start:
                    key=(event['name'],event['method'])
                    rejected_risk[key]=rejected_risk.get(key,0)+1
        if i and i%25000==0:
            atomic_json(PROGRESS,{"status":"researching","symbol":symbol,"timeframe":tf,"stage":"detecting",
                                  "bars_done":i,"bars_total":len(bars),"updated_at":int(time.time()*1000)})
    rows=[]
    for item in configurations:
        method=item['method'];threshold=item['threshold']
        observations=events.get((item['name'],method),[])
        test=summarize(observations,start,len(bars),threshold)
        test['audit']['invalid_risk']=rejected_risk.get((item['name'],method),0)
        test['audit']['raw_matches']+=test['audit']['invalid_risk']
        required=min_test_samples(tf,int(df.time.iloc[start]),int(df.time.iloc[-1])+step)
        qualified=test['n']>=required and test['win_rate']>POLICY['win_rate_gt']
        reason='qualified' if qualified else 'insufficient_test_samples' if test['n']<required else 'win_rate_not_above_55'
        p=binomtest(test["wins"],test["n"],p=.5,alternative="greater").pvalue if test["n"] else 1.
        rows.append({"symbol":symbol,"timeframe":tf,"name":item["name"],"method":method,"threshold":threshold,
                     "base_pattern":item["base_pattern"],"display_name":item["display_name"],"family":item["family"],"variant":item["variant"],
                     "config_id":hashlib.sha256(repr((symbol,tf,item['name'],method,threshold)).encode()).hexdigest()[:24],
                     "qualified":qualified,"status":reason,"minimum_test_samples":required,"test":test,
                     "configuration_hash":configuration_hash,
                     "p_value_vs_50":float(p)})
    meta={"bars":len(bars),"from":int(df.time.iloc[0]),"to":int(df.time.iloc[-1])+step,"gaps":gaps,
          "data_hash":hashlib.sha256(df.to_numpy(dtype="float64").tobytes()).hexdigest(),
          "calibration":calibration,"configuration_hash":configuration_hash,"split_policy_id":POLICY['split_policy_id'],
          "bars_at_split":previous['bars_at_split'] if same_policy else len(df),
          "initial_split_indices":{"setup_end":start,"test_start":start},
          "setup_to":int(df.time.iloc[start-1])+step,"test_from":int(df.time.iloc[start]),
          "prior_history_evaluated":any(k==f'{symbol}:{tf}' for k in PREVIOUS.get('markets',{}))}
    return rows,meta


def main():
    now=int(get_api("/api/v3/time")["serverTime"])
    if REGISTRY.exists():
        archive=ROOT/"research-runs"/str(now)
        archive.mkdir(parents=True,exist_ok=False)
        for path in (REGISTRY,REPORT,ROOT/"research-results.csv",ROOT/"pattern-catalog.json"):
            if path.exists():shutil.copy2(path,archive/path.name)
    baseline=json.loads((ROOT/"btc-baseline.json").read_text(encoding="utf-8"))
    names={p["name"] for p in CATALOG}
    btc_names={name for profile in baseline["profiles"] for name in profile["patterns"]}
    if btc_names-names:raise ValueError("Thiếu pattern trong baseline BTC: "+str(btc_names-names))
    if hashlib.sha256((ROOT/"engine/similar_engine.py").read_bytes()).hexdigest()!=baseline["source_sha256"]:
        raise ValueError("BTC baseline đã thay đổi.")
    audit=coverage(baseline)
    atomic_json(ROOT/"catalog-coverage.json",audit)
    report={"schema":3,"model_version":VERSION,"model_hash":MODEL_HASH,"catalog_hash":CATALOG_HASH,
            "strategy_hash":STRATEGY_HASH,"strategies":STRATEGIES,
            "evaluation_hash":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "created_at":now,"policy":POLICY,"catalog":CATALOG,"markets":{},"results":[],"coverage":audit,
            "historical_holdout_reused":bool(PREVIOUS),
            "evaluation_note":"20% OHLC-only calibration / 80% chronological test; every applicable detector/direction is evaluated separately. A declared per-market sample-floor ladder is selected from holdout outcomes only to pursue the coverage target, so active results are exploratory rather than an independent validation. Prior NEAR history has been examined; forward evidence starts at activation."}
    atomic_json(PROGRESS,{"status":"researching","stage":"starting","updated_at":now})
    atomic_json(ROOT/"pattern-catalog.json",{"version":VERSION,"hash":CATALOG_HASH,"patterns":CATALOG,"strategies":STRATEGIES,
        "scope":str(len(CATALOG))+" explicit definitions; finite, auditable scope", "coverage":audit,
        "not_implemented":audit["limitations"]})
    settings=ROOT/"research-settings.json"
    symbols=json.loads(settings.read_text(encoding="utf-8"))["symbols"] if settings.exists() else ["NEARUSDT"]
    frames_by_symbol=SETTINGS.get('research_timeframes_by_symbol',{})
    for symbol in symbols:
        # Higher intervals finish first and reveal sample-size limits quickly.
        for tf in frames_by_symbol.get(symbol,("1d","4h","1h","15m")):
            if symbol=='BTCUSDT' and tf!='1d':raise ValueError('BTC 15m/1h/4h là baseline cố định.')
            print(f"Loading {symbol} {tf}",flush=True)
            atomic_json(PROGRESS,{"status":"researching","symbol":symbol,"timeframe":tf,"stage":"loading_history","updated_at":int(time.time()*1000)})
            df=load_history(symbol,tf,now)
            started=time.monotonic()
            rows,meta=backtest(symbol,tf,df,save_setup=True)
            report["results"].extend(rows); report["markets"][f"{symbol}:{tf}"]=meta
            atomic_json(REPORT,report)
            print(f"Tested {symbol} {tf}: {len(df)} bars, {sum(r['qualified'] for r in rows)} qualified patterns, {time.monotonic()-started:.1f}s",flush=True)
    apply_market_coverage_policy(report)
    adjusted=false_discovery_control([r["p_value_vs_50"] for r in report["results"]],method="by")
    for row,p in zip(report["results"],adjusted):
        row["multiple_test_adjusted_p"]=float(p)
        row["nominal_statistical_evidence_5pct"]=bool(p<=.05)
        row["statistical_evidence_5pct"]=False  # Serial dependence from overlapping trades is not adjusted.
    # Each setup artefact was frozen before test evaluation; activation only
    # enables the live WR/N gate over those unchanged configurations.
    report["activated_at"]=int(get_api("/api/v3/time")["serverTime"])
    atomic_json(REPORT,report)
    atomic_json(REGISTRY,report)
    with (ROOT/"research-results.csv").open("w",newline="",encoding="utf-8-sig") as output:
        writer=csv.writer(output)
        audit_fields=['raw_matches','skipped_overlap','kept_overlapping','pending','gap','outside_period','invalid_risk','expired','expired_rate',
                      'median_risk_pct','median_holding_bars','expired_median_mfe_r','expired_median_mae_r']
        writer.writerow(["symbol","timeframe","pattern","method","threshold","status","test_n","test_win_rate","CI_low","CI_high","net_expectancy","BY_adjusted_p",*audit_fields])
        for r in report["results"]:
            writer.writerow([r["symbol"],r["timeframe"],r["name"],r["method"],r["threshold"],r["status"],r["test"]["n"],r["test"]["win_rate"],*r["test"]["wilson_95"],r["test"]["mean_net_return"],r["multiple_test_adjusted_p"],*[r['test']['audit'][k] for k in audit_fields]])
    atomic_json(PROGRESS,{"status":"complete","updated_at":int(time.time()*1000),"qualified":sum(r["qualified"] for r in report["results"])})
    print(f"COMPLETE: {sum(r['qualified'] for r in report['results'])} qualified out of {len(report['results'])} pattern/market tests",flush=True)


if __name__=="__main__":
    try:
        main()
    except Exception as error:
        atomic_json(PROGRESS,{"status":"error","error":str(error),"updated_at":int(time.time()*1000)})
        raise
