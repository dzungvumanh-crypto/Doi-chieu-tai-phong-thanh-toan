"""Chấm công: thứ Bảy đi làm bù là ngày làm việc.

Trước đây `/month`, `/day` và bản xuất Excel đều chỉ xét `d.weekday() < 5` +
`public_holidays`, nên thứ Bảy cả cơ quan đi làm vẫn bị chấm 0 công và không
xin điều chỉnh được. Ngày làm bù chỉ khai ở màn Phân lịch trực → Ngày đặc biệt.

Dùng DB file tạm chạy migration thật (không dùng ":memory:" — TestClient có thể
mở nhiều connection cho cùng 1 request), giống test_attendance_permissions.py.
"""
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.db.migrations import _create_tables, _ensure_indexes
from backend.main import app
from tests.conftest import cap_quyen

# 03/01/2026 là thứ Bảy, 02/01 là thứ Sáu
T7 = "2026-01-03"
T6 = "2026-01-02"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test_att_bu.db")
    import backend.database as dbmod
    import backend.db.migrations as mig
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(mig, "DB_PATH", path)
    _create_tables(path)
    _ensure_indexes()
    return path


@pytest.fixture
def seeded(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    acct_id = conn.execute(
        "INSERT INTO departments (code, name, is_source, is_active) VALUES ('ACCT','Phong Ke toan',1,1)"
    ).lastrowid
    tp_id = conn.execute(
        """INSERT INTO user_tttt (employee_code, full_name, role, department_id,
               is_active, username, pwd_hash) VALUES ('E04','Truong Phong D',?,?,1,'u_E04','x')""",
        (StaffRole.TRUONG_PHONG, acct_id),
    ).lastrowid
    # Quyền vào màn Chấm công gán qua nhóm, không suy ra từ role/phòng nữa.
    cap_quyen(conn, tp_id, "menu.attendance")
    conn.commit()
    conn.close()
    return {"acct_id": acct_id, "tp_id": tp_id}


@pytest.fixture
def client(db_path, seeded):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": seeded["tp_id"], "role": StaffRole.TRUONG_PHONG,
        "department_id": seeded["acct_id"], "full_name": "Truong Phong D",
    }
    def _fake_db():
        yield conn

    app.dependency_overrides[get_db] = _fake_db
    c = TestClient(app)
    c.conn = conn
    c.staff_id = seeded["tp_id"]
    yield c
    app.dependency_overrides.clear()
    conn.close()


def _lam_bu(conn, ngay=T7, xac_nhan=1):
    conn.execute(
        "INSERT INTO duty_special_days (date, day_type, is_confirmed) VALUES (?,'makeup',?)",
        (ngay, xac_nhan),
    )
    conn.commit()


def _get_day(client, ngay=T7):
    r = client.get("/api/attendance/day", params={"staff_id": client.staff_id, "date": ngay})
    assert r.status_code == 200, r.text
    return r.json()


# ── /day ─────────────────────────────────────────────────────────────────────

def test_t7_thuong_khong_tinh_cong(client):
    assert _get_day(client)["work_value"] == 0.0


def test_t7_lam_bu_tinh_cong_nhu_ngay_thuong(client):
    _lam_bu(client.conn)
    d = _get_day(client)
    assert d["symbol"] == "x"
    assert d["work_value"] > 0


def test_t7_lam_bu_chua_xac_nhan_van_khong_tinh_cong(client):
    _lam_bu(client.conn, xac_nhan=0)
    assert _get_day(client)["work_value"] == 0.0


def test_ngay_le_khai_ben_so_truc_khong_tinh_cong(client):
    """Ngày lễ khai ở tab Ngày đặc biệt (không có trong public_holidays) cũng phải nghỉ."""
    client.conn.execute(
        "INSERT INTO duty_special_days (date, day_type, is_confirmed) VALUES (?,'holiday',1)", (T6,)
    )
    client.conn.commit()
    assert _get_day(client, T6)["work_value"] == 0.0


# ── /month ───────────────────────────────────────────────────────────────────

def _month(client):
    r = client.get("/api/attendance/month", params={"year": 2026, "month": 1, "scope": "mine"})
    assert r.status_code == 200, r.text
    return r.json()


def test_month_tra_ve_danh_sach_ngay_lam_bu(client):
    """Frontend cần danh sách này để không tô T7 làm bù thành màu cuối tuần."""
    assert _month(client)["makeup_days"] == []
    _lam_bu(client.conn)
    assert _month(client)["makeup_days"] == [T7]


def test_month_cong_them_cong_cua_ngay_lam_bu(client):
    truoc = _month(client)["staff"][0]["total_work_value"]
    _lam_bu(client.conn)
    sau = _month(client)["staff"][0]["total_work_value"]
    assert sau > truoc


# ── Xin điều chỉnh ───────────────────────────────────────────────────────────

def test_khong_xin_dieu_chinh_duoc_cho_t7_thuong(client):
    r = client.post("/api/attendance/adjustments",
                    json={"date": T7, "new_symbol": "P", "reason": "Nghi phep"})
    assert r.status_code == 400
    assert "cuối tuần" in r.json()["detail"]


def test_xin_dieu_chinh_duoc_cho_t7_lam_bu(client):
    _lam_bu(client.conn)
    r = client.post("/api/attendance/adjustments",
                    json={"date": T7, "new_symbol": "P", "reason": "Nghi phep"})
    assert r.status_code == 200, r.text
