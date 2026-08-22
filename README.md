# Hệ thống của TTTT - Agribank

---

## Cài đặt

### 1. Yêu cầu
- Python 3.10+
- Windows / Linux / macOS
- **Microsoft Word** trên máy chạy backend — chỉ cần cho việc xuất **đơn nghỉ phép bản PDF**
  (Word chuyển `.docx` → `.pdf`). Không có Word thì hệ thống vẫn chạy đủ, riêng phần ký đơn
  lui về tải bản `.docx` không chữ ký.
  Backend **giữ sẵn một bản Word chạy ngầm** để không phải mở/đóng Word cho từng tờ đơn
  (~0,3 giây thay vì ~5 giây mỗi lần xem trước). Bản này chiếm ~130 MB RAM và tự tắt sau
  15 phút không ai dùng. Chỉnh bằng `WORD_SERVER`, `WORD_IDLE_SECONDS`, `WORD_MAX_JOBS`
  trong `.env` — xem `.env.example`.
  **Máy người dùng không cần Word** — họ chỉ dùng trình duyệt.
  > ⚠️ **Word đòi một phiên có người đăng nhập trên máy chủ** — xem
  > [mục riêng bên dưới](#word-đòi-phiên-đăng-nhập-trên-máy-chủ)

### 2. Tạo môi trường ảo và cài thư viện

```bash
python -m venv venv

# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt

# Máy phát triển (muốn chạy pytest) dùng file này thay cho dòng trên —
# nó đã bao gồm toàn bộ requirements.txt, chỉ thêm pytest
pip install -r requirements-dev.txt
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
ENV=production                                  # tắt /docs, /redoc, /openapi.json
```

> `ALLOWED_ORIGINS` **chỉ cần khi có máy khác gọi thẳng cổng 8000 từ trình duyệt.** Với
> `BACKEND_HOST=127.0.0.1` (mặc định `start.bat` sinh ra) thì không cần đặt: trình duyệt
> chỉ nói chuyện với frontend cổng 8080, CORS không tham gia vào đường đi nào cả.

Hai mật khẩu nghiệp vụ — không bắt buộc để khởi động, nhưng thiếu là mất tính năng hoặc mất lớp bảo vệ:

```ini
DOI_CHIEU_ZIP_PASSWORD=<mật khẩu file ZIP do đơn vị cấp file đặt>
BACKUP_PASSWORD=<mật khẩu nén bản sao lưu>
```

| Biến | Thiếu thì sao |
|---|---|
| `DOI_CHIEU_ZIP_PASSWORD` | Đối chiếu ACH / Chấm 459901 / Đối chiếu Song phương báo lỗi rõ khi giải nén; phần còn lại chạy bình thường. Trước 20/08/2026 mật khẩu này nằm cứng trong mã nguồn nên **đã đi vào lịch sử git** — nếu chưa đổi thì coi như đã lộ. |
| `BACKUP_PASSWORD` | Bản sao lưu ghi ra `.db` **không mã hoá** (chứa mã băm mật khẩu toàn bộ tài khoản), kèm cảnh báo trong log mỗi lần backup. Xem mục [Backup tự động](#backup-tự-động). |

> `start.bat` **tự sinh `BACKUP_PASSWORD`** nếu `.env` chưa có, và in ra màn hình đúng một lần —
> chép ngay vào két mật khẩu của đơn vị. `DOI_CHIEU_ZIP_PASSWORD` phải điền tay vì đó là mật khẩu
> của bên cấp file, không phải của phần mềm này — không có cách nào tự sinh hộ.

> **Nâng cấp máy đang chạy:** `deploy.bat` không chép đè `.env` của máy đích, nên biến mới thêm vào
> giữa vòng đời hệ thống **không tự sang**. Từ 22/08/2026 `deploy.bat` in cảnh báo (bước 1/8, nhắc lại
> ở khung tổng kết cuối) khi `.env` máy đích còn thiếu biến thuộc loại phải gõ tay — hiện là
> `DOI_CHIEU_ZIP_PASSWORD`. Biến mới cùng loại thì thêm vào bảng `CHI_CANH_BAO` trong
> `scripts/deploy_env_check.py`; chỉ đưa vào đó thứ mà **thiếu là gãy tính năng**, không thì bảng
> thành danh sách dài ai cũng bỏ qua.

Hai biến tuỳ chọn liên quan đến hiệu năng và mức độ kín của backend:

```ini
BACKEND_URL=http://127.0.0.1:8000   # frontend gọi backend — KHÔNG dùng localhost
BACKEND_HOST=127.0.0.1              # địa chỉ backend lắng nghe
```

> **Đừng dùng `localhost` cho `BACKEND_URL`.** Trên Windows nó phân giải ra `::1` (IPv6)
> trước, mà uvicorn chỉ lắng nghe IPv4 → mỗi kết nối mới tốn thêm ~2 giây chờ IPv6
> thất bại. Đo được: `localhost` 2062 ms so với `127.0.0.1` 18 ms. Không đặt dòng này
> cũng được — mặc định trong code đã là `127.0.0.1`.

> `BACKEND_HOST=127.0.0.1` kín hơn: trình duyệt người dùng chỉ nói chuyện với frontend
> cổng 8080, không bao giờ chạm cổng 8000. Extension CITAD cũng đi qua proxy cổng 8080.
> Chỉ đổi sang `0.0.0.0` khi chắc chắn **có máy khác gọi thẳng API** — và khi đó phải đặt
> luôn `ALLOWED_ORIGINS`.
>
> `start.bat` sinh `.env` mới với `127.0.0.1`, và `deploy.bat` kiểm tra rồi hỏi sửa khi
> máy đích đang để `0.0.0.0`. Mặc định trong code (khi `.env` không có dòng này) vẫn là
> `0.0.0.0` — nên cứ ghi rõ ra `.env` thay vì dựa vào mặc định.

### 5. Chạy hệ thống

```bash
python run.py
```

Truy cập:
- **Giao diện web**: http://localhost:8080
- **API docs**: http://localhost:8000/docs — chỉ khi `ENV=development`. Ở `production`
  cả `/docs`, `/redoc` và `/openapi.json` đều trả 404; cần xem để gỡ lỗi thì đặt
  `ENABLE_API_DOCS=1`, **không** hạ `ENV` xuống `development`
- **Từ máy khác trong LAN**: http://[IP-máy-chủ]:8080

> **Windows — dùng `start.bat`.** Script tự kiểm tra `.venv` và **vá tại chỗ** (~2 giây) khi thư mục dự án
> được mang sang máy khác (chạy từ USB), thay vì xoá và cài lại toàn bộ thư viện. Máy mới cần **Python 3.10.x**;
> bản 3.11/3.12 sẽ buộc cài lại thư viện và **cần internet**.
>
> Sửa file `.bat` / `.ps1` phải giữ xuống dòng **CRLF** — `.gitattributes` đã ép sẵn khi clone/checkout,
> nhưng công cụ ghi file thường mặc định LF và `cmd.exe` chạy sai file .bat dạng LF mà không báo lỗi rõ.

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
│   │   ├── sessions.py      # Session lưu DB (bảng login_sessions) — không mất khi restart
│   │   ├── audit_middleware.py # Ghi nhật ký thao tác tập trung → audit_logs
│   │   ├── audit_queue.py   # Hàng đợi + 1 luồng ghi audit, không chặn response
│   │   ├── concurrency.py   # Giới hạn số việc nặng chạy đồng thời (sinh Word/Excel)
│   │   ├── paths.py         # Đường dẫn template có dấu — chống lệch chuẩn hoá Unicode NFC/NFD
│   │   ├── net.py           # IP thật của người dùng — chỉ tin X-Client-IP từ máy đáng tin
│   │   ├── uploads.py       # Trần kích thước upload + làm sạch tên file (chống ghi ra ngoài thư mục)
│   │   └── rate_limit.py    # Chặn dò mật khẩu — đếm theo tên đăng nhập VÀ theo địa chỉ máy
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
│   │   ├── ttqt_branches.py # Danh mục CN thực hiện TTQT (CRUD + import/export Excel)
│   │   ├── logs.py          # Nhật ký hệ thống (admin)
│   │   └── holidays.py      # Quản lý ngày lễ (admin)
│   └── services/
│       ├── bundle_service.py       # Thuật toán gom tập (max 350 tờ)
│       ├── cover_service.py        # Tạo bìa tập chứng từ (docxtpl)
│       ├── archive_cover_service.py# Bìa hồ sơ lưu trữ M01/LHS (đọc Excel tra cứu → điền XML)
│       ├── report_service.py       # Xuất báo cáo Excel
│       ├── handover_report_service.py # Tính chứng từ nộp đúng hạn / quá hạn
│       ├── th_report_service.py    # Xuất báo cáo tổng hợp (phòng TH)
│       ├── backup_service.py       # Backup SQLite tự động
│       ├── log_cleanup_service.py  # Dọn login_logs / audit_logs quá hạn theo lịch
│       ├── time_sync.py            # Cảnh báo lệch giờ máy chủ so NTP (không tự sửa, có cache)
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
│       ├── storage.py       # Lưu trữ tập (số hộp, vị trí kệ) + In bìa hồ sơ M01/LHS
│       ├── ttqt_branches.py # Danh sách CN thực hiện TTQT
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
├── templates/                       # ⚠ Tên thư mục có dấu — xem ghi chú bên dưới
│   ├── bia_mau_goc.docx             # Mẫu bìa tập chứng từ
│   ├── don_xin_nghi_phep_tpl.docx  # Template phiếu nghỉ phép (mẫu chung, dùng khi thiếu mẫu riêng)
│   ├── Phòng Tổng hợp/
│   │   └── Nghỉ phép/               # Mẫu đơn riêng theo chức danh (_nv/_tp/_gd/_pgd.docx)
│   └── Phòng KSNB&HTVH/
│       └── Bàn giao cho lưu trữ/
│           ├── Bia_ho_so.doc        # Mẫu gốc do bên lưu trữ cấp (giữ để đối chiếu)
│           └── Bia_ho_so.docx       # Bản dùng lúc chạy (chuyển từ .doc, render giống hệt)
├── data/
│   ├── ksnb.db             # SQLite database (tự tạo khi chạy lần đầu)
│   ├── backups/            # Backup tự động — xem mục "Backup tự động"
│   └── temp_*/             # Kết quả tạm của ACH / Chấm 459901 / Đối chiếu song phương;
│                           #   temp_cleanup_service dọn nền mỗi 6h (không chờ ai mở menu)
├── logs/
│   ├── app.log             # Log xoay vòng (5 MB × 3 file) — nguồn của màn hình Nhật ký hệ thống
│   ├── backend.log         # stdout/stderr tiến trình backend (run.py ghi) — xoay khi >20 MB, giữ 3 đời
│   ├── frontend.log        # stdout/stderr tiến trình frontend (run.py ghi) — xoay khi >20 MB, giữ 3 đời
│   └── *.truoc-utf8.log    # Phần log ghi trước bản vá UTF-8, run.py tự tách ra một lần
├── init_db.py               # Khởi tạo DB + seed data
├── run.py                   # Launcher (chạy backend + frontend song song; ép UTF-8 cho tiến trình con)
├── .github/workflows/       # CI — chạy pytest mỗi lần push / mở PR
├── docs/                    # Tài liệu dự án (README.md, CLAUDE.md, Logs_update.md ở gốc)
│   ├── DESIGN.md                # Patterns & business logic
│   ├── SKILL.md                 # Nguyên tắc & quy ước làm việc
│   ├── CONTRIBUTING.md          # Quy tắc đóng góp
│   ├── Implementation-notes.html # Ghi chú kỹ thuật, quyết định thiết kế (bản đang dùng)
│   └── Implementation-notes.md   # Bản cũ, giữ làm lịch sử
├── scripts/                 # Script phụ trợ chạy tay hoặc do deploy.bat gọi
│   ├── deploy_env_check.py      # Kiểm/sửa .env máy đích khi deploy
│   ├── deploy_don_file_thua.py  # Dò file .py cũ còn sót trên máy đích
│   └── import_users_csv.py      # Nạp data/user_tttt.csv vào bảng user_tttt
└── requirements.txt
```

> ⚠️ **Thư mục template có dấu tiếng Việt: luôn dùng `template_path()` trong `backend/core/paths.py`, không dùng `os.path.join`.**
> Tên thư mục trên đĩa (và trong git) ở dạng Unicode **NFD**, còn chuỗi gõ trong mã nguồn là **NFC** — hai chuỗi khác nhau về byte, Windows không tự chuẩn hoá, nên `os.path.exists()` trả về `False` dù thư mục vẫn ở đó. Thư mục con (`Nghỉ phép`, `Bàn giao cho lưu trữ`) cũng NFD, nên phải đưa **toàn bộ** các đoạn vào `template_path()`, đừng resolve nửa chừng rồi `join` tiếp.
>
> Thêm file mẫu mới thì **copy/paste vào thư mục đang có sẵn**, **đừng gõ tay tên thư mục** để tạo mới — bộ gõ sinh NFC và sẽ đẻ ra thư mục thứ hai trùng tên (đã từng xảy ra với `Phòng Tổng hợp`, hậu quả là mẫu đơn riêng theo chức danh không bao giờ được dùng mà không báo lỗi gì). `tests/test_paths.py` canh việc này.

---

## Chức năng

### Module Nhân sự & Tài khoản
- Quản lý cán bộ theo phòng ban, vai trò (8 vai trò — xem bảng RBAC)
- Quản lý nhóm cán bộ và phân quyền tính năng theo nhóm
- Dashboard tổng quan: KPI người dùng & phòng nghiệp vụ, bảng nghỉ phép hôm nay theo phòng, biểu đồ cột tỷ lệ nộp chứng từ đúng hạn/muộn theo 4 phòng (chọn tháng/năm để xem). **Mọi vai trò đều vào Trang chủ sau khi đăng nhập**
- **Công việc chờ xử lý**: khối ở đầu sidebar, hiện trên mọi trang — số chứng từ chờ xác nhận và đơn nghỉ phép chờ duyệt của **chính người đang đăng nhập**; bấm vào mở màn hình theo dõi `/pending/<loại>` có đủ chi tiết và link nhảy thẳng tới ô cần xử lý
- **Nhật ký thao tác** (audit log): middleware ghi tập trung mọi request thay đổi dữ liệu (POST/PUT/PATCH/DELETE) vào bảng `audit_logs` — ai, làm gì, kết quả HTTP, IP, thời gian; lọc theo phương thức, tìm kiếm, phân trang; tự dọn sau 365 ngày
- Nhật ký đăng nhập và nhật ký lỗi/cảnh báo hệ thống (admin xem, lọc theo user/thời gian)
- **Ảnh chữ ký cá nhân** (menu *Quản lý người dùng*, mọi vai trò kể cả chuyên viên): tải lên ảnh
  **PNG nền trong suốt**, tối đa 2 MB, mỗi người một ảnh. Ảnh lưu trong DB (bảng `user_signatures`)
  nên đi cùng bản sao lưu `.db`; chỉ xem/sửa/xoá được ảnh **của chính mình**. Dùng để ký đơn nghỉ phép
- **Trạng thái tài khoản** — cột `user_tttt.is_active` cho phép NULL (dữ liệu cũ, đường *Nhập DB*). **NULL = tạm khoá**, thống nhất với `WHERE is_active = 1` ở đăng nhập và danh sách cán bộ; migration lúc khởi động ghi hẳn về `0`, `StaffOut` cũng ép NULL → `False` để một dòng bỏ trống không làm hỏng cả response `/api/staff/`
- **Nhập Ngày vào ngành hàng loạt từ Excel** (nút *Nhập Ngày vào ngành*, feature `staff.import_join_date`)
  — `POST /api/staff/import-join-dates`, khớp theo **Mã cán bộ**, chỉ ghi cột `join_industry_date`.
  Dòng tiêu đề cột được dò trong 15 dòng đầu (file thật có dòng trống ở trên); dòng nào ô Mã cán bộ
  rỗng thì bỏ qua (tiêu đề nhóm phòng). Nhận ngày dạng `dd/mm/yyyy`, `yyyy-mm-dd`, ô định dạng Date,
  và serial Excel; **loại mọi năm ngoài 1950 → năm hiện tại**. Mặc định `overwrite=false` — chỉ điền
  vào ô đang trống, ai đã có ngày khác thì được liệt kê chứ không bị đè. Giao diện luôn chạy
  `dry_run=true` trước để xem số dòng sẽ đổi / mã không khớp / ô ngày hỏng, chỉ mở nút ghi khi thật sự
  có thay đổi. Người đã xoá (`is_deleted = 1`) không được khớp; endpoint **không tạo tài khoản mới**

- **Xuất / Nhập file DB người dùng** (`staff.export` · `staff.import_db`) — dùng để di trú toàn bộ
  tài khoản sang hệ thống khác **mà không phải đặt lại mật khẩu**, nên file mang theo nguyên
  `pwd_hash` và `role`. Vì thế **cả hai đường đều chỉ Quản trị viên (cấp 1/2) gọi được**, xét theo
  vai trò thật chứ không chỉ theo feature. Đường nhập còn bỏ qua — và báo lại danh sách bỏ qua —
  các dòng có `role` sai chính tả, `department_id` không tồn tại, hoặc thiếu Mã cán bộ; khớp theo
  **Mã cán bộ**. ⚠️ **Số liệu phép (`used_leave_days`, `annual_leave_days`, `carryover_notice_year`)
  của tài khoản đã có thì KHÔNG bị đè** — đó là dữ liệu của module Nghỉ phép, nơi có batch nhập +
  hoàn tác riêng; tài khoản mới thì vẫn lấy theo file. `tests/test_import_db_an_toan.py` canh việc này

### Module Nghỉ phép
- Cán bộ tạo đơn xin nghỉ (phép năm, ốm, việc riêng, khác)
- Workflow duyệt 3 bước: **KSV → Tổng hợp → Giám đốc**
- Ủy quyền Giám đốc: GĐ có thể ủy quyền cho PGĐ trong khoảng thời gian xác định
- Tải phiếu nghỉ phép dạng **`.pdf`** đúng mẫu (Word chuyển từ `.docx`; máy không có Word → lui về `.docx`)
- **Ký đơn trên bản in**: lúc gửi đơn và lúc phê duyệt (KSV, Ban lãnh đạo) hiện popup xem trước
  **chính bản in thật**, kéo/thu phóng ảnh chữ ký cá nhân vào đúng ô ký rồi mới gửi/duyệt.
  Mở màn Nghỉ phép là backend tự đánh thức Word ở nền, nên đến lúc bấm nút gần như không phải chờ.
  Chữ ký được **sao lại vào đơn** tại thời điểm ký — sau này đổi hoặc xoá ảnh chữ ký cá nhân
  thì đơn đã ký không đổi theo. Nộp lại đơn bị từ chối sẽ xoá chữ ký của người duyệt.
  Chưa có ảnh chữ ký (Quản lý người dùng → Ảnh chữ ký) thì vẫn gửi/duyệt được, chỉ là phiếu trống ô ký.
  *Duyệt hàng loạt và bước Tổng hợp không ký.*
- **Lịch nghỉ tháng chỉ hiện người cùng phòng.** Xem được toàn trung tâm: admin, GĐ/PGĐ, nhân viên
  phòng Tổng hợp — đúng tiêu chí `scope="all"` của `list_leaves()`. Hậu kiểm viên **không** nằm trong
  danh sách này (họ ngang chuyên viên ở quy trình nghỉ phép). Rê chuột vào ô ngày để xem đủ danh sách
- Theo dõi quota phép năm (hạn ngạch / đã dùng); chuyển tiếp ngày phép chưa dùng năm trước sang Q1
- Banner "Phép còn lại" tính đủ hạn mức nhập tay + ngày chuyển kỳ, khớp đúng tab Hạn mức phép
- Đơn nghỉ vắt qua ranh giới năm (vd 29/12 → 02/01) được chia đúng cho từng năm khi tính hạn mức
- Nghỉ thai sản / bảo hiểm (không trừ vào hạn mức phép năm), chọn khoảng ngày bằng lịch cuộn
- Nhập hạn mức phép hàng loạt từ file Excel (xem trước / áp dụng / hoàn tác); sửa tay số ngày "Đã dùng" của từng người — cả hai cách đều thay thế lẫn nhau, không cộng dồn
- Bản ghi hạn mức nhập từ Excel / sửa tay không phải đơn nghỉ thật: bị ẩn khỏi danh sách đơn, lịch, kiểm tra trùng ngày, số liệu Dashboard, Trang chủ và Báo cáo bàn giao
- Khai báo hộ; ngày nghỉ lẻ không liên tục (`spread_dates`)
- Bảng nghỉ phép hôm nay trên Trang chủ theo từng phòng — **chỉ đếm đơn đã duyệt** (lịch tháng trong menu thì hiện cả đơn đang chờ, kèm nhãn trạng thái)
- Chống duyệt trùng: hai người (hoặc hai tab) bấm duyệt cùng lúc thì chỉ lần đầu có hiệu lực, lần sau báo đơn đã được xử lý
- Resubmit đơn bị từ chối; huỷ đơn đang chờ hoặc đã duyệt

### Module Chứng từ Hậu kiểm
- **Bàn giao**: GDV nhập số tờ theo ngày, HKV/KSV xác nhận từng ô
  - *Phạm vi xem*: `admin` / GĐ / PGĐ và người có quyền hậu kiểm (`handovers.confirm_entry`) xem được **mọi phòng nguồn**; các vai trò còn lại — kể cả trưởng/phó phòng — chỉ xem **phòng của chính mình**, dropdown chọn phòng cũng chỉ liệt kê phòng đó. Backend chặn ở `grid`, `history` và `export` (xuất Excel tự ép về phòng người gọi)
  - *Phạm vi ghi*: `admin`, `giam_doc`, `pho_giam_doc` **chỉ đọc — bị cấm hoàn toàn** mọi thao tác ghi (`_NO_WRITE_ROLES`, chặn ở dependency `require_handover_write` nên `admin` không bypass được như với `require_feature`). Các vai trò còn lại ghi được **trong phòng mình** nếu nhóm được cấp feature tương ứng; riêng người có `handovers.confirm_entry` ghi được trên mọi phòng
  - Vào được menu vẫn cần feature `menu.handovers` — vai trò không tự mở menu
  - *Vòng đời một ô*: `chờ xác nhận → đã xác nhận`; mượn - trả có hai đường vào trạng thái **đang mượn**:
    GDV bấm **Mượn lại** (xin → HKV duyệt), hoặc HKV/KSV bấm **Chuyển trả GDV** ở panel lịch sử để đẩy thẳng
    `đã xác nhận → đang mượn` (bắt buộc nhập lý do, feature `handovers.return_entry`, chặn cứng `chuyen_vien`).
    Cả hai đường đều kết thúc bằng GDV **Bàn giao lại** → HKV xác nhận
  - *Cán bộ chuyển phòng*: chứng từ hiển thị theo phòng tại **ngày giao dịch** — trước ngày chuyển ở phòng cũ, từ ngày chuyển ở phòng mới (lịch sử đổi phòng lưu ở bảng `staff_department_history`). Nhập bù chứng từ tháng cũ cho cán bộ đã chuyển vẫn vào đúng phòng cũ; do giới hạn phạm vi phòng ở trên, việc nhập bù này do người hậu kiểm thực hiện
- **Gom tập tự động**:
  - Max 350 tờ/tập
  - (user, ngày) không bị tách sang tập khác
  - Nếu 1 ngày > 350 tờ → chia 2 tập cân bằng
- **In bìa**: Tạo file `.docx` đúng format mẫu (2-column layout)
- **Lưu trữ**: Ghi số hộp, vị trí kệ; tra cứu theo phòng/thời gian; bảng tổng hợp cả năm (số tờ/số tập theo phòng × 12 tháng); sửa **ngày** và **số chứng từ** ngay trên bảng — nhập vào ô trống để thêm tập, sửa về 0 để xoá tập, số tập/tổng tự cập nhật. Sửa ngày chỉ ghi lại `cover_units` của tập, **không đụng** số liệu bàn giao gốc của phòng nguồn (`document_entries`); mỗi dòng phải còn ít nhất một ngày, xoá hết ngày thì báo lỗi và giữ nguyên số đang nhập
  - *Tab "In bìa hồ sơ"*: Nạp file Excel tra cứu hồ sơ (`LT_HS_TRACUU_*.xls`) xuất từ chương trình lưu trữ → điền vào mẫu bìa **M01/LHS** (`templates/Phòng KSNB&HTVH/Bàn giao cho lưu trữ/Bia_ho_so.docx`), giữ nguyên toàn bộ định dạng của mẫu. Lấy cột **I** *Mã vạch* (ký hiệu thông tin + chuỗi barcode), cột **C** *Tên hồ sơ* (dòng tiêu đề + **Ngày mở** = ngày **đầu tiên** xuất hiện trong tên), cột **F** *Ngày CVKT*, cột **G** *Số tờ*. Chọn hồ sơ cần in trên bảng rồi tải về **1 file Word nhiều trang** (mỗi hồ sơ 1 trang) hoặc **ZIP mỗi hồ sơ 1 file**. Máy in phải cài font **"3 of 9 Barcode"**, nếu không dòng mã vạch in ra thành chữ thường và máy quét không đọc được
- **Báo cáo** (menu con):
  - *Báo cáo hậu kiểm*: Xuất Excel tổng hợp theo phòng
  - *Báo cáo bàn giao chứng từ*: Số chứng từ nộp đúng hạn / quá hạn theo phòng; chi tiết cán bộ nào nộp chậm chứng từ ngày nào, chậm bao nhiêu ngày làm việc. **Xuất Word A4 ngang** đúng kỳ đang xem (bảng tổng hợp theo phòng + chi tiết quá hạn, phần chi tiết chỉ ghi họ tên, không ghi User IPCAS)
- **Báo cáo tổng hợp**: Báo cáo riêng cho phòng Tổng hợp
- **Lịch sử thay đổi**: Ghi log mọi thao tác xác nhận, mượn, trả chứng từ

### Module Danh sách CN TTQT
- Danh mục chi nhánh thực hiện thanh toán quốc tế trực tiếp (mã CN, tên CN, SWIFT BIC, loại I/II,
  CN loại I quản lý, SĐT, địa chỉ, ghi chú)
- Menu: **Danh sách CN TTQT** (menu phẳng, cấp 1)
- Tra cứu theo mã CN / tên CN / SWIFT BIC; lọc theo loại CN và trạng thái
  (**Đang hoạt động** / **Đã đóng BIC** / Tất cả) — CN đã đóng BIC tô xám khi xem chung
- Thêm / sửa / xoá từng CN ngay trên giao diện, mọi thao tác ghi audit log
- **Nhập từ Excel**: đọc đúng file gốc do phòng KSNB phát hành — dòng đánh dấu `Đóng BICCODE` phân
  tách nhóm CN còn hoạt động với nhóm đã đóng BIC. Mặc định chỉ **thêm mới + cập nhật**; tích ô
  *"Xoá CN không có trong file"* nếu muốn đồng bộ hoàn toàn theo file
- **Xuất Excel** theo đúng bộ lọc đang xem; file xuất ra nhập lại được (cùng định dạng file gốc)
- Phân quyền riêng theo nhóm (`menu.ttqt_branches` + `ttqt_branches.create/edit/delete/import/export`)

### Module Lịch trực
- Xếp lịch trực tự động cho phòng Thanh toán
- **Số người mỗi ca do phòng tự khai** ở tab Cài đặt (ca thường và ca quyết toán khai riêng);
  một ca có thể có **nhiều hơn một Lãnh đạo**. Thiếu người so với số đã khai thì
  **không hình thành ca trực**, có cảnh báo nêu rõ lý do
- **Ca quyết toán** chia nhóm trực chính / trực phụ (nhóm phụ về sớm hơn), lưu thành **một** bản ghi
- Cần **ít nhất 1 người xử lý song phương** trong Lãnh đạo + nhóm trực chính — thiếu hoặc dư
  đều vẫn lập ca, chỉ cảnh báo. Người ở nhóm trực phụ không tính (về sớm)
- Ngày thường bốc **ngẫu nhiên trong nhóm ít ca nhất**; thứ 6 luân phiên **tất định**.
  Có tiêu chí phụ tránh hình thành ê-kíp trực cố định
- **Ba luật công bằng (mềm)**, áp dụng như nhau cho Lãnh đạo lẫn nhân viên: không quá
  **2 ca/tuần**, không quá **2 thứ 6/tháng**, không trực thứ 6 ở **2 tuần liên tiếp**.
  Thuật toán ưu tiên tránh; pool cạn thì **vẫn lập ca** kèm cảnh báo nêu đích danh người bị
  phá luật — đủ người quan trọng hơn giữ đúng luật mềm. Đường **sửa tay** cũng cảnh báo,
  nhưng hiện chỉ soi các ca **trước** ngày đang sửa (xem card 91 trong Implementation-notes)
- **Sửa tay** thành phần ca: vai song phương hệ thống tự suy từ cờ "biết song phương",
  số ca trong vòng xoay đi theo người được đổi. Sửa xong ca quay về bản thảo, phải xác nhận lại
- **Xoá hoặc tạo lại lịch trả số ca về vòng xoay** — mọi đường ghi/xoá ca đều tra cùng
  `KENH_VONG_XOAY` trong `duty_scheduler_engine.py`, không đường nào tự hiểu khác
- **Thứ 7 / chủ nhật đi làm**: khai loại **"Ngày bù"** ở tab Ngày đặc biệt rồi xác nhận thì
  hôm đó sinh ca thường, vào lịch tuần/tháng, lên file Excel, đăng ký nguyện vọng được,
  và được tính khi dò 2 ngày cut-off cuối tháng
- **Ngày lễ lấy từ hai nguồn**: danh mục ngày lễ chung `public_holidays` (nhập ở màn hình *Nghỉ phép*
  — giao diện nhập ngày lễ duy nhất của phần mềm) hợp với khai báo riêng ở tab *Ngày đặc biệt*.
  **Khai báo riêng thắng**: ngày đã có dòng trong `duty_special_days` thì lấy nguyên `day_type` của
  nó, nhờ vậy ngày làm bù rơi trúng ngày lễ (nhà nước hoán đổi) vẫn đúng là ngày làm
- **Đơn nghỉ phép đã duyệt tự loại người khỏi lịch** — không phải khai vắng mặt lần thứ hai.
  Đọc thẳng `leave_records` lúc xếp lịch chứ không sao chép sang `duty_absences`: đơn còn bị huỷ,
  thu hồi, sửa ngày. Chỉ đơn `approved` mới tính; đơn đang chờ duyệt vẫn xếp trực bình thường
- Quản lý cán bộ trực, ràng buộc lịch trực (ngày không trực, giới hạn ca)
- Thống kê số ca trực theo cán bộ, theo tháng — **trực chính và trực phụ đếm 2 cột riêng**, không quy đổi
- **Xuất lịch trực ra Excel** bám mẫu giấy của phòng: 5 cột A–E, trắng đen, cỡ chữ 24/18/16,
  mỗi ngày đúng một hàng; ngày quyết toán để trực chính IN HOA đậm và trực phụ nghiêng nhỏ
  trong cùng ô. **Chức danh người ký khai được** ở tab Cài đặt (`signer_title`), mặc định "GIÁM ĐỐC"
- **Phân quyền enforce ở backend**, không chỉ ẩn nút: cả 35 endpoint đều gắn `require_feature`
  (`menu.duty_schedule` để đọc · `duty.generate` tạo & sửa lịch · `duty.confirm` · `duty.delete`
  · `duty.export` · `duty.manage_staff` cờ nhân sự & vắng mặt · `duty.manage_config` cài đặt &
  ngày đặc biệt & reset vòng xoay)

### Module Đối chiếu điện SWIFT (phòng Swift)
- Đối chiếu điện SAA ↔ Màn hình quản lý điện, 2 chiều: **Điện đến** / **Điện đi**
- Mỗi bên nhận **nhiều file** (SAA có thể xuất nhiều đợt trong ngày) — tự gộp
  trước khi đối chiếu; giới hạn 10 file hoặc 100 MB mỗi ô
- Xuất Excel 5 loại mỗi chiều: Tổng hợp, Chi tiết lệch, Bản ghi đang lọc,
  **Tổng hợp theo biểu mẫu** và **Chi tiết lệch theo biểu mẫu** (Mẫu 04/05,
  khung nền lấy từ `backend/services/swift_recon/templates/`)
- Cột "Chênh lệch" đếm số bản ghi **không khớp khoá**, không phải hiệu số lượng
- Tab **Lịch sử đối chiếu** — lưu vào bảng `swift_recon_history` trong DB chung
- Phân quyền riêng theo nhóm (`menu.swift_recon`)

### Module Chấm 459901
- Phân loại bút toán tài khoản trung gian 459901 dành cho phòng Thanh toán
- Menu: **Đối chiếu → Phòng Thanh toán → Chấm 459901**
- Upload file ZIP chứa dữ liệu giao dịch; xử lý bất đồng bộ (~65s)
- Xuất 3 file Excel: **Huỷ**, **Đi**, **Khác** theo kết quả phân loại
- Phân quyền riêng theo nhóm (`menu.cham_459901`, `cham_459901.process`)

### Module Đối chiếu Song phương
- Định tuyến lệnh IPCAS phục vụ đối chiếu song phương tại phòng Thanh toán
- Menu: **Đối chiếu → Phòng Thanh toán → Đối chiếu Song phương**
- Upload file ZIP (mã hóa AES-256) chứa dữ liệu IPCAS; xử lý bất đồng bộ, theo dõi tiến độ real-time
- Phân loại mỗi dòng theo **4 ngân hàng** (Vietinbank 201, BIDV 202, Vietcombank 203, MBBank 311) × **2 chiều**: **ĐẾN** (`CRAMOUNT=0`) / **ĐI** (`DRAMOUNT=0`) → xuất **8 file CSV**
- Phân quyền riêng theo nhóm (`menu.doi_chieu_song_phuong`, `doi_chieu_song_phuong.process`)

### Module Đối chiếu ACH
- Đối chiếu GL02 (IPCAS/NPO) với MIS PaymentHub theo phiên ACH, cả hai chiều ĐI và ĐẾN
- Menu: **Đối chiếu → Phòng Thanh toán → Chấm đối chiếu ACH**
- Chọn bộ file 1 ngày **từ máy người dùng**: `GL02*.zip`, file GW `.xlsx`, 2 file `*_DI_*.zip`,
  2 file `*_DEN_*.zip`, PDF sao kê ACH (lấy số session + suy ngày đối chiếu). Mở thư mục chứa
  bộ file rồi Ctrl+A để chọn cả loạt. Mỗi file gửi lên frontend ngay khi chọn (`auto_upload`) và
  **nằm trong RAM** của tiến trình frontend cho tới lúc bấm Chạy; backend cũng đọc trọn bộ vào
  RAM (`read_limited`) trước khi ghi ra `data/temp_ach/<job>/input/`. Tên file được
  `safe_filename()` cắt sạch phần đường dẫn trước khi ghi — tên client gửi lên là chuỗi tuỳ ý,
  ghép thẳng vào `Path` thì đoạn tuyệt đối nuốt trọn thư mục đích. Trần 500 MB (`_MAX_UPLOAD`), bộ
  file thật 150–250 MB → cần dư RAM tương ứng ở **cả hai** tiến trình. Timeout lần gửi này để
  riêng 600s (`post_upload(..., timeout=600.0)`), các màn hình khác giữ mặc định 60s
- Ngày đối chiếu suy từ tên file PDF (`ACH_YYYYMMDD_..._NRT_<session>_...` → ngày T-1), nhập tay được;
  không suy được thì **báo lỗi**, không lặng lẽ dùng ngày khác
- Khớp theo số lượng cặp khoá: chiều ĐI `TRBRCD+SO_TRACE+CRAMOUNT` ↔ `CHI_NHANH+SO_TRACE+SO_TIEN`,
  chiều ĐẾN `SO_TRACE+DRAMOUNT` ↔ `TRACE+SO_TIEN`. Lệnh TPAY vượt số slot GW được tách ra sheet
  **TIMEOUT_KHONG_KENH** (đánh dấu `CO_TRONG_GW` nếu MSGREF vẫn có trong GW → cần kiểm tra tay)
- Kết quả: 1 file Excel 11 sheet (TONG_KET, PHAN_TICH có cảnh báo tự động, các sheet khớp/thừa,
  CAP_CN_TIEN, RAW_GW); sheet trên **15.000 dòng** tự tách ra CSV riêng, tải lẻ hoặc tải gộp ZIP
- Chạy nền trên **1 luồng riêng** (`max_workers=1`) — job thứ hai xếp hàng; theo dõi tiến độ + nhật ký
  bằng poll, có nút Dừng (dừng ở mốc kiểm tra giữa các pha, không tức thì)
- Kết quả giữ **4 giờ** trong `data/temp_ach/` rồi tự xoá; không lưu lịch sử vào DB
- Phân quyền riêng theo nhóm: `menu.cham_ach` = xem trang / kiểm tra file / tải kết quả,
  `cham_ach.process` = được bấm Chạy, Chạy tiếp sau Checkpoint và Dừng

### Module Đối chiếu CITAD ↔ PaymentHub
- Đối chiếu số liệu tổng CITAD (NHNN) với PaymentHub (Agribank) theo từng ngày
- Menu: **Đối chiếu → Phòng Thanh toán → Đối chiếu CITAD**
- Nhập tay 5 cổng CITAD × 3 loại tiền × 8 trường; chênh lệch tính lại ngay khi gõ
- Ngoài 5 cổng còn 2 kênh cộng vào tổng CITAD: **Napas** và **PSS - MDP** (chỉ 2 ô *IH Đến —
  Món/Tiền*). Kênh **Ebanking** đã ngừng: bỏ khỏi màn hình 14/08/2026, bỏ nốt khỏi file Excel
  20/08/2026 — số liệu các ngày đã chấm vẫn nằm nguyên trong DB, chỉ không hiện/in ra nữa
- Mỗi ngày là **một bản ghi chung cả phòng** (`doi_chieu_citad_sessions`, khoá theo `ngay`) —
  ai lưu sau cùng là bản hiện hành; mỗi lần bấm Lưu ghi thêm 1 dòng vào
  `doi_chieu_citad_history` để xem/tải lại từng bản cũ
- Xuất Excel theo mẫu *"Báo cáo đối chiếu giao dịch hệ thống thanh toán điện tử liên ngân hàng"*
  đã duyệt (`build_xlsx` — không đổi format/công thức khi sửa)
- Kèm **Extension trình duyệt** (`extension_citad/`) tự lấy số liệu từ trang CITAD/PaymentHub:
  tải `.zip` ngay trên màn hình, ghép nối bằng *mã kết nối* cá nhân
  (`doi_chieu_citad_extension_tokens`, chỉ lưu hash SHA-256, tạo mã mới tự thu hồi mã cũ).
  Chỉ chạy trên Chromium (Chrome/Edge/Cốc Cốc), phải cài tay từng máy
- Phân quyền riêng theo nhóm (`menu.doi_chieu_citad`)

### Module Đối soát CITAD ↔ IPCAS
- Đối soát từng lệnh chuyển tiền giữa CITAD (NHNN) và IPCAS (Agribank) theo ngày chấm
- Menu: **Đối chiếu → Phòng Thanh toán → Đối soát CITAD ↔ IPCAS**
- Upload file CITAD (`.xls`/`.xlsx`/`.zip`), IPCAS (`.csv`/`.zip`) và Hub ngoại tệ (`.xls`/`.xlsx`);
  khớp trong RAM theo `msgref` (Đi) / `txid` (Đến), phân loại lệch thành 4 nhóm:
  **Chỉ CITAD / Chỉ IPCAS / Chỉ Hub / Lệch trạng thái**
- Cảnh báo khi chọn **trùng nội dung file** (băm SHA-256 toàn bộ byte, không dựa vào tên file)
- Xuất Excel 4 sheet; tab **Lịch sử** lưu `doi_soat_citad_history` kèm snapshot nguyên vẹn danh sách
  lệch — xem lại/tải lại đúng số liệu của lần đối soát cũ, không tính lại từ file gốc
- Nút **"Xuất tất cả lệnh"** xuất đủ cả khớp lẫn lệch trong 1 sheet (lệch đẩy lên đầu, bôi vàng);
  ~38.000 dòng mất ~6 giây nhờ đặt style ở cấp cột thay vì từng ô — xem
  `docs/Implementation-notes.html`. Danh sách khớp **không** lưu vào lịch sử, chỉ giữ trong phiên
- Phân quyền riêng theo nhóm (`menu.doi_soat_citad`)

### Module Sổ trực cuối ngày (Phòng Thanh toán)
- Ghi nhận ca trực cuối ngày: **2 GDV chính** (+ trực phụ chỉ liệt kê, không tham gia duyệt)
  nhập ghi chú, chọn **1 KSV** xác nhận. Menu cấp 1: **Sổ trực cuối ngày**
- Luồng: `draft` → `pending_ksv` → `approved`. Một GDV đủ để chuyển KSV; GDV còn lại bấm
  *Xác nhận phiên trực* chỉ để ghi nhận đã xem (`gdv_ack`, không chặn luồng)
- KSV có hai lựa chọn từ chối, **cả hai đều chỉ là đề nghị và đều quay về `draft`** —
  phân biệt bằng `ksv_decision`: `reject_fix` (yêu cầu sửa) và `reject_cancel` (đề nghị huỷ,
  khoá form, GDV chỉ còn nút *Huỷ phiên trực*). **Chỉ GDV mới đóng được phiên thật**
  (`draft_cancel` → `cancelled`, ngõ cụt — làm lại phải mở phiên mới cho cùng ngày)
- Phiên đã **Hoàn thành** vẫn mở lại sửa được (`request_edit`): GDV mở lại thì phải đẩy KSV
  duyệt lại từ đầu; KSV tự mở lại (`self_edit`) thì tự sửa rồi tự chốt (`ksv_finalize_edit`)
- **Khoá theo đúng người, không theo vai**: một khi `gdv1_id`/`gdv2_id` đã chọn, chỉ đúng 2 tài
  khoản đó sửa được; `ksv_id` khoá cứng từ lần chọn đầu, đẩy lại sau khi bị từ chối vẫn phải
  đúng người đó. Sai người → `NotAllowedError` → HTTP 403
- Một ngày có thể có **nhiều phiên** (đã huỷ rồi mở lại). Unique index một phần
  `ux_so_truc_active_date (truc_date) WHERE status != 'cancelled'` bảo đảm mỗi ngày chỉ một
  phiên đang hoạt động, đồng thời chặn tranh chấp khi hai GDV cùng mở một ngày
- Cảnh báo (không chặn) khi **Đối chiếu CITAD cùng ngày chưa khớp**; link sang thẳng tab
  Lịch sử của `/doi_chieu_citad?ngay=`
- Badge **Sổ trực chờ xử lý** trên sidebar; trang chủ nhắc khi sau 16h (giờ máy chủ) chưa ai
  mở sổ. Tab Lịch sử xuất Excel theo khoảng ngày
- Phân quyền: `menu.so_truc` (vào module, xem lịch sử) + `so_truc.ksv_confirm`
  (được xuất hiện trong danh sách chọn KSV)

---

## Phân quyền (RBAC)

| Vai trò | Mô tả |
|---|---|
| `admin` | **Quản trị viên cấp 1** — toàn quyền hệ thống, quản lý tài khoản & phân quyền nhóm. **Ngoại lệ: chỉ đọc ở Bàn giao chứng từ** |
| `admin_l2` | **Quản trị viên cấp 2** — quyền theo nhóm chức năng được gán; không thuộc phòng nào; không được tạo/sửa/xóa tài khoản cấp 1; **dùng được màn Phân quyền chức năng, trừ nhóm chứa chính mình** |
| `hau_kiem_vien` | Quyền hậu kiểm (xác nhận, gom tập, in bìa) |
| `giam_doc` | Duyệt nghỉ phép bước cuối; xem toàn bộ màn hình. **Chỉ đọc ở Bàn giao chứng từ** (xem mọi phòng) |
| `pho_giam_doc` | Duyệt thay GĐ khi có ủy quyền còn hiệu lực. **Chỉ đọc ở Bàn giao chứng từ** (xem mọi phòng) |
| `truong_phong` | Duyệt nghỉ phép bước KSV; xem + nhập bàn giao **phòng mình** nếu nhóm được cấp feature (trừ khi có quyền hậu kiểm) |
| `pho_phong` | Duyệt nghỉ phép bước KSV; xem + nhập bàn giao **phòng mình** nếu nhóm được cấp feature (trừ khi có quyền hậu kiểm) |
| `chuyen_vien` | Nhập bàn giao, xem dữ liệu phòng mình |

**Phân cấp**: `admin > admin_l2 > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien`

> `admin_l2` (Quản trị viên cấp 2) hiển thị chung nhóm "Quản trị viên" như cấp 1, nhưng quyền hạn được cấu hình qua **Phân quyền theo nhóm** thay vì all-access.

**Cấp 2 và màn Phân quyền chức năng** — cấp 2 thấy menu *Phân quyền chức năng* và thao tác như cấp 1
(tạo/sửa/xoá nhóm, thêm bớt thành viên, tick ma trận quyền), trừ hai đường có thể dùng để tự nâng mình
lên gần bằng cấp 1:

| Thao tác | Cấp 1 | Cấp 2 |
|---|---|---|
| Nhóm **không** chứa mình | ✔ | ✔ |
| Nhóm **có** chứa mình (sửa tên, xoá, thành viên, quyền) | ✔ | ✘ 403 — chỉ xem |
| Tự thêm mình vào một nhóm bất kỳ | ✔ | ✘ 403 |

Chặn ở backend (`groups.py::_chan_l2_tu_cap_quyen`), frontend chỉ khoá nút cho khỏi bấm rồi nhận 403.
Hai luật phải đi cùng nhau: nếu chỉ cấm sửa nhóm chứa mình thì cấp 2 lập nhóm mới full quyền rồi tự
thêm mình vào — lúc thêm, nhóm chưa chứa mình. Vẫn còn một đường **không** chặn: hai cấp 2 cấp quyền
chéo cho nhau; đó là chuyện chọn người, không phải chuyện mã.

### Menu sidebar
Menu nhóm theo **chức năng**, không theo phòng ban. Hover để mở flyout bên phải.

```
Quản lý chứng từ ─ Bàn giao chứng từ / Đóng chứng từ / Lưu trữ
Đối chiếu ──────── Phòng Thanh toán ─ Chấm 459901 / Song phương / ACH / CITAD / Đối soát CITAD
                   Phòng Swift ────── Đối chiếu điện SWIFT
Báo cáo ────────── Phòng KSNB & HTVH ─ Báo cáo hậu kiểm / Báo cáo bàn giao chứng từ
                   Phòng Tổng hợp ──── Báo cáo dữ liệu thanh toán
Chấm công & Lịch trực ─ Nghỉ phép
                   Phòng Kế toán ───── Chấm công
                   Phòng Thanh toán ── Phân lịch trực / Sổ trực cuối ngày
Danh sách CN TTQT ─ menu phẳng, không có nhóm cha
```

Tầng "phòng" **chỉ còn ở cấp 2** của Đối chiếu, Báo cáo và Chấm công & Lịch trực, và chỉ liệt kê phòng đang thực sự có tính năng. Trước đây menu chia theo phòng ở cấp 1; cách đó buộc người dùng phải biết chức năng mình cần thuộc phòng nào mới tìm ra.

Một nhóm **chỉ hiện khi user có ít nhất 1 chức năng** bên trong (`menu.<key>`); nhóm con không còn mục nào hiển thị được cũng bị bỏ qua — không dựng mục menu hover ra rỗng. Menu phẳng cấp 1 kiểm feature giống hệt: không có `menu.ttqt_branches` thì không thấy "Danh sách CN TTQT".

Một ngoại lệ: **Chấm công** không gate bằng feature-flag mà theo **phòng** — chỉ nhân viên Phòng Kế toán (`ACCT`) và admin thấy, vì mọi nhân viên phòng đó đều cần xem "Công của tôi" chứ không riêng người được cấp quyền. Nó nằm chung nhóm với các mục gate bằng feature-flag, nên `_dept_group()` nhận thêm tham số `overrides={"attendance": ...}` để đè kết quả kiểm tra của **đúng một khoá** thay vì đổi cách lọc cả nhóm. Ô tick `menu.attendance` ở màn Phân quyền vẫn tồn tại nhưng chỉ để gán 2 quyền con (xem bảng công cả phòng / xuất Excel) — tick hay không **không** làm menu hiện ra với người ngoài phòng ACCT.

Cây menu nằm ở `shared.MENU_TREE`. Phần tử cấp 1 là **tuple** `(key, label, icon)` cho menu phẳng, hoặc **dict** `{"id", "label", "icon", "items"}` cho nhóm. Sâu tối đa 3 tầng — `_dept_group()` không dựng được tầng thứ tư.

Trên cùng là khối **Công việc chờ xử lý**, tự ẩn khi không có việc nào. Dưới nó là **Trang chủ** — hiện với mọi vai trò và mọi vai trò đều vào được.

> **Phân quyền màn hình đi theo nhóm quyền, không theo vai trò.** Các trang Báo cáo, Lưu trữ, Báo cáo bàn giao, Nhân sự, Đóng tập chỉ kiểm `menu.<key>` — giống hệt luật mà backend (`require_feature`) và sidebar đang dùng. Trước đây các trang này còn một lớp chặn cứng theo vai trò chạy **trước** lớp nhóm quyền, khiến quyền admin cấp cho `chuyen_vien` qua nhóm không có tác dụng mà không báo gì. Lớp đó đã gỡ; chỉ `/user-management` còn giữ vì là trang duy nhất không gắn mã feature nào.

### Màn hình Phân quyền theo nhóm
Bố cục **soi gương cây menu sidebar** — admin tick quyền theo đúng thứ user sẽ nhìn thấy. Cấu trúc ở `backend/core/features.py::FEATURE_GROUPS`, hai loại thẻ phân biệt bằng khoá `kind`:

| `kind` | Hình dạng | Dùng cho |
|---|---|---|
| `group` | Thẻ có header đỏ; `sections` gom menu theo phòng (`label=None` = không cần dải nhãn) | Quản lý chứng từ, Đối chiếu, Báo cáo, Chấm công & Lịch trực, Quản lý hệ thống |
| `menu` | Thẻ **không header**, chính ô tick là tiêu đề thẻ | Danh sách CN TTQT |

Dải nhãn phòng **không phải ô tick** — luật *"mỗi ô tick là đúng một mã quyền"* được giữ nguyên, để không có hai loại ô nhìn giống nhau mà ý nghĩa khác nhau. Cạnh dải nhãn có nút **Chọn tất cả / Bỏ chọn**, chỉ tác động lên MENU chứ không tự cấp ACTION — tránh một cú bấm cấp luôn quyền chạy xử lý dữ liệu.

> ⚠️ **`FEATURE_GROUPS` phải phủ kín `FEATURES`** — `_assert_feature_coverage()` kiểm lúc import và **chặn khởi động** nếu thiếu / trùng / thừa mã. Lý do: `PUT /api/groups/{id}/features` xoá sạch quyền của nhóm rồi ghi lại đúng các ô tick đang hiển thị. Mã không được vẽ ra sẽ không nằm trong danh sách gửi lên → lần bấm **Lưu** đầu tiên xoá nó khỏi mọi nhóm, không log, không báo. Vì vậy `_render_features()` và `save_features()` trong `frontend/pages/group_features.py` **phải sửa cùng lượt** — sửa một mà quên cái kia thì quyền mất im lặng.

**Thu gọn / mở rộng**: chỉ bằng nút ở góc trên cùng bên trái. Click vào mục menu chỉ điều hướng, không đổi trạng thái sidebar. Icon nút phản ánh trạng thái hiện tại (`menu_open` khi đang mở, `menu` khi đang thu gọn). Lựa chọn được lưu trong `localStorage` và giữ nguyên khi chuyển trang.

Máy có màn hình rộng **≤ 1440px** (máy trạm 1366×768) mặc định vào đã thu gọn sẵn, nhường thêm ~184px cho vùng nội dung. Chỉ áp dụng khi user chưa từng bấm nút — đã bấm một lần thì lựa chọn đó được tôn trọng ở mọi màn hình.

### Vùng nội dung
Giao diện thiết kế cho **máy trạm desktop**, không có breakpoint mobile. Vùng nội dung rộng `calc(100% - 16rem)` (hoặc `- 4.5rem` khi sidebar thu gọn) và cho **cuộn ngang** khi bảng vượt khung — không cắt bớt nội dung.

Đầu mỗi trang hiển thị **đường dẫn menu** dẫn tới trang đó, ví dụ *Báo cáo / Phòng KSNB & HTVH / **Báo cáo hậu kiểm***. Phần cha in nhỏ màu xám, tên trang giữ cỡ tiêu đề. Đường dẫn **suy ra từ route** rồi tra bảng dựng sẵn từ chính cây menu (`shared.BREADCRUMBS`) — đổi tên một mục trong `MENU_TREE` thì breadcrumb tự đổi theo, không có chỗ thứ hai phải sửa. Trang không nằm trong menu (`/home`, `/user-management`) không hiện phần cha. Menu phẳng cấp 1 (Danh sách CN TTQT) chỉ có 1 đoạn nên cũng không hiện phần cha — nếu hiện sẽ là chính tên trang lặp lại.

> Điều kiện: route của trang phải trùng khoá menu (`@ui.page("/reports")` ↔ khoá `reports`) — ràng buộc này vốn đã có sẵn vì sidebar điều hướng bằng `ui.navigate.to(f"/{key}")`.

**Ô chọn file**: bấm vào **cả dải màu** của ô là mở hộp thoại chọn file, không cần nhắm đúng dấu `+`. Mặc định Quasar chỉ gắn `<input type="file">` vào riêng nút `+`; `ui_kit.install()` nạp một listener ở cấp `document` chuyển tiếp click từ `.q-uploader__header` sang input đó. Áp dụng cho **mọi** `ui.upload` trong dự án, kể cả ô tạo động — không phải sửa gì ở từng trang. Click rơi trúng nút thật (`.q-btn, button, label, input, a`) vẫn giữ hành vi cũ.

### Màn hình đăng nhập
Hai bên ô đăng nhập là **các cụm đường dẫn nhanh** tới hệ thống nghiệp vụ (Thanh toán trong nước / Thanh toán quốc tế / Nội bộ), click mở tab mới. Danh sách để cứng trong `frontend/pages/login.py` chứ không nằm trong DB — cố ý, để trang login **không phụ thuộc backend**: backend chết thì người dùng vẫn mở được CITAD, mail, iOffice.

Bố cục khoá bằng biến CSS (`--pc-row`, `--pc-head`, `--pc-pad`, `--pc-bd`) để các hàng trái/phải luôn ngang nhau. Khoảng cách giữa hai cụm bên phải **tính bằng Python** từ số link mỗi cụm (`_split_gap_css()`) — thêm hoặc bớt link ở cụm nào cũng tự khớp lại.

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

Database SQLite được backup vào `data/backups/` **mỗi lần app khởi động** và sau đó mỗi 24h.
Cấu hình trong `backend/services/backup_service.py`.

**Tiêu chí giữ lại** (hợp của hai tập, giữ cả hai):

| Giữ | Vì sao |
|---|---|
| Bản mới nhất của **mỗi ngày**, trong `_GIU_NGAY = 7` ngày gần nhất | Chiều sâu lịch sử — hỏng DB thường phát hiện muộn |
| `_GIU_GAN_NHAT = 5` bản mới nhất, bất kể ngày | Một ngày khởi động lại nhiều lần thì bản vừa chụp không bị dọn ngay |

> ⚠️ **Chỉ file đúng mẫu `ksnb_YYYYMMDD_HHMM.db` (hoặc `.zip`) mới bị xoá tự động.** Bản đặt tay
> (`ksnb_truoc_nhomA_20260728.db`…) **không bao giờ** bị đụng tới — muốn bỏ thì xoá tay.
> Trước đây luật dọn glob `ksnb_*.db` và sắp **theo tên**: `'2' < 'b' < 't'` nên bản đặt tay
> luôn bị coi là "mới nhất", vừa chiếm chỗ vĩnh viễn vừa làm màn hình Admin báo sai ngày
> backup gần nhất. `tests/test_backup_rotation.py` canh việc này.

**Thư mục backup phụ** (`BACKUP_EXTRA_DIR` trong `.env`, nên đặt ở ổ/máy khác): mỗi bản backup được
chép sang đó rồi **áp cùng luật dọn**. Tức là phần mềm chủ động xoá file trên ổ/máy ngoài — vẫn chỉ
đụng đúng mẫu tên `ksnb_YYYYMMDD_HHMM.db` / `.zip`.

> ⚠️ **Mỗi máy chủ một thư mục riêng.** Hai máy cùng trỏ vào một thư mục thì tên file không phân
> biệt được nguồn, máy này sẽ xoá bản của máy kia mà cả hai đều tưởng mình còn đủ lịch sử.

### Mã hoá bản sao lưu (`BACKUP_PASSWORD`)

Đặt `BACKUP_PASSWORD` trong `.env` thì mỗi bản sao lưu được nén thành `.zip` **mã hoá AES-256**
(mở được bằng 7-Zip/WinRAR sẵn có, không cần công cụ riêng của phần mềm), bản `.db` trần bị xoá
ngay sau đó.

Vì sao cần: file `.db` chứa **nguyên cột `pwd_hash` của toàn bộ tài khoản**. Ai đọc được thư mục
`data/backups` — hoặc share mạng `BACKUP_EXTRA_DIR` — là mang mã băm về dò ngoại tuyến, không cần
quyền gì trong phần mềm.

> ⚠️ **Mất mật khẩu này = không mở được bản sao lưu.** Cất vào két mật khẩu của đơn vị, đừng chỉ để
> trong `.env` trên đúng cái máy mà bản sao lưu dùng để cứu.

Để trống thì **vẫn backup** nhưng ra `.db` không mã hoá, kèm một dòng cảnh báo trong log mỗi lần
chạy — mất bản sao lưu nặng hơn hẳn việc bản sao lưu chưa được mã hoá, nên thiếu cấu hình không
làm dừng việc backup. `tests/test_backup_ma_hoa.py` canh cả hai nhánh.

---

## Word đòi phiên đăng nhập trên máy chủ

**Máy chủ phải có một tài khoản đang đăng nhập** (console hoặc RDP) thì việc xuất đơn nghỉ
phép bản PDF mới chạy. Chạy `start.bat` bằng tay trong phiên đó là đúng cách.

**Không** đưa hệ thống vào Windows Service, cũng không dùng Task Scheduler với tuỳ chọn
*"Run whether user is logged on or not"*. Cả hai đều chạy ở **phiên 0** — phiên không có
màn hình — và Word không làm việc được ở đó.

Đã đo trên chính máy này (chạy dưới `NT AUTHORITY\SYSTEM`, phiên 0):

| Bước | Kết quả ở phiên 0 |
|---|---|
| `New-Object -ComObject Word.Application` | ✅ tạo được, mất 0,59 s |
| `Documents.Open(...)` | ❌ trả về `null` — **không ném lỗi, chỉ trả rỗng** |
| Chuyển sang PDF | ❌ không thực hiện được |

Chỗ khó chịu là bước 1 **thành công**, nên nhìn qua tưởng Word chạy tốt. Chỉ tới lúc mở tài
liệu mới hỏng, mà lại hỏng kiểu trả `null` chứ không báo lỗi.

**Hỏng thì hệ thống không đứng lại**: API trả 503, giao diện tự lui về tải bản `.docx` và vẫn
duyệt đơn được, chỉ là không có chữ ký trên bản in. Trong log sẽ thấy nguyên văn:

> Word mo len duoc nhung KHONG mo duoc tai lieu. Thuong gap khi backend chay o phien khong co
> nguoi dang nhap...

> 💡 Máy chủ hay bị khoá màn hình hoặc mất phiên RDP: khoá màn hình **vẫn giữ phiên**, không
> sao. Nhưng *đăng xuất* (Sign out) thì mất phiên — sau khi khởi động lại máy, phải đăng nhập
> rồi chạy lại `start.bat`.

## Truy cập LAN (nhiều người dùng)

Mở firewall port 8080:

```bash
# Windows
netsh advfirewall firewall add rule name="TTTT" dir=in action=allow protocol=TCP localport=8080
```

> Chỉ cần mở 8080. Trình duyệt người dùng **không bao giờ gọi thẳng cổng 8000** — frontend
> gọi backend qua loopback trong cùng máy chủ. Mở thêm 8000 chỉ để lộ API ra mạng mà không
> được lợi ích gì; nếu không có hệ thống nào khác cần, đặt luôn `BACKEND_HOST=127.0.0.1`.

Người dùng khác truy cập: `http://[IP-máy-chủ]:8080`

Đặt trong `.env` — quên là trang liệt kê toàn bộ endpoint bị mở công khai ra mạng:

```ini
BACKEND_HOST=127.0.0.1                       # cổng backend chỉ nghe trong máy chủ
ENV=production                               # tắt /docs, /redoc, /openapi.json
```

Chỉ thêm `ALLOWED_ORIGINS=http://192.168.1.100:8080` khi thật sự phải để `BACKEND_HOST=0.0.0.0`
cho một hệ thống khác gọi thẳng API — nhiều giá trị cách nhau dấu phẩy.

Hai biến nữa có mặc định an toàn, chỉ đặt khi cần đổi:

```ini
MAX_UPLOAD_MB=200          # trần MỘT file tải lên; MAX_REQUEST_MB=600 cho cả thân request
TRUSTED_PROXY_IPS=         # máy được phép khai IP hộ qua X-Client-IP (loopback đã có sẵn)
```

> Chỉ điền `TRUSTED_PROXY_IPS` khi đặt nginx/IIS **trước cổng backend**. Máy không nằm trong danh
> sách mà gửi `X-Client-IP` thì backend bỏ qua và ghi IP thật của kết nối — nếu không, nhật ký
> truy vết có thể do chính người bị truy vết viết ra.

Backend tự **cảnh báo trong log khi khởi động** nếu đang lắng nghe trên mạng mà hai biến này chưa đặt đúng.
`deploy.bat` cũng kiểm `.env` của máy đích ở bước 1/8 và hỏi trước khi sửa, nên không phải nhớ thủ công.

---

## Lệnh thường dùng

```bash
# Cài thư viện (đúng những gì máy chính cần)
pip install -r requirements.txt

# Máy phát triển: thêm pytest (đã gồm sẵn requirements.txt)
pip install -r requirements-dev.txt

# Chạy test
python -m pytest -q

# Khởi tạo DB lần đầu
python init_db.py

# Chạy toàn bộ hệ thống
python run.py

# Chạy backend riêng (development)
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Chạy frontend riêng
python frontend/main.py
```
