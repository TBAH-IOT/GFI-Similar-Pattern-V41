# Ghi chú hiển thị V41

Logic nhận diện, Entry, TP/SL và dữ liệu OHLC nguồn bên dưới vẫn giữ. V41 chỉ hiển thị mũi tên PATH trên nến thật, ẩn nến dự báo; xem `docs/V41-DISPLAY-VI.md`. Phần mô tả nến rỗng ở cuối tài liệu là hành vi renderer V34 cũ.

# Logic của bản bàn giao r59

## Phạm vi và provenance

Chỉ mô hình giá; thư viện có 78 định nghĩa hữu hạn, không tuyên bố bao phủ mọi diễn giải trong sách. Không dùng nến Nhật/harmonic.
BTC 15m/1h/4h: giữ engine baseline, threshold, direction override, win rate đã chốt trong btc-baseline.json; không tái fit.
NEAR/SOL: Scanner + calibration/registry riêng. Khung pattern hoạt động: 15m, 1h, 4h. 1D xem giá, 1W tắt.

## Setup và test

Lấy OHLC Binance từ ngày đầu symbol có dữ liệu. 20% đầu chỉ đo biến động/nhiễu để điều chỉnh tham số phụ thuộc coin; khóa trước test.
80% sau kiểm định theo thời gian. Similarity cố định 0.85, không tối ưu accuracy để chọn detector/threshold.
Gate mặc định N=100/75/50 theo 15m/1h/4h; ladder sàn=50/30/20, chỉ chọn bậc đã khai báo theo coverage từng thị trường. Bậc chọn từ holdout mang tính thăm dò, không phải bằng chứng độc lập.
Admission WR>55% và đủ N; cấu hình đã active được giữ ở đúng 55%, bị tắt khi xuống dưới 55% hoặc thiếu N hiệu lực.
Không ép phải có đủ hai pattern nếu accuracy/evidence không đáp ứng. Trạng thái reference >90% được phân biệt rõ.

## Entry và TP/SL

NEAR/SOL: Entry tại Open nến tiếp theo sau xác nhận. BTC frozen hiện giữ Entry=Close nến phát hiện như baseline gốc; đây là ngoại lệ cần giữ khi tích hợp, không âm thầm thay bằng Open.
H của template pivot = max(pivot.value) − min(pivot.value); curve/gap có H theo detector chuyên biệt.
LONG: TP=Entry+H, SL=Entry−H. SHORT: TP=Entry−H, SL=Entry+H. R:R đối xứng 1:1.
Đây là quy tắc kiểm định hiện hành, chưa phải mục tiêu riêng theo từng mô hình SGK.
Theo dõi tối đa 48 nến. Cùng một nến chạm hai mức: AMBIGUOUS, không coi thắng. EXPIRED: không thắng; pending chưa đưa vào N.

## Accuracy và phần trăm tăng/giảm

Accuracy gate = số TP hợp lệ / N kết thúc, gồm SL/AMBIGUOUS/EXPIRED trong mẫu số.
Phần trăm hai nhánh NEAR/SOL là conditional split trên các TP/SL không mơ hồ đã kết thúc:
P(thắng hướng setup)=wins/(wins+opposite_wins); LONG gán tỷ lệ này cho nhánh trên, SHORT gán cho nhánh dưới.
`directional_prediction.py` sử dụng bộ đếm TP/SL trực tiếp; không phân loại theo dấu lãi ròng sau phí. TP nhỏ vẫn là TP dù phí làm net âm.
BTC giữ phần trăm baseline. Vì vậy không gọi % nhánh và configured_win_rate là cùng một population.
Các field median-return cũ giữ để tương thích, V34 không dùng chúng đặt đích giá; đích line lấy TP/SL thật của setup.

## Một cấu trúc chỉ có một Entry

Đầu tiên, cùng method + thời điểm + đầy đủ chuỗi pivot: chọn đạt chuẩn → accuracy → similarity.
Sau đó canonicalize theo symbol + tf + method + base pattern + chuỗi neo.
Với template 5 pivot của EMA Peaks / Pivot Window / ZigZag (kể cả calibrated), 4 pivot đầu là neo cố định; pivot thứ 5 có thể kéo dài. Đổi direction hoặc kéo dài tail cùng neo được xem là revision.
Giữ nguyên toàn bộ lần xác nhận sớm nhất: Entry, thời gian, hướng, points, TP/SL. Rank chỉ dùng cho các ứng viên đồng thời; không dùng thông tin sau để sửa Entry đầu.
Các cấu trúc khác neo/method/coin/khung vẫn độc lập; không gom chỉ vì chồng lấn trên màn hình. Các detector khác gom theo đầy đủ points chính xác.
occurrence_aliases/last_seen_at là metadata, không là Entry mới. Browser và Python dùng quy tắc tương ứng, có test cùng fixture thực.
Regression thực: Broadening Bottom BTC1h ngày 07/10/2026 tại 07:00, 13:00, 18:00 → một Entry 07:00 UTC, 84.229,67.
Module này chỉ gom kết quả hiển thị; raw research observations và thống kê kiểm định vẫn được giữ để bảo toàn baseline.

## 10 nến mỗi nhánh và pullback

1. Lấy các mẫu lịch sử cùng pattern/direction cấu hình; ưu tiên đúng detector, cho phép detector khác cùng hình dạng. Chỉ dùng mẫu trước Entry hiện tại, đã kết thúc và đã có đủ 10 nến.
Thư viện nguồn loại case đi qua giờ thiếu nến; không nối nến hai đầu gap thành một đường dự báo liên tục.
2. Nhánh trên: LONG→TP hoặc SHORT→SL. Nhánh dưới: SHORT→TP hoặc LONG→SL.
3. Chia OHLC mỗi mẫu cho Entry lịch sử (Entry=1). Tính trung bình cộng OHLC theo vị trí nến 1..10 trong nhóm.
4. Để nến giữ thân/râu thật, không trực tiếp vẽ mean OHLC. Chọn **một chuỗi thật** gần trung bình nhất.
5. Score chọn chuỗi = mean squared OHLC distance + 4×(adverse−mean adverse)^2 + 0.1×v^2×(phase−mean phase)^2, v là mean high−low chuẩn hóa của nhóm.
6. Adverse nhánh trên=max(0,1−min Low); nhánh dưới=max(0,max High−1), đo trong toàn bộ 10 nến. Phase=index cực trị/9; khi không có adverse thì phase=0.
7. Ưu tiên pool cùng coin nếu nhánh đó có mẫu; peer chỉ là fallback. Metadata source_symbol/source_time/sample_count ghi nguồn đã chọn.
8. Cân biên độ bằng một hệ số cho cả chuỗi: k=median(TR của tối đa 32 nến trước Entry)/(Entry hiện tại×median(TR chuỗi chuẩn hóa)). Cần ít nhất 14 TR, thiếu thì k=1.
9. Giá vẽ=Entry hiện tại×[1+k×(giá chuẩn hóa−1)]. Không chặn riêng mỗi body/wick, không chèn pullback, không mirror nhánh thiếu, không kéo nến cuối về TP/SL.

TR=max(High−Low,abs(High−Close trước),abs(Low−Close trước)). Hệ số k áp riêng từng nhánh; có thể co hoặc giãn theo biến động.
Nguồn 10 nến bao gồm nến Entry lịch sử; convention UI đã chốt đặt 10 ô bắt đầu sau chấm Entry hiện tại một ô. Không diễn giải đây là dự đoán chính xác timestamp của từng nến tương lai.
Pullback hiển thị là pullback của chuỗi đại diện sau scale, chỉ gần trung bình nhóm, không bắt buộc đúng bằng mean pullback. Nó đo cả cửa sổ 10 nến, không chỉ trước lần chạm TP đầu.

## Quy tắc vẽ

Nét đứt xanh/đỏ vẫn nối Entry tới hai mức TP/SL 1:1; độ cong là thiết kế UI, không phải ước lượng đường giá xác suất.
Candle dùng renderer native cùng chart/price scale/bar spacing với nến thật, fill transparent; màu là màu kịch bản, không đổi xanh/đỏ theo từng body.
Phần hai nhánh giao nhau viền trắng. Nến thật trong vùng preview xám dịu; tắt CANDLE hoặc cả LONG/SHORT thì phục hồi màu thật.
LINE/CANDLE độc lập; LONG/SHORT chỉ tác động nến. CANDLE là công tắc tổng; Similar Pattern off ẩn cả nhóm controls.
Line có thể tới TP/SL trong khi 10 nến đại diện chưa chạm đích; hai lớp giữ logic đã chốt, không gán % line cho độ chính xác của chuỗi nến.
