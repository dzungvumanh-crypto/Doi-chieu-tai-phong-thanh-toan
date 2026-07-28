# Logs cập nhật hệ thống

Ghi lại từng đợt push lên GitHub / deploy sang máy chính (qua `deploy.bat`). Entry mới nhất ở trên cùng.

---

- 28/07/2026 ⚠️ LƯU Ý KHI DEPLOY ĐỢT NÀY:
    + **Người dùng sẽ bị đăng xuất một lần** sau khi khởi động lại. Không tránh được — khoá ký phiên đăng nhập trước đây nằm cứng trong mã nguồn, nay chuyển ra file cấu hình. Nên deploy ngoài giờ cao điểm
    + `start.bat` **tự sinh khoá mới** nếu file `.env` chưa có — không phải làm gì thủ công trên máy chính lẫn máy test
    + Thư viện giao diện được nâng cấp nên lần chạy đầu `start.bat` sẽ mất thêm ít phút để cài lại

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

- 28/07/2026 Kỹ thuật - Dọn nền (không thấy được nhưng cần biết):
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
