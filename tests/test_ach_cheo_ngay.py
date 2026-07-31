"""Test thuật toán Điểm 4 — b11_doi_chieu_cheo_ngay.py (đối chiếu chéo ngày MIS
thừa T-2 ⟷ NPO thừa T-1, cả 2 chiều đi/đến).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_cheo_ngay.py -v
"""
import pandas as pd
import pytest

from backend.services.ach.b11_doi_chieu_cheo_ngay import (
    GHI_CHU_T2, danh_dau_da_can_di, danh_dau_da_can_den,
    doc_mis_di_thua_t2, doc_mis_den_thua_t2,
)
from backend.services.ach.pipeline import _tim_file_ngoai_output


# ── Fixtures dùng chung ─────────────────────────────────────────────────────

def _npo_di_thua_row(trbrcd, so_trace, cramount):
    key_di = trbrcd.strip() + so_trace + str(cramount)
    return {'TRBRCD': trbrcd, 'SO_TRACE': so_trace, 'CRAMOUNT': cramount, 'KEY_DI': key_di}


def _npo_den_thua_row(trbrcd, so_trace, dramount):
    key_den = trbrcd.strip() + so_trace + str(dramount)
    return {'TRBRCD': trbrcd, 'SO_TRACE': so_trace, 'DRAMOUNT': dramount, 'KEY_DEN': key_den}


def _mis_di_thua_t2_row(chi_nhanh, so_tien, trace, se_trace='', osb=''):
    return {
        'CHI_NHANH': chi_nhanh, 'SO_TIEN': str(so_tien), 'TRACE': trace, 'SE_TRACE': se_trace,
        'NGAY_KENH_TRA': '26/07/2026 10:00:00', 'LOAI_LENH_OSB': osb,
    }


def _mis_den_thua_t2_row(chi_nhanh, so_tien, trace, osb=''):
    return {'CHI_NHANH': chi_nhanh, 'SO_TIEN': str(so_tien), 'TRACE': trace, 'LOAI_LENH_OSB': osb}


# ── Chiều đi ─────────────────────────────────────────────────────────────────

class TestDanhDauDaCanDi:
    def test_khong_co_file_t2_them_cot_rong_khong_mat_dong(self):
        df = pd.DataFrame([_npo_di_thua_row('1240', '142755985', 3_000_000)])
        ket_qua = danh_dau_da_can_di(df, None)
        assert len(ket_qua) == 1
        assert list(ket_qua['GHI_CHU_T2']) == ['']

    def test_file_t2_rong_them_cot_rong(self):
        df = pd.DataFrame([_npo_di_thua_row('1240', '142755985', 3_000_000)])
        mis_t2 = pd.DataFrame(columns=['CHI_NHANH', 'SO_TIEN', 'TRACE', 'SE_TRACE', 'NGAY_KENH_TRA', 'LOAI_LENH_OSB'])
        ket_qua = danh_dau_da_can_di(df, mis_t2)
        assert list(ket_qua['GHI_CHU_T2']) == ['']

    def test_dong_khop_khoa_duoc_gan_ghi_chu(self):
        df = pd.DataFrame([_npo_di_thua_row('1240', '142755985', 3_000_000)])
        mis_t2 = pd.DataFrame([_mis_di_thua_t2_row('1240', 3_000_000, '000142755985')])
        ket_qua = danh_dau_da_can_di(df, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == GHI_CHU_T2

    def test_dong_khong_khop_giu_rong(self):
        df = pd.DataFrame([_npo_di_thua_row('1240', '142755985', 3_000_000)])
        mis_t2 = pd.DataFrame([_mis_di_thua_t2_row('9999', 1, '000000001')])
        ket_qua = danh_dau_da_can_di(df, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == ''

    def test_lenh_osb_bi_loai_khoi_input_t2_du_khoa_trung(self):
        """Dòng OSB (LOAI_LENH_OSB='O') phải bị loại khỏi MIS T-2 TRƯỚC khi so
        khớp — dù khóa trùng NPO_đi thừa, KHÔNG được đánh dấu Hạch toán T-2."""
        df = pd.DataFrame([_npo_di_thua_row('1300', '111', 6_000_000)])
        mis_t2 = pd.DataFrame([_mis_di_thua_t2_row('1300', 6_000_000, '000000111', osb='O')])
        ket_qua = danh_dau_da_can_di(df, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == ''

    def test_khong_lam_mat_hoac_them_dong(self):
        df = pd.DataFrame([
            _npo_di_thua_row('1240', '142755985', 3_000_000),
            _npo_di_thua_row('1300', '111', 6_000_000),
        ])
        mis_t2 = pd.DataFrame([_mis_di_thua_t2_row('1240', 3_000_000, '000142755985')])
        ket_qua = danh_dau_da_can_di(df, mis_t2)
        assert len(ket_qua) == len(df)


# ── Chiều đến ────────────────────────────────────────────────────────────────

class TestDanhDauDaCanDen:
    def test_khong_co_file_t2_them_cot_rong(self):
        df = pd.DataFrame([_npo_den_thua_row('1240', '142755985', 3_000_000)])
        ket_qua = danh_dau_da_can_den(df, None)
        assert list(ket_qua['GHI_CHU_T2']) == ['']

    def test_dong_khop_khoa_duoc_gan_ghi_chu(self):
        df = pd.DataFrame([_npo_den_thua_row('1240', '142755985', 3_000_000)])
        mis_t2 = pd.DataFrame([_mis_den_thua_t2_row('1240', 3_000_000, '000142755985')])
        ket_qua = danh_dau_da_can_den(df, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == GHI_CHU_T2

    def test_dong_khong_khop_giu_rong(self):
        df = pd.DataFrame([_npo_den_thua_row('1240', '142755985', 3_000_000)])
        mis_t2 = pd.DataFrame([_mis_den_thua_t2_row('9999', 1, '000000001')])
        ket_qua = danh_dau_da_can_den(df, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == ''

    def test_lenh_osb_den_bi_loai_khoi_input_t2_du_khoa_trung(self):
        """OSB chiều đến đánh dấu bằng chữ số '1' (khác chiều đi 'O') — xem
        osb_common.py::OSB_DEN_VALUE."""
        df = pd.DataFrame([_npo_den_thua_row('1300', '111', 6_000_000)])
        mis_t2 = pd.DataFrame([_mis_den_thua_t2_row('1300', 6_000_000, '000000111', osb='1')])
        ket_qua = danh_dau_da_can_den(df, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == ''

    def test_khong_lam_mat_hoac_them_dong(self):
        df = pd.DataFrame([
            _npo_den_thua_row('1240', '142755985', 3_000_000),
            _npo_den_thua_row('1300', '111', 6_000_000),
        ])
        ket_qua = danh_dau_da_can_den(df, None)
        assert len(ket_qua) == len(df)


# ── Đọc file CSV T-2 ─────────────────────────────────────────────────────────

class TestDocFileT2:
    def test_doc_mis_di_thua_t2_dung_cau_truc(self, tmp_path):
        path = tmp_path / 'MIS_DI_THUA_20260726.csv'
        pd.DataFrame([_mis_di_thua_t2_row('1240', 3_000_000, '000142755985')]).to_csv(path, index=False)
        df = doc_mis_di_thua_t2(str(path))
        assert len(df) == 1

    def test_doc_mis_di_thua_t2_thieu_cot_bao_loi_ro(self, tmp_path):
        path = tmp_path / 'MIS_DI_THUA_20260726.csv'
        pd.DataFrame([{'CHI_NHANH': '1240'}]).to_csv(path, index=False)
        with pytest.raises(ValueError, match='thiếu cột'):
            doc_mis_di_thua_t2(str(path))

    def test_doc_mis_den_thua_t2_dung_cau_truc(self, tmp_path):
        path = tmp_path / 'MIS_DEN_THUA_20260726.csv'
        pd.DataFrame([_mis_den_thua_t2_row('1240', 3_000_000, '000142755985')]).to_csv(path, index=False)
        df = doc_mis_den_thua_t2(str(path))
        assert len(df) == 1

    def test_doc_mis_den_thua_t2_thieu_cot_bao_loi_ro(self, tmp_path):
        path = tmp_path / 'MIS_DEN_THUA_20260726.csv'
        pd.DataFrame([{'CHI_NHANH': '1240'}]).to_csv(path, index=False)
        with pytest.raises(ValueError, match='thiếu cột'):
            doc_mis_den_thua_t2(str(path))


# ── Dò file T-2, loại trừ thư mục Output/ của chính lần chạy trước ────────────
# Bug thật phát hiện khi chạy trên dữ liệu G: thật (2026-07-31): glob đệ quy '**'
# bắt luôn MIS_DI_THUA*.csv cũ nằm trong <thư mục ngày>/Output/ — tự khớp nhầm
# với kết quả CHÍNH NÓ thay vì file T-2 thật của ngày hôm trước.

class TestTimFileNgoaiOutput:
    def test_loai_file_trong_thu_muc_output(self, tmp_path):
        (tmp_path / 'Output').mkdir()
        (tmp_path / 'Output' / 'MIS_DI_THUA_20260727.csv').write_text('x')
        assert _tim_file_ngoai_output(str(tmp_path), 'MIS_DI_THUA*.csv') == []

    def test_giu_file_ngoai_thu_muc_output(self, tmp_path):
        (tmp_path / 'Output').mkdir()
        (tmp_path / 'Output' / 'MIS_DI_THUA_20260727.csv').write_text('x')
        f = tmp_path / 'MIS_DI_THUA_20260726.csv'
        f.write_text('y')
        ket_qua = _tim_file_ngoai_output(str(tmp_path), 'MIS_DI_THUA*.csv')
        assert ket_qua == [str(f)]
