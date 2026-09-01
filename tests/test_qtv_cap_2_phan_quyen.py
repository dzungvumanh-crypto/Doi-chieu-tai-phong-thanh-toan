"""Quản trị viên cấp 2 vào được màn Phân quyền chức năng — nhưng không tự nâng quyền.

Trước bản vá, mọi endpoint /api/groups đều `require_admin` nên cấp 2 nhận 403 và
menu bị ẩn luôn ở sidebar. Nay cấp 2 dùng màn này như cấp 1, trừ hai đường có
thể dùng để tự nâng mình lên gần bằng cấp 1:
    - sửa nhóm mà chính mình là thành viên (kể cả ma trận quyền)
    - tự thêm mình vào một nhóm bất kỳ

Chạy: .venv/Scripts/python.exe -m pytest tests/test_qtv_cap_2_phan_quyen.py -v
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.main import app

_L2_ID = 2          # QTV cấp 2 đang đăng nhập
_NGUOI_KHAC = 9
NHOM_CUA_TOI = 1
NHOM_KHAC = 2


def _client(role) -> TestClient:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE user_groups (
            id INTEGER PRIMARY KEY, name TEXT, description TEXT,
            is_active BOOLEAN DEFAULT 1, created_at TEXT);
        CREATE TABLE group_members (group_id INTEGER, staff_id INTEGER);
        CREATE TABLE group_features (group_id INTEGER, feature_code TEXT);
        CREATE TABLE user_tttt (
            id INTEGER PRIMARY KEY, full_name TEXT, role TEXT, employee_code TEXT,
            department_id INTEGER, is_active INTEGER DEFAULT 1, is_deleted INTEGER DEFAULT 0);
        CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO user_groups (id, name, is_active) VALUES (1, 'Nhom QTV', 1), (2, 'Nhom Ke toan', 1);
        INSERT INTO group_members (group_id, staff_id) VALUES (1, 2);
        INSERT INTO user_tttt (id, full_name, role) VALUES (2, 'QTV cap 2', 'admin_l2'), (9, 'Nhan vien', 'chuyen_vien');
    """)
    conn.commit()

    app.dependency_overrides[get_current_staff] = lambda: {
        "id": _L2_ID, "role": role, "username": "test-l2", "full_name": "QTV cap 2",
    }
    def _db():
        yield conn

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


@pytest.fixture
def l2():
    yield _client(StaffRole.ADMIN_L2)
    app.dependency_overrides.clear()


@pytest.fixture
def chuyen_vien():
    yield _client(StaffRole.CHUYEN_VIEN)
    app.dependency_overrides.clear()


class TestCap2DungDuocManPhanQuyen:
    def test_xem_duoc_danh_sach_nhom(self, l2):
        r = l2.get("/api/groups")
        assert r.status_code == 200
        assert {g["name"] for g in r.json()} == {"Nhom QTV", "Nhom Ke toan"}

    def test_co_co_danh_dau_nhom_chua_minh(self, l2):
        nhom = {g["id"]: g["contains_me"] for g in l2.get("/api/groups").json()}
        assert nhom[NHOM_CUA_TOI] == 1
        assert nhom[NHOM_KHAC] == 0

    def test_tao_nhom_moi(self, l2):
        r = l2.post("/api/groups", json={"name": "Nhom moi"})
        assert r.status_code == 201

    def test_sua_quyen_nhom_khong_chua_minh(self, l2):
        r = l2.put(f"/api/groups/{NHOM_KHAC}/features", json={"codes": ["menu.leaves"]})
        assert r.status_code == 200
        assert r.json()["codes"] == ["menu.leaves"]

    def test_them_nguoi_khac_vao_nhom(self, l2):
        r = l2.post(f"/api/groups/{NHOM_KHAC}/members", json={"staff_id": _NGUOI_KHAC})
        assert r.status_code == 201


class TestCap2KhongTuNangQuyen:
    def test_khong_sua_duoc_quyen_cua_nhom_minh_o_trong(self, l2):
        r = l2.put(f"/api/groups/{NHOM_CUA_TOI}/features", json={"codes": ["menu.staff"]})
        assert r.status_code == 403

    def test_khong_sua_duoc_thong_tin_nhom_minh_o_trong(self, l2):
        assert l2.put(f"/api/groups/{NHOM_CUA_TOI}", json={"name": "Doi ten"}).status_code == 403

    def test_khong_xoa_duoc_nhom_minh_o_trong(self, l2):
        assert l2.delete(f"/api/groups/{NHOM_CUA_TOI}").status_code == 403

    def test_khong_them_bot_thanh_vien_nhom_minh_o_trong(self, l2):
        assert l2.post(
            f"/api/groups/{NHOM_CUA_TOI}/members", json={"staff_id": _NGUOI_KHAC}
        ).status_code == 403
        assert l2.delete(
            f"/api/groups/{NHOM_CUA_TOI}/members/{_NGUOI_KHAC}"
        ).status_code == 403

    def test_khong_tu_them_minh_vao_nhom_khac(self, l2):
        """Đường vòng: lập nhóm mới full quyền rồi tự thêm mình vào — lúc thêm,
        nhóm chưa chứa mình nên luật "nhóm chứa mình" không bắt được."""
        r = l2.post(f"/api/groups/{NHOM_KHAC}/members", json={"staff_id": _L2_ID})
        assert r.status_code == 403


class TestVaiTroKhacVanBiChan:
    def test_chuyen_vien_khong_vao_duoc(self, chuyen_vien):
        assert chuyen_vien.get("/api/groups").status_code == 403
        assert chuyen_vien.put(
            f"/api/groups/{NHOM_KHAC}/features", json={"codes": []}
        ).status_code == 403
