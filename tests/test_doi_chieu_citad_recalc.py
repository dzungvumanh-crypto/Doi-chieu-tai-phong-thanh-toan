# -*- coding: utf-8 -*-
"""
test_doi_chieu_citad_recalc.py
--------------------------------
Khoá lại `diff_rounded()`/`cur_mismatch()` trong
`frontend/pages/doi_chieu_citad.py` — bug thật 25/08/2026 (Phòng Thanh toán
tự phát hiện): màn hình "Bảng chênh lệch (CITAD - PaymentHub)" hiện "+0,01"
ở cột ĐẾN IH Tiền và cờ "⚠ Lệch: USD", dù số CITAD gốc (chụp trực tiếp từ
NHNN, 5 Cổng) cộng đúng khớp PaymentHub tuyệt đối.

Nguyên nhân: `_compute_totals()` gộp cả 3 loại tiền vào 1 số thực, số VNĐ
hàng nghìn tỷ nuốt mất độ chính xác phần USD/EUR rất nhỏ, sinh dư nhị phân
(giá trị thật đọc được trong file cùng ngày: 0,0078125 = 2⁻⁷ — chữ ký kinh
điển của lỗi cộng dồn số thực, không phải một khoản tiền thật) dù về bản
chất đã khớp. `recalc()` so `== 0`/`!=` bằng số thực thô nên hiện lệch giả.

Test dựng lại đúng 5 số CITAD thật (ảnh chụp Bảng kê giao dịch ngoại tệ
NHNN, USD, Đến, 25/08/2026) và số PaymentHub thật, xác nhận sau khi làm
tròn thì không còn lệch giả.
"""
from frontend.pages.doi_chieu_citad import FK, cur_mismatch, diff_rounded


def test_khong_lech_gia_khi_cong_dong_so_thuc_that_khop():
    """5 Cổng USD 'đến IH tiền' CITAD thật (chụp từ NHNN 25/08/2026) cộng
    đúng bằng PaymentHub — nhưng cộng bằng số thực có thể sinh dư nhị phân,
    trước khi làm tròn. Test khoá 2 việc: diff_rounded() ra đúng 0, và
    cur_mismatch() không báo lệch."""
    citad_usd_den_ih_tien = [1000.00, 516.60, 36000.00, 155518.00, 950314.87]
    payment_hub_total = 1143349.47

    ci_cur = {f: 0.0 for f in FK}
    for v in citad_usd_den_ih_tien:
        ci_cur["den_ih_t"] += v
    ph_cur = {f: 0.0 for f in FK}
    ph_cur["den_ih_t"] = payment_hub_total

    assert diff_rounded(ci_cur["den_ih_t"], ph_cur["den_ih_t"]) == 0
    assert cur_mismatch(ci_cur, ph_cur) is False


def test_diff_rounded_bo_du_nhi_phan_nho_hon_nua_don_vi():
    """Dư nhị phân thật đã ghi nhận trong file 25/08/2026: 0,0078125 (2⁻⁷).
    Số tiền/số món luôn là số nguyên nên phải làm tròn về 0, không phải một
    khoản chênh lệch thật."""
    assert diff_rounded(43462772025396.48, 43462772025396.48 - 0.0078125) == 0


def test_diff_rounded_van_bat_duoc_lech_that():
    """Không được làm tròn che mất lệch thật — lệch từ 1 trở lên vẫn phải
    hiện đúng, không phải luôn-0."""
    assert diff_rounded(1000, 998) == 2


def test_cur_mismatch_van_bat_duoc_lech_xu_that():
    """Không được làm tròn che mất lệch 1 xu thật của USD/EUR — chỉ bỏ dư
    dưới mức xu, giữ nguyên lệch từ 1 xu trở lên."""
    ci_cur = {f: 0.0 for f in FK}
    ph_cur = {f: 0.0 for f in FK}
    ci_cur["den_ih_t"] = 100.00
    ph_cur["den_ih_t"] = 99.99
    assert cur_mismatch(ci_cur, ph_cur) is True
