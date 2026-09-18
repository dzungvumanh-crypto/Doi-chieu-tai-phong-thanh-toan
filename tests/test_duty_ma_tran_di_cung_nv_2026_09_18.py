"""
B7 — Test đơn vị cho _ma_tran_di_cung_nv() (backend/services/duty_scheduler_engine.py).
Xem pipeline/PLAN.md mục 3 + mục 5 (bảng B7). Thuần đọc — chưa nối vào đường
chọn người (nối ở B9).
"""
import sqlite3

from backend.services.duty_scheduler_engine import _ma_tran_di_cung_nv

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


def _them_ca(db, date_str, nv_ids, sp_id=None, nv_phu_ids=None):
    import json
    db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, nv_ids, sp_id, nv_phu_ids) "
        "VALUES (?,?,?,?,?)",
        (date_str, "normal", json.dumps(nv_ids), sp_id, json.dumps(nv_phu_ids or [])),
    )
    db.commit()


def _cap(a, b):
    return (min(a, b), max(a, b))


def test_dem_dung_cap_trong_nhom_truc_chinh():
    """3 ca: (11,12) chính; (11,13) chính + 12 trực phụ (không tính); (12) chính
    + sp_id=13 (13 gia nhập nhóm chính qua vai song phương)."""
    db = _db()
    _them_ca(db, "2026-08-04", [11, 12])
    _them_ca(db, "2026-08-05", [11, 13], nv_phu_ids=[12])
    _them_ca(db, "2026-08-06", [12], sp_id=13)

    dem = _ma_tran_di_cung_nv(db, 2026)
    assert dem.get(_cap(11, 12)) == 1, "chỉ ca 04/08 có (11,12) cùng nhóm chính"
    assert dem.get(_cap(11, 13)) == 1, "ca 05/08: (11,13) cùng nhóm chính"
    assert dem.get(_cap(12, 13)) == 1, "ca 06/08: sp_id nhập nhóm chính cùng nv_ids"


def test_khong_tinh_nv_phu_ids_q4():
    """NV12 chỉ xuất hiện ở nv_phu_ids của ca 05/08 — KHÔNG được tính là 'đi
    cùng' NV11/NV13 dù cùng có mặt trong ca (Q4: trực phụ không tính)."""
    db = _db()
    _them_ca(db, "2026-08-05", [11, 13], nv_phu_ids=[12])

    dem = _ma_tran_di_cung_nv(db, 2026)
    assert _cap(11, 12) not in dem, "trực phụ không được tính là đi cùng (Q4)"
    assert _cap(12, 13) not in dem, "trực phụ không được tính là đi cùng (Q4)"
    assert dem.get(_cap(11, 13)) == 1


def test_chi_dem_dung_nam():
    db = _db()
    _them_ca(db, "2026-08-04", [11, 12])
    _them_ca(db, "2025-08-04", [11, 12])

    dem_2026 = _ma_tran_di_cung_nv(db, 2026)
    dem_2025 = _ma_tran_di_cung_nv(db, 2025)
    assert dem_2026.get(_cap(11, 12)) == 1
    assert dem_2025.get(_cap(11, 12)) == 1


def test_cong_don_nhieu_ca():
    db = _db()
    for d in ("2026-08-04", "2026-08-11", "2026-08-18"):
        _them_ca(db, d, [11, 12])

    dem = _ma_tran_di_cung_nv(db, 2026)
    assert dem.get(_cap(11, 12)) == 3
