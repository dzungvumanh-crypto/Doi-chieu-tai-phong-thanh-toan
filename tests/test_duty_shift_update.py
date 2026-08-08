"""
Test đường SỬA TAY ca trực.

Hai tầng luật:
  CỨNG — đúng 1 Lãnh đạo + 2 nhân viên. Vi phạm thì không hình thành ca trực.
  MỀM  — đúng 1 người song phương, không xếp người đi dự án / vắng mặt.
          Vi phạm thì vẫn ghi nhận, chỉ cảnh báo.

Dùng lại fixture DB của test_duty_scheduler_algorithm để hai bộ test không thể
lệch nhau về schema và danh sách nhân sự mẫu.
"""
import json

from test_duty_scheduler_algorithm import (
    _make_db, _standard_staff, _members, MONDAY, FRIDAY, YEAR,
)

from backend.services.duty_rules import resolve_sp_role, validate_shift_members
from backend.services.duty_schedule_service import update_shift, confirm_shift

# Nhân sự mẫu: 1=LD Một(SP) 2=LD Hai 3=NV Ba(SP) 4=NV Bốn(SP) 5..8=NV thường
LD_SP, LD_THUONG   = 1, 2
NV_SP1, NV_SP2     = 3, 4
NV_A, NV_B, NV_C   = 5, 6, 7


def _tao_ca(db, date_str=MONDAY, shift_type="normal",
            leader_id=LD_THUONG, sp_id=NV_SP1, nv_ids=(NV_A,), status="draft"):
    cur = db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_id, sp_id, sp_warning, "
        "nv_ids, nv_count, is_auto, status, created_at) VALUES (?,?,?,?,NULL,?,?,1,?,'2026-08-01')",
        (date_str, shift_type, leader_id, sp_id, json.dumps(list(nv_ids)),
         len(nv_ids), status),
    )
    db.commit()
    return cur.lastrowid


def _dat_so_ca(db, role, staff_id, n):
    db.execute(
        "INSERT OR REPLACE INTO duty_rotation_state (year, role, staff_id, shift_count, position) "
        "VALUES (?,?,?,?,0)", (YEAR, role, staff_id, n))
    db.commit()


def _so_ca(db, role, staff_id):
    row = db.execute(
        "SELECT shift_count FROM duty_rotation_state WHERE year=? AND role=? AND staff_id=?",
        (YEAR, role, staff_id)).fetchone()
    return row["shift_count"] if row else 0


# ══════════════════════════════════════════════════════════════
# 1. Vai song phương tự suy
# ══════════════════════════════════════════════════════════════

def test_lanh_dao_biet_sp_thi_lanh_dao_giu_vai():
    ld  = {"id": 1, "can_do_sp": 1}
    nvs = [{"id": 5, "can_do_sp": 0}, {"id": 6, "can_do_sp": 0}]
    sp, warn = resolve_sp_role(ld, nvs)
    assert sp is None and warn == "leader_sp"


def test_nhan_vien_giu_vai_khi_lanh_dao_khong_biet_sp():
    ld  = {"id": 2, "can_do_sp": 0}
    nvs = [{"id": 3, "can_do_sp": 1}, {"id": 5, "can_do_sp": 0}]
    sp, warn = resolve_sp_role(ld, nvs)
    assert sp["id"] == 3 and warn is None


def test_khong_ai_biet_song_phuong():
    ld  = {"id": 2, "can_do_sp": 0}
    nvs = [{"id": 5, "can_do_sp": 0}, {"id": 6, "can_do_sp": 0}]
    sp, warn = resolve_sp_role(ld, nvs)
    assert sp is None and warn == "no_sp"


def test_hai_nguoi_biet_song_phuong_thi_canh_bao():
    ld  = {"id": 2, "can_do_sp": 0}
    nvs = [{"id": 3, "can_do_sp": 1}, {"id": 4, "can_do_sp": 1}]
    sp, warn = resolve_sp_role(ld, nvs)
    assert sp["id"] == 3 and warn == "multi_sp"

    # Lãnh đạo biết SP + 1 nhân viên biết SP cũng là 2 người
    sp2, warn2 = resolve_sp_role({"id": 1, "can_do_sp": 1},
                                 [{"id": 3, "can_do_sp": 1}, {"id": 5, "can_do_sp": 0}])
    assert sp2 is None and warn2 == "multi_sp"


# ══════════════════════════════════════════════════════════════
# 2. Luật CỨNG — chặn, không hình thành ca
# ══════════════════════════════════════════════════════════════

def test_xep_nhan_vien_vao_vi_tri_lanh_dao_bi_chan():
    db = _make_db(_standard_staff())
    loi, _canh_bao, _ = validate_shift_members(db, MONDAY, NV_A, [NV_B, NV_C])
    assert loi and "không phải Lãnh đạo" in " ".join(loi)


def test_xep_lanh_dao_vao_vi_tri_nhan_vien_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, LD_THUONG, [LD_SP, NV_A])
    assert loi and "Lãnh đạo" in " ".join(loi)


def test_thieu_hoac_thua_nhan_vien_bi_chan():
    db = _make_db(_standard_staff())
    for nv in ([NV_A], [NV_A, NV_B, NV_C], []):
        loi, _c, _ = validate_shift_members(db, MONDAY, LD_THUONG, nv)
        assert loi, f"{len(nv)} nhân viên phải bị chặn"
        assert "đúng 2 nhân viên" in " ".join(loi)


def test_hai_nhan_vien_trung_nhau_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_A, NV_A])
    assert loi and "hai vị trí" in " ".join(loi)


def test_lanh_dao_kiem_luon_nhan_vien_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, LD_THUONG, [LD_THUONG, NV_A])
    assert loi


def test_nguoi_ngoai_phong_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_A, 999])
    assert loi and "999" in " ".join(loi)


def test_khong_co_lanh_dao_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, None, [NV_A, NV_B])
    assert loi and "phải có 1 Lãnh đạo" in " ".join(loi)


# ══════════════════════════════════════════════════════════════
# 3. Luật MỀM — vẫn cho lưu, chỉ cảnh báo
# ══════════════════════════════════════════════════════════════

def test_nguoi_di_du_an_chi_canh_bao():
    staff = _standard_staff()
    staff[4] = (NV_A, "NV Năm", "chuyen_vien", 0, 1, 5)   # đi dự án
    db = _make_db(staff)
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_SP1, NV_A])
    assert not loi, "đi dự án là luật mềm, không được chặn"
    assert any("đi dự án" in c for c in canh_bao)


def test_nguoi_vang_mat_chi_canh_bao():
    db = _make_db(_standard_staff())
    db.execute("INSERT INTO duty_absences (staff_id, absence_date) VALUES (?,?)", (NV_A, MONDAY))
    db.commit()
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_SP1, NV_A])
    assert not loi, "vắng mặt là luật mềm, không được chặn"
    assert any("vắng mặt" in c for c in canh_bao)


def test_hai_nguoi_song_phuong_chi_canh_bao():
    db = _make_db(_standard_staff())
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_SP1, NV_SP2])
    assert not loi
    assert any("nhiều hơn 1 người xử lý song phương" in c for c in canh_bao)


def test_khong_ai_song_phuong_chi_canh_bao():
    db = _make_db(_standard_staff())
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_A, NV_B])
    assert not loi
    assert any("không có ai xử lý song phương" in c for c in canh_bao)


def test_ca_hop_le_thi_khong_canh_bao_gi():
    db = _make_db(_standard_staff())
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, LD_THUONG, [NV_SP1, NV_A])
    assert not loi and not canh_bao


# ══════════════════════════════════════════════════════════════
# 4. update_shift — ghi nhận và chu trình xác nhận
# ══════════════════════════════════════════════════════════════

def test_sua_ca_da_xac_nhan_thi_quay_ve_ban_thao():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)
    confirm_shift(db, sid)
    assert db.execute("SELECT status FROM duty_shifts WHERE id=?", (sid,)).fetchone()[0] == "confirmed"

    update_shift(db, sid, LD_SP, [NV_A, NV_B])
    assert db.execute("SELECT status FROM duty_shifts WHERE id=?", (sid,)).fetchone()[0] == "draft"


def test_sua_ca_van_giu_dung_ba_nguoi():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)
    ca = update_shift(db, sid, LD_THUONG, [NV_SP2, NV_B])
    ids = [ca["leader"]["id"]] + ([ca["sp"]["id"]] if ca["sp"] else []) + [p["id"] for p in ca["nvs"]]
    assert sorted(ids) == sorted([LD_THUONG, NV_SP2, NV_B])


def test_sua_ca_tu_suy_lai_vai_song_phuong():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)

    # Lãnh đạo biết SP → lãnh đạo kiêm, không gán sp riêng
    ca = update_shift(db, sid, LD_SP, [NV_A, NV_B])
    assert ca["sp"] is None and ca["sp_warning"] == "leader_sp"

    # Đổi sang lãnh đạo không biết SP + 1 nhân viên biết SP
    ca = update_shift(db, sid, LD_THUONG, [NV_SP1, NV_A])
    assert ca["sp"]["id"] == NV_SP1 and ca["sp_warning"] is None

    # Hai nhân viên đều biết SP
    ca = update_shift(db, sid, LD_THUONG, [NV_SP1, NV_SP2])
    assert ca["sp_warning"] == "multi_sp"

    # Không ai biết SP
    ca = update_shift(db, sid, LD_THUONG, [NV_A, NV_B])
    assert ca["sp"] is None and ca["sp_warning"] == "no_sp"


def test_sua_ca_danh_dau_khong_con_tu_dong():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)
    ca = update_shift(db, sid, LD_THUONG, [NV_SP1, NV_B])
    assert ca["is_auto"] is False


# ══════════════════════════════════════════════════════════════
# 5. Vòng xoay đi theo người sau khi sửa tay
# ══════════════════════════════════════════════════════════════

def test_doi_nguoi_thi_so_ca_chuyen_theo():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, leader_id=LD_THUONG, sp_id=NV_SP1, nv_ids=(NV_A,))
    for role, sid_ in (("LD", LD_THUONG), ("NV", NV_SP1), ("NV", NV_A)):
        _dat_so_ca(db, role, sid_, 3)

    update_shift(db, sid, LD_SP, [NV_B, NV_C])

    assert _so_ca(db, "LD", LD_THUONG) == 2, "lãnh đạo bị gỡ phải giảm 1 ca"
    assert _so_ca(db, "LD", LD_SP) == 1,     "lãnh đạo mới phải tăng 1 ca"
    assert _so_ca(db, "NV", NV_SP1) == 2,    "nhân viên bị gỡ phải giảm 1 ca"
    assert _so_ca(db, "NV", NV_A) == 2
    assert _so_ca(db, "NV", NV_B) == 1
    assert _so_ca(db, "NV", NV_C) == 1


def test_giu_nguyen_nguoi_thi_so_ca_khong_doi():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, leader_id=LD_THUONG, sp_id=NV_SP1, nv_ids=(NV_A,))
    for role, sid_ in (("LD", LD_THUONG), ("NV", NV_SP1), ("NV", NV_A)):
        _dat_so_ca(db, role, sid_, 3)

    update_shift(db, sid, LD_THUONG, [NV_SP1, NV_A])

    assert _so_ca(db, "LD", LD_THUONG) == 3
    assert _so_ca(db, "NV", NV_SP1) == 3
    assert _so_ca(db, "NV", NV_A) == 3


def test_so_ca_khong_bao_gio_am():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, leader_id=LD_THUONG, sp_id=NV_SP1, nv_ids=(NV_A,))
    # chưa từng ghi vòng xoay — sửa tay không được đẩy xuống âm
    update_shift(db, sid, LD_SP, [NV_B, NV_C])
    assert _so_ca(db, "LD", LD_THUONG) == 0
    assert _so_ca(db, "NV", NV_SP1) == 0


def test_ca_thu_sau_dung_kenh_vong_xoay_rieng():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, date_str=FRIDAY, shift_type="friday",
                  leader_id=LD_THUONG, sp_id=NV_SP1, nv_ids=(NV_A,))
    _dat_so_ca(db, "LD_friday", LD_THUONG, 2)

    update_shift(db, sid, LD_SP, [NV_B, NV_C])

    assert _so_ca(db, "LD_friday", LD_THUONG) == 1
    assert _so_ca(db, "LD_friday", LD_SP) == 1
    assert _so_ca(db, "LD", LD_SP) == 0, "không được đụng kênh ngày thường"
    assert _so_ca(db, "NV_friday", NV_B) == 1
