"""Check the V41 API path without depending on the public exchange."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


bars = [{"time": 100, "open": 1, "high": 2, "low": 1, "close": 2,
         "volume": 1, "closed": True}]
calls = []


def fake_signals(tf, data, symbol, include_paths=False, adaptive=False, v41=False):
    calls.append((tf, symbol, include_paths, adaptive, v41))
    return []


with patch.object(server, "live_bars", return_value=(bars, 200000, 100000)), \
     patch.object(server, "asset_metadata", return_value={"symbol": "BTCUSDT"}), \
     patch.object(server, "cached_upstream", return_value={"closeTime": 200000,
         "lastPrice": "2", "priceChangePercent": "0", "highPrice": "2",
         "lowPrice": "1", "volume": "1"}), \
     patch.object(server, "pipeline_status", return_value={"evaluated_bars": 1}), \
     patch.object(server, "live_signals", side_effect=fake_signals):
    data = server.live_market("1h", {"view": ["v40"]}, "BTCUSDT")
    assert data["symbol"] == "BTCUSDT" and data["mode"] == "live"
    assert calls[-1] == ("1h", "BTCUSDT", True, False, True)
    server.live_market("1h", {"view": ["v33"]}, "BTCUSDT")
    assert calls[-1] == ("1h", "BTCUSDT", False, False, False)

signal = {"prediction": {"up_representative": {"candles": [{}]},
                         "down_representative": {"candles": [{}]}}}
with patch.object(server, "_base_live_signals", return_value=[signal]), \
     patch.object(server.V41_OCCURRENCE_HORIZON, "observe") as observe, \
     patch.object(server.V41_OCCURRENCE_HORIZON, "extend", return_value={"extended": True}) as extend:
    assert server.live_signals("1h", bars, "BTCUSDT", include_paths=True, v41=True) == [{"extended": True}]
    observe.assert_called_once()
    extend.assert_called_once()

print("PASS: V41 live API requests both source paths and extends one ready occurrence")
