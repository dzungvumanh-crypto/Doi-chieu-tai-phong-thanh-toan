"""
Test thuật toán phân lịch trực — ca ngày thường / thứ 6.

Quy tắc nghiệp vụ được kiểm tra:
  1. Mỗi ca bắt buộc 1 Lãnh đạo + 2 người (tổng 3).
  2. Trong ca chỉ ĐÚNG 1 người xử lý song phương (Lãnh đạo hoặc nhân viên).
  3. Ngày thường bốc ngẫu nhiên trong nhóm ít ca nhất; thứ 6 luân phiên tất định.
  4. Người đi dự án / vắng mặt không được phân.
"""
import random
import sqlite3

import pytest

from backend.services import duty_scheduler_engine as eng
from backend.services.duty_scheduler_engine import (
    _generate_normal_or_friday, generate_schedule_for_week,
)

# ── Schema tối thiểu ──────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE departments (
    id INTEGER PRIMARY KEY, code TEXT, name TEXT
);
CREATE TABLE user_tttt (
    id INTEGER PRIMARY KEY, full_name TEXT, role TEXT,
    department_id INTEGER, is_active INTEGER DEFAULT 1, is_deleted INTEGER DEFAULT 0
);
CREATE TABLE duty_staff_meta (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE,
    can_do_sp INTEGER DEFAULT 0, is_sp_backup INTEGER DEFAULT 0,
    is_on_project INTEGER DEFAULT 0, display_order INTEGER DEFAULT 999,
    created_at DATETIME
);
CREATE TABLE duty_absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id INTEGER,
    absence_date DATE, created_at DATETIME, UNIQUE(staff_id, absence_date)
);
CREATE TABLE duty_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id INTEGER, request_type TEXT,
    specific_date DATE, day_of_week INTEGER, year INTEGER,
    is_active INTEGER DEFAULT 1, created_at DATETIME
);
CREATE TABLE duty_special_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE UNIQUE, day_type TEXT,
    label TEXT, is_confirmed INTEGER DEFAULT 0, created_at DATETIME
);
CREATE TABLE duty_rotation_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, role TEXT, staff_id INTEGER,
    shift_count INTEGER DEFAULT 0, last_used DATE, position INTEGER DEFAULT 0,
    UNIQUE(year, role, staff_id)
);
CREATE TABLE duty_shifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, shift_date DATE, shift_type TEXT,
    leader_id INTEGER, sp_id INTEGER, sp_warning TEXT, nv_ids TEXT DEFAULT '[]',
    nv_count INTEGER DEFAULT 0, is_auto INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft', created_at DATETIME, UNIQUE(shift_date, shift_type)
);
CREATE TABLE duty_shift_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER UNIQUE,
    nv_count INTEGER DEFAULT 2, signer_name TEXT
);
"""

# Ngày mẫu: 2026-08-10 là thứ 2, 2026-08-14 là thứ 6
MONDAY = "2026-08-10"
FRIDAY = "2026-08-14"
YEAR = 2026


def _make_db(staff: list[tuple]) -> sqlite3.Connection:
    """staff: (id, full_name, role, can_do_sp, is_on_project, display_order)"""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    db.execute("INSERT INTO departments (id, code, name) VALUES (1,'PAYMENT','Phòng Thanh toán')")
    for sid, name, role, can_sp, on_proj, order in staff:
        db.execute(
            "INSERT INTO user_tttt (id, full_name, role, department_id) VALUES (?,?,?,1)",
            (sid, name, role),
        )
        db.execute(
            "INSERT INTO duty_staff_meta (user_id, can_do_sp, is_on_project, display_order) VALUES (?,?,?,?)",
            (sid, can_sp, on_proj, order),
        )
    db.execute("INSERT INTO duty_shift_config (year, nv_count) VALUES (?, 2)", (YEAR,))
    db.commit()
    return db


def _standard_staff() -> list[tuple]:
    """2 LD (1 làm SP) + 6 NV (2 làm SP)."""
    return [
        (1, "LD Một", "truong_phong", 1, 0, 1),   # LD làm được SP
        (2, "LD Hai", "pho_phong",    0, 0, 2),
        (3, "NV Ba",   "chuyen_vien", 1, 0, 3),   # NV làm được SP
        (4, "NV Bốn",  "chuyen_vien", 1, 0, 4),   # NV làm được SP
        (5, "NV Năm",  "chuyen_vien", 0, 0, 5),
        (6, "NV Sáu",  "chuyen_vien", 0, 0, 6),
        (7, "NV Bảy",  "chuyen_vien", 0, 0, 7),
        (8, "NV Tám",  "chuyen_vien", 0, 0, 8),
    ]


def _members(shift: dict) -> list[int]:
    """Toàn bộ id người trong ca, kể cả Lãnh đạo."""
    import json
    ids = []
    if shift["leader_id"]:
        ids.append(shift["leader_id"])
    if shift["sp_id"]:
        ids.append(shift["sp_id"])
    ids.extend(json.loads(shift["nv_ids"]))
    return ids


def _sp_capable_ids(db) -> set:
    rows = db.execute("SELECT user_id FROM duty_staff_meta WHERE can_do_sp=1").fetchall()
    return {r["user_id"] for r in rows}


def _gen_one(db, date_str: str, seed: int, shift_type: str = "normal") -> dict:
    """shift=None nghĩa là không lập được ca (vi phạm luật cứng 1 LD + 2 NV)."""
    ld_role, nv_role = ("LD", "NV") if shift_type == "normal" else ("LD_friday", "NV_friday")
    shifts, warns = _generate_normal_or_friday(
        db, date_str, YEAR, ld_role, nv_role, shift_type, random.Random(seed)
    )
    return {"shift": shifts[0] if shifts else None, "warnings": warns}


# ══════════════════════════════════════════════════════════════
# 1. Cấu trúc ca: đủ 3 người
# ══════════════════════════════════════════════════════════════

def test_ca_ngay_thuong_luon_du_ba_nguoi():
    for seed in range(20):
        db = _make_db(_standard_staff())
        r = _gen_one(db, MONDAY, seed)
        assert len(_members(r["shift"])) == 3, f"seed={seed} không đủ 3 người"
        assert r["shift"]["leader_id"] is not None
        assert r["warnings"] == []


def test_ca_thu_sau_luon_du_ba_nguoi():
    db = _make_db(_standard_staff())
    r = _gen_one(db, FRIDAY, 0, shift_type="friday")
    assert len(_members(r["shift"])) == 3
    assert r["shift"]["shift_type"] == "friday"


# ══════════════════════════════════════════════════════════════
# 2. Đúng 1 người xử lý song phương
# ══════════════════════════════════════════════════════════════

def test_moi_ca_chi_co_dung_mot_nguoi_song_phuong():
    for seed in range(30):
        db = _make_db(_standard_staff())
        sp_ids = _sp_capable_ids(db)
        r = _gen_one(db, MONDAY, seed)
        in_shift = [i for i in _members(r["shift"]) if i in sp_ids]
        assert len(in_shift) == 1, f"seed={seed} có {len(in_shift)} người SP, cần đúng 1"


def test_thu_sau_cung_giu_dung_mot_nguoi_song_phuong():
    db = _make_db(_standard_staff())
    sp_ids = _sp_capable_ids(db)
    r = _gen_one(db, FRIDAY, 0, shift_type="friday")
    assert len([i for i in _members(r["shift"]) if i in sp_ids]) == 1


def test_lanh_dao_lam_sp_thi_hai_nguoi_con_lai_khong_lam_sp():
    """Chỉ có 1 LD và LD đó làm được SP → LD kiêm SP, 2 NV còn lại phải non-SP."""
    staff = [
        (1, "LD Một", "truong_phong", 1, 0, 1),
        (3, "NV Ba",  "chuyen_vien",  1, 0, 3),
        (5, "NV Năm", "chuyen_vien",  0, 0, 5),
        (6, "NV Sáu", "chuyen_vien",  0, 0, 6),
    ]
    for seed in range(10):
        db = _make_db(staff)
        r = _gen_one(db, MONDAY, seed)
        s = r["shift"]
        assert s["leader_id"] == 1
        assert s["sp_id"] is None, "LD kiêm SP thì không gán SP riêng"
        assert s["sp_warning"] == "leader_sp"
        assert sorted(_members(s)) == [1, 5, 6], "hai người còn lại phải là NV không làm SP"


def test_nhan_vien_lam_sp_khi_lanh_dao_khong_lam_duoc():
    staff = [
        (2, "LD Hai", "pho_phong",   0, 0, 2),
        (3, "NV Ba",  "chuyen_vien", 1, 0, 3),
        (5, "NV Năm", "chuyen_vien", 0, 0, 5),
        (6, "NV Sáu", "chuyen_vien", 0, 0, 6),
    ]
    db = _make_db(staff)
    r = _gen_one(db, MONDAY, 0)
    s = r["shift"]
    assert s["leader_id"] == 2
    assert s["sp_id"] == 3
    assert s["sp_warning"] is None
    assert len(_members(s)) == 3


# ══════════════════════════════════════════════════════════════
# 3. Ngẫu nhiên (ngày thường) vs luân phiên tất định (thứ 6)
# ══════════════════════════════════════════════════════════════

def test_ngay_thuong_bo_c_ngau_nhien_khong_lap_lai_mot_ket_qua():
    ket_qua = set()
    for seed in range(30):
        db = _make_db(_standard_staff())
        ket_qua.add(tuple(sorted(_members(_gen_one(db, MONDAY, seed)["shift"]))))
    assert len(ket_qua) > 1, "ngày thường phải ngẫu nhiên, không ra cùng một tổ hợp"


def test_thu_sau_tat_dinh_khong_phu_thuoc_seed():
    ket_qua = set()
    for seed in range(30):
        db = _make_db(_standard_staff())
        r = _gen_one(db, FRIDAY, seed, shift_type="friday")
        ket_qua.add(tuple(sorted(_members(r["shift"]))))
    assert len(ket_qua) == 1, "thứ 6 luân phiên tất định — seed không được ảnh hưởng"


def test_ngau_nhien_van_can_bang_so_ca():
    """Bốc trong nhóm ít ca nhất → chênh lệch số ca giữa các NV phải nhỏ."""
    db = _make_db(_standard_staff())
    # 4 tuần liên tiếp của tháng 8/2026
    for ws in ("2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24"):
        generate_schedule_for_week(db, ws, seed=42)

    rows = db.execute(
        "SELECT staff_id, shift_count FROM duty_rotation_state WHERE year=? AND role='NV'",
        (YEAR,),
    ).fetchall()
    counts = [r["shift_count"] for r in rows]
    assert counts, "phải có dữ liệu vòng xoay"
    assert max(counts) - min(counts) <= 2, f"lệch ca quá lớn: {sorted(counts)}"


# ══════════════════════════════════════════════════════════════
# 4. Loại người không khả dụng
# ══════════════════════════════════════════════════════════════

def test_nguoi_di_du_an_khong_bao_gio_duoc_phan():
    staff = _standard_staff()
    staff[4] = (5, "NV Năm", "chuyen_vien", 0, 1, 5)   # đi dự án
    for seed in range(20):
        db = _make_db(staff)
        assert 5 not in _members(_gen_one(db, MONDAY, seed)["shift"])


def test_nguoi_vang_mat_khong_duoc_phan_ngay_do():
    for seed in range(20):
        db = _make_db(_standard_staff())
        db.execute(
            "INSERT INTO duty_absences (staff_id, absence_date) VALUES (6, ?)", (MONDAY,)
        )
        db.commit()
        assert 6 not in _members(_gen_one(db, MONDAY, seed)["shift"])


# ══════════════════════════════════════════════════════════════
# 5. Khi không đủ người — ưu tiên đủ 3 người + cảnh báo
# ══════════════════════════════════════════════════════════════

def test_thieu_nguoi_non_sp_van_du_ba_nguoi_va_canh_bao_multi_sp():
    """Pool toàn người làm được SP → không tách được, vẫn phải đủ 3 người."""
    staff = [
        (2, "LD Hai", "pho_phong",   0, 0, 2),
        (3, "NV Ba",  "chuyen_vien", 1, 0, 3),
        (4, "NV Bốn", "chuyen_vien", 1, 0, 4),
    ]
    db = _make_db(staff)
    r = _gen_one(db, MONDAY, 0)
    assert len(_members(r["shift"])) == 3
    assert r["shift"]["sp_warning"] == "multi_sp"
    assert any(w["type"] == "multi_sp" for w in r["warnings"])


def test_khong_ai_lam_sp_thi_canh_bao_no_sp():
    staff = [
        (2, "LD Hai", "pho_phong",   0, 0, 2),
        (5, "NV Năm", "chuyen_vien", 0, 0, 5),
        (6, "NV Sáu", "chuyen_vien", 0, 0, 6),
    ]
    db = _make_db(staff)
    r = _gen_one(db, MONDAY, 0)
    assert len(_members(r["shift"])) == 3
    assert r["shift"]["sp_warning"] == "no_sp"
    assert any(w["type"] == "no_sp" for w in r["warnings"])


def test_thieu_nhan_vien_thi_khong_hinh_thanh_ca():
    """Luật cứng: thà không có ca còn hơn có ca 2 người."""
    staff = [
        (2, "LD Hai", "pho_phong",   0, 0, 2),
        (3, "NV Ba",  "chuyen_vien", 1, 0, 3),
    ]
    db = _make_db(staff)
    r = _gen_one(db, MONDAY, 0)
    assert r["shift"] is None, "không đủ 2 nhân viên thì không được lập ca"
    assert any(w["type"] == "khong_du_nguoi" for w in r["warnings"])


def test_khong_co_lanh_dao_thi_khong_hinh_thanh_ca():
    staff = [
        (3, "NV Ba",  "chuyen_vien", 1, 0, 3),
        (5, "NV Năm", "chuyen_vien", 0, 0, 5),
        (6, "NV Sáu", "chuyen_vien", 0, 0, 6),
    ]
    db = _make_db(staff)
    r = _gen_one(db, MONDAY, 0)
    assert r["shift"] is None, "không có Lãnh đạo thì không được lập ca"
    assert any(w["type"] == "khong_du_nguoi" for w in r["warnings"])


def test_thieu_nguoi_thi_khong_ghi_vong_xoay():
    """Ca không hình thành thì không ai được tính số ca."""
    staff = [
        (2, "LD Hai", "pho_phong",   0, 0, 2),
        (3, "NV Ba",  "chuyen_vien", 1, 0, 3),
    ]
    db = _make_db(staff)
    _gen_one(db, MONDAY, 0)
    tong = db.execute(
        "SELECT COALESCE(SUM(shift_count),0) AS t FROM duty_rotation_state WHERE year=?", (YEAR,)
    ).fetchone()["t"]
    assert tong == 0, f"ca không lập được nhưng vẫn ghi {tong} lượt trực"


# ══════════════════════════════════════════════════════════════
# 6. Đăng ký xin trực & không lặp người trong tuần
# ══════════════════════════════════════════════════════════════

def test_dang_ky_dich_danh_ngay_duoc_uu_tien_tuyet_doi():
    """Đăng ký 'once' ép cứng — phải có mặt bất kể vòng xoay/ngẫu nhiên."""
    for seed in range(20):
        db = _make_db(_standard_staff())
        db.execute(
            "INSERT INTO duty_requests (staff_id, request_type, specific_date, year, is_active) "
            "VALUES (8, 'once', ?, ?, 1)", (MONDAY, YEAR)
        )
        db.commit()
        assert 8 in _members(_gen_one(db, MONDAY, seed)["shift"])


def test_ca_trong_tuan_luon_dung_mot_lanh_dao_va_hai_nhan_vien():
    """Cấu trúc cứng: không ca nào được có 2 Lãnh đạo hay 3 nhân viên."""
    for seed in (7, 11, 23, 99):
        db = _make_db(_standard_staff())
        generate_schedule_for_week(db, MONDAY, seed=seed)

        rows = db.execute("SELECT * FROM duty_shifts ORDER BY shift_date").fetchall()
        assert len(rows) == 5, "tuần làm việc phải có 5 ca"

        vai = dict(db.execute(
            "SELECT id, CASE WHEN role IN ('truong_phong','pho_phong') THEN 'LD' ELSE 'NV' END "
            "FROM user_tttt"
        ).fetchall())
        for r in rows:
            ids = _members(dict(r))
            so_ld = sum(1 for i in ids if vai[i] == "LD")
            so_nv = sum(1 for i in ids if vai[i] == "NV")
            assert (so_ld, so_nv) == (1, 2), (
                f"seed={seed} ngày {r['shift_date']}: {so_ld} LD + {so_nv} NV, cần 1 LD + 2 NV"
            )


def test_uu_tien_nguoi_chua_truc_trong_tuan():
    """Pool 8 người / 5 ca — ai cũng phải được dùng ít nhất 1 lần."""
    db = _make_db(_standard_staff())
    generate_schedule_for_week(db, MONDAY, seed=7)

    rows = db.execute("SELECT * FROM duty_shifts").fetchall()
    da_truc: set = set()
    for r in rows:
        da_truc.update(_members(dict(r)))
    chua_truc = {s[0] for s in _standard_staff()} - da_truc
    assert not chua_truc, f"còn người chưa được phân ca nào trong tuần: {chua_truc}"


def test_ghi_vong_xoay_dung_so_nguoi_duoc_chon():
    """Ứng viên bị loại trong lúc thử tổ hợp không được cộng số ca."""
    db = _make_db(_standard_staff())
    _gen_one(db, MONDAY, 0)
    tong = db.execute(
        "SELECT COALESCE(SUM(shift_count),0) AS t FROM duty_rotation_state WHERE year=?", (YEAR,)
    ).fetchone()["t"]
    assert tong == 3, f"1 ca = 3 lượt trực, nhưng ghi nhận {tong}"
