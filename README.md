# GFI-Similar-Pattern — bàn giao tích hợp

Source, model, dữ liệu đã quét và giao diện tham chiếu để tích hợp Similar Pattern vào web tổng. **V41 mặc định chỉ vẽ hai mũi tên kịch bản tăng/giảm** trên biểu đồ nến thật; không hiển thị nến dự báo mờ hay nút CANDLE. Độ đậm của hướng chính tăng liên tục theo accuracy của cấu hình. Bản này ghép từ gói V2 đã chuẩn hóa hash model và source giao diện V41 local.

## Bắt đầu trong 3 bước

1. Giải nén toàn bộ ZIP, mở terminal **ngay trong thư mục chứa file này**.
2. Chạy `python tools/preflight.py` và `python tools/verify_bundle.py` để kiểm tra file và SHA256.
3. Cài `python -m pip install -r requirements-lock.txt`, rồi xem demo offline: `python demo_server.py --port 8767`, mở `http://127.0.0.1:8767/?v=41&symbol=BTCUSDT&tf=1h`.

Demo offline dùng dữ liệu đã quét, **không phải giá realtime**. Đổi `symbol` thành `NEARUSDT` hoặc `SOLUSDT`, `tf` thành `15m`, `1h`, `4h`. Khung `1d` có giá nhưng chưa bật pattern search. Nút tìm coin trên UI cũng đổi coin được.

## Chạy service realtime tham chiếu

Python 3.13 đã dùng khi kiểm tra gói. Tạo môi trường ảo rồi cài dependencies:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python tools/preflight.py --runtime
python tools/model_identity.py --check-registry
python server.py --host 127.0.0.1 --port 8765
```

Mở `http://127.0.0.1:8765/?v=41&embed=1&symbol=BTCUSDT&tf=1h`. Service cần truy cập Binance Spot public REST; trình duyệt có WebSocket và REST dự phòng. Scanner xử lý theo **nến đóng**, không tạo pattern mới ở mỗi tick. Lúc khởi động, pattern snapshot có `bootstrap_snapshot=true`, `actionable=false` cho đến khi worker và nguồn live sẵn sàng. UI phải hiển thị đúng trạng thái snapshot/stale; không coi cache là realtime.

`server.py` là service demo tham chiếu. Khi đưa vào web tổng, đặt sau gateway HTTPS/auth và chạy worker dưới giám sát process; chưa có kiểm thử tải production. `demo_server.py` chỉ để QA offline.

## Tích hợp vào web tổng

- Nhanh nhất: nhúng iframe cùng origin với `?v=41&embed=1&symbol=BTCUSDT&tf=1h`. Parent cập nhật `symbol` và `tf` khi người dùng đổi coin/khung. Xem [hướng dẫn tích hợp](docs/INTEGRATION-VI.md).
- API V41 dùng `GET /api/market?symbol=BTCUSDT&tf=1h&view=v40` và `/api/patterns` với cùng query. `view=v40` là tên contract trả đường OHLC lịch sử đại diện và N theo từng occurrence; **không có nghĩa giao diện đang dùng V40**.
- `static/integration/similar-pattern-adapter.js` là adapter cũ cho Lightweight Charts 5 và V34. Nếu ghép trực tiếp thay vì iframe, cần port lớp mũi tên ở `static/forecast-arrows.js` và kiểm tra lại hành vi V41; adapter cũ không tự cho giao diện V41.

BTC dùng baseline đã chốt; NEAR/SOL dùng registry riêng. Hash template/registry đã chuẩn hóa trong `engine/canonical_catalog.py` và `engine/canonical_price_catalog.json`; không cần compatibility shim 1 ULP. Gói có 12 snapshot (3 coin × 4 khung), 12 file history, 9 forecast path libraries, 279 cấu trúc hiển thị đã gom Entry trùng. Snapshot mỗi nhánh có 10 OHLC nguồn; V41 có thể kéo dài N theo occurrence khi nguồn đủ. `demo-data/manifest.json` ghi thời điểm snapshot; dữ liệu snapshot không cập nhật tự động.

Các chỉ số khác nhau: **similarity** đo hình dạng, **configured win rate** là TP trước SL trong kiểm định, còn **xác suất tăng/giảm** là thống kê hướng. Mũi tên là cách hiển thị hai kịch bản từ đường lịch sử, không phải cam kết giá sẽ đi theo nét vẽ. Xem [logic model](docs/MODEL-LOGIC-VI.md), [hiển thị V41](docs/V41-DISPLAY-VI.md), [mở rộng coin](docs/SCALING-VI.md) và [nghiệm thu](docs/ACCEPTANCE.md).

## Đưa lên GitHub

Giải nén rồi commit **nội dung thư mục** này bằng Git CLI/GitHub Desktop. ZIP bàn giao lớn hơn 100 MB nên dùng nó làm tệp chuyển giao, không commit nguyên ZIP vào repository. File lớn nhất trong nội dung gói dưới 100 MB; một số file lớn hơn mức upload qua trình duyệt GitHub (25 MiB/file). `.gitignore` chỉ loại output phát sinh, môi trường ảo và bí mật; dữ liệu `demo-data/`, `runtime/history/`, `runtime/*-forecast-paths.json.gz` là phần bàn giao bắt buộc. Không tự bỏ chúng khi upload.

`.gitattributes` giữ nguyên byte của mọi file qua Git checkout để `SHA256SUMS.json` còn khớp trên máy khác, kể cả Windows tự động đổi LF/CRLF.

Nếu tạo **repository mới**, mở terminal trong thư mục vừa giải nén (nơi có `README.md`) rồi chạy `git init -b main` **trước** `git add .`. Trên một số máy, thư mục cha đã là Git repo; kiểm tra `git rev-parse --show-toplevel` phải trỏ đúng thư mục gói. Nếu đưa vào **repository công ty đang có**, chép nội dung gói vào vị trí Dustin chọn và chạy `git status` tại đúng repository đó trước khi commit. Không chạy `git add .` từ thư mục cha chứa các file cá nhân.

`VALIDATION.json` ghi kiểm tra đã chạy trên gói này. `SHA256SUMS.json` bảo vệ từng file. `Dockerfile` và `compose.yaml` được cung cấp làm cấu hình tham khảo; cần kiểm tra riêng trong hạ tầng công ty.
