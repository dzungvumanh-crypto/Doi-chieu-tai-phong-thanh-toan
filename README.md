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
ENV=production                                  # tắt /docs, /redoc, /openapi.json
```

> `ALLOWED_ORIGINS` **chỉ cần khi có máy khác gọi thẳng cổng 8000 từ trình duyệt.** Với
> `BACKEND_HOST=127.0.0.1` (mặc định `start.bat` sinh ra) thì không cần đặt: trình duyệt
> chỉ nói chuyện với frontend cổng 8080, CORS không tham gia vào đường đi nào cả.

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
│   └── ksnb.db             # SQLite database (tự tạo khi chạy lần đầu)
├── logs/
│   ├── app.log             # Log xoay vòng (5 MB × 3 file) — nguồn của màn hình Nhật ký hệ thống
│   ├── backend.log         # stdout/stderr tiến trình backend (run.py ghi) — không xoay vòng
│   ├── frontend.log        # stdout/stderr tiến trình frontend (run.py ghi) — không xoay vòng
│   └── *.truoc-utf8.log    # Phần log ghi trước bản vá UTF-8, run.py tự tách ra một lần
├── init_db.py               # Khởi tạo DB + seed data
├── run.py                   # Launcher (chạy backend + frontend song song; ép UTF-8 cho tiến trình con)
├── deploy_env_check.py      # Kiểm/sửa .env máy đích khi deploy (deploy.bat gọi)
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
- **Trạng thái tài khoản** — cột `user_tttt.is_active` cho phép NULL (dữ liệu cũ, đường *Nhập DB*). **NULL = tạm khoá**, thống nhất với `WHERE is_active = 1` ở đăng nhập và danh sách cán bộ; migration lúc khởi động ghi hẳn về `0`, `StaffOut` cũng ép NULL → `False` để một dòng bỏ trống không làm hỏng cả response `/api/staff/`

### Module Nghỉ phép
- Cán bộ tạo đơn xin nghỉ (phép năm, ốm, việc riêng, khác)
- Workflow duyệt 3 bước: **KSV → Tổng hợp → Giám đốc**
- Ủy quyền Giám đốc: GĐ có thể ủy quyền cho PGĐ trong khoảng thời gian xác định
- Tải phiếu nghỉ phép dạng `.docx` đúng mẫu
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
- **Lưu trữ**: Ghi số hộp, vị trí kệ; tra cứu theo phòng/thời gian; bảng tổng hợp cả năm (số tờ/số tập theo phòng × 12 tháng); sửa số chứng từ ngay trên bảng — nhập vào ô trống để thêm tập, sửa về 0 để xoá tập, số tập/tổng tự cập nhật
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
- **Sửa tay** thành phần ca: vai song phương hệ thống tự suy từ cờ "biết song phương",
  số ca trong vòng xoay đi theo người được đổi. Sửa xong ca quay về bản thảo, phải xác nhận lại
- Quản lý cán bộ trực, ràng buộc lịch trực (ngày không trực, giới hạn ca)
- Thống kê số ca trực theo cán bộ, theo tháng — **trực chính và trực phụ đếm 2 cột riêng**, không quy đổi
- Xuất lịch trực ra file
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
- Menu: **Đối chiếu → Phòng Thanh toán → Đối chiếu ACH**
- Upload bộ file 1 ngày: `GL02*.zip`, file GW `.xlsx`, 2 file `*_DI_*.zip`, 2 file `*_DEN_*.zip`,
  PDF sao kê ACH (lấy số session + suy ngày đối chiếu). Mỗi file gửi lên ngay khi chọn, ghi thẳng
  ra đĩa theo khối 1 MB — không giữ cả bộ 150–250 MB trong RAM
- Ngày đối chiếu suy từ tên file PDF (`ACH_YYYYMMDD_..._NRT_<session>_...` → ngày T-1), nhập tay được;
  không suy được thì **báo lỗi**, không lặng lẽ dùng ngày khác
- Khớp theo số lượng cặp khoá: chiều ĐI `TRBRCD+SO_TRACE+CRAMOUNT` ↔ `CHI_NHANH+SO_TRACE+SO_TIEN`,
  chiều ĐẾN `SO_TRACE+DRAMOUNT` ↔ `TRACE+SO_TIEN`. Lệnh TPAY vượt số slot GW được tách ra sheet
  **TIMEOUT_KHONG_KENH** (đánh dấu `CO_TRONG_GW` nếu MSGREF vẫn có trong GW → cần kiểm tra tay)
- Kết quả: 1 file Excel 11 sheet (TONG_KET, PHAN_TICH có cảnh báo tự động, các sheet khớp/thừa,
  CAP_CN_TIEN, RAW_GW); sheet trên **15.000 dòng** tự tách ra CSV riêng, tải lẻ hoặc tải gộp ZIP
- Chạy nền trên **1 luồng riêng** (`max_workers=1`) — job thứ hai xếp hàng; theo dõi tiến độ + nhật ký
  bằng poll, có nút Dừng (dừng ở mốc kiểm tra giữa các pha, không tức thì)
- Kết quả giữ **4 giờ** trong `data/temp_doi_chieu_ach/` rồi tự xoá; không lưu lịch sử vào DB
- Phân quyền riêng theo nhóm (`menu.doi_chieu_ach`, `doi_chieu_ach.process`)

### Module Đối chiếu CITAD ↔ PaymentHub
- Đối chiếu số liệu tổng CITAD (NHNN) với PaymentHub (Agribank) theo từng ngày
- Menu: **Đối chiếu → Phòng Thanh toán → Đối chiếu CITAD**
- Nhập tay 5 cổng CITAD × 3 loại tiền × 8 trường; chênh lệch tính lại ngay khi gõ
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
- Phân quyền riêng theo nhóm (`menu.doi_soat_citad`)

---

## Phân quyền (RBAC)

| Vai trò | Mô tả |
|---|---|
| `admin` | **Quản trị viên cấp 1** — toàn quyền hệ thống, quản lý tài khoản & phân quyền nhóm. **Ngoại lệ: chỉ đọc ở Bàn giao chứng từ** |
| `admin_l2` | **Quản trị viên cấp 2** — quyền theo nhóm chức năng được gán; không thuộc phòng nào; không được tạo/sửa/xóa tài khoản cấp 1 |
| `hau_kiem_vien` | Quyền hậu kiểm (xác nhận, gom tập, in bìa) |
| `giam_doc` | Duyệt nghỉ phép bước cuối; xem toàn bộ màn hình. **Chỉ đọc ở Bàn giao chứng từ** (xem mọi phòng) |
| `pho_giam_doc` | Duyệt thay GĐ khi có ủy quyền còn hiệu lực. **Chỉ đọc ở Bàn giao chứng từ** (xem mọi phòng) |
| `truong_phong` | Duyệt nghỉ phép bước KSV; xem + nhập bàn giao **phòng mình** nếu nhóm được cấp feature (trừ khi có quyền hậu kiểm) |
| `pho_phong` | Duyệt nghỉ phép bước KSV; xem + nhập bàn giao **phòng mình** nếu nhóm được cấp feature (trừ khi có quyền hậu kiểm) |
| `chuyen_vien` | Nhập bàn giao, xem dữ liệu phòng mình |

**Phân cấp**: `admin > admin_l2 > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien`

> `admin_l2` (Quản trị viên cấp 2) hiển thị chung nhóm "Quản trị viên" như cấp 1, nhưng quyền hạn được cấu hình qua **Phân quyền theo nhóm** thay vì all-access.

### Menu sidebar
Menu nhóm theo **chức năng**, không theo phòng ban. Hover để mở flyout bên phải.

```
Quản lý chứng từ ─ Bàn giao chứng từ / Đóng chứng từ / Lưu trữ
Đối chiếu ──────── Phòng Thanh toán ─ Chấm 459901 / Song phương / ACH / CITAD / Đối soát CITAD
                   Phòng Swift ────── Đối chiếu điện SWIFT
Báo cáo ────────── Phòng KSNB & HTVH ─ Báo cáo hậu kiểm / Báo cáo bàn giao chứng từ
                   Phòng Tổng hợp ──── Báo cáo dữ liệu thanh toán
Nghỉ phép                    ┐
Phân lịch trực               ├ menu phẳng, không có nhóm cha
Danh sách CN TTQT            ┘
```

Tầng "phòng" **chỉ còn ở cấp 2** của Đối chiếu và Báo cáo, và chỉ liệt kê phòng đang thực sự có tính năng. Trước đây menu chia theo phòng ở cấp 1; cách đó buộc người dùng phải biết chức năng mình cần thuộc phòng nào mới tìm ra.

Một nhóm **chỉ hiện khi user có ít nhất 1 chức năng** bên trong (`menu.<key>`); nhóm con không còn mục nào hiển thị được cũng bị bỏ qua — không dựng mục menu hover ra rỗng. Menu phẳng cấp 1 kiểm feature giống hệt: không có `menu.leaves` thì không thấy "Nghỉ phép".

Cây menu nằm ở `shared.MENU_TREE`. Phần tử cấp 1 là **tuple** `(key, label, icon)` cho menu phẳng, hoặc **dict** `{"id", "label", "icon", "items"}` cho nhóm. Sâu tối đa 3 tầng — `_dept_group()` không dựng được tầng thứ tư.

Trên cùng là khối **Công việc chờ xử lý**, tự ẩn khi không có việc nào. Dưới nó là **Trang chủ** — hiện với mọi vai trò và mọi vai trò đều vào được.

> **Phân quyền màn hình đi theo nhóm quyền, không theo vai trò.** Các trang Báo cáo, Lưu trữ, Báo cáo bàn giao, Nhân sự, Đóng tập chỉ kiểm `menu.<key>` — giống hệt luật mà backend (`require_feature`) và sidebar đang dùng. Trước đây các trang này còn một lớp chặn cứng theo vai trò chạy **trước** lớp nhóm quyền, khiến quyền admin cấp cho `chuyen_vien` qua nhóm không có tác dụng mà không báo gì. Lớp đó đã gỡ; chỉ `/user-management` còn giữ vì là trang duy nhất không gắn mã feature nào.

### Màn hình Phân quyền theo nhóm
Bố cục **soi gương cây menu sidebar** — admin tick quyền theo đúng thứ user sẽ nhìn thấy. Cấu trúc ở `backend/core/features.py::FEATURE_GROUPS`, hai loại thẻ phân biệt bằng khoá `kind`:

| `kind` | Hình dạng | Dùng cho |
|---|---|---|
| `group` | Thẻ có header đỏ; `sections` gom menu theo phòng (`label=None` = không cần dải nhãn) | Quản lý chứng từ, Đối chiếu, Báo cáo, Quản lý hệ thống |
| `menu` | Thẻ **không header**, chính ô tick là tiêu đề thẻ | Nghỉ phép, Phân lịch trực, Danh sách CN TTQT |

Dải nhãn phòng **không phải ô tick** — luật *"mỗi ô tick là đúng một mã quyền"* được giữ nguyên, để không có hai loại ô nhìn giống nhau mà ý nghĩa khác nhau. Cạnh dải nhãn có nút **Chọn tất cả / Bỏ chọn**, chỉ tác động lên MENU chứ không tự cấp ACTION — tránh một cú bấm cấp luôn quyền chạy xử lý dữ liệu.

> ⚠️ **`FEATURE_GROUPS` phải phủ kín `FEATURES`** — `_assert_feature_coverage()` kiểm lúc import và **chặn khởi động** nếu thiếu / trùng / thừa mã. Lý do: `PUT /api/groups/{id}/features` xoá sạch quyền của nhóm rồi ghi lại đúng các ô tick đang hiển thị. Mã không được vẽ ra sẽ không nằm trong danh sách gửi lên → lần bấm **Lưu** đầu tiên xoá nó khỏi mọi nhóm, không log, không báo. Vì vậy `_render_features()` và `save_features()` trong `frontend/pages/group_features.py` **phải sửa cùng lượt** — sửa một mà quên cái kia thì quyền mất im lặng.

**Thu gọn / mở rộng**: chỉ bằng nút ở góc trên cùng bên trái. Click vào mục menu chỉ điều hướng, không đổi trạng thái sidebar. Icon nút phản ánh trạng thái hiện tại (`menu_open` khi đang mở, `menu` khi đang thu gọn). Lựa chọn được lưu trong `localStorage` và giữ nguyên khi chuyển trang.

Máy có màn hình rộng **≤ 1440px** (máy trạm 1366×768) mặc định vào đã thu gọn sẵn, nhường thêm ~184px cho vùng nội dung. Chỉ áp dụng khi user chưa từng bấm nút — đã bấm một lần thì lựa chọn đó được tôn trọng ở mọi màn hình.

### Vùng nội dung
Giao diện thiết kế cho **máy trạm desktop**, không có breakpoint mobile. Vùng nội dung rộng `calc(100% - 16rem)` (hoặc `- 4.5rem` khi sidebar thu gọn) và cho **cuộn ngang** khi bảng vượt khung — không cắt bớt nội dung.

Đầu mỗi trang hiển thị **đường dẫn menu** dẫn tới trang đó, ví dụ *Báo cáo / Phòng KSNB & HTVH / **Báo cáo hậu kiểm***. Phần cha in nhỏ màu xám, tên trang giữ cỡ tiêu đề. Đường dẫn **suy ra từ route** rồi tra bảng dựng sẵn từ chính cây menu (`shared.BREADCRUMBS`) — đổi tên một mục trong `MENU_TREE` thì breadcrumb tự đổi theo, không có chỗ thứ hai phải sửa. Trang không nằm trong menu (`/home`, `/user-management`) không hiện phần cha. Menu phẳng cấp 1 (Nghỉ phép, Phân lịch trực…) chỉ có 1 đoạn nên cũng không hiện phần cha — nếu hiện sẽ là chính tên trang lặp lại.

> Điều kiện: route của trang phải trùng khoá menu (`@ui.page("/reports")` ↔ khoá `reports`) — ràng buộc này vốn đã có sẵn vì sidebar điều hướng bằng `ui.navigate.to(f"/{key}")`.

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

Database SQLite được backup tự động vào thư mục `data/backups/`. Lịch backup cấu hình trong `backend/services/backup_service.py`.

---

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

Backend tự **cảnh báo trong log khi khởi động** nếu đang lắng nghe trên mạng mà hai biến này chưa đặt đúng.
`deploy.bat` cũng kiểm `.env` của máy đích ở bước 1/7 và hỏi trước khi sửa, nên không phải nhớ thủ công.

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
