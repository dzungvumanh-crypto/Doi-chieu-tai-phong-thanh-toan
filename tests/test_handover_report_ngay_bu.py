"""`compute_period` phải thấy ngày làm bù khai ở màn Phân lịch trực.

Đây là test đi qua đúng SQL thật của báo cáo, không chỉ hàm đếm ngày: cùng một
bộ chứng từ, chỉ thêm một dòng `duty_special_days` loại 'makeup' là kết quả
đúng hạn / quá hạn phải đổi.
"""
import sqlite3

import pytest

from backend.services.handover_report_service import compute_period

# Tháng 01/2026 — 02/01 thứ Sáu, 03/01 thứ Bảy, 05/01 thứ Hai
NGAY_GD = "2026-01-02"
NGAY_NOP = "2026-01-05 08:30:00"
T7 = "2026-01-03"

SCHEMA = """
CREATE TABLE departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    is_source BOOLEAN DEFAULT 1,
    is_active BOOLEAN DEFAULT 1);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code VARCHAR(20), full_name VARCHAR(100),
    username VARCHAR(50), ipcas_code VARCHAR(20), payment_username VARCHAR(50));
CREATE TABLE handovers (
    id INTEGER NOT NULL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    handover_date DATE NOT NULL,
    received_by_id INTEGER REFERENCES user_tttt(id));
CREATE TABLE document_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handover_id INTEGER NOT NULL REFERENCES handovers(id),
    transaction_date DATE NOT NULL,
    sheet_count INTEGER NOT NULL,
    staff_id INTEGER REFERENCES user_tttt(id));
CREATE TABLE entry_change_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL REFERENCES document_entries(id),
    action TEXT NOT NULL,
    performed_by_id INTEGER,
    timestamp DATETIME);
CREATE TABLE leave_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL,
    start_date DATE NOT NULL, end_date DATE NOT NULL,
    reason TEXT, status TEXT);
CREATE TABLE public_holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE NOT NULL UNIQUE, name TEXT NOT NULL);
CREATE TABLE duty_special_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE UNIQUE NOT NULL,
    day_type VARCHAR(20) NOT NULL
        CHECK(day_type IN ('holiday','cutoff','settlement','makeup')),
    label VARCHAR(100), is_confirmed BOOLEAN DEFAULT 0, created_at DATETIME);
"""


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO departments (id, code, name) VALUES (1,'KHDN','Phòng KHDN')")
    conn.execute(
        "INSERT INTO user_tttt (id, employee_code, full_name, username) "
        "VALUES (9,'NV09','Nguyễn Văn A','nva')"
    )
    conn.execute(
        "INSERT INTO handovers (id, department_id, handover_date, received_by_id) "
        "VALUES (1, 1, ?, 9)", (NGAY_GD,)
    )
    conn.execute(
        "INSERT INTO document_entries (id, handover_id, transaction_date, sheet_count, staff_id) "
        "VALUES (1, 1, ?, 10, 9)", (NGAY_GD,)
    )
    conn.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, timestamp) "
        "VALUES (1, 'handover', 9, ?)", (NGAY_NOP,)
    )
    conn.commit()
    yield conn
    conn.close()


def _lam_bu(db, ngay=T7, xac_nhan=1):
    db.execute(
        "INSERT INTO duty_special_days (date, day_type, is_confirmed) VALUES (?,'makeup',?)",
        (ngay, xac_nhan),
    )
    db.commit()


def test_khong_khai_ngay_bu_thi_dung_han(db):
    """GD thứ Sáu, nộp thứ Hai — T7/CN không tính, cách đúng 1 ngày làm việc."""
    kq = compute_period(db, 2026, 1)
    assert kq["overall"] == {"total": 1, "on_time": 1, "late": 0, "rate": 100.0}


def test_khai_ngay_bu_thi_qua_han(db):
    _lam_bu(db)
    kq = compute_period(db, 2026, 1)
    assert kq["overall"]["late"] == 1
    assert kq["late_entries"][0]["days_late"] == 1


def test_ngay_bu_chua_xac_nhan_khong_doi_ket_qua(db):
    _lam_bu(db, xac_nhan=0)
    assert compute_period(db, 2026, 1)["overall"]["on_time"] == 1


def test_nghi_phep_trung_ngay_bu_van_duoc_tru(db):
    """Người nhận nghỉ phép đã duyệt đúng thứ Bảy làm bù → ngày đó không tính vào hạn.

    Nếu không loại, ngày ấy vừa đòi nộp chứng từ vừa không thừa nhận là họ đang nghỉ.
    """
    _lam_bu(db)
    db.execute(
        "INSERT INTO leave_records (staff_id, start_date, end_date, reason, status) "
        "VALUES (9, ?, ?, 'Việc riêng', 'approved')", (T7, T7)
    )
    db.commit()
    assert compute_period(db, 2026, 1)["overall"]["on_time"] == 1


def test_ngay_le_khai_ben_so_truc_noi_han_nop(db):
    """Ngày lễ chỉ khai ở Sổ trực (không có trong public_holidays) vẫn phải được tính."""
    db.execute(
        "INSERT INTO duty_special_days (date, day_type, is_confirmed) "
        "VALUES ('2026-01-05','holiday',1)"
    )
    db.execute(
        "UPDATE entry_change_logs SET timestamp = '2026-01-06 08:30:00' WHERE entry_id = 1"
    )
    db.commit()
    assert compute_period(db, 2026, 1)["overall"]["on_time"] == 1
