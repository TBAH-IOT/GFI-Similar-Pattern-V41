# Cập nhật gói V41 — 22/11/2026

Gói V41 ghép model canonical V2 đã kiểm tra với UI mũi tên mới. `tools/preflight.py` đã mở rộng danh sách file bắt buộc V41. Các kết quả chạy mới nằm trong `VALIDATION.json`; hướng dẫn cũ bên dưới dành cho cấu trúc base V2.

# Kiểm tra toàn vẹn bản bàn giao — 05/11/2026

Chạy `python tools/preflight.py` ngay sau khi giải nén. Lệnh này dùng thư viện chuẩn Python,
kiểm tra các file bắt buộc, SHA256 từng file, import tĩnh, baseline/registry, toàn bộ 12 snapshot,
12 lịch sử nguồn, 9 thư viện forecast, dữ liệu CSV cũ và các file giao diện được HTML tham chiếu.

Cài môi trường Python theo `requirements-lock.txt`, sau đó chạy
`python tools/preflight.py --runtime` để import module thực tế, nạp registry cho NEAR/SOL,
và đọc cả 3 khung CSV BTC cũ. Lỗi sẽ ghi chính xác tên file/module thiếu.

## CSV BTC cũ

Đã kèm `Data/data_btc_price_{15m,1h,4h}.csv` cho `/api/archive`.
`engine/Data/` kèm cùng dữ liệu để các hằng đường dẫn của engine cũ cũng trỏ tới file có thật.
Luồng realtime tiếp tục dùng `runtime/history/` và exchange; thêm CSV không đổi model/baseline.

## File tự tạo khi chạy

SQLite ledger, file tạm, watchlist worker và progress research là output được chương trình tự tạo;
không cần sao chép ledger máy cá nhân. Các thư mục runtime/watchlists cần quyền ghi.
`runtime/setups` đã có đủ 6 cấu hình NEAR/SOL × 15m/1h/4h.

## Môi trường

Python 3.13 đã kiểm tra. Node chỉ cần cho kiểm thử JS; demo backend không dùng npm.
`requirements-lock.txt` khóa cả thư viện phụ đã cài trong môi trường sạch để kiểm tra gói này.
Dockerfile/compose có đầy đủ trong gói; máy kiểm tra không có Docker nên không ghi nhận đã build Docker.
Mạng ra Binance vẫn là điều kiện cho giá realtime, không phải file bị thiếu.

Đọc báo cáo kiểm tra cạnh ZIP và đối chiếu `.zip.sha256` trước khi chuyển tiếp.
