"""
Test ĐỘC LẬP của tester (không dùng lại nguyên văn test coder đã viết trong
tests/test_duty_bat_cap_2026_09_18.py) cho đợt sửa B0->B6 theo pipeline/PLAN.md
(2026-09-18) — bất cập 1 (luật tránh lặp thứ chỉ áp cho thứ 6) và bất cập
2a/2b (bước kéo người song phương phá tầng tránh lặp).

Mục tiêu: dùng kịch bản KHÁC coder (ngày khác, cấu trúc khác) để tìm góc coder
có thể đã bỏ sót khi tự test code của chính mình. Dùng đúng dữ liệu thật người
dùng báo (cặp lặp thứ Ba, ngày 01/08/09/15 09/2026) ở phần 1.
"""
import json
import random

from test_duty_scheduler_algorithm import _make_db, _members, YEAR

from backend.services.duty_scheduler_engine import _generate_ca, generate_schedule_for_week
from backend.services.duty_rules import validate_shift_members


def _insert_shift(db, date_str, shift_type, leader_ids, nv_ids, status="confirmed"):
    """Chèn thẳng 1 ca lịch sử (mô phỏng tuần/thứ trước), không qua _generate_ca."""
    db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_ids, sp_id, nv_ids, "
        "nv_count, is_auto, status, created_at) VALUES (?,?,?,?,?,?,0,?,'2026-01-01')",
        (date_str, shift_type, json.dumps(list(leader_ids)), None, json.dumps(list(nv_ids)),
         len(nv_ids), status),
    )
    db.commit()


# ══════════════════════════════════════════════════════════════
# 1. Cặp cố định lặp trên THỨ BA — đúng ngày thật người dùng báo
#    (01, 08, 15/09/2026), KHÁC bộ ngày 04-18/08/2026 coder đã dùng.
# ══════════════════════════════════════════════════════════════

def test_cap_lap_thu_ba_that_bi_chan_khi_du_nguoi_thay_the():
    """Cặp NV21+NV22 đã lặp y hệt trên thứ Ba (01/09, 08/09/2026 — đúng dữ liệu
    thật Dũng + Hoàng Lan Anh). Đủ 4 NV dự bị tầng 0 để thuật toán CÓ đường
    thoát hợp lệ — nếu luật lặp thứ hoạt động đúng cho cả T2-T6 (không chỉ
    thứ 6) thì không ai trong cặp cũ được chọn lại lần thứ 3 (15/09)."""
    staff = [
        (2, "LD Hai", "pho_phong", 0, 0, 2),
        (9, "LD Chin", "truong_phong", 0, 0, 9),
        (21, "NV 21", "chuyen_vien", 0, 0, 21),
        (22, "NV 22", "chuyen_vien", 0, 0, 22),
        (23, "NV 23", "chuyen_vien", 0, 0, 23),
        (24, "NV 24", "chuyen_vien", 0, 0, 24),
        (25, "NV 25", "chuyen_vien", 0, 0, 25),
        (26, "NV 26", "chuyen_vien", 0, 0, 26),
    ]
    for seed in range(10):
        db = _make_db(staff, ld_count=1, nv_count=2)
        _insert_shift(db, "2026-09-01", "normal", leader_ids=[2], nv_ids=[21, 22])
        _insert_shift(db, "2026-09-08", "normal", leader_ids=[2], nv_ids=[21, 22])

        shifts, warnings = _generate_ca(
            db, "2026-09-15", YEAR, "LD", "NV", "normal", random.Random(seed))
        assert shifts, f"seed={seed}: đủ 6 NV dự bị, phải lập được ca"
        s = shifts[0]
        assert 21 not in _members(s) and 22 not in _members(s), (
            f"seed={seed}: cặp NV21+NV22 đã lặp thứ Ba 2 tuần liền, đủ người thay "
            f"thế mà vẫn bị chọn lại: {_members(s)}")
        assert not any(w["type"] in ("qua_2_thu_thang", "thu_lien_tiep") for w in warnings), (
            f"seed={seed}: đủ người thay thế mà vẫn phải cảnh báo vi phạm: {warnings}")


def test_lap_thu_ba_khi_khong_con_ai_thay_thi_canh_bao_dung_ten_thu():
    """Chỉ đúng 2 NV trong pool (không có ai thay) — buộc phải chọn lại cặp đã
    lặp thứ Ba. Cảnh báo phải nêu đúng "thứ Ba", KHÔNG được lẫn chữ "thứ 6"
    hard-code còn sót lại từ bản cũ (bản cũ chỉ có 1 tên thứ duy nhất)."""
    staff = [
        (2, "LD Hai", "pho_phong", 0, 0, 2),
        (21, "NV 21", "chuyen_vien", 0, 0, 21),
        (22, "NV 22", "chuyen_vien", 0, 0, 22),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    _insert_shift(db, "2026-09-01", "normal", leader_ids=[2], nv_ids=[21, 22])
    _insert_shift(db, "2026-09-08", "normal", leader_ids=[2], nv_ids=[21, 22])

    shifts, warnings = _generate_ca(db, "2026-09-15", YEAR, "LD", "NV", "normal", random.Random(0))
    assert shifts, "luật mềm không được chặn cứng — vẫn phải lập đủ ca"
    msgs = " | ".join(w["msg"] for w in warnings)
    assert "thứ Ba" in msgs, f"cảnh báo phải nêu đúng tên thứ đang xét: {warnings}"
    assert "thứ 6" not in msgs and "thứ Sáu" not in msgs, (
        f"không được lẫn tên thứ 6 hard-code khi đang xét thứ Ba: {warnings}")


# ══════════════════════════════════════════════════════════════
# 2. Q7 — "đã trực trong tuần" (tầng 1) phải THẮNG "lặp thứ" (tầng 2)
#    khi cả 2 loại vi phạm cùng xuất hiện trong 1 tuần.
# ══════════════════════════════════════════════════════════════

def test_q7_uu_tien_da_truc_trong_tuan_hon_lap_thu_hai_nguoi_khac_nhau():
    """NV Y chỉ vi phạm NHẸ (đã trực thứ Hai tuần này — tầng 1). NV X chỉ vi
    phạm NẶNG (lặp đúng thứ Tư tuần trước — tầng 2). Cả hai đều KHÔNG phải là
    ứng viên duy nhất (còn 2 người dự bị tầng 0). Đúng Phương án A (Q7): thà
    cho Y trực ca thứ 2 trong tuần còn hơn ép X lặp thứ — Y phải được chọn,
    X phải bị loại."""
    staff = [
        (9, "LD Chin", "truong_phong", 0, 0, 9),
        (40, "LD Bốn Mươi", "pho_phong", 0, 0, 40),
        (31, "NV X", "chuyen_vien", 0, 0, 31),   # chỉ lặp thứ (tầng 2)
        (32, "NV Y", "chuyen_vien", 0, 0, 32),   # chỉ đã trực tuần này (tầng 1)
        (33, "NV W1", "chuyen_vien", 0, 0, 33),  # dự bị, tầng 0
        (34, "NV W2", "chuyen_vien", 0, 0, 34),  # dự bị, tầng 0
    ]
    for seed in range(10):
        db = _make_db(staff, ld_count=1, nv_count=3)
        _insert_shift(db, "2026-08-05", "normal", leader_ids=[9], nv_ids=[31])  # thứ Tư tuần trước
        _insert_shift(db, "2026-08-10", "normal", leader_ids=[9], nv_ids=[32])  # thứ Hai tuần này

        shifts, _ = _generate_ca(db, "2026-08-12", YEAR, "LD", "NV", "normal", random.Random(seed))
        assert shifts, f"seed={seed}: đủ người, phải lập được ca"
        members = _members(shifts[0])
        assert 32 in members, (
            f"seed={seed}: NV Y (chỉ tầng 1) phải được ưu tiên hơn NV X (tầng 2): {members}")
        assert 31 not in members, (
            f"seed={seed}: NV X (tầng 2 — lặp thứ) không được thắng NV Y (tầng 1): {members}")


def test_q7_mot_nguoi_vua_da_truc_tuan_vua_lap_thu_phai_xep_tang_te_hon():
    """NV X vừa đã trực trong tuần (thứ Hai) VỪA lặp đúng thứ Tư tuần trước —
    mắc CẢ 2 vi phạm cùng lúc trên CÙNG 1 người. NV Y chỉ mắc vi phạm nhẹ (đã
    trực tuần này). Nếu tầng hiệu lực gán đúng ưu tiên (tier_chung được đọc
    TRƯỚC get_week_assignees trong `_generate_ca()`), X phải bị xếp tầng 2
    (tệ hơn), không được "giảm nhẹ" về tầng 1 chỉ vì cũng thuộc diện đã trực
    trong tuần — Y phải được chọn thay X."""
    staff = [
        (9, "LD Chin", "truong_phong", 0, 0, 9),
        (40, "LD Bốn Mươi", "pho_phong", 0, 0, 40),
        (31, "NV X", "chuyen_vien", 0, 0, 31),   # cả 2 vi phạm
        (32, "NV Y", "chuyen_vien", 0, 0, 32),   # chỉ tầng 1
        (33, "NV Z", "chuyen_vien", 0, 0, 33),   # tầng 0
    ]
    for seed in range(10):
        db = _make_db(staff, ld_count=1, nv_count=2)
        _insert_shift(db, "2026-08-05", "normal", leader_ids=[9], nv_ids=[31])        # thứ Tư tuần trước
        _insert_shift(db, "2026-08-10", "normal", leader_ids=[9], nv_ids=[31, 32])    # thứ Hai tuần này

        shifts, _ = _generate_ca(db, "2026-08-12", YEAR, "LD", "NV", "normal", random.Random(seed))
        assert shifts, f"seed={seed}: đủ người, phải lập được ca"
        members = _members(shifts[0])
        assert 31 not in members, (
            f"seed={seed}: NV X mắc CẢ 2 vi phạm phải xếp tầng tệ hơn NV Y: {members}")
        assert 32 in members, (
            f"seed={seed}: NV Y chỉ vi phạm nhẹ hơn phải được chọn trước NV X: {members}")


# ══════════════════════════════════════════════════════════════
# 3. B6 — chỉ 1 người SP khả dụng cả tuần: cảnh báo no_sp_chinh đúng chỗ,
#    KHÔNG ai bị dồn quá 2 ca/tuần (văn bản 18/09/2026).
# ══════════════════════════════════════════════════════════════

def test_chi_1_nguoi_sp_ca_tuan_thi_canh_bao_no_sp_chinh_va_khong_dong_ca():
    """3 LD (không ai biết SP) + 6 NV, chỉ 1 NV biết SP. Sinh cả tuần 5 ngày.
    Q3 (không dồn ca): từ ca thứ 2 trong tuần trở đi, KHÔNG được kéo người SP
    duy nhất lên nếu anh ta đã tệ hơn (đã trực trong tuần) so với người tầng
    tốt hơn — chấp nhận no_sp_chinh thay vì dồn ca."""
    staff = [
        (1, "LD Một", "truong_phong", 0, 0, 1),
        (2, "LD Hai", "pho_phong", 0, 0, 2),
        (3, "LD Ba", "pho_phong", 0, 0, 3),
        (10, "NV SP", "chuyen_vien", 1, 0, 10),
        (11, "NV 11", "chuyen_vien", 0, 0, 11),
        (12, "NV 12", "chuyen_vien", 0, 0, 12),
        (13, "NV 13", "chuyen_vien", 0, 0, 13),
        (14, "NV 14", "chuyen_vien", 0, 0, 14),
        (15, "NV 15", "chuyen_vien", 0, 0, 15),
    ]
    for seed in range(10):
        db = _make_db(staff, ld_count=1, nv_count=2)
        result = generate_schedule_for_week(db, "2026-08-10", seed=seed)

        assert result["created"] == 5, f"seed={seed}: đủ người cho cả 5 ngày trong tuần"
        assert any(w["type"] == "no_sp_chinh" for w in result["warnings"]), (
            f"seed={seed}: chỉ 1 người SP/tuần thì phải có ít nhất 1 ngày cảnh báo "
            f"no_sp_chinh (không đủ để phủ hết 5 ngày)")

        dem: dict = {}
        for r in db.execute("SELECT * FROM duty_shifts"):
            for sid in _members(dict(r)):
                dem[sid] = dem.get(sid, 0) + 1
        vuot = {sid: n for sid, n in dem.items() if n > 2}
        assert not vuot, f"seed={seed}: có người bị dồn quá 2 ca/tuần dù đủ người thay: {vuot}"
        assert dem.get(10, 0) <= 2, (
            f"seed={seed}: NV SP duy nhất không được dồn quá 2 ca/tuần: {dem.get(10)}")


# ══════════════════════════════════════════════════════════════
# 4. Đường sửa tay (validate_shift_members, B3) — cảnh báo phải đúng tên thứ,
#    không còn hard-code "thứ 6".
# ══════════════════════════════════════════════════════════════

def test_sua_tay_ca_thu_tu_lap_tuan_truoc_thi_canh_bao_dung_ten_thu():
    """Sửa tay xếp NV Bảy vào ca thứ Tư (12/08/2026) — người này đã trực đúng
    thứ Tư tuần trước (05/08/2026). Đường sửa tay (`validate_shift_members`)
    phải cảnh báo với đúng "thứ Tư" trong câu chữ, không phải "thứ 6" hard-code
    của bản cũ (trước B3 chỉ mở khối này cho `shift_type == "friday"`)."""
    staff = [
        (2, "LD Hai", "pho_phong", 0, 0, 2),
        (7, "NV Bảy", "chuyen_vien", 0, 0, 7),
        (8, "NV Tám", "chuyen_vien", 0, 0, 8),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    _insert_shift(db, "2026-08-05", "normal", leader_ids=[2], nv_ids=[7])  # thứ Tư tuần trước

    loi_cung, canh_bao, _nguoi = validate_shift_members(
        db, "2026-08-12", "normal", [2], [7, 8])

    assert not loi_cung, f"đủ đúng số người khai báo, không được có lỗi cứng: {loi_cung}"
    msgs = " | ".join(canh_bao)
    assert "thứ Tư" in msgs, f"đường sửa tay phải cảnh báo đúng tên thứ đang xét: {canh_bao}"
    assert "2 tuần liên tiếp" in msgs, f"phải nêu đúng loại vi phạm (liền kề tuần trước): {canh_bao}"
    assert "thứ 6" not in msgs and "thứ Sáu" not in msgs, (
        f"đường sửa tay không được còn hard-code tên thứ 6: {canh_bao}")
