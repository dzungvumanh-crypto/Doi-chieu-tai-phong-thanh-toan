"""Không route nào được nhận đường dẫn thư mục/file trên máy chủ từ client.

Quyết định của dự án (docs/CHECKLIST-TRUOC-KHI-MO-PR.md mục A): chỉ tải file lên, bỏ hẳn
chế độ "chọn thư mục máy chủ". Chế độ này đã quay lại qua 7 PR (#3, #8, #19, #43, #63, #68,
#70) — thường do chép mã cũ từ nhánh khác sang — và bị gỡ theo từng module: ACH 13/08/2026,
Song phương + ILO1000 02/09/2026, Chấm 459901 17/09/2026. Canh từng module thì module mới
thêm sau không ai canh, nên test này quét TOÀN BỘ route.

Dây báo động theo TÊN, không phải chứng minh: tham số tên `src`/`nguon` mà vẫn là đường dẫn
thì lọt. Dính test mà tham số thật sự không phải đường dẫn trên máy chủ thì đổi tên tham số,
đừng nới luật — tên chứa "path"/"folder" chính là thứ người rà PR dùng để nhận ra lỗ này.
"""
import re
from pathlib import Path

from backend.main import app

_TU_NGHI = {"folder", "folders", "dir", "dirs", "directory", "path", "paths"}
_CUM_NGHI = ("thu_muc", "duong_dan")
_DUONG_NGHI = re.compile(r"folder|/api/fs\b|browse", re.I)


def _ten_nghi(ten: str) -> bool:
    # Tách theo từ (snake_case + camelCase): `folder_path`, `zipPath` dính; `direction`, `xpath` không.
    tu = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", ten).lower().split("_")
    return bool(_TU_NGHI.intersection(tu)) or any(c in ten.lower() for c in _CUM_NGHI)


def _schema_dau_vao(s: dict) -> set[str]:
    """Tên schema dùng làm THÂN REQUEST (theo $ref, kể cả lồng nhau) — không quét schema trả về."""
    comps = s.get("components", {}).get("schemas", {})
    thay: set[str] = set()

    def _di(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref:
                ten = ref.rsplit("/", 1)[-1]
                if ten not in thay:
                    thay.add(ten)
                    _di(comps.get(ten, {}))
            for v in node.values():
                _di(v)
        elif isinstance(node, list):
            for v in node:
                _di(v)

    for ops in s["paths"].values():
        for op in ops.values():
            _di(op.get("requestBody", {}))
    return thay


def test_khong_route_nao_nhan_tham_so_giong_duong_dan():
    s = app.openapi()
    comps = s.get("components", {}).get("schemas", {})
    thay = []
    for duong, ops in s["paths"].items():
        for method, op in ops.items():
            for p in op.get("parameters", []):
                if _ten_nghi(p["name"]):
                    thay.append(f"{method.upper()} {duong} — tham số '{p['name']}'")
    for ten_schema in _schema_dau_vao(s):
        for prop in (comps.get(ten_schema, {}).get("properties") or {}):
            if _ten_nghi(prop):
                thay.append(f"body {ten_schema} — trường '{prop}'")
    assert not thay, (
        "Route nhận tham số trông như đường dẫn trên máy chủ — chế độ 'chọn thư mục máy "
        "chủ' đã bị bỏ hẳn, chỉ nhận tải file lên:\n  " + "\n  ".join(sorted(thay))
    )


def test_body_dict_khong_doc_khoa_giong_duong_dan():
    """Route khai `body: dict` không có schema nên OpenAPI không liệt kê tên trường —
    quét thẳng mã nguồn các khoá đọc từ `body[...]` / `body.get(...)`."""
    goc = Path(__file__).resolve().parent.parent / "backend" / "api"
    mau = re.compile(r"""\bbody(?:\.get\(|\[)\s*["']([^"']+)["']""")
    thay = [
        f"{f.name}: body['{k}']"
        for f in sorted(goc.rglob("*.py"))
        for k in mau.findall(f.read_text(encoding="utf-8"))
        if _ten_nghi(k)
    ]
    assert not thay, f"Route đọc khoá trông như đường dẫn máy chủ từ body dict: {thay}"


def test_khong_route_duyet_thu_muc():
    thay = [d for d in app.openapi()["paths"] if _DUONG_NGHI.search(d)]
    assert not thay, f"Route duyệt/chạy từ thư mục máy chủ quay lại: {thay}"


def test_ten_nghi_theo_tu_khong_theo_chuoi_con():
    for ten in ("folder_path", "zipPath", "input_dir", "thu_muc_goc", "duong_dan"):
        assert _ten_nghi(ten), ten
    for ten in ("direction", "redirect_url", "xpath", "filename", "files", "storage_location"):
        assert not _ten_nghi(ten), ten
