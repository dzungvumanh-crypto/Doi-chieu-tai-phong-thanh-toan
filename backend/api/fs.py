"""API liệt kê thư mục con của 1 path trên máy server — phục vụ dialog chọn
thư mục ở frontend (bấm chọn thay vì gõ tay đường dẫn). Chỉ liệt kê thư mục
(không liệt kê file) vì đây thuần túy là folder-picker. Dùng chung cho
cham_ach.py, cham_ilo1000.py, cham459901.py, doi_chieu_song_phuong.py —
require_any_feature() cho qua nếu có ÍT NHẤT MỘT trong các menu đó (review
khanhbq693 PR#68: trước đây chỉ gắn get_current_staff, không giới hạn feature
nào — BẤT KỲ ai đã đăng nhập, kể cả chuyên viên không có menu nào trong 4 module
này, liệt kê được toàn bộ ổ đĩa/thư mục trên máy chủ).

Fail-closed (2026-09-01, review khanhbq693 PR#68 mục B2) — CHƯA cấu hình
FOLDER_PICKER_ROOTS thì route báo lỗi rõ ràng, KHÔNG mặc định liệt kê toàn bộ ổ
đĩa. Cùng nguyên tắc `cham459901_folder_roots()` (backend/core/config.py)."""

import os

from fastapi import APIRouter, Depends, HTTPException

from backend.core.config import folder_picker_roots
from backend.core.deps import require_any_feature

router = APIRouter(prefix='/api/fs', tags=['fs'])

_CO_QUYEN_DUYET_THU_MUC = require_any_feature(
    'menu.cham_ach', 'menu.cham_ilo1000', 'menu.cham_459901', 'menu.doi_chieu_song_phuong',
)

_SKIP_NAMES = {'$recycle.bin', 'system volume information'}


def _pham_vi_cho_phep() -> list[str]:
    """Danh sách thư mục gốc được phép duyệt (FOLDER_PICKER_ROOTS trong .env), đã chuẩn hoá
    tuyệt đối. Raise HTTPException(400) nếu chưa cấu hình — fail-closed."""
    try:
        roots = folder_picker_roots()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    return [os.path.abspath(str(p)) for p in roots]


def _trong_pham_vi(abs_path: str, roots: list[str]) -> bool:
    norm = os.path.normcase(os.path.normpath(abs_path))
    return any(
        norm == os.path.normcase(os.path.normpath(r))
        or norm.startswith(os.path.normcase(os.path.normpath(r)) + os.sep)
        for r in roots
    )


def _list_drives() -> dict:
    """path rỗng/None → điểm khởi đầu duyệt cây thư mục — luôn là danh sách gốc cho phép
    (FOLDER_PICKER_ROOTS), KHÔNG phải danh sách ổ đĩa thật (`_pham_vi_cho_phep()` đã fail-closed,
    raise nếu chưa cấu hình — không còn nhánh 'không giới hạn')."""
    roots = _pham_vi_cho_phep()
    entries = [
        {'name': os.path.basename(r.rstrip(os.sep)) or r, 'path': r} for r in roots
    ]
    entries.sort(key=lambda x: x['name'].lower())
    return {'path': None, 'parent': None, 'entries': entries}


def _breadcrumbs(abs_path: str) -> list[dict]:
    """Danh sách {name, path} từ ổ đĩa tới thư mục hiện tại — phục vụ thanh
    breadcrumb kiểu Windows Explorer (bấm 1 đoạn để nhảy thẳng tới đó)."""
    drive, tail = os.path.splitdrive(abs_path)
    crumbs = [{'name': drive + os.sep, 'path': drive + os.sep}]
    cur = drive + os.sep
    for part in [p for p in tail.split(os.sep) if p]:
        cur = os.path.join(cur, part)
        crumbs.append({'name': part, 'path': cur})
    return crumbs


def _compute_parent(abs_path: str, roots: list[str]) -> str | None:
    """None nghĩa là 'lên nữa thì về màn khởi đầu' (danh sách gốc cho phép). Dừng đúng tại
    gốc, không lộ ra thư mục cha THẬT của gốc (VD gốc 'G:\\Đối chiếu song phương' thì 'lên'
    dừng ở đó, không lộ ra 'G:\\')."""
    if any(
        os.path.normcase(os.path.normpath(abs_path)) == os.path.normcase(os.path.normpath(r))
        for r in roots
    ):
        return None
    _drive, tail = os.path.splitdrive(abs_path)
    if not tail or tail in ('\\', '/'):
        return None
    parent = os.path.dirname(abs_path)
    if os.path.normcase(os.path.normpath(parent)) == os.path.normcase(os.path.normpath(abs_path)):
        return None
    return parent


def _list_dir(raw_path: str) -> dict:
    abs_path = os.path.abspath(raw_path)
    roots = _pham_vi_cho_phep()
    if not _trong_pham_vi(abs_path, roots):
        raise HTTPException(403, f'Thư mục ngoài phạm vi cho phép: {abs_path}')
    if not os.path.isdir(abs_path):
        raise HTTPException(400, f'Thư mục không tồn tại: {abs_path}')

    entries = []
    try:
        with os.scandir(abs_path) as it:
            for entry in it:
                if entry.name.lower() in _SKIP_NAMES:
                    continue
                try:
                    if entry.is_dir():
                        entries.append({'name': entry.name, 'path': entry.path})
                except OSError:
                    continue  # entry lỗi riêng lẻ (symlink hỏng...) — bỏ qua, không chặn cả danh sách
    except PermissionError:
        raise HTTPException(403, f'Không có quyền đọc thư mục: {abs_path}')
    except OSError as e:
        raise HTTPException(
            502, f'Không đọc được thư mục (có thể ổ mạng mất kết nối): {abs_path} — {e}'
        )

    entries.sort(key=lambda x: x['name'].lower())
    return {
        'path': abs_path,
        'parent': _compute_parent(abs_path, roots),
        'entries': entries,
        'breadcrumbs': _breadcrumbs(abs_path),
    }


@router.get('/browse')
def browse(path: str | None = None, _staff: dict = Depends(_CO_QUYEN_DUYET_THU_MUC)):
    """Liệt kê thư mục con của `path`. path rỗng/None → danh sách ổ đĩa."""
    if not path or not path.strip():
        return _list_drives()
    return _list_dir(path.strip())
