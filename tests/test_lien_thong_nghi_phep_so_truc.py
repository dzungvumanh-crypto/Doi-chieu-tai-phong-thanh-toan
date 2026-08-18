"""Test hai đường liên thông giữa Nghỉ phép và Sổ trực.

Trước đây hai tính năng này dùng hai bộ dữ liệu song song mà không biết nhau:

  - Ngày lễ: màn hình Nghỉ phép ghi vào `public_holidays`, còn Sổ trực chỉ đọc
    `duty_special_days` → khai ngày lễ xong lịch trực vẫn xếp người trực.
  - Vắng mặt: đơn nghỉ phép đã duyệt nằm ở `leave_records`, còn Sổ trực chỉ đọc
    `duty_absences` → người được duyệt nghỉ vẫn bị xếp trực.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_lien_thong_nghi_phep_so_truc.py -v
"""

import sqlite3

import pytest

from backend.services.duty_constraint_service import get_holiday_dates
from backend.services.duty_staff_service import get_absences, get_available_pool

_SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY, code TEXT, name TEXT);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY, full_name TEXT, role TEXT,
    department_id INTEGER, is_active INTEGER DEFAULT 1, is_deleted INTEGER DEFAULT 0
);
CREATE TABLE duty_staff_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE,
    can_do_sp INTEGER DEFAULT 0, is_sp_backup INTEGER DEFAULT 0,
    is_on_project INTEGER DEFAULT 0, display_order INTEGER DEFAULT 999, created_at DATETIME
);
CREATE TABLE duty_absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id INTEGER,
    absence_date DATE, created_at DATETIME, UNIQUE(staff_id, absence_date)
);
CREATE TABLE duty_special_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE UNIQUE, day_type TEXT,
    label TEXT, is_confirmed INTEGER DEFAULT 0, created_at DATETIME
);
CREATE TABLE public_holidays (id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE UNIQUE, name TEXT);
CREATE TABLE leave_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id INTEGER,
    start_date DATE, end_date DATE, status TEXT DEFAULT 'pending_ksv'
);
"""


@pytest.fixture
def db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    c.execute("INSERT INTO departments (id, code, name) VALUES (1, 'PAYMENT', 'Phòng Thanh toán')")
    for sid, ten, vai in ((1, "LD Một", "truong_phong"), (2, "NV Hai", "chuyen_vien"),
                          (3, "NV Ba", "chuyen_vien")):
        c.execute("INSERT INTO user_tttt (id, full_name, role, department_id) VALUES (?,?,?,1)",
                  (sid, ten, vai))
        c.execute("INSERT INTO duty_staff_meta (user_id, display_order) VALUES (?,?)", (sid, sid))
    c.commit()
    yield c
    c.close()


# ── Ngày lễ ──────────────────────────────────────────────────────────────────

def test_ngay_le_khai_o_man_hinh_nghi_phep_thi_so_truc_thay(db):
    db.execute("INSERT INTO public_holidays (date, name) VALUES ('2026-09-02', 'Quốc khánh')")
    db.commit()
    assert "2026-09-02" in get_holiday_dates(db, 2026)


def test_van_lay_ngay_le_khai_rieng_trong_so_truc(db):
    db.execute("INSERT INTO duty_special_days (date, day_type, label) "
               "VALUES ('2026-03-05', 'holiday', 'Nghỉ riêng')")
    db.commit()
    assert "2026-03-05" in get_holiday_dates(db, 2026)


def test_khai_ngay_bu_trong_so_truc_thang_ngay_le_chung(db):
    """Nhà nước hoán đổi: ngày lễ chung nhưng cơ quan khai đi làm bù.
    Khai báo riêng của Sổ trực phải thắng, nếu không engine nhận hai câu trả lời
    trái nhau cho cùng một ngày."""
    db.execute("INSERT INTO public_holidays (date, name) VALUES ('2026-04-30', 'Giải phóng')")
    db.execute("INSERT INTO duty_special_days (date, day_type, label, is_confirmed) "
               "VALUES ('2026-04-30', 'makeup', 'Đi làm bù', 1)")
    db.commit()
    assert "2026-04-30" not in get_holiday_dates(db, 2026)


def test_khong_lay_ngay_le_cua_nam_khac(db):
    db.execute("INSERT INTO public_holidays (date, name) VALUES ('2025-09-02', 'Quốc khánh')")
    db.commit()
    assert get_holiday_dates(db, 2026) == set()


# ── Vắng mặt ─────────────────────────────────────────────────────────────────

def test_don_nghi_phep_da_duyet_thi_khong_bi_xep_truc(db):
    db.execute("INSERT INTO leave_records (staff_id, start_date, end_date, status) "
               "VALUES (2, '2026-08-10', '2026-08-12', 'approved')")
    db.commit()
    assert 2 in get_absences(db, "2026-08-11")
    ids = [p["id"] for p in get_available_pool(db, "2026-08-11")["NV"]]
    assert 2 not in ids and 3 in ids


def test_don_chua_duyet_thi_van_xep_truc_binh_thuong(db):
    """Chỉ đơn ĐÃ DUYỆT mới loại người khỏi lịch — đơn còn chờ duyệt thì chưa
    chắc được nghỉ, loại sớm là thiếu người trực."""
    for tt in ("pending_ksv", "pending_gd", "rejected", "cancelled"):
        db.execute("DELETE FROM leave_records")
        db.execute("INSERT INTO leave_records (staff_id, start_date, end_date, status) "
                   "VALUES (2, '2026-08-10', '2026-08-12', ?)", (tt,))
        db.commit()
        assert 2 not in get_absences(db, "2026-08-11"), tt


def test_ngoai_khoang_don_phep_thi_khong_tinh_la_vang(db):
    db.execute("INSERT INTO leave_records (staff_id, start_date, end_date, status) "
               "VALUES (2, '2026-08-10', '2026-08-12', 'approved')")
    db.commit()
    assert 2 not in get_absences(db, "2026-08-13")


def test_hai_nguon_vang_mat_khong_de_len_nhau(db):
    """Khai tay và đơn phép cùng tồn tại: mỗi người vẫn ra đúng lý do của mình."""
    db.execute("INSERT INTO duty_absences (staff_id, absence_date) VALUES (3, '2026-08-11')")
    db.execute("INSERT INTO leave_records (staff_id, start_date, end_date, status) "
               "VALUES (2, '2026-08-11', '2026-08-11', 'approved')")
    db.commit()
    ly_do = get_absences(db, "2026-08-11")
    assert set(ly_do) == {2, 3}
    assert "khai" in ly_do[3]
    assert "phép" in ly_do[2]
