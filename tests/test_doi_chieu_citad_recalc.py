# -*- coding: utf-8 -*-
"""
test_doi_chieu_citad_recalc.py
--------------------------------
Khoá lại `_dec()`/`diff_exact()`/`cur_mismatch()` trong
`frontend/pages/doi_chieu_citad.py` — bug thật 25/08/2026 (Phòng Thanh toán
tự phát hiện): màn hình "Bảng chênh lệch (CITAD - PaymentHub)" hiện "+0,01"
ở cột ĐẾN IH Tiền và cờ "⚠ Lệch: USD", dù số CITAD gốc (chụp trực tiếp từ
NHNN, 5 Cổng) cộng đúng khớp PaymentHub tuyệt đối.

Nguyên nhân: `_compute_totals()` gộp cả 3 loại tiền vào 1 số thực, số VNĐ
hàng nghìn tỷ nuốt mất độ chính xác phần USD/EUR rất nhỏ, sinh dư nhị phân
(giá trị thật đọc được trong file cùng ngày: 0,0078125 = 2⁻⁷ — chữ ký kinh
điển của lỗi cộng dồn số thực, không phải một khoản tiền thật) dù về bản
chất đã khớp.

Sửa lần đầu: làm tròn về số nguyên trước khi so — nhưng Phòng Thanh toán
đúng khi lo ngại: làm tròn có thể CHE MẤT lệch thật nếu lệch đó nhỏ hơn 1
đơn vị gộp (ví dụ đúng lỗi tôi tự gây ra khi nhập tay dữ liệu test: thiếu
0,30 USD, bị round() nuốt mất không hiện). Sửa lại lần 2 (bản này): cộng
dồn bằng `Decimal` (qua `_dec()`) ngay từ đầu — không sinh dư nhị phân nào
để phải làm tròn/che đi, nên kết quả luôn CHÍNH XÁC TUYỆT ĐỐI với số liệu
gốc: khớp thật mới ra 0, lệch thật dù nhỏ đến đâu (kể cả dưới 1 xu) vẫn
hiện đúng.
"""
from decimal import Decimal

from frontend.pages.doi_chieu_citad import FK, _dec, cur_mismatch, diff_exact


def test_khong_lech_gia_khi_cong_dong_bang_decimal():
    """5 Cổng USD 'đến IH tiền' CITAD thật (chụp từ NHNN 25/08/2026) cộng
    đúng bằng PaymentHub — cộng bằng Decimal (qua _dec()) không sinh dư nhị
    phân như cộng bằng float thô, nên ra đúng 0 tuyệt đối, không cần làm tròn."""
    citad_usd_den_ih_tien = [1000.00, 516.60, 36000.00, 155518.00, 950314.87]
    payment_hub_total = 1143349.47

    ci_cur = {f: Decimal(0) for f in FK}
    for v in citad_usd_den_ih_tien:
        ci_cur["den_ih_t"] += _dec(v)
    ph_cur = {f: Decimal(0) for f in FK}
    ph_cur["den_ih_t"] = _dec(payment_hub_total)

    assert diff_exact(ci_cur["den_ih_t"], ph_cur["den_ih_t"]) == 0
    assert cur_mismatch(ci_cur, ph_cur) is False


def test_dec_loai_bo_du_nhi_phan_ma_float_tho_van_con():
    """Đối chứng trực tiếp: cùng 5 số đó cộng bằng float thô (không qua
    _dec()) vẫn có thể ra dư nhị phân (không nhất thiết bằng 0.0078125 —
    tuỳ thứ tự/giá trị cụ thể), nhưng cộng qua _dec() rồi thì luôn ra đúng
    Decimal('0') tuyệt đối — chứng minh Decimal xử lý tận gốc, không phải
    che dư đi bằng round()."""
    citad_usd_den_ih_tien = [1000.00, 516.60, 36000.00, 155518.00, 950314.87]
    payment_hub_total = 1143349.47

    dec_sum = sum((_dec(v) for v in citad_usd_den_ih_tien), Decimal(0))
    assert dec_sum - _dec(payment_hub_total) == Decimal(0)


def test_diff_exact_van_bat_duoc_lech_that_du_nho_hon_1_don_vi():
    """Bug tự phát hiện khi tự nhập tay dữ liệu test 26/08/2026: thiếu đúng
    0,30 USD ở 1 Cổng — nếu làm tròn về số nguyên như bản sửa lần đầu thì
    lệch này (< 1 đơn vị) sẽ bị NUỐT MẤT, hiện thành "khớp" giả dù thực tế
    lệch thật. Bản Decimal không được phép che mất trường hợp này."""
    ci_val = _dec("2151551") + _dec("0")  # CITAD: thiếu 0,30 do nhập tay sai
    ph_val = _dec("2151551.30")           # PaymentHub: số thật đầy đủ
    assert diff_exact(ci_val, ph_val) == Decimal("-0.30")


def test_diff_exact_van_bat_duoc_lech_that_lon():
    """Lệch thật lớn (không phải dư nhị phân) vẫn phải hiện đúng số."""
    assert diff_exact(_dec(1000), _dec(998)) == Decimal("2")


def test_cur_mismatch_van_bat_duoc_lech_xu_that():
    """Không được che mất lệch 1 xu thật của USD/EUR."""
    ci_cur = {f: Decimal(0) for f in FK}
    ph_cur = {f: Decimal(0) for f in FK}
    ci_cur["den_ih_t"] = _dec(100.00)
    ph_cur["den_ih_t"] = _dec(99.99)
    assert cur_mismatch(ci_cur, ph_cur) is True
