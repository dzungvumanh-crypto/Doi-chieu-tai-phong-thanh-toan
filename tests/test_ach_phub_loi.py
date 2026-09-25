"""Test Mục 3 (bổ sung 11.09.2026, Thảo xác nhận ưu tiên làm 16.09.2026) —
b16_phub_loi.py: đối chiếu file pHub "Danh sách giao dịch chuyển tiền đi" với GW
đi (Bước 2 — cột Ghi chú chứa ACSP:NOAN/ACSP:AUTH/ACSC:AUTH) và với "TO ko đi
kênh" (Bước 3-6 — CN trace tiền).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_phub_loi.py -v
"""
import pandas as pd
import xlsxwriter

from backend.services.ach.b16_phub_loi import doc_phub, xu_ly_phub_loi
from backend.services.ach.pipeline import _tim_file_phub

_PHUB_COLS = ['STT', 'Chi nhánh', 'Số thành công', 'Số Trace 1', 'Số Trace 2',
              'Số tiền thực chuyển']


def _viet_file_phub(path, rows):
    """Mô phỏng đúng cấu trúc file thật: dòng 1 = tiêu đề gộp ô, dòng 2 = header
    thật (có 'Số thành công'), dòng 3+ = dữ liệu."""
    wb = xlsxwriter.Workbook(str(path))
    ws = wb.add_worksheet('Danh sách giao dịch chuyển tiền')
    ws.write(0, 1, 'DANH SÁCH GIAO DỊCH CHUYÊN TIỀN ĐI')
    ws.write_row(1, 0, _PHUB_COLS)
    for i, row in enumerate(rows, start=2):
        ws.write_row(i, 0, [row[c] for c in _PHUB_COLS])
    wb.close()


def _row_phub(stt='1', chi_nhanh='1400', so_thanh_cong='MSG1', trace1='142598745',
              trace2='142598745', so_tien='644000'):
    return {'STT': stt, 'Chi nhánh': chi_nhanh, 'Số thành công': so_thanh_cong,
            'Số Trace 1': trace1, 'Số Trace 2': trace2, 'Số tiền thực chuyển': so_tien}


def _df_gw(rows):
    """rows: list (MSGREF, Ghi chú)."""
    return pd.DataFrame(rows, columns=['MSGREF', 'Ghi chú'])


def _df_timeout(rows):
    """rows: list dict CHI_NHANH/TRACE/SE_TRACE/SO_TIEN."""
    return pd.DataFrame(rows, columns=['CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN'])


# ── doc_phub() — dò header theo nội dung, không hard-code offset dòng ────────

class TestDocPhub:
    def test_doc_dung_du_lieu_bo_qua_dong_tieu_de(self, tmp_path):
        path = tmp_path / 'pHub_Danh sach giao dich chuyen tien di_20260916.xlsx'
        _viet_file_phub(path, [
            _row_phub(stt='1', so_thanh_cong='MSG1'),
            _row_phub(stt='2', so_thanh_cong='MSG2'),
        ])
        df = doc_phub(str(path))
        assert len(df) == 2
        assert list(df['Số thành công']) == ['MSG1', 'MSG2']

    def test_boc_dau_nhay_don_dau_so_thanh_cong(self, tmp_path):
        path = tmp_path / 'pHub.xlsx'
        _viet_file_phub(path, [_row_phub(so_thanh_cong="'MSG1")])
        df = doc_phub(str(path))
        assert df['Số thành công'].iloc[0] == 'MSG1'


# ── xu_ly_phub_loi() — Bước 2 (GW) + Bước 3-6 (TO ko đi kênh) ────────────────

class TestXuLyPhubLoi:
    def test_khop_gw_ghi_chu_acsp_auth_la_hoan_thanh(self):
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG1')])
        df_gw = _df_gw([('MSG1', 'ACSP:AUTH:AUTH:/AIR/168283;/FAI/xxx;')])
        df_timeout = _df_timeout([])
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert out['TRANG_THAI_CAP_NHAT'].iloc[0] == 'Hoàn thành'

    def test_khop_gw_nhung_ghi_chu_khong_chua_ma_hop_le_khong_phai_hoan_thanh(self):
        """Khớp MSGREF nhưng Ghi chú không chứa ACSP:NOAN/ACSP:AUTH/ACSC:AUTH (ví
        dụ điện bị từ chối) — không được coi là 'Hoàn thành', phải rơi xuống Bước
        3-6 để xét tiếp bằng CN trace tiền."""
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG1', chi_nhanh='1400',
                                           trace2='999', so_tien='644000')])
        df_gw = _df_gw([('MSG1', 'RJCT:khac_hoan_toan')])
        df_timeout = _df_timeout([])  # không khớp gì -> Trạng thái khác
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert out['TRANG_THAI_CAP_NHAT'].iloc[0] == 'Trạng thái khác'

    def test_khong_khop_gw_nhung_khop_timeout_la_tt_lenh_loi(self):
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG_KHONG_CO_TREN_GW',
                                           chi_nhanh='1400', trace2='142598745',
                                           so_tien='644000')])
        df_gw = _df_gw([])
        df_timeout = _df_timeout([{
            'CHI_NHANH': '1400', 'TRACE': '142598745', 'SE_TRACE': None, 'SO_TIEN': '644000',
        }])
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert out['TRANG_THAI_CAP_NHAT'].iloc[0] == 'TT lệnh lỗi ngày T'

    def test_khong_khop_ca_2_ben_la_trang_thai_khac(self):
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG_LA', chi_nhanh='1400',
                                           trace2='999999', so_tien='1')])
        df_gw = _df_gw([])
        df_timeout = _df_timeout([{
            'CHI_NHANH': '1400', 'TRACE': '142598745', 'SE_TRACE': None, 'SO_TIEN': '644000',
        }])
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert out['TRANG_THAI_CAP_NHAT'].iloc[0] == 'Trạng thái khác'

    def test_so_trace_2_bo_so_0_dau_khop_voi_timeout(self):
        """Số Trace 2 = '0012345' (còn số 0 đầu) phải khớp với TRACE='12345' bên
        timeout sau khi cả 2 bên bỏ số 0 dẫn đầu — không được coi là lệch."""
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG_X', chi_nhanh='2002',
                                           trace2='0012345', so_tien='500000')])
        df_gw = _df_gw([])
        df_timeout = _df_timeout([{
            'CHI_NHANH': '2002', 'TRACE': '0012345', 'SE_TRACE': None, 'SO_TIEN': '500000',
        }])
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert out['TRANG_THAI_CAP_NHAT'].iloc[0] == 'TT lệnh lỗi ngày T'

    def test_timeout_uu_tien_se_trace_khi_co(self):
        """Bên TO ko đi kênh: SE_TRACE có giá trị thì phải dùng SE_TRACE, không
        dùng TRACE — pHub phải khớp theo SE_TRACE, khớp theo TRACE (giá trị khác)
        phải KHÔNG được coi là khớp."""
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG_Y', chi_nhanh='3000',
                                           trace2='777', so_tien='100000')])
        df_gw = _df_gw([])
        df_timeout = _df_timeout([{
            'CHI_NHANH': '3000', 'TRACE': '999999', 'SE_TRACE': '777', 'SO_TIEN': '100000',
        }])
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert out['TRANG_THAI_CAP_NHAT'].iloc[0] == 'TT lệnh lỗi ngày T'

    def test_giu_nguyen_thu_tu_dong_goc(self):
        """Kết quả phải giữ đúng thứ tự dòng gốc của pHub (không xáo trộn khi
        tách rồi ghép các nhánh Hoàn thành/TT lệnh lỗi/Trạng thái khác)."""
        df_phub = pd.DataFrame([
            _row_phub(so_thanh_cong='A', chi_nhanh='1', trace2='1', so_tien='1'),
            _row_phub(so_thanh_cong='B', chi_nhanh='2', trace2='2', so_tien='2'),
            _row_phub(so_thanh_cong='C', chi_nhanh='3', trace2='3', so_tien='3'),
        ])
        df_gw = _df_gw([('B', 'ACSC:AUTH:xxx')])
        df_timeout = _df_timeout([{'CHI_NHANH': '3', 'TRACE': '3', 'SE_TRACE': None, 'SO_TIEN': '3'}])
        out = xu_ly_phub_loi(df_phub, df_gw, df_timeout)
        assert list(out['Số thành công']) == ['A', 'B', 'C']
        assert list(out['TRANG_THAI_CAP_NHAT']) == ['Trạng thái khác', 'Hoàn thành', 'TT lệnh lỗi ngày T']


# ── _tim_file_phub() (pipeline.py) — dò file pHub theo tên đã chuẩn hoá ──────

class TestTimFilePhub:
    def test_khop_ten_file_that(self, tmp_path):
        f = tmp_path / 'pHub_Danh sach giao dich chuyen tien di_20260914.xlsx'
        f.write_text('x')
        assert _tim_file_phub(str(tmp_path)) == [str(f)]

    def test_khong_phan_biet_hoa_thuong_dau(self, tmp_path):
        f = tmp_path / 'PHUB_bao_cao_loi.xlsx'
        f.write_text('x')
        assert _tim_file_phub(str(tmp_path)) == [str(f)]

    def test_khong_gioi_han_so_luong_khong_raise(self, tmp_path):
        """Đối xứng `_tim_file_timeout_cu()` (Mục 8) — nghiệp vụ có thể đẩy nhiều
        file pHub của nhiều ngày cùng lúc, không raise khi >1 file."""
        f1 = tmp_path / 'pHub_ngay_12.09.xlsx'
        f2 = tmp_path / 'pHub_ngay_13.09.xlsx'
        f1.write_text('x'); f2.write_text('x')
        assert sorted(_tim_file_phub(str(tmp_path))) == sorted([str(f1), str(f2)])

    def test_khong_bat_nham_file_gw(self, tmp_path):
        (tmp_path / 'GW_20260914.xlsx').write_text('x')
        assert _tim_file_phub(str(tmp_path)) == []

    def test_khong_co_file_nao_tra_rong(self, tmp_path):
        assert _tim_file_phub(str(tmp_path)) == []

    def test_bo_qua_file_trong_thu_muc_output(self, tmp_path):
        out = tmp_path / 'Output'
        out.mkdir()
        (out / 'pHub_ngay_cu.xlsx').write_text('x')
        assert _tim_file_phub(str(tmp_path)) == []
