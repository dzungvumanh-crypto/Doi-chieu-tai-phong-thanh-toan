"""Test Kết quả pHub gộp nhiều ngày (`phub_gop.py`) — bản-2 "kho 30 ngày"
(`phub_lichsu.py`) đã bị gỡ (Luồng A, 23.09.2026). `gop_phub()` nay là hàm
THUẦN DỮ LIỆU: nhận thẳng `df_gw`/`df_timeout` đã nạp sẵn, không tự đọc đĩa.
Xem `pipeline/PLAN.md` mục 3 (A3).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_phub_gop.py -v
"""
import pandas as pd
import pytest

from backend.services.ach import phub_gop


def _df_to(chi_nhanh='1400', trace='111', se_trace=None, so_tien='500', ngay='20260915'):
    return pd.DataFrame([{'CHI_NHANH': chi_nhanh, 'TRACE': trace,
                          'SE_TRACE': se_trace, 'SO_TIEN': so_tien,
                          'NGAY_TIMEOUT': ngay}])


def _df_to_rong():
    return pd.DataFrame(columns=['CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN', 'NGAY_TIMEOUT'])


def _df_gw(msgref='M1', ghi_chu='ACSP:AUTH'):
    return pd.DataFrame([{'MSGREF': msgref, 'Ghi chú': ghi_chu}])


def _row_phub(so_thanh_cong='M1', chi_nhanh='1400', trace2='111', so_tien='500',
             ngay_gui='15/09/2026 10:00:00'):
    return {'STT': '1', 'Chi nhánh': chi_nhanh, 'Số thành công': so_thanh_cong,
            'Số Trace 1': trace2, 'Số Trace 2': trace2, 'Số tiền thực chuyển': so_tien,
            'Ngày giờ gửi lệnh': ngay_gui}


# ── gop_phub() — hàm gộp thuần dữ liệu, nhận df_gw/df_timeout trực tiếp ──────

class TestGopPhub:
    def test_gop_2_ngay_gia_lap(self):
        df_gw = pd.concat([
            _df_gw(msgref='MSG_A', ghi_chu='ACSP:AUTH'),
            _df_gw(msgref='MSG_khac', ghi_chu='khong khop'),
        ], ignore_index=True)
        df_timeout = pd.concat([
            _df_to(chi_nhanh='1400', trace='111', so_tien='500', ngay='20260915'),
            _df_to(chi_nhanh='1400', trace='111', so_tien='500', ngay='20260916'),
        ], ignore_index=True)
        df_phub = pd.DataFrame([
            _row_phub(so_thanh_cong='MSG_A', ngay_gui='15/09/2026 10:00:00'),
            _row_phub(so_thanh_cong='MSG_B', chi_nhanh='1400', trace2='111', so_tien='500',
                      ngay_gui='16/09/2026 11:00:00'),
            _row_phub(so_thanh_cong='MSG_C', chi_nhanh='9999', trace2='999', so_tien='999',
                      ngay_gui='16/09/2026 12:00:00'),
        ])
        df_ketqua, thong_ke = phub_gop.gop_phub(
            df_phub, df_gw, df_timeout, ['20260915', '20260916'])

        assert thong_ke == {'hoan_thanh': 1, 'tt_lenh_loi': 1, 'trang_thai_khac': 1, 'tong': 3}

        hang_a = df_ketqua.loc[df_ketqua['Số thành công'] == 'MSG_A'].iloc[0]
        assert hang_a['TRANG_THAI_CAP_NHAT'] == 'Hoàn thành'
        assert hang_a['NGAY_TIMEOUT_KHOP'] == ''   # chỉ điền cho 'TT lệnh lỗi ngày T'

        hang_b = df_ketqua.loc[df_ketqua['Số thành công'] == 'MSG_B'].iloc[0]
        assert hang_b['TRANG_THAI_CAP_NHAT'] == 'TT lệnh lỗi ngày T'
        assert hang_b['NGAY_TIMEOUT_KHOP'] == '15/09/2026|16/09/2026'   # khớp 2 ngày nối '|'

        hang_c = df_ketqua.loc[df_ketqua['Số thành công'] == 'MSG_C'].iloc[0]
        assert hang_c['TRANG_THAI_CAP_NHAT'] == 'Trạng thái khác'
        assert hang_c['NGAY_TIMEOUT_KHOP'] == ''

    def test_ngay_co_mis_di_nhung_timeout_rong_van_gop_duoc(self):
        """R6 — ngày có MIS_đi nhưng 0 dòng timeout (mọi giao dịch trong ngày đã
        khớp GW, không có gì rơi vào Timeout không đi kênh) vẫn gộp được, KHÔNG
        crash — dòng pHub khớp GW vẫn ra 'Hoàn thành' như bình thường."""
        df_gw      = _df_gw(msgref='M1', ghi_chu='ACSP:AUTH')
        df_timeout = _df_to_rong()

        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='M1')])
        df_ketqua, thong_ke = phub_gop.gop_phub(df_phub, df_gw, df_timeout, ['20260915'])
        assert thong_ke == {'hoan_thanh': 1, 'tt_lenh_loi': 0, 'trang_thai_khac': 0, 'tong': 1}

    def test_2_dong_timeout_cung_ngay_cung_khoa_khop_1_dong_phub_khong_lap_ngay(self):
        """2 dòng timeout CÙNG 1 ngày, CÙNG khoá CN trace tiền, khớp 1 dòng pHub —
        NGAY_TIMEOUT_KHOP chỉ hiện đúng 1 lần ('15/09/2026'), không lặp thành
        '15/09/2026|15/09/2026' (dedup qua `set` trong `gop_phub()`)."""
        df_timeout = pd.DataFrame([
            {'CHI_NHANH': '1400', 'TRACE': '111', 'SE_TRACE': None, 'SO_TIEN': '500',
             'NGAY_TIMEOUT': '20260915'},
            {'CHI_NHANH': '1400', 'TRACE': '111', 'SE_TRACE': None, 'SO_TIEN': '500',
             'NGAY_TIMEOUT': '20260915'},
        ])
        df_gw = _df_gw(msgref='KHAC', ghi_chu='khong khop')
        df_phub = pd.DataFrame([_row_phub(so_thanh_cong='MSG_X', chi_nhanh='1400',
                                          trace2='111', so_tien='500',
                                          ngay_gui='15/09/2026 10:00:00')])
        df_ketqua, _ = phub_gop.gop_phub(df_phub, df_gw, df_timeout, ['20260915'])

        hang = df_ketqua.iloc[0]
        assert hang['TRANG_THAI_CAP_NHAT'] == 'TT lệnh lỗi ngày T'
        assert hang['NGAY_TIMEOUT_KHOP'] == '15/09/2026'   # không lặp


# ── xuat_excel_phub_gop() — exporter (không đổi ở A3, canh_bao là tham số ────
# độc lập truyền từ ngoài vào, không lấy từ gop_phub()) ───────────────────────

class TestXuatExcelPhubGop:
    def test_xuat_du_2_sheet_va_ten_file(self, tmp_path):
        df_ketqua = pd.DataFrame([
            {'Số thành công': 'A', 'TRANG_THAI_CAP_NHAT': 'Hoàn thành',
             'NGAY_TIMEOUT_KHOP': '', 'Ngày giờ gửi lệnh': '15/09/2026 10:00:00'},
            {'Số thành công': 'B', 'TRANG_THAI_CAP_NHAT': 'TT lệnh lỗi ngày T',
             'NGAY_TIMEOUT_KHOP': '16/09/2026', 'Ngày giờ gửi lệnh': '16/09/2026 11:00:00'},
        ])
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        path = phub_gop.xuat_excel_phub_gop(str(out_dir), ['20260915', '20260916'],
                                            df_ketqua, [])
        assert path == str(out_dir / 'GOP_PHUBLOI_20260915_20260916.xlsx')

        xl = pd.ExcelFile(path, engine='calamine')
        assert xl.sheet_names == ['TONG_KET', 'PHUB_KET_QUA']

        df_out = pd.read_excel(path, sheet_name='PHUB_KET_QUA', engine='calamine')
        assert len(df_out) == 2

    def test_so_cong_lai_khop_tong(self, tmp_path):
        df_ketqua = pd.DataFrame([
            {'Số thành công': 'A', 'TRANG_THAI_CAP_NHAT': 'Hoàn thành',
             'Ngày giờ gửi lệnh': '15/09/2026 10:00:00'},
            {'Số thành công': 'B', 'TRANG_THAI_CAP_NHAT': 'TT lệnh lỗi ngày T',
             'Ngày giờ gửi lệnh': '15/09/2026 11:00:00'},
            {'Số thành công': 'C', 'TRANG_THAI_CAP_NHAT': 'Trạng thái khác',
             'Ngày giờ gửi lệnh': '16/09/2026 09:00:00'},
        ])
        out_dir = tmp_path / 'out'
        out_dir.mkdir()
        canh_bao = ['Ngày 16/09 thiếu dữ liệu GW-cho-pHub — dòng thuộc ngày này '
                    'không thể rơi vào nhóm Hoàn thành.']
        path = phub_gop.xuat_excel_phub_gop(str(out_dir), ['20260915', '20260916'],
                                            df_ketqua, canh_bao)
        df_tong_ket = pd.read_excel(path, sheet_name='TONG_KET', header=None, engine='calamine')
        # Dòng 'TỔNG' (cột 0) phải có giá trị 3 ở cột 1 — khớp tổng thật.
        vals = df_tong_ket.values.tolist()
        tong_row = next(r for r in vals if str(r[0]).strip() == 'TỔNG')
        assert int(tong_row[1]) == 3
