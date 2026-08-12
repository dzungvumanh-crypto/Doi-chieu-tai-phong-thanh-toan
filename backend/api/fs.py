"""API liệt kê thư mục con của 1 path trên máy server — phục vụ dialog chọn
thư mục ở frontend (bấm chọn thay vì gõ tay đường dẫn). Chỉ liệt kê thư mục
(không liệt kê file) vì đây thuần túy là folder-picker. Dùng chung cho
cham_ach.py và cham_ilo1000.py — không gắn require_feature vì cần OR giữa
menu.cham_ach và menu.cham_ilo1000 (require_feature chỉ nhận 1 feature_code)."""

import ctypes
import os
import string

from fastapi import APIRouter, Depends, HTTPException

from backend.core.deps import get_current_staff

router = APIRouter(prefix='/api/fs', tags=['fs'])

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
    # Người dùng hay copy đường dẫn của 1 FILE thay vì thư mục (VD copy từ cột
    # đường dẫn trong Explorer) — mở thư mục chứa nó thay vì báo lỗi bế tắc.
    if not os.path.isdir(abs_path) and os.path.isfile(abs_path):
        abs_path = os.path.dirname(abs_path)
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
def browse(path: str | None = None, _staff: dict = Depends(get_current_staff)):
    """Liệt kê thư mục con của `path`. path rỗng/None → danh sách ổ đĩa."""
    if not path or not path.strip():
        return _list_drives()
    # Windows "Copy as path" bọc đường dẫn trong dấu nháy kép.
    return _list_dir(path.strip().strip('"'))
