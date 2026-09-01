"""Hậu kiểm viên KHÔNG tham gia quy trình nghỉ phép — ngang chuyên viên.

Trước đây `leaves.py` hardcode "hau_kiem_vien" vào mọi danh sách vai trò người
duyệt, trong khi phân quyền theo nhóm lại không cấp `leaves.approve_ksv` cho họ.
Hậu quả: họ hiện trong dropdown "Người phê duyệt (KSV)" và nhận được đơn, nhưng
bấm Duyệt thì backend trả 403 → đơn kẹt vĩnh viễn, chỉ admin gỡ được.

Bộ test này khoá lại hành vi đúng: không hiện trong danh sách chọn, không gán
được, không thấy đơn của người khác.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_nghi_phep_hau_kiem_vien.py -v
"""

import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api.leaves import _validate_ksv
from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.main import app

_SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT, name TEXT);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY, full_name TEXT, role TEXT,
    department_id INTEGER, is_active INTEGER DEFAULT 1
);
CREATE TABLE leave_records (
    id INTEGER PRIMARY KEY, status TEXT, ksv_approver_id INTEGER,
    tong_hop_approver_id INTEGER, gd_approver_id INTEGER, direct_by INTEGER,
    staff_id INTEGER, start_date TEXT, end_date TEXT, leave_type TEXT,
    reason TEXT, created_at DATETIME
);
INSERT INTO departments (id, code, name) VALUES (5, 'KSNB', 'Phòng KSNB&HTVH');
INSERT INTO user_tttt (id, full_name, role, department_id) VALUES
    (1, 'Trưởng phòng KSNB',  'truong_phong',  5),
    (2, 'Phó phòng KSNB',     'pho_phong',     5),
    (3, 'Hậu kiểm viên A',    'hau_kiem_vien', 5),
    (4, 'Hậu kiểm viên B',    'hau_kiem_vien', 5),
    (5, 'Chuyên viên KSNB',   'chuyen_vien',   5);
"""

_HKV = {"id": 3, "role": "hau_kiem_vien", "department_id": 5,
        "username": "hkv", "full_name": "Hậu kiểm viên A"}
_CV  = {"id": 5, "role": "chuyen_vien", "department_id": 5,
        "username": "cv", "full_name": "Chuyên viên KSNB"}


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    yield conn
    conn.close()


def _client(db, staff):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_staff] = lambda: staff
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


# ── Không hiện trong danh sách chọn người phê duyệt ──────────────────────────

def test_dropdown_nguoi_phe_duyet_khong_co_hau_kiem_vien(db):
    r = _client(db, _CV).get("/api/leaves/approvers")
    assert r.status_code == 200
    roles = {a["role_label"] for a in r.json()}
    assert roles == {"Trưởng phòng", "Phó phòng"}
    assert all("Hậu kiểm" not in a["full_name"] for a in r.json())


def test_hau_kiem_vien_nop_don_van_chon_duoc_lanh_dao_phong(db):
    """Bản thân họ vẫn phải chọn KSV như chuyên viên — chỉ là chọn TP/PP."""
    r = _client(db, _HKV).get("/api/leaves/approvers")
    assert r.status_code == 200
    assert {a["id"] for a in r.json()} == {1, 2}


# ── Không gán được làm người duyệt, kể cả gọi thẳng API ──────────────────────

def test_khong_gan_duoc_hau_kiem_vien_lam_ksv(db):
    with pytest.raises(HTTPException) as e:
        _validate_ksv(4, _CV, db)
    assert e.value.status_code == 400
    assert "Trưởng phòng" in e.value.detail


def test_van_gan_duoc_truong_pho_phong(db):
    assert _validate_ksv(1, _CV, db)["role"] == "truong_phong"
    assert _validate_ksv(2, _CV, db)["role"] == "pho_phong"


# ── Không xem được đơn của người khác ────────────────────────────────────────

@pytest.mark.parametrize("scope", ["all", "dept"])
def test_hau_kiem_vien_khong_xem_duoc_don_nguoi_khac(db, scope):
    r = _client(db, _HKV).get("/api/leaves/", params={"scope": scope})
    assert r.status_code == 403


def test_hau_kiem_vien_khong_nhan_don_cho_duyet(db):
    db.execute(
        """INSERT INTO leave_records (id, status, ksv_approver_id, staff_id,
                                      start_date, end_date, leave_type, reason)
           VALUES (1, 'pending_ksv', 3, 5, '2026-08-21', '2026-08-21', 'annual', 'viec rieng')"""
    )
    db.commit()
    r = _client(db, _HKV).get("/api/leaves/", params={"scope": "pending"})
    assert r.status_code == 200
    assert r.json() == []


# ── Lịch nghỉ phép cũng phải theo đúng phạm vi đó ────────────────────────────

def test_hau_kiem_vien_khong_xem_duoc_lich_nghi_phong_khac(db):
    """Chốt chặn ở /api/leaves/ mà quên /api/leaves/calendar thì HKV vẫn đọc được
    tên cả trung tâm, chỉ khác cửa vào. Không có bài này thì lần sau ai thêm một
    danh sách vai trò mới ở endpoint lịch cũng không có gì báo."""
    from datetime import date
    d = date.today().replace(day=15).isoformat()
    db.executescript(
        "INSERT INTO departments (id, code, name) VALUES (8, 'KT', 'Phòng Kế toán');"
        "INSERT INTO user_tttt (id, full_name, role, department_id)"
        " VALUES (9, 'Chuyên viên Kế toán', 'chuyen_vien', 8);"
    )
    for staff_id in (5, 9):
        db.execute(
            "INSERT INTO leave_records (status, staff_id, start_date, end_date,"
            " leave_type, reason) VALUES ('approved', ?, ?, ?, 'annual', 'viec rieng')",
            (staff_id, d, d),
        )
    db.commit()

    r = _client(db, _HKV).get(
        "/api/leaves/calendar", params={"year": date.today().year, "month": date.today().month}
    )
    assert r.status_code == 200
    ten = sorted(p["staff_name"] for p in r.json()["days"][d])
    assert ten == ["Chuyên viên KSNB"], f"HKV thấy cả phòng khác: {ten}"
