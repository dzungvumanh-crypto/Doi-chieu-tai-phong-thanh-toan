# UPGRADE260516 — Bảo mật & Sửa bug nghiệp vụ

**Ngày cập nhật:** 16/05/2026  
**Phiên bản:** 1.2.0  
**Thực hiện bởi:** KSNB System / Claude Code  

---

## Tóm tắt

Hoàn thành 9 mục bảo mật và sửa bug nghiệp vụ theo đánh giá PLAN.md ngày 16/05/2026.

| Mục | Tên | Trạng thái |
|-----|-----|-----------|
| P0-1 | Sửa CORS, tắt API docs theo ENV | ✅ Hoàn thành |
| P0-2 | Xóa hardcode password khỏi init_db.py | ✅ Hoàn thành |
| P0-3 | Tách migration vào FastAPI lifespan | ✅ Hoàn thành |
| P0-4 | Bỏ tin tưởng X-Client-IP từ client | ✅ Hoàn thành |
| P0-5 | Giới hạn scope GET /api/staff/ theo role | ✅ Hoàn thành |
| P0-6 | Ghi audit log khi tải backup DB | ✅ Hoàn thành |
| P1-1 | Chuẩn hóa leave_type + validate | ✅ Hoàn thành |
| P1-2 | Sửa timezone: date.today() → _vn_now().date() | ✅ Hoàn thành |
| P1-3 | Kiểm tra entry đã thuộc tập trước khi gom | ✅ Hoàn thành |
| P1-4 | CHECK constraint DB qua trigger | ✅ Hoàn thành |
| P1-5 | Đổi require_controller → require_pho_phong_or_above | ✅ Hoàn thành |

---

## Chi tiết thay đổi

---

### P0-1 — CORS, ENV, tắt API docs

**Vấn đề:** CORS `allow_origins=["*"]` kết hợp `allow_credentials=True` cho phép mọi domain truy cập API có cookie/token.  
API docs `/docs` `/redoc` public mọi lúc.

**Các file thay đổi:**

#### `backend/core/config.py`
- Thêm 3 config mới đọc từ biến môi trường:
  - `ENV`: `development` | `production` (mặc định: `development`)
  - `ALLOWED_ORIGINS`: danh sách origin phân cách bằng dấu phẩy (mặc định: `http://localhost:8080`)
  - `ENABLE_API_DOCS`: `true`/`1`/`yes` để bật docs dù ở production

#### `backend/main.py`
- CORS `allow_origins` → đọc từ `settings.ALLOWED_ORIGINS`
- `/docs`, `/redoc`: tắt khi `ENV=production` và `ENABLE_API_DOCS` không bật

**Cách cấu hình .env cho production:**
```env
ENV=production
ALLOWED_ORIGINS=http://192.168.1.100:8080,http://10.0.0.5:8080
SECRET_KEY=<key mạnh>
# ENABLE_API_DOCS=true  ← bỏ comment nếu cần debug tạm
```

---

### P0-2 — Xóa hardcode password khỏi init_db.py

**Vấn đề:** Mật khẩu mặc định được hardcode trong source code và in ra console.

**Thay đổi trong `init_db.py`:**
- Thêm hàm `_get_seed_password(label, env_key, default_dev)`:
  - Ưu tiên đọc từ biến môi trường (`SEED_ADMIN_PASSWORD`, `SEED_KSV_PASSWORD`)
  - Nếu `ENV=production` và không có env var → prompt nhập từ terminal
  - Nếu `ENV=development` → dùng mặc định cũ (vẫn có `must_change_password=1`)
- Tài khoản test (gdv_nostro, gdv_swift, gdv_payment) **chỉ seed khi `ENV=development`**
- Không in mật khẩu ra console; chỉ in tên tài khoản đã tạo

**Cách dùng production:**
```bash
set ENV=production
set SEED_ADMIN_PASSWORD=<mật khẩu mạnh>
python init_db.py
```

---

### P0-3 — Tách migration vào FastAPI lifespan

**Vấn đề:** `_create_tables()` và `_ensure_indexes()` chạy ngay khi import `backend.main` — không kiểm soát được, không có backup trước migration.

**Thay đổi trong `backend/main.py`:**
- Xóa 2 lệnh gọi module-level: `_create_tables(DB_PATH)` và `_ensure_indexes()`
- Thêm `@asynccontextmanager async def lifespan(app)` gọi theo thứ tự:
  1. `_create_tables()` — tạo bảng mới nếu chưa có
  2. `_ensure_indexes()` — migrate schema idempotent
  3. `start_scheduler()` — khởi động backup tự động
- FastAPI app sử dụng `lifespan=lifespan`
- `init_db.py` vẫn import và gọi trực tiếp — không thay đổi hành vi seed

---

### P0-4 — Bỏ tin tưởng X-Client-IP từ client

**Vấn đề:** `auth.py` ưu tiên header `X-Client-IP` do client tự gửi → có thể giả mạo IP để vượt kiểm tra session trùng.

**Thay đổi trong `backend/api/auth.py`:**
```python
# Trước:
client_ip = (
    request.headers.get("X-Client-IP")
    or (request.client.host if request.client else "unknown")
)

# Sau:
client_ip = request.client.host if request.client else "unknown"
```

---

### P0-5 — Giới hạn scope GET /api/staff/ theo role

**Vấn đề:** Bất kỳ user đã đăng nhập đều xem được toàn bộ nhân viên mọi phòng.

**Thay đổi trong `backend/api/staff.py`:**
- Thêm hằng `_BROAD_VIEW_ROLES = frozenset(("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"))`
- Logic scope trong `list_staff()`:
  - **admin / hau_kiem_vien / giam_doc / pho_giam_doc**: xem tất cả (filter theo `department_id` nếu có)
  - **Nhân viên phòng TH**: xem tất cả (cần để chọn GĐ/PGĐ trong workflow nghỉ phép)
  - **truong_phong / pho_phong / chuyen_vien**: mặc định chỉ xem phòng mình

---

### P0-6 — Ghi audit log khi tải backup DB

**Vấn đề:** Endpoint `GET /api/admin/logs/backup` không ghi lại ai tải, từ IP nào, lúc nào.

**Thay đổi trong `backend/api/logs.py`:**
- Thêm tham số `request: Request` và `db: sqlite3.Connection` vào `backup_db()`
- Sau khi đọc xong file DB, INSERT vào `login_logs`:
  - `username`: username của người tải
  - `staff_id`: id người tải
  - `ip_address`: IP từ TCP connection
  - `success`: 1
  - `detail`: `backup_download:<timestamp>`

---

### P1-1 + P1-2 — Chuẩn hóa leave_type và sửa timezone

**Vấn đề:**
1. Frontend có `dot_xuat` nhưng backend không nhận, không validate.
2. `date.today()` trả ngày theo múi giờ máy chủ, có thể khác `_vn_now().date()` (UTC+7).

**Thay đổi trong `backend/api/leaves.py`:**
- `LEAVE_TYPE_LABELS` thêm: `"bat_buoc": "Nghỉ phép bắt buộc"`, `"dot_xuat": "Nghỉ đột xuất"`
- Thêm `_VALID_LEAVE_TYPES = frozenset(LEAVE_TYPE_LABELS.keys())`
- Đầu `create_leave()`: validate `leave_type IN _VALID_LEAVE_TYPES`, trả 400 nếu không hợp lệ
- `date.today()` → `_vn_now().date()` trong kiểm tra "ngày phép năm phải từ hôm nay"

---

### P1-3 — Kiểm tra entry đã thuộc tập trước khi gom

**Vấn đề:** `bundles.py` không kiểm tra entry đã nằm trong tập khác → 1 entry có thể thuộc nhiều tập đồng thời.

**Thay đổi trong `backend/api/bundles.py`:**
Sau khi kiểm tra entry thuộc đúng phòng, thêm:
```python
already_bundled = db.execute(
    f"SELECT bi.entry_id, bg.notes FROM bundle_items bi
      JOIN bundles b ON bi.bundle_id = b.id
      JOIN bundle_groups bg ON b.group_id = bg.id
      WHERE bi.entry_id IN ({placeholders})", entry_ids
).fetchall()
if already_bundled:
    raise HTTPException(409, "Chứng từ #... đã thuộc tập khác. Hủy tập cũ trước khi gom lại.")
```

---

### P1-4 — CHECK constraint qua trigger

**Vấn đề:** DB không có ràng buộc tự nhiên, chỉ dựa vào Pydantic validate ở tầng API.

**Thêm vào `schema_migrations` trong `_ensure_indexes()` (`backend/main.py`):**
- Trigger `chk_sheet_count_insert` / `chk_sheet_count_update`: ABORT nếu `sheet_count <= 0`
- Trigger `chk_used_leave_days`: ABORT nếu `used_leave_days < 0` khi UPDATE

---

### P1-5 — Đổi require_controller → require_pho_phong_or_above

**Vấn đề:** `require_controller` là deprecated alias; còn 14 caller trong 2 file.

**Thay đổi:**
- `backend/api/handovers.py`: thay toàn bộ `require_controller` → `require_pho_phong_or_above`
- `backend/api/bundles.py`: thay toàn bộ `require_controller` → `require_pho_phong_or_above`
- `backend/core/deps.py`: giữ nguyên định nghĩa deprecated (backward compat nếu code khác còn import)

---

## Danh sách file thay đổi

### File sửa đổi
| File | Nội dung thay đổi |
|------|------------------|
| `backend/core/config.py` | Thêm `ENV`, `ALLOWED_ORIGINS`, `ENABLE_API_DOCS` |
| `backend/main.py` | CORS từ env; tắt docs; tách migration vào lifespan; thêm trigger constraints |
| `backend/api/auth.py` | Bỏ `X-Client-IP` header |
| `backend/api/staff.py` | Scope list_staff theo role |
| `backend/api/logs.py` | Audit log khi tải backup |
| `backend/api/leaves.py` | Thêm `dot_xuat`/`bat_buoc`; validate leave_type; sửa timezone |
| `backend/api/bundles.py` | Check entry đã thuộc tập; đổi require_controller |
| `backend/api/handovers.py` | Đổi require_controller → require_pho_phong_or_above |
| `init_db.py` | Xóa hardcode password; chỉ seed test accounts khi development |

---

## Hướng dẫn deploy

### Cấu hình môi trường
Tạo hoặc cập nhật `.env` trước khi khởi động:
```env
SECRET_KEY=<key hiện tại>
ENV=production
ALLOWED_ORIGINS=http://<IP_server>:8080
# ENABLE_API_DOCS=true   # bỏ comment khi debug
```

### DB migration (tự động)
Khi backend khởi động, `lifespan` chạy `_ensure_indexes()` — thêm 3 trigger mới:
- `chk_sheet_count_insert`
- `chk_sheet_count_update`
- `chk_used_leave_days`

Không cần thao tác thủ công, idempotent.

### Kiểm tra sau deploy

1. **CORS**: Thử gọi API từ domain không có trong `ALLOWED_ORIGINS` → phải bị chặn
2. **API docs**: Truy cập `http://server:8000/docs` ở production → phải trả 404
3. **Staff scope**: Login bằng chuyên viên → `GET /api/staff/` chỉ trả về phòng mình
4. **Backup audit**: Admin tải backup → kiểm tra `GET /api/admin/logs/logins` có dòng `backup_download`
5. **Gom tập trùng**: Thử gom entry đã thuộc tập → phải trả 409 với thông báo rõ ràng
6. **Nghỉ đột xuất**: Tạo đơn nghỉ `dot_xuat` → backend chấp nhận và lưu đúng loại

---

*Tài liệu tạo ngày 16/05/2026.*
