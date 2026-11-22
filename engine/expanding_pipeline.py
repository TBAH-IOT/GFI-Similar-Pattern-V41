"""Fixed configurations, expanding holdout statistics, reversible live gate."""
import hashlib
import json
from pathlib import Path
import sqlite3
from statistics import median
import threading

import pandas as pd

from research_model import Scanner,TF_SECONDS,MODEL_HASH,CATALOG_HASH,VERSION
from pattern_catalog import candle_matrix,BY_NAME
from strategy_catalog import variants,BY_STRATEGY,STRATEGY_HASH
from pipeline import scan_cutoff
from eligibility import minimum_samples


class ExpandingPipeline:
    def __init__(self,tf,database,symbol="NEARUSDT"):
        if symbol=="BTCUSDT" and tf!="1d":
            raise ValueError("BTC phải dùng pipeline baseline đã cố định.")
        self.tf,self.symbol,self.database=tf,symbol,Path(database)
        self.root=self.database.parent.parent
        self.lock=threading.RLock()
        self.scanner=None; self.last_time=None; self.registry_mtime=None
        self.models={}; self.counters={}; self.return_history={}; self.pending={}; self.found=[]; self.signals=[]
        self.min_samples=100
        self.meta={"symbol":symbol,"timeframe":tf,"status":"awaiting_validation","model_version":VERSION,
                   "evaluated_bars":0,"expected_bars":0,"pattern_count":0,"qualified_models":0,"error":None}

    def snapshot(self):
        with self.lock:
            return [dict(s) for s in self.signals],dict(self.meta)

    def fail(self,error):
        with self.lock:
            self.meta.update(status="error",error=str(error)); self.signals=[]

    def _load(self,now_ms):
        path=self.root/"runtime/research-registry.json"
        if not path.exists():
            return False
        modified=path.stat().st_mtime_ns
        if modified==self.registry_mtime:
            return True
        raw=path.read_bytes(); registry=json.loads(raw)
        if registry["model_hash"]!=MODEL_HASH or registry["catalog_hash"]!=CATALOG_HASH or registry.get("strategy_hash")!=STRATEGY_HASH:
            raise ValueError("Thư viện đã đổi; cần chạy lại kiểm định trước khi kích hoạt.")
        if registry["evaluation_hash"]!=hashlib.sha256((self.root/"research_runner.py").read_bytes()).hexdigest():
            raise ValueError("Quy tắc đánh giá đã đổi; cần cập nhật registry.")
        market=registry["markets"].get(f"{self.symbol}:{self.tf}")
        if not market:
            return False
        self.models={(r["name"],r["method"]):r for r in registry["results"]
                     if r["symbol"]==self.symbol and r["timeframe"]==self.tf and r["method"] is not None}
        self.counters={k:{"n":0,"wins":0,"opposite_wins":0,"net_sum":0.,"ambiguous":0,"expired":0,"active":False,"last_transition":None} for k in self.models}
        self.return_history={k:[] for k in self.models}
        self.anchor=market["test_from"]
        self.calibration=market.get('calibration',{})
        policy=registry["policy"]
        self.policy=policy
        self.min_samples=minimum_samples(self.tf,self.anchor,now_ms//1000,self.policy,f'{self.symbol}:{self.tf}')
        self.activated_at=registry["activated_at"]
        if self.activated_at>now_ms:
            raise ValueError("Registry có thời điểm kích hoạt trong tương lai.")
        self.registry_hash=hashlib.sha256(raw).hexdigest()
        self.registry_mtime=modified; self.scanner=None; self.last_time=None
        self.pending={}; self.found=[]; self.signals=[]
        with self.lock:
            self.meta.update(accuracy_anchor=self.anchor,registry_hash=self.registry_hash,configured_models=len(self.models),
                             minimum_samples=self.min_samples,
                             validated_at=self.activated_at,accuracy_source="expanding_oos",policy=registry["policy"],error=None)
        return True

    @staticmethod
    def apply_result(counter,win,net,status,timestamp,min_samples=100):
        counter["n"]+=1; counter["wins"]+=int(win); counter["net_sum"]+=net
        counter["ambiguous"]+=int(status=="AMBIGUOUS"); counter["expired"]+=int(status=="EXPIRED")
        ExpandingPipeline.apply_gate(counter,min_samples,timestamp)

    @staticmethod
    def apply_gate(counter,min_samples,timestamp):
        rate=counter["wins"]/counter["n"] if counter['n'] else 0.
        previous=counter["active"]
        # Admit above 55%; an already active model is removed BELOW 55%.
        counter["active"]=counter["n"]>=min_samples and (rate>.55 or (previous and rate>=.55))
        if previous!=counter["active"]:
            counter["last_transition"]={"time":timestamp,"active":counter["active"],"n":counter["n"],"win_rate":rate}

    def _settle(self,bar):
        finished=[]
        for trade_id,trade in list(self.pending.items()):
            key=(trade['name'],trade['method'])
            if bar["time"]<trade["available_at"]:
                continue
            if trade.get("entry") is None:
                entry=bar["open"]; sign=trade["sign"]; risk=trade["height"]
                trade.update(entry=entry,tp=entry+sign*risk,sl=entry-sign*risk,age=0)
                if min(trade["tp"],trade["sl"])<=0:
                    del self.pending[trade_id]; continue
            trade["age"]+=1
            long=trade["sign"]==1
            tp=bar["high"]>=trade["tp"] if long else bar["low"]<=trade["tp"]
            sl=bar["low"]<=trade["sl"] if long else bar["high"]>=trade["sl"]
            if not tp and not sl and trade["age"]<48:
                continue
            win=bool(tp and not sl)
            status="TP" if win else "AMBIGUOUS" if tp and sl else "SL" if sl else "EXPIRED"
            price=trade["tp"] if win else trade["sl"] if sl else bar["close"]
            if sl and (bar["open"]-price)*trade["sign"]<0:
                price=bar["open"]
            net=(price/trade["entry"]-1)*trade["sign"]-.003
            self.counters[key]["opposite_wins"]+=int(sl and not tp)
            # Forecast probabilities intentionally use only resolved TP/SL
            # cases. Expired and ambiguous cases are the omitted sideways
            # bucket, never silently treated as a directional move.
            if status in ("TP","SL"):
                self.return_history.setdefault(key,[]).append(float(net))
            required=minimum_samples(self.tf,self.anchor,bar["time"]+TF_SECONDS[self.tf],self.policy,f'{self.symbol}:{self.tf}')
            # Reconstructed pre-activation eligibility is not a real live
            # admission. At startup a 55.00% pattern must pass the strict new
            # admission gate, rather than inherit a hypothetical earlier one.
            if (bar['time']+TF_SECONDS[self.tf])*1000<self.activated_at:
                self.counters[key]['active']=False
            self.apply_result(self.counters[key],win,net,status,bar["time"]+TF_SECONDS[self.tf],required)
            finished.append((self.registry_hash,self.symbol,self.tf,trade["id"],trade["name"],trade["method"],
                             trade["available_at"],bar["time"]+TF_SECONDS[self.tf],int(win),status,float(net)))
            del self.pending[trade_id]
        return finished

    def _prediction(self,key,signal):
        """Summarise completed historical outcomes for the two-way forecast.

        Positive net returns mean the detected direction won; negative returns
        mean the opposite direction won. Expired and ambiguous observations are
        intentionally excluded from the up/down split, so no sideways bucket is
        shown in the terminal.
        """
        returns=[float(value) for value in self.return_history.get(key,[]) if float(value)!=0]
        if not returns:
            return None
        wins=[value for value in returns if value>0]
        losses=[abs(value) for value in returns if value<0]
        total=len(wins)+len(losses)
        if not total:
            return None
        success=signal.get("direction")=="LONG"
        success_probability=len(wins)/total
        failure_probability=len(losses)/total
        success_median=float(median(wins)) if wins else 0.0
        failure_median=float(median(losses)) if losses else 0.0
        up_probability=success_probability if success else failure_probability
        down_probability=failure_probability if success else success_probability
        up_median_move=success_median if success else failure_median
        down_median_move=failure_median if success else success_median
        return {"up_probability":round(up_probability,4),"down_probability":round(down_probability,4),
                "up_median_move":round(max(0.0,up_median_move),6),"down_median_move":round(max(0.0,down_median_move),6),
                "sample_count":total,"horizon_bars":min(7,48),"basis":"median_completed_outcomes"}

    def update(self,df,now_ms):
        step=TF_SECONDS[self.tf]; cutoff=scan_cutoff(now_ms)
        if not self._load(now_ms):
            with self.lock:
                self.meta.update(status="awaiting_validation",checked_at=now_ms)
            return []
        if not self.models:
            available=int(df.index[-1].timestamp())+step
            with self.lock:
                self.signals=[]
                self.meta.update(status="no_qualified_patterns",checked_at=now_ms,last_available_at=available,
                                 metrics=[],qualified_models=0,pattern_count=0,completed_observations=0)
            if self.last_time!=available-step:
                directory=self.root/'watchlists'; directory.mkdir(parents=True,exist_ok=True)
                document=dict(symbol=self.symbol,timeframe=self.tf,accuracy_anchor=self.anchor,as_of=available,
                    minimum_samples=self.min_samples,registry_hash=self.registry_hash,
                    active_patterns_by_method={},monitored_strategies=[])
                filename=directory/f'{self.symbol}_{self.tf}.json'; temp=filename.with_suffix('.json.tmp')
                temp.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(filename)
                self.last_time=available-step
            return []
        current=df.rename(columns={c:c.lower() for c in df.columns}).copy()
        current["time"]=[int(t.timestamp()) for t in current.index]
        current=current.reset_index(drop=True)
        boot=self.scanner is None
        if boot:
            history=pd.read_csv(self.root/f"runtime/history/{self.symbol}_{self.tf}.csv.gz")
            source=pd.concat([history,current],ignore_index=True).drop_duplicates("time",keep="last").sort_values("time").reset_index(drop=True)
            if len(current) and int(current.time.iloc[0])>int(history.time.iloc[-1])+step:
                from research_runner import load_history
                source=load_history(self.symbol,self.tf,now_ms)
            source=source[(source.time+step)*1000<=now_ms].reset_index(drop=True)
            self.scanner=Scanner(self.symbol,self.tf,candles=candle_matrix(source),calibration=self.calibration)
        else:
            source=current[current.time>self.last_time].reset_index(drop=True)
            if len(source) and int(source.time.iloc[0])>self.last_time+step:
                from research_runner import load_history
                all_data=load_history(self.symbol,self.tf,now_ms)
                source=all_data[all_data.time>self.last_time].reset_index(drop=True)
        scan_status = "backfilling" if boot else "catching_up" if len(source) else "live"
        # Publish the work size before the first candle is processed. The
        # initial expanding scan can rebuild a long closed-candle history;
        # reporting 0/0 makes the terminal look frozen while it is healthy.
        with self.lock:
            self.meta.update(status=scan_status, evaluated_bars=0 if boot else self.meta.get("evaluated_bars", 0),
                             expected_bars=len(source), checked_at=now_ms, error=None)
        records=[]
        for position, bar in enumerate(source.to_dict("records"), 1):
            ts=int(bar["time"])
            if self.last_time is not None and ts-self.last_time!=step:
                position=self.scanner.i+1
                values=self.scanner.candle_values
                self.scanner=Scanner(self.symbol,self.tf,candles=values,calibration=self.calibration)
                self.scanner.i=position-1; self.pending.clear()
            if ts>=self.anchor:
                records.extend(self._settle(bar))
            for raw in self.scanner.step(bar):
                for signal in variants(raw):
                    key=(signal["name"],signal["method"])
                    profile=self.models.get(key)
                    if not profile or signal["similarity"]/100<profile["threshold"] or ts<self.anchor or signal['id'] in self.pending:
                        continue
                    # Observe inactive patterns too; direct and inverse outcomes
                    # are evaluated independently, never by 1 - win_rate.
                    signal.update(active_at_detection=self.counters[key]["active"],
                                  config_id=profile.get('config_id'),
                                  registry_hash=self.registry_hash,backfilled=signal["available_at"]*1000<self.activated_at,
                                  actionable=signal["available_at"]*1000>=self.activated_at and self.counters[key]["active"],
                                  accuracy_source="expanding_oos",display_name=BY_STRATEGY[signal["name"]]["display_name"])
                    self.pending[signal['id']]=dict(signal)
                    if signal["available_at"]>=cutoff:
                        self.found.append(signal)
            self.last_time=ts
            if boot and position % 250 == 0:
                with self.lock:
                    self.meta.update(evaluated_bars=position, expected_bars=len(source), checked_at=now_ms)
        self.found=[s for s in self.found if s["available_at"]>=cutoff]
        self.min_samples=minimum_samples(self.tf,self.anchor,self.last_time+step,self.policy,f'{self.symbol}:{self.tf}')
        active=[]; metrics=[]
        for key,counter in self.counters.items():
            n=counter["n"]; rate=counter["wins"]/n if n else None
            self.apply_gate(counter,self.min_samples,self.last_time+step)
            metrics.append({"name":key[0],"method":key[1],"display_name":BY_STRATEGY[key[0]]["display_name"],
                            "config_id":self.models[key].get('config_id'),
                            "family":BY_STRATEGY[key[0]]["family"],"variant":BY_STRATEGY[key[0]]["variant"],**counter,"win_rate":rate,
                            "opposite_win_rate":counter["opposite_wins"]/n if n else None,"minimum_samples":self.min_samples,
                            "mean_net_return":counter["net_sum"]/n if n else None,"anchor":self.anchor})
        by_key={(m["name"],m["method"]):m for m in metrics}
        references=[]
        reference_seen=set()
        for signal in self.found:
            metric=by_key[signal["name"],signal["method"]]
            if metric["active"]:
                active.append({**signal,"configured_win_rate":metric["win_rate"],"validation_samples":metric["n"],
                               "accuracy_anchor":self.anchor,"mean_net_return":metric["mean_net_return"],"minimum_samples":self.min_samples,
                               "statistical_evidence_5pct":self.models[signal["name"],signal["method"]]["statistical_evidence_5pct"],
                               "prediction":self._prediction((signal["name"],signal["method"]),signal),
                               "research_only":True})
            elif signal.get("similarity",0)>90:
                # Keep very close shapes visible as non-actionable context even
                # when their historical accuracy/sample gate did not qualify.
                identity=(signal["name"],signal["method"],signal["available_at"],signal.get("direction"))
                if identity in reference_seen:continue
                reference_seen.add(identity)
                references.append({**signal,"configured_win_rate":metric["win_rate"],"validation_samples":metric["n"],
                                   "accuracy_anchor":self.anchor,"mean_net_return":metric["mean_net_return"],"minimum_samples":self.min_samples,
                                   "statistical_evidence_5pct":self.models[signal["name"],signal["method"]]["statistical_evidence_5pct"],
                                   "prediction":self._prediction((signal["name"],signal["method"]),signal),
                                   "research_only":True,"reference_only":True,"actionable":False})
        references.sort(key=lambda s:(s["available_at"],s.get("similarity",0)),reverse=True)
        active.extend(references[:80])
        active.sort(key=lambda s:(s["available_at"],s["id"]),reverse=True)
        if records:
            connection=sqlite3.connect(self.database,timeout=30)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS expanding_observations (registry_hash TEXT,symbol TEXT,tf TEXT,id TEXT,pattern TEXT,method TEXT,entry_at INTEGER,exit_at INTEGER,win INTEGER,status TEXT,net_return REAL,PRIMARY KEY(registry_hash,symbol,tf,id))")
                connection.executemany("INSERT OR REPLACE INTO expanding_observations VALUES (?,?,?,?,?,?,?,?,?,?,?)",records)
                connection.commit()
            finally:
                connection.close()
        with self.lock:
            self.signals=active
            self.meta.update(status="live" if any(m["active"] for m in metrics) else "no_qualified_patterns",checked_at=now_ms,
                             qualified_models=sum(m["active"] for m in metrics),pattern_count=len(active),metrics=metrics,
                             evaluated_bars=sum(int(t.timestamp())+step>=cutoff for t in df.index),
                             expected_bars=sum(int(t.timestamp())+step>=cutoff for t in df.index),
                             scan_from=cutoff,scan_to=self.last_time+step,last_available_at=self.last_time+step,error=None,
                             accuracy_anchor=self.anchor,minimum_samples=self.min_samples,completed_observations=sum(m["n"] for m in metrics))
        if boot or len(source):
            directory=self.root/"watchlists"; directory.mkdir(parents=True,exist_ok=True)
            grouped={}
            for metric in metrics:
                if metric["active"]:
                    row=self.models[metric["name"],metric["method"]]
                    grouped.setdefault(metric["method"],{})[metric["name"]]={
                        "base_pattern":row["base_pattern"],"variant":metric["variant"],"win_rate":metric["win_rate"],
                        "samples":metric["n"],"wins":metric["wins"],"similarity_threshold":row["threshold"],
                        "minimum_samples":self.min_samples,
                        "opposite_win_rate":metric["opposite_win_rate"],"mean_net_return":metric["mean_net_return"]}
            document={"symbol":self.symbol,"timeframe":self.tf,"accuracy_anchor":self.anchor,
                      "minimum_samples":self.min_samples,
                      "as_of":self.last_time+step,"registry_hash":self.registry_hash,
                      "active_patterns_by_method":grouped,"monitored_strategies":metrics}
            filename=directory/f"{self.symbol}_{self.tf}.json"; temp=filename.with_suffix(".json.tmp")
            temp.write_text(json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
            temp.replace(filename)
        return active
