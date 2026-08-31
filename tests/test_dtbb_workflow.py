"""Test luồng lưu/xác nhận/bỏ xác nhận kỳ DTBB (backend/api/dtbb.py).

Trọng tâm: quyền xác nhận (Trưởng/Phó phòng Kế toán, không tự xác nhận kỳ chính
mình tạo/sửa), kỳ đã xác nhận (xanh) bị chặn ghi đè cho tới khi bỏ xác nhận, và
(report_date, branch_code) là khoá — 1 ngày nhiều chi nhánh cùng lưu được.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app

_SCHEMA = """
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY, full_name TEXT, role TEXT, department_id INTEGER, is_active INTEGER DEFAULT 1
);
CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT);
CREATE TABLE dtbb_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date     DATE NOT NULL,
    branch_code     VARCHAR(10) NOT NULL DEFAULT '9999',
    vnd_duoi12      REAL NOT NULL DEFAULT 0,
    vnd_tu12        REAL NOT NULL DEFAULT 0,
    usd_duoi12      REAL NOT NULL DEFAULT 0,
    usd_tu12        REAL NOT NULL DEFAULT 0,
    tk413_usd       REAL NOT NULL DEFAULT 0,
    rate_usd_to_vnd REAL NOT NULL DEFAULT 0,
    file_count      INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed')),
    confirmed_by    INTEGER,
    confirmed_at    DATETIME,
    created_by      INTEGER NOT NULL,
    created_at      DATETIME NOT NULL,
    updated_by      INTEGER,
    updated_at      DATETIME,
    UNIQUE(report_date, branch_code)
);
CREATE TABLE dtbb_report_details (
    id INTEGER PRIMARY KEY,
    report_id INTEGER REFERENCES dtbb_reports(id) ON DELETE CASCADE,
    ccy TEXT, rate_to_vnd REAL,
    group1_native REAL DEFAULT 0, group2_native REAL DEFAULT 0, tk413_native REAL DEFAULT 0
);
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT, target_type TEXT,
    target_id INTEGER, detail TEXT, ip_address TEXT, created_at DATETIME
);
"""


@pytest.fixture
def client_va_db():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(_SCHEMA)
    db.execute("INSERT INTO departments (id, code) VALUES (1, 'ACCT')")
    db.execute("INSERT INTO departments (id, code) VALUES (2, 'KSNB')")
    # id=10 chuyên viên ACCT (tạo/lưu), id=11 trưởng phòng ACCT (xác nhận),
    # id=12 phó phòng ACCT, id=13 chuyên viên phòng khác (không được vào)
    db.execute("INSERT INTO user_tttt (id, full_name, role, department_id) VALUES "
               "(10, 'Chuyen Vien', 'chuyen_vien', 1), "
               "(11, 'Truong Phong', 'truong_phong', 1), "
               "(12, 'Pho Phong', 'pho_phong', 1), "
               "(13, 'Nguoi Ngoai', 'chuyen_vien', 2)")
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app), db
    app.dependency_overrides.clear()
    db.close()


def _dang_nhap(staff_id: int, role: str, department_id: int = 1):
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": staff_id, "role": role, "department_id": department_id,
        "username": "u", "full_name": "Test",
    }


_BODY_MAU = {
    "report_date": "2026-07-31",
    "branch_code": "9999",
    "file_count": 2,
    "vnd_duoi12": 100.0,
    "vnd_tu12": 50.0,
    "usd_duoi12": 10.0,
    "usd_tu12": 5.0,
    "tk413_usd": 1.0,
    "details": [],
}


def test_luu_moi_ra_trang_thai_vang(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    r = client.post("/api/dtbb/save", json=_BODY_MAU)
    assert r.status_code == 200, r.text
    row = db.execute("SELECT status FROM dtbb_reports WHERE report_date='2026-07-31'").fetchone()
    assert row["status"] == "pending"


def test_1_ngay_2_chi_nhanh_cung_luu_duoc(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    r1 = client.post("/api/dtbb/save", json=_BODY_MAU)
    r2 = client.post("/api/dtbb/save", json={**_BODY_MAU, "branch_code": "1200"})
    assert r1.status_code == 200 and r2.status_code == 200
    n = db.execute("SELECT COUNT(*) c FROM dtbb_reports WHERE report_date='2026-07-31'").fetchone()["c"]
    assert n == 2


def test_nguoi_ngoai_phong_ke_toan_khong_luu_duoc(client_va_db):
    client, _ = client_va_db
    _dang_nhap(13, "chuyen_vien", department_id=2)
    r = client.post("/api/dtbb/save", json=_BODY_MAU)
    assert r.status_code == 403


def test_truong_phong_xac_nhan_duoc_ky_nguoi_khac_luu(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(11, "truong_phong")
    r = client.post(f"/api/dtbb/{report_id}/confirm")
    assert r.status_code == 200, r.text
    row = db.execute("SELECT status, confirmed_by FROM dtbb_reports WHERE id=?", (report_id,)).fetchone()
    assert row["status"] == "confirmed"
    assert row["confirmed_by"] == 11


def test_khong_tu_xac_nhan_ky_chinh_minh_da_luu(client_va_db):
    client, db = client_va_db
    _dang_nhap(11, "truong_phong")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    # Vẫn đăng nhập id=11 (chính người vừa lưu) — dù đúng vai trò Trưởng phòng,
    # vẫn phải bị chặn vì là chính người tạo.
    r = client.post(f"/api/dtbb/{report_id}/confirm")
    assert r.status_code == 403


def test_chuyen_vien_khong_duoc_xac_nhan(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(12, "chuyen_vien")  # id khác nhưng role chuyen_vien, không phải KSV
    r = client.post(f"/api/dtbb/{report_id}/confirm")
    assert r.status_code == 403


def test_ky_da_xanh_bi_chan_ghi_de(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(11, "truong_phong")
    client.post(f"/api/dtbb/{report_id}/confirm")

    _dang_nhap(10, "chuyen_vien")
    r = client.post("/api/dtbb/save", json={**_BODY_MAU, "confirm_overwrite": True, "vnd_duoi12": 999.0})
    assert r.status_code == 400
    row = db.execute("SELECT vnd_duoi12 FROM dtbb_reports WHERE id=?", (report_id,)).fetchone()
    assert row["vnd_duoi12"] == 100.0  # KHÔNG bị ghi đè


def test_bo_xac_nhan_roi_ghi_de_lai_duoc(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(11, "truong_phong")
    client.post(f"/api/dtbb/{report_id}/confirm")
    r = client.post(f"/api/dtbb/{report_id}/unconfirm")
    assert r.status_code == 200, r.text
    row = db.execute("SELECT status, confirmed_by FROM dtbb_reports WHERE id=?", (report_id,)).fetchone()
    assert row["status"] == "pending"
    assert row["confirmed_by"] is None

    _dang_nhap(10, "chuyen_vien")
    r = client.post("/api/dtbb/save", json={**_BODY_MAU, "confirm_overwrite": True, "vnd_duoi12": 999.0})
    assert r.status_code == 200, r.text
    row = db.execute("SELECT vnd_duoi12, status FROM dtbb_reports WHERE id=?", (report_id,)).fetchone()
    assert row["vnd_duoi12"] == 999.0
    assert row["status"] == "pending"  # ghi đè lại luôn về pending, không giữ xanh cũ


def test_admin_bypass_xac_nhan_duoc(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(999, "admin", department_id=None)
    r = client.post(f"/api/dtbb/{report_id}/confirm")
    assert r.status_code == 200, r.text


def test_xoa_ky_dang_vang_thanh_cong(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]
    db.execute(
        "INSERT INTO dtbb_report_details (report_id, ccy, rate_to_vnd) VALUES (?, 'USD', 1.0)",
        (report_id,),
    )
    db.commit()

    # Người khác cùng phòng ACCT (không phải người tạo, không phải KSV) vẫn xoá được —
    # quyền xoá kỳ vàng áp dụng cho mọi người trong phòng, không riêng KSV.
    _dang_nhap(12, "pho_phong")
    r = client.delete(f"/api/dtbb/{report_id}")
    assert r.status_code == 200, r.text
    assert db.execute("SELECT * FROM dtbb_reports WHERE id=?", (report_id,)).fetchone() is None
    assert db.execute(
        "SELECT * FROM dtbb_report_details WHERE report_id=?", (report_id,)
    ).fetchone() is None  # cascade xoá theo


def test_xoa_ky_da_xanh_bi_chan(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(11, "truong_phong")
    client.post(f"/api/dtbb/{report_id}/confirm")

    r = client.delete(f"/api/dtbb/{report_id}")
    assert r.status_code == 400
    assert db.execute("SELECT * FROM dtbb_reports WHERE id=?", (report_id,)).fetchone() is not None


def test_nguoi_ngoai_phong_ke_toan_khong_xoa_duoc(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(13, "chuyen_vien", department_id=2)
    r = client.delete(f"/api/dtbb/{report_id}")
    assert r.status_code == 403
    assert db.execute("SELECT * FROM dtbb_reports WHERE id=?", (report_id,)).fetchone() is not None


def test_save_chan_nan_infinity():
    """NaN/Infinity không nghiệp vụ nào sinh ra hợp lệ — chặn ở schema.

    Test thẳng ở tầng Pydantic (không qua HTTP): httpx tự chặn NaN/Infinity khi encode
    JSON phía Python (ValueError) trước cả khi gửi được request thật — không mô phỏng
    được qua TestClient. Ngoài phạm vi sửa lần này: nếu 1 client thô gửi thẳng byte
    JSON có token NaN/Infinity literal vượt qua được bước đó, FastAPI mặc định render
    lỗi 422 bằng json.dumps(..., allow_nan=False) — echo lại giá trị NaN gốc trong
    "input" của error detail cũng làm chính bước render đó ném ValueError → 500 thay
    vì 422 sạch. Đây là hạn chế sẵn có của FastAPI/Starlette (ảnh hưởng MỌI schema
    dùng allow_inf_nan=False trong toàn hệ thống), không riêng DTBB — ngoài phạm vi
    sửa ở đây.
    """
    from pydantic import ValidationError
    from backend.schemas.dtbb import DtbbSaveRequest

    with pytest.raises(ValidationError):
        DtbbSaveRequest(**{**_BODY_MAU, "vnd_duoi12": float("nan")})
    with pytest.raises(ValidationError):
        DtbbSaveRequest(**{**_BODY_MAU, "usd_tu12": float("inf")})


def test_save_cho_phep_so_am_hop_le_do_tru_9300(client_va_db):
    """Số âm PHẢI được chấp nhận — có thể hợp lệ do nghiệp vụ trừ CN 9300 theo từng
    dòng tài khoản (tài khoản chỉ có ở 9300 → kết quả âm là đúng thiết kế)."""
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    r = client.post("/api/dtbb/save", json={**_BODY_MAU, "usd_duoi12": -500.0})
    assert r.status_code == 200, r.text
    row = db.execute("SELECT usd_duoi12 FROM dtbb_reports WHERE report_date='2026-07-31'").fetchone()
    assert row["usd_duoi12"] == -500.0


def test_calculate_file_loi_tra_ve_filenames_co_cau_truc(client_va_db):
    """File .XLS rác (không mở được) → DtbbFileError.filenames → detail trả về dạng
    dict {"message", "filenames"} — FE (ApiFileError) dùng để tô đỏ đúng file lỗi."""
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    r = client.post(
        "/api/dtbb/calculate",
        files=[("files", ("USD20260715.XLS", b"khong phai file xls that", "application/octet-stream"))],
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["filenames"] == ["USD20260715.XLS"]


def test_xoa_ghi_audit_log(client_va_db):
    client, db = client_va_db
    _dang_nhap(10, "chuyen_vien")
    client.post("/api/dtbb/save", json=_BODY_MAU)
    report_id = db.execute("SELECT id FROM dtbb_reports").fetchone()["id"]

    _dang_nhap(12, "pho_phong")
    client.delete(f"/api/dtbb/{report_id}")
    row = db.execute(
        "SELECT actor_id, action, target_id FROM audit_logs WHERE action='dtbb_delete'"
    ).fetchone()
    assert row is not None
    assert row["actor_id"] == 12
    assert row["target_id"] == report_id
