"""Nhật ký hệ thống — tóm tắt nội dung request, cắt tiền tố HTTP, bộ lọc.

Ba nhóm test tương ứng ba việc: ghi được "đã sửa gì", hiện đúng ở cột Chi tiết,
và lọc được theo ngày / người / module.
"""
import json

import pytest

from backend.core import audit_body
from backend.services.audit_labels import describe_detail, describe_result, MODULES


# ── audit_body.nen_doc_body ──────────────────────────────────────────────────
class _H(dict):
    """Header giả — httpx/starlette tra bằng key thường."""
    def get(self, k, default=None):
        return super().get(k.lower(), default)


@pytest.mark.parametrize("headers, mong_doi", [
    ({"content-type": "application/json", "content-length": "50"}, True),
    ({"content-type": "application/json; charset=utf-8", "content-length": "50"}, True),
    ({"content-type": "multipart/form-data", "content-length": "50"}, False),
    ({"content-type": "application/json", "content-length": "0"}, False),
    ({"content-type": "application/json"}, False),                       # chunked
    ({"content-type": "application/json", "content-length": "999999"}, False),
    ({}, False),
])
def test_chi_doc_body_json_nho(headers, mong_doi):
    assert audit_body.nen_doc_body(_H(headers)) is mong_doi


# ── audit_body.tom_tat ───────────────────────────────────────────────────────
def test_tom_tat_body_va_query():
    s = audit_body.tom_tat("thang=9", json.dumps({"ten": "Tập 1", "so_to": 12}).encode())
    assert "?thang=9" in s
    assert "ten=Tập 1" in s and "so_to=12" in s


@pytest.mark.parametrize("khoa", [
    "password", "new_password", "token", "api_key", "signature_image",
    "chu_ky_base64", "password_hash",
])
def test_che_khoa_nhay_cam(khoa):
    s = audit_body.tom_tat("", json.dumps({khoa: "bi-mat-that"}).encode())
    assert "bi-mat-that" not in s
    assert f"{khoa}=***" in s


def test_che_khoa_nhay_cam_trong_query():
    assert "abc" not in audit_body.tom_tat("token=abc", None)


def test_cat_gia_tri_dai_va_ca_chuoi():
    dai = "x" * 5000
    s = audit_body.tom_tat("", json.dumps({"ghi_chu": dai}).encode())
    assert len(s) <= audit_body.MAX_DETAIL + 1     # +1 cho dấu "…"


def test_body_khong_phai_json_khong_lam_hong():
    assert audit_body.tom_tat("", b"<html>khong phai json</html>") == ""
    assert audit_body.tom_tat("", None) == ""
    assert audit_body.tom_tat("", b"") == ""


def test_danh_sach_va_dict_long_nhau():
    s = audit_body.tom_tat("", json.dumps({
        "ngay": ["01/09", "02/09"],
        "meta": {"a": 1, "password": "x"},
        "muc": [{"i": 1}, {"i": 2}, {"i": 3}],
    }).encode())
    assert "ngay=[01/09, 02/09]" in s
    assert "meta={a=1, password=***}" in s
    assert "muc=[3 mục]" in s


# ── audit_labels.describe_detail ─────────────────────────────────────────────
def test_cat_tien_to_http():
    assert describe_detail("HTTP 200") == ""                      # dòng cũ
    assert describe_detail("HTTP 200 · ten=Tập 1") == "ten=Tập 1"  # dòng mới
    # Dòng ngữ nghĩa do write_audit ghi giữ nguyên
    assert describe_detail("Xoá ô chứng từ đã xác nhận") == "Xoá ô chứng từ đã xác nhận"


def test_ket_qua_van_doc_duoc_ma_khi_co_tom_tat():
    assert describe_result("HTTP 403 · ten=abc", "POST") == "Không đủ quyền"
    assert describe_result("HTTP 200 · ten=abc", "POST") == "Thành công"


def test_modules_co_prefix_hop_le():
    assert MODULES, "danh sách module cho bộ lọc không được rỗng"
    for prefix, label in MODULES:
        assert prefix.startswith("/api/")
        assert label


# ── Middleware: đọc body rồi vẫn phải trả nguyên vẹn cho route ───────────────
def _app_thu(monkeypatch):
    """App tối giản gắn AuditMiddleware, thu lại mọi lượt enqueue."""
    from fastapi import FastAPI
    from backend.core import audit_queue
    from backend.core.audit_middleware import AuditMiddleware

    da_ghi = []
    monkeypatch.setattr(audit_queue, "enqueue",
                        lambda *a, **kw: da_ghi.append((a, kw)))

    app = FastAPI()
    app.add_middleware(AuditMiddleware)

    @app.post("/api/bundles/generate")
    async def _tao(payload: dict):
        return {"da_nhan": payload}

    return app, da_ghi


def test_route_van_doc_duoc_body_sau_khi_middleware_doc(monkeypatch):
    """Hàng rào quan trọng nhất: đọc body trong middleware KHÔNG được làm
    route đói dữ liệu. Hỏng chỗ này là mọi POST của hệ thống treo."""
    from fastapi.testclient import TestClient

    app, da_ghi = _app_thu(monkeypatch)
    body = {"ten": "Tập 1", "so_to": 12, "password": "bi-mat"}
    r = TestClient(app).post("/api/bundles/generate?thang=9", json=body)

    assert r.status_code == 200
    assert r.json()["da_nhan"] == body          # route nhận đủ, không mất byte nào

    assert len(da_ghi) == 1
    noi_dung = da_ghi[0][1]["noi_dung"]
    assert "ten=Tập 1" in noi_dung and "so_to=12" in noi_dung
    assert "?thang=9" in noi_dung
    assert "bi-mat" not in noi_dung             # mật khẩu không lọt vào nhật ký


def test_luong_ghi_nen_ghep_ma_http_voi_tom_tat(tmp_path, monkeypatch):
    """Đi hết đường ghi thật: enqueue → luồng nền → dòng trong audit_logs."""
    import sqlite3
    from backend.core import audit_queue

    db_path = str(tmp_path / "audit.db")
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
        target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT,
        created_at TIMESTAMP)""")
    con.commit(); con.close()
    monkeypatch.setattr(audit_queue, "DB_PATH", db_path)

    # Hàng đợi là biến toàn cục sống suốt phiên pytest: mọi request của test
    # khác đi qua AuditMiddleware đều nằm lại đó (không có luồng nền nào chạy
    # để dọn). Không xả trước thì chúng chảy vào DB tạm này.
    while not audit_queue._q.empty():
        audit_queue._q.get()
        audit_queue._q.task_done()

    audit_queue.start()
    try:
        audit_queue.enqueue("PUT", "/api/bundles/7", 200, "", "10.0.0.9", "127.0.0.1",
                            actor_id=1, noi_dung="ten=Tập 1")
        # detail tường minh (write_audit ngữ nghĩa) thì noi_dung bị bỏ qua
        audit_queue.enqueue("POST", "/api/x", 200, "", "10.0.0.9", "127.0.0.1",
                            actor_id=1, detail="Xoá ô chứng từ", noi_dung="bo=qua")
        audit_queue._q.join()
    finally:
        audit_queue.stop()

    con = sqlite3.connect(db_path)
    rows = [r[0] for r in con.execute("SELECT detail FROM audit_logs ORDER BY id")]
    con.close()
    assert rows == ["HTTP 200 · ten=Tập 1", "Xoá ô chứng từ"]


# ── API: bộ lọc ngày / người / module ────────────────────────────────────────
@pytest.fixture
def client_nhat_ky(admin_client):
    """admin_client + DB tạm có sẵn 4 dòng nhật ký để lọc."""
    import sqlite3
    from backend.database import get_db
    from backend.main import app

    # check_same_thread=False: FastAPI chạy endpoint sync trong threadpool
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT);
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
            target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT,
            created_at TIMESTAMP);
        INSERT INTO user_tttt VALUES (1,'an','Nguyễn Văn An'),(2,'binh','Trần Thị Bình');
    """)
    conn.executemany(
        "INSERT INTO audit_logs (actor_id, action, target_type, detail, ip_address, created_at)"
        " VALUES (?,?,?,?,?,?)",
        [
            (1, "POST",   "/api/leaves/",   "HTTP 200 · ly_do=Việc riêng", "10.0.0.1", "2026-09-01 08:00:00"),
            (2, "PUT",    "/api/bundles/7", "HTTP 200 · ten=Tập 1",        "10.0.0.2", "2026-09-02 09:00:00"),
            (1, "DELETE", "/api/bundles/8", "HTTP 403",                    "10.0.0.1", "2026-09-03 23:59:00"),
            (2, "POST",   "/api/duty/x",    "HTTP 200",                    "10.0.0.2", "2026-09-05 10:00:00"),
        ],
    )
    conn.commit()
    app.dependency_overrides[get_db] = lambda: conn
    yield admin_client
    conn.close()


def _tong(client, **params):
    r = client.get("/api/admin/logs/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_loc_theo_khoang_ngay(client_nhat_ky):
    assert _tong(client_nhat_ky)["total"] == 4
    # Ngày "đến" phải lấy trọn cả ngày, kể cả dòng 23:59
    assert _tong(client_nhat_ky, tu_ngay="2026-09-01", den_ngay="2026-09-03")["total"] == 3
    assert _tong(client_nhat_ky, tu_ngay="2026-09-05")["total"] == 1
    # Định dạng sai → bỏ qua bộ lọc chứ không lỗi, không trả bảng rỗng
    assert _tong(client_nhat_ky, tu_ngay="01/09/2026")["total"] == 4


def test_loc_theo_nguoi_va_module(client_nhat_ky):
    assert _tong(client_nhat_ky, actor_id=1)["total"] == 2
    assert _tong(client_nhat_ky, module="/api/bundles")["total"] == 2
    assert _tong(client_nhat_ky, actor_id=1, module="/api/bundles")["total"] == 1


def test_tim_chu_lan_ca_trong_noi_dung(client_nhat_ky):
    """Nội dung mới ghi được thì ô tìm phải với tới — không thì ghi làm gì."""
    assert _tong(client_nhat_ky, q="Việc riêng")["total"] == 1


def test_entry_du_truong_cho_hop_thoai_chi_tiet(client_nhat_ky):
    e = _tong(client_nhat_ky, actor_id=2, module="/api/bundles")["entries"][0]
    assert e["work"] == "Sửa tập chứng từ"
    assert e["detail"] == "ten=Tập 1"          # đã cắt tiền tố HTTP
    assert e["raw_detail"] == "HTTP 200 · ten=Tập 1"
    assert e["action"] == "PUT"
    assert e["full_name"] == "Trần Thị Bình"


def test_endpoint_bo_loc_liet_ke_nguoi_va_module(client_nhat_ky):
    r = client_nhat_ky.get("/api/admin/logs/audit/filters")
    assert r.status_code == 200, r.text
    data = r.json()
    assert [a["label"] for a in data["actors"]] == ["Nguyễn Văn An (2)", "Trần Thị Bình (2)"]
    assert any(m["prefix"] == "/api/bundles" for m in data["modules"])
