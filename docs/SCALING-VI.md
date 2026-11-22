# Mở rộng coin và vận hành model

## Thêm coin

```sh
python tools/add_coin.py AVAXUSDT --name Avalanche --glyph A --peer SOLUSDT
python research_runner.py
```

Lệnh đầu chỉ đăng ký asset + thêm coin vào research-settings.json, không kích hoạt thống kê BTC cho coin mới. Existing asset không bị ghi đè.
Lệnh research tải/bù lịch sử từ ngày đầu Binance có dữ liệu, kiểm định các coin trong settings, ghi setups trước test rồi xuất registry/JSON/CSV. Đang là batch job riêng, có thể lâu; không chạy nó trong request người xem.
Sau khi registry hoàn tất, kiểm tra model_hash/catalog_hash/strategy_hash/evaluation_hash, mốc test, mẫu số và ngưỡng rồi restart service. Coin chưa có registry hợp lệ hiện awaiting_validation; không tự nhận đạt chuẩn.
BTC bị loại khỏi research 15m/1h/4h để giữ baseline. Các market mới dùng ExpandingPipeline cùng logic NEAR/SOL.
assets.json là nguồn chung của server và ô search qua /api/assets. Không cần sửa whitelist JS cho mỗi coin USDT.

## Policy đang chốt

| Khung | N mặc định | Sàn cho phép |
|---|---:|---:|
|15m|100|50|
|1h|75|30|
|4h|50|20|
|1D|30 trong config lưu trữ|Pattern đang tắt|

Giữ similarity ≥0.85 theo bộ lọc scanner, admission accuracy >0.55; đúng0.55 chỉ giữ cấu hình đã active. Không hạ sàn bên ngoài ladder để ép đủ cấu hình.
20% setup đo volatility/noise; 80% test theo thời gian. Mốc split lưu cố định trong setup/registry, không trượt theo ngày mới.
Các cấu hình/method/direct/inverse có thể phụ thuộc nhau; số mẫu không đồng nghĩa mẫu độc lập. Cờ statistical_evidence_5pct giữ false trong registry hiện tại.

## Dữ liệu và tính nhân quả

history/*.csv.gz: time/open/high/low/close/volume; time epoch giây UTC, chỉ nến đã đóng.
Kiểm tra finite, giá dương, high/low bao thân nến, volume không âm, không thiếu nến. Gap phải tải bù trước khi scanner tiến tiếp.
Không dùng nến tương lai để xác nhận pivot, chọn cấu hình hoặc cân biên độ nến tại Entry.
Forecast analogue chỉ dùng case đã có đủ horizon và đã giải quyết trước Entry mục tiêu. Peer giữ cùng timeframe/hình dạng, không dùng giá tuyệt đối của peer.
Horizon đánh giá giao dịch là48; horizon UI candle là10. Hai thông số có mục đích khác nhau.

## Scale hệ thống

Một worker cho mỗi market/khung trong reference server, khởi động theo assets.json. Giá/nến realtime độc lập với backfill thống kê.
Khi tăng nhiều coin, chuyển scheduler sang worker/process queue của công ty, hạn chế concurrency theo CPU/RAM và rate limit của upstream. Không tạo thread vô hạn theo request/user.
Giữ raw OHLC, observations, phiên bản model, registry và last processed closed candle. SQLite ledger hiện lưu observations; scanner/counters vẫn replay khi cold start, chưa có checkpoint scanner hoàn chỉnh.
UI bootstrap đã giải quyết việc chart/pattern trống lúc chờ; nó không bỏ chi phí replay OOS. Đo ready time trên máy triển khai bằng /api/health trước demo.
Thư viện analogue loại cửa sổ thiếu timestamp trong bối cảnh hình dạng tối đa120nến và đoạn kết quả/đoạn10nến; đây là kiểm tra tính toàn vẹn dữ liệu nguồn, không thay warmup của live detector.
Cache forecast mang model_hash + source_sha256; nếu model/nguồn đổi phải rebuild, không sửa hash để ép cache dùng lại.
Các thư viện forecast bàn giao đã quét; SHA256 làm cache portable sau khi giải nén khác mtime.

## Peer coin

Danh sách peer phải được chọn có cơ sở và khai báo trong assets.json. Hiện NEAR↔SOL, BTC không dùng peer.
Peer chỉ giúp lớp đường nến tham khảo khi thiếu mẫu; accuracy/gate của coin mới vẫn kiểm định trên chính coin đó.
Không tự lấy winrate BTC hoặc peer để điền cho coin mới.
