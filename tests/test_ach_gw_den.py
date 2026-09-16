"""Test Mục 4 (bổ sung 11.09.2026) — b13_xu_ly_gw_den.py: đọc file đến_GW (lọc
PrcFlg + Session ID) và đối chiếu TXID (MIS_đến) với MSGREF (GW đến).

Bối cảnh: file đến_GW thật dùng tên cột 'Session ID' (CÓ khoảng trắng) — KHÁC hẳn
'SessionId' (liền) của file GW đi (b3_xu_ly_gw.py) — test này khoá lại đúng tên cột
thật để không lặp lại lỗi đọc nhầm cột.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_gw_den.py -v
"""
import pandas as pd
import pytest
import xlsxwriter

from backend.services.ach.b13_xu_ly_gw_den import xu_ly_gw_den, doi_chieu_gw_den

_SID = '16282'
_HEADER = ['BRCD', 'MSGREF', 'STTLMAMT', 'PrcFlg', 'Session ID']


def _viet_file_gwden(path, rows, them_sheet_tieu_de=True, ten_sheet_data='Sheet 2'):
    """rows: list dict với khoá đúng _HEADER. Mô phỏng đúng cấu trúc file thật —
    Sheet 1 = tiêu đề (không có BRCD), Sheet 2 = dữ liệu thật."""
    wb = xlsxwriter.Workbook(str(path))
    if them_sheet_tieu_de:
        ws0 = wb.add_worksheet('Sheet 1')
        ws0.write(0, 0, 'BAO CAO DIEN DEN GW')
    ws = wb.add_worksheet(ten_sheet_data)
    ws.write_row(0, 0, _HEADER)
    for i, row in enumerate(rows, start=1):
        ws.write_row(i, 0, [row[h] for h in _HEADER])
    wb.close()


def _row(brcd='1000', msgref='M1', sttlmamt='100000', prcflg='Đã treo', session=_SID):
    return {'BRCD': brcd, 'MSGREF': msgref, 'STTLMAMT': sttlmamt, 'PrcFlg': prcflg, 'Session ID': session}


# ── xu_ly_gw_den() ──────────────────────────────────────────────────────────

class TestXuLyGwDen:
    def test_chi_giu_da_treo_va_da_tra_kh(self, tmp_path):
        """Lọc PrcFlg ∈ {'Đã treo', 'Đã trả KH'} — 'Đã từ chối' phải bị loại."""
        path = tmp_path / 'den GW 05.09.xlsx'
        _viet_file_gwden(path, [
            _row(msgref='M1', prcflg='Đã treo'),
            _row(msgref='M2', prcflg='Đã trả KH'),
            _row(msgref='M3', prcflg='Đã từ chối'),
        ])
        df = xu_ly_gw_den(str(path), _SID)
        assert sorted(df['MSGREF']) == ['M1', 'M2']

    def test_loai_dong_sai_session(self, tmp_path):
        path = tmp_path / 'den GW 05.09.xlsx'
        _viet_file_gwden(path, [
            _row(msgref='M1', session=_SID),
            _row(msgref='M2', session='99999'),
        ])
        df = xu_ly_gw_den(str(path), _SID)
        assert list(df['MSGREF']) == ['M1']

    def test_bo_qua_sheet_tieu_de_khong_co_brcd(self, tmp_path):
        """Sheet 1 (tiêu đề, không có cột BRCD) không được chọn làm dữ liệu —
        hàm phải tự tìm đúng Sheet 2."""
        path = tmp_path / 'den GW 05.09.xlsx'
        _viet_file_gwden(path, [_row(msgref='M1')], them_sheet_tieu_de=True)
        df = xu_ly_gw_den(str(path), _SID)
        assert list(df['MSGREF']) == ['M1']

    def test_khong_co_sheet_hop_le_raise(self, tmp_path):
        path = tmp_path / 'khong_hop_le.xlsx'
        wb = xlsxwriter.Workbook(str(path))
        ws = wb.add_worksheet('Sheet 1')
        ws.write_row(0, 0, ['A', 'B'])
        ws.write_row(1, 0, [1, 2])
        wb.close()
        with pytest.raises(ValueError, match="BRCD.*Session ID|Session ID.*BRCD"):
            xu_ly_gw_den(str(path), _SID)

    def test_sttlmamt_ngan_nghin_khong_bi_cat(self, tmp_path):
        """'1.000.000 VND' phải ra 1000000, không bị to_numeric() trần cắt còn 1."""
        path = tmp_path / 'den GW 05.09.xlsx'
        _viet_file_gwden(path, [_row(msgref='M1', sttlmamt='1.000.000 VND')])
        df = xu_ly_gw_den(str(path), _SID)
        assert df.loc[0, 'STTLMAMT'] == 1_000_000

    def test_khong_chon_nham_sheet_tron_nhieu_session(self, tmp_path):
        """Bug thật phát hiện 14.09.2026 (file đến GW 05.09) — workbook có 2 sheet
        CÙNG đủ cột BRCD + Session ID: 'Sheet 1' (đặt trước, tiêu đề "trộn") lẫn
        nhiều session khác nhau NHIỀU dòng hơn, 'Sheet 2' (đặt sau) chỉ chứa đúng 1
        session mục tiêu, ÍT dòng hơn. Chọn sheet đầu tiên tìm thấy (cách làm cũ)
        sẽ chọn nhầm 'Sheet 1' rồi lọc ra dữ liệu sai (không phải bản sao sạch của
        Sheet 2). Phải chọn đúng sheet THUẦN NHẤT ('Sheet 2'), không lẫn dữ liệu từ
        sheet trộn."""
        path = tmp_path / 'den GW 05.09.xlsx'
        wb = xlsxwriter.Workbook(str(path))

        # Sheet 1 — trộn nhiều session, NHIỀU dòng hơn, MSGREF khác hẳn Sheet 2
        # (không phải bản sao sạch — mô phỏng đúng dữ liệu thật đã phát hiện).
        ws1 = wb.add_worksheet('Sheet 1')
        ws1.write_row(0, 0, _HEADER)
        rows_tron = [
            _row(msgref='TRON1', session=_SID),
            _row(msgref='TRON2', session='16538'),
            _row(msgref='TRON3', session='16540'),
            _row(msgref='TRON4', session='16538'),
        ]
        for i, row in enumerate(rows_tron, start=1):
            ws1.write_row(i, 0, [row[h] for h in _HEADER])

        # Sheet 2 — thuần nhất đúng session mục tiêu, ÍT dòng hơn.
        ws2 = wb.add_worksheet('Sheet 2')
        ws2.write_row(0, 0, _HEADER)
        rows_thuan = [
            _row(msgref='THUAN1', session=_SID),
            _row(msgref='THUAN2', session=_SID),
        ]
        for i, row in enumerate(rows_thuan, start=1):
            ws2.write_row(i, 0, [row[h] for h in _HEADER])

        wb.close()

        df = xu_ly_gw_den(str(path), _SID)
        assert sorted(df['MSGREF']) == ['THUAN1', 'THUAN2']


# ── doi_chieu_gw_den() ────────────────────────────────────────────────────────

def _mis_den(txid_list, so_tien=100000):
    n = len(txid_list)
    return pd.DataFrame({
        'TXID': txid_list,
        'SO_TIEN': [so_tien] * n,
        'CHI_NHANH': ['CN1'] * n,
        'NGAY_GIAO_DICH': ['05/09/2026'] * n,
    })


def _gw_den(msgref_list, sttlmamt=100000):
    n = len(msgref_list)
    return pd.DataFrame({
        'MSGREF': msgref_list,
        'STTLMAMT': [sttlmamt] * n,
        'BRCD': ['1000'] * n,
        'PrcFlg': ['Đã treo'] * n,
    })


class TestDoiChieuGwDen:
    def test_boc_dau_nhay_don_dau_txid(self):
        """TXID có dấu nháy đơn đầu (Excel ép kiểu text) phải khớp đúng MSGREF
        không dấu nháy."""
        df_gw = _gw_den(['M1'])
        df_mis = _mis_den(["'M1"])
        df_khop, df_gw_thua, df_mis_thua = doi_chieu_gw_den(df_gw, df_mis)
        assert len(df_khop) == 1
        assert len(df_gw_thua) == 0
        assert len(df_mis_thua) == 0

    def test_khop_dung_gw_thua_mis_thua(self):
        """M1 khớp cả 2 bên, M2 chỉ có ở GW (GW thừa), M3 chỉ có ở MIS (MIS thừa)."""
        df_gw = _gw_den(['M1', 'M2'])
        df_mis = _mis_den(['M1', 'M3'])
        df_khop, df_gw_thua, df_mis_thua = doi_chieu_gw_den(df_gw, df_mis)
        assert list(df_khop['TXID']) == ['M1']
        assert list(df_gw_thua['MSGREF']) == ['M2']
        assert list(df_mis_thua['TXID']) == ['M3']

    def test_khop_giu_cot_mis_den_khong_phai_cot_gw(self):
        """df_khop phải là phía MIS_đến (nhiều cột nghiệp vụ hơn), cùng quy ước
        với doi_chieu_di()/doi_chieu_den() trả về phía MIS."""
        df_gw = _gw_den(['M1'])
        df_mis = _mis_den(['M1'])
        df_khop, _, _ = doi_chieu_gw_den(df_gw, df_mis)
        assert 'CHI_NHANH' in df_khop.columns
        assert 'SO_TIEN' in df_khop.columns

    def test_trung_so_luong_theo_count(self):
        """2 dòng M1 ở GW, 1 dòng M1 ở MIS — chỉ khớp 1 (theo count, giống
        _doi_chieu() dùng ở mọi module khác), 1 dòng GW còn lại là GW thừa."""
        df_gw = _gw_den(['M1', 'M1'])
        df_mis = _mis_den(['M1'])
        df_khop, df_gw_thua, df_mis_thua = doi_chieu_gw_den(df_gw, df_mis)
        assert len(df_khop) == 1
        assert len(df_gw_thua) == 1
        assert len(df_mis_thua) == 0
