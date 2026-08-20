"""Test trigger đồng bộ Nghỉ phép ↔ Chấm công (Phòng Kế toán).

Bối cảnh: module Chấm công không được sửa backend/api/leaves.py (module của
Người 3) nên toàn bộ đồng bộ "đơn nghỉ được duyệt -> tự ghi ký hiệu vào bảng
chấm công" làm bằng trigger SQL thuần trong backend/db/migrations.py, tự kích
hoạt trên INSERT/UPDATE/DELETE thật của leave_records. 5 vòng rà soát đã sửa
nhiều lỗi âm thầm ở đúng các trigger này — file test này khoá lại từng lỗi đã
sửa để tránh tái phát.

Thao tác thẳng bằng sqlite3 (không qua HTTP) vì đây là hành vi trigger kích
hoạt bởi thay đổi leave_records — không có endpoint nào trong attendance.py
chủ động gọi tới."""
import sqlite3

import pytest

from backend.db.migrations import _create_tables, _ensure_indexes


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "test_leave_sync.db")
    import backend.database as dbmod
    import backend.db.migrations as mig
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(mig, "DB_PATH", path)
    _create_tables(path)
    _ensure_indexes()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def staff(db):
    """1 nhân viên active thuộc phòng ACCT."""
    dept_id = db.execute(
        "INSERT INTO departments (code, name, is_source, is_active) VALUES ('ACCT','Phong Ke toan',1,1)"
    ).lastrowid
    staff_id = db.execute(
        """INSERT INTO user_tttt (employee_code, full_name, role, department_id,
               is_active, username, pwd_hash) VALUES (?,?,?,?,?,?,?)""",
        ("E01", "Nhan Vien Test", "chuyen_vien", dept_id, 1, "u_e01", "x"),
    ).lastrowid
    db.commit()
    return {"dept_id": dept_id, "staff_id": staff_id}


def _tao_don(db, staff_id, start, end, leave_type, reason, status="pending"):
    cur = db.execute(
        """INSERT INTO leave_records (staff_id, start_date, end_date, leave_type,
               reason, status, created_at) VALUES (?,?,?,?,?,?,datetime('now'))""",
        (staff_id, start, end, leave_type, reason, status),
    )
    db.commit()
    return cur.lastrowid


def _duyet(db, leave_id):
    db.execute("UPDATE leave_records SET status='approved' WHERE id=?", (leave_id,))
    db.commit()


def _attendances_cua(db, staff_id, start=None, end=None):
    if start:
        return db.execute(
            "SELECT * FROM attendances WHERE staff_id=? AND date BETWEEN ? AND ? ORDER BY date",
            (staff_id, start, end),
        ).fetchall()
    return db.execute(
        "SELECT * FROM attendances WHERE staff_id=? ORDER BY date", (staff_id,)
    ).fetchall()


# ══════════════════════════════════════════════════════════════
# Ký hiệu theo leave_type
# ══════════════════════════════════════════════════════════════

def test_nghi_thuong_duyet_duoc_danh_ky_hieu_P(db, staff):
    # 2026-09-07 là thứ Hai
    lid = _tao_don(db, staff["staff_id"], "2026-09-07", "2026-09-08", "annual", "nghi phep thuong")
    _duyet(db, lid)
    rows = _attendances_cua(db, staff["staff_id"])
    assert len(rows) == 2
    assert all(r["symbol"] == "P" for r in rows)
    assert all(r["source_leave_id"] == lid for r in rows)


def test_thai_san_duoc_danh_ky_hieu_T(db, staff):
    lid = _tao_don(db, staff["staff_id"], "2026-09-07", "2026-09-07", "thai_san", "nghi thai san")
    _duyet(db, lid)
    rows = _attendances_cua(db, staff["staff_id"])
    assert len(rows) == 1 and rows[0]["symbol"] == "T"


def test_sick_duoc_danh_ky_hieu_O(db, staff):
    lid = _tao_don(db, staff["staff_id"], "2026-09-07", "2026-09-07", "sick", "nghi om")
    _duyet(db, lid)
    rows = _attendances_cua(db, staff["staff_id"])
    assert len(rows) == 1 and rows[0]["symbol"] == "O"


# ══════════════════════════════════════════════════════════════
# B2 — NULL reason: đơn "bat_buoc" thật (không có lý do) vẫn phải được chấm công
# ══════════════════════════════════════════════════════════════

def test_bat_buoc_that_reason_null_van_duoc_cham_cong(db, staff):
    """SQLite: "NULL LIKE '...'" -> NULL -> WHEN coi là false -> trigger từng
    không chạy cho đơn thật để trống lý do. Đã sửa bằng "reason IS NOT NULL AND"."""
    lid = _tao_don(db, staff["staff_id"], "2026-09-07", "2026-09-11", "bat_buoc", None)
    _duyet(db, lid)
    rows = _attendances_cua(db, staff["staff_id"])
    assert len(rows) == 5  # 07-11/09/2026 đều là ngày thường (T2-T6)
    assert all(r["symbol"] == "P" for r in rows)


def test_ban_ghi_gia_dieu_chinh_khong_duoc_cham_cong(db, staff):
    lid = _tao_don(
        db, staff["staff_id"], "2026-01-02", "2026-01-15", "bat_buoc",
        "[Điều chỉnh] Đặt số ngày đã dùng = 10 (năm 2026)",
    )
    _duyet(db, lid)
    rows = _attendances_cua(db, staff["staff_id"], "2026-01-01", "2026-02-01")
    assert len(rows) == 0


def test_ban_ghi_gia_import_insert_truc_tiep_khong_duoc_cham_cong(db, staff):
    """Path INSERT trực tiếp status='approved' (leaves.py::_import_quota_apply) —
    trigger AFTER INSERT riêng, không qua UPDATE."""
    _tao_don(
        db, staff["staff_id"], "2026-01-02", "2026-01-20", "bat_buoc",
        "[Import] Tổng hợp 12 ngày đã nghỉ năm 2026 (batch #1)", status="approved",
    )
    rows = _attendances_cua(db, staff["staff_id"], "2026-01-01", "2026-02-01")
    assert len(rows) == 0


# ══════════════════════════════════════════════════════════════
# source_leave_id — huỷ đơn cũ không xoá nhầm dòng của đơn mới (race condition)
# ══════════════════════════════════════════════════════════════

def test_huy_don_cu_khong_xoa_nham_dong_cua_don_moi_chong_ngay(db, staff):
    """Trước khi có source_leave_id: trigger revert xoá theo khớp lại ký hiệu +
    khoảng ngày — 2 đơn chồng đúng 1 ngày cùng ra ký hiệu 'P', huỷ đơn cũ (đã bị
    đơn mới ghi đè) sẽ xoá nhầm dòng của đơn mới. Giờ khớp thẳng theo ID."""
    lid_cu = _tao_don(db, staff["staff_id"], "2026-09-02", "2026-09-02", "personal", "don cu")
    _duyet(db, lid_cu)
    lid_moi = _tao_don(db, staff["staff_id"], "2026-09-02", "2026-09-02", "other", "don moi chong ngay")
    _duyet(db, lid_moi)

    row = db.execute(
        "SELECT source_leave_id FROM attendances WHERE staff_id=? AND date='2026-09-02'",
        (staff["staff_id"],),
    ).fetchone()
    assert row["source_leave_id"] == lid_moi

    db.execute("UPDATE leave_records SET status='cancelled' WHERE id=?", (lid_cu,))
    db.commit()
    row = db.execute(
        "SELECT source_leave_id FROM attendances WHERE staff_id=? AND date='2026-09-02'",
        (staff["staff_id"],),
    ).fetchone()
    assert row is not None and row["source_leave_id"] == lid_moi

    db.execute("UPDATE leave_records SET status='rejected' WHERE id=?", (lid_moi,))
    db.commit()
    row = db.execute(
        "SELECT * FROM attendances WHERE staff_id=? AND date='2026-09-02'",
        (staff["staff_id"],),
    ).fetchone()
    assert row is None


# ══════════════════════════════════════════════════════════════
# is_active — nhân viên ACCT bị vô hiệu hoá không được đồng bộ
# ══════════════════════════════════════════════════════════════

def test_nhan_vien_inactive_khong_duoc_dong_bo(db):
    dept_id = db.execute(
        "INSERT INTO departments (code, name, is_source, is_active) VALUES ('ACCT','Phong Ke toan',1,1)"
    ).lastrowid
    staff_id = db.execute(
        """INSERT INTO user_tttt (employee_code, full_name, role, department_id,
               is_active, username, pwd_hash) VALUES (?,?,?,?,?,?,?)""",
        ("E02", "Nhan Vien Nghi Viec", "chuyen_vien", dept_id, 0, "u_e02", "x"),
    ).lastrowid
    db.commit()
    lid = _tao_don(db, staff_id, "2026-09-07", "2026-09-07", "annual", "test")
    _duyet(db, lid)
    rows = _attendances_cua(db, staff_id)
    assert len(rows) == 0


# ══════════════════════════════════════════════════════════════
# DELETE leave_records — dọn đúng dòng, không để mồ côi
# ══════════════════════════════════════════════════════════════

def test_xoa_thang_leave_records_don_dung_attendances(db, staff):
    lid = _tao_don(
        db, staff["staff_id"], "2026-09-14", "2026-09-14", "annual", "test",
        status="approved",
    )
    assert len(_attendances_cua(db, staff["staff_id"], "2026-09-14", "2026-09-14")) == 1

    db.execute("DELETE FROM leave_records WHERE id=?", (lid,))
    db.commit()
    assert len(_attendances_cua(db, staff["staff_id"], "2026-09-14", "2026-09-14")) == 0
