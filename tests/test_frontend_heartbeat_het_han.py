"""Nhịp kiểm tra phiên 60 giây phải đưa người dùng về /login khi phiên HẾT HẠN.

Trước 23/09/2026 nó chỉ bắt `DisplacedSessionError`; phiên hết hạn (8 giờ) rơi xuống
nhánh `Exception` chung → ghi WARNING kèm traceback mỗi phút cho mỗi tab còn mở, người
dùng không được báo. Không có bộ dựng giao diện để test hành vi, nên canh cấu trúc hàm.
"""
import ast
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "frontend" / "shared.py"


def _ham_heartbeat() -> ast.AsyncFunctionDef:
    cay = ast.parse(_SHARED.read_text(encoding="utf-8"))
    for n in ast.walk(cay):
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_session_heartbeat":
            return n
    raise AssertionError("không thấy _session_heartbeat trong frontend/shared.py")


def _ten_loi(handler: ast.ExceptHandler) -> str:
    return ast.unparse(handler.type) if handler.type is not None else ""


def test_bat_phien_het_han_truoc_nhanh_chung():
    khoi_try = next(n for n in ast.walk(_ham_heartbeat()) if isinstance(n, ast.Try))
    ten = [_ten_loi(h) for h in khoi_try.handlers]
    assert "api.SessionExpiredError" in ten, ten
    # Bắt sau `Exception` thì không bao giờ tới được
    assert ten.index("api.SessionExpiredError") < ten.index("Exception"), ten


def test_phien_het_han_chuyen_ve_dang_nhap():
    khoi_try = next(n for n in ast.walk(_ham_heartbeat()) if isinstance(n, ast.Try))
    nhanh = next(h for h in khoi_try.handlers if _ten_loi(h) == "api.SessionExpiredError")
    ma = "\n".join(ast.unparse(s) for s in nhanh.body)
    assert "client.open('/login')" in ma, ma
