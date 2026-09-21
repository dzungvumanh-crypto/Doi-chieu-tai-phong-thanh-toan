"""Canh: bọc coroutine trong create_task/ensure_future làm RỖNG ngăn xếp slot của NiceGUI.

Hậu quả là kiểu hỏng tệ nhất của dự án này: ui.notify / ui.navigate / ui.timer bên
trong coroutine ném RuntimeError, rơi vào handler ngoại lệ toàn cục — màn hình KHÔNG
đổi gì và cũng KHÔNG có thông báo lỗi nào. Xem mục "Event handler async" trong
docs/DESIGN.md.

Đo 21/09/2026 bằng chính nicegui.testing (dựng trang thật rồi bấm nút):

    on_click=f                              -> slot còn nguyên
    on_click=lambda: f(doi_so)              -> slot còn nguyên  (NiceGUI await kết quả lambda)
    on_click=lambda: ensure_future(f(...))  -> slot RỖNG, thao tác UI bị nuốt
    ui.timer(0, f, once=True)               -> slot còn nguyên  (khuôn nạp lần đầu)

Vì thế lưới này chỉ cấm khuôn nằm TRONG lambda — chỗ luôn có sẵn cách viết đúng là bỏ
lớp bọc đi. create_task nằm trong thân hàm thì còn có trường hợp chính đáng (việc nền
thật, không vẽ gì), nên chỉ giới hạn số lượng và bắt khai báo tường minh ở đây.
"""
import ast
from pathlib import Path

_GOC = Path(__file__).resolve().parent.parent / "frontend"

# `asyncio.create_task(...)` (Attribute) lẫn `create_task(...)` sau
# `from asyncio import create_task` (Name) — bắt cả hai, không thì đổi kiểu
# import là lách được lưới. `background_tasks.create` của chính NiceGUI cũng mở
# task rời y hệt nên tính luôn.
_BOC = {"create_task", "ensure_future", "create"}
_BOC_MODULE = {"asyncio", "background_tasks"}

# Chỗ còn lại được phép: việc nền thật, KHÔNG vẽ giao diện. Thêm vào đây là một
# quyết định có chủ ý — kèm lý do ngay tại dòng mã đó. So theo ĐƯỜNG DẪN tương
# đối, không theo tên file: so tên thì một `frontend/pages/shared.py` mới sau
# này tự được miễn mà không ai để ý.
_DUOC_PHEP = {"shared.py"}


def _la_loi_goi_boc(n: ast.AST) -> bool:
    if not isinstance(n, ast.Call):
        return False
    f = n.func
    if isinstance(f, ast.Attribute):
        # asyncio.create_task / background_tasks.create — chặn `create` trần của
        # đối tượng khác (vd. dialog.create) bằng cách soi tên module.
        if f.attr == "create":
            return isinstance(f.value, ast.Name) and f.value.id in _BOC_MODULE
        return f.attr in _BOC
    if isinstance(f, ast.Name):
        return f.id in {"create_task", "ensure_future"}
    return False


def _duyet(f: Path):
    """Trả về [(dòng, có_nằm_trong_lambda)] cho mọi create_task/ensure_future."""
    cay = ast.parse(f.read_text(encoding="utf-8"))
    cha = {}
    for n in ast.walk(cay):
        for c in ast.iter_child_nodes(n):
            cha[c] = n
    ra = []
    for n in ast.walk(cay):
        if _la_loi_goi_boc(n):
            ra.append((n.lineno, isinstance(cha.get(n), ast.Lambda)))
    return ra


def test_khong_boc_create_task_trong_lambda():
    loi = []
    for f in sorted(_GOC.rglob("*.py")):
        for dong, trong_lambda in _duyet(f):
            if trong_lambda:
                loi.append(
                    f"{f.relative_to(_GOC.parent)}:{dong} — bỏ lớp bọc đi, "
                    f"để NiceGUI tự await: lambda: ham(...)"
                )
    assert not loi, "\n".join(loi)


def test_create_task_trong_than_ham_chi_con_o_cho_da_khai():
    """Mọi chỗ nạp giao diện phải dùng ui.timer(..., once=True), không phải create_task."""
    thua = []
    for f in sorted(_GOC.rglob("*.py")):
        if str(f.relative_to(_GOC)).replace("\\", "/") in _DUOC_PHEP:
            continue
        for dong, trong_lambda in _duyet(f):
            if not trong_lambda:
                thua.append(f"{f.relative_to(_GOC.parent)}:{dong}")
    assert not thua, (
        "Nạp giao diện thì dùng ui.timer(0, ham, once=True); handler thì cho NiceGUI "
        "tự await (kể cả khuôn `lambda: [gán…, ensure_future(…)]` — lambda trả LIST "
        "nên không được await, phải tách thành `async def`). Nếu đây thật sự là việc "
        "nền không vẽ gì, thêm đường dẫn file vào _DUOC_PHEP và ghi lý do tại dòng mã:\n"
        + "\n".join(thua)
    )
