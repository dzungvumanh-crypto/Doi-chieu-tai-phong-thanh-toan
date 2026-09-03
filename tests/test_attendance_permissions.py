"""Test phân quyền + validate input module Chấm công (Phòng Kế toán).

Bối cảnh: 5 vòng rà soát (review PR #22 + 4 vòng rà soát bổ sung) phát hiện và
sửa nhiều lỗi "âm thầm" — đặc biệt lỗ hổng phân quyền (chỉ chặn đúng role
"chuyen_vien", bỏ sót vai trò khác không phải quản lý như hau_kiem_vien nếu
được gán vào ACCT). Toàn bộ test trước đó là script tạm rồi xoá — file này khoá
lại các quy tắc đã xác nhận, tránh tái phát khi có người sửa code sau này.

Quyền VÀO màn hình nay là mã "menu.attendance" gán qua nhóm, không phải mã phòng
ACCT — fixture `seeded` gán sẵn cho 4 người, cố ý bỏ "outsider". Phân biệt tiếp
trong màn (xem cả phòng / xin điều chỉnh hộ người khác) vẫn theo role quản lý
CỘNG THÊM attendance.view_dept — đó là quyền cộng thêm, không thay thế.

Dùng TestClient + dependency_overrides (get_current_staff/get_db) — DB thật
chạy qua _create_tables/_ensure_indexes trên file SQLite tạm, không đụng
data/ksnb.db. Không dùng ":memory:" vì TestClient có thể mở nhiều connection
khác nhau tới cùng 1 request — ":memory:" mỗi connection là 1 DB riêng biệt.
"""
import os
import sqlite3
import tempfile
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_staff
from backend.core.enums import StaffRole
from backend.database import get_db
from backend.db.migrations import _create_tables, _ensure_indexes
from backend.main import app
from tests.conftest import cap_quyen


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """DB tạm (file), chạy migration thật — có đủ bảng/trigger của module Chấm công."""
    path = str(tmp_path / "test_attendance.db")
    # _ensure_indexes() đọc DB_PATH từ backend.database tại thời điểm gọi (module-level
    # import trong migrations.py: "from backend.database import DB_PATH") — phải patch
    # đúng cả 2 chỗ như đã làm ở toàn bộ script test trước đó trong phiên rà soát.
    import backend.database as dbmod
    import backend.db.migrations as mig
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(mig, "DB_PATH", path)
    _create_tables(path)
    _ensure_indexes()
    return path


@pytest.fixture
def seeded(db_path):
    """Seed phòng ACCT + 1 phòng khác (PAYMENT) + nhân viên nhiều role."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    acct_id = conn.execute(
        "INSERT INTO departments (code, name, is_source, is_active) VALUES ('ACCT','Phong Ke toan',1,1)"
    ).lastrowid
    other_id = conn.execute(
        "INSERT INTO departments (code, name, is_source, is_active) VALUES ('PAYMENT','Phong Thanh toan',1,1)"
    ).lastrowid

    def _mk(code, name, role, dept_id, active=1):
        return conn.execute(
            """INSERT INTO user_tttt (employee_code, full_name, role, department_id,
                   is_active, username, pwd_hash) VALUES (?,?,?,?,?,?,?)""",
            (code, name, role, dept_id, active, f"u_{code}", "x"),
        ).lastrowid

    ids = {
        "chuyen_vien": _mk("E01", "Chuyen Vien A", StaffRole.CHUYEN_VIEN, acct_id),
        "chuyen_vien2": _mk("E02", "Chuyen Vien B", StaffRole.CHUYEN_VIEN, acct_id),
        "hau_kiem_vien": _mk("E03", "Hau Kiem Vien C", StaffRole.HAU_KIEM_VIEN, acct_id),
        "truong_phong": _mk("E04", "Truong Phong D", StaffRole.TRUONG_PHONG, acct_id),
        "admin": _mk("E05", "Admin E", StaffRole.ADMIN, None),
        "outsider": _mk("E06", "Nguoi Ngoai ACCT", StaffRole.CHUYEN_VIEN, other_id),
    }
    # Quyền vào màn Chấm công gán qua nhóm, KHÔNG suy ra từ role hay phòng (xem mục
    # "Phân quyền" trong docs/DESIGN.md). "outsider" cố ý không được gán — nó đóng vai
    # người chưa được cấp quyền, không còn đóng vai "người ngoài phòng ACCT".
    for k in ("chuyen_vien", "chuyen_vien2", "hau_kiem_vien", "truong_phong"):
        cap_quyen(conn, ids[k], "menu.attendance")
    conn.commit()
    conn.close()
    return {"acct_id": acct_id, "other_id": other_id, "ids": ids}


def _client(db_path, staff_id: int, role: str, department_id):
    """TestClient đăng nhập giả lập đúng 1 nhân viên cụ thể.

    check_same_thread=False: FastAPI chạy route sync trong threadpool khác thread
    tạo connection — khớp đúng cách backend/database.py::get_db() đang mở connection
    thật, nếu không sqlite3 raise "objects created in a thread can only be used in
    that same thread" ngay khi TestClient gọi request."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    def _fake_current():
        return {"id": staff_id, "role": role, "department_id": department_id, "full_name": "Test"}

    def _fake_db():
        try:
            yield conn
        finally:
            pass

    app.dependency_overrides[get_current_staff] = _fake_current
    app.dependency_overrides[get_db] = _fake_db
    return TestClient(app)


def _teardown():
    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════
# Chưa được cấp "menu.attendance" thì bị chặn hoàn toàn
# ══════════════════════════════════════════════════════════════

def test_chua_duoc_cap_quyen_bi_chan_hoan_toan(db_path, seeded):
    """Không có mã "menu.attendance" thì mọi endpoint đều 403 — kể cả xem công
    của chính mình. Trước đây điều kiện là "thuộc phòng ACCT"."""
    s = seeded
    c = _client(db_path, s["ids"]["outsider"], StaffRole.CHUYEN_VIEN, s["other_id"])
    try:
        r = c.get("/api/attendance/month", params={"year": 2026, "month": 9})
        assert r.status_code == 403
    finally:
        _teardown()


def test_nguoi_ngoai_acct_duoc_cap_quyen_van_vao_duoc(db_path, seeded):
    """Khoá đúng thay đổi hành vi: gate là MÃ QUYỀN, không phải mã phòng.

    "outsider" thuộc phòng PAYMENT. Trước đây bị chặn cứng vì không phải ACCT;
    giờ được cấp "menu.attendance" là vào được (bảng công vẫn chỉ liệt kê nhân
    viên ACCT — đó là phạm vi DỮ LIỆU, không phải phạm vi quyền)."""
    s = seeded
    conn = sqlite3.connect(db_path)
    cap_quyen(conn, s["ids"]["outsider"], "menu.attendance")
    conn.close()
    c = _client(db_path, s["ids"]["outsider"], StaffRole.CHUYEN_VIEN, s["other_id"])
    try:
        r = c.get("/api/attendance/month", params={"year": 2026, "month": 9})
        assert r.status_code == 200, r.text
    finally:
        _teardown()


# ══════════════════════════════════════════════════════════════
# B1 — phân quyền: hau_kiem_vien (không phải quản lý) không được vượt quyền
# ══════════════════════════════════════════════════════════════

def test_hau_kiem_vien_khong_xem_duoc_cong_nguoi_khac(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["hau_kiem_vien"], StaffRole.HAU_KIEM_VIEN, s["acct_id"])
    try:
        r = c.get("/api/attendance/day", params={
            "staff_id": s["ids"]["chuyen_vien"], "date": "2026-09-01",
        })
        assert r.status_code == 403
    finally:
        _teardown()


def test_hau_kiem_vien_khong_xin_dieu_chinh_ho_nguoi_khac(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["hau_kiem_vien"], StaffRole.HAU_KIEM_VIEN, s["acct_id"])
    try:
        past = date.today() - timedelta(days=1)
        while past.weekday() >= 5:
            past -= timedelta(days=1)
        r = c.post("/api/attendance/adjustments", json={
            "staff_id": s["ids"]["chuyen_vien"], "date": past.isoformat(),
            "new_symbol": "P", "reason": "test",
        })
        assert r.status_code == 403
    finally:
        _teardown()


def test_hau_kiem_vien_scope_pending_chi_thay_cua_minh(db_path, seeded):
    """Trước fix B1: bất kỳ role nào khác "chuyen_vien" rơi vào nhánh scope=pending,
    thấy TOÀN BỘ yêu cầu điều chỉnh đang chờ duyệt của cả phòng. Giờ phải fallback
    về "chỉ thấy của chính mình" giống chuyen_vien thường."""
    s = seeded
    c = _client(db_path, s["ids"]["hau_kiem_vien"], StaffRole.HAU_KIEM_VIEN, s["acct_id"])
    try:
        r = c.get("/api/attendance/adjustments", params={"scope": "pending"})
        assert r.status_code == 200
        assert r.json() == []
    finally:
        _teardown()


def test_truong_phong_duoc_xem_cong_nguoi_khac(db_path, seeded):
    """Đối chứng: quản lý thật (truong_phong) vẫn phải làm được các việc trên."""
    s = seeded
    c = _client(db_path, s["ids"]["truong_phong"], StaffRole.TRUONG_PHONG, s["acct_id"])
    try:
        r = c.get("/api/attendance/day", params={
            "staff_id": s["ids"]["chuyen_vien"], "date": "2026-09-01",
        })
        assert r.status_code == 200
    finally:
        _teardown()


def test_truong_phong_xin_dieu_chinh_ho_nguoi_khac_duoc(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["truong_phong"], StaffRole.TRUONG_PHONG, s["acct_id"])
    try:
        past = date.today() - timedelta(days=1)
        while past.weekday() >= 5:
            past -= timedelta(days=1)
        r = c.post("/api/attendance/adjustments", json={
            "staff_id": s["ids"]["chuyen_vien"], "date": past.isoformat(),
            "new_symbol": "P", "reason": "test hop le",
        })
        assert r.status_code == 200
    finally:
        _teardown()


# ══════════════════════════════════════════════════════════════
# Validate input
# ══════════════════════════════════════════════════════════════

def test_get_day_sai_dinh_dang_ngay_tra_400(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["chuyen_vien"], StaffRole.CHUYEN_VIEN, s["acct_id"])
    try:
        r = c.get("/api/attendance/day", params={
            "staff_id": s["ids"]["chuyen_vien"], "date": "not-a-date",
        })
        assert r.status_code == 400
    finally:
        _teardown()


def test_create_adjustment_ngay_tuong_lai_bi_chan(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["chuyen_vien"], StaffRole.CHUYEN_VIEN, s["acct_id"])
    try:
        future = date.today() + timedelta(days=10)
        r = c.post("/api/attendance/adjustments", json={
            "date": future.isoformat(), "new_symbol": "P", "reason": "test",
        })
        assert r.status_code == 400
    finally:
        _teardown()


def test_create_adjustment_reason_rong_bi_chan(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["chuyen_vien"], StaffRole.CHUYEN_VIEN, s["acct_id"])
    try:
        past = date.today() - timedelta(days=1)
        while past.weekday() >= 5:
            past -= timedelta(days=1)
        r = c.post("/api/attendance/adjustments", json={
            "date": past.isoformat(), "new_symbol": "P", "reason": "   ",
        })
        assert r.status_code == 400
    finally:
        _teardown()


def test_put_day_ngay_tuong_lai_bi_chan_ke_ca_truong_phong(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["truong_phong"], StaffRole.TRUONG_PHONG, s["acct_id"])
    try:
        future = date.today() + timedelta(days=10)
        r = c.put(
            "/api/attendance/day",
            params={"staff_id": s["ids"]["chuyen_vien"], "date": future.isoformat()},
            json={"symbol": "x"},
        )
        assert r.status_code == 400
    finally:
        _teardown()


def test_symbol_work_value_ngoai_khoang_bi_tu_choi(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["admin"], StaffRole.ADMIN, None)
    try:
        r = c.post("/api/attendance/symbols", json={
            "symbol": "ZZ", "description": "test", "work_value": 1.5,
        })
        assert r.status_code == 422
    finally:
        _teardown()


def test_symbol_hop_le_tao_duoc(db_path, seeded):
    s = seeded
    c = _client(db_path, s["ids"]["admin"], StaffRole.ADMIN, None)
    try:
        r = c.post("/api/attendance/symbols", json={
            "symbol": "ZZ", "description": "test hop le", "work_value": 0.5,
        })
        assert r.status_code == 200
    finally:
        _teardown()
