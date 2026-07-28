# PHÂN TÍCH VÒNG ĐỐI CHIẾU — BẢN DÀNH CHO NGƯỜI KHÔNG LÀM CODE

> Ngày: 27/07/2026
> Cơ sở kiểm chứng: `develop` @ `d5722f8` (HEAD) và `caa427f~1` (bản trước, lấy từ lịch sử Git)
> Tài liệu này giải thích kết quả cuộc đối chiếu giữa hai bản rà soát. Không cần biết code để đọc.

---

## 1. CHUYỆN GÌ ĐANG XẢY RA — GIẢI THÍCH ĐƠN GIẢN

Có ba tài liệu, xếp theo thời gian:

| # | Tài liệu | Ai viết | Nội dung |
|---|---|---|---|
| 1 | `RA_SOAT_TTTT_DEVELOP.md` | Người rà soát A | Soi hệ thống, tìm ra 14 vấn đề, đề xuất lộ trình sửa |
| 2 | `REVIEW_RA_SOAT_TTTT_DEVELOP.md` | Tôi | Kiểm tra lại tài liệu 1 — đếm lại từng con số |
| 3 | `PHAN_HOI_REVIEW.md` | Người rà soát A | Trả lời tài liệu 2 — nhận cái nào, phản đối cái nào |

Đây là tài liệu thứ **4**: tôi kiểm tra lại tài liệu 3.

### Vấn đề gốc, nói bằng hình ảnh đời thường

Hãy tưởng tượng anh nhờ một người **chụp ảnh** căn phòng làm việc rồi về nhà ngồi soi ảnh, viết báo cáo "cái ghế kê sai chỗ, bóng đèn cháy, tủ tài liệu không có khoá".

Trong lúc người đó ngồi viết báo cáo, ở phòng làm việc đã có người kê lại ghế và thay bóng đèn.

Báo cáo không sai — **ảnh chụp đúng như thế**. Nhưng khi anh mang báo cáo ra đối chiếu với phòng thật, ba dòng đã lạc hậu.

Đó chính xác là chuyện đã xảy ra. Người rà soát A làm việc trên một **bản sao đóng gói** (file zip) của hệ thống, còn tôi đọc trực tiếp **hệ thống thật**. Giữa hai thời điểm đó có 3 lần sửa code trong cùng một ngày.

**Điểm mấu chốt để anh nắm:** không ai gian dối, không ai làm việc kém. Đây là lỗi **quy trình** — dùng ảnh chụp thay vì vào phòng. Và cả hai bên đã thống nhất cách sửa: từ nay ghi rõ "ảnh này chụp lúc nào" (trong nghề gọi là *commit hash* — như số hiệu bản vẽ).

---

## 2. KẾT QUẢ CUỘC ĐỐI CHIẾU — BẢNG TỔNG

Tôi kiểm chứng lại từng điểm hai bên tranh chấp. Kết quả:

| Điểm tranh chấp | Ai đúng | Ghi chú |
|---|---|---|
| Hệ thống có 3 chỗ đã sửa trước rồi | **Tôi đúng** | A đã chấp nhận |
| Cảnh báo về `run_javascript` là rủi ro không tồn tại | **Tôi đúng** | A nhận là lỗi thật của mình |
| Bỏ sót một chỗ dùng `right_drawer` | **Tôi đúng** | A nhận |
| Hai file hướng dẫn dự án mô tả sai kiến trúc | **Tôi đúng** | A gọi đây là "phát hiện giá trị nhất" |
| Đổi `Ctrl+S` sang `Ctrl+Enter` | **Tôi đúng** | A nhận hoàn toàn |
| Đưa việc thử nâng cấp thư viện lên làm sớm | **Tôi đúng** | A nhận, và tìm thêm bằng chứng ủng hộ |
| Tỷ lệ tương phản màu chữ là 2,54 chứ không phải 2,8 | **Tôi đúng** | A tính lại độc lập, ra cùng kết quả |
| **A không trích sai chữ `100vw`** | **A đúng — tôi sai** | Git history xác nhận |
| **Dòng 176 trong bản zip đúng là `run_javascript`** | **A đúng — tôi sai** | Git history xác nhận |
| **Biến `ENV` có được dùng** | **A đúng — tôi sai** | Đã kiểm tra lại |
| **Số service backend là 21 chứ không phải 17** | **A đúng — tôi sai** | Tôi đếm thiếu một thư mục con |
| **Cách sửa menu bằng CSS của tôi sẽ không chạy** | **A đúng về kết luận** | Nhưng lý do A đưa ra sai — xem mục 5 |
| **Font Inter nạp ở mấy trang?** | **A đúng — tôi sai** | 2 trang, không phải 3 |
| **`handovers.py` chiếm 82% mã màu** | **Cả hai sai** | Con số đúng là ~40% — xem mục 5 |

**Tóm lại:** trong 14 điểm, tôi đúng 7, A đúng 5, cả hai sai 1, và 1 điểm A đúng kết luận nhưng sai lý do.

Đây là dấu hiệu tốt, không phải dấu hiệu xấu. Hai bên soi chéo nhau tìm ra được nhiều lỗi hơn hẳn một bên tự soi. Không có điểm nào bị bỏ ngỏ vì "ai cũng nghĩ người kia đã kiểm".

---

## 3. NHỮNG GÌ ĐÃ CHỐT — ANH KHÔNG CẦN BÀN THÊM

Đây là phần quan trọng nhất với anh: **9 việc dưới đây hai bên đã thống nhất hoàn toàn.** Có thể triển khai ngay.

| # | Việc | Vì sao cần làm | Chi phí |
|---|---|---|---|
| 1 | Chuyển mật khẩu ký cookie ra khỏi source code | Hiện có một "chìa khoá" nằm ngay trong bộ mã nguồn — ai đọc được mã nguồn có thể giả mạo phiên đăng nhập | ~30 phút |
| 2 | Sửa 2 file hướng dẫn dự án đang mô tả sai | Người mới vào đọc tài liệu sẽ tin sai và thiết kế sai theo | ~15 phút |
| 3 | Đổi màu chữ xám nhạt sang đậm hơn một bậc | Chữ hiện quá mờ so với chuẩn quốc tế về khả năng đọc | ~15 phút |
| 4 | Cảnh báo khi hệ thống chạy trên mạng nội bộ mà chưa cấu hình đúng | Tránh việc quên cấu hình rồi hệ thống chặn người dùng, hoặc mở quá rộng | ~1 giờ |
| 5 | Thử nâng cấp thư viện giao diện trên nhánh riêng | Phải biết kết quả **trước** khi xây bộ giao diện dùng chung, tránh làm rồi phải sửa lại | 1 ngày |
| 6 | Nâng cỡ chữ từ 12px lên 14px — làm cùng lúc với việc làm lại bảng biểu | Làm riêng lẻ sẽ vỡ bố cục các bảng đang vừa khít | gộp vào Pha 3 |
| 7 | Dùng `Ctrl+Enter` để lưu, không dùng `Ctrl+S` | Xem mục 4 — đây là việc tránh mất dữ liệu thật | trong Pha 2b |
| 8 | Viết bài kiểm thử **trước** khi chia nhỏ file lớn | Chia 5.000 dòng logic duyệt phép mà không có lưới an toàn là rủi ro trực tiếp lên đơn nghỉ phép thật của người thật | 2 ngày |
| 9 | Chọn trước 3 trang bắt buộc phải chuyển sang bộ giao diện mới | Không có mốc cụ thể thì "chuyển dần" trên thực tế là "không chuyển" | trong Pha 3 |

**Tổng lộ trình hai bên đồng thuận: khoảng 18 ngày công.**

---

## 4. VIỆC SỐ 7 — GIẢI THÍCH VÌ SAO ĐÁNG QUAN TÂM

Đây là mục duy nhất trong toàn bộ đề xuất có thể **gây mất dữ liệu thật**, nên tôi tách ra giải thích riêng.

Đề xuất ban đầu là dùng `Ctrl+S` để lưu biểu mẫu — vì đó là phím quen thuộc.

**Vấn đề:** `Ctrl+S` là phím mà **trình duyệt** đã dùng cho việc "Lưu trang web này thành file". Muốn dùng lại phím đó cho việc khác thì phải chặn trình duyệt ở từng trang.

Hình ảnh đời thường: giống như trong toà nhà có một cái nút màu đỏ mà ai cũng biết là "gọi thang máy". Giờ ta muốn ở tầng 3 nút đó thành "gọi bảo vệ". Muốn vậy phải dán giấy che nút thang máy ở tầng 3.

Hai chuyện sẽ xảy ra:

1. **Quên dán ở một tầng** → người bấm nút tưởng gọi bảo vệ, thang máy tới. Trong hệ thống: hộp thoại "Save as…" của Windows bật ra giữa lúc cán bộ đang nhập liệu.

2. **Nguy hiểm hơn** — cán bộ ngân hàng có phản xạ `Ctrl+S` từ Excel. Họ sẽ bấm ở **mọi** trang, kể cả trang không có biểu mẫu. Nếu phím tắt im lặng không làm gì, **họ tưởng đã lưu trong khi chưa lưu.**

Chuyện thứ hai là loại lỗi tệ nhất trong thiết kế: không phải "hệ thống báo lỗi", mà là "hệ thống làm người dùng tin sai".

**Giải pháp đã chốt:** dùng `Ctrl+Enter` để lưu (không xung đột với trình duyệt). Vẫn bắt `Ctrl+S`, nhưng bắt ở tầng toàn hệ thống: có biểu mẫu thì lưu, không có thì hiện thông báo rõ ràng *"Trang này không có biểu mẫu để lưu"*. **Im lặng là lựa chọn tệ nhất.**

---

## 5. HAI ĐIỂM TÔI CẦN ĐÍNH CHÍNH TRONG PHẢN HỒI CỦA A

Phản hồi của A chất lượng cao. Nhưng có hai chỗ cần sửa, và cả hai đều **không đổi kết luận** — chỉ đổi lý do. Việc này quan trọng vì lý do sai dẫn tới quyết định sai về sau.

### 5.1 Con số "82%" là phép chia không hợp lệ

A viết: *"`handovers.py` một mình đã chiếm 82% tổng số mã hex"* — con số này dùng để biện minh cho việc chọn `handovers.py` làm trang cần sửa đầu tiên.

**Vấn đề:** phép tính là 47 chia 57. Nhưng hai con số đó **không cùng đơn vị**.

Hình ảnh đời thường: trong một xưởng sơn có **57 loại sơn khác nhau** trên giá. Ở phòng A, thợ đã **quét sơn 47 lần**. Chia 47 cho 57 rồi nói "phòng A chiếm 82% số sơn" là vô nghĩa — một bên là *số loại*, một bên là *số lần dùng*.

Tôi đếm lại cho đúng cả hai cách:

| Cách đếm | Toàn hệ thống | Riêng `handovers.py` | Tỷ lệ đúng |
|---|---|---|---|
| **Số lần** viết mã màu cứng | 118 | 47 | **40%** |
| **Số loại** màu khác nhau | 57 | 24 | **42%** |

Không cách nào ra 82%. Con số đúng là **khoảng 40%** — vẫn là trang tệ nhất, nhưng mức độ chỉ bằng **một nửa** những gì A mô tả.

**Vì sao điều này quan trọng với anh:** nếu tin con số 82%, người ta sẽ nghĩ "sửa xong `handovers.py` là gần như xong việc". Thực tế sửa xong trang đó vẫn còn 60% khối lượng ở 20 trang khác. Con số sai làm kế hoạch lạc quan quá mức.

**Ghi nhận công bằng:** mầm mống lỗi này nằm trong tài liệu gốc (bảng B5 đặt cạnh nhau "58 mã hex trong frontend" và "handovers.py riêng 47 mã hex" — hai cách đếm khác nhau, trình bày như thể so sánh được). A chỉ nhân lỗi đó lên. Đề xuất chọn `handovers.py` làm trang mốc **vẫn đúng**.

Độ tin cậy: **cao** — đếm trực tiếp, hai cách, kết quả nhất quán.

### 5.2 Lý do "menu không thể mở chậm được" bị gán sai cho thư viện

Đây là điểm kỹ thuật, tôi giải thích bằng hình ảnh.

**Bối cảnh:** menu con của phần mềm hiện mở khi rê chuột vào, và đóng ngay khi chuột rời. Vấn đề là khi rê chuột **chéo** từ tên phòng xuống mục con nằm lệch bên dưới, con trỏ ra khỏi vùng menu trong tích tắc → menu đóng, phải rê lại. Lỗi này lặp lại hàng chục lần mỗi ngày.

**Cách sửa tôi đề xuất:** cho menu "nán lại" 120 phần nghìn giây trước khi đóng — đủ để chuột đi chéo qua.

**A phản đối, và A đúng:** cách tôi mô tả sẽ không chạy được. Lý do — bằng hình ảnh:

Hiện tại menu được **cất vào tủ và đóng cửa tủ** (thuật ngữ: `display: none`). Không có cách nào "đóng cửa tủ từ từ" — cửa đóng là mất hút ngay lập tức. Muốn có hiệu ứng nán lại thì phải đổi cách ẩn: **để menu trên bàn nhưng phủ một tấm khăn** (thuật ngữ: `visibility: hidden`). Khăn thì gỡ được từ từ, phủ được từ từ.

Kết luận của A đúng, và đoạn CSS thay thế A viết ra tôi đã kiểm — **chạy được, và viết đúng chỗ khó nhất**: A đặt độ trễ ở chiều *đóng*, chiều *mở* vẫn tức thì. Nếu đặt sai chiều thì menu sẽ mở chậm 120ms, cảm giác lag rõ rệt. A tránh được bẫy này.

**Chỗ cần đính chính:** A giải thích rằng nguyên nhân là *"Quasar 2.16 (đi kèm NiceGUI 1.4.37) chưa hỗ trợ tính năng này"*.

Đây là gán sai địa chỉ. Tính năng đó là của **trình duyệt** (Chrome / Edge), không phải của thư viện giao diện. Thư viện giao diện là bộ khuôn dựng nút bấm và bảng biểu — nó không có quyền quyết định trình duyệt hiểu được lệnh CSS nào.

Hình ảnh: giống như nói *"cái tủ này không mở ra được vì bản thiết kế nội thất chưa cập nhật"*. Không — tủ mở được hay không phụ thuộc vào **bản lề**, không phụ thuộc bản thiết kế.

**Vì sao điều này quan trọng với anh:** nếu tin lời giải thích của A, có người sẽ nói *"khoan sửa menu đã, chờ nâng cấp thư viện lên bản mới rồi tự nhiên chạy"*. Điều đó **sẽ không xảy ra** — nâng cấp thư viện không liên quan gì tới chuyện này. Việc sửa menu phải làm bằng cách A đề xuất, bất kể có nâng cấp hay không.

Độ tin cậy: **cao** cho việc gán sai địa chỉ; **cao** cho việc đoạn CSS của A chạy được.

**Một điểm A chưa nêu, tôi bổ sung:** khi đổi từ "cất vào tủ" sang "phủ khăn", có một tính chất cần thử: tấm khăn phủ menu cha **không tự động phủ menu con** — về nguyên tắc menu con có thể tự gỡ khăn của nó ra và hiện lơ lửng một mình. Trên thực tế điều này khó xảy ra (vật bị phủ khăn thì không nhận được chuột), nhưng đây là loại lỗi hiển thị kỳ quái, khó đoán, nên cần thử một lần cho chắc. A đã liệt kê 3 việc cần thử — đây là việc thứ **4**.

**Ước tính:** A nói ~3 giờ thay vì ~2 giờ của tôi. Tôi đồng ý với A, thêm 30 phút cho điểm thử số 4 → **~3,5 giờ**.

---

## 6. HAI CÂU HỎI A NHỜ ANH — ĐÃ CÓ ĐÁP ÁN

A nhờ anh chạy hai lệnh để chốt số liệu. Tôi đã chạy.

### Câu 1 — Font chữ nạp ở mấy trang?

**Đáp án: 2 trang.** A đúng, tôi sai.

Chi tiết: chỉ `login.py` (trang đăng nhập) và `change_password.py` (trang đổi mật khẩu) nạp font Inter. **19 trang còn lại** dùng font mặc định.

Tôi báo 3 trang, có thêm trang Trang chủ. Đó là **lỗi máy móc của tôi**: tôi tìm chuỗi chữ `Inter` và nó khớp với chữ `minInterval` — một tham số cấu hình biểu đồ, chẳng liên quan gì tới font. Kiểu lỗi này trong nghề gọi là "khớp giả" — như tìm người tên "An" trong danh bạ rồi nhận cả "Lan", "Tuấn Anh".

Ngoài ra tôi phát hiện `storage.py` có khai báo font Arial, nhưng đó là **font cho bản in giấy**, không phải font màn hình — không tính vào đây.

**Kết luận không đổi, mà còn mạnh hơn:** 2 trang một kiểu chữ, 19 trang kiểu khác. Cán bộ đăng nhập thấy một font, vào việc thấy font khác.

### Câu 2 — Còn bản ghi nào dùng vai trò cũ `controller` không?

**Đáp án: 0 bản ghi.** Đã chuyển đổi xong sạch.

Phân bố vai trò thật trong hệ thống, 78 người:

| Vai trò | Số người |
|---|---|
| Chuyên viên | 42 |
| Phó phòng | 17 |
| Trưởng phòng | 6 |
| Hậu kiểm viên | 5 |
| Phó Giám đốc | 3 |
| Quản trị viên cấp 1 | 2 |
| Quản trị viên cấp 2 | 2 |
| Giám đốc | 1 |
| **`controller` (vai trò cũ)** | **0** |

**Nghĩa là:** dòng code xử lý vai trò `controller` trong giao diện là **mã phòng thủ đã hết việc** — xoá được an toàn, không cần chuyển đổi dữ liệu gì trước.

*(Ghi chú nhỏ: lệnh SQL A gợi ý dùng tên bảng `ksnb_staff`, tên thật là `user_tttt` — nên lệnh đó sẽ báo lỗi nếu chạy nguyên văn. Không ảnh hưởng gì tới kết luận.)*

---

## 7. MỘT VIỆC A PHÁT HIỆN THÊM — ĐÁNG CHÚ Ý

Trong lúc đính chính tôi về biến `ENV`, A tìm ra một chuyện đáng quan tâm hơn cả điểm đang tranh luận.

Hệ thống có một trang liệt kê **toàn bộ 162 cửa giao tiếp** của phần mềm (địa chỉ `/docs`), kèm mô tả từng cửa nhận dữ liệu gì. Trang này chỉ nên bật khi lập trình viên đang gỡ lỗi.

**Vấn đề:** nó chỉ tự tắt nếu người vận hành khai báo *"đây là môi trường chạy thật"*. Mặc định hệ thống coi mình đang ở môi trường phát triển → **trang này đang mở.**

Hình ảnh đời thường: như dán ở sảnh toà nhà một tấm bảng liệt kê đầy đủ 162 cánh cửa, mỗi cửa dẫn vào đâu, cần loại thẻ nào để qua. Bảng đó rất tiện cho thợ bảo trì. Nhưng nó không nên để ở sảnh cho khách đọc.

Đây **không phải lỗ hổng cho phép xâm nhập** — vẫn cần thẻ mới qua được cửa. Nhưng nó cho người ngoài bản đồ đầy đủ để biết nên thử cửa nào. Trong môi trường ngân hàng, đó là thông tin không nên phát.

Cùng vấn đề gốc mà tôi nêu ở mục cảnh báo cấu hình: **nếu người vận hành quên khai báo một thứ, khả năng cao họ quên cả những thứ khác cùng loại.** Nên cảnh báo không được dựa vào lời khai báo, mà dựa vào **sự thật quan sát được** — hệ thống tự nhìn xem mình đang mở ra mạng nội bộ hay không, rồi tự nhắc.

**Xử lý:** gộp vào cùng cảnh báo khởi động ở Pha 0. Không thêm chi phí đáng kể.

---

## 8. ĐÁNH GIÁ PHẢN HỒI CỦA A

| Tiêu chí | Nhận xét |
|---|---|
| **Tính trung thực** | Rất cao. A phân biệt rõ ba loại: "lỗi thật của tôi", "tôi đọc đúng bản cũ", "không kiểm chứng được". Ba nhãn này khác nhau về bản chất, và trộn lẫn chúng là cách phổ biến nhất để né trách nhiệm. A không né. |
| **Chất lượng phản biện** | Cao. Điểm mục 5.2 — chỉ ra cách sửa CSS của tôi không chạy được — là phản biện **cứu được nửa ngày làm việc**. Không có nó, người thực thi sẽ viết thêm một dòng, mở trình duyệt, thấy menu vẫn đóng tức thì, rồi mất buổi chiều đi tìm nguyên nhân. |
| **Độ chính xác số liệu** | Tốt, một lỗi. Phép chia 82% là lỗi số học thật, và nó nằm ở chỗ dùng để ra quyết định. |
| **Tự phê đúng chỗ** | Cao. Ở mục R2, A tự phân biệt: *"trích dẫn dòng của tôi không sai; sai là ở suy luận — tôi thấy có `run_javascript` rồi kết luận nó dính lỗi, mà không kiểm tra nó có dùng đúng hai tham số bị bỏ hay không. Đó là lỗi logic, nghiêm trọng hơn lỗi trích dẫn."* Nhận đúng loại lỗi khó hơn nhận có lỗi. |
| **Thái độ khi thắng** | Điểm mục 5.2, A thắng nhưng không dùng nó để hạ giá phần còn lại của review. Vẫn giữ kết luận của tôi và chỉ chỉnh ước tính từ 2 giờ lên 3 giờ. |

**Kết luận: phản hồi đạt chất lượng làm việc.** Hai vòng đối chiếu đã đưa tài liệu rà soát từ trạng thái "có 3 mục lỗi thời + 1 rủi ro không tồn tại" sang trạng thái dùng được để triển khai.

---

## 9. VIỆC CẦN ANH QUYẾT — CHỈ CÒN MỘT CÂU

Ban đầu có 7 câu hỏi cần anh xác nhận. Sau hai vòng đối chiếu:

| Trạng thái | Số câu | Chi tiết |
|---|---|---|
| ✅ Hai bên đã đồng thuận, không cần anh quyết | 5 | Vỏ ứng dụng (Phương án 1) · Bàn phím (`Ctrl+Enter`) · Cỡ chữ 14px (gộp Pha 3) · Bộ giao diện áp dụng dần + 3 trang mốc · Thử nâng cấp thư viện ở Pha 0,5 |
| ✅ Đã tự giải quyết | 2 | Ba phòng chưa có tính năng (đã ẩn ở `caa427f`) · Thứ tự test/tách file (đã thống nhất) |
| ⬅️ **Còn lại, cần anh** | **1** | **Độ phân giải màn hình tối thiểu cần hỗ trợ** |

### Câu duy nhất còn lại — và vì sao chỉ anh trả lời được

**Câu hỏi:** máy tính của cán bộ trong Trung tâm có màn hình cỡ nào?

Đây là câu duy nhất **không thể tìm ra bằng cách đọc code**. Nó phụ thuộc vào thiết bị thật đang có trên bàn làm việc.

**Vì sao nó quan trọng:** nó quyết định mỗi bảng biểu hiện được bao nhiêu cột, và biểu mẫu xếp 1 cột hay 2 cột.

| Nếu thiết kế cho | Máy 1366px sẽ | Máy 1920px sẽ |
|---|---|---|
| 1366×768 (thấp nhất) | Vừa khít | Hơi thưa, chấp nhận được |
| 1920×1080 (cao) | **Phải cuộn ngang mọi bảng** | Vừa khít |

Chọn sai theo hướng lạc quan gây hậu quả nặng hơn: cán bộ dùng laptop đời cũ sẽ phải cuộn ngang **mọi bảng, mọi ngày**.

**Cách trả lời rẻ nhất:** một buổi đi hỏi, hoặc nhìn nhanh vào màn hình cũ nhất trong phòng. Không cần thống kê đầy đủ — chỉ cần biết **cái nhỏ nhất là bao nhiêu**.

**Khuyến nghị nếu anh không muốn khảo sát:** chọn **1366×768**. Thiết kế cho máy yếu nhất thì máy khoẻ vẫn dùng tốt; ngược lại thì không.

---

## 10. ĐIỀU QUAN TRỌNG NHẤT CẦN NHỚ

Nếu anh chỉ đọc một mục trong tài liệu này, đọc mục này.

**1. Hệ thống của anh về cơ bản lành mạnh.** Cả hai vòng rà soát đều kết luận phần lõi xử lý nghiệp vụ ở mức tốt: khoá bảo mật fail-fast, giới hạn số lần đăng nhập sai, tự sao lưu, bắt đổi mật khẩu lần đầu, cảnh báo lệch giờ mà không tự sửa. Trọng tâm cần đầu tư là **giao diện và trải nghiệm**, không phải xây lại nền.

**2. Rủi ro lớn nhất không phải lỗi code — là hai file hướng dẫn dự án đang mô tả sai kiến trúc.** Hai file này là thứ mọi người mới (và mọi phiên làm việc của công cụ AI) đọc đầu tiên. Một dòng sai ở đó không sai một lần — nó sai **lặp lại** với mọi người, mọi lần, và mỗi lần dẫn tới một quyết định thiết kế dựng trên giả định sai. Chi phí sửa: 15 phút. Đây là việc có tỷ lệ giá trị trên chi phí cao nhất trong toàn bộ danh sách.

**3. Việc nguy hiểm nhất trong lộ trình là chia nhỏ file 5.018 dòng xử lý nghỉ phép** — vì quy trình duyệt phép **đang chạy thật**. Nếu bước duyệt Giám đốc hỏng một ngày, đơn nghỉ phép thật của người thật bị treo. Cả hai bên đã thống nhất: **viết bài kiểm thử trước, chia file sau.** Xin đừng đảo thứ tự này để tiết kiệm thời gian.

**4. Về quy trình rà soát:** bài học rút ra không phải "người rà soát làm sai" mà là "đừng soi ảnh chụp". Từ nay mọi tài liệu rà soát ghi rõ **số hiệu bản** ở đầu file. Một dòng chữ giải quyết triệt để vấn đề đã tốn của hai bên gần một vòng đối chiếu.

**5. Hai vòng soi chéo đã có giá trị đo được:** loại bỏ 3 mục đã lỗi thời, 1 rủi ro không tồn tại, 1 lỗi số học ở chỗ ra quyết định, 1 cách sửa CSS không chạy được, và tìm thêm 3 vấn đề mới (file backend 2.716 dòng, hai file hướng dẫn sai, trang `/docs` đang mở). Không vòng nào trong hai vòng đó tự mình làm được toàn bộ.

---

*Phân tích vòng đối chiếu — 27/07/2026 · Cơ sở: `develop` @ `d5722f8`, đối chiếu với `caa427f~1` từ lịch sử Git*
