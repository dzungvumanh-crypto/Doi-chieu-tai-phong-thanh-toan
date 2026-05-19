# UPGRADE260512 — Nâng cấp Pha 1 (trừ 1.2)

**Ngày cập nhật:** 12/05/2026  
**Phiên bản:** 1.1.0  
**Thực hiện bởi:** KSNB System / Claude Code  

---

## Tóm tắt

Hoàn thành 4 mục trong Pha 1 của PLAN.md:

| Mục | Tên | Trạng thái |
|-----|-----|-----------|
| 1.3 | Bắt buộc đổi mật khẩu lần đầu | ✅ Hoàn thành |
| 1.4 | Backup tự động hàng ngày | ✅ Hoàn thành |
| 1.5 | Audit error boundary toàn cục | ✅ Hoàn thành |
| 1.1 | Tách `frontend/main.py` thành modules | ✅ Hoàn thành |
| 1.2 | Persist session vào SQLite | ⏭️ Bỏ qua theo yêu cầu |

---

## Chi tiết thay đổi

---

### 1.3 — Bắt buộc đổi mật khẩu lần đầu đăng nhập

**Mục tiêu:** Sau khi `init_db.py` seed user hoặc Admin reset mật khẩu, user bị buộc đổi mật khẩu trước khi dùng hệ thống.

**Các file thay đổi:**

#### `backend/models.py`
- Thêm cột `must_change_password = Column(Boolean, default=False)` vào model `KSNBStaff`.

#### `backend/main.py`
- Thêm schema migration vào `_ensure_indexes()`:
  ```sql
  ALTER TABLE ksnb_staff ADD COLUMN must_change_password BOOLEAN DEFAULT 0
  ```

#### `backend/schemas.py`
- Thêm field `must_change_password: bool = False` vào `Token` schema để frontend nhận được flag sau login.

#### `backend/api/auth.py`
- **`POST /api/auth/login`**: trả `must_change_password` trong response.
- **`POST /api/auth/change-password`**: sau khi đổi thành công → set `must_change_password = False`.
- **`POST /api/auth/admin-reset-password`**: sau khi reset → set `must_change_password = True` để buộc user đổi lần tiếp theo.

#### `init_db.py`
- Tất cả user được seed (admin, kiensoat1, gdv_*) đều được tạo với `must_change_password=True`.
- In cảnh báo: `⚠️ CẢNH BÁO BẢO MẬT: Hãy đổi mật khẩu ngay sau lần đăng nhập đầu tiên!`

#### `frontend/pages/login.py` (và logic trong `pages/change_password.py`)
- Sau login: nếu `result.get("must_change_password")` → navigate đến `/change-password` thay vì `/home`.
- Trang `/change-password` là trang full-screen (không có sidebar), bắt buộc nhập mật khẩu cũ + mật khẩu mới trước khi tiếp tục.

**Luồng hoạt động:**
```
Login → (must_change_password=True) → /change-password
      → đổi mật khẩu thành công → /home hoặc /handovers
```

---

### 1.4 — Backup tự động hàng ngày

**Mục tiêu:** Tự động tạo bản sao DB mỗi 24 giờ, lưu tối đa 7 bản gần nhất tại `data/backups/`.

**File mới:**

#### `backend/services/backup_service.py` *(tạo mới)*
- `run_backup(db_path)`: Tạo bản sao an toàn dùng SQLite online backup API (`sqlite3.connect.backup()`).
- `_rotate(backup_dir)`: Xóa bản cũ, giữ tối đa 7 bản mới nhất.
- `_schedule_next(db_path)`: Lên lịch timer Python (`threading.Timer`) sau 24 giờ.
- `start_scheduler(db_path)`: Gọi khi khởi động — backup ngay lập tức + khởi động scheduler.
- `last_backup_info()`: Trả thông tin bản backup gần nhất (dùng cho UI admin).

#### `backend/main.py`
- Gọi `start_scheduler()` sau khi `_ensure_indexes()` chạy xong.
- Đọc đường dẫn DB từ `settings.DATABASE_URL`.

#### `backend/api/logs.py`
- Thêm endpoint `GET /api/admin/logs/backup-info` (quyền admin/GĐ): trả thông tin bản backup gần nhất.

#### `frontend/pages/logs.py`
- Hiển thị "Backup gần nhất: HH:MM DD/MM/YYYY (N bản)" trong toolbar của trang Nhật ký hệ thống.

**Lịch backup:**
- Lần đầu: ngay khi app khởi động.
- Các lần tiếp theo: mỗi 24 giờ.
- Lưu tại: `data/backups/ksnb_YYYYMMDD_HHMM.db`.
- Giữ tối đa: 7 bản.

---

### 1.5 — Audit error boundary toàn cục

**Mục tiêu:** Đảm bảo tất cả `on_click` handler gọi API đều dùng `_handle_api_error(e)` để redirect về `/login` khi session hết hạn (thay vì chỉ hiện toast lỗi và user bị kẹt).

**Vấn đề tìm thấy:** 10 handler dùng `ui.notify(str(ex), type="negative")` trực tiếp thay vì `_handle_api_error(ex)` — bỏ qua `SessionExpiredError`.

**Các handler đã sửa trong `frontend/main.py` (trước khi tách):**

| Handler | Trang | Vấn đề |
|---------|-------|--------|
| `do_deactivate_staff` | `/staff` | `ui.notify` trực tiếp |
| `render_detail_entries` (load) | `/handovers/{id}` | `ui.notify` trực tiếp |
| `do_delete_entry` | `/handovers/{id}` | `ui.notify` trực tiếp |
| `do_add_entry` | `/handovers/{id}` | `ui.notify` trực tiếp |
| `do_confirm_detail` | `/handovers/{id}` | `ui.notify` trực tiếp |
| `do_delete_handover` | `/handovers/{id}` | `ui.notify` trực tiếp |
| `_do_confirm` (entry panel) | `/handovers` | `ui.notify` trực tiếp |
| `_do_reject_submit` | `/handovers` | `ui.notify` trực tiếp |
| `_do_borrow_submit` | `/handovers` | `ui.notify` trực tiếp |
| `_do_handback_submit` | `/handovers` | `ui.notify` trực tiếp |

**Pattern sửa:**
```python
# Trước:
except Exception as ex:
    ui.notify(str(ex), type="negative")

# Sau:
except Exception as ex:
    if _handle_api_error(ex): return
```

**Ghi chú:** `do_change_pw` và `do_admin_reset` trong `/user-management` dùng cách kiểm tra `isinstance(e, api.SessionExpiredError)` inline — đây là pattern cố ý vì hiển thị lỗi trong label thay vì toast; **không sửa**.

---

### 1.1 — Tách `frontend/main.py` thành modules

**Mục tiêu:** File `frontend/main.py` cũ 3 500+ dòng → tách thành modules nhỏ dễ bảo trì.

**Cấu trúc mới:**

```
frontend/
├── main.py              (~40 dòng) — entry point, import pages + ui.run()
├── shared.py            (~140 dòng) — shared helpers, constants
├── api_client.py        (không đổi)
└── pages/
    ├── __init__.py      (rỗng)
    ├── login.py         — /login
    ├── dashboard.py     — /home, /
    ├── staff.py         — /staff
    ├── source_users.py  — /source_users
    ├── handovers.py     — /handovers, /handovers/new, /handovers/{id}
    ├── bundles.py       — /bundles
    ├── storage.py       — /storage
    ├── user_management.py — /user-management
    ├── leaves.py        — /leaves
    ├── logs.py          — /logs
    └── change_password.py — /change-password
```

**`frontend/shared.py`** (tạo mới):
- Constants: `MENU_ITEMS`, `MENU_ITEMS_CV`, `COLORS`
- Helpers: `_logout`, `_sidebar`, `_content_area`, `_page_header`, `_card`, `_require_auth`, `_redirect_if_cv`, `_handle_api_error`

**`frontend/main.py`** (viết lại slim):
- Import `app.add_static_files` (phải chạy trước khi pages được load)
- Import tất cả page modules (trigger `@ui.page` registration)
- Re-export shared utilities để backward compat
- Gọi `ui.run()`

**Cơ chế hoạt động:**
- NiceGUI đăng ký route khi `@ui.page(...)` decorator chạy (lúc import module)
- Import 11 page modules trong main.py → 13 route được đăng ký tự động

---

## Danh sách file thay đổi

### File mới tạo
| File | Mô tả |
|------|-------|
| `frontend/shared.py` | Shared utilities (helper, constants) |
| `frontend/pages/login.py` | Trang đăng nhập |
| `frontend/pages/dashboard.py` | Trang chủ / Dashboard |
| `frontend/pages/staff.py` | Quản lý tài khoản |
| `frontend/pages/source_users.py` | Danh sách giao dịch viên |
| `frontend/pages/handovers.py` | Bàn giao chứng từ (3 routes) |
| `frontend/pages/bundles.py` | Đóng tập chứng từ |
| `frontend/pages/storage.py` | Lưu trữ & tra cứu |
| `frontend/pages/user_management.py` | Quản lý người dùng |
| `frontend/pages/leaves.py` | Nghỉ phép |
| `frontend/pages/logs.py` | Nhật ký hệ thống |
| `frontend/pages/change_password.py` | Đổi mật khẩu bắt buộc |
| `backend/services/backup_service.py` | Backup tự động hàng ngày |

### File sửa đổi
| File | Nội dung thay đổi |
|------|------------------|
| `frontend/main.py` | Viết lại slim (~40 dòng), xóa toàn bộ page code |
| `backend/models.py` | Thêm `must_change_password` vào `KSNBStaff` |
| `backend/main.py` | Thêm migration + khởi động backup scheduler |
| `backend/schemas.py` | Thêm `must_change_password` vào `Token` |
| `backend/api/auth.py` | Login trả flag; change-password xóa flag; admin-reset bật flag |
| `backend/api/logs.py` | Thêm endpoint `GET /api/admin/logs/backup-info` |
| `init_db.py` | Seed user với `must_change_password=True` + cảnh báo |

---

## Hướng dẫn deploy

### DB migration (tự động)
Khi khởi động backend, `_ensure_indexes()` tự chạy:
```sql
ALTER TABLE ksnb_staff ADD COLUMN must_change_password BOOLEAN DEFAULT 0
```
Không cần thao tác thủ công.

### User hiện tại
- User đang có trong DB **sẽ không** bị force đổi mật khẩu (`must_change_password DEFAULT 0`).
- Chỉ user tạo mới sau lần này mới bị bắt đổi.
- Admin có thể bật flag thủ công bằng cách reset mật khẩu cho họ qua trang `/user-management`.

### Backup
- Thư mục `data/backups/` được tạo tự động khi app khởi động.
- File backup đầu tiên được tạo ngay khi backend start.
- Kiểm tra: xem "Backup gần nhất" trong trang **Nhật ký hệ thống**.

---

*Tài liệu tạo ngày 12/05/2026.*
