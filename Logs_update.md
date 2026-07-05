# Logs cập nhật hệ thống

Ghi lại từng đợt push lên GitHub / deploy sang máy chính (qua `deploy.bat`). Entry mới nhất ở trên cùng.

---

- 05/07/2026 Giao diện - Đăng nhập: đổi theme trang login sang tông đỏ đô + viền vàng đồng (phương án A) — thêm thanh top bar, hoạ tiết vòng tròn trang trí, footer bản quyền; fix set nền trực tiếp trên container thay vì chỉ dựa vào `body` để tránh mất màu khi NiceGUI/Quasar phủ nền riêng
- 05/07/2026 Tài liệu - README/CONTRIBUTING: cập nhật tên repo GitHub từ `KSNB` sang `TTTT` (đã đổi tên thật trên GitHub) trong hướng dẫn clone/di chuyển thư mục
- 16:02:36 05/07/2026 Phòng Swift - Đối chiếu điện SWIFT: thêm module đối chiếu điện SAA <-> Màn hình quản lý điện (2 chiều Điện đến/Điện đi), 3 nút xuất Excel mỗi chiều (Tổng hợp/Chi tiết lệch/Bản ghi đang lọc), tab Lịch sử đối chiếu lưu vào DB chung (bảng `swift_recon_history`)
- 14:25 02/07/2026 Phòng Tổng hợp - Báo cáo - Báo cáo thanh toán: fix lỗi "Worksheet named 'Result' not found" khi upload file IN/OUT — file export tháng mới đặt tên sheet dữ liệu là "Export Worksheet" thay vì "Result", nay tự nhận diện cả hai tên
- 14:25 02/07/2026 Giao diện - Sidebar: thêm nút thu gọn/mở rộng menu (nhớ trạng thái qua localStorage), sửa flyout menu con dùng `position: fixed` để không bị cắt khi sidebar cuộn
