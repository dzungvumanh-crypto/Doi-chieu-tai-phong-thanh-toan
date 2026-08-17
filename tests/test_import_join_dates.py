"""Test nhập hàng loạt Ngày vào ngành từ Excel (POST /api/staff/import-join-dates).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_import_join_dates.py -v
"""

import io
import sqlite3
from datetime import date

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_URL = "/api/staff/import-join-dates"
_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows, header=("STT", "Họ và tên", "Mã cán bộ", "Ngày vào ngành", "Phòng")) -> bytes:
    """Dựng file giống MA CB.xlsx: 1 dòng trống ở trên, xen dòng tiêu đề nhóm phòng."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([])
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE user_tttt (
               id INTEGER PRIMARY KEY, employee_code TEXT, full_name TEXT,
               join_industry_date DATE, is_deleted INTEGER DEFAULT 0);
           CREATE TABLE audit_logs (
               id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
               target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT,
               created_at DATETIME);
           INSERT INTO user_tttt (id, employee_code, full_name, join_industry_date) VALUES
               (1, '200733664', 'Nguyễn Quốc Hùng', NULL),
               (2, '201101780', 'Đào Tiến Thành', NULL),
               (3, '200739320', 'Nguyễn Thị Hiền', '2008-01-15');
           INSERT INTO user_tttt (id, employee_code, full_name, is_deleted) VALUES
               (4, '999999999', 'Đã xoá', 1);"""
    )
    conn.commit()

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 1, "role": StaffRole.ADMIN, "username": "admin", "full_name": "Admin",
    }
    app.dependency_overrides[get_db] = lambda: (yield conn)
    c = TestClient(app)
    c.conn = conn
    yield c
    app.dependency_overrides.clear()


def _ngay(c, code):
    return c.conn.execute(
        "SELECT join_industry_date FROM user_tttt WHERE employee_code = ?", (code,)
    ).fetchone()[0]


def _post(c, content, qs=""):
    return c.post(_URL + qs, files={"file": ("MA CB.xlsx", content, _MIME)})


# ── Luồng chính ────────────────────────────────────────────────────────────

def test_khop_theo_ma_can_bo_va_ghi_iso(client):
    data = _xlsx([
        (None, "Ban Lãnh đạo", None, None, None),          # dòng tiêu đề nhóm
        (1, "Nguyễn Quốc Hùng", "200733664", "01/04/1999", "Ban Lãnh đạo"),
        (2, "Đào Tiến Thành", "201101780", "22/04/2012", "Phòng Thanh Toán"),
    ])
    r = _post(client, data)
    assert r.status_code == 200
    body = r.json()
    assert (body["updated"], body["total_rows"]) == (2, 2)
    assert _ngay(client, "200733664") == "1999-04-01"
    assert _ngay(client, "201101780") == "2012-04-22"


def test_chay_lai_khong_doi_gi(client):
    data = _xlsx([(1, "A", "200733664", "01/04/1999", "X")])
    _post(client, data)
    body = _post(client, data).json()
    assert (body["updated"], body["unchanged"]) == (0, 1)


def test_dry_run_khong_ghi_db(client):
    data = _xlsx([(1, "A", "200733664", "01/04/1999", "X")])
    body = _post(client, data, "?dry_run=true").json()
    assert body["updated"] == 1 and body["dry_run"] is True
    assert _ngay(client, "200733664") is None
    assert client.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0


# ── Bảo vệ dữ liệu đã có ───────────────────────────────────────────────────

def test_mac_dinh_khong_de_len_nguoi_da_co_ngay(client):
    data = _xlsx([(1, "Nguyễn Thị Hiền", "200739320", "01/01/2000", "X")])
    body = _post(client, data).json()
    assert body["updated"] == 0
    assert len(body["kept_existing"]) == 1
    assert _ngay(client, "200739320") == "2008-01-15"


def test_overwrite_true_thi_de_len(client):
    data = _xlsx([(1, "Nguyễn Thị Hiền", "200739320", "01/01/2000", "X")])
    body = _post(client, data, "?overwrite=true").json()
    assert body["updated"] == 1
    assert _ngay(client, "200739320") == "2000-01-01"


def test_ma_khong_co_trong_he_thong_bi_bao_chu_khong_tao_moi(client):
    data = _xlsx([(1, "Người lạ", "123456789", "01/01/2000", "X")])
    body = _post(client, data).json()
    assert body["updated"] == 0 and len(body["not_found"]) == 1
    assert client.conn.execute("SELECT COUNT(*) FROM user_tttt").fetchone()[0] == 4


def test_nguoi_da_xoa_khong_duoc_khop(client):
    data = _xlsx([(1, "Đã xoá", "999999999", "01/01/2000", "X")])
    body = _post(client, data).json()
    assert len(body["not_found"]) == 1
    assert _ngay(client, "999999999") is None


# ── Đọc ngày ───────────────────────────────────────────────────────────────

def test_o_ngay_trong_hoac_sai_bi_bao_khong_lam_hong_dong_khac(client):
    data = _xlsx([
        (1, "A", "200733664", "01/04/1999", "X"),
        (2, "B", "201101780", None, "X"),
        (3, "C", "200739320", "khong-phai-ngay", "X"),
    ])
    body = _post(client, data).json()
    assert body["updated"] == 1
    assert len(body["bad_date"]) == 2
    assert _ngay(client, "200733664") == "1999-04-01"


def test_nhan_ca_datetime_va_nam_vo_ly_bi_loai(client):
    from datetime import datetime
    data = _xlsx([
        (1, "A", "200733664", datetime(1999, 4, 1), "X"),
        (2, "B", "201101780", f"01/01/{date.today().year + 5}", "X"),
    ])
    body = _post(client, data).json()
    assert _ngay(client, "200733664") == "1999-04-01"
    assert _ngay(client, "201101780") is None
    assert len(body["bad_date"]) == 1


def test_ma_can_bo_o_dang_so_van_khop(client):
    # Ô Excel định dạng Number → openpyxl trả int/float, str() ra "200733664.0"
    data = _xlsx([(1, "A", 200733664, "01/04/1999", "X")])
    assert _post(client, data).json()["updated"] == 1


# ── File hỏng ──────────────────────────────────────────────────────────────

def test_tu_choi_file_khong_phai_excel(client):
    r = client.post(_URL, files={"file": ("users.db", b"SQLite format 3", "application/octet-stream")})
    assert r.status_code == 400


def test_thieu_cot_bat_buoc_thi_bao_loi_ro(client):
    data = _xlsx([(1, "A", "200733664", "01/04/1999", "X")],
                 header=("STT", "Họ và tên", "Mã cán bộ", "Ngày sinh", "Phòng"))
    r = _post(client, data)
    assert r.status_code == 400 and "Ngày vào ngành" in r.json()["detail"]
