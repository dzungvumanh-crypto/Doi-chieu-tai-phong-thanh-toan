"""Test thuật toán Điểm 3 — b10_xu_ly_npo_di_thua.py::tach_dien_huy() (tách "điện
đi huỷ trong ngày"/"điện đi huỷ khác ngày" khỏi NPO_đi thừa).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_dien_huy.py -v
"""

import pandas as pd

from backend.services.ach.b10_xu_ly_npo_di_thua import tach_dien_huy


def _row(trbrcd, so_trace, cramount, trtp='Normal', reference=None):
    return {
        'TRBRCD': trbrcd, 'SO_TRACE': so_trace, 'CRAMOUNT': cramount, 'TRTP': trtp,
        'REFERENCE': reference or f'1000API{so_trace}',
    }


class TestHuyTrongNgay:
    def test_cap_2_dong_doi_ung_vao_huy_trong_ngay(self):
        df = pd.DataFrame([
            _row('1240', '142755985', 3000000, 'Normal'),
            _row('1240', '142755985', -3000000, 'Cancel'),
        ])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 2
        assert set(huy_trong_ngay['TRTP']) == {'Normal', 'Cancel'}
        assert len(huy_khac_ngay) == 0
        assert len(con_lai) == 0

    def test_nhom_3_dong_tong_bang_0_van_vao_huy_trong_ngay(self):
        """Mở "cặp 2 dòng" thành "nhóm >=2 dòng" — nhóm 3 dòng cùng CHECK_TRUNG,
        tổng CRAMOUNT = 0 vẫn được coi là huỷ trong ngày."""
        df = pd.DataFrame([
            _row('1240', '999', 5000000, 'Normal'),
            _row('1240', '999', -2000000, 'Cancel'),
            _row('1240', '999', -3000000, 'Cancel'),
        ])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 3
        assert len(huy_khac_ngay) == 0
        assert len(con_lai) == 0

    def test_dong_don_le_khong_bao_gio_vao_huy_trong_ngay(self):
        """1 dòng luôn có CRAMOUNT != 0 nên không thể tự tổng = 0 — dù là Cancel."""
        df = pd.DataFrame([_row('1240', '999', -3000000, 'Cancel')])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 0

    def test_cung_check_trung_nhung_tong_khac_0_khong_vao_huy_trong_ngay(self):
        df = pd.DataFrame([
            _row('1240', '999', 5000000, 'Normal'),
            _row('1240', '999', -3000000, 'Cancel'),
        ])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 0
        # Dòng Cancel không ghép được cặp -> rơi vào huỷ khác ngày (B3).
        assert len(huy_khac_ngay) == 1
        assert len(con_lai) == 1


class TestHuyKhacNgay:
    def test_cancel_khong_ghep_duoc_cap_vao_huy_khac_ngay(self):
        df = pd.DataFrame([_row('1300', '111', -6000000, 'Cancel')])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 0
        assert len(huy_khac_ngay) == 1
        assert len(con_lai) == 0

    def test_normal_khong_vao_huy_khac_ngay_du_khong_ghep_cap(self):
        df = pd.DataFrame([_row('1300', '111', 6000000, 'Normal')])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_khac_ngay) == 0
        assert len(con_lai) == 1


class TestBatBienSoHoc:
    def test_tong_3_phan_bang_dau_vao(self):
        df = pd.DataFrame([
            _row('1240', '142755985', 3000000, 'Normal'),
            _row('1240', '142755985', -3000000, 'Cancel'),
            _row('1300', '111', -6000000, 'Cancel'),
            _row('1400', '222', 900000, 'Normal'),
        ])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) + len(huy_khac_ngay) + len(con_lai) == len(df)
        assert set(huy_trong_ngay['SO_TRACE']) | set(huy_khac_ngay['SO_TRACE']) | set(con_lai['SO_TRACE']) \
            == set(df['SO_TRACE'])

    def test_khong_co_du_lieu_tra_ve_3_df_rong(self):
        df = pd.DataFrame(columns=['TRBRCD', 'SO_TRACE', 'CRAMOUNT', 'TRTP', 'REFERENCE'])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 0
        assert len(huy_khac_ngay) == 0
        assert len(con_lai) == 0

    def test_cramount_ngan_nghin_khong_lam_sai_nhom_huy(self):
        """Regression: CRAMOUNT dạng chuỗi ngăn-nghìn ('180.000'/'-180.000') phải
        vẫn nhóm đúng thành huỷ-trong-ngày, không bị to_numeric() cắt sai (180)
        khiến tổng nhóm != 0."""
        df = pd.DataFrame([
            _row('1240', '999', '180.000', 'Normal'),
            _row('1240', '999', '-180.000', 'Cancel'),
        ])
        huy_trong_ngay, huy_khac_ngay, con_lai = tach_dien_huy(df)
        assert len(huy_trong_ngay) == 2
        assert len(huy_khac_ngay) == 0
        assert len(con_lai) == 0
