"""
Test ĐỘC LẬP của tester cho GIAI ĐOẠN 2 (B7->B11, bất cập 3 — cặp nhân viên
trực chính cố định), theo brief tổng chỉ huy 2026-09-18. Không copy nguyên văn
test coder đã viết (`tests/test_duty_bat_cap_2026_09_18.py`,
`tests/test_duty_ma_tran_di_cung_nv_2026_09_18.py`) hay test tester Giai đoạn 1
(`tests/test_duty_luat_thu_tester_doc_lap_2026_09_18.py`) — dùng kịch bản, dữ
liệu và cách gọi hàm khác để soi các góc coder có thể đã bỏ sót.

Trọng tâm soi theo pipeline/CODE_REPORT.md mục 3 (2 quyết định tự chọn của
coder) + brief:
  1. Bucket-theo-tầng trong `_chia_nhan_vien()` (quyết định #1) — gọi thẳng hàm
     ở mức đơn vị, không qua `_generate_ca()`, để cô lập đúng cơ chế đang nghi.
  2. Không nới fixture 4 LD/12 NV ở B10 (quyết định #2) — quét 50 seed liên
     tiếp (0-49), rộng hơn 4 seed-offset coder tự thử trong script rời.
  3. Bug "thiếu tranh_sp" coder tự phát hiện và tự sửa giữa chừng B9 — xác
     nhận bản vá còn nguyên trong code hiện tại, không chỉ trong lời kể.
  4. Kịch bản gốc của người dùng (2 cặp cố định — thứ Hai VÀ thứ Ba — cùng lúc
     trong 1 phòng, 3 tuần liên tiếp) — dựng lại đúng hình dạng, không chỉ 1
     cặp như test B0 của coder.
  5. Q4 (đi cùng chỉ tính trực chính) qua ĐƯỜNG ENGINE THẬT (sinh ca quyết
     toán có nhóm phụ rồi soi ma trận), không chỉ qua insert DB trực tiếp.
"""
import random
import json

import pytest

from test_duty_scheduler_algorithm import _make_db, _members, _leaders, YEAR

from backend.services.duty_scheduler_engine import (
    _generate_ca, _generate_ngay_dac_biet, _save_shift, generate_schedule_for_week,
    _chia_nhan_vien, _rank_candidates, _ma_tran_di_cung_nv,
)


def _insert_shift(db, date_str, shift_type, leader_ids, nv_ids, status="confirmed"):
    """Chèn thẳng 1 ca lịch sử, không qua _generate_ca — kiểm soát chính xác
    kịch bản, giống tiền lệ 2 file test trước (coder B0 + tester Giai đoạn 1)."""
    db.execute(
        "INSERT INTO duty_shifts (shift_date, shift_type, leader_ids, sp_id, nv_ids, "
        "nv_count, is_auto, status, created_at) VALUES (?,?,?,?,?,?,0,?,'2026-01-01')",
        (date_str, shift_type, json.dumps(list(leader_ids)), None, json.dumps(list(nv_ids)),
         len(nv_ids), status),
    )
    db.commit()


# ══════════════════════════════════════════════════════════════
# 1. Quyết định #1 — bucket theo TẦNG trước, `tong` chỉ phân xử TRONG tầng
#    (CODE_REPORT mục 3.1). Gọi thẳng _chia_nhan_vien(), schema tối thiểu.
# ══════════════════════════════════════════════════════════════

def _db_rotation_only():
    """Schema tối thiểu — chỉ duty_rotation_state. Đủ vì mỗi hàng ta tự chèn
    sẵn nên `_get_rotation_state()` tìm thấy ngay, không cần user_tttt/
    duty_staff_meta (chỉ đụng 2 bảng đó khi row CHƯA có, xem duty_scheduler_engine.py:48-71)."""
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE duty_rotation_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, role TEXT, staff_id INTEGER,
        shift_count INTEGER DEFAULT 0, last_used DATE, position INTEGER DEFAULT 0,
        UNIQUE(year, role, staff_id)
    );
    """)
    return db


def _set_tong(db, sid, year, role, n, position=0):
    db.execute(
        "INSERT INTO duty_rotation_state (year, role, staff_id, shift_count, position) "
        "VALUES (?,?,?,?,?)", (year, role, sid, n, position))
    db.commit()


def test_bucket_theo_tang_thang_tong_khi_chon_tuan_tu():
    """Ép đúng tình huống CODE_REPORT mô tả: người tầng XẤU (tang=2, đã lặp
    thứ/quá tải tuần) có `tong` (tổng ca cả năm) THẤP HƠN người tầng SẠCH
    (tang=0) — nếu `_chia_nhan_vien()` xếp hạng PHẲNG trên toàn bộ `con_lai`
    (không bucket theo tầng trước), `tong` thấp hơn sẽ thắng ngay ở vòng lặp
    thứ 2, tái hiện đúng dạng bug 2a/2b/4b ở lớp mới. Xác nhận code hiện tại
    KHÔNG mắc lại lỗi đó."""
    db = _db_rotation_only()
    year = 2026
    # NV_C: tầng 0, tong=0 -> chắc chắn là nv_order[0] (người đầu tiên, giữ
    # nguyên logic hiện có, không đi qua bucket).
    _set_tong(db, 43, year, "NV", 0, position=73)
    # NV_B: tầng 0 (sạch), tong=3 (cao hơn nhiều so với NV_A).
    _set_tong(db, 44, year, "NV", 3, position=84)
    # NV_A: tầng 2 (XẤU — đã lặp thứ/quá tải tuần), tong=1 (THẤP hơn NV_B).
    _set_tong(db, 21, year, "NV", 1, position=21)

    nv_order = [
        {"id": 43, "full_name": "NV C", "can_do_sp": 0},
        {"id": 44, "full_name": "NV B", "can_do_sp": 0},
        {"id": 21, "full_name": "NV A", "can_do_sp": 0},
    ]
    tang = {43: 0, 44: 0, 21: 2}

    chinh, phu = _chia_nhan_vien(
        db, nv_order, so_chinh=2, so_phu=0, ld_co_sp=True, tang=tang,
        year=year, role="NV", date_str="2026-08-12", rng=random.Random(0),
        randomize=False, di_cung={}, ma_tran_di_cung_nv={})

    ids = [p["id"] for p in chinh]
    assert 21 not in ids, (
        f"NV A tầng 2 (xấu) có tong=1 thấp hơn NV B tầng 0 (tong=3) mà vẫn được "
        f"chọn — nghĩa là code đang xếp hạng PHẲNG, bỏ qua bucket theo tầng: {ids}")
    assert 44 in ids, (
        f"NV B tầng 0 (sạch) phải thắng dù tong cao hơn NV A — tầng phải đứng "
        f"trước tong trong thứ tự ưu tiên chọn tuần tự: {ids}")


def test_rank_candidates_phang_se_chon_sai_neu_khong_bucket():
    """Bằng chứng ĐỘC LẬP cho lập luận của coder (không chỉ tin lời kể): dùng
    trực tiếp `_rank_candidates()` — hàm mà `_chia_nhan_vien()` gọi bên trong
    mỗi vòng lặp — trên đúng 2 người ở test trên (bỏ qua bucket, coi như gọi
    trên toàn bộ `con_lai` không lọc tầng). Nếu NV A (tang xấu, tong thấp)
    thắng NV B (tầng sạch, tong cao hơn) ở đây, tức là RỦI RO coder nêu trong
    quyết định #1 là CÓ THẬT — bucket ở `_chia_nhan_vien()` là hàng rào bắt
    buộc, không phải phòng xa thừa thãi."""
    db = _db_rotation_only()
    year = 2026
    _set_tong(db, 44, year, "NV", 3, position=84)   # tầng sạch, tong cao
    _set_tong(db, 21, year, "NV", 1, position=21)   # tầng xấu, tong thấp

    candidates = [
        {"id": 44, "full_name": "NV B", "can_do_sp": 0},
        {"id": 21, "full_name": "NV A", "can_do_sp": 0},
    ]
    # Gọi PHẲNG — không lọc theo tầng trước, đúng cách "nếu không bucket" mà
    # CODE_REPORT cảnh báo.
    ranked = _rank_candidates(db, candidates, year, "NV", "2026-08-12",
                              random.Random(0), randomize=False)
    assert ranked[0]["id"] == 21, (
        "nếu KHÔNG bucket theo tầng, `tong` thắng bất kể tầng — xác nhận rủi ro "
        "coder nêu trong quyết định #1 (CODE_REPORT mục 3.1) là CÓ THẬT, không "
        "phải lo xa thừa thãi. Đây CHÍNH LÀ lý do bucket ở `_chia_nhan_vien()` "
        "là bắt buộc.")


# ══════════════════════════════════════════════════════════════
# 2. Quyết định #2 — KHÔNG nới fixture 4 LD/12 NV ở B10. Quét 50 seed liên
#    tiếp (0-49), rộng hơn 4 seed-offset (0,100,500,999) coder tự thử.
# ══════════════════════════════════════════════════════════════

def _mo_phong_3_thang(seed_base: int):
    """Sao y hệt cấu hình fixture + kịch bản của
    test_mo_phong_3_thang_giu_dong_thoi_ca_3_luat (coder, B10) — CHỈ đổi
    seed_base để quét rộng hơn 4 mức coder tự thử trong script rời (không
    phải test chính thức)."""
    from datetime import date, timedelta

    staff = [(i, f"LD {i}", "truong_phong", 0, 0, i) for i in range(1, 5)]
    staff += [(10 + i, f"NV {i}", "chuyen_vien", 1 if i % 3 == 0 else 0, 0, 10 + i)
              for i in range(1, 13)]
    db = _make_db(staff)

    start = date(2026, 6, 1)
    start -= timedelta(days=start.weekday())
    all_warnings = []
    for i in range(13):
        ws = (start + timedelta(weeks=i)).isoformat()
        result = generate_schedule_for_week(db, ws, seed=seed_base + i)
        all_warnings.extend(result["warnings"])
    return db, all_warnings


def _kiem_6_luat(db, all_warnings):
    """Trả về danh sách vi phạm (rỗng nếu đạt cả 6 luật) — logic y hệt phần
    kiểm của test_mo_phong_3_thang_giu_dong_thoi_ca_3_luat, tách hàm để tái sử
    dụng cho vòng quét seed."""
    from datetime import date, timedelta

    vi_pham = []

    theo_tuan: dict = {}
    for r in db.execute("SELECT shift_date, leader_ids, sp_id, nv_ids, nv_phu_ids FROM duty_shifts"):
        d = date.fromisoformat(r["shift_date"])
        wk = (d - timedelta(days=d.weekday())).isoformat()
        cho_tuan = theo_tuan.setdefault(wk, {})
        for sid in _members(dict(r)):
            cho_tuan[sid] = cho_tuan.get(sid, 0) + 1
    vuot_tuan = {(wk, sid): n for wk, m in theo_tuan.items() for sid, n in m.items() if n > 2}
    if vuot_tuan:
        vi_pham.append(f"(a) vượt 2 ca/tuần: {vuot_tuan}")

    theo_thang_thu: dict = {}
    rows_theo_thu: dict = {}
    for row in db.execute(
        "SELECT * FROM duty_shifts WHERE shift_type IN ('normal','friday') ORDER BY shift_date"
    ):
        r = dict(row)
        d = date.fromisoformat(r["shift_date"])
        if d.weekday() > 4:
            continue
        thang = r["shift_date"][:7]
        key = (thang, d.weekday())
        cho = theo_thang_thu.setdefault(key, {})
        for sid in _members(r):
            cho[sid] = cho.get(sid, 0) + 1
        rows_theo_thu.setdefault(d.weekday(), []).append(r)

    vuot_thang_thu = {k: {sid: n for sid, n in m.items() if n > 2}
                      for k, m in theo_thang_thu.items() if any(n > 2 for n in m.values())}
    if vuot_thang_thu:
        vi_pham.append(f"(b) vượt 2 lần/thứ/tháng: {vuot_thang_thu}")

    for wd, rows in rows_theo_thu.items():
        for prev, cur in zip(rows, rows[1:]):
            if (date.fromisoformat(cur["shift_date"])
                    - date.fromisoformat(prev["shift_date"])).days != 7:
                continue
            trung = set(_members(prev)) & set(_members(cur))
            if trung:
                vi_pham.append(f"(c) trùng thứ liên tiếp {prev['shift_date']}->"
                               f"{cur['shift_date']}: {trung}")

    cap_nv: dict = {}
    tong_ca = 0
    for row in db.execute("SELECT nv_ids, sp_id FROM duty_shifts"):
        r = dict(row)
        nhom = sorted(set(json.loads(r["nv_ids"] or "[]"))
                     | ({r["sp_id"]} if r["sp_id"] else set()))
        tong_ca += 1
        for i in range(len(nhom)):
            for j in range(i + 1, len(nhom)):
                cap = (nhom[i], nhom[j])
                cap_nv[cap] = cap_nv.get(cap, 0) + 1
    if cap_nv:
        nhieu_nhat = max(cap_nv.values())
        if nhieu_nhat >= tong_ca * 0.75:
            vi_pham.append(f"(d) cặp NV-NV cố định {nhieu_nhat}/{tong_ca} ca")

    canh_bao_vi_pham = [w for w in all_warnings if w["type"] in
                        ("qua_tai_tuan", "qua_2_thu_thang", "thu_lien_tiep")]
    if canh_bao_vi_pham:
        vi_pham.append(f"(e) cảnh báo buộc-vi-phạm: {canh_bao_vi_pham}")

    return vi_pham


def test_quet_50_seed_lien_tiep_fixture_4ld_12nv_khong_nen_vi_pham():
    """Quyết định #2 của coder (KHÔNG nới fixture, trái khuyến nghị thận
    trọng của PLAN.md B10): coder chỉ tự thử 4 mức seed-offset (0,100,500,999)
    bằng script rời KHÔNG commit. Đây là rủi ro của việc "chỉ thử 4 mức rồi kết
    luận an toàn" mà brief yêu cầu soi. Quét toàn bộ 50 seed LIÊN TIẾP (0-49)
    — rộng hơn nhiều — để tìm seed nào lộ ra vi phạm mà coder chưa thấy.

    Tự chạy độc lập (ngoài test này) còn quét thêm seed 50-299 + 50 seed ngẫu
    nhiên lớn (tổng 400 seed) bằng script rời, 0/400 vi phạm — xem TEST_REPORT.md.
    Test này chỉ giữ lại 50 seed đầu để không kéo dài thời gian chạy suite."""
    that_bai = {}
    ty_le_cao_nhat = 0.0
    for seed in range(50):
        db, all_warnings = _mo_phong_3_thang(seed)
        vi_pham = _kiem_6_luat(db, all_warnings)
        if vi_pham:
            that_bai[seed] = vi_pham
    assert not that_bai, (
        f"fixture 4 LD/12 NV LỘ vi phạm ở seed cụ thể — quyết định #2 của coder "
        f"(không nới fixture) SAI, cần nới theo khuyến nghị PLAN.md: {that_bai}")


# ══════════════════════════════════════════════════════════════
# 3. Bug "thiếu tranh_sp" coder tự phát hiện/tự sửa giữa chừng B9 — xác nhận
#    bản vá còn nguyên trong CODE HIỆN TẠI (không chỉ trong lời kể CODE_REPORT).
# ══════════════════════════════════════════════════════════════

def test_khong_con_multi_sp_gia_khi_lanh_dao_giu_sp_va_nhieu_nv_biet_sp():
    """Lãnh đạo duy nhất biết SP (ld_co_sp=True). Nhóm dự bị có CẢ người biết
    SP (position nhỏ — dễ bị chọn nếu tiêu chí tranh_sp bị bỏ quên trong vòng
    lặp chọn tuần tự) LẪN người không biết SP (position lớn hơn). Nếu bug cũ
    (thiếu `tranh_sp=ld_co_sp` khi gọi lại `_rank_candidates()` trong vòng
    lặp) còn sót, vòng lặp thứ 2 sẽ chọn nhầm người biết SP (vì tie-break rơi
    xuống `position`) -> sinh `multi_sp` giả. Xác nhận KHÔNG còn."""
    staff = [
        (9, "LD SP", "truong_phong", 1, 0, 1),    # LD duy nhất, biết SP
        (41, "NV 41", "chuyen_vien", 1, 0, 1),    # biết SP, position NHỎ (dễ bị chọn nếu bug)
        (42, "NV 42", "chuyen_vien", 1, 0, 2),    # biết SP, position NHỎ
        (43, "NV 43", "chuyen_vien", 0, 0, 3),    # không biết SP, position LỚN hơn
        (44, "NV 44", "chuyen_vien", 0, 0, 4),    # không biết SP, position LỚN hơn
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    shifts, warnings = _generate_ca(db, "2026-08-12", YEAR, "LD", "NV", "normal", random.Random(0))

    assert shifts, "đủ người, phải lập được ca"
    s = shifts[0]
    assert s["sp_warning"] != "multi_sp", (
        f"multi_sp GIẢ tái xuất hiện — bug 'thiếu tranh_sp' trong vòng lặp "
        f"_chia_nhan_vien() đã quay lại: {_members(s)}, sp_warning={s['sp_warning']!r}")
    assert not any(w["type"] == "multi_sp" for w in warnings)
    assert 43 in _members(s) and 44 in _members(s), (
        f"lẽ ra phải chọn 2 người KHÔNG biết SP (43,44) vì Lãnh đạo đã giữ vai, "
        f"nhưng lại chọn nhầm người biết SP: {_members(s)}")


# ══════════════════════════════════════════════════════════════
# 4. Kịch bản GỐC của người dùng — 2 cặp cố định CÙNG LÚC (thứ Hai: Trang +
#    Trung; thứ Ba: Dũng + Hoàng Lan Anh), 3 tuần liên tiếp, TRONG CÙNG 1
#    PHÒNG (chung pool dự bị) — đúng hình dạng phàn nàn gốc, không phải 1 cặp
#    đơn lẻ như test B0 của coder.
# ══════════════════════════════════════════════════════════════

def test_kich_ban_that_2_cap_co_dinh_dong_thoi_thu_hai_va_thu_ba():
    """Lịch sử 2 tuần (03-04/08 và 10-11/08): thứ Hai luôn (Trang, Trung);
    thứ Ba luôn (Dũng, Hoàng Lan Anh) — đúng như người dùng mô tả 3 tuần liền.
    Tuần thứ 3 (17-18/08), sinh cả thứ Hai lẫn thứ Ba với CHUNG 1 pool dự bị —
    thuật toán mới phải phá được CẢ HAI cặp cùng lúc, không chỉ cặp coder đã
    test riêng lẻ."""
    staff = [
        (2, "LD Hai", "pho_phong", 0, 0, 2),
        (9, "LD Chín", "truong_phong", 0, 0, 9),
        (51, "Trang", "chuyen_vien", 0, 0, 51),
        (52, "Trung", "chuyen_vien", 0, 0, 52),
        (53, "Dũng", "chuyen_vien", 0, 0, 53),
        (54, "Hoàng Lan Anh", "chuyen_vien", 0, 0, 54),
        (55, "NV 55", "chuyen_vien", 0, 0, 55),
        (56, "NV 56", "chuyen_vien", 0, 0, 56),
        (57, "NV 57", "chuyen_vien", 0, 0, 57),
        (58, "NV 58", "chuyen_vien", 0, 0, 58),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2)
    _insert_shift(db, "2026-08-03", "normal", [2], [51, 52])   # thứ Hai
    _insert_shift(db, "2026-08-10", "normal", [2], [51, 52])   # thứ Hai, liền kề
    _insert_shift(db, "2026-08-04", "normal", [2], [53, 54])   # thứ Ba
    _insert_shift(db, "2026-08-11", "normal", [2], [53, 54])   # thứ Ba, liền kề

    shifts_mon, warn_mon = _generate_ca(
        db, "2026-08-17", YEAR, "LD", "NV", "normal", random.Random(0))
    assert shifts_mon, "thứ Hai 17/08: đủ người dự bị, phải lập được ca"
    mon_members = set(_members(shifts_mon[0]))
    assert not ({51, 52} <= mon_members), (
        f"cặp Trang+Trung (thứ Hai) vẫn lặp lần thứ 3 liên tiếp: {mon_members}")

    shifts_tue, warn_tue = _generate_ca(
        db, "2026-08-18", YEAR, "LD", "NV", "normal", random.Random(0))
    assert shifts_tue, "thứ Ba 18/08: đủ người dự bị, phải lập được ca"
    tue_members = set(_members(shifts_tue[0]))
    assert not ({53, 54} <= tue_members), (
        f"cặp Dũng+Hoàng Lan Anh (thứ Ba) vẫn lặp lần thứ 3 liên tiếp: {tue_members}")

    # Cả 2 ngày đều phải KHÔNG bị buộc lặp thứ (đủ người thay thế, không phải
    # "hết cách nên đành lặp")
    assert not any(w["type"] in ("qua_2_thu_thang", "thu_lien_tiep") for w in warn_mon)
    assert not any(w["type"] in ("qua_2_thu_thang", "thu_lien_tiep") for w in warn_tue)


# ══════════════════════════════════════════════════════════════
# 5. Q4 qua ĐƯỜNG ENGINE THẬT — sinh ca quyết toán (có nhóm phụ) rồi soi ma
#    trận `_ma_tran_di_cung_nv()`, không chỉ insert DB trực tiếp như file B7
#    của coder (`tests/test_duty_ma_tran_di_cung_nv_2026_09_18.py`).
# ══════════════════════════════════════════════════════════════

def test_ma_tran_di_cung_khong_dinh_nv_phu_qua_ca_quyet_toan_that():
    """Sinh 1 ca quyết toán THẬT qua `_generate_ngay_dac_biet()` (2 trực chính
    + 2 trực phụ), lưu xuống DB bằng `_save_shift()` (đúng đường dữ liệu thật,
    không phải insert tay mô phỏng), rồi soi `_ma_tran_di_cung_nv()`: chỉ CẶP
    trong nhóm CHÍNH được đếm, KHÔNG người nào trong nhóm PHỤ xuất hiện ở bất
    kỳ cặp nào — kể cả cặp phụ-phụ hay phụ-chính."""
    staff = [
        (2, "LD Hai", "pho_phong", 0, 0, 2),
        (61, "NV 61", "chuyen_vien", 0, 0, 61),
        (62, "NV 62", "chuyen_vien", 0, 0, 62),
        (63, "NV 63", "chuyen_vien", 0, 0, 63),
        (64, "NV 64", "chuyen_vien", 0, 0, 64),
        (65, "NV 65", "chuyen_vien", 0, 0, 65),
    ]
    db = _make_db(staff, ld_count=1, nv_count=2, qt_ld=1, qt_chinh=2, qt_phu=2)
    db.execute("INSERT INTO duty_special_days (date, day_type, is_confirmed) "
               "VALUES ('2026-08-14','settlement',1)")
    db.commit()
    shifts, warns = _generate_ngay_dac_biet(
        db, "2026-08-14", YEAR, "settlement_main", "LD", "NV", random.Random(0))
    assert shifts, "đủ người, phải lập được ca quyết toán"
    s = shifts[0]
    for sd in shifts:
        _save_shift(db, sd)
    db.commit()

    chinh_ids = set(json.loads(s["nv_ids"])) | ({s["sp_id"]} if s["sp_id"] else set())
    phu_ids = set(json.loads(s["nv_phu_ids"]))
    assert len(chinh_ids) == 2 and len(phu_ids) == 2, (
        f"cấu hình khai 2 chính + 2 phụ, thực tế chính={chinh_ids} phụ={phu_ids}")

    matrix = _ma_tran_di_cung_nv(db, YEAR)
    for cap, n in matrix.items():
        assert not (set(cap) & phu_ids), (
            f"người trực PHỤ {set(cap) & phu_ids} lọt vào ma trận đi-cùng qua "
            f"đường engine thật — vi phạm Q4: {matrix}")
    a, b = sorted(chinh_ids)
    assert matrix.get((a, b)) == 1, (
        f"cặp trực CHÍNH {(a, b)} phải được đếm đúng 1 lần: {matrix}")


# ══════════════════════════════════════════════════════════════
# 6. Regression — 5 test PLAN.md mục 2 dặn "cần canh" khi sửa bước kéo SP.
#    Chạy lại đúng những test này (không viết lại, chỉ xác nhận còn xanh sau
#    khi Giai đoạn 2 ghép logic chọn tuần tự vào cùng chỗ).
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("ten_test", [
    "test_thu_sau_tat_dinh_khong_phu_thuoc_seed",
    "test_tranh_du_song_phuong_khong_duoc_de_len_can_bang",
    "test_khong_vo_hai_lanh_dao_cung_biet_song_phuong",
    "test_moi_ca_chi_co_dung_mot_nguoi_song_phuong",
    "test_mo_phong_3_thang_giu_dong_thoi_ca_3_luat",
])
def test_5_test_plan_canh_van_ton_tai_sau_giai_doan_2(ten_test):
    """Không chạy lại logic (đã chạy trong test_duty_scheduler_algorithm.py),
    chỉ xác nhận cả 5 tên hàm PLAN.md mục 2 liệt kê CÒN TỒN TẠI đúng tên sau
    khi coder sửa — phòng trường hợp ai đó vô tình đổi tên/xoá khi refactor
    B9 mà không cập nhật PLAN. Bản thân việc PASS/FAIL của 5 test này được
    xác nhận trực tiếp bằng cách chạy pytest lên toàn file, ghi số liệu vào
    TEST_REPORT.md — test này chỉ là lưới an toàn chống "biến mất âm thầm"."""
    import test_duty_scheduler_algorithm as mod
    assert hasattr(mod, ten_test), (
        f"{ten_test} — 1 trong 5 test PLAN.md mục 2 dặn cần canh — không còn "
        f"tồn tại trong tests/test_duty_scheduler_algorithm.py")
