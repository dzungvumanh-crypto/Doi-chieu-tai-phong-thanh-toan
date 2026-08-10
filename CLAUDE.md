# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

See also: @DESIGN.md @SKILL.md

**Bắt đầu phiên mới → đọc 2 file này TRƯỚC:**
- [`docs/VIEC-CAN-LAM.md`](docs/VIEC-CAN-LAM.md) — sổ việc cần làm, ưu tiên, ai làm bước tiếp.
- [`docs/BOI-CANH-DU-AN.md`](docs/BOI-CANH-DU-AN.md) — bối cảnh nghiệp vụ, bẫy đã dính, trạng thái.

Đó là những thứ không suy ra được từ code hay git log.

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

## Testing

```bash
.venv\Scripts\python.exe -m pytest tests/ -v          # TOÀN BỘ test suite
.venv\Scripts\python.exe -m pytest tests/test_X.py -v # 1 file
```

**Quan trọng — dùng đúng `.venv`:** máy dev có nhiều Python song song; `.venv` (Python 3.12) là môi trường
thật của dự án (đủ `python-jose`, `fastapi`, v.v., dùng bởi `run.py`) nhưng có thể thiếu `pytest`
(`pip install pytest` một lần nếu vậy). Python hệ thống có thể có `pytest` nhưng thiếu dependency backend
(`jose`...) — dùng nó chỉ chạy được test không import `backend.main`/API layer.

**2 kiểu test, chọn theo đối tượng cần kiểm tra:**

| Kiểu | Khi dùng | File mẫu |
|---|---|---|
| **Thuật toán/service** — import thẳng hàm từ `backend/services/*.py`, DataFrame tổng hợp nhỏ, không cần DB/HTTP | Logic phân loại, đối chiếu, tính toán — nơi sai sót gây hậu quả tài chính | `tests/test_cham459901_algorithm.py`, `tests/test_ilo1000_algorithm.py` |
| **API-level** — `TestClient` từ `tests/conftest.py::admin_client`, gọi thật qua route `backend/api/*.py` | Hợp đồng request/response, validate input, mã lỗi HTTP, luồng nhiều bước (process → poll → cancel/delete) | `tests/test_cham459901_api.py` |

`admin_client` (trong `conftest.py`) override `get_current_staff`/`get_db` để bypass JWT/session/DB thật —
không cần tài khoản đăng nhập thật, không đụng `data/*.db`. Route nào thật sự cần đọc/ghi DB thì override
`get_db` riêng trong test đó với schema cần thiết, đừng dựa vào DB thật.

**Nguyên tắc viết test** (đúc kết từ 2 module trên, áp dụng dự án):
- File thu nhỏ thật (CSV/xlsx/zip tổng hợp), **không mock** I/O — mock che giấu lỗi format thật (xem `doi-chieu` skill).
- Với dữ liệu tài chính: luôn có test bất biến số học (bảo toàn dòng, Tổng Nợ = Tổng Có khi rule yêu cầu).
- Test regression cho mỗi bug đã tìm+sửa (đặt tên rõ mô tả case, VD `test_1000ht_runs_before_ccn_to_avoid_being_stolen`).
- `monkeypatch.setattr(module, 'TEMP_DIR', tmp_path)` khi test chạm file hệ thống — không được đụng `data/` thật.

## Implementation Notes

Mọi quyết định kỹ thuật không hiển nhiên, đánh đổi thiết kế, và vấn đề phát hiện trong quá trình implement **phải được ghi vào [`Implementation-notes.html`](Implementation-notes.html)** — cập nhật liên tục, không để sau.

Dùng format: card per topic, bảng cho so sánh trước/sau và đánh đổi, badge màu cho trạng thái.

## Quy tắc làm việc

- **Dọn data test:** Sau khi test bất kỳ tính năng nào, phải tự xóa toàn bộ data đã tạo để test (user, phòng ban, chứng từ, đơn nghỉ phép, v.v.) trước khi báo hoàn thành. Không chờ người dùng nhắc.

## Làm việc từ điện thoại / phiên cloud

Dự án chạy song song hai nơi: **laptop** (Claude Code trong VS Code, có ổ dữ liệu thật) và
**phiên cloud** `claude.ai/code` (điều khiển từ app Claude trên điện thoại).

```bash
claude --cloud "mô tả việc"   # laptop → tạo phiên cloud, làm tiếp được trên điện thoại
claude --teleport             # cloud → kéo cả hội thoại + nhánh code về terminal
```

**Máy ảo cloud KHÔNG có dữ liệu thật** — toàn bộ `data/`, `Cham ILO1000/`, `Đối chiếu ACH/`,
`Chấm 459901/` (~50GB) đã gitignore. Trong phiên cloud:

- **Được:** đọc/sửa code, viết + chạy test với dữ liệu tổng hợp nhỏ, viết tài liệu, phân tích
  nghiệp vụ, lập kế hoạch, rà logic tìm bug.
- **Không được:** chạy pipeline đối chiếu thật, đối chiếu golden sample, kiểm thử UI
  click-through. **Đừng đề xuất "chạy thử để xác nhận"** — để dành cho phiên trên laptop.

⚠️ Gói Pro/Max chỉ có 2 mức chia sẻ phiên: **Private** và **Public** (mọi người dùng claude.ai
đều xem được). Phiên có thể chứa code và dữ liệu nghiệp vụ — **giữ Private, không bật share**.

Cấu hình Claude Code tách 2 tầng: [`.claude/settings.json`](.claude/settings.json) dùng chung
(commit, portable) — [`.claude/settings.local.json`](.claude/settings.local.json) riêng từng
máy (gitignore: đường dẫn ổ mạng, thư mục temp, lệnh scratch).
