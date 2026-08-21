"""Canh cho mọi lời gọi `api.<tên>` trong frontend đều trỏ tới hàm CÓ THẬT trong
`frontend/api_client.py`.

Vì sao cần: 13/08/2026 phát hiện `frontend/pages/cham_ach.py` gọi
`api.post_multipart(...)` — hàm chưa bao giờ tồn tại. Lời gọi nằm trong `try:` nên
AttributeError bị nuốt và hiện ra như lỗi mạng, khiến nút "Chạy đối chiếu" của
module ACH chết hoàn toàn mà test không hề báo: toàn bộ test ACH gọi thẳng backend
qua `admin_client`, không đi qua tầng api_client.

Quét bằng AST (đọc file, không import) — không cần nicegui, không cần chạy server.

Chạy: python -m pytest tests/test_frontend_api_client_calls.py -v
"""

import ast
import re
from pathlib import Path

_ROOT       = Path(__file__).resolve().parent.parent
_API_CLIENT = _ROOT / 'frontend' / 'api_client.py'
_FRONTEND   = _ROOT / 'frontend'

_IMPORT_ALIAS_RE = re.compile(
    r'(?:import\s+frontend\.api_client\s+as\s+(\w+)'
    r'|from\s+frontend\s+import\s+api_client\s+as\s+(\w+))'
)


def _ten_public_cua_api_client() -> set[str]:
    """Tên top-level định nghĩa trong api_client.py: hàm, class, biến, import."""
    tree = ast.parse(_API_CLIENT.read_text(encoding='utf-8'))
    ten = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ten.add(node.name)
        elif isinstance(node, ast.Assign):
            ten.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            ten.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            ten.update(a.asname or a.name.split('.')[0] for a in node.names)
    return ten


def _cac_loi_goi_thieu(thu_muc: Path = None) -> list[str]:
    co_san = _ten_public_cua_api_client()
    thieu  = []

    for f in sorted((thu_muc or _FRONTEND).rglob('*.py')):
        if f == _API_CLIENT:
            continue
        src = f.read_text(encoding='utf-8')
        if 'api_client' not in src:
            continue

        m     = _IMPORT_ALIAS_RE.search(src)
        alias = (m.group(1) or m.group(2)) if m else 'api'

        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == alias
                    and not node.attr.startswith('__')
                    and node.attr not in co_san):
                ten_hien = f.relative_to(_ROOT) if f.is_relative_to(_ROOT) else f
                thieu.append(f'{ten_hien}:{node.lineno} → api.{node.attr}')
    return thieu


def test_khong_co_loi_goi_api_client_khong_ton_tai():
    thieu = _cac_loi_goi_thieu()
    assert not thieu, (
        'Frontend gọi hàm không tồn tại trong frontend/api_client.py:\n  '
        + '\n  '.join(thieu)
    )


def test_bo_quet_that_su_bat_duoc_loi(tmp_path):
    """Chốt chặn cho chính bộ quét: nếu nó luôn trả rỗng thì test trên vô dụng."""
    gia = tmp_path / 'frontend'
    gia.mkdir()
    (gia / 'trang_gia.py').write_text(
        'import frontend.api_client as api\n'
        'def f():\n'
        '    return api.ham_khong_ton_tai_bao_gio("/x")\n',
        encoding='utf-8',
    )

    thieu = _cac_loi_goi_thieu(gia)
    assert any('ham_khong_ton_tai_bao_gio' in t for t in thieu)


# ── Tên tham số, không chỉ tên hàm ────────────────────────────────────────────
# Bộ quét trên chỉ chắc hàm CÓ THẬT. Gọi đúng tên nhưng sai tên tham số
# (`api.get(..., timeout=30)` khi `get()` không nhận `timeout`) vẫn ném TypeError
# lúc chạy, lại rơi vào đúng cái bẫy cũ: lời gọi nằm trong `try:` nên lỗi hiện ra
# như lỗi mạng. Nhiều lời gọi đi qua `asyncio.to_thread(api.get, ..., timeout=...)`
# nên tham số được truyền dưới dạng kwargs, càng không có gì kiểm ở thời điểm viết.

def _tham_so_cua_api_client() -> dict:
    """{tên hàm: (bộ tên tham số, có **kwargs hay không)}"""
    tree = ast.parse(_API_CLIENT.read_text(encoding='utf-8'))
    ket_qua = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = node.args
        ten = {p.arg for p in (a.posonlyargs + a.args + a.kwonlyargs)}
        ket_qua[node.name] = (ten, a.kwarg is not None)
    return ket_qua


def _cac_kwarg_sai(thu_muc: Path = None) -> list[str]:
    chu_ky = _tham_so_cua_api_client()
    sai    = []

    for f in sorted((thu_muc or _FRONTEND).rglob('*.py')):
        if f == _API_CLIENT:
            continue
        src = f.read_text(encoding='utf-8')
        if 'api_client' not in src:
            continue

        m     = _IMPORT_ALIAS_RE.search(src)
        alias = (m.group(1) or m.group(2)) if m else 'api'

        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue

            # api.get(...) trực tiếp, hoặc asyncio.to_thread(api.get, ..., kw=...)
            ham = node.func
            kwargs_cua_loi_goi = node.keywords
            if not (isinstance(ham, ast.Attribute)
                    and isinstance(ham.value, ast.Name) and ham.value.id == alias):
                if (isinstance(ham, ast.Attribute) and ham.attr == 'to_thread'
                        and node.args
                        and isinstance(node.args[0], ast.Attribute)
                        and isinstance(node.args[0].value, ast.Name)
                        and node.args[0].value.id == alias):
                    ham = node.args[0]
                else:
                    continue

            chu_ky_ham = chu_ky.get(ham.attr)
            if chu_ky_ham is None:
                continue    # test ở trên lo phần hàm không tồn tại
            ten_tham_so, co_kwargs = chu_ky_ham
            if co_kwargs:
                continue

            for kw in kwargs_cua_loi_goi:
                if kw.arg is None:          # **something — không suy ra được
                    continue
                if kw.arg not in ten_tham_so:
                    ten_hien = f.relative_to(_ROOT) if f.is_relative_to(_ROOT) else f
                    sai.append(f'{ten_hien}:{node.lineno} → api.{ham.attr}(..., {kw.arg}=)')
    return sai


def test_khong_truyen_tham_so_khong_ton_tai():
    sai = _cac_kwarg_sai()
    assert not sai, (
        'Frontend truyền tham số không có trong chữ ký hàm của api_client:\n  '
        + '\n  '.join(sai)
    )


def test_bo_quet_kwarg_that_su_bat_duoc_loi(tmp_path):
    gia = tmp_path / 'frontend'
    gia.mkdir()
    (gia / 'trang_gia.py').write_text(
        'import asyncio\n'
        'import frontend.api_client as api\n'
        'async def f():\n'
        '    api.get("/x", tham_so_bia_dat=1)\n'
        '    await asyncio.to_thread(api.post, "/y", tham_so_bia_dat_2=2)\n',
        encoding='utf-8',
    )

    sai = _cac_kwarg_sai(gia)
    assert any('tham_so_bia_dat=' in s for s in sai), sai
    assert any('tham_so_bia_dat_2=' in s for s in sai), sai
