"""Canh cho MỌI trang trong `frontend/pages/` nạp được — import thật, không phải quét tĩnh.

Vì sao cần: `frontend/main.py` nạp trang bằng `pkgutil.iter_modules` + `importlib.import_module`
KHÔNG bọc try/except. Một trang import sai tên là ImportError bắn ra giữa lúc khởi động →
**toàn bộ giao diện không lên**, không riêng trang đó.

Đã xảy ra thật (30/08/2026): `pages/cham_459901.py` còn `from frontend.shared import
open_folder_picker`, trong khi hàm ấy đã bị gỡ ở commit 9b3d310 cùng `/api/fs/browse`
(hộp thoại duyệt cây thư mục cho mọi người đăng nhập liệt kê sạch ổ đĩa máy chủ). Hai
nhánh merge vào nhau, mỗi nhánh đúng phần của mình. 1082 test đều xanh vì không test nào
chạm tới `frontend/pages/` — test frontend duy nhất lúc đó (`test_frontend_api_client_calls`)
đọc file bằng AST nên không bao giờ thực thi câu `import`.

Quét tĩnh không thay được test này: lỗi nằm ở việc tên có tồn tại lúc CHẠY hay không.

Chạy: python -m pytest tests/test_kiem_nap_trang_frontend.py -v
"""

import importlib
import pkgutil

import pytest

import frontend.pages as _pages_pkg


_TEN_TRANG = sorted(m.name for m in pkgutil.iter_modules(_pages_pkg.__path__))


def test_co_it_nhat_mot_trang():
    """Chốt chặn cho chính bài test này: `iter_modules` trả rỗng thì mọi test dưới
    biến mất lặng lẽ và file này thành vô dụng mà vẫn xanh."""
    assert len(_TEN_TRANG) >= 20, f"Chỉ tìm thấy {len(_TEN_TRANG)} trang — đường dẫn sai?"


@pytest.mark.parametrize("ten", _TEN_TRANG)
def test_trang_nap_duoc(ten):
    try:
        importlib.import_module(f"frontend.pages.{ten}")
    except Exception as e:      # noqa: BLE001 — bắt rộng là đúng: main.py không bắt gì cả
        pytest.fail(
            f"frontend/pages/{ten}.py không nạp được: {type(e).__name__}: {e}. "
            "Trang hỏng ở đây làm CẢ giao diện không khởi động (main.py không bọc try/except)."
        )
