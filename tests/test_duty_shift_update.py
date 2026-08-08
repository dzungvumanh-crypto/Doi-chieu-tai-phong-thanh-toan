"""
Test đường SỬA TAY ca trực và số người khai báo ở tab Cài đặt.

Hai tầng luật:
  CỨNG — đủ đúng số Lãnh đạo / trực chính / trực phụ đã khai báo.
          Vi phạm thì không hình thành ca trực.
  MỀM  — ít nhất 1 người song phương trong (Lãnh đạo + trực chính), không xếp
          người đi dự án / vắng mặt. Vi phạm thì vẫn ghi nhận, chỉ cảnh báo.

Dùng lại fixture DB của test_duty_scheduler_algorithm để hai bộ test không thể
lệch nhau về schema và danh sách nhân sự mẫu.
"""
import json

from test_duty_scheduler_algorithm import (
    _make_db, _standard_staff, _members, _leaders, MONDAY, FRIDAY, YEAR,
)

from backend.services.duty_rules import (
    resolve_sp_role, validate_shift_members, get_cau_hinh_ca,
)
from backend.services.duty_schedule_service import update_shift, confirm_shift

# Nhân sự mẫu: 1=LD Một(SP) 2=LD Hai 3=NV Ba(SP) 4=NV Bốn(SP) 5..8=NV thường
LD_SP, LD_THUONG   = 1, 2
NV_SP1, NV_SP2     = 3, 4
NV_A, NV_B, NV_C, NV_D = 5, 6, 7, 8


def _tao_ca(db, date_str=MONDAY, shift_type="normal", leader_ids=(LD_THUONG,),
            sp_id=NV_SP1, nv_ids=(NV_A,), nv_phu_ids=(), status="draft"):
    cur = db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_ids, sp_id, sp_warning, "
        "nv_ids, nv_count, nv_phu_ids, nv_phu_count, is_auto, status, created_at) "
        "VALUES (?,?,?,?,NULL,?,?,?,?,1,?,'2026-08-01')",
        (date_str, shift_type, json.dumps(list(leader_ids)), sp_id,
         json.dumps(list(nv_ids)), len(nv_ids),
         json.dumps(list(nv_phu_ids)), len(nv_phu_ids), status),
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


def _ld(*ids):
    return list(ids)


# ══════════════════════════════════════════════════════════════
# 1. Cấu hình số người
# ══════════════════════════════════════════════════════════════

def test_cau_hinh_mac_dinh_ca_thuong():
    db = _make_db(_standard_staff())
    assert get_cau_hinh_ca(db, YEAR, "normal") == (1, 2, 0)
    assert get_cau_hinh_ca(db, YEAR, "friday") == (1, 2, 0)
    assert get_cau_hinh_ca(db, YEAR, "cutoff") == (1, 2, 0)


def test_cau_hinh_ca_quyet_toan_tach_rieng():
    db = _make_db(_standard_staff(), qt_ld=2, qt_chinh=3, qt_phu=2)
    assert get_cau_hinh_ca(db, YEAR, "settlement_main") == (2, 3, 2)


def test_doi_cau_hinh_thi_so_nguoi_doi_theo():
    db = _make_db(_standard_staff(), ld_count=2, nv_count=3)
    assert get_cau_hinh_ca(db, YEAR, "normal") == (2, 3, 0)


def test_nam_chua_khai_bao_thi_dung_mac_dinh():
    db = _make_db(_standard_staff())
    db.execute("DELETE FROM duty_shift_config")
    db.commit()
    assert get_cau_hinh_ca(db, YEAR, "normal") == (1, 2, 0)
    assert get_cau_hinh_ca(db, YEAR, "settlement_main") == (1, 3, 2)


# ══════════════════════════════════════════════════════════════
# 2. Vai song phương tự suy
# ══════════════════════════════════════════════════════════════

def test_lanh_dao_biet_sp_thi_lanh_dao_giu_vai():
    sp, warn = resolve_sp_role([{"id": 1, "can_do_sp": 1}],
                               [{"id": 5, "can_do_sp": 0}, {"id": 6, "can_do_sp": 0}])
    assert sp is None and warn == "leader_sp"


def test_nhan_vien_giu_vai_khi_lanh_dao_khong_biet_sp():
    sp, warn = resolve_sp_role([{"id": 2, "can_do_sp": 0}],
                               [{"id": 3, "can_do_sp": 1}, {"id": 5, "can_do_sp": 0}])
    assert sp["id"] == 3 and warn is None


def test_khong_ai_o_truc_chinh_biet_song_phuong():
    sp, warn = resolve_sp_role([{"id": 2, "can_do_sp": 0}],
                               [{"id": 5, "can_do_sp": 0}, {"id": 6, "can_do_sp": 0}])
    assert sp is None and warn == "no_sp_chinh"


def test_nguoi_song_phuong_o_nhom_phu_khong_tinh_la_du():
    """Trực phụ về sớm — không thay được vai song phương của trực chính."""
    sp, warn = resolve_sp_role([{"id": 2, "can_do_sp": 0}],
                               [{"id": 5, "can_do_sp": 0}],
                               [{"id": 3, "can_do_sp": 1}])
    assert warn == "no_sp_chinh"


def test_hai_nguoi_biet_song_phuong_thi_canh_bao():
    sp, warn = resolve_sp_role([{"id": 2, "can_do_sp": 0}],
                               [{"id": 3, "can_do_sp": 1}, {"id": 4, "can_do_sp": 1}])
    assert sp["id"] == 3 and warn == "multi_sp"

    sp2, warn2 = resolve_sp_role([{"id": 1, "can_do_sp": 1}],
                                 [{"id": 3, "can_do_sp": 1}, {"id": 5, "can_do_sp": 0}])
    assert sp2 is None and warn2 == "multi_sp"


# ══════════════════════════════════════════════════════════════
# 3. Luật CỨNG — chặn, không hình thành ca
# ══════════════════════════════════════════════════════════════

def test_xep_nhan_vien_vao_vi_tri_lanh_dao_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(NV_A), [NV_B, NV_C])
    assert loi and "không phải Lãnh đạo" in " ".join(loi)


def test_xep_lanh_dao_vao_vi_tri_nhan_vien_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(LD_THUONG), [LD_SP, NV_A])
    assert loi and "là Lãnh đạo" in " ".join(loi)


def test_thieu_hoac_thua_nhan_vien_bi_chan():
    db = _make_db(_standard_staff())
    for nv in ([NV_A], [NV_A, NV_B, NV_C], []):
        loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(LD_THUONG), nv)
        assert loi, f"{len(nv)} nhân viên phải bị chặn"
        assert "đúng 2 nhân viên trực chính" in " ".join(loi)


def test_thieu_hoac_thua_lanh_dao_bi_chan():
    db = _make_db(_standard_staff())
    for ld in ([], [LD_SP, LD_THUONG]):
        loi, _c, _ = validate_shift_members(db, MONDAY, "normal", ld, [NV_A, NV_B])
        assert loi and "đúng 1 Lãnh đạo" in " ".join(loi)


def test_khai_hai_lanh_dao_thi_bat_buoc_du_hai():
    db = _make_db(_standard_staff(), ld_count=2)
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(LD_SP), [NV_A, NV_B])
    assert loi and "đúng 2 Lãnh đạo" in " ".join(loi)

    loi2, _c2, _ = validate_shift_members(db, MONDAY, "normal",
                                          _ld(LD_SP, LD_THUONG), [NV_A, NV_B])
    assert not loi2


def test_khai_ba_nhan_vien_thi_bat_buoc_du_ba():
    db = _make_db(_standard_staff(), nv_count=3)
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(LD_THUONG), [NV_SP1, NV_A])
    assert loi and "đúng 3 nhân viên trực chính" in " ".join(loi)


def test_ca_quyet_toan_bat_buoc_du_ca_nhom_phu():
    db = _make_db(_standard_staff(), qt_ld=1, qt_chinh=3, qt_phu=2)
    # thiếu nhóm phụ
    loi, _c, _ = validate_shift_members(db, MONDAY, "settlement_main",
                                        _ld(LD_THUONG), [NV_SP1, NV_A, NV_B], [NV_C])
    assert loi and "đúng 2 nhân viên trực phụ" in " ".join(loi)

    loi2, _c2, _ = validate_shift_members(db, MONDAY, "settlement_main",
                                          _ld(LD_THUONG), [NV_SP1, NV_A, NV_B], [NV_C, NV_D])
    assert not loi2


def test_mot_nguoi_khong_the_giu_hai_cho():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(LD_THUONG), [NV_A, NV_A])
    assert loi and "hai vị trí" in " ".join(loi)

    # trùng giữa nhóm chính và nhóm phụ
    db2 = _make_db(_standard_staff(), qt_ld=1, qt_chinh=2, qt_phu=1)
    loi2, _c2, _ = validate_shift_members(db2, MONDAY, "settlement_main",
                                          _ld(LD_THUONG), [NV_SP1, NV_A], [NV_A])
    assert loi2 and "hai vị trí" in " ".join(loi2)


def test_lanh_dao_kiem_luon_nhan_vien_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal",
                                        _ld(LD_THUONG), [LD_THUONG, NV_A])
    assert loi


def test_nguoi_ngoai_phong_bi_chan():
    db = _make_db(_standard_staff())
    loi, _c, _ = validate_shift_members(db, MONDAY, "normal", _ld(LD_THUONG), [NV_A, 999])
    assert loi and "999" in " ".join(loi)


# ══════════════════════════════════════════════════════════════
# 4. Luật MỀM — vẫn cho lưu, chỉ cảnh báo
# ══════════════════════════════════════════════════════════════

def test_nguoi_di_du_an_chi_canh_bao():
    staff = _standard_staff()
    staff[4] = (NV_A, "NV Năm", "chuyen_vien", 0, 1, 5)   # đi dự án
    db = _make_db(staff)
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, "normal",
                                              _ld(LD_THUONG), [NV_SP1, NV_A])
    assert not loi, "đi dự án là luật mềm, không được chặn"
    assert any("đi dự án" in c for c in canh_bao)


def test_nguoi_vang_mat_chi_canh_bao():
    db = _make_db(_standard_staff())
    db.execute("INSERT INTO duty_absences (staff_id, absence_date) VALUES (?,?)", (NV_A, MONDAY))
    db.commit()
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, "normal",
                                              _ld(LD_THUONG), [NV_SP1, NV_A])
    assert not loi, "vắng mặt là luật mềm, không được chặn"
    assert any("vắng mặt" in c for c in canh_bao)


def test_hai_nguoi_song_phuong_chi_canh_bao():
    db = _make_db(_standard_staff())
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, "normal",
                                              _ld(LD_THUONG), [NV_SP1, NV_SP2])
    assert not loi
    assert any("nhiều hơn 1 người xử lý song phương" in c for c in canh_bao)


def test_truc_chinh_khong_ai_song_phuong_chi_canh_bao():
    db = _make_db(_standard_staff())
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, "normal",
                                              _ld(LD_THUONG), [NV_A, NV_B])
    assert not loi
    assert any("không có ai xử lý song phương" in c for c in canh_bao)


def test_ca_hop_le_thi_khong_canh_bao_gi():
    db = _make_db(_standard_staff())
    loi, canh_bao, _ = validate_shift_members(db, MONDAY, "normal",
                                              _ld(LD_THUONG), [NV_SP1, NV_A])
    assert not loi and not canh_bao


# ══════════════════════════════════════════════════════════════
# 5. update_shift — ghi nhận và chu trình xác nhận
# ══════════════════════════════════════════════════════════════

def test_sua_ca_da_xac_nhan_thi_quay_ve_ban_thao():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)
    confirm_shift(db, sid)
    assert db.execute("SELECT status FROM duty_shifts WHERE id=?", (sid,)).fetchone()[0] == "confirmed"

    update_shift(db, sid, _ld(LD_SP), [NV_A, NV_B])
    assert db.execute("SELECT status FROM duty_shifts WHERE id=?", (sid,)).fetchone()[0] == "draft"


def test_sua_ca_van_giu_dung_so_nguoi():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)
    ca = update_shift(db, sid, _ld(LD_THUONG), [NV_SP2, NV_B])
    ids = ([p["id"] for p in ca["leaders"]]
           + ([ca["sp"]["id"]] if ca["sp"] else [])
           + [p["id"] for p in ca["nvs"]])
    assert sorted(ids) == sorted([LD_THUONG, NV_SP2, NV_B])


def test_sua_ca_luu_duoc_hai_lanh_dao():
    db = _make_db(_standard_staff(), ld_count=2)
    sid = _tao_ca(db)
    ca = update_shift(db, sid, _ld(LD_SP, LD_THUONG), [NV_A, NV_B])
    assert [p["id"] for p in ca["leaders"]] == [LD_SP, LD_THUONG]


def test_sua_ca_luu_duoc_nhom_truc_phu():
    db = _make_db(_standard_staff(), qt_ld=1, qt_chinh=2, qt_phu=2)
    sid = _tao_ca(db, shift_type="settlement_main")
    ca = update_shift(db, sid, _ld(LD_THUONG), [NV_SP1, NV_A], [NV_B, NV_C])
    assert [p["id"] for p in ca["nv_phu"]] == [NV_B, NV_C]
    assert ca["nv_phu_count"] == 2


def test_sua_ca_tu_suy_lai_vai_song_phuong():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)

    ca = update_shift(db, sid, _ld(LD_SP), [NV_A, NV_B])
    assert ca["sp"] is None and ca["sp_warning"] == "leader_sp"

    ca = update_shift(db, sid, _ld(LD_THUONG), [NV_SP1, NV_A])
    assert ca["sp"]["id"] == NV_SP1 and ca["sp_warning"] is None

    ca = update_shift(db, sid, _ld(LD_THUONG), [NV_SP1, NV_SP2])
    assert ca["sp_warning"] == "multi_sp"

    ca = update_shift(db, sid, _ld(LD_THUONG), [NV_A, NV_B])
    assert ca["sp"] is None and ca["sp_warning"] == "no_sp_chinh"


def test_sua_ca_danh_dau_khong_con_tu_dong():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db)
    ca = update_shift(db, sid, _ld(LD_THUONG), [NV_SP1, NV_B])
    assert ca["is_auto"] is False


# ══════════════════════════════════════════════════════════════
# 6. Vòng xoay đi theo người sau khi sửa tay
# ══════════════════════════════════════════════════════════════

def test_doi_nguoi_thi_so_ca_chuyen_theo():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, leader_ids=(LD_THUONG,), sp_id=NV_SP1, nv_ids=(NV_A,))
    for role, sid_ in (("LD", LD_THUONG), ("NV", NV_SP1), ("NV", NV_A)):
        _dat_so_ca(db, role, sid_, 3)

    update_shift(db, sid, _ld(LD_SP), [NV_B, NV_C])

    assert _so_ca(db, "LD", LD_THUONG) == 2, "lãnh đạo bị gỡ phải giảm 1 ca"
    assert _so_ca(db, "LD", LD_SP) == 1,     "lãnh đạo mới phải tăng 1 ca"
    assert _so_ca(db, "NV", NV_SP1) == 2,    "nhân viên bị gỡ phải giảm 1 ca"
    assert _so_ca(db, "NV", NV_A) == 2
    assert _so_ca(db, "NV", NV_B) == 1
    assert _so_ca(db, "NV", NV_C) == 1


def test_nguoi_truc_phu_cung_duoc_tinh_vong_xoay():
    db = _make_db(_standard_staff(), qt_ld=1, qt_chinh=2, qt_phu=1)
    sid = _tao_ca(db, shift_type="settlement_main")
    update_shift(db, sid, _ld(LD_THUONG), [NV_SP1, NV_A], [NV_B])
    assert _so_ca(db, "NV", NV_B) == 1, "trực phụ cũng là đi trực, phải vào vòng xoay"


def test_giu_nguyen_nguoi_thi_so_ca_khong_doi():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, leader_ids=(LD_THUONG,), sp_id=NV_SP1, nv_ids=(NV_A,))
    for role, sid_ in (("LD", LD_THUONG), ("NV", NV_SP1), ("NV", NV_A)):
        _dat_so_ca(db, role, sid_, 3)

    update_shift(db, sid, _ld(LD_THUONG), [NV_SP1, NV_A])

    assert _so_ca(db, "LD", LD_THUONG) == 3
    assert _so_ca(db, "NV", NV_SP1) == 3
    assert _so_ca(db, "NV", NV_A) == 3


def test_so_ca_khong_bao_gio_am():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, leader_ids=(LD_THUONG,), sp_id=NV_SP1, nv_ids=(NV_A,))
    update_shift(db, sid, _ld(LD_SP), [NV_B, NV_C])
    assert _so_ca(db, "LD", LD_THUONG) == 0
    assert _so_ca(db, "NV", NV_SP1) == 0


def test_ca_thu_sau_dung_kenh_vong_xoay_rieng():
    db = _make_db(_standard_staff())
    sid = _tao_ca(db, date_str=FRIDAY, shift_type="friday",
                  leader_ids=(LD_THUONG,), sp_id=NV_SP1, nv_ids=(NV_A,))
    _dat_so_ca(db, "LD_friday", LD_THUONG, 2)

    update_shift(db, sid, _ld(LD_SP), [NV_B, NV_C])

    assert _so_ca(db, "LD_friday", LD_THUONG) == 1
    assert _so_ca(db, "LD_friday", LD_SP) == 1
    assert _so_ca(db, "LD", LD_SP) == 0, "không được đụng kênh ngày thường"
    assert _so_ca(db, "NV_friday", NV_B) == 1
