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
- `backend/main.py` (danh sách migration trong `_ensure_indexes()`)
- `backend/core/enums.py`
- `init_db.py`, `requirements.txt`, `run.py`

---

## Phần 2 — Cài đặt Môi trường (làm 1 lần khi mới vào)

### Bước 1 — Cài Git

Tải tại: https://git-scm.com/download/win

Kiểm tra cài thành công: mở PowerShell, gõ `git --version`

### Bước 2 — Tải code về máy

```
git clone https://github.com/khanhbq693/KSNB.git
cd KSNB
git checkout develop
```

### Bước 3 — Tạo môi trường Python

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Dòng lệnh sẽ có `(venv)` ở đầu — nghĩa là đang trong môi trường riêng.

### Bước 4 — Tạo file `.env`

Tạo file tên `.env` ở thư mục gốc (cùng cấp với `run.py`):

```
SECRET_KEY=bat-ky-chuoi-nao-cung-duoc
DATABASE_URL=sqlite:///./data/ksnb.db
ENV=development
ALLOWED_ORIGINS=http://localhost:8080
```

> **Quan trọng:** File `.env` chứa khoá bí mật. **Tuyệt đối không** đẩy file này lên GitHub.

### Bước 5 — Khởi tạo database (chỉ làm 1 lần)

```
python init_db.py
```

### Bước 6 — Chạy ứng dụng

```
python run.py
```

Mở trình duyệt: `http://localhost:8080`  
Tài khoản mẫu: `admin` / `admin123`

---

## Phần 3 — Quy trình Làm việc Hàng ngày

### Sơ đồ nhánh

```
main        ← code đã kiểm tra, sẵn sàng triển khai (không làm việc trực tiếp)
develop     ← nơi mọi người gộp code vào
nhánh riêng ← mỗi người làm trên đây
```

### Bắt đầu công việc mới

```
# 1. Lấy code mới nhất
git checkout develop
git pull origin develop

# 2. Tạo nhánh riêng (đặt tên theo quy tắc: <mảng>/<mô-tả>)
git checkout -b leaves/them-ly-do-huy-don
```

Ví dụ tên nhánh:
```
leaves/them-ly-do-huy-don
handover/sua-loi-tinh-tong-to
bundles/cap-nhat-mau-bia-word
staff/them-truong-ma-ipcas
```

### Làm việc và lưu thay đổi

```
git add backend/api/leaves.py frontend/pages/leaves.py
git commit -m "feat: thêm trường lý do huỷ đơn nghỉ phép"
```

Loại commit:
- `feat:` — tính năng mới
- `fix:` — sửa lỗi
- `refactor:` — cải thiện code
- `chore:` — cài đặt, thư viện

Commit thường xuyên (mỗi tính năng nhỏ 1 commit), không đợi xong hết mới commit.

### Nộp code để review

```
# Cập nhật code mới nhất trước khi nộp
git fetch origin develop
git rebase origin/develop

# Đẩy lên GitHub
git push origin leaves/them-ly-do-huy-don
```

Sau đó vào GitHub → thấy thông báo "Compare & pull request" → bấm vào → đảm bảo merge **vào `develop`** → điền mô tả → bấm **Create pull request**.

---

## Phần 4 — File Dùng Chung (cẩn thận)

### Thêm cột mới vào database (`backend/main.py`)

Thêm vào cuối danh sách `schema_migrations` trong `_ensure_indexes()`:

```python
# Người 3 — 2026-05-20: thêm cột lý do huỷ
"ALTER TABLE leave_records ADD COLUMN cancel_reason TEXT",
```

Tạo PR riêng cho thay đổi này. Ghi rõ: cột nào, bảng nào, ai cần.  
**Phải được Người 1 approve.** Sau khi merge, thông báo nhóm pull develop và chạy lại app.

### Thêm thư viện (`requirements.txt`)

```
pip show <tên-thư-viện>   # kiểm tra chưa có
# Thêm vào requirements.txt: pandas==2.2.2
```

Tạo PR riêng, Người 1 approve, thông báo nhóm `pip install -r requirements.txt`.

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
- [ ] `git status` không thấy file `.env` hay `data/*.db`
- [ ] Đã rebase trên develop mới nhất
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
