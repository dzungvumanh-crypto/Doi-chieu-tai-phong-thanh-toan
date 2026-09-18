"""Canh: gọi hàm async của shared.py mà quên await → coroutine bị vứt, không vẽ gì, không lỗi."""
import ast
from pathlib import Path

_GOC = Path(__file__).resolve().parent.parent / "frontend"


def _ham_async_cua_shared() -> set[str]:
    cay = ast.parse((_GOC / "shared.py").read_text(encoding="utf-8"))
    return {n.name for n in cay.body if isinstance(n, ast.AsyncFunctionDef)}


def test_ham_async_cua_shared_luon_duoc_await():
    ten_async = _ham_async_cua_shared()
    assert "_sidebar" in ten_async

    loi = []
    for f in sorted((_GOC / "pages").rglob("*.py")):
        cay = ast.parse(f.read_text(encoding="utf-8"))
        da_await = {id(n.value) for n in ast.walk(cay) if isinstance(n, ast.Await)}
        for n in ast.walk(cay):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id in ten_async and id(n) not in da_await):
                loi.append(f"{f.relative_to(_GOC.parent)}:{n.lineno} {n.func.id}() thiếu await")

    assert not loi, "\n".join(loi)
