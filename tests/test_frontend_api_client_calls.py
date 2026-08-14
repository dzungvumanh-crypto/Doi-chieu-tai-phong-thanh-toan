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
