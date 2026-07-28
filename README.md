# Hệ thống của TTTT - Agribank

---

## Cài đặt

### 1. Yêu cầu
- Python 3.10+
- Windows / Linux / macOS

### 2. Tạo môi trường ảo và cài thư viện

```bash
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Khởi tạo database

```bash
python init_db.py
```

Kết quả:
```
✓ Database đã khởi tạo thành công!
Tài khoản đăng nhập:
  Admin : admin / Admin@2024!
```
> ⚠️ Đổi mật khẩu ngay sau lần đăng nhập đầu tiên.

### 4. Cấu hình `.env` (bắt buộc)

Copy `.env.example` thành `.env` rồi điền hai khoá bí mật — **thiếu là hệ thống không khởi động**:

```bash
python -c "import secrets; print(secrets.token_hex(32))"   # chạy 2 lần, lấy 2 giá trị khác nhau
```

```ini
SECRET_KEY=<giá trị 1>       # khoá ký JWT (backend)
STORAGE_SECRET=<giá trị 2>   # khoá ký cookie phiên (frontend)
```

> Trên Windows, `start.bat` **tự sinh cả hai** nếu `.env` chưa có hoặc còn thiếu — không cần làm tay.
> Đổi `STORAGE_SECRET` sẽ đăng xuất toàn bộ người dùng đang đăng nhập một lần.

Chạy thật trên mạng nội bộ thì đặt thêm (xem mục [Truy cập LAN](#truy-cập-lan-nhiều-người-dùng)):

```ini
ENV=production                                  # tắt /docs, /redoc
ALLOWED_ORIGINS=http://192.168.1.100:8080       # IP thật của máy chủ
```

### 5. Chạy hệ thống

```bash
python run.py
```

Truy cập:
- **Giao diện web**: http://localhost:8080
- **API docs**: http://localhost:8000/docs
- **Từ máy khác trong LAN**: http://[IP-máy-chủ]:8080

---

## Cấu trúc hệ thống

```
├── backend/
│   ├── main.py              # FastAPI app + schema migration khi khởi động
│   ├── database.py          # SQLite engine (WAL mode, FK via PRAGMA)
│   ├── core/
│   │   ├── config.py        # Cấu hình (SECRET_KEY, DATABASE_URL, NTP...)
│   │   ├── security.py      # JWT + bcrypt
│   │   ├── deps.py          # FastAPI dependencies (RBAC)
│   │   ├── sessions.py      # Session in-memory
│   │   ├── audit_middleware.py # Ghi nhật ký thao tác tập trung → audit_logs
│   │   └── rate_limit.py    # Rate limiting đăng nhập
│   ├── api/
│   │   ├── auth.py          # Đăng nhập / đăng xuất / đổi mật khẩu
│   │   ├── staff.py         # Quản lý cán bộ
│   │   ├── departments.py   # Phòng ban
│   │   ├── groups.py        # Nhóm cán bộ
│   │   ├── handovers.py     # Phiếu bàn giao chứng từ
│   │   ├── bundles.py       # Gom tập + in bìa
│   │   ├── leaves.py        # Nghỉ phép (workflow 3 bước)
│   │   ├── delegations.py   # Ủy quyền Giám đốc
│   │   ├── dashboard.py     # Tổng quan thống kê
│   │   ├── reports.py       # Báo cáo hậu kiểm
│   │   ├── handover_reports.py # Báo cáo bàn giao chứng từ (đúng hạn/quá hạn)
│   │   ├── th_reports.py    # Báo cáo tổng hợp (phòng TH)
│   │   ├── swift_recon.py   # Đối chiếu điện SWIFT (phòng Swift)
│   │   ├── duty_schedule.py # Lịch trực
│   │   ├── duty_staff.py    # Cán bộ trực
│   │   ├── duty_constraints.py # Ràng buộc lịch trực
│   │   ├── duty_stats.py    # Thống kê lịch trực
│   │   ├── duty_export.py   # Xuất lịch trực
│   │   ├── cham459901.py    # Phân loại bút toán TK 459901
│   │   ├── doi_chieu_song_phuong.py # Đối chiếu song phương (định tuyến lệnh IPCAS)
│   │   ├── logs.py          # Nhật ký hệ thống (admin)
│   │   └── holidays.py      # Quản lý ngày lễ (admin)
│   └── services/
│       ├── bundle_service.py       # Thuật toán gom tập (max 350 tờ)
│       ├── cover_service.py        # Tạo bìa Word (docxtpl)
│       ├── report_service.py       # Xuất báo cáo Excel
│       ├── handover_report_service.py # Tính chứng từ nộp đúng hạn / quá hạn
│       ├── th_report_service.py    # Xuất báo cáo tổng hợp (phòng TH)
│       ├── backup_service.py       # Backup SQLite tự động
│       ├── time_sync.py            # Cảnh báo lệch giờ máy chủ so NTP (không tự sửa)
│       ├── cham459901_service.py   # Xử lý ZIP + phân loại bút toán 459901
│       ├── doi_chieu_song_phuong_service.py # Định tuyến lệnh IPCAS theo NH + chiều → 8 CSV
│       ├── swift_recon/            # Đối chiếu điện SWIFT (parse, so khớp, export Excel)
│       └── duty_*                  # Xếp lịch trực, ràng buộc, thống kê, xuất file (6 module)
├── frontend/
│   ├── main.py              # NiceGUI entry point
│   ├── shared.py            # Layout chung (sidebar, header, helpers)
│   ├── ui_kit.py            # Nguồn sự thật: màu, trạng thái, khung chờ, font
│   ├── api_client.py        # httpx wrapper → backend
│   └── pages/
│       ├── login.py         # Đăng nhập
│       ├── dashboard.py     # Tổng quan
│       ├── pending_work.py  # Màn hình theo dõi việc chờ xử lý (/pending/<loại>)
│       ├── staff.py         # Quản lý cán bộ
│       ├── groups.py        # Quản lý nhóm
│       ├── group_features.py # Phân quyền theo nhóm
│       ├── handovers.py     # Bàn giao chứng từ
│       ├── bundles.py       # Gom tập + in bìa
│       ├── storage.py       # Lưu trữ tập (số hộp, vị trí kệ)
│       ├── leaves.py        # Nghỉ phép
│       ├── duty_schedule.py # Lịch trực
│       ├── cham_459901.py   # Phân loại bút toán TK 459901
│       ├── doi_chieu_song_phuong.py # Đối chiếu song phương (định tuyến lệnh IPCAS)
│       ├── reports.py       # Báo cáo hậu kiểm
│       ├── handover_reports.py # Báo cáo bàn giao chứng từ (đúng hạn/quá hạn)
│       ├── th_reports.py    # Báo cáo tổng hợp
│       ├── swift_recon.py   # Đối chiếu điện SWIFT (phòng Swift)
│       ├── user_management.py # Quản lý tài khoản (admin)
│       ├── login_logs.py    # Nhật ký đăng nhập (admin)
│       ├── audit_logs.py    # Nhật ký thao tác — lịch sử ghi dữ liệu (admin)
│       ├── logs.py          # Nhật ký lỗi & cảnh báo (admin)
│       └── change_password.py # Đổi mật khẩu
├── templates/
│   ├── bia_mau_goc.docx             # Mẫu bìa tập chứng từ
│   └── don_xin_nghi_phep_tpl.docx  # Template phiếu nghỉ phép
├── data/
│   └── ksnb.db             # SQLite database (tự tạo khi chạy lần đầu)
├── logs/
│   └── app.log             # Log xoay vòng (5 MB × 3 file)
├── init_db.py               # Khởi tạo DB + seed data
├── run.py                   # Launcher (chạy backend + frontend song song)
└── requirements.txt
```

---

## Chức năng

### Module Nhân sự & Tài khoản
- Quản lý cán bộ theo phòng ban, vai trò (8 vai trò — xem bảng RBAC)
- Quản lý nhóm cán bộ và phân quyền tính năng theo nhóm
- Dashboard tổng quan: KPI người dùng & phòng nghiệp vụ, bảng nghỉ phép hôm nay theo phòng, biểu đồ cột tỷ lệ nộp chứng từ đúng hạn/muộn theo 4 phòng (chọn tháng/năm để xem). **Mọi vai trò đều vào Trang chủ sau khi đăng nhập**
- **Công việc chờ xử lý**: khối ở đầu sidebar, hiện trên mọi trang — số chứng từ chờ xác nhận và đơn nghỉ phép chờ duyệt của **chính người đang đăng nhập**; bấm vào mở màn hình theo dõi `/pending/<loại>` có đủ chi tiết và link nhảy thẳng tới ô cần xử lý
- **Nhật ký thao tác** (audit log): middleware ghi tập trung mọi request thay đổi dữ liệu (POST/PUT/PATCH/DELETE) vào bảng `audit_logs` — ai, làm gì, kết quả HTTP, IP, thời gian; lọc theo phương thức, tìm kiếm, phân trang; tự dọn sau 365 ngày
- Nhật ký đăng nhập và nhật ký lỗi/cảnh báo hệ thống (admin xem, lọc theo user/thời gian)

### Module Nghỉ phép
- Cán bộ tạo đơn xin nghỉ (phép năm, ốm, việc riêng, khác)
- Workflow duyệt 3 bước: **KSV → Tổng hợp → Giám đốc**
- Ủy quyền Giám đốc: GĐ có thể ủy quyền cho PGĐ trong khoảng thời gian xác định
- Tải phiếu nghỉ phép dạng `.docx` đúng mẫu
- Theo dõi quota phép năm (hạn ngạch / đã dùng); chuyển tiếp ngày phép chưa dùng năm trước sang Q1
- Nghỉ thai sản / bảo hiểm (không trừ vào hạn mức phép năm), chọn khoảng ngày bằng lịch cuộn
- Nhập hạn mức phép hàng loạt từ file Excel (xem trước / áp dụng / hoàn tác)
- Khai báo hộ; ngày nghỉ lẻ không liên tục (`spread_dates`)
- Bảng nghỉ phép hôm nay trên Trang chủ theo từng phòng
- Resubmit đơn bị từ chối; huỷ đơn đang chờ hoặc đã duyệt

### Module Chứng từ Hậu kiểm
- **Bàn giao**: GDV nhập số tờ theo ngày, HKV/KSV xác nhận từng ô
  - *Cán bộ chuyển phòng*: chứng từ hiển thị theo phòng tại **ngày giao dịch** — trước ngày chuyển ở phòng cũ, từ ngày chuyển ở phòng mới (lịch sử đổi phòng lưu ở bảng `staff_department_history`). Nhập bù chứng từ tháng cũ cho cán bộ đã chuyển vẫn vào đúng phòng cũ
- **Gom tập tự động**:
  - Max 350 tờ/tập
  - (user, ngày) không bị tách sang tập khác
  - Nếu 1 ngày > 350 tờ → chia 2 tập cân bằng
- **In bìa**: Tạo file `.docx` đúng format mẫu (2-column layout)
- **Lưu trữ**: Ghi số hộp, vị trí kệ; tra cứu theo phòng/thời gian; bảng tổng hợp cả năm (số tờ/số tập theo phòng × 12 tháng); sửa số chứng từ ngay trên bảng — nhập vào ô trống để thêm tập, sửa về 0 để xoá tập, số tập/tổng tự cập nhật
- **Báo cáo** (menu con):
  - *Báo cáo hậu kiểm*: Xuất Excel tổng hợp theo phòng
  - *Báo cáo bàn giao chứng từ*: Số chứng từ nộp đúng hạn / quá hạn theo phòng; chi tiết cán bộ nào nộp chậm chứng từ ngày nào, chậm bao nhiêu ngày làm việc
- **Báo cáo tổng hợp**: Báo cáo riêng cho phòng Tổng hợp
- **Lịch sử thay đổi**: Ghi log mọi thao tác xác nhận, mượn, trả chứng từ

### Module Lịch trực
- Xếp lịch trực tự động cho phòng Thanh toán
- Quản lý cán bộ trực, ràng buộc lịch trực (ngày không trực, giới hạn ca)
- Thống kê số ca trực theo cán bộ, theo tháng
- Xuất lịch trực ra file

### Module Đối chiếu điện SWIFT (phòng Swift)
- Đối chiếu điện SAA ↔ Màn hình quản lý điện, 2 chiều: **Điện đến** / **Điện đi**
- Xuất Excel 3 loại mỗi chiều: Tổng hợp, Chi tiết lệch, Bản ghi đang lọc
- Tab **Lịch sử đối chiếu** — lưu vào bảng `swift_recon_history` trong DB chung
- Phân quyền riêng theo nhóm (`menu.swift_recon`)

### Module Chấm 459901
- Phân loại bút toán tài khoản trung gian 459901 dành cho phòng Thanh toán
- Menu: **Phòng Thanh toán → Đối chiếu → Chấm 459901**
- Upload file ZIP chứa dữ liệu giao dịch; xử lý bất đồng bộ (~65s)
- Xuất 3 file Excel: **Huỷ**, **Đi**, **Khác** theo kết quả phân loại
- Phân quyền riêng theo nhóm (`menu.cham_459901`, `cham_459901.process`)

### Module Đối chiếu Song phương
- Định tuyến lệnh IPCAS phục vụ đối chiếu song phương tại phòng Thanh toán
- Menu: **Phòng Thanh toán → Đối chiếu → Đối chiếu Song phương**
- Upload file ZIP (mã hóa AES-256) chứa dữ liệu IPCAS; xử lý bất đồng bộ, theo dõi tiến độ real-time
- Phân loại mỗi dòng theo **4 ngân hàng** (Vietinbank 201, BIDV 202, Vietcombank 203, MBBank 311) × **2 chiều**: **ĐẾN** (`CRAMOUNT=0`) / **ĐI** (`DRAMOUNT=0`) → xuất **8 file CSV**
- Phân quyền riêng theo nhóm (`menu.doi_chieu_song_phuong`, `doi_chieu_song_phuong.process`)

---

## Phân quyền (RBAC)

| Vai trò | Mô tả |
|---|---|
| `admin` | **Quản trị viên cấp 1** — toàn quyền hệ thống, quản lý tài khoản & phân quyền nhóm |
| `admin_l2` | **Quản trị viên cấp 2** — quyền theo nhóm chức năng được gán; không thuộc phòng nào; không được tạo/sửa/xóa tài khoản cấp 1 |
| `hau_kiem_vien` | Quyền hậu kiểm (xác nhận, gom tập, in bìa) |
| `giam_doc` | Duyệt nghỉ phép bước cuối; xem toàn bộ màn hình |
| `pho_giam_doc` | Duyệt thay GĐ khi có ủy quyền còn hiệu lực |
| `truong_phong` | Duyệt nghỉ phép bước KSV; nhập bàn giao |
| `pho_phong` | Duyệt nghỉ phép bước KSV; nhập bàn giao |
| `chuyen_vien` | Nhập bàn giao, xem dữ liệu phòng mình |

**Phân cấp**: `admin > admin_l2 > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien`

> `admin_l2` (Quản trị viên cấp 2) hiển thị chung nhóm "Quản trị viên" như cấp 1, nhưng quyền hạn được cấu hình qua **Phân quyền theo nhóm** thay vì all-access.

### Menu sidebar
Menu nhóm theo phòng ban, hover để mở flyout bên phải. Một phòng **chỉ hiện khi user có ít nhất 1 chức năng** của phòng đó (`menu.<key>`) — phòng chưa có chức năng hoặc user không được cấp quyền nào thì ẩn hoàn toàn, không hiện tên phòng rỗng. Riêng `chuyen_vien` dùng menu phẳng (Bàn giao chứng từ, Nghỉ phép).

Trên cùng là khối **Công việc chờ xử lý**, tự ẩn khi không có việc nào. Dưới nó là **Trang chủ** — hiện với mọi vai trò và mọi vai trò đều vào được.

> **Phân quyền màn hình đi theo nhóm quyền, không theo vai trò.** Các trang Báo cáo, Lưu trữ, Báo cáo bàn giao, Nhân sự, Đóng tập chỉ kiểm `menu.<key>` — giống hệt luật mà backend (`require_feature`) và sidebar đang dùng. Trước đây các trang này còn một lớp chặn cứng theo vai trò chạy **trước** lớp nhóm quyền, khiến quyền admin cấp cho `chuyen_vien` qua nhóm không có tác dụng mà không báo gì. Lớp đó đã gỡ; chỉ `/user-management` còn giữ vì là trang duy nhất không gắn mã feature nào.

**Thu gọn / mở rộng**: chỉ bằng nút ở góc trên cùng bên trái. Click vào mục menu chỉ điều hướng, không đổi trạng thái sidebar. Icon nút phản ánh trạng thái hiện tại (`menu_open` khi đang mở, `menu` khi đang thu gọn). Lựa chọn được lưu trong `localStorage` và giữ nguyên khi chuyển trang.

Máy có màn hình rộng **≤ 1440px** (máy trạm 1366×768) mặc định vào đã thu gọn sẵn, nhường thêm ~184px cho vùng nội dung. Chỉ áp dụng khi user chưa từng bấm nút — đã bấm một lần thì lựa chọn đó được tôn trọng ở mọi màn hình.

### Vùng nội dung
Giao diện thiết kế cho **máy trạm desktop**, không có breakpoint mobile. Vùng nội dung rộng `calc(100% - 16rem)` (hoặc `- 4.5rem` khi sidebar thu gọn) và cho **cuộn ngang** khi bảng vượt khung — không cắt bớt nội dung.

---

## Quy trình duyệt nghỉ phép

```
[Cán bộ tạo đơn]
       ↓
pending_ksv  →  (Trưởng/Phó phòng duyệt)
       ↓
pending_tong_hop  →  (Phòng TH chọn GĐ/PGĐ và chuyển lên)
       ↓
pending_gd  →  (GĐ hoặc PGĐ nếu có ủy quyền còn hiệu lực)
       ↓
approved / rejected / cancelled
```

---

## Tập số (số La Mã)

| Trường hợp | Ký hiệu |
|---|---|
| 1 tập duy nhất | I/I |
| Chia 2 tập | I/II, II/II |
| Chia 3 tập | I/III, II/III, III/III |

---

## Backup tự động

Database SQLite được backup tự động vào thư mục `data/backups/`. Lịch backup cấu hình trong `backend/services/backup_service.py`.

---

## Truy cập LAN (nhiều người dùng)

Mở firewall port 8080 và 8000:

```bash
# Windows
netsh advfirewall firewall add rule name="TTTT" dir=in action=allow protocol=TCP localport=8080,8000
```

Người dùng khác truy cập: `http://[IP-máy-chủ]:8080`

Đặt trong `.env` — quên là máy khác bị CORS chặn, và trang liệt kê toàn bộ endpoint bị mở công khai:

```ini
ALLOWED_ORIGINS=http://192.168.1.100:8080    # thay bằng IP thật, nhiều giá trị cách nhau dấu phẩy
ENV=production                               # tắt /docs và /redoc
```

Backend tự **cảnh báo trong log khi khởi động** nếu đang lắng nghe trên mạng mà hai biến này chưa đặt đúng.

---

## Lệnh thường dùng

```bash
# Cài thư viện
pip install -r requirements.txt

# Khởi tạo DB lần đầu
python init_db.py

# Chạy toàn bộ hệ thống
python run.py

# Chạy backend riêng (development)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Chạy frontend riêng
python frontend/main.py
```
