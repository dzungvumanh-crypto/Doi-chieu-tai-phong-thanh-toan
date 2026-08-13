# Implementation Notes

> ⚠️ **BẢN CŨ, ĐÃ NGỪNG CẬP NHẬT (28/05/2026).**
> Bản đang dùng là [`Implementation-notes.html`](Implementation-notes.html) — xem `CLAUDE.md`.
> Giữ lại file này làm lịch sử. Bảng `ksnb_staff` nhắc bên dưới nay tên là `user_tttt`.

> Ghi chú triển khai — quyết định kỹ thuật, đánh đổi, thứ cần biết.
> Cập nhật liên tục trong quá trình implement.

---

## 1. Tách `backend/main.py` — Migrations + Registry

**Vấn đề**: `backend/main.py` ban đầu dài ~600 dòng — chứa cả SQL tạo bảng, migration schema, và đăng ký router. Mỗi người trong nhóm 6 đều phải sửa file này khi thêm tính năng → conflict liên tục.

**Quyết định**: Tách ra 2 file mới, `main.py` chỉ còn ~80 dòng:
- `backend/db/migrations.py` — toàn bộ `_create_tables()` và `_ensure_indexes()`
- `backend/api/registry.py` — hàm `apply_routers()` với danh sách router

**Đánh đổi**:
- `init_db.py` phải đổi import từ `backend.main` → `backend.db.migrations`. Đã cập nhật.
- `CONTRIBUTING.md` và `DESIGN.md` đã cập nhật để phản ánh file mới.
- `CLAUDE.md` đã cập nhật kiến trúc.

**Quy tắc mới** (ghi vào CONTRIBUTING.md):
- Thêm migration → chỉ sửa `backend/db/migrations.py`
- Thêm router → chỉ sửa `backend/api/registry.py`
- Thêm page frontend → chỉ tạo file mới, KHÔNG sửa `frontend/main.py`

---

## 2. Tính ngày phép tự động từ `join_industry_date`

**Nghiệp vụ**: Số ngày phép năm = 12 + floor(số_năm_vào_ngành / 4). VD: vào ngành 2007, năm 2015 → 14 ngày.

**Trước**: `annual_leave_days` được lưu tĩnh trong DB, admin phải cập nhật thủ công mỗi năm.

**Sau**: Thêm cột `join_industry_date DATE` vào `user_tttt`. Hàm `compute_annual_leave()` trong `backend/database.py` tính tự động.

**Nơi áp dụng**:
- `backend/database.py` — định nghĩa `compute_annual_leave()`
- `backend/core/deps.py` — ghi đè `annual_leave_days` trong dict của mọi authenticated request
- `backend/api/staff.py` — hàm `_enrich()` áp dụng khi trả staff data
- `backend/api/leaves.py` — dùng khi generate phiếu nghỉ phép Word
- `backend/schemas/staff.py` — thêm `join_industry_date` và `annual_leave_days` vào schema

**Đánh đổi quan trọng — cột `annual_leave_days` trong DB trở thành legacy**:
- Nếu `join_industry_date` có giá trị → số ngày phép LUÔN được tính lại từ ngày vào ngành, bỏ qua giá trị trong DB.
- Nếu `join_industry_date = NULL` → fallback sang `annual_leave_days` trong DB (mặc định 12).
- Không xóa cột `annual_leave_days` để tránh breaking migration và backward compat.

**Lưu ý: Token đăng nhập không chứa `annual_leave_days`**: `Token` schema trong `auth.py` trả về `staff_id`, `role`, `department_id`, `must_change_password` — không có `annual_leave_days`. Frontend `api.get_current_user()` sẽ không có trường này. Đây KHÔNG phải bug vì frontend không dùng giá trị này từ JWT; nó lấy từ `GET /api/staff/` khi cần hiển thị.

---

## 3. Auto-discovery Frontend Pages

**Trước**: `frontend/main.py` hardcode danh sách 11 import page. Thêm page mới phải sửa file chung → conflict.

**Sau**:
```python
import pkgutil, importlib
import frontend.pages as _pages_pkg
for _importer, _modname, _ispkg in pkgutil.iter_modules(_pages_pkg.__path__):
    importlib.import_module(f"frontend.pages.{_modname}")
```

**Quyết định**: Dùng `pkgutil.iter_modules` thay vì `pkgutil.walk_packages` vì chỉ cần scan level 1 (không có sub-package trong `pages/`).

**Đánh đổi**:
- Thứ tự import từ **cụ thể** → **alphabetical**. Không ảnh hưởng vì các page độc lập, không import lẫn nhau.
- Nếu ai tạo **thư mục con** trong `frontend/pages/` → `importlib.import_module` sẽ import `__init__.py` của nó (nếu có). Chưa xử lý edge case này, nhưng hiện tại không cần.
- Thêm `_ispkg` check nếu sau này muốn skip sub-packages: `if not _ispkg: importlib.import_module(...)`.

---

## 4. Staff Export / Import DB

**Tính năng mới** trong `backend/api/staff.py`:
- `GET /api/staff/export` — Xuất Excel (openpyxl). Chỉ Admin.
- `GET /api/staff/export-db` — Xuất file SQLite chứa bảng `user_tttt`. Chỉ Admin.
- `POST /api/staff/import-db` — Nhập file SQLite, upsert theo `employee_code`. Chỉ Admin.

**Lý do có export-db**: Hỗ trợ đồng bộ dữ liệu nhân sự giữa các máy (offline scenario). Định dạng `.db` đảm bảo type safety tốt hơn CSV.

**Quyết định upsert theo `employee_code`** (không phải `id`): `id` có thể khác nhau giữa các hệ thống, còn `employee_code` là mã nhân viên nghiệp vụ — duy nhất và ổn định.

**Vấn đề tiềm ẩn**: Import không kiểm tra schema compatibility. Nếu file `.db` nguồn từ phiên bản cũ hơn (thiếu cột), câu UPDATE vẫn chạy nhưng sẽ bỏ qua cột mới. Chấp nhận được vì đây là tool nội bộ.

**Audit log**: Mọi thao tác import đều ghi vào `audit_logs`.

---

## 5. Login Logs Viewer (Frontend + Backend)

**Backend** (`backend/api/logs.py`):
- `GET /api/admin/logs/logins` — danh sách login logs với filter `success` và phân trang
- `GET /api/admin/logs/logins/export` — xuất Excel
- Quyền: `require_admin_or_gd` (Admin + GĐ/PGĐ xem được)

**Frontend** (`frontend/pages/logs.py`):
- Thêm section "Nhật ký đăng nhập" phía dưới section log file
- Filter theo kết quả (Tất cả / Thành công / Thất bại)
- Nút "Xuất Excel" theo filter đang chọn

**Lưu ý**: `api.download()` đã hỗ trợ `params` (query string) → không cần thêm gì ở `api_client.py`.

---

## 6. Exception Handler Frontend

**Vấn đề**: NiceGUI nuốt một số exception trong async handler mà không log — debug rất khó.

**Giải pháp**: Thêm `ui.on_exception(_on_exception)` trong `frontend/main.py`. Handler ghi traceback đầy đủ vào `logs/app.log` qua logger `nicegui.crash`.

**Chú ý**: `ui.on_exception` chỉ bắt exception trong **UI callbacks** (click, submit...), không bắt exception trong `asyncio.to_thread()`. Những chỗ đó vẫn phải `try/except` bình thường.

---

## 7. Dashboard Stat Fix — "Phòng nghiệp vụ"

**Bug cũ**: Đếm `len([d for d in depts if d.get("is_source")])` — chỉ tính phòng có `is_source=True`, bỏ qua phòng TH (Tổng hợp) vì TH có `is_source=False`.

**Fix mới**: `len([d for d in depts if d.get("code") != "BGD"])` — loại trừ Ban Giám đốc ra khỏi đếm, nhưng tính TH.

**Lý do**: TH là phòng nghiệp vụ thực sự (có nhân viên, có công việc), chỉ BGD không phải "phòng nghiệp vụ" theo nghĩa dashboard.

**Rủi ro**: Nếu sau này thêm phòng có `code` khác mà cũng không phải nghiệp vụ (VD: phòng IT, phòng HR), cần cập nhật điều kiện này. Hard-code `!= "BGD"` là giải pháp đơn giản nhất cho hiện tại.

---

## 8. Vấn đề phát hiện nhưng KHÔNG fix

### 8a. Migration index `ix_ksnb_staff_dept` trong `_ensure_indexes()`

File `backend/db/migrations.py` còn câu:
```python
"CREATE INDEX IF NOT EXISTS ix_ksnb_staff_dept ON ksnb_staff(department_id)",
```
Bảng `ksnb_staff` đã được đổi tên thành `user_tttt` — câu này sẽ fail với "no such table". **Được nuốt bởi error handler** (check `"no such table" not in msg`). Index đúng là `ix_user_tttt_dept` đã có trong `index_stmts`. 

**Không fix** vì: sửa migration cũ có thể break DB hiện tại nếu có hệ thống nào còn dùng `ksnb_staff`. Migration idempotent — lỗi được log không raise → an toàn.

### 8b. Token login không trả `annual_leave_days`

`Token` schema (`backend/schemas/auth.py`) không có field `annual_leave_days`. Frontend `get_current_user()` không biết số ngày phép của user đang đăng nhập. 

**Không fix** vì: Frontend không dùng `annual_leave_days` từ user session — chỉ dùng từ response của `/api/staff/` hoặc `/api/leaves/`. Thêm vào Token schema là được nhưng không cần thiết lúc này.

### 8c. `pkgutil.iter_modules` không skip sub-packages

Nếu ai tạo thư mục con trong `frontend/pages/`, `_ispkg=True` nhưng code hiện tại vẫn gọi `importlib.import_module` lên nó. **Không fix** vì hiện tại không có sub-package nào và không có kế hoạch tạo.

---

## 9. Files hỗ trợ không nằm trong web app

- `import_users_csv.py` — script one-off import CSV vào DB trực tiếp. **Không đưa vào web app** vì: chỉ dùng khi setup lần đầu hoặc migration dữ liệu. Không cần expose qua API.
- `BaoCaoHauKiem/` — tài liệu/báo cáo Excel/Word mẫu. Không liên quan code.

---

*Cập nhật lần cuối: 2026-05-28*
