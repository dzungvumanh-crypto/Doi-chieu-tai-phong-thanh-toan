"""Canh hộp ngữ cảnh của ngăn kéo chi tiết đơn nghỉ phép luôn được điền đủ.

Khi tách `open_detail` (728 dòng) khỏi hàm trang, 17 thứ nó từng mượn qua closure nay đi
qua `ChiTietCtx`. Kiểu hỏng của cách này: thêm một trường vào dataclass mà quên gán ở trang
→ `None` lặng lẽ, chỉ nổ khi người dùng bấm mở đơn. Không test nào dựng trang nên test này
đối chiếu TĨNH: mọi trường của ChiTietCtx phải được trang gán, bằng tham số lúc dựng hoặc
bằng `_ctx.<tên> = …` sau đó.

Chạy: .venv\Scripts\python.exe -m pytest tests/test_leaves_chi_tiet_ctx.py -v
"""
import ast
from pathlib import Path

from frontend.pages.leaves._chi_tiet_don import ChiTietCtx

_TRANG = Path("frontend/pages/leaves/__init__.py")


def _cay_trang() -> ast.Module:
    return ast.parse(_TRANG.read_text(encoding="utf-8"))


def test_moi_truong_ctx_deu_duoc_trang_gan():
    cay = _cay_trang()
    dat = set()
    for n in ast.walk(cay):
        # _ctx = _chi_tiet_don.ChiTietCtx(user_id=…, …)
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("ChiTietCtx"):
            dat |= {kw.arg for kw in n.keywords if kw.arg}
        # _ctx.leave_tabs = leave_tabs
        if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and \
                isinstance(n.value, ast.Name) and n.value.id == "_ctx":
            dat.add(n.attr)

    thieu = set(ChiTietCtx.__dataclass_fields__) - dat
    assert not thieu, f"Trang chưa gán cho ctx: {sorted(thieu)} — ngăn kéo chi tiết sẽ thấy None"


def test_than_chi_tiet_khong_con_muon_ten_cua_trang():
    """Thân đã tách phải tự đứng được: mọi thứ của trang đi qua `ctx`."""
    ma = Path("frontend/pages/leaves/_chi_tiet_don.py").read_text(encoding="utf-8")
    cay = ast.parse(ma)
    ten_module = {n.name for n in cay.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for n in cay.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            ten_module |= {(a.asname or a.name).split(".")[0] for a in n.names}
    ham = next(n for n in cay.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "mo_chi_tiet")

    gan_trong = {x.id for x in ast.walk(ham) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
    gan_trong |= {x.name for x in ast.walk(ham) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))}
    gan_trong |= {a.arg for x in ast.walk(ham) if isinstance(x, (ast.arguments,)) for a in x.args}
    gan_trong |= {x.arg for x in ast.walk(ham) if isinstance(x, ast.arg)}
    # `except ... as e` cũng là một phép gán tên, nhưng AST để riêng ở ExceptHandler.name
    gan_trong |= {x.name for x in ast.walk(ham) if isinstance(x, ast.ExceptHandler) and x.name}
    # import cục bộ ngay trong hàm (vd `from datetime import date as _d`)
    for x in ast.walk(ham):
        if isinstance(x, (ast.Import, ast.ImportFrom)):
            gan_trong |= {(a.asname or a.name).split(".")[0] for a in x.names}

    dung = {x.id for x in ast.walk(ham) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}
    la = sorted(dung - gan_trong - ten_module - set(dir(__builtins__)) - set(dir(__import__("builtins"))))
    assert not la, f"Tên không rõ từ đâu trong _chi_tiet_don: {la}"
