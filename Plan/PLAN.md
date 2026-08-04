> ⚠️ **TÀI LIỆU LỊCH SỬ — KHÔNG DÙNG LÀM THAM CHIẾU KỸ THUẬT.**
> Viết cho `KSNB-main` (11/05/2026). Đường dẫn file và số dòng không còn đúng.
> Bảng `ksnb_staff` nhắc trong file này **nay tên là `user_tttt`**.
> Tham chiếu đang dùng: `CLAUDE.md`, `DESIGN.md`.

# PLAN.md — Kế hoạch cải tiến hệ thống KSNB&HTVH

> Agribank – Trung tâm Thanh toán  
> Phân tích dựa trên source code tại `KSNB-main/` (commit 2026-05-11)  
> **Đánh giá & hiệu chỉnh lần 1: 2026-05-12** — đối chiếu với source thực tế

---

## Tóm tắt

| Pha | Thời gian | Số việc còn lại | Mức độ |
|-----|-----------|---------|--------|
| 1 – Hotfix & Nợ kỹ thuật | Ngay bây giờ | 5 | 🔴 Khẩn cấp |
| 2 – Cải tiến chức năng hiện có | 1–2 tháng | 5 *(2 đã xong)* | 🟡 Quan trọng |
| 3 – Tính năng mới | 2–4 tháng | 6 | 🔵 Cao |
| 4 – Nâng cấp kiến trúc | Dài hạn | 4 | 🟢 Chiến lược |

---

## Đã làm xong nhưng plan chưa cập nhật

| Hạng mục | Thực trạng |
|---|---|
| **2.7** UI lịch sử thao tác | ✅ ĐÃ XONG — `history_dialog` ở main.py:2527, gọi `/api/handovers/entries/{entry_id}/history` |
| **2.5** Calendar view nghỉ phép | ✅ ĐÃ XONG — `GET /api/leaves/calendar` tồn tại (leaves.py:312), UI gọi từ main.py:3118 |
| **2.4** Xuất Excel nghỉ phép & bàn giao | ✅ ĐÃ XONG — `/api/leaves/export` (leaves.py:366) và `/api/handovers/export` (handovers.py:529) |
| **3.2** Borrow/return API | ✅ ĐÃ XONG — 4 endpoint: `/borrow`, `/handback`, `/confirm-returned`, `/reject` (handovers.py:280–360) |
| **1.5** Error boundary cơ bản | ✅ ĐÃ CÓ — `_handle_api_error()` ở main.py dùng rộng rãi; redirect SessionExpiredError → /login |

**Kết luận:** Pha 2 thực tế đã hoàn thành ~5/7 mục thay vì 0/7 như plan ước tính ban đầu.

---

## Pha 1 — Hotfix & Nợ kỹ thuật nghiêm trọng

> **Thứ tự thực hiện đã điều chỉnh:** Security trước Maintainability.  
> Thứ tự mới: **1.3 → 1.2 → 1.4 → 1.5 → 1.1**

### 1.1 Tách `frontend/main.py` (3 513 dòng) thành các module riêng

**Vấn đề:** File duy nhất 3 513 dòng không thể bảo trì, dễ gây conflict khi nhiều người chỉnh sửa, IDE không thể navigate hiệu quả.

**Giải pháp:** Tách theo trang vào thư mục `frontend/pages/`:

```
frontend/
├── main.py              # Chỉ còn: _sidebar(), routes, ui.run()  (~200 dòng)
└── pages/
    ├── dashboard.py     # Trang chủ + KPI
    ├── staff.py         # Quản lý cán bộ KSNB + user management
    ├── source_users.py  # Danh sách giao dịch viên
    ├── handovers.py     # Bàn giao chứng từ
    ├── bundles.py       # Đóng tập + in bìa
    ├── storage.py       # Lưu trữ + tra cứu
    ├── leaves.py        # Nghỉ phép (đăng ký + duyệt)
    └── logs.py          # Nhật ký đăng nhập
```

> **Lưu ý kỹ thuật:** `frontend/pages/` đã tồn tại nhưng rỗng. Mỗi pages/\*.py export 1 hàm `register_page()` gọi `@ui.page(...)`. Shared helpers (`_sidebar`, `_handle_api_error`, `api`) giữ trong `main.py`. Tách từng trang một, test ngay sau mỗi trang.

**Ưu tiên:** Làm cuối Pha 1 (sau các mục security).

---

### 1.2 Session in-memory mất khi restart server

**Vấn đề:** `backend/core/sessions.py` lưu session map trong RAM. Mỗi lần restart server → toàn bộ user bị đăng xuất đột ngột, JWT còn hiệu lực nhưng server trả 401.

**Giải pháp:** Persist session vào bảng SQLite mới:

```sql
CREATE TABLE active_sessions (
    token_jti   TEXT PRIMARY KEY,
    staff_id    INTEGER NOT NULL,
    ip_address  TEXT,
    created_at  DATETIME,
    expires_at  DATETIME
);
```

Thêm cleanup job xóa session hết hạn khi khởi động (`_ensure_indexes()`). Migration thêm vào `schema_migrations` theo pattern hiện có.

---

### 1.3 Mật khẩu mặc định hardcode trong `init_db.py`

**Vấn đề:** `init_db.py` tạo tài khoản `admin/Admin@2024!`, `kiensoat1/Ksnb@2024!`, và các GDV với mật khẩu cố định. Nếu không đổi → lỗ hổng bảo mật nghiêm trọng trên LAN.

**Giải pháp:**

1. Thêm cột `must_change_password: bool = True` vào `KSNBStaff`.
2. Sau đăng nhập thành công, nếu `must_change_password=True` → redirect bắt buộc đến trang đổi mật khẩu trước khi vào bất kỳ trang nào khác.
3. `init_db.py` in rõ cảnh báo: `⚠ Hãy đổi mật khẩu ngay sau lần đăng nhập đầu tiên!`
4. Schema migration: `ALTER TABLE ksnb_staff ADD COLUMN must_change_password BOOLEAN DEFAULT 0`.

> **Ưu tiên cao nhất trong Pha 1 — thực hiện trước.**

---

### 1.4 Không có cơ chế backup tự động

**Vấn đề:** Toàn bộ dữ liệu nghiệp vụ trong file `data/ksnb.db` duy nhất. Không có backup → mất file là mất tất cả.

> **Lưu ý:** `backend/api/logs.py` đã có logic backup on-demand (tải về client). Cần bổ sung backup định kỳ lưu trên server.

**Giải pháp:** Thêm `backend/services/backup_service.py`:

```python
import shutil, threading
from pathlib import Path
from datetime import datetime

def _rotate_backups(backup_dir: Path, keep: int = 7):
    backups = sorted(backup_dir.glob("ksnb_*.db"))
    for old in backups[:-keep]:
        old.unlink()

def daily_backup(db_path: str, backup_dir: str = "data/backups"):
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    dst = Path(backup_dir) / f"ksnb_{stamp}.db"
    shutil.copy2(db_path, dst)
    _rotate_backups(Path(backup_dir))
```

Gọi khi khởi động app và schedule bằng `threading.Timer` mỗi 24 giờ. Hiển thị "Backup gần nhất" ở trang Admin.

---

### 1.5 Thiếu error boundary toàn cục

**Hiện trạng:** `_handle_api_error()` đã tồn tại trong `frontend/main.py` và được dùng rộng rãi — xử lý `SessionExpiredError` → redirect `/login`, hiện toast lỗi cho exception khác.

**Việc còn lại:** Audit các `on_click` handler còn thiếu `try/except + _handle_api_error(e)`.

> **Không cần** viết `_safe_call()` mới như kế hoạch gốc — sẽ conflict với pattern hiện có.

---

## Pha 2 — Cải tiến chức năng hiện có (1–2 tháng)

### ✅ 2.5 Lịch nghỉ phép trực quan — ĐÃ HOÀN THÀNH

Backend: `GET /api/leaves/calendar` (leaves.py:312). UI: đã render trong frontend/main.py:3118. **Xóa khỏi backlog.**

### ✅ 2.7 Giao diện lịch sử thao tác chứng từ — ĐÃ HOÀN THÀNH

Backend: `GET /api/handovers/entries/{entry_id}/history` (handovers.py:426). UI: `history_dialog` + timeline drawer tại main.py:2527. **Xóa khỏi backlog.**

---

### 2.1 Nhập liệu bàn giao từ file Excel

**Giá trị:** Cao nhất trong pha này. Hiện tại phải nhập tay từng dòng (user × ngày × số tờ). Excel sẽ tiết kiệm ~80% thời gian nhập liệu.

**Thiết kế:**

- Endpoint: `POST /api/handovers/{id}/import-excel`
- Template Excel chuẩn: cột A = `user_code`, cột B = `transaction_date` (dd/mm/yyyy), cột C = `sheet_count`, cột D = `notes` (tuỳ chọn)
- Validate: user_code tồn tại trong phòng, ngày hợp lệ, sheet_count > 0
- Trả về summary: `{imported: 45, skipped: 2, errors: [...]}`
- UI: nút "Nhập từ Excel" + dialog upload + preview trước khi lưu

Thư viện: `openpyxl` (đã có trong requirements).

---

### 2.2 Biểu đồ thống kê trên Dashboard

**Vấn đề:** Dashboard hiện chỉ có 4 KPI dạng số. Không có xu hướng hay so sánh trực quan.

**Bổ sung:**

- Biểu đồ cột: số tờ bàn giao theo phòng, theo tháng trong năm hiện tại
- Biểu đồ tròn: tỷ lệ trạng thái chứng từ (`confirmed` / `pending_confirm` / `borrowed`)
- Line chart: số đơn phép theo tháng (approved / rejected)

**Cách triển khai:** NiceGUI 1.4.37 hỗ trợ `ui.echart()` (Apache ECharts). Thêm endpoint `GET /api/dashboard/charts?year=2026` trả JSON theo format ECharts.

---

### 2.3 Tìm kiếm chứng từ nâng cao

**Vấn đề:** Hiện chỉ lọc theo phòng + ngày bàn giao. Không thể tìm theo user, số tờ, hay trạng thái.

**Endpoint mới:** `GET /api/documents/search`

```
Params: department_id, user_code, date_from, date_to,
        sheet_min, sheet_max, entry_status, text (full-text)
```

> **Lưu ý:** Không dùng SQLite FTS5 (chưa setup). Filter bằng SQLAlchemy `LIKE` là đủ cho quy mô hiện tại.

**UI:** Thanh tìm kiếm mở rộng được (collapsed by default) với các filter chip. Kết quả hiển thị dạng bảng phân trang.

---

### 2.4 Xuất báo cáo Excel và PDF

> **Cập nhật:** `/api/leaves/export` (Excel) và `/api/handovers/export` (Excel) đã tồn tại. Còn thiếu: PDF bìa tập và PDF phiếu nghỉ phép.

| Báo cáo | Endpoint | Format | Trạng thái |
|---------|----------|--------|-----------|
| Danh sách nghỉ phép theo tháng | `GET /api/leaves/export?month=&year=` | Excel | ✅ Có |
| Thống kê tờ bàn giao theo phòng | `GET /api/handovers/export?month=&year=` | Excel | ✅ Có |
| Bìa tập chứng từ | `GET /api/bundles/{id}/cover` | DOCX | ✅ Có |
| Bìa tập chứng từ (PDF) | `GET /api/bundles/{id}/cover.pdf` | PDF | ❌ Chưa |
| Phiếu đăng ký nghỉ phép (PDF) | Đã có `.docx`, thêm `.pdf` | PDF | ❌ Chưa |

> **Cảnh báo:** `weasyprint` (đề xuất trong kế hoạch gốc) **không khả thi trên Windows** — yêu cầu Cairo/Pango binary không có installer Python thuần. Thay bằng `reportlab` hoặc `fpdf2` (pure Python).

---

### 2.6 Thông báo in-app real-time

**Vấn đề:** Sidebar badge hiện đã đếm pending, nhưng chỉ refresh khi load trang. User không biết có việc mới khi đang ở trang khác.

**Giải pháp:**

1. Thêm background task polling `/api/dashboard/pending-counts` mỗi 30 giây.
2. So sánh với giá trị trước: nếu tăng → `ui.notify("Có đơn phép mới chờ duyệt", type="info")`.
3. Cập nhật badge số tự động không cần refresh trang.

NiceGUI hỗ trợ `ui.timer()` cho polling background.

---

## Pha 3 — Tính năng mới (2–4 tháng)

### 3.1 Thông báo email khi đơn phép thay đổi trạng thái

**Trigger gửi email:**

| Sự kiện | Người nhận |
|---------|-----------|
| Đơn mới tạo | KSV phụ trách |
| KSV duyệt | Người nộp đơn |
| KSV từ chối | Người nộp đơn |
| TH chuyển GĐ | GĐ/PGĐ được chọn |
| GĐ phê duyệt | Người nộp + KSV |
| GĐ từ chối | Người nộp đơn |

**Cấu hình** trong `backend/core/config.py`:
```python
SMTP_HOST: str = ""
SMTP_PORT: int = 587
SMTP_USER: str = ""
SMTP_PASSWORD: str = ""
EMAIL_FROM: str = "ksnb@agribank.com.vn"
EMAIL_ENABLED: bool = False  # Tắt mặc định nếu chưa cấu hình
```

> **Lưu ý:** SMTP internal Agribank có thể yêu cầu certificate riêng. Test trên môi trường thực trước khi deploy.

Nếu `EMAIL_ENABLED=False` hoặc email nhân viên trống → bỏ qua, không raise lỗi.

---

### 3.2 Module mượn/trả chứng từ đầy đủ

> **Cập nhật:** 4 endpoint đã tồn tại: `/borrow` (handovers.py:280), `/handback` (handovers.py:317), `/confirm-returned` (handovers.py:354), `/reject` (handovers.py:360). Còn thiếu: model `BorrowRecord` và trang UI tổng hợp.

**Bổ sung model `BorrowRecord`:**

```python
class BorrowRecord(Base):
    __tablename__ = "borrow_records"
    id              = Column(Integer, primary_key=True)
    entry_id        = Column(Integer, ForeignKey("document_entries.id"))
    borrower_id     = Column(Integer, ForeignKey("ksnb_staff.id"))
    borrow_date     = Column(Date)
    expected_return = Column(Date)
    actual_return   = Column(Date, nullable=True)
    reason          = Column(Text)
    approved_by_id  = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)
```

**Thêm trang "Chứng từ đang mượn":**
- Danh sách tất cả entry đang `borrowed`
- Highlight màu đỏ nếu quá hạn trả (> ngày hẹn)
- Nút "Xác nhận đã trả" cho HKV
- Thống kê: tổng đang mượn, quá hạn, trả đúng hạn trong tháng

---

### 3.3 Progressive Web App (PWA) cho mobile

**Mục tiêu:** GĐ/PGĐ có thể duyệt đơn phép trên điện thoại mà không cần mở máy tính.

**Các bước:**

1. Thêm `manifest.json` (tên app, icon, màu theme Agribank `#8B0000`)
2. Thêm service worker cơ bản (cache trang login + trang duyệt phép)
3. Tối ưu layout responsive: sidebar thu gọn thành hamburger menu trên màn < 768px
4. Trang duyệt phép tối giản cho mobile: chỉ hiện thông tin quan trọng + nút Duyệt/Từ chối

> **Rủi ro cao:** NiceGUI dùng WebSocket — service worker khó cache nội dung động. Chỉ cache trang login offline là thực sự khả thi. Cân nhắc kỹ trước khi đầu tư.

NiceGUI cho phép inject custom HTML/JS vào `<head>` qua `app.add_static_file()`.

---

### 3.4 Quản lý hộp lưu trữ và tra cứu vị trí

**Vấn đề:** `storage_box` và `storage_location` hiện chỉ là text field tự do trên Bundle. Không có quản lý tập trung.

**Bổ sung model `StorageBox`:**

```python
class StorageBox(Base):
    __tablename__ = "storage_boxes"
    id          = Column(Integer, primary_key=True)
    box_code    = Column(String(20), unique=True)   # VD: H2025-001
    shelf       = Column(String(50))                # Kệ A, tầng 3
    room        = Column(String(100))               # Phòng lưu trữ tầng 2
    year        = Column(Integer)
    is_full     = Column(Boolean, default=False)
    note        = Column(Text, nullable=True)
```

**Tính năng tra cứu:** Nhập mã hộp → xem danh sách tập bên trong, phòng + khoảng ngày chứng từ.

**QR code:** Mỗi hộp có QR link `http://[server]:8080/storage/box/H2025-001`. Thêm thư viện `qrcode` vào requirements (pure Python).

---

### 3.5 Báo cáo tổng hợp cuối năm tự động

**Nội dung báo cáo Excel (multi-sheet):**

- Sheet 1: Thống kê tờ bàn giao theo phòng × tháng (pivot table)
- Sheet 2: Danh sách nghỉ phép toàn đơn vị theo loại
- Sheet 3: Số lần mượn/trả chứng từ theo phòng
- Sheet 4: Tỷ lệ bàn giao đúng ngày (so với deadline T+1)

Endpoint: `GET /api/reports/annual?year=2026` → file Excel với charts nhúng.

Thư viện: `openpyxl` (đã có).

---

### 3.6 QR code trên bìa tập chứng từ

**Giá trị:** Khi kiểm kho, quét QR → mở ngay trang chi tiết tập đó, thay vì phải tìm thủ công.

**Cách triển khai:**

```python
import qrcode, io

def _add_qr_to_cover(doc, bundle_id: int, server_url: str):
    url = f"{server_url}/bundles/{bundle_id}"
    qr = qrcode.make(url)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    doc.add_picture(buf, width=Inches(1.2))
```

Thêm `server_url` vào `config.py` (mặc định `http://localhost:8080`). Thêm `qrcode` vào requirements.

---

## Pha 4 — Nâng cấp kiến trúc (Dài hạn)

### 4.1 Migrate SQLite → PostgreSQL

**Khi nào cần:** Khi số user đồng thời > 20 hoặc volume > 5 000 phiếu bàn giao/tháng.

**Công việc:**
- Thay `sqlite:///./data/ksnb.db` → `postgresql+psycopg2://...` trong `database.py`
- Xóa các PRAGMA SQLite-specific (`PRAGMA foreign_keys`, `PRAGMA journal_mode=WAL`)
- Kiểm tra lại các raw SQL trong `schema_migrations` (AUTOINCREMENT → SERIAL)
- Viết script migrate data: `python tools/migrate_to_pg.py`

SQLAlchemy đã trừu tượng hóa phần lớn — thay đổi tối thiểu.

---

### 4.2 Bộ test tự động (pytest + httpx)

> **Khuyến nghị:** Bắt đầu sớm hơn kế hoạch gốc — viết song song với Pha 1-2.

**Ưu tiên test theo rủi ro nghiệp vụ:**

```
tests/
├── unit/
│   ├── test_bundle_service.py   # Thuật toán gom tập — nghiệp vụ cốt lõi
│   ├── test_leave_days.py       # calculate_leave_days() + ngày lễ
│   └── test_cover_service.py   # Tạo bìa Word
└── integration/
    ├── test_leave_workflow.py   # 6 trạng thái: pending_ksv → approved/rejected
    ├── test_auth.py             # Login, JWT, session, RBAC
    └── test_handover_flow.py   # Bàn giao → gom tập → in bìa
```

Target coverage: **70%** (tập trung vào business logic, không cần test UI).

```bash
pip install pytest httpx pytest-asyncio
pytest tests/ -v --cov=backend --cov-report=html
```

---

### 4.3 Docker hóa + CI/CD

**`Dockerfile`:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000 8080
CMD ["python", "run.py"]
```

**`docker-compose.yml`:**
```yaml
services:
  ksnb:
    build: .
    ports: ["8000:8000", "8080:8080"]
    volumes:
      - ./data:/app/data
      - ./templates:/app/templates
    restart: unless-stopped
```

Thay thế `deploy.bat` bằng `docker compose up -d --build`.

---

### 4.4 Dark mode và tùy chỉnh giao diện

```python
@ui.page("/settings/appearance")
def appearance_page():
    dark = ui.dark_mode()
    ui.switch("Chế độ tối", on_change=lambda e: dark.enable() if e.value else dark.disable())
```

`ui.dark_mode()` đã built-in trong NiceGUI, chỉ cần thêm toggle và persist vào `app.storage.user["theme"]`.

---

## Thứ tự ưu tiên thực hiện (đã hiệu chỉnh)

```
Ngay bây giờ:
  [P1] 1.3 Bắt buộc đổi mật khẩu lần đầu    ← Security trước
  [P2] 1.2 Persist session vào SQLite         ← Tránh logout đột ngột
  [P3] 1.4 Backup tự động hàng ngày
  [P4] 1.5 Audit error boundary còn thiếu     ← Không viết lại, chỉ audit
  [P5] 1.1 Tách frontend/main.py              ← Làm cuối, từng trang một

Tháng 1–2:
  [P6]  2.1 Nhập liệu từ Excel               ← Giá trị cao nhất
  [P7]  2.3 Tìm kiếm nâng cao
  [P8]  2.2 Biểu đồ thống kê Dashboard
  [P9]  2.6 Thông báo in-app
  [P10] 2.4 PDF bìa tập (dùng reportlab)      ← Không dùng weasyprint
  [~~]  2.5 Lịch nghỉ phép                    ← ĐÃ XONG
  [~~]  2.7 UI lịch sử thao tác              ← ĐÃ XONG

Tháng 2–4:
  [P11] 3.6 QR code bìa tập                  ← Ít công, nhiều lợi
  [P12] 3.4 Quản lý hộp lưu trữ + QR
  [P13] 3.2 BorrowRecord model + trang UI     ← API đã có
  [P14] 3.5 Báo cáo tổng hợp năm
  [P15] 3.1 Email notification
  [P16] 3.3 PWA mobile                        ← Rủi ro cao, cân nhắc kỹ

Dài hạn:
  [P17] 4.2 Bộ test tự động                  ← Nên làm sớm hơn nếu có người
  [P18] 4.3 Docker + CI/CD
  [P19] 4.1 Migrate PostgreSQL
  [P20] 4.4 Dark mode
```

---

*Tài liệu tạo ngày 12/05/2026. Đánh giá & hiệu chỉnh lần 1: 12/05/2026.*
