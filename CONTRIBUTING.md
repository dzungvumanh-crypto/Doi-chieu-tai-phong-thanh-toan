# Hướng dẫn Làm việc Nhóm

## Tại sao cần quy tắc này?

Khi nhiều người cùng sửa code, nếu không có quy tắc thì sẽ xảy ra:
- Hai người cùng sửa 1 file → xung đột khi gộp code, mất nhiều thời gian xử lý thủ công
- Người này vô tình xoá/sửa code của người kia
- Không biết ai chịu trách nhiệm khi có lỗi

**Nguyên tắc vàng: Mỗi người chỉ sửa files trong khu vực của mình. Muốn sửa chỗ khác → hỏi trước.**

---

## Phần 1 — Phân công Công việc

| Người | Mảng | Files phụ trách |
|-------|------|-----------------|
| **Người 1 — Tech Lead** | Nền tảng & Đăng nhập | `backend/core/*`, `backend/database.py`, `backend/api/auth.py`, `backend/schemas/auth.py`, `frontend/pages/login.py`, `frontend/pages/change_password.py`, `frontend/api_client.py`, `frontend/shared.py` |
| **Người 2** | Quản lý Nhân sự | `backend/api/staff.py`, `backend/api/departments.py`, `backend/schemas/staff.py`, `backend/schemas/common.py`, `frontend/pages/staff.py`, `frontend/pages/user_management.py` |
| **Người 3** | Nghỉ phép | `backend/api/leaves.py`, `backend/api/delegations.py`, `backend/schemas/leaves.py`, `frontend/pages/leaves.py` |
| **Người 4** | Bàn giao Chứng từ | `backend/api/handovers.py`, `backend/schemas/handovers.py`, `frontend/pages/handovers.py` |
| **Người 5** | Tập Chứng từ & Bìa | `backend/api/bundles.py`, `backend/services/bundle_service.py`, `backend/services/cover_service.py`, `backend/schemas/bundles.py`, `frontend/pages/bundles.py`, `frontend/pages/storage.py`, `templates/*` |
| **Người 6** | Báo cáo & Admin | `backend/api/reports.py`, `backend/api/dashboard.py`, `backend/api/logs.py`, `backend/api/holidays.py`, `backend/services/report_service.py`, `frontend/pages/reports.py`, `frontend/pages/dashboard.py`, `frontend/pages/logs.py` |

**Files dùng chung — phải được Người 1 approve mới được merge:**
- `backend/db/migrations.py` (danh sách migration trong `_ensure_indexes()`)
- `backend/api/registry.py` (danh sách router)
- `backend/core/enums.py`
- `init_db.py`, `requirements.txt`, `run.py`

---

## Phần 2 — Cài đặt Môi trường (làm 1 lần khi mới vào)

### Bước 1 — Cài Python

Tải Python 3.10 trở lên tại: https://www.python.org/downloads/

Khi cài, **nhớ tích vào ô "Add Python to PATH"** trước khi bấm Install.

Kiểm tra cài thành công: mở PowerShell, gõ `python --version`

### Bước 2 — Cài Git

Tải tại: https://git-scm.com/download/win

Khi cài, chọn các tuỳ chọn mặc định, nhấn Next liên tục đến khi xong.

Kiểm tra cài thành công: mở PowerShell, gõ `git --version` → thấy số phiên bản là OK.

### Bước 3 — Tải code về máy (làm 1 lần duy nhất)

**Mở CMD tại thư mục muốn chứa project:**
1. Mở File Explorer, vào thư mục muốn lưu (ví dụ `Desktop`)
2. Click vào thanh địa chỉ trên cùng, gõ `cmd`, nhấn Enter
3. Cửa sổ CMD mở ra đúng thư mục đó

**Gõ lệnh sau rồi nhấn Enter:**
```
git clone https://github.com/khanhbq693/KSNB.git
```

Sau khi xong sẽ có thư mục `KSNB` — đây là thư mục làm việc từ nay.

> **Lưu ý:** Chỉ clone 1 lần duy nhất. Những lần sau dùng `git-start.bat` để lấy code mới.

### Bước 4 — Khởi tạo database (chỉ làm 1 lần)

Vào thư mục `KSNB` vừa clone, bấm đúp vào **`start.bat`**.

File này tự động:
- Tạo môi trường Python (`.venv`)
- Cài thư viện cần thiết
- Tạo file `.env` chứa khoá bí mật
- Khởi động ứng dụng

Mở trình duyệt: `http://localhost:8080`  
Tài khoản mẫu: `admin` / `admin123`

> **Quan trọng:** File `.env` được tạo tự động và chứa khoá bí mật. **Tuyệt đối không** đẩy file này lên GitHub.

---

## Phần 3 — Quy trình Làm việc Hàng ngày

### Các file .bat hỗ trợ Git

Thay vì gõ lệnh git thủ công, dùng 4 file `.bat` có sẵn trong thư mục gốc:

| File | Dùng khi nào |
|------|-------------|
| `git-start.bat` | Bắt đầu 1 công việc mới |
| `git-save.bat` | Lưu thay đổi vừa làm |
| `git-submit.bat` | Nộp code xong để người khác review |
| `git-update.bat` | Lấy code mới nhất từ đồng nghiệp |

### Sơ đồ nhánh

```
main        ← code đã kiểm tra, sẵn sàng triển khai (không làm việc trực tiếp)
develop     ← nơi mọi người gộp code vào
nhánh riêng ← mỗi người làm trên đây
```

---

### Bắt đầu công việc mới → `git-start.bat`

Mỗi khi bắt đầu một task mới, vào thư mục `KSNB`, bấm đúp vào `git-start.bat`. File sẽ:
1. Tự động chuyển sang nhánh `develop` và lấy code mới nhất
2. Hỏi tên nhánh → nhập tên rồi Enter

> **Nếu thấy lỗi "not a git repository":** bạn đang chạy file từ sai thư mục — phải chạy từ bên trong thư mục `KSNB` (thư mục đã clone).

Đặt tên nhánh theo quy tắc `<mảng-của-mình>/<mô-tả-ngắn>`:
```
leaves/them-ly-do-huy-don
handover/sua-loi-tinh-tong-to
bundles/cap-nhat-mau-bia-word
staff/them-truong-ma-ipcas
```

---

### Lưu thay đổi → `git-save.bat`

Sau khi sửa xong một phần, bấm đúp vào `git-save.bat`. File sẽ:
1. Hiển thị danh sách file đã thay đổi
2. Hỏi nội dung commit → nhập mô tả rồi Enter

Gõ nội dung commit theo quy tắc `<loại>: <mô tả>`:
```
feat: thêm trường lý do huỷ đơn nghỉ phép
fix: sửa lỗi tính tổng số tờ
refactor: tách hàm xử lý bước duyệt
chore: cập nhật phiên bản thư viện
```

Commit thường xuyên (mỗi tính năng nhỏ 1 commit), không đợi xong hết mới commit.

---

### Nộp code để review → `git-submit.bat`

Khi xong toàn bộ công việc, bấm đúp vào `git-submit.bat`. File sẽ:
1. Kiểm tra còn thay đổi chưa lưu không
2. Tự động cập nhật code mới nhất từ đồng nghiệp
3. Đẩy code lên GitHub
4. Tự mở trình duyệt vào trang tạo Pull Request

Trong trang Pull Request vừa mở, điền mô tả rồi bấm **Create pull request**:
- Làm gì trong PR này?
- Test thế nào để kiểm tra?
- Có thay đổi cấu trúc database không?

---

### Lấy code mới từ đồng nghiệp → `git-update.bat`

Khi có thông báo đồng nghiệp vừa merge code mới vào `develop`, bấm đúp vào `git-update.bat` để cập nhật về máy.

---

## Phần 4 — File Dùng Chung (cẩn thận)

Một số file ảnh hưởng đến toàn bộ hệ thống. Khi cần sửa, phải làm PR riêng và được Người 1 approve.

### Thêm cột mới vào database (`backend/db/migrations.py`)

Thêm vào cuối danh sách `schema_migrations` trong `_ensure_indexes()`:

```python
# Người 3 — 2026-05-20: thêm cột lý do huỷ
"ALTER TABLE leave_records ADD COLUMN cancel_reason TEXT",
```

Tạo PR riêng, ghi rõ: cột nào, bảng nào, ai cần.  
**Phải được Người 1 approve.** Sau khi merge, thông báo nhóm chạy `git-update.bat` rồi khởi động lại app.

### Thêm API router mới (`backend/api/registry.py`)

1. Tạo file `backend/api/<tên>.py` với `router = APIRouter(...)`
2. Mở `backend/api/registry.py`, thêm 1 dòng import và 1 tuple vào `_ROUTERS`
3. Tạo PR riêng, Người 1 approve

### Thêm trang frontend mới (`frontend/pages/`)

Chỉ cần tạo file `frontend/pages/<tên>.py` với `@ui.page("/route")` — **không cần sửa `frontend/main.py`**. Trang tự động được đăng ký khi app khởi động.

### Thêm thư viện (`requirements.txt`)

Thêm vào `requirements.txt` kèm phiên bản cụ thể, ví dụ: `pandas==2.2.2`

Tạo PR riêng, Người 1 approve. Sau khi merge, thông báo nhóm chạy lại `start.bat` (tự cài thư viện mới).

### Thêm enum (`backend/core/enums.py`)

Tạo PR riêng, Người 1 approve.

---

## Phần 5 — Ai Review PR của ai?

| PR từ | Reviewer bắt buộc |
|-------|------------------|
| Người 1 | Người 2 hoặc Người 3 |
| Người 2 | Người 1 |
| Người 3 | Người 1 |
| Người 4 | Người 1 |
| Người 5 | Người 1 |
| Người 6 | Người 1 |
| File dùng chung | **Người 1 bắt buộc** |

Reviewer cần phản hồi trong 1 ngày làm việc.  
**Không được tự merge PR của chính mình.**

---

## Phần 6 — Checklist Trước khi Tạo PR

- [ ] App chạy được trên máy, không lỗi
- [ ] Đã test tính năng mình làm
- [ ] Không còn `print()` debug thừa
- [ ] `git-submit.bat` không báo lỗi `.env` hay conflict
- [ ] Mô tả PR đầy đủ: làm gì, test thế nào, có thay đổi database không

---

## Phần 7 — Tuyệt đối Không được Làm

1. Không push thẳng vào `main` hoặc `develop` — luôn qua Pull Request
2. Không tự merge PR của chính mình
3. Không commit file `.env` (chứa mật khẩu)
4. Không commit file database `data/*.db`
5. Không sửa file của người khác mà không báo trước
6. Không dùng `datetime.utcnow()` — dùng `_vn_now()` từ `backend/database.py`
7. Không dùng SQLAlchemy ORM — chỉ dùng raw SQL với thư viện `sqlite3`
