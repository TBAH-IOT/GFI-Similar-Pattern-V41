# Bắt đầu với gói GFI-Similar-Pattern

1. Giải nén **toàn bộ** ZIP. Mở terminal trong thư mục có `README.md`, `server.py`, `SHA256SUMS.json`.
2. Chạy `python tools/preflight.py` rồi `python tools/verify_bundle.py`. Mọi file thiếu/sai hash sẽ được báo ngay.
3. Cài `python -m pip install -r requirements-lock.txt`, rồi xem bản đã quét BTC/NEAR/SOL, không cần mạng: `python demo_server.py --port 8767`; mở `http://127.0.0.1:8767/?v=41&symbol=BTCUSDT&tf=1h`.
4. Để chạy nguồn realtime, cài `requirements-lock.txt`, chạy `python tools/preflight.py --runtime` và `python tools/model_identity.py --check-registry`, rồi chạy `python server.py --port 8765`.
5. Xem `docs/INTEGRATION-VI.md` để nhúng vào web tổng. `?v=41&embed=1` là giao diện đã chốt; V41 chỉ hiện mũi tên PATH, không có nến dự báo mờ.

`demo_server.py` trả snapshot, không dùng làm backend realtime. Snapshot được đóng băng theo thời điểm trong `demo-data/manifest.json`; service live cần Internet ra Binance và thời gian đồng bộ worker. Mọi giới hạn triển khai ở `docs/ACCEPTANCE.md`.
