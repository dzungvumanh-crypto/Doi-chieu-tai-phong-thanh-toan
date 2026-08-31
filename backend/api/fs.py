"""API liệt kê thư mục con của 1 path trên máy server — phục vụ dialog chọn
thư mục ở frontend (bấm chọn thay vì gõ tay đường dẫn). Chỉ liệt kê thư mục
(không liệt kê file) vì đây thuần túy là folder-picker. Dùng chung cho
cham_ach.py, cham_ilo1000.py, cham459901.py, doi_chieu_song_phuong.py —
require_any_feature() cho qua nếu có ÍT NHẤT MỘT trong các menu đó (review
khanhbq693 PR#68: trước đây chỉ gắn get_current_staff, không giới hạn feature
nào — BẤT KỲ ai đã đăng nhập, kể cả chuyên viên không có menu nào trong 4 module
này, liệt kê được toàn bộ ổ đĩa/thư mục trên máy chủ)."""

import ctypes
import os
import string

from fastapi import APIRouter, Depends, HTTPException

from backend.core.deps import require_any_feature

router = APIRouter(prefix='/api/fs', tags=['fs'])

_CO_QUYEN_DUYET_THU_MUC = require_any_feature(
    'menu.cham_ach', 'menu.cham_ilo1000', 'menu.cham_459901', 'menu.doi_chieu_song_phuong',
)

_SKIP_NAMES = {'$recycle.bin', 'system volume information'}


def _list_drives() -> dict:
    """path rỗng/None → liệt kê ổ đĩa Windows. Dùng GetLogicalDrives() (chỉ đọc
    bitmask trong bộ nhớ, KHÔNG chạm filesystem) thay vì lặp os.path.isdir cho
    từng chữ cái — tránh treo nếu có ổ mạng đã map nhưng mất kết nối (đã gặp
    thật với G:\\ trong dự án)."""
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    entries = [
        {'name': f'{letter}:\\', 'path': f'{letter}:\\'}
        for i, letter in enumerate(string.ascii_uppercase)
        if bitmask & (1 << i)
    ]
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


def _compute_parent(abs_path: str) -> str | None:
    """None nghĩa là 'lên nữa thì về danh sách ổ đĩa'."""
    _drive, tail = os.path.splitdrive(abs_path)
    if not tail or tail in ('\\', '/'):
        return None
    parent = os.path.dirname(abs_path)
    if os.path.normcase(os.path.normpath(parent)) == os.path.normcase(os.path.normpath(abs_path)):
        return None
    return parent


def _list_dir(raw_path: str) -> dict:
    abs_path = os.path.abspath(raw_path)
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
        'parent': _compute_parent(abs_path),
        'entries': entries,
        'breadcrumbs': _breadcrumbs(abs_path),
    }


@router.get('/browse')
def browse(path: str | None = None, _staff: dict = Depends(_CO_QUYEN_DUYET_THU_MUC)):
    """Liệt kê thư mục con của `path`. path rỗng/None → danh sách ổ đĩa."""
    if not path or not path.strip():
        return _list_drives()
    return _list_dir(path.strip())
