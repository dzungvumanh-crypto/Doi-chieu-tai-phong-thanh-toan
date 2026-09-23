"""Test Kết quả pHub gộp nhiều ngày (`phub_gop.py`) — bản-2 "kho 30 ngày"
(`phub_lichsu.py`) đã bị gỡ (Luồng A, 23.09.2026). `gop_phub()` nay là hàm
THUẦN DỮ LIỆU: nhận thẳng `df_gw`/`df_timeout` đã nạp sẵn, không tự đọc đĩa.
Xem `pipeline/PLAN.md` mục 3 (A3).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_phub_gop.py -v
"""
import io

import openpyxl
import pandas as pd
import pytest

from backend.services import ach_service
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


# ── phan_loai_file_gop() — Luồng C (bản-3), phân loại N file theo NỘI DUNG ───

def _phub_xlsx_bytes(rows: list[dict]) -> bytes:
    """Dựng 1 file pHub giả lập — dòng 0 tiêu đề gộp, dòng 1 header thật (đúng
    cấu trúc thật đã xác nhận trong b16_phub_loi.py)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['DANH SÁCH GIAO DỊCH CHUYỂN TIỀN ĐI'])
    ws.append(['STT', 'Chi nhánh', 'Số thành công', 'Số Trace 1', 'Số Trace 2',
               'Số tiền thực chuyển', 'Ngày giờ gửi lệnh'])
    for i, r in enumerate(rows, start=1):
        ws.append([str(i), r['chi_nhanh'], r['so_thanh_cong'], r['trace2'], r['trace2'],
                  r['so_tien'], r['ngay_gui']])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _gw_csv_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows, columns=['MSGREF', 'Ghi chú'])
    return df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')


def _timeout_csv_bytes(rows: list[dict], voi_cot_ngay: bool = True) -> bytes:
    cols = ['CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN']
    if voi_cot_ngay:
        cols.append('NGAY_DOI_CHIEU')
    df = pd.DataFrame(rows, columns=cols)
    return df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')


class TestPhanLoaiFileGop:
    def test_nhan_dien_dung_3_loai_va_gop_duoc(self):
        danh_sach = [
            ('pHub_20260915.xlsx', _phub_xlsx_bytes([
                {'chi_nhanh': '1400', 'so_thanh_cong': 'MSG_A', 'trace2': '111',
                 'so_tien': '500', 'ngay_gui': '15/09/2026 10:00:00'},
            ])),
            ('GW_CHO_PHUB_20260915.csv', _gw_csv_bytes([
                {'MSGREF': 'MSG_A', 'Ghi chú': 'ACSP:AUTH'},
            ])),
            ('TIMEOUT_KHONG_KENH_20260915.csv', _timeout_csv_bytes([
                {'CHI_NHANH': '1400', 'TRACE': '111', 'SE_TRACE': '', 'SO_TIEN': '500',
                 'NGAY_DOI_CHIEU': '20260915'},
            ])),
        ]
        df_phub, df_gw, df_timeout, canh_bao = phub_gop.phan_loai_file_gop(danh_sach)

        assert len(df_phub) == 1
        assert list(df_gw['MSGREF']) == ['MSG_A']
        assert list(df_timeout['NGAY_TIMEOUT']) == ['20260915']
        assert canh_bao == []

    def test_0_file_phub_bao_loi_ro(self):
        danh_sach = [
            ('GW_CHO_PHUB_20260915.csv', _gw_csv_bytes([{'MSGREF': 'M1', 'Ghi chú': 'x'}])),
        ]
        with pytest.raises(ValueError, match='Không tìm thấy file pHub'):
            phub_gop.phan_loai_file_gop(danh_sach)

    def test_2_file_phub_bao_loi_neu_ten_ca_hai(self):
        p1 = _phub_xlsx_bytes([{'chi_nhanh': '1400', 'so_thanh_cong': 'A', 'trace2': '1',
                               'so_tien': '1', 'ngay_gui': '15/09/2026 10:00:00'}])
        danh_sach = [('a.xlsx', p1), ('b.xlsx', p1)]
        with pytest.raises(ValueError) as exc:
            phub_gop.phan_loai_file_gop(danh_sach)
        assert 'a.xlsx' in str(exc.value) and 'b.xlsx' in str(exc.value)

    def test_file_la_bao_loi_neu_ten(self):
        danh_sach = [('bao_cao_khac.csv',
                      pd.DataFrame([{'CỘT_LẠ': '1'}]).to_csv(index=False).encode())]
        with pytest.raises(ValueError) as exc:
            phub_gop.phan_loai_file_gop(danh_sach)
        assert 'bao_cao_khac.csv' in str(exc.value)

    def test_timeout_thieu_cot_ngay_canh_bao_va_bi_loai(self):
        """File TIMEOUT bản cũ (trước A4) không có NGAY_DOI_CHIEU — KHÔNG đoán
        ngày, dữ liệu file đó bị loại, cảnh báo nêu đích danh tên file, KHÔNG
        raise (các file khác vẫn gộp được)."""
        danh_sach = [
            ('pHub.xlsx', _phub_xlsx_bytes([{'chi_nhanh': '1400', 'so_thanh_cong': 'A',
                                            'trace2': '1', 'so_tien': '1',
                                            'ngay_gui': '15/09/2026 10:00:00'}])),
            ('TIMEOUT_CU_KHONG_CO_NGAY.csv', _timeout_csv_bytes(
                [{'CHI_NHANH': '1400', 'TRACE': '1', 'SE_TRACE': '', 'SO_TIEN': '1'}],
                voi_cot_ngay=False)),
        ]
        df_phub, df_gw, df_timeout, canh_bao = phub_gop.phan_loai_file_gop(danh_sach)
        assert len(df_timeout) == 0
        assert len(canh_bao) == 1
        assert 'TIMEOUT_CU_KHONG_CO_NGAY.csv' in canh_bao[0]
        assert 'NGAY_DOI_CHIEU' in canh_bao[0]


# ── ach_service.gop_phub() — Luồng C (bản-3), nối C-a + phub_gop + xuất Excel ─

class TestAchServiceGopPhub:
    def test_gop_2_ngay_gia_lap_ghi_ra_temp_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ach_service, 'TEMP_DIR', tmp_path)
        danh_sach = [
            ('pHub.xlsx', _phub_xlsx_bytes([
                {'chi_nhanh': '1400', 'so_thanh_cong': 'MSG_A', 'trace2': '111',
                 'so_tien': '500', 'ngay_gui': '15/09/2026 10:00:00'},
                {'chi_nhanh': '1400', 'so_thanh_cong': 'MSG_B', 'trace2': '222',
                 'so_tien': '600', 'ngay_gui': '16/09/2026 10:00:00'},
            ])),
            ('GW_15.csv', _gw_csv_bytes([{'MSGREF': 'MSG_A', 'Ghi chú': 'ACSP:AUTH'}])),
            ('TIMEOUT_15.csv', _timeout_csv_bytes([
                {'CHI_NHANH': '9999', 'TRACE': '999', 'SE_TRACE': '', 'SO_TIEN': '999',
                 'NGAY_DOI_CHIEU': '20260915'},
            ])),
            ('TIMEOUT_16.csv', _timeout_csv_bytes([
                {'CHI_NHANH': '1400', 'TRACE': '222', 'SE_TRACE': '', 'SO_TIEN': '600',
                 'NGAY_DOI_CHIEU': '20260916'},
            ])),
        ]
        ket_qua = ach_service.gop_phub(danh_sach)

        assert ket_qua['tong_ket'] == {
            'hoan_thanh': 1, 'tt_lenh_loi': 1, 'trang_thai_khac': 0, 'tong': 2}
        assert ket_qua['canh_bao'] == []
        assert ket_qua['ten_file'] == 'GOP_PHUBLOI_20260915_20260916.xlsx'

        # File thật đã được ghi ra TEMP_DIR/<ma>/ — không phải giả lập.
        out_path = tmp_path / ket_qua['ma'] / ket_qua['ten_file']
        assert out_path.exists()

    def test_tat_ca_timeout_thieu_cot_ngay_bao_loi_khong_crash(self, tmp_path, monkeypatch):
        """Không còn ngày nào xác định được → ValueError rõ ràng, KHÔNG để
        xuat_excel_phub_gop() crash IndexError vì ngay_list rỗng."""
        monkeypatch.setattr(ach_service, 'TEMP_DIR', tmp_path)
        danh_sach = [
            ('pHub.xlsx', _phub_xlsx_bytes([{'chi_nhanh': '1400', 'so_thanh_cong': 'A',
                                            'trace2': '1', 'so_tien': '1',
                                            'ngay_gui': '15/09/2026 10:00:00'}])),
            ('TIMEOUT_CU.csv', _timeout_csv_bytes(
                [{'CHI_NHANH': '1400', 'TRACE': '1', 'SE_TRACE': '', 'SO_TIEN': '1'}],
                voi_cot_ngay=False)),
        ]
        with pytest.raises(ValueError, match='Không xác định được ngày nào'):
            ach_service.gop_phub(danh_sach)

    def test_tai_ket_qua_gop_chan_path_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ach_service, 'TEMP_DIR', tmp_path)
        ma_dir = tmp_path / 'phubgop_abc123'
        ma_dir.mkdir()
        (ma_dir / 'GOP_PHUBLOI_1_2.xlsx').write_bytes(b'noi dung')

        assert ach_service.tai_ket_qua_gop('phubgop_abc123', 'GOP_PHUBLOI_1_2.xlsx') is not None
        assert ach_service.tai_ket_qua_gop('phubgop_abc123', 'khong_ton_tai.xlsx') is None
        # basename() cắt hết '../' — không đụng được file ngoài TEMP_DIR.
        assert ach_service.tai_ket_qua_gop('../../etc', 'passwd') is None
