"""Trang Bàn giao vẫn dựng đủ khi WebSocket nối chậm quá 3 giây.

`app.storage.tab` ném RuntimeError khi trình duyệt chưa nối WebSocket. Trang chờ
`client.connected()` rồi nuốt lỗi hết giờ với chú thích "vẫn dựng tiếp", nhưng dòng
đọc bộ lọc ngay sau đó lại ném → nửa dưới trang không hiện (logs/frontend.log
22/09/2026). Canh: mọi lần chạm `app.storage.tab` trong trang phải được bọc.
"""
import ast
from pathlib import Path

_TRANG = Path(__file__).resolve().parents[1] / "frontend" / "pages" / "handovers.py"


def _bat_runtime_error(khoi: ast.Try) -> bool:
    for h in khoi.handlers:
        ten = ast.unparse(h.type) if h.type is not None else ""
        if "RuntimeError" in ten or ten in ("", "Exception"):
            return True
    return False


def test_moi_lan_cham_storage_tab_deu_duoc_boc():
    cay = ast.parse(_TRANG.read_text(encoding="utf-8"))
    cha: dict[ast.AST, ast.AST] = {}
    for n in ast.walk(cay):
        for con in ast.iter_child_nodes(n):
            cha[con] = n

    cham = [n for n in ast.walk(cay)
            if isinstance(n, ast.Attribute) and ast.unparse(n) == "app.storage.tab"]
    assert cham, "không thấy app.storage.tab — test đã lỗi thời?"
    for n in cham:
        p, duoc_boc = n, False
        while p in cha:
            p = cha[p]
            if isinstance(p, ast.Try) and _bat_runtime_error(p):
                duoc_boc = True
                break
        assert duoc_boc, f"dòng {n.lineno}: app.storage.tab không được bọc try/except RuntimeError"
