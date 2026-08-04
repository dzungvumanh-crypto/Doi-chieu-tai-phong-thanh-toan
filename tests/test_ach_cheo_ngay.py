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
from backend.services.ach.pipeline import (
    _tim_file_ngoai_output, _tim_file_thua_t2, _tim_di_zip_ngay_khac,
)


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


class TestTimDiZipNgayKhac:
    """2026-08-04 — dò *_DI_*.zip ở thư mục ANH EM (cùng cha) với input_dir, phục
    vụ tra REFHUB bổ sung từ ngày khác ở Checkpoint Bước 2."""

    def test_tim_thay_file_o_thu_muc_anh_em(self, tmp_path):
        parent = tmp_path
        ngay_a = parent / '31.07'
        ngay_b = parent / '01.08'
        ngay_a.mkdir()
        ngay_b.mkdir()
        f = ngay_a / 'doichieugd_20260731__01_DI_9999_N.zip'
        f.write_bytes(b'x')

        ket_qua = _tim_di_zip_ngay_khac(str(ngay_b))
        assert ket_qua == [str(f)]

    def test_khong_lay_file_cua_chinh_thu_muc_dang_chay(self, tmp_path):
        ngay_a = tmp_path / '31.07'
        ngay_a.mkdir()
        (ngay_a / 'doichieugd_20260731__01_DI_9999_N.zip').write_bytes(b'x')

        assert _tim_di_zip_ngay_khac(str(ngay_a)) == []

    def test_khong_co_thu_muc_anh_em_tra_ve_rong(self, tmp_path):
        ngay_a = tmp_path / '31.07'
        ngay_a.mkdir()
        assert _tim_di_zip_ngay_khac(str(ngay_a)) == []

    def test_gop_nhieu_thu_muc_anh_em(self, tmp_path):
        parent = tmp_path
        (parent / '31.07').mkdir()
        (parent / '01.08').mkdir()
        (parent / '02.08').mkdir()
        f1 = parent / '31.07' / 'doichieugd_20260731__01_DI_9999_N.zip'
        f2 = parent / '01.08' / 'doichieugd_20260801__01_DI_9999_N.zip'
        f1.write_bytes(b'x')
        f2.write_bytes(b'y')

        ket_qua = _tim_di_zip_ngay_khac(str(parent / '02.08'))
        assert sorted(ket_qua) == sorted([str(f1), str(f2)])


# ── Đọc file T-2 dạng .xlsx (người chấm tự sửa tay) ──────────────────────────
# 2026-08-03: Business Owner cần nạp lại file T-2 đã tự sửa tay (khi kết quả
# chương trình tự xuất bị sai) — file .xlsx, tên bắt đầu "MIS đi thừa"/"MIS đến
# thừa", KHÔNG phải file .csv chương trình tự xuất.

class TestDocFileT2Xlsx:
    def test_doc_mis_di_thua_t2_xlsx_dung_cau_truc(self, tmp_path):
        path = tmp_path / 'MIS đi thừa (không bao gồm OSB) ngày 26.07.xlsx'
        pd.DataFrame([_mis_di_thua_t2_row('1240', 3_000_000, '000142755985')]).to_excel(path, index=False)
        df = doc_mis_di_thua_t2(str(path))
        assert len(df) == 1

    def test_doc_mis_den_thua_t2_xlsx_dung_cau_truc(self, tmp_path):
        path = tmp_path / 'MIS đến thừa ngày 26.07 (không bao gồm OSB).xlsx'
        pd.DataFrame([_mis_den_thua_t2_row('1240', 3_000_000, '000142755985')]).to_excel(path, index=False)
        df = doc_mis_den_thua_t2(str(path))
        assert len(df) == 1

    def test_doc_mis_di_thua_t2_xlsx_thieu_cot_bao_loi_ro(self, tmp_path):
        path = tmp_path / 'MIS đi thừa ngày 26.07.xlsx'
        pd.DataFrame([{'CHI_NHANH': '1240'}]).to_excel(path, index=False)
        with pytest.raises(ValueError, match='thiếu cột'):
            doc_mis_di_thua_t2(str(path))

    def test_khop_khoa_dau_cuoi_khong_bi_lech_do_doc_excel(self, tmp_path):
        """Bài test thật cho rủi ro '.0': ghi TRACE/SO_TIEN dạng SỐ (không phải
        chuỗi) vào .xlsx qua to_excel() — giống hệt cách Business Owner mở/lưu
        file bằng Excel — rồi xác nhận khóa vẫn khớp đúng NPO_đi thừa tương ứng."""
        df_npo = pd.DataFrame([_npo_di_thua_row('1240', '142755985', 3_000_000)])
        path = tmp_path / 'MIS đi thừa ngày 26.07.xlsx'
        pd.DataFrame([{
            'CHI_NHANH': 1240, 'SO_TIEN': 3_000_000, 'TRACE': 142755985, 'SE_TRACE': None,
            'NGAY_KENH_TRA': '26/07/2026 10:00:00', 'LOAI_LENH_OSB': '',
        }]).to_excel(path, index=False)
        mis_t2 = doc_mis_di_thua_t2(str(path))
        ket_qua = danh_dau_da_can_di(df_npo, mis_t2)
        assert ket_qua.loc[0, 'GHI_CHU_T2'] == GHI_CHU_T2


# ── Dò file T-2 qua nhiều pattern (máy tự xuất .csv lẫn người chấm tự đặt tên
# .xlsx) — phải phân biệt được với file OSB thừa (Điểm 2, cấu trúc cột giống
# hệt nhưng KHÔNG phải input T-2) chỉ bằng TÊN file, không suy đoán nội dung.

class TestTimFileThuaT2:
    def test_khop_pattern_may_tu_xuat_csv(self, tmp_path):
        f = tmp_path / 'MIS_DI_THUA_20260726.csv'
        f.write_text('x')
        ket_qua = _tim_file_thua_t2(str(tmp_path), ['MIS_DI_THUA*.csv', 'MIS đi thừa*.xlsx'])
        assert ket_qua == [str(f)]

    def test_khop_pattern_nguoi_cham_tu_dat_ten_xlsx(self, tmp_path):
        f = tmp_path / 'MIS đi thừa (không bao gồm OSB) ngày 26.07.xlsx'
        f.write_text('x')
        ket_qua = _tim_file_thua_t2(str(tmp_path), ['MIS_DI_THUA*.csv', 'MIS đi thừa*.xlsx'])
        assert ket_qua == [str(f)]

    def test_khong_nham_voi_file_osb_thua_cung_thu_muc(self, tmp_path):
        (tmp_path / 'OSB đi thừa ngày 26.07.xlsx').write_text('x')
        ket_qua = _tim_file_thua_t2(str(tmp_path), ['MIS_DI_THUA*.csv', 'MIS đi thừa*.xlsx'])
        assert ket_qua == []

    def test_khong_trung_lap_khi_2_pattern_cung_khop_1_file(self, tmp_path):
        f = tmp_path / 'MIS_DI_THUA_20260726.csv'
        f.write_text('x')
        ket_qua = _tim_file_thua_t2(str(tmp_path), ['MIS_DI_THUA*.csv', 'MIS_DI_THUA*.csv'])
        assert ket_qua == [str(f)]
