# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See also: @DESIGN.md @SKILL.md

## Commands

```bash
pip install -r requirements.txt   # Cài thư viện
python init_db.py                  # Khởi tạo DB lần đầu
python run.py                      # Chạy cả backend + frontend
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000  # Backend riêng
python frontend/main.py            # Frontend riêng
```

## Architecture

**Backend** (`backend/`) — FastAPI REST API, port 8000:
- `backend/main.py` — App entry (~80 LOC); lifespan gọi migrations, routers đăng ký qua registry
- `backend/db/migrations.py` — `_create_tables()` + `_ensure_indexes()`; **thêm migration tại đây**
- `backend/api/registry.py` — Danh sách tất cả routers; **thêm router mới tại đây**
- `backend/schemas/` — Pydantic request/response schemas (package)
- `backend/database.py` — SQLite engine (WAL mode, FK via PRAGMA) + `_vn_now()`
- `backend/core/` — `deps.py` (RBAC), `security.py` (JWT), `sessions.py` (DB-backed, bảng `login_sessions`), `config.py`, `rate_limit.py`

**Bảng nhân sự tên là `user_tttt`** (tên cũ `ksnb_staff` đã đổi). Tài liệu trong `Plan/` và `Upgrade/`
là lịch sử, vẫn dùng tên cũ — không copy tên bảng từ đó. Xem `DESIGN.md`.
- `backend/api/` — Route handlers theo tính năng
- `backend/services/` — Business logic (đóng tập, in bìa, phiếu nghỉ phép)

**Frontend** (`frontend/`) — NiceGUI SPA, port 8080:
- `frontend/main.py` — Entry point; auto-discovers pages qua `pkgutil.iter_modules`
- `frontend/pages/` — Mỗi file là một trang (`@ui.page`); thêm page mới chỉ cần tạo file
- `frontend/shared.py` — Layout, sidebar, helpers dùng chung
- `frontend/api_client.py` — httpx wrapper; token lưu trong `app.storage.user`

**Templates** (`templates/`) — Word templates (docxtpl):
- `bia_mau_goc.docx` — Bìa tập chứng từ
- `don_xin_nghi_phep_tpl.docx` — Phiếu nghỉ phép

**Database** (`data/`) — SQLite; WAL mode; FK constraints enforced.

## Implementation Notes

Mọi quyết định kỹ thuật không hiển nhiên, đánh đổi thiết kế, và vấn đề phát hiện trong quá trình implement **phải được ghi vào [`Implementation-notes.html`](Implementation-notes.html)** — cập nhật liên tục, không để sau.

Dùng format: card per topic, bảng cho so sánh trước/sau và đánh đổi, badge màu cho trạng thái.

## Quy tắc làm việc

- **Dọn data test:** Sau khi test bất kỳ tính năng nào, phải tự xóa toàn bộ data đã tạo để test (user, phòng ban, chứng từ, đơn nghỉ phép, v.v.) trước khi báo hoàn thành. Không chờ người dùng nhắc.
