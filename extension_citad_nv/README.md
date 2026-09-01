# Extension CITAD - PaymentHub N&V (Phòng QLTK Nostro, Vostro)

Extension Chrome **RIÊNG** cho module Đối chiếu CITAD - PaymentHub của Phòng
Quản lý tài khoản Nostro, Vostro — không dùng chung với `extension_citad/`
(Phòng Thanh toán). Tự động đọc số liệu từ 2 trang:

- CITAD **"Tra cứu dữ liệu"** (`10.0.85.100/CITAD*/Modules/TraCuuDuLieu/...`)
  — chỉ tự lưu khi trang đang lọc **Chiều giao dịch = Đi** và **Tình trạng =
  Giao dịch thành công**, đọc dòng "Tổng số giao dịch"/"Tổng số tiền" theo
  đúng cổng (URL) và loại dịch vụ (GTT/GTC) đang chọn.
- PaymentHub **"Lập bảng kê phí chia sẻ CITAD"**
  (`paymenthub.agribank.com.vn/final-settlement-citad/charges`) — đọc dòng
  "Tổng cộng", tách 3 khối GTT / GTC Trước 15h30 / GTC Từ 15h30.

## Cài đặt

1. Vào trang `/doi_chieu_citad_nostro` trên web TTTT (đăng nhập, có quyền
   "Đối chiếu CITAD - PaymentHub" của Phòng QLTK Nostro, Vostro), tab "Kết
   nối Extension" → bấm "Tải Extension (.zip)" → giải nén.
2. `chrome://extensions` → bật **Developer mode** → **Load unpacked** → chọn
   thư mục vừa giải nén.
3. Vẫn ở tab "Kết nối Extension" trên web, bấm "Tạo mã kết nối mới" → sao
   chép mã hiện ra (chỉ hiện đúng 1 lần).
4. Mở trang Tuỳ chọn (options) của Extension vừa cài (chuột phải icon
   Extension → Tuỳ chọn / Options) → dán **địa chỉ backend TTTT** + **mã kết
   nối** vừa sao chép → Lưu cấu hình.
5. Mở 1 trong 5 địa chỉ CITAD "Tra cứu dữ liệu" hoặc trang PaymentHub
   "Lập bảng kê phí chia sẻ CITAD", lọc đúng bộ lọc nghiệp vụ — Extension tự
   phát hiện và gửi số liệu, có toast xác nhận góc dưới phải màn hình.
6. Quay lại `/doi_chieu_citad_nostro`, tab "Đối chiếu", bấm "Nạp CITAD" /
   "Nạp PaymentHub" để nạp số liệu đã gửi vào bảng.

## Vì sao tách Extension riêng, không dùng chung `extension_citad/`

Theo yêu cầu nghiệp vụ: Phòng QLTK Nostro, Vostro có quy trình đối chiếu
độc lập, không liên quan phần của Phòng Thanh toán — tách hẳn gói Extension
(khác `content_scripts`, khác trang Tuỳ chọn, khác tên hiển thị trong
`chrome://extensions`) để 2 phòng không nhầm lẫn khi cài đặt/gỡ cài đặt,
dù backend dùng chung 1 cơ chế "mã kết nối" theo người dùng (không theo
Extension) nên 1 mã vẫn dán được vào cả 2 gói nếu 1 người cần dùng cả 2.
