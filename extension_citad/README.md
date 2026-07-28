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

## Cấu hình bắt buộc trước khi dùng

Mở `content.js` **và** `content_paymenthub.js`, sửa 3 hằng số ở đầu file:

| Hằng số | Ý nghĩa | Giá trị |
|---|---|---|
| `SERVER` | Địa chỉ backend TTTT thật (không phải `localhost`) | `http://<IP-hoặc-domain-backend>:8000` |
| `EXTENSION_KEY` | Khoá bí mật xác thực Extension, không phải mật khẩu đăng nhập | Đúng giá trị `CITAD_EXTENSION_KEY` đã đặt trong `.env` của backend |
| `STAFF_USERNAME` | Username TTTT của người dùng máy này | Đúng username bạn dùng để đăng nhập web TTTT |

**Vì sao cần `STAFF_USERNAME`:** buffer trên backend được tách riêng theo
từng người dùng (mỗi người 1 vùng nhớ tạm) — nếu để nguyên giá trị mặc định
`CHUA_CAU_HINH`, Extension sẽ báo lỗi và không lưu được gì (tránh trường hợp
nhiều người dùng chung backend ghi đè/xoá dữ liệu của nhau).

## Cách dùng

1. Vào trang CITAD hoặc PaymentHub, tra cứu/truy vấn số liệu như bình thường
   — Extension tự phát hiện kết quả mới và tự lưu (có toast báo góc dưới
   phải màn hình). Nếu không tự lưu, dùng nút thủ công góc dưới phải trang.
2. Vào `/doi_chieu_citad` trên web TTTT, bấm **"Nạp CITAD"** hoặc **"Nạp
   PaymentHub"** để nạp đúng số liệu vừa lưu vào bảng đối chiếu.

## Sau khi cấu hình xong

Chrome không tự đóng gói lại extension khi sửa file trực tiếp trong thư mục
đã Load unpacked — chỉ cần bấm nút "Reload" (biểu tượng vòng tròn) của
extension tại `chrome://extensions` sau khi sửa `content.js`/
`content_paymenthub.js` để áp dụng thay đổi.
