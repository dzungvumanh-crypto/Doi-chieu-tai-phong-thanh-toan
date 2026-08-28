# -*- coding: utf-8 -*-
"""
test_doi_chieu_citad_matched_status.py
--------------------------------------
Khoá lại `is_reconciliation_matched()` trong
`backend/services/doi_chieu_citad_service.py` — dùng bởi
`get_reconciliation_status()` để Sổ trực cuối ngày cảnh báo "chưa đối
chiếu"/"chưa khớp". Cùng bug đã rà soát ở `build_xlsx()` (dòng Chênh lệch
Excel) và `recalc()`/`cur_mismatch()` (bảng chênh lệch trên màn hình,
`frontend/pages/doi_chieu_citad.py`): `ci`/`ph` gộp cả 3 loại tiền vào 1 số
thực, cộng dồn 5 Cổng + Napas + PSS-MDP có thể sinh dư nhị phân dù về bản
chất đã khớp tuyệt đối — hàm này so `==` trên số thực thô nên sẽ báo
"chưa khớp" giả, khiến Sổ trực cảnh báo nhầm.
"""
from backend.services.doi_chieu_citad_service import is_reconciliation_matched

FK = ['di_ih_m', 'di_ih_t', 'di_il_m', 'di_il_t', 'den_ih_m', 'den_ih_t', 'den_il_m', 'den_il_t']
CONGS = [1, 9, 18, 17, 12]
CURS = ['VNĐ', 'USD', 'EUR']


def _sess(**over) -> dict:
    gD = {str(c): {u: {f: 0.0 for f in FK} for u in CURS} for c in CONGS}
    phD = {u: {f: 0.0 for f in FK} for u in CURS}
    sess = dict(gD=gD, phD=phD, napas_m=0, napas_t=0, pssmdp_m=0, pssmdp_t=0)
    sess.update(over)
    return sess


def test_khong_bao_chua_khop_gia_khi_cong_dong_so_thuc_that_khop():
    """Đúng ca thật 25/08/2026: 5 Cổng USD 'đến IH tiền' (số CITAD gốc chụp
    từ NHNN) cộng đúng bằng PaymentHub, nhưng cộng bằng số thực có thể sinh
    dư nhị phân trước khi làm tròn."""
    gD = {str(c): {u: {f: 0.0 for f in FK} for u in CURS} for c in CONGS}
    citad_usd_den_ih_tien = [1000.00, 516.60, 36000.00, 155518.00, 950314.87]
    for cong, v in zip(CONGS, citad_usd_den_ih_tien):
        gD[str(cong)]['USD']['den_ih_t'] = v
    phD = {u: {f: 0.0 for f in FK} for u in CURS}
    phD['USD']['den_ih_t'] = 1143349.47

    sess = dict(gD=gD, phD=phD, napas_m=0, napas_t=0, pssmdp_m=0, pssmdp_t=0)
    assert is_reconciliation_matched(sess) is True


def test_van_bao_chua_khop_khi_lech_that():
    """Không được làm tròn che mất lệch thật — Sổ trực vẫn phải cảnh báo
    đúng khi số liệu thực sự chưa khớp."""
    sess = _sess()
    sess["gD"]["1"]["VNĐ"]["den_ih_t"] = 1_000_000_000
    sess["phD"]["VNĐ"]["den_ih_t"] = 999_000_000  # lệch thật 1 triệu
    assert is_reconciliation_matched(sess) is False


def test_van_bao_chua_khop_khi_lech_that_du_nho_hon_1_don_vi():
    """Không được lấy làm tròn số nguyên làm cách sửa (như bản đầu tiên) —
    sẽ CHE MẤT lệch thật nếu nhỏ hơn 1 đơn vị. Decimal không được nuốt."""
    sess = _sess()
    sess["gD"]["1"]["USD"]["den_ih_t"] = 100
    sess["phD"]["USD"]["den_ih_t"] = 100.3  # lệch thật 0,3 USD
    assert is_reconciliation_matched(sess) is False
