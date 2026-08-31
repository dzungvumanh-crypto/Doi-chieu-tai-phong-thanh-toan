"""API liệt kê thư mục con của 1 path trên máy server — phục vụ dialog chọn
thư mục ở frontend (bấm chọn thay vì gõ tay đường dẫn). Chỉ liệt kê thư mục
(không liệt kê file) vì đây thuần túy là folder-picker.

Trên NHÁNH NÀY chỉ cham459901.py dùng open_folder_picker() — cham_ach.py và
doi_chieu_song_phuong.py ở đây KHÔNG có chế độ chọn thư mục server (đã grep,
0 kết quả), khác nhánh feat/doi-chieu-song-phuong-den-2026-08-30 (PR#68) nơi cả
4 module đều dùng chung. Chỉ khai menu.cham_459901 — không copy nguyên danh
sách 4 mã từ PR#68 sang, tránh cấp thừa quyền duyệt thư mục server cho
ACH/Song-phương trên nhánh này (chốt bởi sentinel test
tests/test_ach_quyen.py::TestFsBrowseKhongLoRaNgoai — menu.cham_ach KHÔNG được
lọt qua). Khi rebase/gộp nhánh, so lại danh sách này với PR#68.

Review PR#43 (khanhbq693): commit trước mang open_folder_picker() (frontend)
từ nhánh feat/doi-chieu-song-phuong-den-2026-08-30 sang nhưng QUÊN mang theo
router backend này + đăng ký ở registry.py — dialog chọn thư mục gọi
GET /api/fs/browse ra 404, rơi vào nhánh except. File này port lại có vá
quyền (require_any_feature) + giới hạn phạm vi duyệt (FOLDER_PICKER_ROOTS)
từ PR#68, nhưng danh sách feature-code khai riêng cho đúng nhánh này."""

import ctypes
import logging
import os
import string

from fastapi import APIRouter, Depends, HTTPException

from backend.core.config import settings
from backend.core.deps import require_any_feature

router = APIRouter(prefix='/api/fs', tags=['fs'])

_CO_QUYEN_DUYET_THU_MUC = require_any_feature('menu.cham_459901')

_SKIP_NAMES = {'$recycle.bin', 'system volume information'}
_log = logging.getLogger(__name__)


def _pham_vi_cho_phep() -> list[str]:
    """Danh sách thư mục gốc được phép duyệt (settings.FOLDER_PICKER_ROOTS), đã chuẩn
    hoá tuyệt đối. Rỗng = KHÔNG giới hạn (xem cảnh báo ở _canh_bao_khong_gioi_han)."""
    return [os.path.abspath(p) for p in settings.FOLDER_PICKER_ROOTS]


def _trong_pham_vi(abs_path: str, roots: list[str]) -> bool:
    norm = os.path.normcase(os.path.normpath(abs_path))
    return any(
        norm == os.path.normcase(os.path.normpath(r))
        or norm.startswith(os.path.normcase(os.path.normpath(r)) + os.sep)
        for r in roots
    )


def _canh_bao_khong_gioi_han() -> None:
    _log.warning(
        'FOLDER_PICKER_ROOTS chưa cấu hình trong .env — /api/fs/browse KHÔNG giới hạn '
        'phạm vi (duyệt được mọi ổ đĩa/thư mục máy chủ). Đặt FOLDER_PICKER_ROOTS để vá '
        'lỗ hổng này (xem backend/core/config.py).'
    )


def _list_drives() -> dict:
    """path rỗng/None → điểm khởi đầu duyệt cây thư mục.

    Có cấu hình FOLDER_PICKER_ROOTS: hiện đúng danh sách gốc được phép (không phải ổ
    đĩa thật) — người dùng chỉ thấy và duyệt được trong phạm vi đó.

    Không cấu hình (rỗng): hành vi CŨ — liệt kê toàn bộ ổ đĩa Windows. Dùng
    GetLogicalDrives() (chỉ đọc bitmask trong bộ nhớ, KHÔNG chạm filesystem) thay vì
    lặp os.path.isdir cho từng chữ cái — tránh treo nếu có ổ mạng đã map nhưng mất kết
    nối (đã gặp thật với G:\\ trong dự án)."""
    roots = _pham_vi_cho_phep()
    if roots:
        entries = [
            {'name': os.path.basename(r.rstrip(os.sep)) or r, 'path': r} for r in roots
        ]
        entries.sort(key=lambda x: x['name'].lower())
        return {'path': None, 'parent': None, 'entries': entries}

    _canh_bao_khong_gioi_han()
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


def _compute_parent(abs_path: str, roots: list[str]) -> str | None:
    """None nghĩa là 'lên nữa thì về màn khởi đầu' (danh sách gốc cho phép, hoặc danh
    sách ổ đĩa nếu không giới hạn). Có giới hạn: dừng đúng tại gốc, không lộ ra thư mục
    cha THẬT của gốc (VD gốc 'G:\\Đối chiếu song phương' thì 'lên' dừng ở đó, không lộ
    ra 'G:\\')."""
    if roots and any(
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
    if roots:
        if not _trong_pham_vi(abs_path, roots):
            raise HTTPException(403, f'Thư mục ngoài phạm vi cho phép: {abs_path}')
    else:
        _canh_bao_khong_gioi_han()
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
