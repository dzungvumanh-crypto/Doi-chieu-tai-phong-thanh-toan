# Extension Chrome — Đối chiếu CITAD

Content script tự động đọc số liệu từ trang CITAD (NHNN, `10.0.85.100`) và
PaymentHub/Payment (Agribank) rồi gửi lên module **Đối chiếu CITAD** của app
TTTT (`/doi_chieu_citad`), thay cho việc gõ tay từng số.

Đây là add-on trình duyệt độc lập — không chạy trong tiến trình backend/
frontend của app, nên phải cài **thủ công** vào từng máy cần dùng (không có
cách nào tự động cài qua repo).

## Cài đặt (mỗi máy làm 1 lần)

1. Mở `chrome://extensions` (hoặc `edge://extensions`)
2. Bật **Developer mode** (góc trên phải)
3. Bấm **Load unpacked**, chọn đúng thư mục `extension_citad/` này

## Xác thực — mã kết nối cá nhân (bắt buộc, không dùng chung)

Bản đầu dùng 1 khoá cố định cho toàn Phòng Thanh toán — đã bỏ sau review bảo
mật vì ai cũng ghi được buffer dưới bất kỳ tên nào. Giờ **mỗi người tự tạo 1
mã riêng**, không chia sẻ mã của mình cho người khác dùng chung.

**Bước 1 — Tạo mã kết nối:**
1. Đăng nhập web TTTT thật (không phải Extension), vào `/doi_chieu_citad`
2. Ở mục **"Kết nối Extension"**, bấm **"Tạo mã kết nối mới"**
3. Sao chép mã hiện ra — **chỉ hiện ĐÚNG 1 LẦN**, không xem lại được (tạo mã
   mới sẽ tự động huỷ mã cũ)

**Bước 2 — Dán vào Extension:**
Mở `content.js` **và** `content_paymenthub.js`, sửa 2 hằng số ở đầu file:

| Hằng số | Ý nghĩa | Giá trị |
|---|---|---|
| `SERVER` | Địa chỉ backend TTTT thật (không phải `localhost`) | `https://<domain-backend>:8000` — **bắt buộc HTTPS** nếu không chỉ chạy trên localhost, xem cảnh báo bên dưới |
| `EXTENSION_TOKEN` | Mã kết nối cá nhân vừa tạo ở Bước 1 | Dán nguyên văn, không sửa |

Sau khi sửa, vào `chrome://extensions`, bấm nút "Reload" (biểu tượng vòng
tròn) của extension để áp dụng.

## ⚠️ Vì sao bắt buộc HTTPS khi dùng thật

Extension gửi `EXTENSION_TOKEN` trong mỗi request. Nếu `SERVER` là `http://`
(không mã hoá), bất kỳ ai bắt được gói tin trên cùng mạng nội bộ cũng đọc
được mã này ở dạng chữ thường — có mã là ghi được buffer thay bạn. Extension
tự in cảnh báo ra Console nếu phát hiện `SERVER` không bắt đầu bằng
`https://`. Chỉ chấp nhận chạy HTTP khi test trên `localhost` (không rời máy).

## Cách dùng hàng ngày

1. Vào trang CITAD hoặc PaymentHub, tra cứu/truy vấn số liệu như bình thường
   — Extension tự phát hiện kết quả mới và tự lưu (có toast báo góc dưới
   phải màn hình). Nếu không tự lưu, dùng nút thủ công góc dưới phải trang.
   Nếu thấy toast đỏ báo "mã kết nối không hợp lệ" — mã đã hết hạn/bị thu
   hồi (ví dụ do bạn tạo mã mới trên máy khác), quay lại Bước 1 lấy mã mới.
2. Vào `/doi_chieu_citad` trên web TTTT, bấm **"Nạp CITAD"** hoặc **"Nạp
   PaymentHub"** để nạp đúng số liệu vừa lưu vào bảng đối chiếu.

## Nếu đổi máy hoặc nghi ngờ mã bị lộ

Vào `/doi_chieu_citad` → "Kết nối Extension" → **"Thu hồi"** (hoặc bấm "Tạo
mã kết nối mới" để tự động thay mã cũ) — mã cũ ngừng hoạt động ngay lập tức,
không ảnh hưởng tới mã của người khác trong phòng.
