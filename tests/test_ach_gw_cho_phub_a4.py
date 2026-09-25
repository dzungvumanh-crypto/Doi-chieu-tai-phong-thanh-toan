"""Test A4 (23/09/2026) — cột NGAY_DOI_CHIEU (C-N) ghi vào TIMEOUT_KHONG_KENH_*.csv/
GW_CHO_PHUB_*.csv (xem `main_from_dir()` trong pipeline.py — test end-to-end xuất
file ở tests/test_ach_chay_gian_luoc.py::TestGwChoPhubA4).

File này kiểm RIÊNG rủi ro #4 của PLAN.md mục 4.3 — TIMEOUT_KHONG_KENH_*.csv còn
là INPUT của chính Mục 8 (`doc_timeout_cu()`/`doi_chieu_timeout_cu()`) ở lượt chạy
KẾ TIẾP, cột mới thêm có thể lọt vào sheet kết quả Mục 8. Ba test bắt buộc theo
PLAN.md:
(a) file CÓ cột mới vẫn đọc/khớp được, kết quả giống hệt file KHÔNG có cột mới.
(b) file CŨ (không có cột mới) vẫn đọc được — cột mới KHÔNG bắt buộc.
(c) sheet kết quả Mục 8 (`xuat_excel_timeout_cu`) không lỗi khi df có cột mới.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_gw_cho_phub_a4.py -v
"""
import openpyxl
import pandas as pd

from backend.services.ach.b11_doi_chieu_cheo_ngay import doc_timeout_cu
from backend.services.ach.b12_ghi_chu_timeout import doi_chieu_timeout_cu
from backend.services.ach.pipeline import xuat_excel_timeout_cu

_COLS_CO_BAN = ['CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN', 'NGAY_GIAO_DICH']


def _timeout_cu_row(ngay_doi_chieu=None):
    row = {
        'CHI_NHANH': '1240', 'TRACE': '000142755985', 'SE_TRACE': '',
        'SO_TIEN': '1000000', 'NGAY_GIAO_DICH': '03/09/2026',
    }
    if ngay_doi_chieu is not None:
        row['NGAY_DOI_CHIEU'] = ngay_doi_chieu
    return row


def _npo_di_thua_row(key_di):
    return {'KEY_DI': key_di, 'TRBRCD': '1240', 'CRAMOUNT': 1_000_000}


class TestDocTimeoutCuChapNhanCotMoi:
    """(b) — file CŨ (không có NGAY_DOI_CHIEU) vẫn đọc được, cột mới KHÔNG bắt buộc."""

    def test_file_khong_co_cot_moi_doc_binh_thuong(self, tmp_path):
        path = tmp_path / 'TIMEOUT_KHONG_KENH_20260901.csv'
        pd.DataFrame([_timeout_cu_row()]).to_csv(path, index=False, encoding='utf-8-sig')

        df = doc_timeout_cu(str(path))

        assert 'NGAY_DOI_CHIEU' not in df.columns
        assert len(df) == 1

    def test_file_co_cot_moi_doc_binh_thuong_giu_nguyen_cot(self, tmp_path):
        """(a phần 1) — file MỚI (có NGAY_DOI_CHIEU) đọc được, cột được giữ lại
        nguyên vẹn (không bị loại bỏ ở tầng đọc)."""
        path = tmp_path / 'TIMEOUT_KHONG_KENH_20260901.csv'
        pd.DataFrame([_timeout_cu_row('20260901')]).to_csv(path, index=False, encoding='utf-8-sig')

        df = doc_timeout_cu(str(path))

        assert 'NGAY_DOI_CHIEU' in df.columns
        assert df['NGAY_DOI_CHIEU'].iloc[0] == '20260901'


class TestDoiChieuTimeoutCuKetQuaKhongDoiDuCoCotMoi:
    """(a) — kết quả khớp (TT_DOI_CHIEU/GHI_CHU) GIỐNG HỆT dù file input có hay
    không có cột NGAY_DOI_CHIEU — cột chỉ mang tính thông tin, không ảnh hưởng
    logic khớp."""

    def test_ket_qua_giong_het(self, tmp_path):
        key_hub = '1240' + '142755985' + '1000000'
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row(key_hub)])

        path_moi = tmp_path / 'TIMEOUT_KHONG_KENH_20260901.csv'
        pd.DataFrame([_timeout_cu_row('20260901')]).to_csv(path_moi, index=False, encoding='utf-8-sig')
        path_cu = tmp_path / 'TO_ko_di_kenh_ngay_cu.csv'
        pd.DataFrame([_timeout_cu_row()]).to_csv(path_cu, index=False, encoding='utf-8-sig')

        df_moi = doc_timeout_cu(str(path_moi))
        df_cu  = doc_timeout_cu(str(path_cu))

        out_moi, _, _ = doi_chieu_timeout_cu(df_moi, df_npo_di_thua.copy(), None, None)
        out_cu,  _, _ = doi_chieu_timeout_cu(df_cu,  df_npo_di_thua.copy(), None, None)

        assert out_moi['TT_DOI_CHIEU'].tolist() == out_cu['TT_DOI_CHIEU'].tolist()
        assert out_moi['KEY_HUB'].tolist() == out_cu['KEY_HUB'].tolist()
        # Số dòng/khoá không đổi — cột mới không tạo thêm/bớt dòng nào.
        assert len(out_moi) == len(out_cu) == 1


class TestXuatExcelTimeoutCuChiuDuocCotMoi:
    """(c) — sheet kết quả Mục 8 không lỗi khi df_timeout_cu_ketqua có cột
    NGAY_DOI_CHIEU. Cột này SẼ xuất hiện thêm trên sheet (xuat_excel_timeout_cu()
    ghi TOÀN BỘ cột của df, không whitelist) — đây là hệ quả ĐÃ BIẾT (PLAN.md mục
    4.3), không tự ý ẩn/xoá cột khi chưa hỏi lại người dùng."""

    def test_khong_loi_va_cot_moi_xuat_hien_tren_sheet(self, tmp_path):
        df_ketqua = pd.DataFrame([
            {'KEY_HUB': 'K1', 'CHI_NHANH': '1240', 'SO_TIEN': '1000000',
             'NGAY_GIAO_DICH': '03/09/2026', 'NGAY_DOI_CHIEU': '20260901',
             'TT_DOI_CHIEU': 'Không có'},
        ])
        out_dir = tmp_path / 'out'
        out_dir.mkdir()

        path = xuat_excel_timeout_cu(str(out_dir), __import__('datetime').datetime(2026, 9, 2), df_ketqua)

        assert path is not None
        wb = openpyxl.load_workbook(path)
        header = [c.value for c in next(wb['TIMEOUT_CU_KETQUA'].iter_rows(min_row=1, max_row=1))]
        assert 'NGAY_DOI_CHIEU' in header
        assert 'TT_DOI_CHIEU' in header
