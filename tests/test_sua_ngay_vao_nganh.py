"""Test PATCH /api/leaves/quotas/staff/{id}/join-date.

`join_industry_date` là hồ sơ nhân sự nhưng có tới ba đường ghi; đường nằm trong
màn hình Nghỉ phép này trước đây nhận thẳng chuỗi client gửi và ghi nguyên vào
cột DATE, lại không để lại vết gì ngoài "PATCH <đường dẫn>". Số ngày phép năm
tính từ chính cột này.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_sua_ngay_vao_nganh.py -v
"""

import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db, _vn_now
from backend.main import app


def _url(sid=5):
    return f"/api/leaves/quotas/staff/{sid}/join-date"


@pytest.fixture
def client():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE user_tttt (
               id INTEGER PRIMARY KEY, full_name TEXT,
               join_industry_date DATE, is_active INTEGER DEFAULT 1);
           CREATE TABLE audit_logs (
               id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER, action TEXT NOT NULL,
               target_type TEXT, target_id INTEGER, detail TEXT, ip_address TEXT,
               created_at DATETIME);
           INSERT INTO user_tttt (id, full_name, join_industry_date)
               VALUES (5, 'Lê Vào Ngành', '2008-01-15');"""
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


def _ngay(c):
    return c.conn.execute("SELECT join_industry_date FROM user_tttt WHERE id=5").fetchone()[0]


@pytest.mark.parametrize("gia_tri", ["01/07/2020", "hôm qua", "2020-13-45", "2020/07/01", "  "])
def test_ngay_khong_dung_dinh_dang_thi_bi_tu_choi(client, gia_tri):
    """Chuỗi lạ lọt vào cột DATE sẽ làm compute_annual_leave() vỡ ở nơi khác,
    muộn hơn, không ai lần ra nguyên nhân."""
    r = client.patch(_url(), json={"join_industry_date": gia_tri})
    assert r.status_code == 400, r.text
    assert _ngay(client) == "2008-01-15"


def test_ngay_tuong_lai_bi_tu_choi(client):
    mai = (_vn_now().date() + timedelta(days=1)).isoformat()
    r = client.patch(_url(), json={"join_industry_date": mai})
    assert r.status_code == 400
    assert _ngay(client) == "2008-01-15"


def test_ngay_hop_le_thi_ghi_va_luu_vet_gia_tri_cu(client):
    r = client.patch(_url(), json={"join_industry_date": "2010-06-01"})
    assert r.status_code == 200, r.text
    assert _ngay(client) == "2010-06-01"

    row = client.conn.execute(
        "SELECT action, target_id, detail FROM audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["action"] == "staff_join_date_update"
    assert row["target_id"] == 5
    assert "2008-01-15" in row["detail"] and "2010-06-01" in row["detail"]


def test_nhan_vien_khong_ton_tai_thi_404(client):
    r = client.patch(_url(999), json={"join_industry_date": "2010-06-01"})
    assert r.status_code == 404
