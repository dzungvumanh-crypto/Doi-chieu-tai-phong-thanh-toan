# Logs cập nhật hệ thống

Ghi lại từng đợt push lên GitHub / deploy sang máy chính (qua `deploy.bat`). Entry mới nhất ở trên cùng.

---

- 10/07/2026 Phòng KSNB&HTVH - Bàn giao chứng từ (màu trạng thái):
    + Tách bạch màu 3 trạng thái cho dễ nhận biết: "Đang mượn" đổi từ cam sang tím (cam nằm giữa vàng và đỏ nên dễ lẫn). Nay: Chờ xác nhận = vàng, Đang mượn = tím, Bị từ chối = đỏ, Đã xác nhận = xanh lá

- 10/07/2026 Phòng KSNB&HTVH - Báo cáo hậu kiểm:
    + Bỏ chặn tạo báo cáo khi cột "GD Hậu kiểm sai" khác 0 — trước đây báo lỗi và bỏ qua dữ liệu file, nay tạo báo cáo bình thường
    + Fix cột tổng TC (I)/TC (II) và cột tỷ lệ bị trống trên một số máy: báo cáo phòng cũ ghi công thức Excel (=SUM, =IFERROR) nhưng để ô kết quả rỗng, máy nào không tự tính lại (Excel chế độ tính tay, WPS, LibreOffice, xem nhanh) thì hiện trống. Nay tính sẵn số bằng Python, ghi thẳng giá trị vào ô

- 10/07/2026 Phòng KSNB&HTVH - Bàn giao chứng từ:
    + HKV từ chối chứng từ mới: ô chuyển trạng thái "Bị từ chối" (đỏ), giữ lịch sử + lý do thay vì xóa
    + GDV nộp lại ô bị từ chối (nút "Nộp lại" hoặc gõ số khác rồi Lưu) để đưa về "Chờ xác nhận"
    + Thêm màu đỏ + nhãn "Bị từ chối" vào chú thích lưới

- 09/07/2026 Phòng KSNB&HTVH - Báo cáo:
    + Menu "Báo cáo" tách thành menu con: "Báo cáo hậu kiểm" (màn hình cũ) và "Báo cáo bàn giao chứng từ" (mới)
    + Báo cáo bàn giao chứng từ: số chứng từ nộp đúng hạn/quá hạn theo từng phòng nghiệp vụ; chi tiết cán bộ nào nộp chậm chứng từ ngày nào, chậm bao nhiêu ngày làm việc
    + Fix KPI "Tỷ lệ nộp chứng từ đúng hạn" ở Trang chủ luôn hiển thị 100%: cũ so `handover_date` với `transaction_date` nhưng hai cột này luôn bằng nhau khi nhập qua lưới. Nay lấy ngày nộp đầu tiên từ lịch sử thao tác (`entry_change_logs`)
    + Trang chủ và Báo cáo bàn giao dùng chung một hàm tính (`handover_report_service.compute_period`) để không lệch số

- 09/07/2026 Phòng KSNB&HTVH - Bàn giao chứng từ (dọn code chết):
    + Xóa 2 trang cũ `/handovers/new` (lập phiếu bàn giao) và `/handovers/{id}` (chi tiết phiếu) — tàn dư thiết kế cũ, chưa bao giờ có menu/nút dẫn tới và chưa từng được dùng (0/148 phiếu có "người giao", 0 phiếu từng được xác nhận)
    + Xóa 7 endpoint chết kèm theo: `GET /api/handovers/`, `GET|POST|DELETE /api/handovers/{id}`, `POST /api/handovers/{id}/entries`, `DELETE /api/handovers/{id}/entries/{eid}`, `POST /api/handovers/{id}/confirm` (16 route còn 9)

- 05/07/2026 Giao diện 
    + Đăng nhập: đổi theme trang login sang tông đỏ đô + viền vàng đồng
    + Thêm thanh top bar, hoạ tiết vòng tròn trang trí, footer bản quyền; fix set nền trực tiếp trên container thay vì chỉ dựa vào `body` để tránh mất màu khi NiceGUI/Quasar phủ nền riêng
- 16:02:36 05/07/2026 Phòng Swift - Đối chiếu điện SWIFT:
    + Thêm module đối chiếu điện SAA
    + Màn hình quản lý điện (2 chiều Điện đến/Điện đi)
    + 3 nút xuất Excel mỗi chiều (Tổng hợp/Chi tiết lệch/Bản ghi đang lọc)
    + Tab Lịch sử đối chiếu lưu vào DB chung (bảng `swift_recon_history`)
- 14:25 02/07/2026 Phòng Tổng hợp - Báo cáo - Báo cáo thanh toán:
    + Fix lỗi "Worksheet named 'Result' not found" khi upload file IN/OUT — file export tháng mới đặt tên sheet dữ liệu là "Export Worksheet" thay vì "Result", nay tự nhận diện cả hai tên
- 14:25 02/07/2026 Giao diện - Sidebar:
    + Thêm nút thu gọn/mở rộng menu (nhớ trạng thái qua localStorage)
    + Sửa flyout menu con dùng `position: fixed` để không bị cắt khi sidebar cuộn
