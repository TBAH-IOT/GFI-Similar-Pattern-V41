"""GFI local terminal: public Binance prices, local pattern computation."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import gzip
import hashlib
from pathlib import Path
import sys
import threading
import time
import webbrowser
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "engine"))
from similar_engine import PatternMatcher, _load_price_csv, WIN_RATE_BY_TF_METHOD
from research_model import Scanner, MODEL_HASH
from forecast_selection import representative_path
from occurrence_identity import collapse_occurrences
from directional_prediction import directional_outcome_prediction
from path_integrity import contiguous_path_groups
from horizon_forecast import HorizonService
from occurrence_horizon_v40 import OccurrenceHorizonV40
from expanding_pipeline import ExpandingPipeline as ValidatedPipeline
from pipeline import PatternPipeline

SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
PATTERN_TIMEFRAMES = ("15m", "1h", "4h")
METHODS = ("EMA Peaks", "Pivot Window", "ZigZag Limit")
BINANCE_BASE = "https://data-api.binance.vision"
ASSET_CATALOG = json.loads((ROOT/'assets.json').read_text(encoding='utf-8'))
ASSETS = ASSET_CATALOG['assets']
SIMILAR_ASSETS = ASSET_CATALOG.get('similar_assets', {})
ASSET_FRAMES={symbol:("15m","1h","4h","1d") for symbol in ASSETS}
LIVE_CACHE = {}
LIVE_LOCKS = {(symbol, tf): threading.RLock() for symbol in ASSETS for tf in SECONDS}
UPSTREAM_CACHE = {}
UPSTREAM_LOCK = threading.RLock()
PIPELINES = {(symbol,tf):(PatternPipeline(tf,ROOT/f"runtime/BTCUSDT_{tf}-ledger.sqlite3",symbol) if symbol=="BTCUSDT" and tf!="1d" else ValidatedPipeline(tf,ROOT/f"runtime/{symbol}_{tf}-ledger.sqlite3",symbol))
             for symbol in ASSETS for tf in PATTERN_TIMEFRAMES}
PIPELINE_STOP = threading.Event()
FULL_PATH_CACHE = {}
BOOTSTRAP_CACHE = {}
SIGNAL_RESPONSE_CACHE = {}
SIGNAL_CACHE_LOCKS = {(symbol,tf):threading.RLock() for symbol in ASSETS for tf in PATTERN_TIMEFRAMES}
FULL_PATH_LOCK = threading.RLock()
FULL_PATH_FUTURES = {}
PATH_EXECUTOR = ThreadPoolExecutor(max_workers=1)
PATH_CACHE_VERSION = 'entry-bar-ten-candles-v1'
HORIZON_SERVICE = HorizonService(ROOT)
V41_OCCURRENCE_HORIZON = OccurrenceHorizonV40(ROOT)
NAMES = {
    "Triangle_Ascending": "Tam giác tăng", "Diamond_Top": "Đỉnh kim cương",
    "Broadening_Bottom": "Đáy mở rộng", "Triple_Top_Wide": "Ba đỉnh mở rộng",
    "Wedge_Falling": "Nêm giảm", "Triple_Bottom_Wide": "Ba đáy mở rộng",
    "Cup_and_Handle": "Cốc tay cầm", "Double_Bottom": "Hai đáy",
    "Triple_Top": "Ba đỉnh", "Head_and_Shoulders_Top": "Vai đầu vai",
    "Head_and_Shoulders_Bottom": "Vai đầu vai ngược", "Pennant_Bearish": "Cờ đuôi nheo giảm",
    "Wedge_Rising": "Nêm tăng",
}


def safe_log(value):
    """Keep a transient upstream error from killing a Windows worker log."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def stamp(value):
    # The CSV timestamps have no offset. Preserve them as UTC for this demo,
    # explicitly disclose that assumption in the data dialog.
    return int(pd.Timestamp(value).timestamp())


@lru_cache(maxsize=3)
def frame(tf):
    df = _load_price_csv(str(ROOT / "Data" / f"data_btc_price_{tf}.csv"))
    if df is None or df.empty:
        raise ValueError("Không đọc được dữ liệu BTC.")
    df = df[~df.index.duplicated(keep="last")].dropna().sort_index()
    # The final row may be an unfinished candle. Exclude it consistently.
    return df.iloc[:-1].copy()


def outcome(df, signal, until):
    start = signal["bar_index"] + 1
    # This replay demo expires a trade after 48 bars. Ambiguous intrabar hits
    # stay ambiguous; they must never be silently counted as winners.
    end = min(until, signal["bar_index"] + 48)
    long = signal["direction"] == "LONG"
    for pos in range(start, end + 1):
        row = df.iloc[pos]
        tp_hit = row.High >= signal["tp"] if long else row.Low <= signal["tp"]
        sl_hit = row.Low <= signal["sl"] if long else row.High >= signal["sl"]
        if tp_hit and sl_hit:
            return {"status": "AMBIGUOUS", "close": None, "pnl": None, "closed_at": stamp(df.index[pos])}
        if tp_hit or sl_hit:
            price = signal["tp"] if tp_hit else signal["sl"]
            pnl = (price / signal["entry"] - 1) * (1 if long else -1) * 100
            return {"status": "TP" if tp_hit else "SL", "close": price, "pnl": round(pnl, 2), "closed_at": stamp(df.index[pos])}
    if until >= signal["bar_index"] + 48:
        price = float(df.Close.iloc[end])
        pnl = (price / signal["entry"] - 1) * (1 if long else -1) * 100
        return {"status": "EXPIRED", "close": price, "pnl": round(pnl, 2), "closed_at": stamp(df.index[end])}
    return {"status": "OPEN", "close": None, "pnl": None, "closed_at": None}


@lru_cache(maxsize=3)
def scan(tf):
    df = frame(tf)
    return scan_frame(tf, df)


def scan_frame(tf, df):
    matchers = [(method, PatternMatcher.for_tf_method(tf, method)) for method in METHODS]
    found, seen = [], set()
    for pos in range(max(119, len(df) - 720), len(df)):
        view = df.iloc[pos - 119:pos + 1]
        candidates = []
        for method, matcher in matchers:
            if not matcher.templates:
                continue
            name, score, ext = matcher.search_pattern(view, method=method)
            if name == "None" or not ext or 119 - ext[-1][0] > 10:
                continue
            # Never modify a previously emitted signal using later candles.
            direction = matcher.resolve_direction(name, float(view.Close.iloc[-1]), float(ext[-1][1]))
            if direction not in ("Up", "Down"):
                continue
            pts = [{"time": stamp(view.index[int(p[0])]), "value": round(float(p[1]), 2)} for p in ext]
            key = (name, direction, tuple(p["time"] for p in pts))
            if key in seen:
                continue
            candidates.append((float(score), name, method, matcher, pts, direction, key))
        # One best new pattern per candle keeps the visual/history readable.
        if not candidates:
            continue
        score, name, method, matcher, pts, direction, key = max(candidates, key=lambda c: c[0])
        seen.add(key)
        price = float(view.Close.iloc[-1])
        height = max(p["value"] for p in pts) - min(p["value"] for p in pts)
        if height <= 0:
            continue
        sign = 1 if direction == "Up" else -1
        found.append({
            "id": f"{tf}-{stamp(df.index[pos])}-{name}", "tf": tf,
            "name": name, "label": NAMES.get(name, name.replace("_", " ")),
            "similarity": round(score * 100, 2), "method": method,
            "direction": "LONG" if sign == 1 else "SHORT",
            "detected_at": stamp(df.index[pos]), "available_at": stamp(df.index[pos]) + SECONDS[tf],
            "bar_index": pos, "entry": round(price, 2),
            "tp": round(price + sign * height, 2), "sl": round(price - sign * height, 2),
            "points": pts, "configured_win_rate": matcher.win_rates.get(name),
            "calibrated": name in matcher.sim_thresholds,
            "threshold": matcher.sim_thresholds.get(name, 0.85),
        })
    return found


def end_position(df, params):
    raw = params.get("end", [None])[0]
    if raw is None:
        return len(df) - 1
    try:
        end = pd.Timestamp(int(raw), unit="s", tz=df.index.tz)
        return max(119, min(len(df) - 1, int(df.index.searchsorted(end, side="right")) - 1))
    except (ValueError, OverflowError):
        raise ValueError("Thời điểm replay không hợp lệ.")


def market(tf, params):
    df = frame(tf)
    pos = end_position(df, params)
    view = df.iloc[max(0, pos - 359):pos + 1]
    candles = [{"time": stamp(idx), "open": float(r.Open), "high": float(r.High), "low": float(r.Low), "close": float(r.Close), "volume": float(r.Volume)} for idx, r in view.iterrows()]
    count24 = 86400 // SECONDS[tf]
    day = df.iloc[max(0, pos - count24 + 1):pos + 1]
    reference = float(df.Close.iloc[max(0, pos - count24)])
    available = [s for s in scan(tf) if s["bar_index"] <= pos]
    signals = [{**s, **outcome(df, s, pos)} for s in available[-80:]][::-1]
    current = float(df.Close.iloc[pos])
    return {
        "symbol": "BTCUSDT", "timeframe": tf, "mode": "historical_replay",
        "as_of": stamp(df.index[pos]), "data_end": stamp(df.index[-1]),
        "dataset_rows": len(df), "has_next": pos < len(df) - 1,
        "last": current, "change_24h": (current / reference - 1) * 100,
        "high_24h": float(day.High.max()), "low_24h": float(day.Low.min()),
        "volume_24h": float(day.Volume.sum()), "candles": candles, "signals": signals,
        "scanned_bars": min(720, len(df)), "source": "Pattern_Detection_GFI / CSV",
    }


class MarketUnavailable(Exception):
    pass


def upstream(path, **params):
    url = BINANCE_BASE + path + ("?" + urlencode(params) if params else "")
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "GFI-Local-Terminal/1.0", "Accept": "application/json"})
            with urlopen(request, timeout=12) as response:
                result = json.load(response)
            if isinstance(result, dict) and "code" in result:
                raise MarketUnavailable("Nguồn Binance trả lỗi dữ liệu. Thử kết nối lại.")
            return result
        except HTTPError as error:
            if error.code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(.5 * (attempt + 1))
                continue
            raise MarketUnavailable(f"Binance HTTP {error.code}. Chưa thể tải giá trực tiếp.") from error
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            if attempt < 2:
                time.sleep(.5 * (attempt + 1))
                continue
            raise MarketUnavailable("Không kết nối được Binance. Kiểm tra mạng và thử lại.") from error


def cached_upstream(path, ttl=2, **params):
    key = (path, tuple(sorted(params.items())))
    with UPSTREAM_LOCK:
        cached = UPSTREAM_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
        data = upstream(path, **params)
        UPSTREAM_CACHE[key] = (time.monotonic(), data)
        return data


def exchange_time():
    return int(cached_upstream("/api/v3/time", ttl=1)["serverTime"])


def asset_metadata(symbol):
    info = cached_upstream("/api/v3/exchangeInfo", ttl=3600, symbol=symbol)
    entry = next((s for s in info.get("symbols", []) if s["symbol"] == symbol), None)
    if not entry or entry["status"] != "TRADING" or not entry.get("isSpotTradingAllowed", False):
        raise MarketUnavailable(f"{symbol} chưa sẵn sàng trên Binance Spot.")
    tick = next(f["tickSize"] for f in entry["filters"] if f["filterType"] == "PRICE_FILTER")
    precision = max(0, -Decimal(tick).normalize().as_tuple().exponent)
    return {**ASSETS[symbol], "symbol": symbol, "quote": entry["quoteAsset"],
            "price_precision": precision, "min_move": float(tick)}


def window_start(now_ms, tf="1h"):
    """Three calendar months, UTC midnight, using the exchange's clock."""
    date=pd.Timestamp(now_ms,unit="ms",tz="UTC")
    start=(date-pd.DateOffset(months=3)).normalize()
    seconds=int(start.timestamp())
    return (seconds//SECONDS[tf]*SECONDS[tf])*1000


def parse_bars(rows, now_ms, tf):
    result = []
    for row in rows:
        if len(row) < 7:
            raise MarketUnavailable("Định dạng nến từ Binance không hợp lệ.")
        opened, closed = int(row[0]), int(row[6])
        values = [float(row[k]) for k in range(1, 6)]
        o, h, l, c, v = values
        origin=0
        if not all(np.isfinite(values)) or min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or v < 0 or (opened-origin) % (SECONDS[tf] * 1000) != 0:
            raise MarketUnavailable("Nguồn trả về nến không hợp lệ; tạm ngừng cập nhật.")
        result.append({"time": opened // 1000, "open": o, "high": h, "low": l, "close": c, "volume": v, "closed": closed < now_ms})
    return result


def fetch_history(tf, now_ms, start_ms, symbol="BTCUSDT"):
    step = SECONDS[tf] * 1000
    ranges = [(start, min(start + 1000 * step - 1, now_ms)) for start in range(start_ms, now_ms + 1, 1000 * step)]

    def page(bounds):
        start, end = bounds
        return upstream("/api/v3/klines", symbol=symbol, interval=tf, startTime=start, endTime=end, limit=1000)

    with ThreadPoolExecutor(max_workers=4) as executor:
        pages = list(executor.map(page, ranges))
    by_time = {bar["time"]: bar for rows in pages for bar in parse_bars(rows, now_ms, tf)}
    bars = [by_time[key] for key in sorted(by_time)]
    if not bars or bars[0]["time"] > start_ms // 1000 + SECONDS[tf] or bars[-1]["time"] + SECONDS[tf] <= now_ms // 1000:
        raise MarketUnavailable("Nguồn chưa trả đủ ba tháng nến đến hiện tại.")
    if any(b["time"] - a["time"] != SECONDS[tf] for a, b in zip(bars, bars[1:])):
        raise MarketUnavailable("Phát hiện khoảng trống trong dữ liệu nến. Hãy thử tải lại.")
    return bars


def live_bars(tf, symbol="BTCUSDT"):
    now_ms = exchange_time()
    start_ms = window_start(now_ms,tf)
    key = (symbol, tf)
    with LIVE_LOCKS[key]:
        entry = LIVE_CACHE.get(key)
        if not entry:
            entry = {"bars": fetch_history(tf, now_ms, start_ms, symbol), "updated": time.monotonic(), "bucket": now_ms // (SECONDS[tf] * 1000)}
            LIVE_CACHE[key] = entry
        elif time.monotonic() - entry["updated"] >= 2 or entry["bucket"] != now_ms // (SECONDS[tf] * 1000):
            last_ms = entry["bars"][-1]["time"] * 1000
            if now_ms - last_ms > SECONDS[tf] * 1000 * 3:
                fresh = fetch_history(tf, now_ms, max(start_ms, last_ms), symbol)
            else:
                fresh = parse_bars(upstream("/api/v3/klines", symbol=symbol, interval=tf, limit=3), now_ms, tf)
            merged = {bar["time"]: bar for bar in entry["bars"] if bar["time"] * 1000 >= start_ms}
            merged.update({bar["time"]: bar for bar in fresh})
            updated = [merged[key] for key in sorted(merged) if key * 1000 >= start_ms]
            if any(b["time"] - a["time"] != SECONDS[tf] for a, b in zip(updated, updated[1:])):
                # Recover missed candles before allowing the scanner to advance.
                updated = fetch_history(tf, now_ms, start_ms, symbol)
            entry["bars"] = updated
            entry["updated"] = time.monotonic()
            entry["bucket"] = now_ms // (SECONDS[tf] * 1000)
        # Derive closure from exchange time, including candles retained in cache.
        bars = [{**bar, "closed": (bar["time"] + SECONDS[tf]) * 1000 <= now_ms} for bar in entry["bars"]]
        return bars, now_ms, start_ms


def bars_frame(bars):
    df = pd.DataFrame(bars)
    df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)
    return df.rename(columns={key: key.capitalize() for key in ("open", "high", "low", "close", "volume")})


def frozen_prediction(signal):
    """Fallback forecast for the frozen BTC baseline when no expanding history is attached."""
    rate=signal.get("configured_win_rate")
    entry=float(signal.get("entry") or 0)
    height=abs(float(signal.get("tp") or 0)-entry) if entry else 0
    if not isinstance(rate,(int,float)) or not 0<=rate<=1 or entry<=0 or height<=0:
        return None
    move=height/entry
    success=float(rate); failure=1-success
    if signal.get("direction")=="LONG":
        up_probability,down_probability=success,failure
    else:
        up_probability,down_probability=failure,success
    return {"up_probability":round(up_probability,4),"down_probability":round(down_probability,4),
            "up_median_move":round(move,6),"down_median_move":round(move,6),"median_tp_sl_move":round(move,6),"sample_count":None,
            "horizon_bars":7,"basis":"tp_sl_1r"}


def _build_full_historical_paths(symbol, tf):
    """Scan the complete local history once and cache compact analogue paths."""
    key = (symbol, tf)
    source = ROOT / "runtime" / "history" / f"{symbol}_{tf}.csv.gz"
    if not source.exists():
        return {}
    raw = pd.read_csv(source).drop_duplicates("time", keep="last").sort_values("time")
    last_time = int(raw.time.iloc[-1]) if len(raw) else 0
    with FULL_PATH_LOCK:
        cached = FULL_PATH_CACHE.get(key)
        if cached and cached[0] == last_time:
            return cached[1]

    history = bars_frame(raw.to_dict("records"))
    positions = {stamp(index): position for position, index in enumerate(history.index)}
    scanner = Scanner(symbol, tf)
    groups = defaultdict(list)
    for bar in raw.to_dict("records"):
        for raw_signal in scanner.step(bar):
            detected_at = int(raw_signal.get("detected_at", 0))
            available_at = int(raw_signal.get("available_at", 0))
            entry_index = positions.get(available_at)
            if entry_index is None or detected_at not in positions:
                continue
            entry = float(history.Open.iloc[entry_index])
            if entry <= 0 or raw_signal.get("height", 0) <= 0:
                continue
            base = raw_signal["name"]
            for variant, direction_sign in (("direct", raw_signal["sign"]), ("inverse", -raw_signal["sign"])):
                candidate = {**raw_signal,
                             "variant": variant,
                             "base_pattern": base,
                             "bar_index": entry_index,
                             "entry": entry,
                             "tp": entry + direction_sign * raw_signal["height"],
                             "sl": entry - direction_sign * raw_signal["height"],
                             "direction": "LONG" if direction_sign == 1 else "SHORT"}
                result = outcome(history, candidate, len(history) - 1)
                if result["status"] not in {"TP", "SL"}:
                    continue
                # Entry is this bar's OPEN: the path must include this bar,
                # otherwise the averaged first candle begins after a gap.
                future = history.iloc[entry_index:entry_index + 12]
                if len(future) < 12:
                    continue
                path = []
                for index, row in future.iterrows():
                    path.append({"open": float(row.Open) / entry,
                                 "high": float(row.High) / entry,
                                 "low": float(row.Low) / entry,
                                 "close": float(row.Close) / entry})
                is_up = (candidate["direction"] == "LONG" and result["status"] == "TP") or \
                        (candidate["direction"] == "SHORT" and result["status"] == "SL")
                groups[(base, raw_signal["method"], variant)].append({
                    "id": f"history-{symbol}-{tf}-{detected_at}-{base}-{variant}",
                    "source_symbol": symbol,
                    "base_pattern": base,
                    "method": raw_signal["method"],
                    "variant": variant,
                    "available_at": available_at,
                    "resolved_at": result.get('closed_at'),
                    "similarity": float(raw_signal.get("similarity", raw_signal.get("score", 0) * 100)),
                    "is_up": is_up,
                    "_normalized_path": path,
                })
    compact = {}
    for group_key, rows in groups.items():
        rows.sort(key=lambda row: row["available_at"])
        # Keep every completed analogue. The V35 preview should use the
        # largest honest sample available for a coin/timeframe instead of a
        # hidden fixed-size slice.
        compact[group_key] = rows
    compact = contiguous_path_groups(compact,raw.time.to_numpy(),SECONDS[tf])
    with FULL_PATH_LOCK:
        FULL_PATH_CACHE[key] = (last_time, compact)
    # Save completed scans so a UI/server update can reuse the analogue
    # library instead of losing it on every process restart.
    path_cache = ROOT / 'runtime' / f'{symbol}_{tf}-forecast-paths.json.gz'
    document = {'version': PATH_CACHE_VERSION, 'model_hash': MODEL_HASH, 'path_contiguity_checked':True,
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'source_mtime': source.stat().st_mtime_ns, 'last_time': last_time,
                'groups': [{'key': list(group_key), 'rows': rows} for group_key, rows in compact.items()]}
    temporary = path_cache.with_suffix('.tmp')
    try:
        with gzip.open(temporary, 'wt', encoding='utf-8') as output:
            json.dump(document, output, separators=(',', ':'))
        temporary.replace(path_cache)
    except OSError as error:
        print(f'Forecast cache: {safe_log(error)}', flush=True)
    return compact


def _full_historical_paths(symbol, tf):
    """Return ready analogues and schedule a non-blocking full-history scan."""
    key = (symbol, tf)
    with FULL_PATH_LOCK:
        cached = FULL_PATH_CACHE.get(key)
        if cached:
            return cached[1]
        source = ROOT / 'runtime' / 'history' / f'{symbol}_{tf}.csv.gz'
        saved = ROOT / 'runtime' / f'{symbol}_{tf}-forecast-paths.json.gz'
        if source.exists() and saved.exists():
            try:
                with gzip.open(saved, 'rt', encoding='utf-8') as input_file:
                    document = json.load(input_file)
                same_source = document.get('source_mtime') == source.stat().st_mtime_ns or (document.get('source_sha256') and document['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest())
                if document.get('version') == PATH_CACHE_VERSION and document.get('model_hash') == MODEL_HASH and same_source:
                    groups = {tuple(group['key']): group['rows'] for group in document['groups']}
                    if not document.get('path_contiguity_checked'):
                        groups=contiguous_path_groups(groups,pd.read_csv(source,usecols=['time']).time.to_numpy(),SECONDS[tf])
                    FULL_PATH_CACHE[key] = (document['last_time'], groups)
                    return groups
            except (OSError, ValueError, KeyError, TypeError):
                pass
        future = FULL_PATH_FUTURES.get(key)
        if future is None or future.done():
            if future is not None:
                try:
                    future.result()
                except Exception:
                    pass
                cached = FULL_PATH_CACHE.get(key)
                if cached:
                    return cached[1]
            FULL_PATH_FUTURES[key] = PATH_EXECUTOR.submit(_build_full_historical_paths, symbol, tf)
    return {}


def _variant_rank(signal):
    """Rank direct/inverse candidates for one exact historical match.

    The research pipeline evaluates both directions independently.  The
    terminal should nevertheless present one decision: prefer a qualified
    model, then the strongest out-of-sample win rate, then shape similarity.
    Shape similarity is never treated as accuracy.
    """
    qualified = bool(signal.get("actionable"))
    win_rate = signal.get("configured_win_rate")
    samples = signal.get("validation_samples")
    minimum = signal.get("minimum_samples")
    if not qualified and isinstance(win_rate, (int, float)) and isinstance(samples, (int, float)):
        qualified = samples >= (minimum or 0) and win_rate > .55
    return (
        1 if qualified else 0,
        float(win_rate) if isinstance(win_rate, (int, float)) else -1.0,
        float(signal.get("similarity") or 0),
        int(samples) if isinstance(samples, (int, float)) else -1,
        float(signal.get("mean_net_return") or -1e9),
        1 if signal.get("variant") == "direct" else 0,
    )


def _pivot_signature(signal):
    points = signal.get("points") or []
    if not points:
        return None
    signature = []
    for point in points:
        try:
            signature.append((int(point["time"]), round(float(point["value"]), 6)))
        except (KeyError, TypeError, ValueError):
            return None
    return tuple(signature)


def _historical_path_prediction(signal, candidates, df, positions, step, prediction):
    """Build average OHLC paths from all available earlier analogue matches.

    The existing accuracy probabilities remain TP/SL statistics. These paths
    are a separate visual layer: candidates are matched by the same chart
    pattern, detector and evaluated direction, then their future candles are
    normalized to each candidate's entry before averaging.
    """
    if not prediction or not signal.get("available_at"):
        return prediction
    base = signal.get("base_pattern") or signal.get("name", "").removesuffix("__Inverse")
    variant = signal.get("variant")
    method = signal.get("method")
    current_similarity = float(signal.get("similarity") or 0)
    horizon = max(3, min(int(prediction.get("candle_horizon_bars") or 10), 12))
    analogues = []
    seen_analogues = set()
    for candidate in candidates:
        if candidate.get("id") == signal.get("id") or candidate.get("available_at") is None:
            continue
        if candidate["available_at"] >= signal["available_at"]:
            continue
        if candidate["available_at"] + horizon * step > signal["available_at"]:
            continue
        resolved_at = candidate.get('resolved_at') or candidate.get('closed_at')
        if resolved_at is not None and int(resolved_at)+step > signal['available_at']:
            continue
        candidate_base = candidate.get("base_pattern") or candidate.get("name", "").removesuffix("__Inverse")
        method_fallback = bool(candidate.get("_method_fallback"))
        if candidate_base != base or (candidate.get("method") != method and not method_fallback):
            continue
        if variant in {"direct", "inverse"} and candidate.get("variant") != variant:
            continue
        source_symbol = candidate.get("source_symbol") or signal.get("symbol")
        identity = (source_symbol, candidate["available_at"], candidate_base, candidate.get("method"), candidate.get("variant"))
        if identity in seen_analogues:
            continue
        seen_analogues.add(identity)
        if candidate.get("_normalized_path") is not None:
            path = candidate["_normalized_path"]
            if len(path) < horizon:
                continue
            is_up = bool(candidate.get("is_up"))
            analogues.append((abs(float(candidate.get("similarity") or 0) - current_similarity),
                              -int(candidate["available_at"]), is_up, path,
                              source_symbol))
            continue
        if candidate.get("status") not in {"TP", "SL"}:
            continue
        bar_index = candidate.get("bar_index")
        entry = float(candidate.get("entry") or 0)
        if not isinstance(bar_index, int) or entry <= 0:
            continue
        entry_index = positions.get(candidate["available_at"])
        if entry_index is None:
            continue
        future = df.iloc[entry_index:entry_index + horizon]
        if len(future) < horizon:
            continue
        is_up = (candidate.get("direction") == "LONG" and candidate.get("status") == "TP") or \
                (candidate.get("direction") == "SHORT" and candidate.get("status") == "SL")
        path = []
        for index, row in future.iterrows():
            path.append({
                "time": int(pd.Timestamp(index).timestamp()),
                "open": float(row.Open) / entry,
                "high": float(row.High) / entry,
                "low": float(row.Low) / entry,
                "close": float(row.Close) / entry,
            })
        analogues.append((abs(float(candidate.get("similarity") or 0) - current_similarity),
                          -int(candidate["available_at"]), is_up, path,
                          source_symbol))
    # Keep the full available set. The matching pool is already constrained
    # by pattern, detector and evaluated direction; truncating it to 30 makes
    # sparse coins look more certain than their history supports.
    analogues.sort(key=lambda item: (item[0], item[1]))

    def average_paths(items):
        if not items:
            return []
        output = []
        for offset in range(horizon):
            rows = [item[3][offset] for item in items]
            output.append({
                "time_offset": offset + 1,
                "open": round(float(np.mean([row["open"] for row in rows])), 8),
                "high": round(float(np.mean([row["high"] for row in rows])), 8),
                "low": round(float(np.mean([row["low"] for row in rows])), 8),
                "close": round(float(np.mean([row["close"] for row in rows])), 8),
            })
        return output

    def average_pullback(items, side):
        """Return empirical adverse excursion and its average timing.

        The forecast curve uses these two values instead of inventing a
        pullback amplitude: up paths contribute their average low below the
        normalized entry, while down paths contribute their average high above
        it. Both are measured on the same horizon as the displayed candles.
        """
        excursions = []
        phases = []
        for item in items:
            path = item[3][:horizon]
            if not path:
                continue
            if side == "up":
                values = [float(row["low"]) for row in path]
                extreme = min(values)
                excursion = max(0.0, 1.0 - extreme)
            else:
                values = [float(row["high"]) for row in path]
                extreme = max(values)
                excursion = max(0.0, extreme - 1.0)
            excursions.append(excursion)
            phases.append(values.index(extreme) / max(1, len(path) - 1))
        if not excursions:
            return 0.0, 0.24
        return float(np.mean(excursions)), float(np.mean(phases))

    up = [item for item in analogues if item[2]]
    down = [item for item in analogues if not item[2]]
    up_pullback_pct, up_pullback_phase = average_pullback(up, "up")
    down_pullback_pct, down_pullback_phase = average_pullback(down, "down")
    source_symbol = signal.get("symbol")
    cross_asset_count = sum(1 for item in analogues if item[4] and item[4] != source_symbol)
    return {**prediction,
            "path_basis": "mean_all_available_similar_patterns_with_peer_coin" if cross_asset_count else "mean_all_available_similar_patterns",
            "path_start": "entry_bar",
            "candle_horizon_bars": horizon,
            "candle_basis": "closest_real_path_to_group_mean",
            "path_sample_count": len(analogues),
            "path_same_asset_count": len(analogues) - cross_asset_count,
            "path_cross_asset_count": cross_asset_count,
            "up_path_count": len(up),
            "down_path_count": len(down),
            "up_pullback_pct": round(up_pullback_pct, 8),
            "up_pullback_phase": round(up_pullback_phase, 6),
            "down_pullback_pct": round(down_pullback_pct, 8),
            "down_pullback_phase": round(down_pullback_phase, 6),
            "up_candles": average_paths(up),
            "down_candles": average_paths(down),
            "up_representative": representative_path(up, horizon, 'up', signal.get('symbol')),
            "down_representative": representative_path(down, horizon, 'down', signal.get('symbol'))}


def select_optimized_variants(signals):
    """Expose one optimized label for each exact geometric match.

    Distinct occurrences remain distinct. Candidates sharing the same
    detector, recognition time and pivot sequence compete even when the
    catalog gave them different names, preventing one setup from appearing
    as several simultaneous patterns in the terminal.
    """
    groups = {}
    passthrough = []
    for signal in signals:
        if signal.get("variant") not in {"direct", "inverse"}:
            passthrough.append(signal)
            continue
        pivot_signature = _pivot_signature(signal)
        if pivot_signature is None:
            base = signal.get("base_pattern") or signal.get("name", "").removesuffix("__Inverse")
            key = ("variant", base, signal.get("method"), signal.get("detected_at"), signal.get("available_at"))
        else:
            key = ("geometry", signal.get("method"), signal.get("detected_at"), signal.get("available_at"), pivot_signature)
        groups.setdefault(key, []).append(signal)

    selected = list(passthrough)
    for candidates in groups.values():
        best = dict(max(candidates, key=_variant_rank))
        # Inverse is an internal evaluated direction, not a second pattern
        # family for the reader.  Direction still communicates LONG/SHORT.
        best["display_name"] = (best.get("display_name") or best.get("name", "Pattern"))\
            .removesuffix(" · Inverse")
        best["optimized_variant"] = best.get("variant", "direct")
        selected.append(best)
    return sorted(selected, key=lambda signal: (signal.get("available_at", 0), signal.get("id", "")), reverse=True)


def _compute_live_signals(tf, bars, symbol="BTCUSDT", include_paths=False):
    if tf not in PATTERN_TIMEFRAMES:
        return []
    closed = [bar for bar in bars if bar["closed"]]
    df = bars_frame(closed)
    found, scan_meta = PIPELINES[symbol, tf].snapshot()
    bootstrap = not found and scan_meta.get('status') not in {'live','no_qualified_patterns','awaiting_validation'}
    if bootstrap:
        found = bootstrap_signals(symbol, tf)
    positions = {stamp(idx): pos for pos, idx in enumerate(df.index)}
    # Use closed bars for both detection and result accounting.
    by_time={b["time"]:b for b in bars}
    result=[]
    for signal in found:
        if signal["detected_at"] not in positions:
            continue
        if symbol=="BTCUSDT" and tf!="1d":
            original={**signal,"bar_index":positions[signal["detected_at"]]}
            result.append({**original,**outcome(df,original,len(df)-1),"accuracy_source":"frozen_btc","actionable":not bootstrap,"backfilled":False,
                           "prediction":original.get("prediction") or frozen_prediction(original)})
            continue
        entry_bar=by_time.get(signal["available_at"])
        if not entry_bar:
            result.append({**signal,"entry":None,"tp":None,"sl":None,"close":None,"pnl":None,"status":"PENDING"})
            continue
        entry=signal['entry'] if bootstrap else entry_bar["open"]; sign=signal["sign"]
        signal={**signal,"entry":entry,"tp":entry+sign*signal["height"],"sl":entry-sign*signal["height"],
                "bar_index":positions[signal["detected_at"]]}
        result.append({**signal,**outcome(df,signal,len(df)-1),"prediction":signal.get("prediction") or frozen_prediction(signal)})
    metrics = {(m['name'],m['method']):m for m in scan_meta.get('metrics',[])}
    result = [{**signal,'prediction':directional_outcome_prediction(signal,metrics)} for signal in result]
    if include_paths and not bootstrap and any(signal.get("prediction") for signal in result):
        full_paths = _full_historical_paths(symbol, tf)
        for index, signal in enumerate(result):
            prediction = signal.get("prediction")
            if not prediction:
                continue
            base = signal.get("base_pattern") or signal.get("name", "").removesuffix("__Inverse")
            variant = signal.get("variant", "direct")
            path_key = (base, signal.get("method"), variant)
            analogues = list(full_paths.get(path_key, []))
            pool = result + analogues
            # When the exact detector has little history, broaden the pool
            # without throwing away the exact matches: first other detectors
            # for the same geometry, then equivalent geometry from peer coins.
            # There is intentionally no 30-sample ceiling; every completed
            # analogue that passes the same identity filters is available to
            # the averaging step.
            for (candidate_base, candidate_method, candidate_variant), rows in full_paths.items():
                if candidate_base == base and candidate_variant == variant and candidate_method != signal.get("method"):
                    pool.extend({**row, "_method_fallback": True} for row in rows)
            for peer_symbol in SIMILAR_ASSETS.get(symbol, ()):
                peer_paths = _full_historical_paths(peer_symbol, tf)
                pool.extend(peer_paths.get(path_key, []))
            result[index] = {**signal, "prediction": _historical_path_prediction(signal, pool, df, positions, SECONDS[tf], prediction)}
    return collapse_occurrences(select_optimized_variants(result))


def _base_live_signals(tf, bars, symbol="BTCUSDT", include_paths=False):
    """Share projections across viewers until the closed-bar/model state changes."""
    if tf not in PATTERN_TIMEFRAMES: return []
    closed_time = next((bar['time'] for bar in reversed(bars) if bar['closed']),None)
    _,meta=PIPELINES[symbol,tf].snapshot()
    libraries=tuple((peer,FULL_PATH_CACHE.get((peer,tf),(None,None))[0])
                    for peer in [symbol,*SIMILAR_ASSETS.get(symbol,[])]) if include_paths else ()
    version=(closed_time,meta.get('status'),meta.get('last_available_at'),meta.get('registry_hash'),
             meta.get('completed_observations'),meta.get('pattern_count'),libraries)
    key=(symbol,tf,include_paths)
    with SIGNAL_CACHE_LOCKS[symbol,tf]:
        saved=SIGNAL_RESPONSE_CACHE.get(key)
        if saved and saved[0]==version: return saved[1]
        result=_compute_live_signals(tf,bars,symbol,include_paths)
        SIGNAL_RESPONSE_CACHE[key]=(version,result)
        return result


def live_signals(tf, bars, symbol="BTCUSDT", include_paths=False, adaptive=False, v41=False):
    signals = _base_live_signals(tf, bars, symbol, include_paths)
    if v41 and signals:
        # Keep the snapshot projection visible during cold start. Lock a live
        # occurrence horizon only after both historical source paths exist;
        # an asynchronous cache miss must not permanently freeze an empty N.
        V41_OCCURRENCE_HORIZON.observe(symbol, tf, bars)
        return [V41_OCCURRENCE_HORIZON.extend(signal, symbol, tf)
                if not signal.get('bootstrap_snapshot') and all(
                    (signal.get('prediction') or {}).get(side + '_representative')
                    for side in ('up', 'down')) else signal for signal in signals]
    return [HORIZON_SERVICE.extend(signal, symbol, tf) for signal in signals] if adaptive else signals


def bootstrap_signals(symbol, tf):
    """Instant historical display while causal workers rebuild live state.

    Cached history is never emitted as a newly actionable live detection.
    Prices/candles continue to come from the current exchange feed. Once a
    worker is ready its current model gate replaces this bootstrap display.
    """
    key = (symbol, tf)
    if key not in BOOTSTRAP_CACHE:
        manifest_path = ROOT/'demo-data/manifest.json'
        if not manifest_path.exists(): return []
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('model_hash') != MODEL_HASH: return []
        path = ROOT/'demo-data'/f'{symbol}_{tf}.json.gz'
        if not path.exists(): return []
        with gzip.open(path,'rt',encoding='utf-8') as source: data=json.load(source)
        BOOTSTRAP_CACHE[key] = data
    data = BOOTSTRAP_CACHE[key]
    return [{**signal,'bootstrap_snapshot':True,'statistics_as_of':data['snapshot_as_of'],
             'actionable':False} for signal in data['signals']]


def seed_market_cache():
    """Reuse scanned chart bars, then fetch/validate only the missing tail.

    updated=0/bucket=-1 force a current exchange refresh before returning a
    live response. A frozen last price is never passed off as realtime.
    """
    for symbol in ASSETS:
        for tf in SECONDS:
            path=ROOT/'demo-data'/f'{symbol}_{tf}.json.gz'
            if not path.exists(): continue
            with gzip.open(path,'rt',encoding='utf-8') as source: data=json.load(source)
            LIVE_CACHE[symbol,tf]={'bars':data['candles'],'updated':0,'bucket':-1}


def pipeline_status(tf, now_ms, symbol="BTCUSDT"):
    if tf not in SECONDS:
        raise ValueError("Khung 1W đã được bỏ khỏi pipeline; chỉ hỗ trợ 15m, 1h, 4h và 1D.")
    if tf not in PATTERN_TIMEFRAMES:
        return {"symbol":symbol,"timeframe":tf,"status":"disabled","model_profile":"temporarily_disabled",
                "evaluated_bars":0,"expected_bars":0,"pattern_count":0,"qualified_models":0,
                "completed_observations":0,"minimum_samples":None,"error":None,
                "reason":"Pattern search 1D đang tạm dừng; biểu đồ giá 1D vẫn hoạt động."}
    _, meta = PIPELINES[symbol, tf].snapshot()
    origin = 0
    latest = ((now_ms // 1000 - origin) // SECONDS[tf]) * SECONDS[tf] + origin
    if meta["status"] == "live" and meta.get("last_available_at", 0) < latest:
        meta["status"] = "catching_up"
    if meta.get("checked_at") and now_ms - meta["checked_at"] > 20000:
        meta["status"] = "stale" if meta["status"] == "live" else meta["status"]
    meta["poll_interval_seconds"] = 3
    return meta


def run_pipeline(tf, symbol):
    """Runs without an open browser; catches up every missing closed candle."""
    while not PIPELINE_STOP.is_set():
        try:
            bars, now_ms, _ = live_bars(tf, symbol)
            PIPELINES[symbol, tf].update(bars_frame([b for b in bars if b["closed"]]), now_ms)
        except Exception as error:
            PIPELINES[symbol, tf].fail(str(error))
            print(f"Pipeline {symbol} {tf}: {safe_log(error)}", flush=True)
        PIPELINE_STOP.wait(3)


def live_market(tf, params, symbol="BTCUSDT"):
    asset = asset_metadata(symbol)
    bars, now_ms, start_ms = live_bars(tf, symbol)
    view = params.get("view", [""])[0]
    signals = live_signals(tf, bars, symbol, include_paths=view in {"v34", "v38", "v39", "v40"},
                           adaptive=view == "v38", v41=view == "v40")
    ticker = cached_upstream("/api/v3/ticker/24hr", ttl=2, symbol=symbol)
    return {
        "symbol": symbol, "asset": asset, "timeframe": tf, "mode": "live", "source": "Binance Spot",
        "source_url": BINANCE_BASE, "server_time": now_ms, "updated_at": int(ticker["closeTime"]),
        "as_of": bars[-1]["time"], "data_end": bars[-1]["time"], "history_start": bars[0]["time"],
        "requested_start": start_ms // 1000, "dataset_rows": len(bars), "has_next": False,
        "last": float(ticker["lastPrice"]), "change_24h": float(ticker["priceChangePercent"]),
        "high_24h": float(ticker["highPrice"]), "low_24h": float(ticker["lowPrice"]),
        "volume_24h": float(ticker["volume"]), "candles": bars, "signals": signals,
        "scanned_bars": pipeline_status(tf, now_ms, symbol)["evaluated_bars"],
        "pipeline": pipeline_status(tf, now_ms, symbol),
    }


def live_tick(tf, symbol="BTCUSDT"):
    bars, now_ms, _ = live_bars(tf, symbol)
    ticker = cached_upstream("/api/v3/ticker/24hr", ttl=2, symbol=symbol)
    return {"symbol": symbol, "timeframe": tf, "server_time": now_ms,
            "updated_at": int(ticker["closeTime"]), "candles": bars[-3:],
            "last": float(ticker["lastPrice"]), "change_24h": float(ticker["priceChangePercent"]),
            "high_24h": float(ticker["highPrice"]), "low_24h": float(ticker["lowPrice"]), "volume_24h": float(ticker["volume"])}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def do_GET(self):
        route = urlparse(self.path)
        if route.path.startswith("/api/"):
            params = parse_qs(route.query)
            tf = params.get("tf", ["1h"])[0]
            symbol = params.get("symbol", ["BTCUSDT"])[0].upper()
            try:
                if tf not in SECONDS:
                    raise ValueError("Chỉ hỗ trợ 15m, 1h, 4h và 1d.")
                if symbol not in ASSETS:
                    raise ValueError("Coin chưa đăng ký trong assets.json.")
                if tf not in ASSET_FRAMES[symbol]:
                    raise ValueError("Tất cả coin hiện hỗ trợ 15m, 1h, 4h và 1D; 1W đã được bỏ khỏi pipeline.")
                if route.path == "/api/assets":
                    data = {**ASSET_CATALOG, 'timeframes':['15m','1h','4h','1d'], 'pattern_timeframes':list(PATTERN_TIMEFRAMES)}
                elif route.path == "/api/horizon":
                    data = HORIZON_SERVICE.report
                elif route.path == "/api/market":
                    data = live_market(tf, params, symbol)
                elif route.path == "/api/tick":
                    data = live_tick(tf, symbol)
                elif route.path == "/api/patterns":
                    bars, now_ms, _ = live_bars(tf, symbol)
                    view = params.get("view", [""])[0]
                    data = {"symbol": symbol, "timeframe": tf, "signals": live_signals(tf, bars, symbol,
                            include_paths=view in {"v34", "v38", "v39", "v40"}, adaptive=view == "v38",
                            v41=view == "v40"), "server_time": now_ms, "source": "Binance Spot",
                            "pipeline": pipeline_status(tf, now_ms, symbol)}
                elif route.path == "/api/archive":
                    if symbol != "BTCUSDT" or tf not in ("15m","1h","4h"):
                        raise ValueError("Kho CSV cũ chỉ có BTC; NEAR dùng nguồn trực tiếp.")
                    data = market(tf, params)
                elif route.path == "/api/research":
                    report=ROOT/"research-results.json"
                    progress=ROOT/"runtime/research-progress.json"
                    data={"progress":json.loads(progress.read_text(encoding="utf-8")) if progress.exists() else {"status":"not_started"},
                          "report":json.loads(report.read_text(encoding="utf-8")) if report.exists() else None,
                          "live":{tf:pipeline_status(tf, exchange_time(), "NEARUSDT") for tf in ASSET_FRAMES["NEARUSDT"]},
                          "live_by_symbol":{s:{tf:pipeline_status(tf, exchange_time(), s) for tf in ASSET_FRAMES[s]} for s in ASSETS}}
                elif route.path == "/api/catalog":
                    data=json.loads((ROOT/"pattern-catalog.json").read_text(encoding="utf-8"))
                elif route.path == "/api/research.csv":
                    body=(ROOT/'research-results.csv').read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type','text/csv; charset=utf-8')
                    self.send_header('Content-Disposition','attachment; filename="gfi-near-sol-price-patterns.csv"')
                    self.send_header('Content-Length',str(len(body)))
                    self.end_headers();self.wfile.write(body);return
                elif route.path == "/api/btc-baseline":
                    data=json.loads((ROOT/"btc-baseline.json").read_text(encoding="utf-8"))
                elif route.path == "/api/health":
                    now_ms = exchange_time()
                    data = {"ok": True, "mode": "live", "provider": "Binance Spot", "history_months": 3,
                            "history_months_by_timeframe":{tf:3 for tf in SECONDS},
                            "pattern_months": 2, "timeframes": list(SECONDS), "symbols": list(ASSETS),
                            "timeframes_by_symbol":ASSET_FRAMES,
                            "pipelines": {s: {tf: pipeline_status(tf, now_ms, s) for tf in ASSET_FRAMES[s]} for s in ASSETS}}
                else:
                    self.send_error(404)
                    return
                self.json_response(data)
            except ValueError as error:
                self.json_response({"error": str(error)}, 400)
            except MarketUnavailable as error:
                self.json_response({"error": str(error), "source": "Binance Spot", "live": False}, 503)
            except Exception as error:
                print(f"API error: {type(error).__name__}: {error}", flush=True)
                self.json_response({"error": "Không xử lý được dữ liệu. Xem cửa sổ chạy demo."}, 500)
            return
        super().do_GET()

    def json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    address = f"http://{args.host}:{args.port}"
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    seed_market_cache()
    print(f"GFI Intelligence local demo: {address}", flush=True)
    print("Binance Spot live prices; background closed-candle pipelines scan two calendar months.", flush=True)
    for symbol in ASSETS:
        for tf in PATTERN_TIMEFRAMES:
            threading.Thread(target=run_pipeline, args=(tf, symbol), daemon=True, name=f"patterns-{symbol}-{tf}").start()
    print("Ready. Press Ctrl+C to stop.", flush=True)
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(address)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PIPELINE_STOP.set()
        httpd.server_close()
