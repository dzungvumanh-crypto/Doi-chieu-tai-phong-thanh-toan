"""Không route nào được nhận đường dẫn thư mục/file trên máy chủ từ client.

Quyết định của dự án (docs/CHECKLIST-TRUOC-KHI-MO-PR.md mục A): chỉ tải file lên, bỏ hẳn
chế độ "chọn thư mục máy chủ". Chế độ này đã quay lại qua 7 PR (#3, #8, #19, #43, #63, #68,
#70) — thường do chép mã cũ từ nhánh khác sang — và bị gỡ theo từng module: ACH 13/08/2026,
Song phương + ILO1000 02/09/2026, Chấm 459901 17/09/2026. Canh từng module thì module mới
thêm sau không ai canh, nên test này quét TOÀN BỘ route qua OpenAPI.

Dính test này mà thật sự cần một tham số tên như vậy (không phải đường dẫn trên máy chủ)
thì đổi tên tham số, đừng nới danh sách — tên chứa "path"/"folder" chính là thứ người rà
PR dùng để nhận ra lỗ này.
"""
import re

from backend.main import app

_TEN_NGHI = re.compile(r"folder|thu_muc|duong_dan|dir|path", re.I)
_DUONG_NGHI = re.compile(r"folder|/api/fs\b|browse", re.I)


def _schema():
    return app.openapi()


def test_khong_route_nao_nhan_tham_so_giong_duong_dan():
    s = _schema()
    thay = []
    for duong, ops in s["paths"].items():
        for method, op in ops.items():
            for p in op.get("parameters", []):
                if _TEN_NGHI.search(p["name"]):
                    thay.append(f"{method.upper()} {duong} — tham số '{p['name']}'")
    for ten_schema, sc in s.get("components", {}).get("schemas", {}).items():
        for prop in (sc.get("properties") or {}):
            if _TEN_NGHI.search(prop):
                thay.append(f"schema {ten_schema} — trường '{prop}'")
    assert not thay, (
        "Route nhận tham số trông như đường dẫn trên máy chủ — chế độ 'chọn thư mục máy "
        "chủ' đã bị bỏ hẳn, chỉ nhận tải file lên:\n  " + "\n  ".join(sorted(thay))
    )


def test_khong_route_duyet_thu_muc():
    s = _schema()
    thay = [d for d in s["paths"] if _DUONG_NGHI.search(d)]
    assert not thay, f"Route duyệt/chạy từ thư mục máy chủ quay lại: {thay}"
