# Kế hoạch: Xóa trang Danh sách GDV + Gộp SourceUser vào KSNBStaff

## Context

Hệ thống có hai bảng riêng biệt:
- `source_users` — GDV tại phòng nguồn (user_code IPCAS, full_name PaymentHub, vn_name, department_id)
- `ksnb_staff` — Tài khoản hệ thống (ipcas_code, payment_username, full_name, department_id, role, ...)

Các field hoàn toàn tương đương:

| SourceUser     | KSNBStaff        |
|----------------|------------------|
| user_code      | ipcas_code       |
| full_name      | payment_username |
| vn_name        | full_name        |
| department_id  | department_id    |
| is_active      | is_active        |

Trang `/staff` (Quản lý User) đã hiển thị `ipcas_code` và `payment_username` → trang `/source_users` trở thành dư thừa. Mục tiêu: xóa bảng `source_users`, gộp vào `ksnb_staff`, xóa trang frontend.

---

## Ảnh hưởng

### Sâu (cần sửa code):
- `backend/api/handovers.py` — dùng SourceUser cho grid GDV, validate entry, borrow/handback, export
- `backend/api/bundles.py` — dùng `entry.source_user` cho bundle generation
- `backend/api/departments.py` — chứa toàn bộ CRUD `/api/source-users/`
- `backend/models.py` — `DocumentEntry.source_user_id` FK → `source_users.id`
- `backend/schemas.py` — `SourceUserCreate`, `SourceUserOut`, `DocumentEntryIn.source_user_id`, `GridResponse.users`, `EntryUpsertRequest.source_user_id`
- `frontend/pages/handovers.py` — gọi `/api/source-users/?department_id=X`
- `frontend/pages/bundles.py` — dùng `source_user_id` trong users_map

### Nông (xóa đơn giản):
- `frontend/pages/source_users.py` — xóa file
- `frontend/shared.py:11` — xóa menu item
- `frontend/main.py:17` — xóa import

---

## Kế hoạch thực hiện

### Bước 1 — DB Migration (backend/main.py)

Thêm vào `schema_migrations` trong `_ensure_indexes()`:

```sql
ALTER TABLE document_entries ADD COLUMN staff_id INTEGER
```

Sau đó thêm hàm Python backfill chạy một lần (kiểm tra staff_id IS NULL):

```python
# Backfill staff_id từ source_users → ksnb_staff matching ipcas_code + department_id
db.execute("""
    UPDATE document_entries
    SET staff_id = (
        SELECT ks.id FROM ksnb_staff ks
        JOIN source_users su ON ks.ipcas_code = su.user_code
        WHERE su.id = document_entries.source_user_id
        LIMIT 1
    )
    WHERE staff_id IS NULL
""")
```

Thêm index mới:
```sql
CREATE INDEX IF NOT EXISTS ix_doc_entries_staff ON document_entries(staff_id)
```

> **Rủi ro**: SourceUser không có KSNBStaff tương ứng → staff_id = NULL → các entry đó sẽ mất GDV. Cần kiểm tra trước: `SELECT COUNT(*) FROM document_entries WHERE staff_id IS NULL` sau backfill. Nếu > 0, tạo KSNBStaff placeholder hoặc yêu cầu admin bổ sung.

---

### Bước 2 — Backend models (backend/models.py)

- `DocumentEntry`: Thêm `staff_id = Column(Integer, ForeignKey("ksnb_staff.id"), nullable=True)` và relationship `staff = relationship("KSNBStaff")`
- `Department`: Giữ `source_users` relationship tạm thời (xóa sau)
- `KSNBStaff`: Thêm `document_entries = relationship("DocumentEntry", back_populates="staff")`
- Giữ class `SourceUser` tạm thời (tránh startup crash nếu table còn tồn tại)

---

### Bước 3 — Backend schemas (backend/schemas.py)

- `DocumentEntryIn`: `source_user_id: int` → `staff_id: int`
- `DocumentEntryOut`: `source_user_id` → `staff_id`; `source_user: Optional[SourceUserOut]` → `staff: Optional[StaffOut]`
- `GridEntryOut`: `source_user_id: int` → `staff_id: int`
- `GridResponse`: `users: List[SourceUserOut]` → `users: List[StaffOut]`
- `EntryUpsertRequest`: `source_user_id: int` → `staff_id: int`
- Xóa `SourceUserCreate`, `SourceUserOut`

---

### Bước 4 — Backend API staff (backend/api/staff.py)

Thêm param `department_id: Optional[int] = None` vào `GET /api/staff/`:

```python
if department_id:
    q = q.filter(KSNBStaff.department_id == department_id)
```

---

### Bước 5 — Backend API departments (backend/api/departments.py)

- Xóa `user_router` và toàn bộ 4 endpoint source-users (GET, POST, PUT, DELETE)
- Xóa import `SourceUser`, `SourceUserCreate`, `SourceUserOut`
- Giữ nguyên `dept_router`
- Xóa dòng register `user_router` trong `backend/main.py`

---

### Bước 6 — Backend API handovers (backend/api/handovers.py)

Thay SourceUser bằng KSNBStaff ở mọi nơi:

| Hiện tại | Sau thay đổi |
|---|---|
| `db.query(SourceUser).filter(SourceUser.department_id == dept_id, ...)` | `db.query(KSNBStaff).filter(KSNBStaff.department_id == dept_id, KSNBStaff.is_active == True, ...)` |
| `body.source_user_id` | `body.staff_id` |
| `entry.source_user_id` | `entry.staff_id` |
| `joinedload(DocumentEntry.source_user)` | `joinedload(DocumentEntry.staff)` |
| `source_user.vn_name or source_user.full_name or source_user.user_code` | `staff.full_name or staff.payment_username or staff.ipcas_code` |
| `source_user.department_id` | `staff.department_id` |

Grid query (line 82–88): Thay `SourceUser` bằng `KSNBStaff`, lấy users đang active HOẶC có entries trong tháng.

Uniqueness check: Thay `source_user_id` bằng `staff_id` trong filter DocumentEntry.

---

### Bước 7 — Backend API bundles (backend/api/bundles.py)

- `joinedload(DocumentEntry.source_user)` → `joinedload(DocumentEntry.staff)`
- `e.source_user.user_code` → `e.staff.ipcas_code`
- `e.source_user.full_name` → `e.staff.payment_username`
- `e.source_user_id` → `e.staff_id`

---

### Bước 8 — Frontend

**Xóa:**
- `frontend/pages/source_users.py` — xóa file hoàn toàn
- `frontend/shared.py:11` — xóa dòng `("source_users", "Danh sách giao dịch viên", "manage_accounts")`
- `frontend/main.py:17` — xóa `import frontend.pages.source_users`

**Sửa `frontend/pages/handovers.py`:**
- `refresh_users()` (line 556–565): Đổi gọi `/api/source-users/` → `/api/staff/` với `{"department_id": dept_id}`
- Đổi build `user_opts`: `u["user_code"]` → `u["ipcas_code"]`, `u["full_name"]` → `u.get("payment_username")`
- `load_detail_users()` (line 674–680): Tương tự
- `user_opts` (line 737): Đổi field mapping
- Entry dict: `source_user_id` → `staff_id`
- `/api/handovers/{id}/entries` body: `source_user_id` → `staff_id`

**Sửa `frontend/pages/bundles.py`:**
- `users_map.get(e["source_user_id"])` → `users_map.get(e["staff_id"])`

---

### Bước 9 — Dọn dẹp cuối

Sau khi xác nhận hệ thống chạy ổn:
- Xóa class `SourceUser` khỏi `backend/models.py`
- Xóa `Department.source_users` relationship
- Xóa SourceUser import khắp nơi còn sót
- Optionally: DROP TABLE source_users (via schema_migrations)

---

## Verification

1. Khởi động app: `python run.py` — không có lỗi startup
2. Kiểm tra DB sau backfill: `SELECT COUNT(*) FROM document_entries WHERE staff_id IS NULL` → phải = 0
3. Mở `/staff` — hiển thị bình thường, không còn menu "Danh sách GDV"
4. Truy cập `/source_users` → 404 Not Found
5. Mở Bàn giao chứng từ → chọn phòng → GDV dropdown hiển thị đúng danh sách chuyen_vien của phòng đó
6. Tạo entry mới và submit → thành công
7. Mở Đóng chứng từ → bundle hiển thị đúng tên GDV (từ ipcas_code/payment_username)
8. Kiểm tra GET /api/staff/?department_id=X trả về đúng danh sách