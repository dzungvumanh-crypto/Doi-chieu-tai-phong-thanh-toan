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
- `backend/main.py` — App entry; `_ensure_indexes()` chạy schema migration khi khởi động
- `backend/models.py` — SQLAlchemy ORM (tất cả bảng)
- `backend/schemas.py` — Pydantic request/response schemas
- `backend/database.py` — SQLite engine (WAL mode, FK via PRAGMA)
- `backend/core/` — `deps.py` (RBAC), `security.py` (JWT), `sessions.py` (in-memory), `config.py`, `rate_limit.py`
- `backend/api/` — Route handlers theo tính năng
- `backend/services/` — Business logic (đóng tập, in bìa, phiếu nghỉ phép)

**Frontend** (`frontend/`) — NiceGUI SPA, port 8080:
- `frontend/main.py` — Single-file SPA: toàn bộ trang, layout, UI logic
- `frontend/api_client.py` — httpx wrapper; token lưu trong `app.storage.user`

**Templates** (`templates/`) — Word templates (docxtpl):
- `bia_mau_goc.docx` — Bìa tập chứng từ
- `don_xin_nghi_phep_tpl.docx` — Phiếu nghỉ phép

**Database** (`data/`) — SQLite; WAL mode; FK constraints enforced.
