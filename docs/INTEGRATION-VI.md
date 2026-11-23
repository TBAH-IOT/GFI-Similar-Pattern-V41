# Tích hợp V41 vào web tổng

## Kiến trúc demo

```text
Web tổng HTTPS + auth
  └─ /similar-pattern/ → reverse proxy → server.py
       ├─ UI V41 + API market/patterns
       ├─ nguồn Binance Spot REST/WebSocket
       ├─ worker scan sau nến đóng + registry BTC/NEAR/SOL
       └─ volume runtime ghi cache/ledger
```

`server.py` là service realtime tham chiếu; `demo_server.py` là snapshot QA offline. Khởi động một worker theo process, không chạy detector riêng cho từng viewer. Khi upstream gián đoạn, UI phải nêu trạng thái stale. Snapshot bootstrap không actionable và không được báo là phát hiện mới.

## Cách nhanh nhất: nhúng V41

Khi chạy cùng Signal (cổng 8765), chạy `python server.py --port 8767` hoặc đặt `GFI_PATTERN_PORT=8767` cho Docker Compose. Mẫu proxy bên dưới dùng cổng 8767.

Đặt `integration/nginx-location.conf` dưới HTTPS/auth của web tổng, trỏ về service Python. Đặt service sau proxy cùng origin để asset/API hoạt động.

```html
<iframe
  title="GFI-Similar-Pattern"
  src="/similar-pattern/?v=41&embed=1&symbol=BTCUSDT&tf=1h"
  style="width:100%;height:900px;border:0"
></iframe>
```

`embed=1` giữ biểu đồ và hai thanh bên, bỏ header nội bộ. Parent đổi query `symbol` / `tf` khi người dùng đổi coin. Coin hỗ trợ: BTCUSDT, NEARUSDT, SOLUSDT. Pattern hoạt động ở 15m/1h/4h; 1d chỉ giá. Chart nến là Binance Spot, UTC. Không ghép nguồn futures hoặc sàn khác vào dự báo spot mà không kiểm định lại.

## Contract API cho V41

| Route | Nội dung |
|---|---|
| `GET /api/assets` | coin và khung hỗ trợ |
| `GET /api/market?symbol=BTCUSDT&tf=1h&view=v40` | giá/nến, tín hiệu, pipeline, đường lịch sử đại diện |
| `GET /api/patterns?symbol=BTCUSDT&tf=1h&view=v40` | cập nhật tín hiệu và trạng thái scanner |
| `GET /api/tick?symbol=BTCUSDT&tf=1h` | giá/nến mới cho REST dự phòng |
| `GET /api/health` | trạng thái worker |
| `GET /api/research` | nghiên cứu/registry cho QA |

**Lưu ý:** URL giao diện dùng `v=41`, nhưng API dùng `view=v40` vì V41 vẫn đọc hai đường OHLC đại diện và N theo occurrence từ contract đó. Thử API bằng browser/curl trước khi ghép. HTTP 400 là input không hỗ trợ, 503 là nguồn chưa sẵn, 500 là lỗi xử lý. Frontend cần giữ response cuối và báo retry/stale đúng trạng thái.

Timestamp `candles[].time`, pivot `time`, `available_at`, `detected_at`, `closed_at` là giây UTC. `server_time`, `updated_at`, `statistics_as_of`, `snapshot_as_of` là mili giây. Similarity là 0–100; `configured_win_rate`, `up_probability`, `down_probability` là 0–1. `entry`, `tp`, `sl` là giá tuyệt đối; representative candles chuẩn hóa Entry nguồn = 1. Ví dụ JSON trong `demo-data/BTCUSDT_1h.json.gz`, type tại `integration/api-contract.ts`.

`bootstrap_snapshot=true` đồng nghĩa `actionable=false`, không phát alert mới. `reference_only=true` là hình dạng >90% nhưng chưa qua gate win rate/số mẫu. `occurrence_aliases` gom các raw ID cùng cấu trúc vào Entry đầu; dùng để giữ selection khi refresh. Không lấy similarity làm xác suất thắng.

## Ghép trực tiếp vào chart khác

`static/integration/similar-pattern-adapter.js` là adapter **legacy V34** cho Lightweight Charts 5, không phải API TradingView Advanced Charting Library. Nó chưa port renderer mũi tên V41. Nếu web tổng cần dùng chart có sẵn thay vì iframe, Dustin cần chuyển lớp V41 trong `static/forecast-arrows.js` và phần điều phối trong `static/app.js`, giữ invariant: cùng UTC/symbol/timeframe/Entry, không reset zoom khi tiến lùi, chỉ hiển thị PATH, màu nến thật không đổi. Kiểm tra trực quan cả BTC/NEAR/SOL × 15m/1h/4h.

## Vận hành và giới hạn

Worker quét theo nến đóng và có bước bắt kịp khi khởi động. Cùng coin/khung dùng cache theo phiên bản model và nến đóng. `runtime/history/`, `runtime/*-forecast-paths.json.gz`, `runtime/research-registry.json`, `runtime/setups/` phải có và cần volume bền vững cho output mới. `server.py` dựa ThreadingHTTPServer, phù hợp demo sau proxy; khi triển khai lớn tách worker/gateway theo chuẩn hạ tầng công ty. `Dockerfile` và `compose.yaml` chỉ là mẫu, phải build/test riêng trên môi trường đích.
