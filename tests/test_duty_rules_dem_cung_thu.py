"""
B1 — Test đơn vị cho dem_cung_thu_trong_thang() / nguoi_truc_cung_thu_tuan_truoc()
(backend/services/duty_rules.py). Xem pipeline/PLAN.md mục 1 + mục 5 (bảng B1).
"""
import sqlite3

from backend.services.duty_rules import (
    dem_cung_thu_trong_thang, nguoi_truc_cung_thu_tuan_truoc,
    dem_thu6_trong_thang, nguoi_truc_thu6_tuan_truoc,
)

_SCHEMA = """
CREATE TABLE duty_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, shift_date DATE, shift_type TEXT,
    leader_ids TEXT DEFAULT '[]', sp_id INTEGER, nv_ids TEXT DEFAULT '[]',
    nv_phu_ids TEXT DEFAULT '[]', status TEXT DEFAULT 'confirmed'
);
"""


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    return db


def _them_ca(db, date_str, shift_type, leader_ids, nv_ids):
    import json
    db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_ids, nv_ids) VALUES (?,?,?,?)",
        (date_str, shift_type, json.dumps(leader_ids), json.dumps(nv_ids)),
    )
    db.commit()


def test_dem_cung_thu_trong_thang_dung_thu_moi_tinh():
    """3 thứ Ba trong tháng 8/2026: 04, 11, 18 — đếm 2 ca TRƯỚC ngày 18 (04, 11),
    không tính chính ca 18 đang xét."""
    db = _db()
    _them_ca(db, "2026-08-04", "normal", [2], [1, 3])   # thứ Ba
    _them_ca(db, "2026-08-11", "normal", [2], [1, 4])   # thứ Ba
    _them_ca(db, "2026-08-05", "normal", [2], [1, 9])   # thứ Tư — KHÁC thứ, không tính

    dem = dem_cung_thu_trong_thang(db, "2026-08-18", "normal")
    assert dem.get(1) == 2, f"NV1 trực đúng 2 thứ Ba trước đó, đang đếm {dem.get(1)}"
    assert dem.get(2) == 2, f"LD2 trực đúng 2 thứ Ba trước đó, đang đếm {dem.get(2)}"
    assert 9 not in dem, "ca thứ Tư (khác thứ) không được tính vào"


def test_dem_cung_thu_trong_thang_loc_dung_shift_type():
    """Ca cut-off rơi đúng thứ Ba KHÔNG được tính vào luật của ca 'normal' (Q1)."""
    db = _db()
    _them_ca(db, "2026-08-04", "cutoff", [2], [1, 3])   # thứ Ba nhưng là cut-off
    _them_ca(db, "2026-08-11", "normal", [2], [1, 4])   # thứ Ba, đúng loại

    dem = dem_cung_thu_trong_thang(db, "2026-08-18", "normal")
    assert dem.get(1) == 1, "chỉ ca 'normal' đúng thứ Ba mới được đếm, cut-off phải bị loại"
    assert dem.get(3) is None, "người chỉ xuất hiện ở ca cut-off không được tính"


def test_nguoi_truc_cung_thu_tuan_truoc_dung_7_ngay():
    db = _db()
    _them_ca(db, "2026-08-11", "normal", [2], [1, 4])   # đúng 7 ngày trước 18/08
    _them_ca(db, "2026-08-04", "normal", [2], [1, 9])   # 14 ngày trước — không tính

    tuan_truoc = nguoi_truc_cung_thu_tuan_truoc(db, "2026-08-18", "normal")
    assert tuan_truoc == {2, 1, 4}
    assert 9 not in tuan_truoc


def test_thu6_la_vo_mong_goi_lai_ham_chung():
    """dem_thu6_trong_thang / nguoi_truc_thu6_tuan_truoc phải cho kết quả giống
    hệt gọi trực tiếp hàm chung với shift_type='friday' — giữ tên cũ nhưng
    không được lệch hành vi (hành vi thứ 6 phải nguyên vẹn)."""
    db = _db()
    _them_ca(db, "2026-08-07", "friday", [1], [11, 12])
    _them_ca(db, "2026-08-14", "friday", [1], [11, 13])

    assert dem_thu6_trong_thang(db, "2026-08-21") == \
        dem_cung_thu_trong_thang(db, "2026-08-21", "friday")
    assert nguoi_truc_thu6_tuan_truoc(db, "2026-08-21") == \
        nguoi_truc_cung_thu_tuan_truoc(db, "2026-08-21", "friday")
    assert nguoi_truc_thu6_tuan_truoc(db, "2026-08-21") == {1, 11, 13}
