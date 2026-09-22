"""Màn Nhật ký hệ thống 4 tab — các bộ lọc và endpoint backend mới.

Chạy: python -m pytest tests/test_nhat_ky_de_dung.py -v
"""
import sqlite3
from datetime import timedelta

import pytest

from backend.database import _vn_now
from backend.services.audit_labels import MODULES, describe_target, describe_work


@pytest.fixture
def client(admin_client):
    from backend.database import get_db
    from backend.main import app

    homnay = _vn_now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT);
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT,
            target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT,
            created_at TIMESTAMP);
        CREATE TABLE login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, staff_id INTEGER,
            ip_address TEXT, success INTEGER, detail TEXT, created_at DATETIME);
        INSERT INTO user_tttt VALUES (1,'an','Nguyễn Văn An'),(2,'binh','Trần Thị Bình');
    """)
    conn.executemany(
        "INSERT INTO audit_logs (actor_id, action, target_type, detail, created_at) VALUES (?,?,?,?,?)",
        [
            (1, "PUT",    "/api/leaves/12/ksv-review", "HTTP 200",       f"{homnay} 08:00:00"),
            (1, "PATCH",  "/api/leaves/12/cancel",     "HTTP 200",       f"{homnay} 08:05:00"),
            (1, "PATCH",  "/api/leaves/120/cancel",    "HTTP 500",       f"{homnay} 08:06:00"),
            (2, "DELETE", "/api/bundles/8",            "HTTP 403",       f"{homnay} 09:00:00"),
            (2, "staff_create", "user_tttt",           "Tạo tài khoản",  f"{homnay} 09:30:00"),
            # Dòng ghi tay qua audit_queue (token Extension sai) — không có "HTTP" → thất bại
            (None, "POST", "/api/doi-chieu-citad/citad-buffer", "Thất bại: mã sai", f"{homnay} 10:00:00"),
            (1, "POST",   "/api/leaves/",              "HTTP 200",       "2026-01-01 08:00:00"),
        ],
    )
    # Sai mật khẩu: staff_id rỗng (auth.py chưa xác thực được là ai)
    sai = [("binh", None, "10.0.0.9", 0, f"{homnay} 07:0{i}:00") for i in range(5)]
    conn.executemany(
        "INSERT INTO login_logs (username, staff_id, ip_address, success, created_at) VALUES (?,?,?,?,?)",
        sai + [("an", 1, "10.0.0.1", 1, f"{homnay} 07:50:00"),
               ("an", None, "10.0.0.1", 0, f"{homnay} 07:49:00"),
               # Mật khẩu ĐÚNG nhưng bị chặn vì đang mở ở máy khác — có staff_id
               *[("an", 1, "10.0.0.1", 0, f"{homnay} 07:4{i}:00") for i in range(5)],
               ("an", 1, "10.0.0.1", 1, "2026-01-01 07:00:00")],
    )
    conn.commit()
    app.dependency_overrides[get_db] = lambda: conn
    yield admin_client
    conn.close()


def _audit(client, **params):
    r = client.get("/api/admin/logs/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ── Tab Thao tác ──
def test_loc_that_bai_khop_cach_man_hinh_to_mau(client):
    """Lọc SQL và màu trên bảng (result_ok) phải cùng một quy tắc — lệch là bấm
    "Thất bại" ra dòng tô xanh, hoặc sót dòng tô cam."""
    loi = _audit(client, ket_qua="loi")
    assert loi["total"] == 3                    # 500, 403, và dòng ghi tay không có mã HTTP
    assert all(not e["result_ok"] for e in loi["entries"])
    # Dòng không có mã HTTP: ô Kết quả ngắn gọn, câu mô tả nằm ở Chi tiết
    ghi_tay = [e for e in loi["entries"] if e["action"] == "POST"][0]
    assert ghi_tay["result"] == "Thất bại" and ghi_tay["detail"] == "Thất bại: mã sai"
    ok = _audit(client, ket_qua="ok")
    assert ok["total"] == 4                     # gồm cả dòng ngữ nghĩa staff_create
    assert all(e["result_ok"] for e in ok["entries"])


def test_nut_sua_gom_ca_put_va_patch(client):
    assert _audit(client, method="PUT")["total"] == 3


def test_lich_su_ho_so_khong_dinh_ma_dai_hon(client):
    """'/api/leaves/12' không được kéo theo đơn 120."""
    d = _audit(client, doi_tuong="/api/leaves/12")
    assert d["total"] == 2
    assert {e["target_type"] for e in d["entries"]} == {"/api/leaves/12/ksv-review", "/api/leaves/12/cancel"}


def test_moi_dong_co_nhan_ho_so_bam_duoc(client):
    e = _audit(client, doi_tuong="/api/leaves/12")["entries"][0]
    assert e["doi_tuong"] == {"nhan": "nghỉ phép #12", "khoa": "/api/leaves/12"}
    assert e["actor_id"] == 1


def test_describe_target():
    assert describe_target("/api/handovers/entries/55/confirm-received") == {
        "nhan": "bàn giao chứng từ #55", "khoa": "/api/handovers/entries/55"}
    assert describe_target("/api/leaves/") is None          # không có mã hồ sơ
    assert describe_target("user_tttt") is None             # dòng ngữ nghĩa
    assert describe_target("/api/la/9") is None             # module lạ — không đoán


def test_thao_tac_lan_can_cung_nguoi_trong_10_phut(client):
    goc = _audit(client, doi_tuong="/api/leaves/12", method="PATCH")["entries"][0]
    r = client.get(f"/api/admin/logs/audit/{goc['id']}/lan-can")
    assert r.status_code == 200, r.text
    ds = r.json()["entries"]
    # 08:00 và 08:06 của cùng người; không có dòng của người khác, không có chính nó
    assert [e["created_at"][11:16] for e in ds] == ["08:00", "08:06"]


def test_moi_route_ghi_du_lieu_deu_co_nhan_module():
    """Route mới chưa khai trong MODULES thì màn hình hiện đường dẫn thô
    ("Thực hiện /api/…") và ô "Chức năng" không lọc được nó."""
    from backend.core.audit_middleware import bo_qua
    from backend.main import app
    prefixes = [p for p, _ in MODULES]
    thieu = sorted({
        r.path for r in app.routes
        for m in (getattr(r, "methods", None) or set()) & {"POST", "PUT", "PATCH", "DELETE"}
        if not bo_qua(m, r.path) and not any(r.path.startswith(p) for p in prefixes)
    })
    assert not thieu, f"Thêm tiền tố vào MODULES (backend/services/audit_labels.py): {thieu}"


def test_nostro_khong_bi_nhan_nham_la_citad_cuoi_ngay():
    assert "PaymentHub" in describe_work("POST", "/api/doi-chieu-citad-nostro/session")


# ── Tab Đăng nhập ──
def _logins(client, **params):
    r = client.get("/api/admin/logs/logins", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_dang_nhap_tim_theo_ten_va_ip(client):
    assert _logins(client, q="Bình")["total"] == 5
    assert _logins(client, q="10.0.0.1")["total"] == 8
    homnay = _vn_now().strftime("%Y-%m-%d")
    assert _logins(client, tu_ngay=homnay)["total"] == 12


def test_nghi_do_mat_khau_tu_nguong_khoa_tai_khoan(client):
    ds = _logins(client, success="false")["entries"]
    binh = [e for e in ds if e["username"] == "binh"]
    an = [e for e in ds if e["username"] == "an"]
    assert all(e["nghi_van"] and e["so_sai_ngay"] == 5 for e in binh)
    # "an" thất bại 6 lần nhưng 5 lần là bị chặn vì đang mở ở máy khác (mật khẩu đúng) —
    # chỉ 1 lần sai mật khẩu thật, không được tô "nghi dò mật khẩu"
    assert len(an) == 6
    assert not any(e["nghi_van"] for e in an) and all(e["so_sai_ngay"] == 1 for e in an)
    assert _logins(client, q="an", success="true")["entries"][0]["staff_id"] == 1


# ── Tab Tổng quan ──
def test_tong_quan_dem_va_chi_ra_cho_can_chu_y(client):
    r = client.get("/api/admin/logs/tong-quan", params={"so_ngay": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["so"]["thao_tac"] == 6 and d["so"]["that_bai"] == 3
    assert d["so"]["dang_nhap"] == 1 and d["so"]["dang_nhap_sai"] == 11
    chu_y = d["chu_y"]
    # Tài khoản bị dò mật khẩu đứng đầu, kèm bộ lọc mở đúng danh sách
    assert chu_y[0]["tab"] == "dang-nhap" and chu_y[0]["loc"]["q"] == "binh"
    assert not any(m["tab"] == "dang-nhap" and m["loc"]["q"] == "an" for m in chu_y)
    # Lỗi 500 xếp trước lỗi 403
    thao_tac = [m for m in chu_y if m["tab"] == "thao-tac"]
    assert thao_tac[0]["muc"] == "loi" and "lỗi hệ thống" in thao_tac[0]["noi_dung"]
    assert thao_tac[0]["loc"] == {"ket_qua": "loi", "tu_ngay": d["tu_ngay"],
                                  "actor_id": 1, "module": "/api/leaves"}


def test_tong_quan_7_ngay_lui_moc(client):
    d = client.get("/api/admin/logs/tong-quan", params={"so_ngay": 7}).json()
    assert d["tu_ngay"] == (_vn_now() - timedelta(days=6)).strftime("%Y-%m-%d")


# ── Tab Lỗi hệ thống ──
def test_nhat_ky_loi_tim_chu_va_loc_ngay(tmp_path, monkeypatch):
    from backend.api import logs
    p = tmp_path / "app.log"
    p.write_text(
        "2026-09-20 08:00:00 ERROR    backend.api.leaves — Hỏng đơn 12\n"
        "Traceback dòng 1\n"
        "2026-09-21 09:00:00 WARNING  slow.request — Request chậm\n"
        "2026-09-22 10:00:00 ERROR    backend.api.bundles — Hỏng tập 8\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(logs, "_LOG_PATH", str(p))
    ds, n = logs._parse_log_file(q="hỏng")
    assert n == 2 and ds[1]["msg"] == "Hỏng đơn 12\nTraceback dòng 1"
    assert logs._parse_log_file(q="bundles")[1] == 1                 # tìm cả theo nguồn
    assert logs._parse_log_file(tu_ngay="2026-09-21")[1] == 2
    assert logs._parse_log_file(den_ngay="2026-09-21")[1] == 2        # trọn ngày 21
    assert logs._parse_log_file("ERROR", tu_ngay="2026-09-21")[1] == 1
