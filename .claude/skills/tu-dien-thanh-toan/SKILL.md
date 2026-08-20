---
name: tu-dien-thanh-toan
description: Cập nhật docs/TU-DIEN-LENH-THANH-TOAN.md khi người dùng cung cấp/mô tả tài liệu kỹ thuật, quy trình nghiệp vụ, hoặc spec chính thức về các hệ thống thanh toán TTTT vận hành (ACH, ILO1000, 459901, Đối chiếu Song phương, IPCAS/Core, Citad, Hub, GW, OSB, hoặc hệ thống mới) — dù dạng paste văn bản, đính kèm file, hay mô tả bằng lời. KHÔNG dùng cho câu hỏi chung chung không kèm tài liệu chính thức (VD giải thích code) — đó là trả lời trực tiếp.
---

Người dùng không có tài liệu quy chuẩn chính thức cho các hệ thống thanh toán họ vận hành —
`docs/TU-DIEN-LENH-THANH-TOAN.md` được xây bằng suy luận ngược từ code + kiểm chứng dữ liệu thật.
Khi họ tìm được tài liệu kỹ thuật/quy trình chính thức, việc gộp vào từ điển đã được **uỷ quyền
sẵn** — chủ động làm ngay, không cần hỏi xin phép cho hành động này.

## Trước khi sửa

Đọc `docs/TU-DIEN-LENH-THANH-TOAN.md` trước — đặc biệt mục "Cách đọc bảng" (schema 4 cột: Mã | Ý
nghĩa suy luận | Nguồn | Độ tin cậy; 4 mức độ tin cậy) và mục "Ưu tiên cao"/"Ưu tiên trung bình"
trong Phần khoảng trống cuối file + mục Đối chiếu Song phương (dữ liệu kênh còn thiếu) — đó là nơi
cần lấp trước nếu tài liệu mới liên quan.

## Quy trình cập nhật

1. Trích mã/lệnh/trạng thái/quy trình liên quan từ tài liệu vừa nhận.
2. Đối chiếu với bảng hiện có trong từ điển:
   - **Khớp** → nâng độ tin cậy lên "cao — xác nhận tài liệu chính thức (tên tài liệu, ngày)".
   - **Mâu thuẫn** với code/dữ liệu đã ghi trước → ghi CẢ HAI, gắn cờ "⚠️ mâu thuẫn với code/dữ
     liệu", KHÔNG âm thầm ghi đè. Mâu thuẫn tự nó là một phát hiện (có thể là bug, có thể tài liệu
     lỗi thời) — báo lại người dùng, không tự quyết bên nào đúng.
   - **Mã hoàn toàn mới** → thêm dòng mới đúng schema 4 cột, độ tin cậy theo đúng thang đã định
     nghĩa trong file (đừng bịa mức mới).
   - **Hệ thống/kênh hoàn toàn mới** (chưa có Phần nào trong từ điển) → thêm 1 Phần mới theo đúng
     cấu trúc đã dùng cho 4 module hiện có; cập nhật sơ đồ mermaid ở đầu file nếu tài liệu làm rõ
     thêm quan hệ giữa các hệ thống.
3. Ghi vào bảng "Nhật ký cập nhật từ tài liệu chính thức" ở cuối file: ngày, tên tài liệu, phạm vi
   đã đổi (đủ để lần sau biết tài liệu nào đã xử lý, tránh hỏi lại hoặc làm trùng).
4. Báo lại ngắn gọn cho người dùng: đã đổi những gì, có mâu thuẫn nào phát hiện cần họ quyết định
   không.

## Không được làm

- Không suy diễn thêm ngoài nội dung tài liệu — tài liệu không nói gì thì vẫn để "chưa rõ"/"không
  biết", không đoán theo hướng "nghe hợp lý".
- Không sửa code chỉ vì tài liệu nói khác — mâu thuẫn code/tài liệu là phát hiện cần báo, không
  phải lỗi tự sửa.
- Không tự ý xoá các mục "chưa rõ"/"không biết" cũ trừ khi tài liệu mới thật sự làm rõ được.
- Không công bố/chia sẻ nội dung tài liệu ra ngoài repo — đây là dữ liệu nghiệp vụ ngân hàng nội bộ.
