# Logs cập nhật hệ thống

Ghi lại từng đợt push lên GitHub / deploy sang máy chính (qua `deploy.bat`). Entry mới nhất ở trên cùng.

---

- 12/08/2026 Đối chiếu CITAD - Sửa lỗi lệch số liệu ngoại tệ do cắt xu USD/EUR:
    + **Lỗi thật, gây sai số liệu**: ô nhập số liệu (5 cổng, Payment, Napas, PSS-MDP, Ebanking) hiển thị số theo kiểu số nguyên — USD/EUR có phần xu (vd 2.954.592,79) bị **cắt mất phần xu khi hiển thị**, và chữ đã cắt này sau đó bị đọc ngược lại thành số liệu gốc, mất vĩnh viễn phần xu. Xác nhận thực tế: ngày 06/08/2026 lệch đúng 1 xu vì 3 khoản USD đều bị cắt trước khi cộng
    + Sửa để giữ nguyên phần xu khi hiển thị — áp dụng cho cả VNĐ (không đổi, luôn số nguyên) lẫn USD/EUR (giờ hiện đủ 2 chữ số thập phân nếu có)
    + Sửa luôn 1 chỗ sót: dòng **"CHÊNH LỆCH"** trên màn hình (và bảng xem trước khi xuất Excel) vẫn còn 1 công thức riêng cắt xu độc lập, chưa được sửa cùng lần trước — lệch thật kiểu +0,79 từng hiện nhầm thành "+0" (vẫn bôi đỏ đúng nhưng số hiện sai). Đã test lại bằng số liệu thật, hiện đúng
    + File Excel tải về không bị ảnh hưởng (backend luôn tính lại bằng số thực đầy đủ, độc lập với màn hình)

- 12/08/2026 Đối chiếu / Đối soát CITAD - Thêm bộ lọc Lịch sử theo ngày + tên người chấm, tự động refresh:
    + **Đối chiếu CITAD**: tab Lịch sử thêm ô lọc **"Tên người chấm"** (trước chỉ lọc được theo ngày). Cột "Người lưu sau cùng" đổi sang hiện tên đầy đủ thay vì tên đăng nhập
    + **Đối soát CITAD ↔ IPCAS**: tab Lịch sử trước đây **không có bộ lọc nào** (chỉ hiện 100 lần gần nhất) — nay thêm đủ 3 ô lọc **"Từ ngày chấm"/"Đến ngày chấm"/"Tên người chấm"**
    + **Tự động cập nhật Lịch sử**: trước đây phải bấm F5 tải lại cả trang thì tab Lịch sử mới thấy bản vừa lưu/đối soát. Nay ở **Đối chiếu CITAD**, ngay sau khi lưu thành công, Lịch sử tự nạp lại dữ liệu mới ở phía sau — **không tự chuyển tab**, đang ở tab nào vẫn ở nguyên tab đó. Bên **Đối soát CITAD ↔ IPCAS** cơ chế này vốn đã có sẵn từ trước, đã kiểm tra lại xác nhận vẫn hoạt động đúng
    + Đã sửa kèm 1 lỗi hiệu năng tự phát sinh khi thêm bộ lọc: câu truy vấn lịch sử đối soát bị mất giới hạn số dòng, tải hết cả bảng mỗi lần gọi kể cả khi không lọc gì — đã thêm lại giới hạn cho trường hợp không lọc (phổ biến nhất)

- 11/08/2026 Đối chiếu CITAD - Extension lên **bản 2.14**, sửa dứt điểm lỗi chọn nhầm bảng rỗng:
    + ℹ️ Đây là **bản chốt** của chuỗi 2.11 → 2.14: ba bản trước chẩn đoán chưa đúng vì không có dữ liệu thật từ trang Agribank. Bản này sửa theo đúng nguyên nhân đã xác nhận qua lệnh kiểm tra chạy trực tiếp trên trang — không phải lại một lần đoán nữa
    + Xác nhận qua console: trang có **nhiều bảng trùng cấu trúc cột** (cùng có cột "NH gửi") — bảng **đầu tiên** khớp tên cột lại **rỗng** (0 dòng, khả năng là bảng mẫu/bản sao ẩn phục vụ mục đích khác), còn bảng có dữ liệu thật (13 dòng) nằm ở vị trí khác trong trang
    + Extension trước đây chọn đại bảng đầu tiên khớp tên cột mà không kiểm tra bảng đó có dữ liệu hay không, nên luôn vớ trúng bảng rỗng — dù bảng thật vẫn còn nguyên, tưởng "không có kết quả"
    + Nay bỏ qua mọi bảng rỗng trước khi so khớp tên cột, chỉ chọn bảng vừa đúng tên cột vừa có ít nhất 1 dòng dữ liệu
    + ⚠️ **Phải tải lại `.zip` và cài lại Extension** — vào `/doi_chieu_citad` → **Tải Extension**, giải nén, *Load unpacked* lại

- 11/08/2026 Đối chiếu CITAD - Extension lên **bản 2.13**, tìm ra nguyên nhân thật khiến không đọc được cột "NH gửi":
    + Xác nhận qua lệnh kiểm tra trực tiếp trên trình duyệt (Console): cột "NH gửi" và "Số tiền" đều có sẵn trong bảng, chữ sạch — **không phải do tên cột lệch hay có icon** như 2 lần sửa trước (bản 2.11/2.12) từng đoán
    + Nguyên nhân thật: hàm dò cột tiêu đề chỉ tìm trong `<thead>` hoặc đúng dòng đầu tiên của bảng, nhưng bảng thật của trang này không đặt tiêu đề cột theo 1 trong 2 kiểu đó — dò trượt dù cột vẫn tồn tại. Nay dò mọi thẻ tiêu đề trong bảng, không giới hạn vị trí
    + ⚠️ **Phải tải lại `.zip` và cài lại Extension** — vào `/doi_chieu_citad` → **Tải Extension**, giải nén, *Load unpacked* lại

- 11/08/2026 Bàn giao chứng từ - Thêm nút **Trả lại** để hậu kiểm chủ động trả chứng từ về cho cán bộ:

- 12/08/2026 Nghỉ phép / Kỹ thuật - Sửa lỗi **hai thư mục "Phòng Tổng hợp" trùng tên** trong `templates/` làm mẫu đơn theo chức danh không được dùng:
    + **Trong `templates/` đang có hai thư mục tên y hệt nhau là "Phòng Tổng hợp"** — nhìn trong Explorer thấy hai dòng giống hệt. Nguyên nhân: chữ có dấu tiếng Việt có hai cách lưu khác nhau bên trong máy (dạng dựng sẵn và dạng ghép dấu rời), Windows coi là hai tên khác nhau nên tạo ra hai thư mục
    + **Hậu quả**: chương trình tìm mẫu đơn nghỉ phép trong thư mục **rỗng**, nên các **mẫu đơn riêng theo chức danh** (nhân viên / trưởng phòng / giám đốc / phó giám đốc) nếu đặt vào thư mục thật sẽ **không bao giờ được dùng** — hệ thống lặng lẽ quay về mẫu chung, không báo lỗi gì. Hiện thư mục đó đang rỗng nên chưa ai gặp, nhưng cứ bỏ mẫu riêng vào là dính ngay
    + ⚠️ **Đính chính**: lần báo trước có ghi *"máy chỉ checkout từ git sẽ hỏng phiếu nghỉ phép"* — **không đúng**. In đơn nghỉ phép vẫn chạy bình thường vì có sẵn mẫu chung ở thư mục gốc để dùng thay. Lỗi thật chỉ ảnh hưởng mẫu riêng theo chức danh
    + **Đã xử lý**: xoá thư mục thừa (bản rỗng, không có file nào, không nằm trong git), **giữ thư mục đang chứa dữ liệu** (`Báo cáo giao dịch chuyển tiền qua Swift`). Đồng thời sửa cách chương trình dò đường dẫn để khớp được cả hai cách lưu, không phụ thuộc thư mục được tạo kiểu nào
    + ⚠️ **Khi thêm file mẫu mới**: **copy/paste vào thư mục đang có sẵn**, **đừng gõ tay tên thư mục** để tạo thư mục mới — gõ tay sẽ đẻ lại đúng thư mục trùng vừa xoá và lỗi quay lại y như cũ
    + Không đổi giao diện, không đổi quyền, không cần thao tác gì sau khi cập nhật

- 12/08/2026 Lưu trữ - Thêm tab **"In bìa hồ sơ"** để in bìa hồ sơ lưu trữ (mẫu M01/LHS) hàng loạt từ file Excel tra cứu:
    + **Trước đây phải vào chương trình lưu trữ bấm in từng hồ sơ một.** 140 hồ sơ là 140 lần bấm, mỗi lần ra một file Word riêng
    + Nay vào *Quản lý chứng từ → Lưu trữ → tab **In bìa hồ sơ***, nạp file Excel tra cứu (`LT_HS_TRACUU_*.xls`) xuất thẳng từ chương trình lưu trữ. Phần mềm đọc file, hiện bảng để soát lại, tích chọn hồ sơ cần in rồi tải về **một file Word — mỗi hồ sơ một trang**, in một lượt. Ai muốn từng file riêng thì bấm nút **Tải ZIP (mỗi hồ sơ 1 file)**
    + Dữ liệu lấy từ đâu: **Mã vạch** = cột I (điền vào dòng *Ký hiệu thông tin* và dòng mã vạch); **dòng tiêu đề** = cột C; **Ngày mở** = ngày **đầu tiên** xuất hiện trong cột C (ví dụ *"Nhật ký chứng từ ngày 04/02/2025, 05/02/2025, 06/02/2025"* → ngày mở là **04/02/2025**); **Ngày công việc kết thúc** = cột F; **Số tờ** = cột G
    + **Bìa in ra giống hệt bìa của chương trình lưu trữ.** Đã đối chiếu với 2 file bìa gốc do chương trình lưu trữ tự sinh (kèm trong file zip người dùng gửi) — chữ trên bìa trùng khít từng ký tự, kể cả hồ sơ gộp nhiều ngày. Mẫu Word không bị đụng tới định dạng, căn lề, cỡ chữ hay font nào
    + ⚠️ **Máy in phải cài font "3 of 9 Barcode".** Không có font thì dòng mã vạch in ra thành chữ thường `*1000.P026.178074.1*` và **máy quét không đọc được**. Đây là yêu cầu sẵn có của mẫu bìa, không phải phát sinh mới — nhưng giờ in hàng loạt nên lỡ thiếu font là hỏng cả tập
    + Dòng nào trong Excel mà tên hồ sơ **không có ngày** thì ô *Ngày mở* để trống, và phần mềm **báo cảnh báo vàng kèm số thứ tự dòng** ngay trên bảng để soát lại trước khi in
    + Quyền: dùng chung quyền màn hình *Lưu trữ* (`menu.storage`), **không cần cấp thêm gì**

- 12/08/2026 Toàn hệ thống - **Sắp xếp lại menu theo chức năng thay vì theo phòng**:
    + **Trước đây menu cấp 1 là tên phòng.** Muốn mở *Đối chiếu ACH* phải biết trước nó thuộc Phòng Thanh toán; người mới hoặc người kiêm nhiệm nhiều mảng phải mò từng phòng
    + Nay menu cấp 1 là **việc cần làm**:
        - **Quản lý chứng từ** → Bàn giao chứng từ / Đóng chứng từ / Lưu trữ
        - **Đối chiếu** → *Phòng Thanh toán* (Chấm 459901, Song phương, ACH, Đối chiếu CITAD cuối ngày, Đối soát chênh lệch CITAD cuối ngày) và *Phòng Swift* (Đối chiếu điện SWIFT)
        - **Báo cáo** → *Phòng KSNB & HTVH* (Báo cáo hậu kiểm, Báo cáo bàn giao chứng từ) và *Phòng Tổng hợp* (Báo cáo dữ liệu thanh toán)
        - **Nghỉ phép**, **Phân lịch trực**, **Danh sách CN TTQT** đứng riêng ngoài cùng, không còn nằm trong phòng nào
    + Tên phòng **chỉ còn ở tầng giữa** của hai menu Đối chiếu và Báo cáo — nơi cùng một loại việc nhưng mỗi phòng làm một kiểu. Chỉ hiện phòng đang thực sự có tính năng
    + **Quyền của mọi nhóm giữ nguyên 100%** — chỉ đổi cách sắp xếp, không đổi tên chức năng nào. Không ai bị mất hay được thêm quyền sau lần cập nhật này
    + ⚠️ **Màn *Phân quyền theo nhóm* đổi bố cục theo menu mới.** Đường đi cũ trong các log bên dưới không còn đúng — ví dụ quyền *Chuyển trả chứng từ cho GDV* trước ở *Phòng KSNB & HTVH → Bàn giao chứng từ*, **nay ở *Quản lý chứng từ* → Bàn giao chứng từ**. Quyền vẫn còn nguyên, chỉ nằm ở thẻ khác
    + Màn phân quyền có thêm nút **"Chọn tất cả" / "Bỏ chọn"** cạnh mỗi tên phòng. Nút này **chỉ tích các màn hình**, không tự tích các thao tác bên trong (tạo / xoá / xử lý file…) — muốn cấp thao tác vẫn phải tự tích, tránh lỡ tay cấp quyền chạy dữ liệu

- 11/08/2026 Bàn giao chứng từ - Thêm nút **Chuyển trả GDV** để hậu kiểm chủ động trả chứng từ về cho giao dịch viên:
    + **Trước đây chứng từ đã xác nhận chỉ ra khỏi kho được khi giao dịch viên chủ động xin mượn.** Hậu kiểm cầm chứng từ trên tay, thấy thiếu chữ ký hay sai sót, muốn trả về cho cán bộ thì không có nút nào — phải nhờ chính cán bộ đó vào bấm *Mượn lại* rồi mình duyệt, vòng vèo và sai bản chất sự việc
    + Nay ở **bảng lịch sử của từng ô** (bấm vào ô trong lưới), phần *THAO TÁC* có thêm nút tím **"↪ Chuyển trả GDV"**. Nút **chỉ hiện với ô đang ở trạng thái *Đã xác nhận*** — ô đang chờ, đang mượn hay bị từ chối đều không có
    + **Bắt buộc nhập lý do chuyển trả**, không nhập thì không bấm được. Lý do hiện ngay trong dòng lịch sử của ô, ai cũng đọc được
    + Bấm xong ô chuyển sang **Đang mượn** (ô tím). Từ đây cán bộ dùng nút *Bàn giao lại* như bình thường, hậu kiểm xác nhận lại là xong — giống hệt luồng mượn cũ
    + ⚠️ **Phải cấp quyền thì nút mới hiện.** Vào *Phân quyền theo nhóm* → **Phòng KSNB & HTVH → Bàn giao chứng từ → "Chuyển trả chứng từ cho GDV"**, tích cho nhóm hậu kiểm / kiểm soát viên. Chưa tích thì không ai thấy nút, kể cả người đang có quyền xác nhận
    + **Giao dịch viên không được cấp quyền này** — hệ thống chặn ở máy chủ kể cả khi lỡ tích nhầm. Nếu cho, cán bộ sẽ tự rút được chứng từ đã chốt của chính mình mà không qua bước duyệt của hậu kiểm
    + ⚠️ **Ô đã đóng tập chứng từ vẫn chuyển trả được** — bìa tập đã in sẽ không còn khớp thực tế. Chức năng *Mượn lại* sẵn có cũng đang như vậy, nên lần này giữ nguyên cho nhất quán. Cần chặn thì báo để sửa cả hai chỗ cùng lúc

- 11/08/2026 Đối chiếu CITAD - Extension lên **bản 2.12**, sửa lỗi không đọc được cột "NH gửi" có sẵn trong bảng kết quả:
    + Xác nhận lại thực tế: cột "NH gửi" (dùng tách Napas/PSS-MDP) **có sẵn ngay trong bảng kết quả mặc định** (Loại lệnh: Lệnh quyết toán, NH gửi để "Tất cả") — kéo bảng sang phải là thấy, **không cần** bấm "Xem chi tiết lệnh" như bản 2.10/2.11 từng giả định
    + Lỗi thật: hàm bắt cột so khớp **tuyệt đối** tên cột ("NH gửi" phải khớp y hệt) — bảng có nút sắp xếp cột hay chèn icon/khoảng trắng phụ vào tiêu đề khiến so khớp trượt dù cột hiển thị đúng. Nay so khớp kiểu "chứa chuỗi" sau khi chuẩn hoá khoảng trắng, khoan dung hơn
    + Sửa luôn đường lọc theo bộ lọc "NH gửi" cụ thể (bản 2.11): trước đọc giá trị đang chọn qua chữ hiển thị (`innerText`), không đọc được nếu ô lọc là `<input>` với giá trị nằm trong thuộc tính `value`. Nay tự dò cả `value` của input/select lẫn chữ hiển thị
    + ⚠️ **Phải tải lại `.zip` và cài lại Extension** — vào `/doi_chieu_citad` → **Tải Extension**, giải nén, *Load unpacked* lại

- 11/08/2026 Đối soát CITAD ↔ IPCAS - Sửa 2 lỗi làm sai lệch số liệu ngoại tệ (rà soát code, chưa có báo cáo thực tế):
    + **File CITAD nhiều sheet đọc sai loại tiền từ sheet thứ 2 trở đi**: chỉ sheet đầu tiên được nhận diện VNĐ/USD/EUR, các sheet sau luôn bị coi mặc định là VNĐ — sai cả cột đọc số tiền lẫn nhãn loại tiền, khiến lệnh ngoại tệ ở sheet 2+ bị đẩy nhầm sang so khớp IPCAS (đáng lẽ phải so Hub ngoại tệ) và báo lệch "Chỉ CITAD" giả
    + **File Hub ngoại tệ có cột ngày dạng Date thật bị lọc rớt hết, không báo lỗi**: cột ngày so với ngày chấm bằng so chuỗi, nhưng ô kiểu Date thật (phổ biến với file xuất chuẩn) đọc ra "yyyy-mm-dd" — không bao giờ khớp "dd/mm/yyyy" người dùng nhập → toàn bộ file Hub bị coi như rỗng, mọi lệnh ngoại tệ báo lệch "Chỉ CITAD" dù thực ra khớp đủ trong file đã tải lên
    + Cả 2 lỗi đều **âm thầm, không cảnh báo trên giao diện** — người dùng có thể đã ký duyệt báo cáo với số lệch ngoại tệ giả mà không biết. Đã sửa. **Dấu hiệu nhận ra lần đối soát bị dính lỗi: kết quả ra 0 lệnh ngoại tệ khớp và toàn bộ đều rơi vào "Chỉ CITAD"** — đó gần như chắc chắn là lỗi này chứ không phải số liệu lệch thật. Gặp vậy thì đối soát lại bằng bản mới

- 11/08/2026 Đối chiếu CITAD - Extension lên **bản 2.11**, thêm cách tách Napas/PSS-MDP khi đã lọc sẵn theo "NH gửi":
    + Nếu tự lọc ở form tìm kiếm "NH gửi" = 01401001 (Napas) hoặc 01406001 (PSS-MDP) rồi mới Tìm kiếm — Extension nay đọc thẳng bảng kết quả (khỏi cần bấm "Xem chi tiết lệnh"), tự cộng dồn cột "Số tiền" của toàn bộ dòng vì trang không tự cộng sẵn tổng tiền kiểu lọc này (chỉ có "Tổng số giao dịch" đếm số món)
    + **An toàn phân trang**: nếu số dòng quét được ít hơn "Tổng số giao dịch" trang báo (còn trang sau chưa xem), Extension **không lưu** số liệu thiếu — kể cả lượt tự động — tránh nạp nhầm số liệu hụt vào form Đối chiếu CITAD
    + Cách tách cũ (không lọc "NH gửi", tự bung "Xem chi tiết lệnh" rồi đọc cột NH gửi theo từng dòng — bản 2.10) vẫn giữ nguyên, dùng khi không lọc theo NH gửi
    + ⚠️ **Phải tải lại `.zip` và cài lại Extension** — vào `/doi_chieu_citad` → **Tải Extension**, giải nén, *Load unpacked* lại

- 11/08/2026 Đối chiếu CITAD - Extension lên **bản 2.10**, tự tách Napas/PSS-MDP không cần bấm tay:
    + Trang "Chuyển tiền đến" (payment.agribank.com.vn) sau khi Tìm kiếm chỉ hiện bảng tóm tắt — cột "NH gửi" (dùng để phân biệt Napas/PSS-MDP) chỉ có ở bảng **chi tiết lệnh**, phải tự tích chọn dòng + bấm "Xem chi tiết lệnh" mới hiện ra. Trước đây không ai biết bước này nên bấm "Lưu Napas + PSS-MDP" báo nhầm *"Chưa có kết quả, hãy Tìm kiếm trước"* dù đã tìm kiếm ra kết quả
    + Nay Extension **tự tích "chọn tất cả" + tự bấm "Xem chi tiết lệnh"** ngay khi phát hiện có kết quả tìm kiếm mới — tách Napas/PSS-MDP theo mã NH gửi (01401001/01406001) hoàn toàn tự động, không cần thao tác tay nào ngoài bấm Tìm kiếm
    + ⚠️ **Phải tải lại `.zip` và cài lại Extension** — vào `/doi_chieu_citad` → **Tải Extension**, giải nén, *Load unpacked* lại
    + *Giới hạn biết trước*: nếu kết quả tìm kiếm trải nhiều trang, "chọn tất cả" chỉ chọn các dòng đang hiển thị trên trang hiện tại — giống hạn chế khi thao tác tay từ trước, không phải lỗi mới


- 11/08/2026 Quản lý User - Sửa lỗi trang không hiện được tài khoản nào:
    + **Màn hình *Quản lý User* báo lỗi đỏ và hiện *"Không có kết quả"*** dù trong hệ thống có 79 tài khoản. Không sửa, không xoá, không khoá được ai qua giao diện. Ảnh hưởng **Quản trị viên cấp 1 và cấp 2, Giám đốc, Phó Giám đốc**. Trưởng phòng không bị nên lỗi dễ bị bỏ qua khi người này báo còn người kia bảo vẫn dùng được
    + Nguyên nhân: **một tài khoản có ô trạng thái bỏ trống** — không phải *Hoạt động*, cũng không phải *Tạm khoá*. Chỉ một dòng như vậy là đủ để hệ thống bỏ luôn **cả danh sách**, chứ không phải bỏ riêng dòng đó
    + **Không phải làm gì thủ công.** Lần khởi động đầu tiên sau khi cập nhật, hệ thống tự đặt các tài khoản trạng thái trống thành **Tạm khoá** — đúng với cách nó vẫn đối xử với những tài khoản này từ trước (không đăng nhập được, không hiện trong danh sách đang hoạt động, xuất Excel cũng đã ghi *Tạm khoá*). Không tài khoản nào đang dùng bị đổi trạng thái
    + Trạng thái trống nếu **phát sinh lại về sau** (thường qua chức năng *Nhập DB*) thì trang vẫn hiện bình thường thay vì sập, và không cần khởi động lại
    + ⚠️ **Còn 2 tài khoản kiểm thử trong dữ liệu, nên xoá:** `u1` (*LD Một*, Trưởng phòng, **Phòng Thanh toán**) và `duty_mig_check` (*LD Kiểm Tra*, Trưởng phòng, Phòng QLTK Nostro Vostro). Đã kiểm: **chưa ai từng đăng nhập** vào hai tài khoản này và chúng **không dính chứng từ, bìa, đơn nghỉ phép hay ca trực nào** — xoá không mất dữ liệu. Đáng lưu ý là `u1` đang hiện **đầu danh sách** ô *Người phê duyệt (KSV)* khi chuyên viên phòng Thanh toán tạo đơn nghỉ phép, rất dễ bị chọn nhầm

- 10/08/2026 Đối chiếu CITAD - Extension lên **bản 2.9**, dùng được địa chỉ `apc-portal:9090`:
    + Thêm địa chỉ `apc-portal:9090` (một địa chỉ khác cùng trỏ về trang web TTTT) vào danh sách Extension được phép gọi. Máy trạm nào vào hệ thống bằng địa chỉ này trước đây sẽ báo *"Không kết nối server"* dù cấu hình đúng
    + ⚠️ **Phải tải lại `.zip` và cài lại Extension** thì mới có hiệu lực — bản đang cài không tự nhận. Vào `/doi_chieu_citad` → **Tải Extension**, giải nén, *Load unpacked* lại
    + Máy nào đang vào bằng `apc-portal:8080` hoặc `10.1.3.89` và chạy bình thường thì **không bắt buộc** cập nhật ngay

- 10/08/2026 Phân lịch trực - Khai số người mỗi ca, ca quyết toán chính/phụ, sửa tay được thành phần ca (PR #26):
    + **Số người mỗi ca không còn cứng trong hệ thống** — vào tab *Cài đặt* khai riêng cho ca thường và ca quyết toán (số Lãnh đạo, số nhân viên trực chính, số trực phụ). **Một ca có thể khai nhiều hơn một Lãnh đạo** (tối đa 5), nhất là ngày quyết toán. Lịch tạo sau khi lưu sẽ theo số này
    + ⚠️ **Thiếu người so với số đã khai thì hệ thống KHÔNG lập ca ngày đó**, kèm dòng cảnh báo nêu rõ thiếu ở đâu. Trước đây vẫn sinh ca thiếu người mà không báo gì
    + **Ngày quyết toán** nay là **một ca duy nhất** có nhóm trực chính và nhóm trực phụ (trực phụ về sớm hơn), thay vì hai dòng riêng như trước. Lịch cũ được gộp tự động khi khởi động
    + **Sửa tay được thành phần ca trực** — bấm biểu tượng bút ở cột phải. Chọn sai vai (xếp nhân viên vào chỗ Lãnh đạo) hoặc sai số người thì bị chặn; xếp người đang đi dự án / đã khai vắng mặt thì vẫn cho lưu nhưng có cảnh báo. **Sửa xong ca quay về bản thảo, phải xác nhận lại**
    + Người giữ vai **xử lý song phương** hệ thống tự xác định từ cờ *"biết song phương"* của cán bộ — không phải chọn tay nữa. Ca thiếu hoặc dư người song phương đều vẫn lập, chỉ hiện cảnh báo
    + **Bỏ cờ "Backup SP"** — nay chỉ còn một cờ *"biết song phương"* duy nhất. Ai đang được đánh dấu Backup SP sẽ tự chuyển sang cờ mới, không mất khả năng trực song phương
    + Lịch ngày thường **bốc ngẫu nhiên trong nhóm ít ca nhất** nên không còn đoán trước được ai trực ngày nào, nhưng số ca vẫn chia đều. Thứ 6 giữ luân phiên cố định như cũ
    + **Chia ca đều hơn hẳn.** Phân thử 2 tháng (49 ca) trên danh sách nhân sự thật cho thấy: các Lãnh đạo chênh nhau nhiều nhất 1 ca (9–10 ca mỗi người), và **không ai phải trực 2 lần trong cùng một tuần**. Trước đây có Lãnh đạo trực 15 ca trong khi người khác chỉ 6 ca, và 8 lượt phải trực từ 2 lần trở lên trong một tuần — có người 3 lần. *(Số đo trên danh sách hiện tại; phòng ít người đi hoặc nhiều người nghỉ cùng lúc thì vẫn có thể phải trực lặp trong tuần)*
    + Thêm cơ chế **tránh hai người cứ đi trực cùng nhau mãi** — trước đây một Lãnh đạo và một nhân viên có thể bị ghép cặp cả 10/10 ca
    + Bảng lịch tuần **5 cột** (Ngày trực · Nhân viên 1 · Nhân viên 2 · Lãnh đạo · Tình trạng), luôn hiện đủ 5 hàng T2→T6, và **trạng thái chung của cả tuần hiện ngay cạnh tiêu đề tuần**. Ngày quyết toán hiện tên người trực chính IN HOA đậm, trực phụ chữ nghiêng nhỏ bên dưới
    + Thống kê ca trực tách **2 cột riêng: trực chính và trực phụ** — không quy đổi lẫn nhau
    + Sửa lỗi: bỏ tick *"biết song phương"* cho một Lãnh đạo thì sau khi khởi động lại hệ thống **cờ tự bật lại**. Nay lựa chọn được giữ nguyên
    + Sửa lỗi: đổi *số nhân viên ca thường* rồi lưu có thể làm **cấu hình ca quyết toán bị trả về mặc định** mà không báo gì
    + Sửa lỗi: hết phiên đăng nhập trong lúc mở tab *Cài đặt* thì màn hình im lặng hiện số mặc định thay vì đưa về trang đăng nhập
    + ⚠️ **Bịt lỗ hổng phân quyền — hãy soát lại quyền đã cấp cho từng nhóm.** Trước đây hệ thống chỉ *ẩn nút* trên màn hình, còn bên dưới thì **bất kỳ ai đăng nhập được cũng có thể xoá cả tuần lịch đã xác nhận** nếu biết cách gọi thẳng. Nay quyền được kiểm ở máy chủ. Hệ quả: ai trước giờ vẫn thao tác được nhờ lỗ hổng này mà **chưa được cấp quyền đúng** sẽ bắt đầu bị báo *"Không có quyền truy cập tính năng này"* — vào *Phân quyền theo nhóm* cấp bổ sung. Admin không bị ảnh hưởng
    + Nút **sửa ca trực** nay yêu cầu quyền *Tạo lịch trực tự động* (`duty.generate`) thay vì hiện cho mọi người có bất kỳ quyền nào — sửa tay cũng là sửa lịch

- 10/08/2026 Đối chiếu / Đối soát CITAD - Thêm kênh PSS-MDP, bắt lệnh gửi trùng, tự lọc file theo ngày (PR #25):
    + ⚠️ **Số "Khớp" và "Lệch" sẽ khác các lần chấm trước — số mới mới là số đúng.** Trước đây một lệnh CITAD bị gửi trùng N lần được tính khớp N lần, trong khi IPCAS chỉ có 1 bản ghi. Nay chỉ lần đầu tính khớp, các lần trùng tách riêng. Ai đang theo dõi bằng file Excel riêng sẽ thấy vênh với hệ thống
    + **Lệnh gửi trùng nay hiện rõ** trong nhóm *Chỉ CITAD*, ghi luôn *"bị dup mấy lần, cổng nào"* — trước đây trùng bao nhiêu lần cũng im lặng tính là khớp
    + **Tải chung file CITAD của nhiều ngày cũng được** — hệ thống đọc dòng *"Ngày giao dịch"* trong từng file và tự bỏ file khác ngày chấm, không phải tự lọc tay nữa. File nào bị bỏ đều được liệt kê rõ dưới nút Đối soát
    + **Bắt được trường hợp IPCAS báo lệnh lỗi/huỷ (ERPO, CALD) nhưng CITAD cho thấy lệnh đã đi kênh thành công** — xếp vào *Lệch trạng thái* kèm ghi chú, không lẫn vào *Chỉ Agribank*. Còn lệnh lỗi mà CITAD cũng không có thì là thất bại bình thường, không báo nữa
    + Thêm nút **Reset** cạnh ô *Ngày chấm* (có hỏi lại trước khi xoá) để bắt đầu phiên chấm mới, khỏi phải tải lại trang
    + **Đối chiếu CITAD**: thêm kênh **PSS - MDP**, cách tính giống Napas (cộng vào tổng CITAD). Bỏ 2 dòng *Waiting for AUTO* / *Waiting for manual* không còn dùng trên file Excel xuất ra
    + Đổi tên menu cho rõ: *Đối chiếu CITAD* → **Đối chiếu CITAD cuối ngày**; *Đối soát CITAD ↔ IPCAS* → **Đối soát chênh lệch CITAD cuối ngày**
    + Extension lên **bản 2.8** — vào màn hình Đối chiếu CITAD tải lại `.zip` rồi cài lại để nhận kênh PSS-MDP

- 10/08/2026 Toàn hệ thống - Sửa lỗi log tiếng Việt bị hỏng chữ:
    + **File nhật ký kỹ thuật `logs\backend.log` và `logs\frontend.log` trước đây ghi sai chữ tiếng Việt.** Câu *"Backup hoàn tất"* bị ghi thành `Backup ho?n tất`, *"Đã xóa thành viên"* thành `Đ? x?a th?nh vi?n`. Lỗi có từ 11/05/2026, không ai để ý vì hệ thống vẫn chạy bình thường và không báo lỗi gì
    + **Không ảnh hưởng tới số liệu hay nghiệp vụ.** Chỉ hỏng phần chữ trong file nhật ký kỹ thuật dành cho người quản trị đọc khi có sự cố. Dữ liệu, báo cáo, file Excel xuất ra đều không liên quan
    + **Màn hình *Nhật ký hệ thống* trên web vẫn luôn đúng** — màn hình đó đọc file khác (`logs\app.log`), file này không bị lỗi
    + ⚠️ **Phần nhật ký cũ đã hỏng thì không khôi phục được.** Từ nay các dòng mới ghi đúng. **Không phải làm gì thủ công** — lần khởi động đầu tiên sau khi cập nhật, hệ thống tự chuyển phần nhật ký cũ sang `logs\backend.truoc-utf8.log` và `logs\frontend.truoc-utf8.log`, rồi ghi tiếp vào file mới sạch. Không xoá dòng nào, chỉ tách ra file bên cạnh
    + Ngoài ra bịt luôn một lỗi tiềm ẩn: nếu chạy các chức năng đối chiếu bằng công cụ dòng lệnh thay vì qua web, chỉ một dòng chữ tiếng Việt là đủ làm dừng giữa chừng cả tiến trình đối chiếu

- 07/08/2026 Đối chiếu CITAD - Extension lên **bản 2.6**, bắt buộc cài lại:
    + ⚠️ **PHẢI TẢI LẠI VÀ CÀI LẠI EXTENSION.** Bản 2.5 đang cài trên máy trạm sẽ tiếp tục báo *"Không kết nối server"* dù mọi thứ phía máy chủ đã đúng. Vào `/doi_chieu_citad` → **Tải Extension**, giải nén, rồi *Load unpacked* lại như lần đầu
    + Nguyên nhân: từ bản trước, nút **Tạo mã kết nối mới** tự điền địa chỉ máy chủ vào Extension — nhưng đường tự động đó **không xin được quyền truy cập địa chỉ** cho trình duyệt, nên Extension bị chặn ngay ở tầng quyền. Chỉ khi tự vào Tuỳ chọn bấm Lưu mới xin được. Nay quyền được cấp sẵn ngay lúc cài, không phụ thuộc cách cấu hình nữa
    + Sau khi cài lại, kiểm nhanh: mở `edge://extensions` (hoặc `chrome://extensions`) → phần **Site access** phải thấy `apc-portal:8080`. Không thấy nghĩa là chưa cài đúng bản mới
    + Không cần làm gì thêm — mã kết nối cũ vẫn dùng được, không phải tạo lại

- 07/08/2026 Bảo mật - Đóng cổng backend khỏi mạng nội bộ, tắt trang liệt kê API *(chưa deploy — cần sửa `.env` trên máy chính rồi khởi động lại)*:
    + **Gỡ 2 cảnh báo đỏ hiện mỗi lần khởi động hệ thống chính.** Cả hai đều báo đúng: cổng backend (8000) đang mở ra toàn mạng nội bộ dù không ai cần vào, và trang liệt kê toàn bộ API đang xem được công khai
    + Nay cổng 8000 **chỉ nghe trong máy chủ**. Người dùng không bị ảnh hưởng gì — trình duyệt vẫn vào bằng đúng địa chỉ cũ (cổng 8080), Extension CITAD vẫn đi chung cổng đó như từ 06/08
    + Đã đối chiếu nhật ký máy chính trước khi đổi: **419/419 lượt đăng nhập** và **toàn bộ** thao tác Đối chiếu CITAD đều đi qua đường trong máy chủ, **50 máy trạm** đang dùng đều vào bằng cổng 8080 — không máy nào phụ thuộc cổng vừa đóng
    + Nếu có máy nào từng *tự gõ tay* địa chỉ có `:8000` vào trang Tuỳ chọn của Extension thì sẽ báo *"Không kết nối server"*. Cách sửa: vào `/doi_chieu_citad` bấm **Tạo mã kết nối mới** — hệ thống tự điền lại địa chỉ đúng
    + Trang `/docs` (danh sách 180 đường dẫn API kèm cấu trúc dữ liệu) **không còn mở công khai**. Trước đây bất kỳ ai trong mạng gõ đúng địa chỉ đều xem được cả sơ đồ hệ thống. Không lấy được dữ liệu vì vẫn phải đăng nhập, nhưng là tấm bản đồ dâng sẵn cho người dò
    + Vá thêm một lỗ liên quan: tắt `/docs` theo cách cũ **chưa tắt hết** — vẫn còn một đường dẫn phụ trả về nguyên danh sách 180 API đó ở dạng dữ liệu thô. Nay đóng cả hai
    + **Không phải sửa tay gì trên máy chính** — chạy `deploy.bat` là nó tự hỏi và sửa `.env` giúp (bước 1/7). Hệ thống test giữ nguyên `/docs` để còn gỡ lỗi

- 07/08/2026 Nhật ký hệ thống - Sửa lỗi trang trắng khi có thông báo nhiều dòng *(chưa deploy)*:
    + ⚠️ **Trang *Nhật ký hệ thống* trước đây vỡ đúng lúc hệ thống có lỗi cần xem.** Bản ghi một dòng thì hiện bình thường, nhưng bản ghi nhiều dòng (mô tả lỗi chi tiết) làm trang không hiện được — đã xảy ra **94 lần** trên máy chính mà không ai báo
    + Nay xem được mọi bản ghi, nội dung nhiều dòng giữ nguyên cách xuống dòng cho dễ đọc
    + Không đổi gì về dữ liệu hay quyền xem — chỉ là cách hiển thị


- 06/08/2026 Đối soát CITAD - Đọc được file `.xlsx`, và Extension gọi được máy chủ thật (PR #20):
    + ✅ **GỠ CẢNH BÁO NGÀY 04/08: file CITAD định dạng `.xlsx` nay đọc bình thường.** Trước đây mọi file `.xlsx` bị đọc ra rỗng mà không báo lỗi — màn hình vẫn hiện "đối soát xong" nhưng số khớp bằng 0 và toàn bộ lệnh bị xếp vào "Chỉ IPCAS". Từ nay dùng `.xls` hay `.xlsx` đều được
    + ⚠️ **Ai đã đối soát bằng file `.xlsx` trước ngày 06/08 thì làm lại.** Kết quả cũ và bản đã lưu ở tab *Lịch sử* của những lần đó đều sai — không phải số liệu lệch thật
    + **Extension nay gọi được máy chủ thật.** Trước đây máy chủ chỉ mở cổng giao diện ra máy trạm nên Extension luôn báo *"Không kết nối server"* dù cấu hình đúng. Nay đi chung một cổng với web, không phải mở thêm gì trên tường lửa
    + Nút **Tạo mã kết nối mới** trước đây ghi vào Extension một địa chỉ chỉ đúng trên máy chủ, nên vừa không dùng được vừa **xoá mất cấu hình đúng ai đã điền tay**. Nay lấy đúng địa chỉ đang mở trên trình duyệt
    + Vá một lỗ hổng: có thể giả mạo địa chỉ IP ghi vào Nhật ký hệ thống cho các thao tác Đối chiếu CITAD. **Nhật ký cũ vẫn đúng** — lỗ hổng chỉ mở đường cho ai cố tình, không làm sai dữ liệu đang có

- 06/08/2026 Nghỉ phép - Sửa loạt lỗi hạn mức, số liệu Dashboard và thao tác duyệt (PR #18):
    + **Đổi tab trong màn Nghỉ phép không còn trắng màn hình** — chuyển tab tức thì thay vì tải lại cả trang
    + ⚠️ **Ô "Đã dùng" ở tab Hạn mức phép trước đây cộng dồn mỗi lần bấm Lưu** — mở dialog rồi bấm Lưu mà không sửa gì cũng làm số ngày đã dùng tăng gấp đôi. Nay bấm Lưu bao nhiêu lần giá trị vẫn giữ nguyên. **Cần soát lại hạn mức của các nhân viên đã từng sửa tay trước ngày 06/08**
    + ⚠️ **Nhập file hạn mức Excel dính đúng lỗi trên** — nhân viên đã có đơn nghỉ thật trong năm bị cộng dồn ngay từ lần nhập đầu tiên. Nay hệ thống trừ đúng phần đơn thật rồi mới ghi phần chênh lệch
    + Nhập số "Đã nghỉ" **thấp hơn số ngày đã nghỉ thật** thì hệ thống giữ theo số thật và **báo rõ tên những người bị giữ**, không âm thầm để lệch số
    + Số liệu nhập hạn mức (từ file Excel hoặc sửa tay) **không còn hiện lẫn như một đơn nghỉ thật** ở Lịch nghỉ phép, "Đơn của tôi", danh sách toàn trung tâm, kiểm tra trùng ngày và số liệu Dashboard
    + **5 ô số liệu ở Dashboard đổi theo khoảng ngày** chọn ở Bộ lọc tìm kiếm, đúng phạm vi vai trò của từng người
    + **Bắt buộc chọn Ban lãnh đạo phê duyệt** khi tạo đơn và khi nộp lại — trước đây bỏ trống được, đơn sẽ kẹt vĩnh viễn ở bước Tổng hợp
    + Sửa nút **Phê duyệt / Từ chối** ở bảng Dashboard không phản hồi khi tick chọn; đổi tab nay tự bỏ tick để không xử lý nhầm đơn đã chọn ở tab khác
    + Nhãn trạng thái thống nhất một kiểu ở mọi màn hình: **"Chờ Ban lãnh đạo duyệt"** và **"Hoàn thành"**
    + Tải dữ liệu trang lỗi thì **báo rõ**, không âm thầm hiện số 0

- 06/08/2026 Báo cáo bàn giao chứng từ - Sửa cách trừ ngày nghỉ phép của người nhận:
    + Báo cáo chấm đúng hạn/quá hạn có **trừ những ngày người nhận bàn giao đi nghỉ phép** (người nhận vắng thì không thể trách người nộp). Nhưng số liệu hạn mức phép nhập từ Excel bị tính nhầm thành ngày nghỉ thật, khiến **chứng từ nộp quá hạn trong tháng 1 bị chấm thành đúng hạn**
    + Nay báo cáo chỉ trừ đơn nghỉ phép thật. **Số liệu các kỳ đã xem trước đây không đổi** (hệ thống chưa có dữ liệu hạn mức nhập vào) — đây là vá phòng ngừa trước khi bắt đầu dùng thật
    + Nhật ký hệ thống ghi rõ thao tác **"Sửa số ngày phép đã dùng"** thay vì mô tả chung chung

- 05/08/2026 Phòng Thanh toán - Thêm màn hình **Đối chiếu ACH** (GL02 ↔ MIS):
    + Menu *Phòng Thanh toán → Đối chiếu* có thêm **Đối chiếu ACH**. Công cụ trước đây chạy riêng trên một máy nay vào thẳng phần mềm, dùng chung tài khoản và phân quyền như mọi màn hình khác
    + Cách dùng: chọn (hoặc kéo thả) đủ bộ file của một ngày — file GL02, file GW, 2 file MIS chiều ĐI, 2 file MIS chiều ĐẾN và file PDF sao kê. Màn hình có **bảng kiểm tra đã đủ file chưa**, thiếu loại nào báo ngay chứ không để chạy xong mới lỗi
    + **Ngày đối chiếu để trống là được** — hệ thống tự lấy từ tên file PDF. Nếu tên file không đúng mẫu thì **báo lỗi rõ ràng**, không tự dùng một ngày khác
    + Kết quả là 1 file Excel gồm bảng tổng kết, bảng phân tích có **cảnh báo tự động** (lệnh TPAY chưa xử lý, lệnh timeout không đi kênh, cặp chi nhánh + số tiền nghi sai số trace) và các sheet chi tiết khớp / chưa khớp từng chiều. Sheet nào **trên 15.000 dòng** được tách ra file CSV riêng, tải lẻ từng file hoặc bấm **Tải tất cả (ZIP)**
    + ⚠️ **Mở file CSV bằng Excel → Data → Từ Văn bản/CSV, đừng double-click.** Double-click sẽ mất số 0 đứng đầu ở cột TRACE, MSGSEQ và sai định dạng số tiền
    + Trong lúc chạy có **thanh tiến độ và nhật ký xử lý**; bấm **Dừng** thì hệ thống dừng ở bước gần nhất chứ không cắt ngang giữa chừng (cắt ngang dễ làm treo máy chủ). Dừng xong báo *"Đã dừng đối chiếu theo yêu cầu"* — không phải báo lỗi đỏ
    + Bấm ✕ để bỏ file chọn nhầm: nếu máy chủ chưa xoá được (Windows đang khoá file vừa ghi) thì **báo rõ và giữ nguyên file trong danh sách**, không để màn hình nói đã xoá trong khi file vẫn còn
    + Một lúc chỉ chạy **một lần đối chiếu**; người bấm sau sẽ thấy trạng thái đang xếp hàng. Kết quả giữ trên máy chủ **4 giờ** rồi tự xoá — cần thì tải về máy, không lưu lịch sử tra cứu lại
    + Cần bật quyền trong *Phân quyền theo nhóm* (`menu.doi_chieu_ach`, `doi_chieu_ach.process`), nếu không chỉ admin nhìn thấy menu
    + ⚠️ **Máy chủ phải chạy lại `pip install -r requirements.txt`** (thêm 2 thư viện `xlsxwriter`, `python-calamine`), nếu không backend không khởi động được

- 05/08/2026 Đối chiếu CITAD - Extension lấy đúng số tiền lẻ và tự điền được mã kết nối:
    + ⚠️ **Số tiền USD/EUR lấy tự động từ Extension trước đây sai gấp 100 lần.** Phần xu bị nhập vào thành phần nguyên — `1.234,56` USD thành `123.456`. Nay lấy đúng cả phần lẻ
    + **Số món không dính lỗi này, và VNĐ cũng không** (không có đơn vị lẻ). Chỉ ảnh hưởng cột số tiền của USD và EUR
    + ⚠️ **Cần soát lại các bản đã lưu có USD/EUR nạp bằng Extension trước ngày 05/08.** Số liệu gõ tay không dính
    + Nút **Tạo mã kết nối mới** nay đẩy mã thẳng vào Extension, không phải sao chép dán tay. Trước đây luôn rơi về cách dán tay vì địa chỉ máy chủ thật chưa khai trong Extension
    + Extension lên **bản 2.5** — vào màn hình Đối chiếu CITAD tải lại file `.zip` rồi cập nhật để nhận thay đổi. Máy chưa cập nhật vẫn dùng được nhưng còn nguyên lỗi số tiền lẻ ở trên

- 05/08/2026 Báo cáo bàn giao chứng từ - Thêm nút xuất file Word:
    + Nút **Xuất file Word** nằm ngay cạnh nút *Xem báo cáo*. File ra dạng **A4 ngang**, tiêu đề *"Báo cáo bàn giao chứng từ tháng xx năm xxxx"*
    + Nội dung: bảng tổng hợp theo phòng (tổng chứng từ, nộp đúng hạn, nộp quá hạn, tỷ lệ đúng hạn, có dòng **TỔNG CỘNG**) và phần chi tiết chứng từ nộp quá hạn tách theo từng phòng
    + Phần chi tiết chỉ ghi **họ và tên** cán bộ — không in User IPCAS (màn hình vẫn giữ cột này để tra cứu). Chứng từ của cùng một cán bộ được **xếp liền nhau và gộp ô họ tên thành một**, trong cụm sắp theo ngày giao dịch
    + Xuất đúng **kỳ đang xem trên màn hình**: đổi ô Tháng/Năm mà chưa bấm *Xem báo cáo* thì file vẫn ra tháng đang hiển thị, không bị lệch âm thầm
    + Số liệu trong file dùng chung một hàm tính với màn hình và Trang chủ — không có chuyện file Word lệch với bảng đang xem

- 04/08/2026 Phòng KSNB & HTVH - Thêm màn hình Danh sách CN TTQT:
    + Menu *Phòng KSNB & HTVH → **Danh sách CN TTQT*** — tra cứu danh sách chi nhánh thực hiện thanh toán quốc tế trực tiếp ngay trên hệ thống, không phải mở file Excel dùng chung nữa. Đã nạp sẵn **218 chi nhánh** theo file *Danh sách CN thực hiện TTQT* bản 06.01.26 (204 đang hoạt động, 14 đã đóng BIC)
    + Tìm theo **mã CN, tên CN hoặc mã SWIFT BIC** — **gõ không dấu cũng ra** (`dien bien` ra *Điện Biên*), không phân biệt chữ hoa chữ thường; lọc thêm theo *loại CN* và *trạng thái*. Mặc định chỉ hiện CN **đang hoạt động** — muốn xem CN đã đóng BIC thì đổi ô *Trạng thái*, khi xem chung hai nhóm thì dòng đã đóng BIC được **tô xám**
    + **Thêm / sửa / xoá từng chi nhánh** ngay trên màn hình. Mọi thao tác đều được ghi vào Nhật ký hệ thống
    + **Nhập từ Excel**: chọn thẳng file gốc phòng KSNB phát hành, **không phải sửa gì trước khi nhập** — hệ thống hiểu dòng đánh dấu *Đóng BICCODE* và tự xếp các CN phía dưới vào nhóm đã đóng BIC
    + **Xuất Excel** đúng phần đang lọc, định dạng giống file gốc nên **nhập lại được** — dùng để phát hành bản cập nhật cho các chi nhánh
    + ⚠️ **Nhập Excel mặc định KHÔNG xoá chi nhánh nào** — chỉ thêm mới và cập nhật CN có trong file. Nếu file mới đã bỏ bớt chi nhánh và muốn hệ thống bỏ theo thì phải **tự tích ô *"Xoá CN không có trong file"*** trước khi chọn file. Không tích thì các CN cũ vẫn nằm nguyên trong danh sách
    + ⚠️ Nhập nhầm file **không hoàn tác được** — chưa có lịch sử nhập như màn *Hạn mức phép*. Kiểm kỹ file trước khi chọn, nhất là khi đã tích ô xoá
    + ⚠️ Menu này **phải được cấp quyền** ở màn *Phân quyền chức năng* (mục *Danh sách CN TTQT* trong nhóm Phòng KSNB & HTVH). Quyền xem, thêm, sửa, xoá, nhập, xuất cấp riêng từng loại — không cấp thì mục menu không hiện
    + ⚠️ **Tên chi nhánh trong file gốc có 11 dòng gõ dấu kiểu cũ** (chữ và dấu tách rời). Hệ thống tự chuẩn hoá khi nhập nên tìm kiếm vẫn ra. Nếu sau này gõ tay tên CN từ nguồn khác dán vào mà tìm không ra, báo lại để kiểm tra

- 04/08/2026 Tài khoản - Đặt lại mật khẩu cho người dùng khác:
    + Ô *Chọn người dùng* nay **gõ được để tìm**, không phải cuộn hết danh sách nhân sự. Cách dùng giống hệt ô *Thêm nhân viên* ở màn *Quản lý nhóm quyền*

- 04/08/2026 Bàn giao chứng từ - Phân lại quyền xem và quyền nhập liệu:
    + **Trưởng phòng, Phó phòng** nay vào được màn hình *Bàn giao chứng từ* — xem lưới **phòng của mình**. Cần quản trị cấp mục *Bàn giao chứng từ* trong màn *Phân quyền chức năng* cho nhóm của họ thì mới hiện menu
    + **Quyền nhập/sửa số tờ của Trưởng phòng, Phó phòng vẫn theo nhóm quyền như mọi người khác** — không cấp *Lưu số tờ chứng từ* thì chỉ xem, không gõ được
    + ⚠️ **Admin, Giám đốc, Phó giám đốc từ nay CHỈ XEM, không nhập/sửa/xác nhận được chứng từ.** Đổi lại các vị này xem được **tất cả các phòng** và xuất Excel toàn bộ. Trước đây tài khoản admin sửa được dữ liệu bàn giao — nay không còn. **Cần chữa số liệu nhập sai thì phải dùng tài khoản hậu kiểm hoặc tài khoản trong đúng phòng đó**, không nhờ admin được nữa
    + Ô nhập trên lưới nay **khoá hẳn** với người không có quyền lưu. Trước đây vẫn gõ được vào ô nhưng bấm Lưu thì không có gì xảy ra — nhìn như hệ thống nuốt mất số vừa nhập

- 04/08/2026 Phòng Thanh toán - Thêm 2 màn hình Đối chiếu CITAD và Đối soát CITAD ↔ IPCAS:
    + Menu *Phòng Thanh toán → Đối chiếu* có thêm **Đối chiếu CITAD** (đối chiếu số liệu với PaymentHub) và **Đối soát CITAD ↔ IPCAS** (khớp từng lệnh chuyển tiền). Cả hai chuyển từ công cụ chạy riêng trên máy vào thẳng phần mềm, dùng chung tài khoản và phân quyền như mọi màn hình khác
    + **Đối chiếu CITAD**: nhập số liệu 5 cổng × 3 loại tiền, chênh lệch tự tính ngay khi gõ. Mỗi ngày là **một bản ghi chung của cả phòng**, kèm tab *Lịch sử* xem lại từng lần lưu. Xuất Excel đúng mẫu báo cáo NHNN đã duyệt
    + **Đối soát CITAD ↔ IPCAS**: tải file CITAD, IPCAS và Hub ngoại tệ lên, hệ thống khớp lệnh rồi liệt kê phần lệch theo 4 nhóm, xuất Excel 4 sheet. Có lưu lịch sử để xem lại đúng số liệu của lần đối soát cũ. Hệ thống **cảnh báo khi chọn trùng file** (so nội dung từng byte, không dựa vào tên file)
    + Kèm **Extension trình duyệt** tự lấy số liệu từ trang CITAD và PaymentHub sang, khỏi chép tay. Tải ngay trên màn hình Đối chiếu CITAD, ghép nối bằng *mã kết nối* riêng của từng người
    + ~~⚠️ **Đối soát CITAD: dùng file CITAD định dạng `.xls`, KHÔNG dùng `.xlsx`.** File `.xlsx` hiện bị đọc ra rỗng mà **không báo lỗi**~~ — **ĐÃ SỬA ngày 06/08, xem entry đầu trang.** Từ nay `.xls` và `.xlsx` đều dùng được
    + ⚠️ **Đối chiếu CITAD lưu chung một bản cho cả phòng** — hai người cùng chấm một ngày thì ai bấm Lưu sau cùng là bản hiện hành. Bản của người trước không mất, xem lại ở tab *Lịch sử*
    + ⚠️ Extension **phải cài tay trên từng máy** và chỉ chạy trên **Chrome, Edge, Cốc Cốc** (không có Firefox, Safari). Hướng dẫn cài nằm trong file tải về
    + ⚠️ Nút *Tạo mã kết nối* có thể báo "đã tự động kết nối" nhưng Extension vẫn không gửi được — đang còn lỗi địa chỉ máy chủ. Nếu gặp, mở *Tuỳ chọn* của Extension điền tay địa chỉ và mã kết nối

- 04/08/2026 Bàn giao chứng từ - Cột "Ngày bàn giao" hiện đúng ngày nộp thật:
    + Trước đây cột **Ngày bàn giao** ở màn hình *Công việc chờ xử lý* luôn trùng khít cột *Ngày chứng từ* — chứng từ ngày 03/08 nộp ngày 04/08 vẫn báo bàn giao 03/08. Nay lấy đúng **thời điểm chuyên viên thực sự nộp** ghi trong lịch sử thao tác
    + Ô chi tiết bên phải lưới nhập nay ghi rõ **hai dòng có nhãn**: *Ngày chứng từ* và *Ngày bàn giao*. Trước đây chỉ có một dòng "Ngày ..." lấy theo thao tác gần nhất — sau khi hậu kiểm xác nhận, ngày đó bị đổi theo ngày xác nhận, nhìn tưởng là ngày nộp
    + ⚠️ Chứng từ nhập từ **trước khi hệ thống ghi lịch sử** không có ngày nộp ở bất kỳ đâu trong dữ liệu → hiện dấu `—` thay vì đoán bừa
    + Cùng cách tính với báo cáo *Tỷ lệ nộp đúng hạn*, nên hai màn hình không còn nói hai con số khác nhau

- 03/08/2026 Đối chiếu điện SWIFT - Nạp nhiều file một lúc và xuất Excel theo đúng biểu mẫu:
    + Mỗi ô chọn file nay **nhận nhiều file cùng lúc**. SAA phải xuất làm nhiều đợt trong ngày thì cứ thả hết vào đúng ô đó, hệ thống tự gộp lại trước khi đối chiếu — không phải đối chiếu từng đợt rồi tự cộng tay
    + Mỗi file vẫn báo riêng ✅/❌ và **số dòng đọc được ngay khi vừa chọn**, kèm dòng tổng cộng. Chọn nhầm thì bấm ✕ ở cạnh tên file để bỏ ra, không phải làm lại từ đầu
    + Giới hạn **10 file hoặc 100 MB mỗi ô**. Vượt quá thì báo ngay và không nạp thêm — tránh làm hệ thống hết bộ nhớ ảnh hưởng sang các màn hình khác
    + Thêm **2 nút xuất Excel theo biểu mẫu**: *Tổng hợp theo biểu mẫu* (Mẫu 04) và *Chi tiết lệch theo biểu mẫu* (Mẫu 05). File tải về đã có sẵn quốc hiệu, tiêu đề, dòng ký — in ra trình ký được ngay, không phải chép số sang mẫu Word thủ công
    + Hai biểu mẫu này tự phân loại điện về **SWIFT / IPCAS / P-HUB** dựa trên cột *Channel Process* có sẵn trong file Quản lý điện
    + ⚠️ **Cột "Chênh lệch" đổi cách tính — số sẽ khác trước.** Trước đây lấy hiệu số lượng hai bên; nay đếm đúng số điện **thực sự không khớp**. Ví dụ một loại điện có 5 bản ghi ở mỗi bên nhưng là 5 giao dịch hoàn toàn khác nhau: trước báo *Chênh lệch = 0* (trông như khớp), nay báo đúng *10*. Số mới mới là số đúng, nhưng ai đang theo dõi bằng file riêng sẽ thấy lệch với hệ thống
    + ⚠️ **Các lần đối chiếu đã lưu ở tab Lịch sử TRƯỚC đợt này vẫn giữ con số theo cách tính cũ.** Không so trực tiếp cột Chênh lệch của bản ghi cũ với bản ghi mới
    + ⚠️ Trên hai biểu mẫu mới, ô **ngày đối chiếu** đang bị điền ngày in báo cáo. Đối chiếu số liệu của ngày hôm trước thì **sửa lại ngày này bằng tay trước khi trình ký**

- 31/07/2026 Đăng nhập - Thêm lối tắt tới các hệ thống nghiệp vụ ngay ở màn hình đăng nhập:
    + Hai bên ô đăng nhập nay có **3 cụm đường dẫn**: *Thanh toán trong nước* (10 lối tắt), *Thanh toán quốc tế* (2), *Nội bộ* (4). Click là mở tab mới, không phải nhớ hay gõ lại địa chỉ
    + Mỗi lối tắt hiện **tên tiếng Việt** thay vì địa chỉ khó nhớ — ví dụ *"Hệ thống TT ĐTLNH - Cổng 12"* thay cho `http://10.0.85.100/CITAD9212`. Rê chuột lên vẫn xem được địa chỉ đầy đủ trước khi bấm
    + Các lối tắt **vẫn dùng được khi hệ thống đang lỗi** — chúng không phụ thuộc vào máy chủ của phần mềm này
    + Sửa lỗi ô *Tên đăng nhập* và *Mật khẩu* bị **tô nền xanh** khi trình duyệt tự điền mật khẩu đã lưu

- 31/07/2026 Toàn hệ thống - Đầu mỗi trang hiện rõ đang đứng ở đâu trong menu:
    + Trước đây đầu trang chỉ có tên màn hình (*"Báo cáo hậu kiểm"*), không biết mục đó nằm ở phòng nào, nhóm nào. Nay hiện cả đường đi: *Phòng KSNB & HTVH / Báo cáo / **Báo cáo hậu kiểm***
    + Áp dụng cho **tất cả các màn hình** có trong menu. Trang chủ và Quản lý User nằm ở cấp ngoài cùng nên không có phần dẫn đường

- 30/07/2026 Trang chủ - Xem hết trang không phải cuộn:
    + Trang chủ trước đây **dài hơn màn hình**, phải cuộn xuống mới thấy hết biểu đồ nộp chứng từ. Nay toàn bộ nằm vừa trong một màn hình, không còn thanh cuộn
    + Ô "Người dùng" và "Phòng nghiệp vụ" chuyển lên nằm cùng hàng với tiêu đề — vẫn đủ thông tin, gọn hơn
    + Khối **Nghỉ phép hôm nay** phóng to: số nghỉ to và rõ hơn hẳn
    + Biểu đồ nộp chứng từ thu gọn lại, cột không còn bè ra choán màn hình
    + Ô phòng Nostro rút gọn thành **"Phòng QLTK Nostro, Vostro"** để nhãn nằm một dòng như các ô khác. Tên đầy đủ trên phiếu nghỉ phép, bìa tập và báo cáo **không đổi**

- 30/07/2026 Khởi động - `start.bat` không cài lại thư viện mỗi lần đổi máy:
    + Mang thư mục dự án (chạy từ USB) sang máy khác thì mỗi lần bấm `start.bat` đều báo *".venv bị hỏng"* rồi **cài lại toàn bộ thư viện, mất vài phút**. Nay script vá môi trường tại chỗ, **khoảng 2 giây là chạy được**
    + Khi thật sự có lỗi, script **in rõ nguyên văn lỗi** ra màn hình thay vì im lặng cài lại
    + ⚠️ Máy mới cần **Python 3.10.x**. Máy chỉ có 3.11/3.12 thì vẫn phải cài lại thư viện và **cần internet**
    + Lần chạy đầu sau đợt cập nhật này sẽ cài lại thư viện **một lần** (khoảng 10 giây), sau đó bỏ qua

- 29/07/2026 Bàn giao chứng từ - Mỗi phòng chỉ còn thấy chứng từ của phòng mình:
    + Trước đây bất kỳ ai đăng nhập được đều **tải được file Excel chứa toàn bộ chứng từ của mọi phòng** — kể cả tài khoản không được cấp quyền gì trong menu Bàn giao. Xem lịch sử một chứng từ bất kỳ cũng vậy
    + Người có quyền nhập còn **xem được lưới của phòng khác và nhập chứng từ cho cán bộ phòng khác**
    + Nay ô chọn Phòng chỉ hiện phòng của chính mình; mọi thao tác trên chứng từ phòng khác đều bị chặn, kể cả khi gọi thẳng vào hệ thống mà không qua màn hình
    + **Hậu kiểm viên, Trưởng/Phó phòng KSNB và Giám đốc/Phó Giám đốc không đổi** — vẫn xem và làm việc trên mọi phòng như trước
    + ⚠️ **Cán bộ đã chuyển phòng không tự mở lại được chứng từ tháng còn ở phòng cũ.** Chứng từ vẫn nằm nguyên ở phòng cũ và không mất đi, nhưng từ nay việc nhập bù cho những tháng đó phải nhờ hậu kiểm viên làm

- 29/07/2026 Nghỉ phép - Tính đúng hạn mức khi nghỉ vắt qua giao thừa dương lịch:
    + Đơn nghỉ liền mạch bắc qua ngày 31/12 (ví dụ nghỉ từ 29/12 đến 02/01) trước đây bị **trừ trọn vào năm cũ**, kể cả những ngày thực tế đã sang năm mới. Người nghỉ bị mất oan số ngày phép đúng bằng phần vắt sang năm sau
    + Nay mỗi ngày được tính vào đúng năm của nó. Ví dụ nghỉ 29/12 → 02/01 thì 3 ngày làm việc cuối tháng 12 trừ vào năm cũ, 2 ngày đầu tháng 1 trừ vào năm mới
    + ⚠️ **Số ngày phép chuyển kỳ của một số người sẽ tăng lên sau đợt cập nhật này.** Đây là con số đúng, không phải lỗi — nhưng ai đang theo dõi số phép bằng sổ tay hoặc file Excel riêng sẽ thấy lệch với hệ thống. Cần đối chiếu lại với những người từng nghỉ bắc qua Tết dương lịch

- 29/07/2026 Nghỉ phép - Không còn trừ phép hai lần khi bấm duyệt nhanh:
    + Bấm nút duyệt hai lần liên tiếp, hoặc hai người cùng duyệt một đơn ở hai máy, trước đây có thể **trừ hạn mức phép hai lần** cho cùng một đơn
    + Nay chỉ lần bấm đầu tiên có hiệu lực, lần sau báo *"Đơn đã được xử lý bởi một yêu cầu khác, vui lòng tải lại trang"*

- 29/07/2026 Nghỉ phép - Ô "Phép còn lại" hiện đúng số:
    + Ô này trước đây tính theo công thức thâm niên, **bỏ qua hạn mức phòng Tổng hợp nhập tay và bỏ qua ngày phép chuyển từ năm trước sang**. Người xem thấy một số ở đầu trang, bấm vào tab Hạn mức phép lại thấy số khác
    + Nay hai chỗ dùng chung một cách tính, không còn lệch

- 29/07/2026 Nghỉ phép - Phiếu in ra và quyền xem đơn:
    + Phiếu nghỉ phép trước đây **luôn in cứng chức danh "TUQ. GIÁM ĐỐC / PHÓ GIÁM ĐỐC"** ở ô ký, kể cả khi người duyệt là Giám đốc. Nay in đúng chức danh của người thực sự ký
    + Nghỉ nhiều ngày liền nhau mà chỉ cách nhau thứ 7, Chủ nhật (ví dụ nghỉ thứ 6 rồi nghỉ tiếp thứ 2) nay ghi gọn *"Từ ngày… đến hết ngày…"* thay vì liệt kê rời từng ngày
    + **Người khai báo hộ nay xem lại được chính đơn mình đã khai.** Trước đây khai xong thì không mở ra xem, không xem lịch sử, cũng không tải phiếu về được

- 29/07/2026 Nghỉ phép - Số ngày trong báo cáo và bảng hạn mức:
    + Cột "Số ngày" ở Trang tổng hợp của lãnh đạo và ở file Excel báo cáo năm trước đây **đếm cả thứ 7, Chủ nhật và ngày lễ**, nên luôn cao hơn số ngày thực bị trừ vào hạn mức. Nay tính giống hệt cách trừ hạn mức
    + Công thức gợi ý khi sửa hạn mức thủ công sửa lại thành **12 ngày + 1 ngày mỗi 4 năm công tác** (trước ghi nhầm mỗi 5 năm, lệch với cách hệ thống thực sự tính)
    + Bảng Hạn mức phép thêm cột **Mã cán bộ**
    + Nhập hạn mức từ Excel: ô "Đã nghỉ" ghi số lẻ nửa ngày nay **hiện cảnh báo trước khi áp dụng**, vì hệ thống không có khái niệm nửa ngày phép và sẽ làm tròn

- 29/07/2026 Trang chủ - Bảng nghỉ hôm nay giữ nguyên cách đếm:
    + Bảng "Nghỉ phép hôm nay" **chỉ đếm đơn đã được duyệt xong**. Người vừa nộp đơn mà cấp trên chưa duyệt thì vẫn tính là đang đi làm
    + Lịch tháng trong menu Nghỉ phép thì ngược lại — có hiện cả đơn đang chờ, nhưng ở đó mỗi dòng đều kèm nhãn trạng thái nên không gây nhầm. Hai chỗ khác nhau là **có chủ đích**

- 28/07/2026 Sidebar - Việc chờ xử lý hiện ở mọi trang:
    + Số việc đang chờ trước đây chỉ hiện ở **3 trong 21 trang**. Đứng ở trang Lưu trữ thì không hề biết mình có 12 chứng từ chờ xác nhận. Nay khối **Công việc chờ xử lý** nằm đầu sidebar, theo người dùng đi khắp hệ thống, tự ẩn khi không còn việc
    + Bấm vào mở **màn hình theo dõi riêng**: chứng từ của ai, phòng nào, ai nộp, ngày nào — và bấm tiếp là nhảy thẳng tới đúng ô cần xử lý, không phải tự tìm lại
    + Khối "Công việc đang chờ" trên Trang chủ đã gỡ. Cùng một thông tin không nên có hai chỗ hiển thị, nhất là khi một chỗ bắt phải quay về Trang chủ mới thấy
    + Số trên sidebar cập nhật khi chuyển trang, **không tự làm mới tại chỗ**. Duyệt xong một đơn thì số đúng ngay ở trang kế tiếp

- 28/07/2026 Phân quyền - Chuyên viên vào được Trang chủ:
    + Chuyên viên bấm "Trang chủ" trước đây bị bật ngược về Bàn giao chứng từ — mục menu nhìn thấy nhưng không bao giờ vào được. Nay **mọi vai trò đều đăng nhập vào Trang chủ** và ra vào bình thường
    + Ô "Người dùng" trên Trang chủ đổi nhãn thành **"Nhân sự phòng"** với chuyên viên / trưởng phòng / phó phòng, vì con số họ nhận được vốn chỉ tính phòng mình — nhãn cũ dễ bị đọc nhầm thành toàn trung tâm
    + ⚠️ **Phân quyền nhóm nay có tác dụng thật với chuyên viên.** Trước đây admin cấp quyền Báo cáo / Lưu trữ / Nhân sự / Đóng tập cho một chuyên viên thì màn hình phân quyền báo đã cấp, menu cũng hiện ra, nhưng bấm vào bị đá ra mà không báo gì — do còn một lớp chặn cứng theo chức danh nằm đè lên. Đã gỡ lớp đó. **Chuyên viên không tự nhiên có thêm quyền gì**; chỉ khác là quyền đã cấp thì dùng được

- 28/07/2026
    + Khoá ký phiên đăng nhập trước đây nằm cứng trong mã nguồn
    + `start.bat` **tự sinh khoá mới** nếu file `.env` chưa có
    + Thư viện giao diện được nâng cấp

- 28/07/2026 Bảo mật - Vá thư viện xử lý file tải lên:
    + Thư viện đọc file tải lên đang dùng có **16 lỗ hổng đã biết**, trong đó 4 lỗi nghiêm trọng (1 lỗi cho phép ghi file tuỳ ý, 3 lỗi làm treo máy chủ). Đã nâng lên bản vá sạch hoàn toàn
    + Ảnh hưởng mọi chỗ tải file: nạp ZIP đối chiếu SWIFT, chấm 459901, nhập hạn mức phép, nhập DB nhân sự
    + Khoá ký phiên đăng nhập chuyển từ trong mã nguồn ra file cấu hình — trước đây ai đọc được mã nguồn đều có thể giả mạo phiên của người khác

- 28/07/2026 Toàn hệ thống - Tải nhầm file không còn làm treo trang:
    + Tải lên file `.zip` **hỏng hoặc bị đổi tên đuôi** trước đây báo "Internal Server Error" khó hiểu. Nay báo rõ: *"File tải lên không phải file .zip hợp lệ — có thể tải bị lỗi, bị cắt dở, hoặc chỉ được đổi đuôi tên thành .zip"*
    + File `.zip` **có đặt mật khẩu** nay báo *"hãy giải nén ra rồi tải lại file bên trong"* thay vì lỗi hệ thống
    + Chấm 459901: ZIP không chứa file `.csv`, hoặc file `.csv` thiếu cột, nay **báo đúng thiếu cột nào** thay vì dòng chữ "list index out of range"
    + Sửa lỗi ngầm: mỗi lần tải nhầm file, máy chủ để lại một thư mục rác không bao giờ xoá. Lặp lại nhiều lần sẽ làm đầy ổ đĩa

- 28/07/2026 Phòng KSNB&HTVH - Sửa lỗi tháng/năm không hợp lệ:
    + Gọi lưới bàn giao với tháng ngoài 1–12 (qua đường dẫn trực tiếp, không qua giao diện) làm treo trang. Nay báo lỗi rõ ràng
    + **Báo cáo bàn giao trả sai số liệu âm thầm**: hỏi "tháng 0" thì hệ thống lặng lẽ trả về số liệu **tháng hiện tại** kèm nhãn tháng hiện tại, không cảnh báo gì. Nay báo *"Tháng phải nằm trong khoảng 1–12"*
    + Lịch nghỉ phép cũng chặn năm ngoài 2000–2100 (trước đó mới chặn tháng)

- 28/07/2026 Giao diện - Chữ dễ đọc hơn và thống nhất phông:
    + Chữ ghi chú màu xám nhạt trên toàn hệ thống (**72 chỗ**) đổi sang đậm hơn một bậc — trước đây độ tương phản chỉ đạt 2,5 trên chuẩn tối thiểu 4,5, khó đọc với người phải nhìn bảng số liệu cả ngày
    + **Phông chữ Inter nay dùng cho cả 21 trang**. Trước đây chỉ trang Đăng nhập và Đổi mật khẩu có, 19 trang còn lại rơi về phông mặc định — đăng nhập một kiểu chữ, vào việc lại một kiểu khác
    + Thống nhất nhãn trạng thái chứng từ: "Bị từ chối" ở màn Bàn giao và "Từ chối" ở màn Nghỉ phép nay dùng chung một chữ **"Từ chối"**

- 28/07/2026 Kỹ thuật - Dọn nền
    + Nâng thư viện giao diện lên bản mới (vượt qua một mốc thay đổi lớn). Đã đối chiếu từng dòng CSS của hai bản để chắc chắn **không có gì đổi hình dạng** — 70 khung thẻ trong hệ thống giữ nguyên
    + Sửa bẫy trong hệ thống nâng cấp cơ sở dữ liệu: có 18 câu lệnh trỏ sai tên bảng và **thất bại im lặng** mỗi lần khởi động. Chưa gây hại, nhưng người viết tính năng tiếp theo mà chép nhầm mẫu này thì cột dữ liệu sẽ không được thêm mà không ai biết
    + Cảnh báo khi khởi động nếu máy chủ đang mở ra mạng nội bộ mà chưa cấu hình đúng — gồm cả việc **trang liệt kê toàn bộ 144 cửa giao tiếp đang mở công khai** cho ai vào được cổng 8000
    + Sửa 4 chỗ tài liệu hướng dẫn nội bộ mô tả sai kiến trúc (chỉ tới file không tồn tại, sai tên bảng dữ liệu)
    + Thêm `frontend/ui_kit.py` — gom màu, nhãn trạng thái, khung chờ về một chỗ. Trước đây nhãn trạng thái được định nghĩa ở 3 nơi theo 3 cách khác nhau

- 27/07/2026 Giao diện - Nới rộng vùng nội dung trên màn hình nhỏ:
    + Máy có màn hình rộng từ 1440px trở xuống (máy trạm 1366×768) khi mở phần mềm sẽ **tự thu gọn sidebar**, vùng xem bảng rộng thêm khoảng 184px. Ai đã tự bấm nút thu gọn/mở rộng một lần thì phần mềm nghe theo lựa chọn đó, không tự đổi nữa
    + Bảng rộng hơn màn hình nay **kéo ngang xem được**. Trước đây phần vượt khung bị cắt mất, không có cách nào kéo ra xem
    + Sửa lỗi tính chiều rộng làm mọi trang thừa ra một khoảng bằng đúng bề rộng thanh cuộn dọc

- 27/07/2026 Giao diện - Sidebar (thu gọn/mở rộng):
    + Sidebar **chỉ đóng/mở bằng nút ở góc trên cùng bên trái**. Trước đây click vào mục menu thì sidebar tự thu lại, còn click vùng trống khi đang thu gọn lại tự mở ra — cùng một thao tác cho hai kết quả ngược nhau tuỳ chỗ bấm
    + Click mục menu giờ chỉ chuyển trang, không đụng tới sidebar. Trạng thái đóng/mở giữ nguyên khi chuyển trang
    + Icon trên nút đổi theo trạng thái để biết bấm sẽ đóng hay mở

- 27/07/2026 Phòng Thanh toán - Gom menu Đối chiếu:
    + **Chấm 459901** và **Đối chiếu Song phương** chuyển thành 2 mục con của menu mới **Đối chiếu** (hover ra flyout cấp 2, giống nhóm "Báo cáo" bên KSNB). Phân quyền theo nhóm giữ nguyên (`menu.cham_459901`, `menu.doi_chieu_song_phuong`); nhóm "Đối chiếu" tự ẩn nếu user không có quyền cả 2 mục
    + Tiện thể fix: bấm mục trong menu con cấp 2 nay cũng tự thu gọn sidebar như mục cấp 1 (trước đó bị sót, ảnh hưởng cả 2 nhóm "Báo cáo")

- 22/07/2026 Quản lý User - Nhóm & phân cấp Quản trị viên:
    + Gom các tài khoản quản trị vào **nhóm "Quản trị viên"** trong danh sách Quản lý User Admin **không thuộc phòng nào**: tạo/sửa admin sẽ ẩn ô chọn Phòng, `department_id` để trống
    + Tách quyền quản trị thành **2 cấp**:
        • **Quản trị viên cấp 1** (role cũ `admin`, chỉ đổi nhãn): toàn quyền như trước
        • **Quản trị viên cấp 2** (`admin_l2`, mới): quyền hạn cấu hình qua **Phân quyền theo nhóm** (như các role thường), không mặc định all-access
    + **Chống leo thang quyền**: cấp 2 không được tạo/sửa/xóa hay nâng ai lên cấp 1 — chặn ở cả giao diện (ẩn tùy chọn "cấp 1" khỏi dropdown, khóa nút thao tác trên hàng cấp 1) lẫn backend (trả 403)

- 21/07/2026 Giao diện - Sidebar:
    + Fix nút thu gọn menu (góc trên trái): lỗi thu gọn được nhưng bấm lần nữa không mở lại. 

- 20/07/2026 Phòng KSNB&HTVH - Lưu trữ (sửa số chứng từ trên bảng):
    + Tra cứu lưu trữ cho phép chỉnh trực tiếp cột "Số chứng từ": nhập số vào ô trống để **thêm một tập** cho ngày đó, sửa số hiện có về **0 để xoá tập**. Sau khi lưu, "Số tập" và dòng tổng tự cộng lại (backend đếm lại số tập của nhóm)
    + Cột "Số chứng từ" mở rộng tối thiểu **5 cột** (luôn chừa ô trống để nhập thêm)
    + *Đánh đổi*: tập thêm tay không gắn chứng từ thật (chỉ ngày + số tờ); xoá tập có thể làm lệch số thứ tự "x/tổng" khi in bìa các tập còn lại — chấp nhận vì đây là màn hình chỉnh tay của HKV, tổng số tập đã được tính lại đúng

- 20/07/2026 Toàn hệ thống - Nghỉ phép (Big update):
    + **Nghỉ thai sản / bảo hiểm**: không trừ vào hạn mức phép năm; chọn khoảng ngày bằng lịch cuộn (calendar dropdown); template phiếu hỗ trợ điều kiện 2 năm
    + **Nhập hạn mức phép hàng loạt từ file Excel**: xem trước → áp dụng → hoàn tác (rollback). Cột "Đã nghỉ" tạo bản ghi tổng hợp thay vì ghi từng trường mồ côi
    + **Carry-over**: chuyển tiếp ngày phép chưa dùng của năm trước sang Q1 năm sau
    + **Khai báo hộ** (nhập đơn thay cán bộ khác) + ngày nghỉ lẻ không liên tục (`spread_dates`)
    + Bảng "Nghỉ phép hôm nay" trên Trang chủ, tách theo từng phòng
    + Thống nhất **một nguồn sự thật** cho "số ngày đã dùng": loại thai sản/bảo hiểm khỏi hạn mức phép năm nhất quán ở mọi nơi (thống kê, xuất quota, phiếu) — trước đây mỗi chỗ tính một kiểu
    + Bảng **ủy quyền Giám đốc** chia cột rõ ràng; hoàn thiện luồng duyệt bước Giám đốc (GĐ/PGĐ theo ủy quyền còn hiệu lực)
    + Phân quyền admin (403 đúng chỗ), thêm `leaves.schedule` vào danh mục phân quyền nhóm
    + Xử lý **17 lỗi** phát hiện qua rà soát nghỉ phép

- 20/07/2026 Toàn hệ thống - Nhật ký thao tác (audit log):
    + Ghi tập trung mọi thao tác thay đổi dữ liệu (POST/PUT/PATCH/DELETE) vào bảng `audit_logs` qua middleware `AuditMiddleware` — mỗi request để lại 1 dòng: ai thực hiện, phương thức, đối tượng, kết quả HTTP, IP, thời gian. Không phải rải lệnh ghi log ở từng endpoint
    + Thêm menu "Nhật ký hệ thống" (trang `audit-logs`): lọc theo phương thức, tìm theo tên cán bộ / đối tượng / nội dung, phân trang
    + Tự dọn `audit_logs` cũ hơn 365 ngày

- 20/07/2026 Toàn hệ thống - Cảnh báo lệch giờ máy chủ (NTP):
    + Khi khởi động, so đồng hồ máy chủ với nguồn giờ chuẩn NTP; lệch quá ngưỡng thì ghi CẢNH BÁO vào log. Chỉ cảnh báo, KHÔNG tự sửa giờ (đồng bộ giờ là việc của hệ điều hành / domain), phục vụ độ tin cậy của nhật ký
    + Cấu hình qua `.env`: `NTP_ENABLED`, `NTP_SERVER`, `NTP_TIMEOUT_SEC`, `NTP_DRIFT_THRESHOLD_SEC`. Mạng nội bộ cô lập: trỏ về NTP nội bộ hoặc đặt `NTP_ENABLED=false` để tắt

- 20/07/2026 Phòng KSNB&HTVH - Lưu trữ (tổng hợp cả năm):
    + Thêm bảng tổng hợp lưu trữ theo năm: số tờ / số tập theo từng phòng nghiệp vụ × 12 tháng (endpoint `/storage-summary`). Dùng lại đúng hàm dựng bảng chi tiết nên số liệu luôn khớp với màn hình tra cứu chi tiết

- 20/07/2026 Trang chủ - Biểu đồ bàn giao chứng từ:
    + Thay bảng số liệu "đúng hạn / muộn theo phòng" bằng biểu đồ cột nhóm (4 phòng: Thanh toán, Kế toán, Swift, NosVos × 2 cột đúng hạn/nộp muộn)
    + Ô thống kê "Người dùng" bỏ đếm quản trị viên; "Phòng nghiệp vụ" bỏ đếm Ban Giám đốc

- 20/07/2026 Phòng KSNB&HTVH - Bàn giao chứng từ (giao diện lưới):
    + Cột ngày co giãn để vừa bề ngang màn hình, chỉ cuộn ngang khi hẹp hơn mức tối thiểu; căn header khớp cột nhập bằng `box-sizing:border-box`

- 20/07/2026 Phòng KSNB&HTVH - Bàn giao chứng từ (cán bộ chuyển phòng):
    + Cán bộ chuyển phòng nghiệp vụ vẫn hiển thị đúng phòng cũ cho các tháng **trước** ngày chuyển, phòng mới **từ** ngày chuyển trở đi. Trước đây lưới bàn giao lọc theo phòng hiện tại của cán bộ nên toàn bộ chứng từ cũ "biến mất" khỏi phòng cũ ngay khi họ đổi phòng
    + Thêm bảng lịch sử đổi phòng (`staff_department_history`): mỗi lần quản trị viên đổi phòng cho cán bộ sẽ ghi một mốc theo ngày đổi. Chứng từ được định tuyến về đúng phòng theo **ngày giao dịch** — nhập bù chứng từ tháng cũ cho cán bộ đã chuyển phòng vẫn vào đúng phòng cũ (không rơi nhầm sang phòng mới)
    + Lưới bàn giao hiện cán bộ **từng thuộc** phòng đó trong tháng để nhập bù (kể cả người đã chuyển đi phòng khác)
    + Tự backfill lịch sử phòng cho toàn bộ cán bộ hiện có khi khởi động; báo cáo/xuất Excel/gom tập vốn đã dùng phòng đóng băng trong phiếu nên không đổi
    + *Lưu ý vận hành*: chuyên viên bị khóa ô chọn phòng (chỉ phòng hiện tại) → nhập bù cho cán bộ đã chuyển phòng do HKV / cán bộ phòng cũ chọn phòng cũ + tháng rồi nhập hộ

- 16/07/2026 Phòng Thanh toán - Đối chiếu Song phương (module mới):
    + Định tuyến lệnh IPCAS phục vụ đối chiếu song phương: upload file ZIP (mã hoá AES-256) chứa dữ liệu IPCAS, xử lý bất đồng bộ, theo dõi tiến độ real-time
    + Phân loại mỗi dòng theo 4 ngân hàng (Vietinbank 201, BIDV 202, Vietcombank 203, MBBank 311) × 2 chiều: ĐẾN (`CRAMOUNT=0`) / ĐI (`DRAMOUNT=0`) → xuất 8 file CSV
    + Thêm menu "Đối chiếu Song phương" cho Phòng Thanh toán; phân quyền riêng theo nhóm (`menu.doi_chieu_song_phuong`, `doi_chieu_song_phuong.process`)
    + Thêm thư viện `pyzipper` (đọc ZIP mã hoá AES-256)

- 16/07/2026 Cấu hình - Nạp biến môi trường:
    + `load_dotenv(..., override=True)` ở `config.py`, `api_client.py`, `frontend/main.py`, `run.py` — ép `.env` ghi đè biến môi trường sẵn có của hệ thống, tránh trường hợp máy đã set biến cũ khiến `.env` bị bỏ qua khi chuyển sang máy mới

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
