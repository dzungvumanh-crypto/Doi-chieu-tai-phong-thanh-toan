"""P2 (23/09/2026): `GET /api/leaves/?scope=all&tu_nam=Y` — Dashboard không tải mọi đơn từ trước tới nay.

Giới hạn chỉ áp khi bên gọi truyền `tu_nam`; không truyền thì như cũ. Đơn còn chờ duyệt
luôn được trả dù cũ bao lâu (5 ô tổng quan đếm chúng).
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.database import get_db
from backend.db.migrations import _create_tables, _ensure_indexes
from backend.main import app


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    import backend.database as dbmod
    import backend.db.migrations as mig
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(mig, "DB_PATH", path)
    _create_tables(path)
    _ensure_indexes()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    dept = conn.execute("INSERT INTO departments (code, name, is_source, is_active) "
                        "VALUES ('TT','Phong TT',1,1)").lastrowid
    sid = conn.execute(
        "INSERT INTO user_tttt (employee_code, full_name, role, department_id, is_active, "
        "username, pwd_hash) VALUES ('E1','Nguoi A','chuyen_vien',?,1,'a','x')", (dept,)).lastrowid
    for ma, bd, kt, tt in (
        ("cu_da_duyet", "2023-03-01", "2023-03-02", "approved"),
        ("cu_dang_cho", "2023-05-01", "2023-05-01", "pending_ksv"),
        ("nam_truoc",   "2025-12-30", "2026-01-02", "approved"),
        ("nam_nay",     "2026-09-01", "2026-09-01", "approved"),
    ):
        conn.execute(
            "INSERT INTO leave_records (staff_id, start_date, end_date, leave_type, reason, status, "
            "created_at) VALUES (?,?,?,?,?,?,datetime('now'))",
            (sid, bd, kt, "phep_nam", ma, tt))
    conn.commit()
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_current_staff] = lambda: {
        "id": 999, "role": "admin", "department_id": None, "full_name": "QTV"}
    yield conn
    app.dependency_overrides.clear()
    conn.close()


def _ly_do(params):
    r = TestClient(app).get("/api/leaves/", params=params)
    assert r.status_code == 200, r.text
    return {lv["reason"] for lv in r.json()}


def test_khong_truyen_tu_nam_thi_nhu_cu(db):
    assert _ly_do({"scope": "all"}) == {"cu_da_duyet", "cu_dang_cho", "nam_truoc", "nam_nay"}


def test_tu_nam_bo_don_cu_da_xong_giu_don_dang_cho(db):
    # Đơn vắt năm (30/12/2025 → 02/01/2026) có ngày nằm trong 2026 nên vẫn được trả
    assert _ly_do({"scope": "all", "tu_nam": 2026}) == {"cu_dang_cho", "nam_truoc", "nam_nay"}
    assert _ly_do({"scope": "all", "tu_nam": 2025}) == {"cu_dang_cho", "nam_truoc", "nam_nay"}


def test_tu_nam_sai_mien_bi_tu_choi(db):
    assert TestClient(app).get("/api/leaves/", params={"scope": "all", "tu_nam": 1900}).status_code == 422
