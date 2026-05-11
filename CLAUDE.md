# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database (first run only)
python init_db.py

# Run backend (FastAPI, port 8000)
python run.py
# or
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Run frontend (NiceGUI, port 8080)
python frontend/main.py
```

## Architecture

**Backend** (`backend/`) — FastAPI REST API on port 8000:
- `backend/main.py` — App entry, `_ensure_indexes()` runs schema migrations on startup
- `backend/models.py` — SQLAlchemy ORM models (all tables)
- `backend/schemas.py` — Pydantic request/response schemas
- `backend/database.py` — SQLite engine (WAL mode, FK enforced via PRAGMA)
- `backend/core/` — `deps.py` (RBAC deps), `security.py` (JWT), `sessions.py` (in-memory session store), `config.py`
- `backend/api/` — Route handlers per feature
- `backend/services/` — Business logic (bundle packing, cover/leave Word generation)

**Frontend** (`frontend/`) — NiceGUI SPA on port 8080:
- `frontend/main.py` — Single-file SPA: all pages, shared layout, UI logic
- `frontend/api_client.py` — httpx wrapper; token stored per-user in `app.storage.user`

**Templates** (`templates/`) — Word templates rendered via docxtpl:
- `bia_mau_goc.docx` — Bìa tập chứng từ
- `don_xin_nghi_phep_tpl.docx` — Phiếu nghỉ phép

**Database** (`data/`) — SQLite file(s); WAL mode; all FK constraints enforced.

## Key Patterns

### Timestamps
Use `_vn_now()` from `backend/models.py` for all timestamps (UTC+7, naive datetime). Never use `datetime.utcnow()`.

### Schema Migrations
Add new `ALTER TABLE` or `CREATE TABLE` SQL strings to the `schema_migrations` list in `backend/main.py::_ensure_indexes()`. They run idempotently on startup — duplicate-column errors are silently swallowed; all other errors are logged and raised.

### Authentication & Sessions
- JWT tokens verified by `get_current_staff` in `deps.py`
- Sessions stored in-memory (`backend/core/sessions.py`) — lost on restart
- 401 from backend → `SessionExpiredError` in `api_client.py` → `_handle_api_error()` redirects to `/login`
- Always check `isinstance(e, api.SessionExpiredError)` before generic `Exception` in `asyncio.gather()` blocks

### RBAC Dependencies (deps.py)
| Dependency | Allowed roles |
|---|---|
| `get_current_staff` | Any authenticated |
| `require_admin` | admin |
| `require_hkv_or_above` | admin, hau_kiem_vien |
| `require_pho_phong_or_above` | admin, hau_kiem_vien, truong_phong, pho_phong, controller |
| `require_handover_write` | admin, hau_kiem_vien, truong_phong, pho_phong, controller, chuyen_vien |
| `require_ksnb` | All except chuyen_vien |
| `require_ksv` | admin, truong_phong, pho_phong, controller |
| `require_gd_level` | admin, giam_doc, pho_giam_doc |

### Role Hierarchy
```
admin > hau_kiem_vien > giam_doc/pho_giam_doc > truong_phong > pho_phong > chuyen_vien
```
`controller` is deprecated (kept for backward compat); new records use `pho_phong`.

### Frontend Async Pattern
All API calls are wrapped: `await asyncio.to_thread(api.get, "/path", params)`.
Use `asyncio.gather(..., return_exceptions=True)` for parallel calls; check each result for `api.SessionExpiredError` before the generic fallback.

### Error Handling (Frontend)
```python
try:
    result = await asyncio.to_thread(api.post, "/api/...", body)
except Exception as e:
    if _handle_api_error(e):  # returns True and redirects on SessionExpiredError
        return
```

### Leave Approval Workflow
Status flow: `pending_ksv → pending_gd → approved | rejected | cancelled`
- Step 1: KSV (Trưởng phòng or Phó phòng, auto-assigned on create)
- Step 2: GĐ (auto-assigned when KSV approves; PGĐ allowed if active `DelegationRecord` exists)
- `resubmit`: rejected → pending_ksv (re-assigns KSV approver)
- `cancel`: pending_ksv → cancelled (soft delete)
- `used_leave_days` adjusted via `_apply_status_transition()` helper (idempotent)

### Word Template Generation
```python
from docxtpl import DocxTemplate
tpl = DocxTemplate("templates/don_xin_nghi_phep_tpl.docx")
tpl.render(context_dict)
buf = io.BytesIO()
tpl.save(buf)
```
Use `_download_headers(filename)` from `backend/api/bundles.py` for RFC 6266 UTF-8 Content-Disposition.

## Nguyên tắc giao tiếp

- Không nịnh. Vào thẳng vấn đề.
- Phản biện trước, ủng hộ sau. Khi người dùng đưa quan điểm, trình bày lập luận mạnh nhất chống lại nó trước khi đồng ý.
- Không bị neo vào số liệu người dùng đưa ra. Tự ước lượng hoặc kiểm tra độc lập trước, rồi mới so sánh.
- Không xuống nước khi bị push back. Chỉ đổi quan điểm khi có bằng chứng mới, không phải vì người dùng không vui.
- Gắn nhãn độ tin cậy cho mọi thông tin thực tế: **cao / trung bình / thấp / không biết**.
- **Khi giải thích lỗi hoặc vấn đề kỹ thuật**: dùng ngôn ngữ và hình ảnh đời thường (ví von, so sánh thực tế) để người không chuyên CNTT có thể hiểu được nguyên nhân và mức độ ảnh hưởng. Tránh thuật ngữ kỹ thuật khi không cần thiết.

## Quy ước làm việc

- Dùng **tiếng Việt** khi giải thích, phân tích, và viết comment.
- Code ngắn gọn, rạch ròi từng phần: tách logic bằng dòng trống + comment section ngắn (ví dụ `# ── Validate ──`). Không viết docstring dài nhiều dòng.
- Làm từ từ, ưu tiên lời giải đúng hơn là vượt qua test bằng mọi giá.

### Khi gặp khó

- **Nguyên tắc số 1 — đừng để hệ thống thất bại liên tục.** Nếu sau 3–4 lần sửa vẫn chưa xong, dừng lại, làm mới ngữ cảnh và chia nhỏ nhiệm vụ. Không tiếp tục vòng lặp sai→sửa→sai.
- Nếu yêu cầu có thể không khả thi, nói thẳng: *"Ràng buộc này có thể là không khả thi"* — không cố ép làm bằng mọi giá.
- Nếu không giải được thì nói thẳng, đừng dùng mẹo hoặc hack để vượt qua.

### Code chất lượng — những điều không được làm

- Hardcode giá trị chỉ để khớp test.
- Thêm nhánh xử lý đặc biệt không có ý nghĩa nghiệp vụ.
- Logic chỉ hoạt động với dữ liệu mẫu nhưng không tổng quát.
- `try/except` nuốt lỗi mà không ghi log.

### Kiểm thử

- Bộ test cần có **adversarial cases**: đầu vào biên (edge cases), đầu vào sai, fuzz/property-based test. Chỉ test "đầu vào đẹp" rất dễ bị hardcode qua.
- Session làm việc càng dài thì rủi ro tích lũy càng cao — nên chia nhỏ phiên, tránh kéo dài ngữ cảnh quá lâu.

### Trước và sau mỗi thay đổi

Trước khi sửa, phải xác định **phạm vi ảnh hưởng**:
- Liệt kê các tính năng/endpoint/UI component có thể bị tác động (trực tiếp hoặc gián tiếp).
- Nếu thay đổi model/schema → kiểm tra tất cả nơi dùng field đó (backend API, frontend, migrations).
- Nếu thay đổi logic helper → kiểm tra tất cả caller.

Sau khi sửa, phải **xác nhận không có regression**:
- Đọc lại các route/component liên quan để đảm bảo chúng vẫn hoạt động đúng.
- Nếu xóa hoặc đổi tên hàm/biến → grep toàn bộ codebase để chắc không còn reference cũ.
- Không báo "hoàn thành" nếu chưa kiểm tra tác động lan rộng.
