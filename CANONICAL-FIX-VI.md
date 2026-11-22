# r59.1 — model/registry ổn định trước sai lệch ULP

Đây là bản sửa của gói r59 bàn giao Dustin. Phần thử nghiệm N nến V38/V39 đã dừng và không nằm trong bản sửa này.

## Nguyên nhân

`chart_library.py` cũ tạo catalogue thông qua `PatternMatcher()`.
`Rounding_Top` và `Rounding_Bottom` lấy `np.sin(np.pi/4)` trong lúc khởi tạo.
Lệch 1 ULP ở kết quả hàm sin làm thay đổi float trong catalogue, nên JSON hash của catalogue
và danh sách strategy thay đổi dù source Python giống nhau. Registry từ môi trường gốc bị từ chối.

## Sửa tại nguồn

- `engine/canonical_price_catalog.json` là source chuẩn của cả 78 định nghĩa, template_times,
  và các ma trận mẫu curve 32 điểm (grid/templates/centered/norms).
- Mọi float được ghi bằng hexadecimal binary64 và nạp bằng `float.fromhex`.
  Không làm tròn, không thay bằng epsilon, không tính lại sin/interpolation/normalization của template khi import.
- `engine/chart_library.py` và `curve_search.py` cùng đọc nguồn chuẩn này.
- `MODEL_HASH` bao gồm cả loader và file dữ liệu chuẩn. Sửa template thật, kể cả 1 ULP,
  làm hash đổi và registry vẫn bị từ chối. Không có nhánh bỏ qua validation.
- Đã chứng minh catalogue, strategy và toàn bộ ma trận giữ đúng từng bit của r59 gốc.

Tài liệu Python về biểu diễn float và `hex`/`fromhex`:
https://docs.python.org/3.13/tutorial/floatingpoint.html

## Registry và cache

`CANONICAL-MIGRATION.json` ghi rõ model hash cũ/mới và fingerprint tham chiếu.
Catalogue hash và strategy hash không đổi. Model hash đổi vì thay implementation/nạp dữ liệu.
Registry NEAR/SOL, research report, manifest snapshot và 9 thư viện forecast đã đồng bộ model hash mới.
Mỗi artefact đã được so sánh toàn bộ nội dung sau khi loại riêng trường `model_hash`:
không đổi winrate, n, kết quả trade, calibration, cấu hình, OHLC hay đường forecast.
`research_runner.py`, `btc-baseline.json` và `engine/similar_engine.py` của BTC giữ nguyên.
Không chạy lại hoặc fit lại bộ nghiên cứu để làm đẹp kết quả.

## Dustin áp dụng

1. Giải nén gói FULL r59.1 vào thư mục mới; dùng nguyên source cùng registry/cache trong gói.
2. Gỡ compatibility shim cũ trước khi nối vào ứng dụng công ty. Không chồng shim điều chỉnh float lên model chuẩn.
3. Cài `python -m pip install -r requirements-lock.txt`.
4. Chạy `python tools/verify_bundle.py`.
5. Chạy `python tools/model_identity.py --check-registry` — phải nạp thành công cả 6 market NEAR/SOL × 15m/1h/4h.
6. Chạy `python tests/test_canonical_model.py` và `python tests/test_handoff.py`.
7. Restart service `server.py`; tích hợp theo `docs/INTEGRATION-VI.md` như trước.

Nếu giữ registry riêng của công ty, cần đối chiếu source/identity và dữ liệu kiểm định của registry đó;
không tự sửa hash của một registry có cấu hình khác chỉ để vượt guard.
File checksum của ZIP kiểm tra byte vận chuyển; không áp dụng formatter/line-ending rewrite lên một bundle đã seal
rồi bỏ qua checksum. Model fingerprint vẫn cố ý phát hiện source bị chỉnh sửa.

## Kiểm tra

- NumPy 2.2.6 và 2.3.3 trên Python 3.13.
- Tái hiện lỗi ở code cũ bằng cách dịch kết quả sin ±1 ULP.
- Code mới giữ nguyên mọi identity/ma trận trong cả hai môi trường, kể cả khi cấm gọi sin.
- Sửa 1 ULP trực tiếp trong source template chuẩn: bị từ chối.
- Giả model_hash/catalog_hash/strategy_hash/evaluation_hash: đều bị từ chối.
- Báo cáo chi tiết: `CANONICAL-ENVIRONMENTS.json`, `CANONICAL-MIGRATION.json` và báo cáo validation cạnh ZIP.

Máy kiểm tra không có Docker/Linux runtime: không ghi nhận đã chạy container Linux thực tế.
Việc thử hai NumPy cùng tiêm lỗi ULP không đồng nghĩa đã benchmark bitwise inference trên mọi CPU/BLAS.
Giữ dependencies đã khóa cho demo; khi nâng dependencies cần nghiệm thu như mọi thay đổi môi trường.
