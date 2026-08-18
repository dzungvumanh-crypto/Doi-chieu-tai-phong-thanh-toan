"""Test rào chắn của POST /api/staff/import-db.

Endpoint này nhận file .db do /export-db xuất ra, trong đó có NGUYÊN `pwd_hash`,
`role` và số liệu phép. Bản cũ ghi đè mọi cột cho bất kỳ ai có feature
`staff.import_db`. Bốn rào chắn được canh ở đây:

  1. Chỉ quản trị viên gọi được — có feature thôi chưa đủ.
  2. Không đè số liệu phép của tài khoản ĐÃ CÓ.
  3. Bỏ dòng có vai trò sai chính tả.
  4. Bỏ dòng trỏ vào phòng ban không tồn tại.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_import_db_an_toan.py -v
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_URL = "/api/staff/import-db"

_COLS = ("employee_code", "full_name", "role", "department_id",
         "username", "pwd_hash", "used_leave_days", "is_active")

_SCHEMA = """
CREATE TABLE departments (
    id INTEGER PRIMARY KEY, code TEXT, name TEXT,
    is_active INTEGER DEFAULT 1, is_source INTEGER DEFAULT 1
);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY AUTOINCREMENT, employee_code TEXT UNIQUE, full_name TEXT,
    role TEXT DEFAULT 'chuyen_vien', department_id INTEGER, username TEXT,
    pwd_hash TEXT, used_leave_days INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1
);
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
    target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT, created_at DATETIME
);
CREATE TABLE user_groups   (id INTEGER PRIMARY KEY, is_active INTEGER DEFAULT 1);
CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
CREATE TABLE group_features(group_id INTEGER, feature_code TEXT);
"""


def _file_db(tmp_path, rows, name="users.db") -> bytes:
    """Dựng file .db giống bản /export-db xuất ra."""
    p = tmp_path / name
    con = sqlite3.connect(str(p))
    con.execute(
        "CREATE TABLE user_tttt (id INTEGER PRIMARY KEY, "
        + ", ".join(f"{c} TEXT" for c in _COLS) + ")"
    )
    con.executemany(
        f"INSERT INTO user_tttt ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
        rows,
    )
    con.commit()
    con.close()
    return p.read_bytes()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    c.executescript(
        """INSERT INTO departments (id, code, name) VALUES (1, 'TT', 'Phòng Thanh toán');
           INSERT INTO user_tttt (id, employee_code, full_name, role, department_id,
                                  username, pwd_hash, used_leave_days)
               VALUES (7, 'NV007', 'Trần Đang Làm', 'chuyen_vien', 1, 'nv007', 'hash-cu', 9);
           -- Trưởng phòng (20) và QTV cấp 2 (2) ĐƯỢC cấp feature staff.import_db qua nhóm
           INSERT INTO user_groups (id) VALUES (1);
           INSERT INTO group_members (group_id, staff_id) VALUES (1, 20), (1, 2);
           INSERT INTO group_features (group_id, feature_code) VALUES (1, 'staff.import_db');"""
    )
    c.commit()
    yield c
    c.close()


def _client(conn, role=StaffRole.ADMIN, uid=1):
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": uid, "role": role, "username": "u", "full_name": "U",
    }
    app.dependency_overrides[get_db] = lambda: (yield conn)
    return TestClient(app)


def _post(c, data):
    return c.post(_URL, files={"file": ("users.db", data, "application/octet-stream")})


@pytest.fixture(autouse=True)
def _don_override():
    yield
    app.dependency_overrides.clear()


def _lay(conn, code, cot):
    r = conn.execute(f"SELECT {cot} FROM user_tttt WHERE employee_code=?", (code,)).fetchone()
    return r[0] if r else None


# ── 1. Chỉ quản trị viên ─────────────────────────────────────────────────────

def test_co_feature_nhung_khong_phai_quan_tri_thi_bi_chan(conn, tmp_path):
    """Trưởng phòng có đúng feature staff.import_db vẫn phải bị từ chối:
    file .db đặt được mật khẩu và vai trò cho mọi tài khoản."""
    data = _file_db(tmp_path, [("NV009", "Người Mới", "chuyen_vien", 1, "nv009", "h", "0", "1")])
    r = _post(_client(conn, StaffRole.TRUONG_PHONG, uid=20), data)
    assert r.status_code == 403
    assert _lay(conn, "NV009", "id") is None


def test_quan_tri_thi_nhap_duoc(conn, tmp_path):
    data = _file_db(tmp_path, [("NV009", "Người Mới", "chuyen_vien", 1, "nv009", "h", "3", "1")])
    r = _post(_client(conn), data)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 1
    # Tài khoản MỚI thì số liệu phép đi theo người — đó là mục đích của việc di trú
    assert _lay(conn, "NV009", "used_leave_days") == 3


# ── 2. Không đè số liệu phép của tài khoản đã có ─────────────────────────────

def test_khong_de_ngay_phep_da_dung_len_tai_khoan_da_co(conn, tmp_path):
    """File cũ ghi 0 ngày phép; trên hệ thống người này đã nghỉ 9 ngày. Nhập file
    KHÔNG được xoá sổ 9 ngày đó — đấy là dữ liệu của tính năng Nghỉ phép."""
    data = _file_db(tmp_path, [("NV007", "Trần Đang Làm", "chuyen_vien", 1, "nv007", "hash-moi", "0", "1")])
    r = _post(_client(conn), data)
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1
    assert _lay(conn, "NV007", "used_leave_days") == 9      # giữ nguyên
    assert _lay(conn, "NV007", "pwd_hash") == "hash-moi"    # cột khác vẫn cập nhật


# ── 3 & 4. Dòng hỏng bị bỏ, có báo lại ───────────────────────────────────────

def test_vai_tro_sai_chinh_ta_thi_bo_dong(conn, tmp_path):
    """'truong_phong ' thừa dấu cách = tài khoản rớt khỏi mọi kiểm tra quyền."""
    data = _file_db(tmp_path, [("NV010", "Sai Vai Trò", "truong_phong ", 1, "nv010", "h", "0", "1")])
    r = _post(_client(conn), data)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 0
    assert len(r.json()["skipped"]) == 1
    assert "NV010" in r.json()["skipped"][0]
    assert _lay(conn, "NV010", "id") is None


def test_phong_ban_khong_ton_tai_thi_bo_dong(conn, tmp_path):
    data = _file_db(tmp_path, [("NV011", "Phòng Lạ", "chuyen_vien", 99, "nv011", "h", "0", "1")])
    r = _post(_client(conn), data)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 0
    assert "99" in r.json()["skipped"][0]


def test_dong_hong_khong_lam_hong_ca_me(conn, tmp_path):
    """Một dòng sai không được kéo theo những dòng đúng."""
    data = _file_db(tmp_path, [
        ("NV012", "Đúng", "chuyen_vien", 1, "nv012", "h", "0", "1"),
        ("NV013", "Sai vai trò", "sep_tong", 1, "nv013", "h", "0", "1"),
        ("NV014", "Đúng nữa", "chuyen_vien", 1, "nv014", "h", "0", "1"),
    ])
    r = _post(_client(conn), data)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 2
    assert len(r.json()["skipped"]) == 1
    assert _lay(conn, "NV013", "id") is None


def test_is_active_null_khong_lot_vao_db(conn, tmp_path):
    """NULL ở is_active làm CẢ danh sách /api/staff/ trả 500 — chặn tại cửa vào."""
    data = _file_db(tmp_path, [("NV015", "Không rõ", "chuyen_vien", 1, "nv015", "h", "0", None)])
    r = _post(_client(conn), data)
    assert r.status_code == 200, r.text
    assert _lay(conn, "NV015", "is_active") == 0


def test_qtv_cap_2_khong_dung_duoc_tai_khoan_qtv_cap_1(conn, tmp_path):
    conn.execute(
        "INSERT INTO user_tttt (employee_code, full_name, role, username, pwd_hash) "
        "VALUES ('AD001', 'Sếp Tổng', 'admin', 'ad001', 'hash-that')"
    )
    conn.commit()
    data = _file_db(tmp_path, [("AD001", "Giả Mạo", "admin", None, "ad001", "hash-gia", "0", "1")])
    r = _post(_client(conn, StaffRole.ADMIN_L2, uid=2), data)
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 0
    assert len(r.json()["skipped"]) == 1
    assert _lay(conn, "AD001", "pwd_hash") == "hash-that"
