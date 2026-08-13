# Extension Chrome — Đối chiếu CITAD

Content script tự động đọc số liệu từ trang CITAD (NHNN, `10.0.85.100`) và
PaymentHub/Payment (Agribank) rồi gửi lên module **Đối chiếu CITAD** của app
TTTT (`/doi_chieu_citad`), thay cho việc gõ tay từng số.

## Trình duyệt hỗ trợ

Extension đóng gói theo chuẩn Manifest V3 — chạy được **KHÔNG CẦN SỬA GÌ**
trên mọi trình duyệt nền **Chromium**, vì các trình duyệt này dùng chung 1
nền tảng extension với Chrome (đọc thẳng cùng 1 thư mục `extension_citad/`
qua "Load unpacked"):
- **Google Chrome**
- **Microsoft Edge** (`edge://extensions`)
- **Cốc Cốc** (`coccoc://extensions` — trình duyệt Việt Nam, cũng nền
  Chromium)
- Brave, Opera, Vivaldi và các trình duyệt Chromium khác — tương tự

**KHÔNG hỗ trợ Firefox/Safari** — 2 trình duyệt này dùng nền tảng extension
khác hẳn (Firefox: cơ chế ID riêng + hỗ trợ `externally_connectable`/service
worker khác biệt; Safari: bắt buộc build qua Xcode trên máy Mac, không chỉ
là "Load unpacked" thư mục này) — cần làm lại gần như từ đầu nếu muốn hỗ
trợ, ngoài phạm vi bản hiện tại.

Đây là add-on trình duyệt độc lập — không chạy trong tiến trình backend/
frontend của app, nên phải cài **thủ công** vào từng máy cần dùng. Chrome
không cho phép trang web tự cài extension cho người dùng (giới hạn bảo mật
của trình duyệt, không phải do cách đóng gói ở đây) — bước "Load unpacked"
dưới đây là bước duy nhất không thể bỏ qua bằng code. Sau bước đó, mọi cấu
hình đều làm qua giao diện, không cần sửa file nào.

## Cài đặt (mỗi máy làm 1 lần)

1. Mở `chrome://extensions` (Edge: `edge://extensions`, Cốc Cốc:
   `coccoc://extensions` — trình duyệt Chromium nào cũng vào được trang
   quản lý extension theo đường dẫn tương tự)
2. Bật **Developer mode** (góc trên phải)
3. Bấm **Load unpacked**, chọn đúng thư mục `extension_citad/` này

## Cấu hình — tự động, không cần dán tay

Ở `/doi_chieu_citad`, mục **"Kết nối Extension"**, bấm **"Tạo mã kết nối
mới"**. Nếu Extension đã cài trên đúng trình duyệt đang mở trang này, mã sẽ
được gửi thẳng vào Extension ngay lập tức (qua `chrome.runtime.sendMessage`
— xem `background.js`) — không cần sao chép/dán gì cả, dùng được luôn.

Cơ chế: `manifest.json` khai `externally_connectable.matches` chỉ cho phép
đúng các origin của trang TTTT gọi vào Extension, và ID của Extension được
**cố định** bằng khoá `"key"` gắn cứng trong `manifest.json` (không đổi theo
máy/thư mục cài đặt lúc "Load unpacked") — nhờ vậy trang web luôn gọi đúng
Extension mà không cần biết ID sinh ngẫu nhiên trên từng máy.

**⚠️ Khi deploy sang domain production khác `localhost:8080`**: phải thêm
domain thật vào `externally_connectable.matches` trong `manifest.json`, sau
đó build + phát lại bản `.zip` mới (đổi origin nhưng không đổi khoá `"key"`
thì ID vẫn giữ nguyên, không phải cài lại từ đầu trên các máy đã cài).

### Nếu không tự kết nối được (dán tay — trang Tuỳ chọn)

Xảy ra khi: mở trang `/doi_chieu_citad` bằng trình duyệt/máy khác với máy đã
cài Extension, dùng trình duyệt không hỗ trợ `externally_connectable` (không
phải Chrome/Edge/Cốc Cốc/trình duyệt Chromium khác), hoặc domain trang web
chưa được thêm vào
`externally_connectable.matches` ở trên. Khi đó dialog sau khi tạo mã sẽ tự
chuyển sang hiện mã kèm nút sao chép — làm theo:

1. Sao chép mã hiện ra — **chỉ hiện ĐÚNG 1 LẦN**, không xem lại được (tạo mã
   mới sẽ tự động huỷ mã cũ)
2. Bấm icon Extension trên thanh công cụ Chrome → **"Tuỳ chọn"** (hoặc vào
   `chrome://extensions` → tìm extension này → **Chi tiết** → **Tuỳ chọn**)
3. Điền:
   - **SERVER**: địa chỉ backend TTTT thật (`https://<domain>` — bắt buộc
     HTTPS nếu không phải localhost, xem cảnh báo bên dưới)
   - **Mã kết nối**: dán mã đã sao chép ở bước 1
4. Bấm **Lưu cấu hình** — trình duyệt sẽ hỏi xác nhận quyền truy cập đúng
   domain SERVER, bấm **Cho phép**

Không cần Reload extension, cũng không cần tải lại các tab CITAD/PaymentHub
đang mở — mọi tab tự nhận cấu hình mới ngay lập tức (kể cả các tab đã mở
TRƯỚC khi lưu cấu hình), tiện cho trường hợp mở sẵn nhiều tab ẩn danh đăng
nhập nhiều cổng rồi mới bấm "Tạo mã kết nối mới".

> **Dùng tab ẩn danh thì phải bật quyền trước — Chrome mặc định TẮT.**
> Vào `chrome://extensions` → tìm extension này → **Chi tiết** → bật
> **"Cho phép ở chế độ ẩn danh"**. Chưa bật thì extension **không chạy chút
> nào** trong tab ẩn danh: không lưu được số liệu, không có toast báo lỗi,
> nhìn y hệt như extension hỏng. Bật rồi thì cấu hình dùng chung với tab
> thường (extension chạy ở chế độ *spanning*, không tách riêng bộ nhớ).

## ⚠️ Vì sao bắt buộc HTTPS khi dùng thật

Extension gửi "Mã kết nối" trong mỗi request. Nếu `SERVER` là `http://`
(không mã hoá), bất kỳ ai bắt được gói tin trên cùng mạng nội bộ cũng đọc
được mã này ở dạng chữ thường — có mã là ghi được buffer thay bạn. Trang
Tuỳ chọn và Console của Extension tự cảnh báo nếu phát hiện `SERVER` không
bắt đầu bằng `https://`. Chỉ chấp nhận chạy HTTP khi test trên `localhost`
(không rời máy).

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

## Muốn bỏ luôn cả bước "Load unpacked" thủ công?

Không thể bằng code — nhưng có 2 hướng tổ chức có thể cân nhắc (ngoài phạm
vi extension này):
- **Chrome Web Store (Private/Unlisted)**: đóng gói + submit, người dùng chỉ
  cần bấm "Add to Chrome" 1 lần, không cần Developer mode. Cần tài khoản
  Google Developer của Agribank.
- **Chrome Enterprise / Group Policy**: IT đẩy extension tự động vào mọi máy
  qua domain, người dùng không cần thao tác gì. Cần hạ tầng AD/GPO nội bộ.
