# Lớp hiển thị V41

V41 giữ chart nến thật, EMA và hình học pattern. Từ Entry xuất phát hai mũi tên gấp khúc: xanh cho kịch bản tăng, đỏ cho kịch bản giảm. Dấu giá trên trục và các đường ngang là mức TP/SL tham chiếu của quy tắc R:R 1:1. Đường mũi tên diễn giải hình dạng kịch bản, **không thay đổi TP/SL hay kết quả backtest**. Nến dự báo mờ và nút CANDLE không xuất hiện trong V41.

Nội bộ backend vẫn cung cấp chuỗi OHLC lịch sử đại diện cho hai nhánh. V41 dùng các đường đó để dựng PATH và N theo lần xuất hiện; việc ẩn nến dự báo chỉ là quyết định giao diện. Các cấu hình cũ V34/V39 vẫn nằm trong source để đối chiếu, nhưng URL bàn giao mặc định là `v=41`.

Độ đậm của hướng có xác suất cao hơn thay đổi **liên tục** theo `configured_win_rate` của cấu hình. Đây là mức nhấn thị giác, không làm tăng accuracy. `up_probability` và `down_probability` quyết định nhãn TĂNG/GIẢM, riêng với độ khớp hình dạng. Hai hướng đều được hiển thị để tránh biến kịch bản thành lời hứa giá.

Đối với pattern đã ở quá khứ, N hiển thị có thể được cắt riêng cho từng nhánh sau khi so với giá thật và vượt ngưỡng sai lệch. Đó là phép hồi cứu. Với Entry mới chưa có giá tương lai, N được ước lượng từ nguồn lịch sử có trước Entry và lưu cho occurrence, tránh đổi theo lần tải trang; không dùng tương lai thật để chọn N. Không diễn giải N hồi cứu là độ dài dự báo đã biết từ đầu.

`view=v40` trong API là contract cho đường nguồn/N; frontend `v=41` là renderer mũi tên. Trên môi trường live, chỉ emit dữ liệu occurrence sau khi đủ hai đường nguồn; snapshot bootstrap vẫn có nhãn không actionable. Nếu chart và source có độ trễ, UI phải thể hiện trạng thái nguồn.
