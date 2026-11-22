"""Closed-candle adapter around the unchanged upstream PatternMatcher.

Every eligible candle is evaluated, including candles with no winning pattern.
The SQLite ledger is a reproducible cache, not an alternate source of prices.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import threading

import pandas as pd

from similar_engine import PatternMatcher

METHODS = ("EMA Peaks", "Pivot Window", "ZigZag Limit")
SECONDS = {"15m": 900, "1h": 3600, "4h": 14400}
UPSTREAM_COMMIT = "a502cc2ccc1df17bf5385ea294381718f814b3ce"
ENGINE_SHA = hashlib.sha256(Path(__file__).with_name("similar_engine.py").read_bytes()).hexdigest()
PIPELINE_VERSION = "closed-120-best-multiasset-v2"


def scan_cutoff(now_ms):
    """Exact two calendar months using exchange time, without rounding to days."""
    return int((pd.Timestamp(now_ms, unit="ms", tz="UTC") - pd.DateOffset(months=2)).timestamp())


def make_matchers(tf, symbol="BTCUSDT"):
    matchers = [(method, PatternMatcher.for_tf_method(tf, method)) for method in METHODS]
    if symbol != "BTCUSDT":
        # Reuse the original shapes/method whitelist, not BTC's fitted trading
        # direction inversions or historical performance as NEAR statistics.
        for _, matcher in matchers:
            matcher.win_rates = {}
            matcher.direction_overrides = {}
            matcher.sim_thresholds = {}
    return matchers


def window_winner(tf, view, matchers=None, symbol="BTCUSDT"):
    """Same window, method order, freshness check and strict > tie rule as app.py."""
    best = None
    best_score = 0
    for method, matcher in matchers or make_matchers(tf, symbol):
        if not matcher.templates:
            continue
        name, score, ext = matcher.search_pattern(view, method=method)
        if name != "None" and score > best_score and ext and len(view) - 1 - ext[-1][0] <= 10:
            best_score = score
            best = (method, matcher, name, score, ext)
    if best is None:
        return None
    method, matcher, name, score, ext = best
    price = float(view.Close.iloc[-1])
    direction = matcher.resolve_direction(name, price, float(ext[-1][1]))
    points = [{"time": int(view.index[int(p[0])].timestamp()), "value": float(p[1])} for p in ext]
    height = max(p["value"] for p in points) - min(p["value"] for p in points)
    sign = 1 if direction == "Up" else -1
    detected = int(view.index[-1].timestamp())
    identity = [symbol, tf, method, name, direction, [p["time"] for p in points]]
    key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()[:24]
    return {
        "id": f"{symbol}-{tf}-{key}", "symbol": symbol, "ticker": symbol.removesuffix("USDT"),
        "tf": tf, "name": name, "method": method,
        "direction": "LONG" if sign == 1 else "SHORT", "similarity": float(score) * 100,
        "detected_at": detected, "available_at": detected + SECONDS[tf],
        "entry": price, "tp": price + sign * height, "sl": price - sign * height,
        "points": points, "configured_win_rate": matcher.win_rates.get(name),
        "calibrated": name in matcher.sim_thresholds,
        "threshold": matcher.sim_thresholds.get(name, 0.85),
        "calibration_symbol": "BTCUSDT" if symbol == "BTCUSDT" else None,
        "model_profile": "upstream_btc" if symbol == "BTCUSDT" else "transferred_shapes_unvalidated",
    }


class PatternPipeline:
    def __init__(self, tf, database, symbol="BTCUSDT"):
        if symbol not in ("BTCUSDT", "NEARUSDT"):
            raise ValueError("Coin không được hỗ trợ.")
        self.tf, self.database, self.symbol = tf, Path(database), symbol
        baseline=Path(__file__).resolve().parents[1]/"btc-baseline.json"
        if symbol=="BTCUSDT" and baseline.exists() and json.loads(baseline.read_text(encoding="utf-8"))["source_sha256"]!=ENGINE_SHA:
            raise ValueError("BTC baseline đã thay đổi; từ chối chạy bản khác cấu hình đã cố định.")
        self.lock = threading.RLock()
        self.update_lock = threading.Lock()
        self.evaluations = {}
        self.signals = []
        self.meta = {"status": "backfilling", "symbol": symbol, "timeframe": tf,
                     "model_profile": "upstream_btc" if symbol == "BTCUSDT" else "transferred_shapes_unvalidated",
                     "calibration_symbol": "BTCUSDT" if symbol == "BTCUSDT" else None,
                     "evaluated_bars": 0, "expected_bars": 0,
                     "pattern_count": 0, "upstream_commit": UPSTREAM_COMMIT,
                     "engine_sha256": ENGINE_SHA, "window_bars": 120, "months": 2,
                     "methods": list(METHODS), "version": PIPELINE_VERSION,
                     "last_evaluated_bar": None, "error": None}

    def fail(self, message):
        with self.lock:
            self.meta.update(status="error", error=str(message))

    def snapshot(self):
        with self.lock:
            return [dict(s) for s in self.signals], dict(self.meta)

    def _connect(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.database, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS asset_evaluations (version TEXT, symbol TEXT, tf TEXT, bar_time INTEGER, input_hash TEXT, winner TEXT, PRIMARY KEY(version,symbol,tf,bar_time))")
        return conn

    def update(self, df, now_ms):
        """df contains only final, gap-checked candles. No unfinished bar is read."""
        with self.update_lock:
            return self._update(df, now_ms)

    def _update(self, df, now_ms):
        step = SECONDS[self.tf]
        cutoff = scan_cutoff(now_ms)
        now = now_ms // 1000
        times = [int(t.timestamp()) for t in df.index]
        if any(b - a != step for a, b in zip(times, times[1:])):
            raise ValueError("Khoảng trống nến: dừng pipeline để tải bù.")
        positions = [i for i, t in enumerate(times) if t + step >= cutoff and t + step <= now]
        if not positions or positions[0] < 119:
            raise ValueError("Thiếu 119 nến làm nóng trước khoảng quét hai tháng.")
        first, last = positions[0], positions[-1]
        pending = [i for i in positions if times[i] not in self.evaluations]
        with self.lock:
            self.meta.update(status="backfilling" if not self.evaluations else "catching_up" if pending else "live",
                             scan_from=cutoff, scan_to=times[last] + step,
                             expected_bars=len(positions), source_time=now_ms, error=None)
        version = ENGINE_SHA + ":" + PIPELINE_VERSION
        # In-memory candles are finalized by the exchange; only newly closed
        # bars run the model. On process restart validate EACH cached input.
        bootstrap = not self.evaluations
        matchers = make_matchers(self.tf, self.symbol)
        values = df[["Open", "High", "Low", "Close", "Volume"]].to_numpy(dtype="float64")
        reuse_count = 0
        with closing(self._connect()) as conn, conn:
            cached = {row[0]: (row[1], row[2]) for row in conn.execute(
                "SELECT bar_time,input_hash,winner FROM asset_evaluations WHERE version=? AND symbol=? AND tf=? AND bar_time BETWEEN ? AND ?",
                (version, self.symbol, self.tf, times[first], times[last]))} if bootstrap else {}
            for n, pos in enumerate(pending):
                ts = times[pos]
                fingerprint = hashlib.sha256(values[pos-119:pos+1].tobytes() + str(times[pos-119]).encode()).hexdigest()
                saved = cached.get(ts)
                if saved and saved[0] == fingerprint:
                    signal = json.loads(saved[1]) if saved[1] else None
                    reuse_count += 1
                else:
                    signal = window_winner(self.tf, df.iloc[pos-119:pos+1], matchers, self.symbol)
                    conn.execute("INSERT OR REPLACE INTO asset_evaluations VALUES (?,?,?,?,?,?)",
                                 (version, self.symbol, self.tf, ts, fingerprint, json.dumps(signal) if signal else None))
                self.evaluations[ts] = signal
                if (n + 1) % 128 == 0:
                    conn.commit()
                    with self.lock:
                        self.meta.update(evaluated_bars=sum(t in self.evaluations for t in times[first:last+1]),
                                         last_evaluated_bar=ts)
            conn.commit()
            # Keep three months of reproducible evaluations; this removes only
            # obsolete derived cache rows, never source files or user records.
            conn.execute("DELETE FROM asset_evaluations WHERE version=? AND symbol=? AND tf=? AND bar_time<?",
                         (version, self.symbol, self.tf, times[0]))
        self.evaluations = {t: self.evaluations[t] for t in times[first:last+1]}
        grouped = {}
        observations = 0
        for ts, winner in sorted(self.evaluations.items()):
            if winner is None:
                continue
            observations += 1
            if winner["id"] not in grouped:
                grouped[winner["id"]] = {**winner, "last_seen_at": winner["available_at"], "observations": 0}
            grouped[winner["id"]]["last_seen_at"] = winner["available_at"]
            grouped[winner["id"]]["observations"] += 1
        signals = sorted(grouped.values(), key=lambda s: (s["available_at"], s["id"]), reverse=True)
        with self.lock:
            self.signals = signals
            self.meta.update(status="live", evaluated_bars=len(positions), pattern_count=len(signals),
                             winner_observations=observations, last_evaluated_bar=times[last],
                             last_available_at=times[last] + step, checked_at=now_ms,
                             reused_evaluations=self.meta.get("reused_evaluations", 0) + reuse_count)
        return signals
