# Nghiệm thu GFI Similar Pattern V41

## Gói bàn giao

- [ ] Giải nén toàn bộ ZIP; `python tools/preflight.py` và `python tools/verify_bundle.py` đều PASS.
- [ ] Sau khi cài dependencies, `python tools/preflight.py --runtime` và `python tools/model_identity.py --check-registry` đều PASS; NEAR/SOL không cần shim hash 1 ULP.
- [ ] Có `server.py`, `demo_server.py`, `directional_prediction.py`, `path_integrity.py`, `occurrence_identity.py`, `btc-baseline.json`, engine canonical, registry, snapshots, history, path libraries, docs, tests, Dockerfile/compose, SHA256SUMS.json, VALIDATION.json.

## Demo và giao diện

- [ ] `demo_server.py` trả 9 cặp BTC/NEAR/SOL × 15m/1h/4h; 1d chỉ hiển thị giá.
- [ ] URL `?v=41` mở mặc định V41, chart nến thật + mô hình + hai mũi tên PATH, **không** có nến dự báo mờ hay nút CANDLE/LONG/SHORT.
- [ ] Nút PATH bật/tắt được; tắt Similar Pattern ẩn cả PATH, bật lại phục hồi.
- [ ] Hướng có accuracy cao hơn nổi bật; độ đậm thay đổi theo `configured_win_rate`, không lấy similarity làm accuracy.
- [ ] Đổi coin/khung, tiến/lùi pattern không lẫn dữ liệu và không reset vùng xem.
- [ ] Layout `embed=1` có biểu đồ và hai rail, không bảng chi tiết bên dưới.

## Realtime trước khi đưa lên web công ty

- [ ] Chạy `server.py` sau proxy HTTPS/auth; test nguồn Binance, WebSocket và REST dự phòng trên môi trường đích.
- [ ] API `view=v40` trả hai representative paths cho các tín hiệu live đủ nguồn; 9 cặp coin/khung đúng symbol/timeframe.
- [ ] Sau nến đóng, worker cập nhật pattern; cache khởi động phải có `bootstrap_snapshot=true`, `actionable=false`, không tự phát alert mới.
- [ ] Nếu upstream stale/lỗi, UI nói đúng tình trạng; không coi snapshot là realtime.
- [ ] Broadening Bottom BTC 07/10 cùng 4 pivot neo chỉ có một Entry đầu; cùng cấu trúc không tạo nhiều Entry khi refresh.
- [ ] N của occurrence mới lưu cố định khi đã đủ nguồn, không dùng dữ liệu tương lai để chọn N.

## Giới hạn

Chưa triển khai hoặc kiểm thử tải trên hạ tầng công ty. Kết quả backtest có overlap, gate coverage của NEAR/SOL được chọn trên holdout nên số liệu cần trình bày là thăm dò. Đường PATH và vùng TP/SL là cách mô tả kịch bản, không phải giá bảo đảm sẽ chạm.
