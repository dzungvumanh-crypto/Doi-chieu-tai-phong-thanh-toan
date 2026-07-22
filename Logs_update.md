# Logs cập nhật hệ thống

Ghi lại từng đợt push lên GitHub / deploy sang máy chính (qua `deploy.bat`). Entry mới nhất ở trên cùng.

---

- 22/07/2026 Quản lý User - Nhóm & phân cấp Quản trị viên:
    + Gom các tài khoản quản trị vào **nhóm "Quản trị viên"** trong danh sách Quản lý User (hiển thị như "Ban Giám đốc", các phòng). Admin **không thuộc phòng nào**: tạo/sửa admin sẽ ẩn ô chọn Phòng, `department_id` để trống
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
