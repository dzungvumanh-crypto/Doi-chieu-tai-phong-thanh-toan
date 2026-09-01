"""Chốt chặn hồi quy — mọi feature_code dùng ở require_feature()/require_any_feature()/
has_feature() phải có trong backend/core/features.py::FEATURES (review PR#69, khanhbq693,
mục C).

Vì sao cần: menu.cham_ilo1000 được dùng ở 6 nơi (5 endpoint backend/api/ilo1000.py +
frontend/pages/cham_ilo1000.py) nhưng KHÔNG có trong FEATURES — không hiện trên màn Phân
quyền chức năng, QTV không cấp được cho ai, cả module chỉ admin dùng được. Không lỗi,
không log, không test nào bắt được cho tới khi có người không phải admin báo cáo mất menu.

Quét bằng AST (đọc file, không import) — không cần chạy server. Bắt cả gọi dạng keyword
(`require_feature(feature_code='x')`), không chỉ positional (2026-09-01, review PR#68 vòng 3
mục C3, khanhbq693) — bộ quét gốc chỉ đọc `node.args`, bỏ sót `node.keywords`.

Không cần tự kiểm FEATURE_GROUPS (cây phân cấp) phủ kín FEATURES — `features.py` đã có sẵn
`_assert_feature_coverage()` chạy NGAY LÚC IMPORT module, raise chặn khởi động nếu lệch (mạnh
hơn 1 test riêng: lỗi lộ ra ngay cả khi ai đó quên chạy pytest).

Chạy: python -m pytest tests/test_feature_codes_declared.py -v
"""

import ast
from pathlib import Path

from backend.core.features import FEATURES

_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = [_ROOT / "backend", _ROOT / "frontend"]
_CALL_NAMES = {"require_feature", "require_any_feature", "has_feature"}


def _hang_so_str(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _ma_dung_khong_khai_bao(dirs: list[Path] | None = None) -> list[str]:
    thieu: list[str] = []
    for base in (dirs if dirs is not None else _SCAN_DIRS):
        for f in sorted(base.rglob("*.py")):
            src = f.read_text(encoding="utf-8")
            if not any(name in src for name in _CALL_NAMES):
                continue
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, ast.Call):
                    continue
                fname = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else None
                )
                if fname not in _CALL_NAMES:
                    continue
                # positional: require_feature('x', ...) / require_any_feature('a', 'b')
                # keyword:    require_feature(feature_code='x')
                gia_tri = [_hang_so_str(arg) for arg in node.args]
                gia_tri += [_hang_so_str(kw.value) for kw in node.keywords if kw.arg == "feature_code"]
                for code in gia_tri:
                    if code is not None and code not in FEATURES:
                        ten_hien = f.relative_to(_ROOT) if f.is_relative_to(_ROOT) else f
                        thieu.append(f"{ten_hien}:{node.lineno} → {fname}('{code}')")
    return thieu


def test_moi_feature_code_dung_deu_da_khai_bao_trong_FEATURES():
    thieu = _ma_dung_khong_khai_bao()
    assert not thieu, (
        "Feature code dùng ở require_feature()/require_any_feature()/has_feature() "
        "nhưng KHÔNG có trong backend/core/features.py::FEATURES — QTV không cấp được "
        "quyền này cho ai qua màn Phân quyền chức năng:\n  " + "\n  ".join(thieu)
    )


def test_bo_quet_that_su_bat_duoc_loi(tmp_path):
    """Chốt chặn cho chính bộ quét: nếu nó luôn trả rỗng thì test trên vô dụng."""
    fake_dir = tmp_path / "backend"
    fake_dir.mkdir()
    (fake_dir / "trang_gia.py").write_text(
        "from backend.core.deps import require_feature\n"
        "require_feature('menu.khong_ton_tai_bao_gio')\n",
        encoding="utf-8",
    )
    thieu = _ma_dung_khong_khai_bao([fake_dir])
    assert any("menu.khong_ton_tai_bao_gio" in t for t in thieu)


def test_bo_quet_bat_duoc_ca_dang_goi_keyword(tmp_path):
    """2026-09-01 — bộ quét gốc chỉ đọc `node.args`, bỏ sót gọi dạng
    `require_feature(feature_code='x')`."""
    fake_dir = tmp_path / "backend"
    fake_dir.mkdir()
    (fake_dir / "trang_gia_kw.py").write_text(
        "from backend.core.deps import require_feature\n"
        "require_feature(feature_code='menu.khong_ton_tai_dang_keyword')\n",
        encoding="utf-8",
    )
    thieu = _ma_dung_khong_khai_bao([fake_dir])
    assert any("menu.khong_ton_tai_dang_keyword" in t for t in thieu)
