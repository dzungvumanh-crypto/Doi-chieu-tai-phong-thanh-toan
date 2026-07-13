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

### 4. Chạy hệ thống

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
│   │   ├── config.py        # Cấu hình (SECRET_KEY, DATABASE_URL...)
│   │   ├── security.py      # JWT + bcrypt
│   │   ├── deps.py          # FastAPI dependencies (RBAC)
│   │   ├── sessions.py      # Session in-memory
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
│   │   ├── logs.py          # Nhật ký hệ thống (admin)
│   │   └── holidays.py      # Quản lý ngày lễ (admin)
│   └── services/
│       ├── bundle_service.py       # Thuật toán gom tập (max 350 tờ)
│       ├── cover_service.py        # Tạo bìa Word (docxtpl)
│       ├── report_service.py       # Xuất báo cáo Excel
│       ├── handover_report_service.py # Tính chứng từ nộp đúng hạn / quá hạn
│       ├── th_report_service.py    # Xuất báo cáo tổng hợp (phòng TH)
│       ├── backup_service.py       # Backup SQLite tự động
│       ├── cham459901_service.py   # Xử lý ZIP + phân loại bút toán 459901
│       ├── swift_recon/            # Đối chiếu điện SWIFT (parse, so khớp, export Excel)
│       └── duty_*                  # Xếp lịch trực, ràng buộc, thống kê, xuất file (6 module)
├── frontend/
│   ├── main.py              # NiceGUI entry point
│   ├── shared.py            # Layout chung (sidebar, header, helpers)
│   ├── api_client.py        # httpx wrapper → backend
│   └── pages/
│       ├── login.py         # Đăng nhập
│       ├── dashboard.py     # Tổng quan
│       ├── staff.py         # Quản lý cán bộ
│       ├── groups.py        # Quản lý nhóm
│       ├── group_features.py # Phân quyền theo nhóm
│       ├── handovers.py     # Bàn giao chứng từ
│       ├── bundles.py       # Gom tập + in bìa
│       ├── storage.py       # Lưu trữ tập (số hộp, vị trí kệ)
│       ├── leaves.py        # Nghỉ phép
│       ├── duty_schedule.py # Lịch trực
│       ├── cham_459901.py   # Phân loại bút toán TK 459901
│       ├── reports.py       # Báo cáo hậu kiểm
│       ├── handover_reports.py # Báo cáo bàn giao chứng từ (đúng hạn/quá hạn)
│       ├── th_reports.py    # Báo cáo tổng hợp
│       ├── swift_recon.py   # Đối chiếu điện SWIFT (phòng Swift)
│       ├── user_management.py # Quản lý tài khoản (admin)
│       ├── login_logs.py    # Nhật ký đăng nhập (admin)
│       ├── logs.py          # Nhật ký hệ thống (admin)
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
- Quản lý cán bộ theo phòng ban, vai trò (7 vai trò — xem bảng RBAC)
- Quản lý nhóm cán bộ và phân quyền tính năng theo nhóm
- Dashboard tổng quan: số liệu bàn giao, tập chứng từ, nghỉ phép
- Nhật ký đăng nhập và nhật ký thao tác hệ thống (admin xem, lọc theo user/thời gian)

### Module Nghỉ phép
- Cán bộ tạo đơn xin nghỉ (phép năm, ốm, việc riêng, khác)
- Workflow duyệt 3 bước: **KSV → Tổng hợp → Giám đốc**
- Ủy quyền Giám đốc: GĐ có thể ủy quyền cho PGĐ trong khoảng thời gian xác định
- Tải phiếu nghỉ phép dạng `.docx` đúng mẫu
- Theo dõi quota phép năm (hạn ngạch / đã dùng)
- Resubmit đơn bị từ chối; huỷ đơn đang chờ hoặc đã duyệt

### Module Chứng từ Hậu kiểm
- **Bàn giao**: GDV nhập số tờ theo ngày, HKV/KSV xác nhận từng ô
- **Gom tập tự động**:
  - Max 350 tờ/tập
  - (user, ngày) không bị tách sang tập khác
  - Nếu 1 ngày > 350 tờ → chia 2 tập cân bằng
- **In bìa**: Tạo file `.docx` đúng format mẫu (2-column layout)
- **Lưu trữ**: Ghi số hộp, vị trí kệ; tra cứu theo phòng/thời gian
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
- Upload file ZIP chứa dữ liệu giao dịch; xử lý bất đồng bộ (~65s)
- Xuất 3 file Excel: **Huỷ**, **Đi**, **Khác** theo kết quả phân loại
- Phân quyền riêng theo nhóm (`menu.cham_459901`, `cham_459901.process`)

---

## Phân quyền (RBAC)

| Vai trò | Mô tả |
|---|---|
| `admin` | Toàn quyền hệ thống, quản lý tài khoản |
| `hau_kiem_vien` | Quyền hậu kiểm (xác nhận, gom tập, in bìa) |
| `giam_doc` | Duyệt nghỉ phép bước cuối; xem toàn bộ màn hình |
| `pho_giam_doc` | Duyệt thay GĐ khi có ủy quyền còn hiệu lực |
| `truong_phong` | Duyệt nghỉ phép bước KSV; nhập bàn giao |
| `pho_phong` | Duyệt nghỉ phép bước KSV; nhập bàn giao |
| `chuyen_vien` | Nhập bàn giao, xem dữ liệu phòng mình |

**Phân cấp**: `admin > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien`

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
