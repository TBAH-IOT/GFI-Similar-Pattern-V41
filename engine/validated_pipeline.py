"""Live consumer of a frozen, out-of-sample-qualified research registry."""
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

import pandas as pd

from research_model import Scanner,TF_SECONDS,MODEL_HASH,CATALOG_HASH,VERSION
from pipeline import scan_cutoff


class ValidatedPipeline:
    def __init__(self,tf,database,symbol="BTCUSDT"):
        self.tf,self.database,self.symbol=tf,Path(database),symbol
        self.root=self.database.parent.parent
        self.lock=threading.RLock()
        self.scanner=None
        self.registry_digest=None
        self.registry_mtime=None
        self.models={}
        self.signals=[]
        self.last_time=None
        self.activated_at=None
        self.meta={"symbol":symbol,"timeframe":tf,"status":"awaiting_validation","model_version":VERSION,
                   "model_hash":MODEL_HASH,"evaluated_bars":0,"expected_bars":0,"pattern_count":0,"qualified_models":0,
                   "error":None,"months":2,"min_test_samples":100,"win_rate_gt":.55}

    def fail(self,error):
        with self.lock:
            self.meta.update(status="error",error=str(error))
            self.signals=[]

    def snapshot(self):
        with self.lock:
            return [dict(s) for s in self.signals],dict(self.meta)

    def _registry(self,now_ms):
        filename=self.root/"runtime/research-registry.json"
        if not filename.exists():
            return False
        modified=filename.stat().st_mtime_ns
        if self.registry_mtime==modified:
            return True
        raw=filename.read_bytes(); registry=json.loads(raw)
        if registry.get("model_hash")!=MODEL_HASH or registry.get("catalog_hash")!=CATALOG_HASH:
            raise ValueError("Bộ nhận diện đã đổi; cần kiểm định lại trước khi kích hoạt.")
        if registry.get("evaluation_hash")!=hashlib.sha256((self.root/"research_runner.py").read_bytes()).hexdigest():
            raise ValueError("Quy tắc kiểm định đã đổi; cần chạy lại nghiên cứu.")
        if registry["created_at"]>now_ms:
            raise ValueError("Thời điểm kiểm định nằm trong tương lai.")
        models={}
        for row in registry["results"]:
            metric=row["test"]; n=metric["n"]
            eligible=n>=100 and metric["win_rate"] is not None and metric["win_rate"]>.55
            if row["symbol"]==self.symbol and row["timeframe"]==self.tf and eligible and row["qualified"]:
                if abs(metric["win_rate"]-metric["wins"]/n)>1e-12 or not .85<=row["threshold"]<=1:
                    raise ValueError("Thông số kiểm định không hợp lệ.")
                models[row["name"],row["method"]]=row
        self.registry_mtime=modified
        self.registry_digest=hashlib.sha256(raw).hexdigest()
        self.models=models
        self.activated_at=registry.get("activated_at",registry["created_at"])
        self.scanner=None; self.last_time=None; self.signals=[]
        with self.lock:
            self.meta.update(qualified_models=len(models),registry_hash=self.registry_digest,
                             validated_at=self.activated_at,policy=registry["policy"],error=None)
        return True

    def update(self,df,now_ms):
        cutoff=scan_cutoff(now_ms); step=TF_SECONDS[self.tf]
        expected=sum(int(t.timestamp())+step>=cutoff for t in df.index)
        with self.lock:
            self.meta.update(scan_from=cutoff,expected_bars=expected,source_time=now_ms)
        if not self._registry(now_ms):
            with self.lock:
                self.meta.update(status="awaiting_validation",checked_at=now_ms)
            return []
        if not self.models:
            with self.lock:
                self.meta.update(status="no_qualified_patterns",checked_at=now_ms,evaluated_bars=0,
                                 pattern_count=0,last_available_at=int(df.index[-1].timestamp())+step)
            return []
        with self.lock:
            self.meta.update(status="backfilling" if self.scanner is None else "catching_up")
        if self.scanner is None:
            cache=self.root/f"runtime/history/{self.symbol}_{self.tf}.csv.gz"
            if not cache.exists():
                raise ValueError("Thiếu lịch sử dùng làm nóng mô hình đã kiểm định.")
            history=pd.read_csv(cache)
            current=df.rename(columns={c:c.lower() for c in df.columns}).copy()
            current["time"]=[int(t.timestamp()) for t in current.index]
            current=current.reset_index(drop=True)
            source=pd.concat([history,current],ignore_index=True).drop_duplicates("time",keep="last").sort_values("time")
            source=source[(source.time+step)*1000<=now_ms]
            self.scanner=Scanner(self.symbol,self.tf,self.models)
        else:
            source=df.rename(columns={c:c.lower() for c in df.columns}).copy()
            source["time"]=[int(t.timestamp()) for t in source.index]
            source=source[source.time>self.last_time].reset_index(drop=True)
        ledger=[]
        found=list(self.signals)
        for bar in source.to_dict("records"):
            ts=int(bar["time"])
            if self.last_time is not None and ts-self.last_time!=step:
                position=self.scanner.i+1
                self.scanner=Scanner(self.symbol,self.tf,self.models)
                self.scanner.i=position-1
            emitted=self.scanner.step(bar)
            if ts+step>=cutoff:
                for signal in emitted:
                    profile=self.models[signal["name"],signal["method"]]
                    signal.update(registry_hash=self.registry_digest,
                                  actionable=signal["available_at"]*1000>=self.activated_at,
                                  backfilled=signal["available_at"]*1000<self.activated_at,
                                  mean_net_return=profile["test"]["mean_net_return"],
                                  confidence_interval=profile["test"]["wilson_95"],
                                  statistical_evidence_5pct=profile["statistical_evidence_5pct"],
                                  research_only=True)
                    found.append(signal)
                ledger.append((self.registry_digest,self.symbol,self.tf,ts,json.dumps(emitted)))
            self.last_time=ts
        if ledger:
            self.database.parent.mkdir(parents=True,exist_ok=True)
            connection=sqlite3.connect(self.database,timeout=30)
            try:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE IF NOT EXISTS validated_candles (registry_hash TEXT,symbol TEXT,tf TEXT,bar_time INTEGER,signals TEXT,PRIMARY KEY(registry_hash,symbol,tf,bar_time))")
                connection.executemany("INSERT OR REPLACE INTO validated_candles VALUES (?,?,?,?,?)",ledger)
                connection.commit()
            finally:
                connection.close()
        found=[s for s in found if s["available_at"]>=cutoff]
        found.sort(key=lambda s:(s["available_at"],s["id"]),reverse=True)
        with self.lock:
            self.signals=found
            self.meta.update(status="live",checked_at=now_ms,evaluated_bars=expected,pattern_count=len(found),
                             scan_to=self.last_time+step,last_evaluated_bar=self.last_time,last_available_at=self.last_time+step,
                             winner_observations=len(found),error=None)
        return found
