"""
B0 — Test tái hiện 4 bất cập trong pipeline/PLAN.md (2026-09-18), chạy trên mã
CHƯA sửa để xác nhận chẩn đoán đúng trước khi coder sửa gì.

  1. Bất cập 2a  — `_chon_lanh_dao()` phá tầng tránh lặp khi kéo người SP.
  2. Bất cập 2b/4b — `_chia_nhan_vien()` phá tầng tránh lặp khi kéo người SP.
  3. Bất cập 3   — `_so_lan_di_cung()` không đếm NV-NV, sinh ê-kíp cố định.
  4. Luật tránh lặp thứ chỉ áp cho thứ 6 — lặp cùng thứ Ba nhiều tuần liền
     không bị chặn (mở rộng T2→T6 chưa có).

4 test này PHẢI FAIL trên mã chưa sửa (dùng các trạng thái mong muốn SAU khi
sửa làm assertion). Sau B1-B6, test 1/2/4 phải chuyển XANH; test 3 (bất cập 3,
thuộc B7-B9 — giai đoạn 2, KHÔNG làm trong đợt này) vẫn ĐỎ, ghi rõ trong
CODE_REPORT.md.
"""
import random
import sqlite3

from backend.services.duty_scheduler_engine import _generate_ca

# ── Schema tối thiểu — giống hệt tests/test_duty_scheduler_algorithm.py ──────
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
    leader_id INTEGER, leader_ids TEXT DEFAULT '[]',
    sp_id INTEGER, sp_warning TEXT, nv_ids TEXT DEFAULT '[]',
    nv_count INTEGER DEFAULT 0, nv_phu_ids TEXT DEFAULT '[]', nv_phu_count INTEGER DEFAULT 0,
    is_auto INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft', created_at DATETIME, UNIQUE(shift_date, shift_type)
);
CREATE TABLE duty_shift_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER UNIQUE,
    ld_count INTEGER DEFAULT 1, nv_count INTEGER DEFAULT 2,
    qt_ld_count INTEGER DEFAULT 1, qt_nv_chinh_count INTEGER DEFAULT 3,
    qt_nv_phu_count INTEGER DEFAULT 2, signer_name TEXT, signer_title TEXT
);
CREATE TABLE public_holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE UNIQUE, name TEXT
);
CREATE TABLE leave_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, staff_id INTEGER,
    start_date DATE, end_date DATE, status TEXT DEFAULT 'pending_ksv'
);
"""

YEAR = 2026


def _make_db(staff: list[tuple], ld_count: int = 1, nv_count: int = 2) -> sqlite3.Connection:
    """staff: (id, full_name, role, can_do_sp, is_on_project, display_order)."""
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
    db.execute(
        "INSERT INTO duty_shift_config (year, ld_count, nv_count) VALUES (?,?,?)",
        (YEAR, ld_count, nv_count))
    db.commit()
    return db


def _members(shift: dict) -> list[int]:
    import json
    ids = list(json.loads(shift["leader_ids"] or "[]"))
    if shift["sp_id"]:
        ids.append(shift["sp_id"])
    ids.extend(json.loads(shift["nv_ids"] or "[]"))
    ids.extend(json.loads(shift.get("nv_phu_ids") or "[]"))
    return ids


def _leaders(shift: dict) -> list[int]:
    import json
    return list(json.loads(shift["leader_ids"] or "[]"))


def _insert_shift(db, date_str, shift_type, leader_ids, nv_ids, status="confirmed"):
    """Chèn thẳng 1 ca đã có sẵn vào lịch sử (mô phỏng tuần/thứ trước), không
    qua _generate_ca, để kiểm soát chính xác kịch bản hand-trace của planner."""
    import json
    db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_ids, sp_id, nv_ids, "
        "nv_count, is_auto, status, created_at) VALUES (?,?,?,?,?,?,0,?,'2026-01-01')",
        (date_str, shift_type, json.dumps(leader_ids), None, json.dumps(nv_ids),
         len(nv_ids), status),
    )
    db.commit()


# ══════════════════════════════════════════════════════════════
# 1. Bất cập 2a — _chon_lanh_dao() phá tầng (PLAN.md mục 2, kịch bản dòng 130-140)
# ══════════════════════════════════════════════════════════════

def test_2a_chon_lanh_dao_khong_duoc_vuot_tang_vi_biet_song_phuong():
    """LD_A biết SP nhưng đã trực thứ 6 tuần trước (tầng 2 — cần tránh); LD_B
    không biết SP nhưng đang rảnh (tầng 0). Pool NV không ai biết SP nên
    nv_co_sp=False — đúng điều kiện kích hoạt nhánh kéo SP lên đầu.

    Đúng ý đồ: LD_B (tầng 0) phải được chọn, KHÔNG được kéo LD_A (tầng 2) lên
    chỉ vì biết song phương — nếu không, cảnh báo "phải trực 2 tuần liên tiếp
    vì không đủ người khác" là cảnh báo SAI SỰ THẬT (LD_B đang rảnh)."""
    staff = [
        (1, "LD A", "truong_phong", 1, 0, 1),   # biết SP, sẽ bị coi là "đã lặp thứ 6"
        (2, "LD B", "pho_phong",    0, 0, 2),   # không biết SP, đang rảnh
        (5, "NV Năm", "chuyen_vien", 0, 0, 5),
        (6, "NV Sáu", "chuyen_vien", 0, 0, 6),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    prev_friday = "2026-08-07"
    this_friday = "2026-08-14"        # đúng 7 ngày sau, cùng "thứ 6"
    _insert_shift(db, prev_friday, "friday", leader_ids=[1], nv_ids=[99, 100])

    shifts, warnings = _generate_ca(
        db, this_friday, YEAR, "LD_friday", "NV_friday", "friday", random.Random(0)
    )
    assert shifts, "phải lập được ca — đủ người"
    s = shifts[0]
    assert _leaders(s) == [2], (
        f"LD_A (tầng 2, cần tránh) vẫn được chọn thay LD_B (tầng 0) đang rảnh: {_leaders(s)}")
    assert not any(w["type"] in ("thu6_lien_tiep", "thu_lien_tiep") for w in warnings), (
        "LD_B đang rảnh nên không cần cảnh báo lặp thứ 6 liên tiếp")


# ══════════════════════════════════════════════════════════════
# 2. Bất cập 2b/4b — _chia_nhan_vien() phá tầng (PLAN.md mục 2.2b + 4b)
# ══════════════════════════════════════════════════════════════

def test_2b_4b_chia_nhan_vien_khong_duoc_keo_nguoi_da_truc_trong_tuan():
    """NV1 là người DUY NHẤT biết song phương, đã trực thứ 2 (tầng 1 — đã trực
    trong tuần). NV4/5/6 chưa trực ngày nào trong tuần (tầng 0), không biết SP.
    Lãnh đạo không biết SP.

    Đúng ý đồ (Q3 — không dồn ca): thứ 3 phải ưu tiên NV4/5/6 (tầng 0) trám đủ
    2 slot; KHÔNG kéo NV1 (tầng 1, xấu hơn) lên chỉ vì anh ta biết SP — chấp
    nhận cảnh báo `no_sp_chinh` thay vì để NV1 dính ca thứ 2 trong tuần."""
    staff = [
        (2, "LD Hai", "pho_phong",    0, 0, 2),   # LD không biết SP
        (1, "NV Một", "chuyen_vien",  1, 0, 1),   # NV duy nhất biết SP
        (4, "NV Bốn", "chuyen_vien",  0, 0, 4),
        (5, "NV Năm", "chuyen_vien",  0, 0, 5),
        (6, "NV Sáu", "chuyen_vien",  0, 0, 6),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    monday = "2026-08-10"
    tuesday = "2026-08-11"
    # Thứ 2: NV1 đã trực cùng LD Hai + NV Bốn — cả 3 người này thành "tầng 1" cho thứ 3
    _insert_shift(db, monday, "normal", leader_ids=[2], nv_ids=[1, 4])

    shifts, warnings = _generate_ca(
        db, tuesday, YEAR, "LD", "NV", "normal", random.Random(0)
    )
    assert shifts, "phải lập được ca — đủ người"
    s = shifts[0]
    assert 1 not in _members(s), (
        f"NV1 đã trực trong tuần (tầng 1) vẫn bị kéo lên vì biết SP: {_members(s)}")
    assert s["sp_warning"] == "no_sp_chinh", (
        "không còn ai biết SP ở tầng tốt hơn thì phải cảnh báo no_sp_chinh, "
        f"đang là {s['sp_warning']!r}")


# ══════════════════════════════════════════════════════════════
# 3. Bất cập 3 — ê-kíp nhân viên cố định (PLAN.md mục 3) — THUỘC B7-B9,
#    KHÔNG sửa trong đợt này. Test này dự kiến VẪN ĐỎ sau B6, ghi rõ trong
#    CODE_REPORT.md, không phải lỗi chẩn đoán sai.
# ══════════════════════════════════════════════════════════════

def test_3_khong_duoc_sinh_e_kip_nhan_vien_co_dinh():
    """2 LD + 4 NV, không ai biết SP, kênh thứ 6 tất định (randomize=False).
    Hand-trace của planner: (NV11,NV12) và (NV13,NV14) xen kẽ MÃI MÃI, NV11
    không bao giờ đứng cùng NV13/NV14 — vì `_so_lan_di_cung()` chỉ đếm
    NV↔Lãnh đạo, không đếm NV↔NV."""
    from backend.services.duty_scheduler_engine import generate_schedule_for_week

    staff = [
        (1, "LD Một", "truong_phong", 0, 0, 1),
        (2, "LD Hai", "pho_phong",    0, 0, 2),
        (11, "NV 11", "chuyen_vien", 0, 0, 11),
        (12, "NV 12", "chuyen_vien", 0, 0, 12),
        (13, "NV 13", "chuyen_vien", 0, 0, 13),
        (14, "NV 14", "chuyen_vien", 0, 0, 14),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    for ws in ("2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24"):
        generate_schedule_for_week(db, ws, seed=1)

    import json
    cap_nv_nv: dict = {}
    for r in db.execute("SELECT shift_type, nv_ids FROM duty_shifts WHERE shift_type='friday'"):
        nvs = sorted(json.loads(r["nv_ids"] or "[]"))
        if len(nvs) == 2:
            cap_nv_nv[tuple(nvs)] = cap_nv_nv.get(tuple(nvs), 0) + 1

    da_cheo = (11, 13) in cap_nv_nv or (11, 14) in cap_nv_nv
    assert da_cheo, (
        f"4 thứ 6 mà NV11 không bao giờ đứng cùng NV13/NV14 — ê-kíp cố định: {cap_nv_nv}")


# ══════════════════════════════════════════════════════════════
# 4. Luật tránh lặp thứ chỉ áp cho thứ 6 — lặp cùng thứ Ba (PLAN.md mục 1,
#    bằng chứng thực tế: Dũng + Hoàng Lan Anh lặp thứ Ba 3 tuần liền)
# ══════════════════════════════════════════════════════════════

def test_khong_duoc_lap_cung_thu_ba_2_tuan_lien_tiep_khi_rieng_le_van_re_nhat():
    """Mô phỏng đúng triệu chứng người dùng báo (Dũng + Hoàng Lan Anh lặp thứ Ba
    3 tuần liền 08, 15, 22/09): NV1 đã trực thứ Ba 2 tuần liên tiếp trước đó
    (04/08, 11/08 — dữ liệu lịch sử có sẵn, không quan trọng vì sao). Thứ Ba kế
    tiếp (18/08), NV1 vẫn là ứng viên "rẻ nhất" (số ca thấp nhất) trong pool.

    Nếu không có luật tránh lặp thứ áp cho cả T2-T6 (hiện chỉ có ở thứ 6) thì
    NV1 vẫn được chọn tiếp — thành lần lặp thứ 3 liên tiếp, đúng triệu chứng
    người dùng báo. Đúng ý đồ: phải tránh, vì đã đủ 2 lần/tháng VÀ liền kề
    tuần trước."""
    staff = [
        (2, "LD Hai", "pho_phong",   0, 0, 2),
        (1, "NV Một", "chuyen_vien", 0, 0, 1),
        (3, "NV Ba",  "chuyen_vien", 0, 0, 3),
        (4, "NV Bốn", "chuyen_vien", 0, 0, 4),
        (5, "NV Năm", "chuyen_vien", 0, 0, 5),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    _insert_shift(db, "2026-08-04", "normal", leader_ids=[2], nv_ids=[1, 3])   # thứ Ba
    _insert_shift(db, "2026-08-11", "normal", leader_ids=[2], nv_ids=[1, 4])   # thứ Ba, liền kề

    # Ép NV1 vẫn "rẻ nhất" cho thứ Ba 18/08 — cô lập đúng biến cần kiểm: luật
    # tránh lặp thứ, không phải cân bằng ca theo tổng số.
    db.execute("UPDATE duty_rotation_state SET shift_count=0 WHERE role='NV' AND staff_id=1")
    db.execute("UPDATE duty_rotation_state SET shift_count=5 WHERE role='NV' AND staff_id IN (3,4,5)")
    db.commit()

    shifts, _ = _generate_ca(db, "2026-08-18", YEAR, "LD", "NV", "normal", random.Random(0))
    assert shifts, "phải lập được ca"
    assert 1 not in _members(shifts[0]), (
        "NV1 đã trực thứ Ba 2 tuần liên tiếp (đủ mức 2 lần/tháng, liền kề tuần "
        "trước) vẫn được chọn tiếp — thành lặp 3 tuần liên tiếp như triệu chứng "
        "người dùng báo")
