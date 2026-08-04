# DESIGN.md — Patterns & Business Logic

## Timestamps
Dùng `_vn_now()` từ `backend/database.py` cho mọi timestamp (UTC+7, naive datetime). Không dùng `datetime.utcnow()`.

## Tên bảng
Bảng nhân sự tên là **`user_tttt`**. Tên cũ `ksnb_staff` đã bị đổi (xem `_ensure_indexes()` trong
`backend/db/migrations.py`) — các file trong `Plan/` và `Upgrade/` là tài liệu lịch sử, vẫn ghi tên cũ.
**Không copy tên bảng từ hai thư mục đó.**

## Schema Migrations
Thêm câu SQL vào list `schema_migrations` trong `backend/db/migrations.py::_ensure_indexes()`.
Chạy idempotent khi khởi động.

Lỗi bị nuốt **có chủ đích** (nghĩa là migration đã chạy ở lần khởi động trước):
`duplicate column`, `already exists`, `already another table`.

Mọi lỗi khác — **kể cả `no such table`** — được log ERROR và raise, chặn khởi động.
Riêng `database is locked` chỉ log WARNING và bỏ qua, thử lại ở lần khởi động sau.

> `no such table` từng nằm trong danh sách nuốt lỗi. Hậu quả: migration viết sai tên bảng
> thất bại **im lặng** — không log, không chặn khởi động, cột không được thêm. Đừng đưa lại vào.

## Authentication & Sessions
- JWT verify bởi `get_current_staff` trong `deps.py` — role đọc từ **DB** mỗi request, không lấy từ token
- Session lưu trong DB (`backend/core/sessions.py` → bảng `login_sessions`) — **không** mất khi restart
- 401 từ backend → `SessionExpiredError` → `_handle_api_error()` redirect về `/login`
- Trong `asyncio.gather()`: check `isinstance(e, api.SessionExpiredError)` trước `Exception`

## RBAC — deps.py

| Dependency | Roles được phép |
|---|---|
| `get_current_staff` | Tất cả đã đăng nhập |
| `require_admin` | admin |
| `require_hkv_or_above` | admin, hau_kiem_vien |
| `require_pho_phong_or_above` | admin, hau_kiem_vien, truong_phong, pho_phong |
| `require_handover_write` | admin, hau_kiem_vien, truong_phong, pho_phong, chuyen_vien |
| `require_ksnb` | Tất cả trừ chuyen_vien |
| `require_ksv` | truong_phong, pho_phong |
| `require_gd_level` | giam_doc, pho_giam_doc |
| `require_admin_or_gd` | admin, giam_doc, pho_giam_doc |

## Role Hierarchy
```
admin > hau_kiem_vien > giam_doc / pho_giam_doc > truong_phong > pho_phong > chuyen_vien
```
- `controller` deprecated → migrate sang `pho_phong`
- GĐ/PGĐ bắt buộc thuộc phòng **Ban Giám đốc** (code `BGD`, is_source=False)
- Chuyên viên bắt buộc thuộc phòng nguồn (is_source=True)
- Admin **không** tham gia quy trình duyệt nghỉ phép
- GĐ/PGĐ xem được tất cả màn hình nhưng chỉ thao tác ở bước duyệt GĐ

## Frontend Async Pattern
```python
# Gọi song song:
a, b = await asyncio.gather(
    asyncio.to_thread(api.get, "/api/foo"),
    asyncio.to_thread(api.get, "/api/bar"),
    return_exceptions=True,
)
# Xử lý lỗi:
try:
    result = await asyncio.to_thread(api.post, "/api/...", body)
except Exception as e:
    if _handle_api_error(e):  # True + redirect nếu SessionExpiredError
        return
```

## Leave Approval Workflow
```
pending_ksv → pending_tong_hop → pending_gd → approved | rejected | cancelled
```
- Bước 1 — KSV: Trưởng phòng / Phó phòng (auto-assign khi tạo đơn)
- Bước 2 — Tổng hợp: nhân viên phòng TH chọn GĐ/PGĐ duyệt tiếp
- Bước 3 — GĐ: GĐ hoặc PGĐ nếu có `DelegationRecord` còn hiệu lực
- `resubmit`: rejected → pending_ksv (re-assign KSV)
- `cancel`: huỷ khi pending hoặc approved
- `used_leave_days` điều chỉnh qua `_apply_status_transition()` (idempotent)

## Word Template Generation
```python
from docxtpl import DocxTemplate
tpl = DocxTemplate("templates/don_xin_nghi_phep_tpl.docx")
tpl.render(context_dict)
buf = io.BytesIO(); tpl.save(buf)
```
Dùng `_download_headers(filename)` từ `backend/api/bundles.py` cho RFC 6266 Content-Disposition.
