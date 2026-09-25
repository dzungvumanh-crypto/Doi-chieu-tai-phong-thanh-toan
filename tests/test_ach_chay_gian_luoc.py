"""Test tính năng "chạy đủ file đến đâu ra kết quả đến đó" (2026-09-16, thay hẳn
cờ `chi_tim_timeout` cũ phải tự tay tick mới bật — xem
project_ach_scnl_txrt_trdt_thao_xacnhan_2026-09-16 / lịch sử PR liên quan).

Sàn bắt buộc DUY NHẤT còn lại: PDF (session) — D1 (23/09/2026) đã gỡ GW đi
khỏi sàn bắt buộc CHUNG (trước đó là PDF + GW). Thiếu GL02/MIS_đến/MIS_đi/GW đi
(bất kỳ tổ hợp nào) không raise — `main_from_dir()` tự chạy phần còn tính được,
ghi "CHƯA ĐỐI CHIẾU ĐƯỢC" cho phần phải bỏ qua thay vì số 0 giả. 3 nhóm độc lập,
đúng 3 tab UI:
- `ly_do_thieu_timeout` (phụ thuộc MIS_đi VÀ GW đi) — Timeout không đi kênh,
  GW-thừa, MIS_đi khớp GW, Checkpoint.
- `ly_do_thieu_di` (phụ thuộc GL02, MIS_đi VÀ GW đi) — MIS_đi khớp NPO, NPO_đi
  thừa, huỷ trong/khác ngày, OSB đi.
- `ly_do_thieu_den` (phụ thuộc GL02 và/hoặc MIS_đến, KHÔNG phụ thuộc GW đi) —
  MIS_đến khớp NPO, NPO_đến thừa, OSB đến — đây là Tab 2 "Đối chiếu đến", chạy
  độc lập không cần GW đi.

D-2 (23/09/2026, đã chốt) — thiếu GW đi thì TẮT HẲN cả nhóm Đi và Timeout (ghi
gộp vào cả 2 `ly_do_thieu_di`/`ly_do_thieu_timeout`), không chạy một phần kèm
cảnh báo. Lý do: `_process_mis_di()` dùng GW gốc để giữ lại các dòng
SESSION=NULL; không có GW thì các dòng đó rơi hết, số liệu chiều đi ra SAI
(không phải chỉ thiếu) nếu vẫn cố tính.

4 lớp test:
- TestValidateTang0Ok       — validate_required_files() thuần, không cần file thật.
- TestXuatExcelChuaDoiChieuDuoc — xuat_excel() với DataFrame tổng hợp, đúng pattern
  test_ach_excel_export.py (không mock, ghi file .xlsx thật rồi đọc lại).
- TestMainFromDirChayGianLuoc — end-to-end main_from_dir() với file PDF/GW/MIS_đi/
  GL02/MIS_đến thật (zip AES thu nhỏ, đúng pattern test_ach_gl02_misden_algorithm.py).
- TestAchServiceCheckpointKhiThieuMisDi — bug thật phát hiện qua Agent phản biện
  (2026-09-16): `ach_service.py::_run()` từng suy đoán "đã dừng ở Checkpoint" chỉ
  dựa vào tham số ĐẦU VÀO `dung_sau_mis_di`, trong khi từ đợt sửa này pipeline TỰ
  bỏ qua Checkpoint khi thiếu MIS_đi (chạy thẳng tới báo cáo cuối) — job ĐÃ XONG
  bị gắn nhầm trạng thái 'awaiting_confirmation', đưa nhầm file báo cáo cuối ra
  dưới vỏ bọc "file cần xác nhận". Sửa bằng cách xét TÊN FILE thật trả về, không
  suy đoán từ tham số đầu vào.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_chay_gian_luoc.py -v
"""

import io

import openpyxl
import pandas as pd
import pyzipper
import pytest

from backend.services.ach import config as _cfg
from backend.services.ach.pipeline import xuat_excel, main_from_dir
from backend.services.ach.validate import validate_required_files
from backend.services import ach_service

_FULL_SET = [
    'ACH_20260711_VBAAVNVN_NRT_16362_N03_1.pdf',
    'GL02_20260711_1000.zip',
    'di GW 11.07.xlsx',
    'doichieugd_20260710__01_DI_9999_N.zip',
    'doichieugd_20260711__01_DI_9999_N.zip',
    'doichieugd_20260710__01_DEN_9999_N.zip',
    'doichieugd_20260711__01_DEN_9999_N.zip',
]


# ─── validate_required_files() — cờ tang0_ok ─────────────────────────────────

class TestValidateTang0Ok:
    def test_du_het_ca_ok_va_tang0_ok_deu_true(self):
        res = validate_required_files(_FULL_SET)
        assert res['ok'] is True
        assert res['tang0_ok'] is True

    def test_thieu_gl02_ok_false_nhung_tang0_ok_true(self):
        res = validate_required_files([f for f in _FULL_SET if not f.startswith('GL02')])
        assert res['ok'] is False
        assert res['tang0_ok'] is True

    def test_thieu_mis_den_ok_false_nhung_tang0_ok_true(self):
        res = validate_required_files([f for f in _FULL_SET if '_DEN_' not in f])
        assert res['ok'] is False
        assert res['tang0_ok'] is True

    def test_thieu_ca_gl02_lan_mis_den_van_tang0_ok_true(self):
        res = validate_required_files([
            f for f in _FULL_SET if not f.startswith('GL02') and '_DEN_' not in f
        ])
        assert res['ok'] is False
        assert res['tang0_ok'] is True

    def test_thieu_mis_di_van_tang0_ok_true(self):
        """2026-09-16 — MIS_đi không còn nằm trong sàn tối thiểu (tang0_ok chỉ
        còn PDF+GW). Trái với hành vi cũ (từng bắt buộc)."""
        res = validate_required_files([f for f in _FULL_SET if '_DI_' not in f])
        assert res['ok'] is False
        assert res['tang0_ok'] is True

    def test_thieu_gw_van_tang0_ok_true(self):
        """D1 (23/09/2026) — GW đi không còn nằm trong sàn tối thiểu (tang0_ok
        chỉ còn PDF). Trái với hành vi cũ (từng bắt buộc cùng PDF)."""
        res = validate_required_files([f for f in _FULL_SET if 'GW' not in f])
        assert res['ok'] is False
        assert res['tang0_ok'] is True

    def test_thieu_pdf_thi_tang0_ok_cung_false(self):
        res = validate_required_files([f for f in _FULL_SET if not f.endswith('.pdf')])
        assert res['tang0_ok'] is False


# ─── xuat_excel() — nhãn "CHƯA ĐỐI CHIẾU ĐƯỢC" theo 3 nhóm độc lập ───────────

def _synthetic_dfs_tang0_only():
    """Chỉ có dữ liệu nhóm timeout (GW + Timeout) — mọi df nhóm đi/đến = None (mô
    phỏng main_from_dir() khi thiếu GL02/MIS_đến, MIS_đi vẫn có)."""
    df_timeout = pd.DataFrame({'SO_TIEN': [300_000]})
    df_gw_raw = pd.DataFrame({
        'BRCD': ['0001'], 'STTLMAMT': [1_000_000], 'MSGREF': ['REF1'],
        'SessionId': ['16282'], 'PrcFlg': ['Lệnh Hoàn thành'], 'KEY_GW': ['00011000000'],
    })
    return df_timeout, df_gw_raw


class TestXuatExcelChuaDoiChieuDuoc:
    def test_thieu_gl02_mis_den_sheet_den_hien_chua_doi_chieu_duoc(self, tmp_path):
        """Thiếu GL02+MIS_đến (MIS_đi vẫn có) — sheet nhóm ĐẾN + phần "đi" phụ
        thuộc GL02 đều ghi CHƯA ĐỐI CHIẾU ĐƯỢC, đúng ly_do_thieu tương ứng."""
        df_timeout, df_gw_raw = _synthetic_dfs_tang0_only()
        output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

        xuat_excel(
            output_path, '16282',
            None, None, None,   # df_mis_di_khop, df_npo_di_thua, df_mis_di_thua
            df_timeout,
            None, None, None,   # df_mis_den_khop, df_npo_den_thua, df_mis_den_thua
            df_gw_raw,
            ly_do_thieu_di='GL02',
            ly_do_thieu_den='GL02, MIS_đến',
        )

        wb = openpyxl.load_workbook(output_path)
        assert wb['MIS_DI_KHOP']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file GL02'
        assert wb['NPO_DI_THUA']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file GL02'
        assert wb['MIS_DEN_THUA']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file GL02, MIS_đến'

    def test_thieu_gl02_mis_den_sheet_timeout_khong_bi_anh_huong(self, tmp_path):
        """TIMEOUT_KHONG_KENH chỉ phụ thuộc MIS_đi — vẫn hiện dữ liệu thật khi chỉ
        thiếu GL02/MIS_đến, không bị gắn nhãn thiếu."""
        df_timeout, df_gw_raw = _synthetic_dfs_tang0_only()
        output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

        xuat_excel(
            output_path, '16282',
            None, None, None, df_timeout, None, None, None, df_gw_raw,
            ly_do_thieu_di='GL02', ly_do_thieu_den='GL02, MIS_đến',
        )

        wb = openpyxl.load_workbook(output_path)
        ws = wb['TIMEOUT_KHONG_KENH']
        header = [c.value for c in next(ws.iter_rows(max_row=1))]
        assert 'SO_TIEN' in header
        assert ws.cell(row=2, column=header.index('SO_TIEN') + 1).value == 300_000

    def test_thieu_mis_di_sheet_timeout_hien_chua_doi_chieu_duoc(self, tmp_path):
        """2026-09-16 — hành vi MỚI: thiếu MIS_đi làm TIMEOUT_KHONG_KENH (và
        MIS_DI_KHOP) cũng CHƯA ĐỐI CHIẾU ĐƯỢC — trước đây sheet này KHÔNG BAO GIỜ
        bị gắn nhãn thiếu vì Tầng 0 luôn bắt buộc có MIS_đi."""
        output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')

        xuat_excel(
            output_path, '16282',
            None, None, None, None, None, None, None, None,
            ly_do_thieu_di='MIS_đi', ly_do_thieu_timeout='MIS_đi',
        )

        wb = openpyxl.load_workbook(output_path)
        assert wb['TIMEOUT_KHONG_KENH']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file MIS_đi'
        assert wb['MIS_DI_KHOP']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file MIS_đi'

    def test_khong_thieu_gi_thi_khong_hien_nhan_canh_bao(self, tmp_path):
        """Regression — không thiếu gì (mặc định, hành vi cũ) không được đổi
        thông điệp sheet rỗng thật."""
        output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')
        xuat_excel(
            output_path, '16282',
            None, None, None, None, None, None, None, None,
        )
        wb = openpyxl.load_workbook(output_path)
        assert wb['MIS_DI_KHOP']['A1'].value == '(Không có dữ liệu)'

    def test_tong_ket_hien_banner_gop_ca_3_nhom(self, tmp_path):
        df_timeout, df_gw_raw = _synthetic_dfs_tang0_only()
        output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')
        xuat_excel(
            output_path, '16282',
            None, None, None, df_timeout, None, None, None, df_gw_raw,
            ly_do_thieu_di='GL02', ly_do_thieu_den='GL02, MIS_đến',
        )
        wb = openpyxl.load_workbook(output_path)
        ws = wb['TONG_KET']
        assert 'THIẾU FILE' in ws['A1'].value
        assert 'GL02' in ws['A1'].value
        assert 'MIS_ĐẾN' in ws['A1'].value.upper()
        assert 'Chiều đi' in ws['A1'].value
        assert 'Chiều đến' in ws['A1'].value

    def test_tong_ket_khong_hien_banner_khi_du_file(self, tmp_path):
        output_path = str(tmp_path / 'doi_chieu_20260723.xlsx')
        xuat_excel(
            output_path, '16282',
            None, None, None, None, None, None, None, None,
        )
        wb = openpyxl.load_workbook(output_path)
        ws = wb['TONG_KET']
        assert ws['A1'].value == 'Ngày đối chiếu'


# ─── main_from_dir() end-to-end — chạy giản lược theo file đang có ───────────

_SID = '16362'
_MIS_DI_COLS = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SE_TRACE', 'SESSION', 'LOAI_LENH_OSB', 'NH_NHAN',
    'MA_GIAO_DICH', 'NOI_DUNG', 'NGAY_KENH_TRA',
]
_GL02_COLS = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
              'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
              'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']
_MIS_DEN_COLS = ['NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
                 'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
                 'SESSION', 'LOAI_LENH_OSB', 'NH_GUI', 'NOI_DUNG']
_LOCAC_TARGET = '502003'
_CUSTOMER_ACH = '1000-003526275'
_REF_NORMAL   = '1234567' + '000123456789' + 'XYZ'   # SO_TRACE -> '123456789'


def _mis_di_row(refhub='REF1', chi_nhanh='1000', so_tien='500000', trang_thai='SCNL'):
    return {
        'NGAY_GIAO_DICH': '11/07/2026', 'CHI_NHANH': chi_nhanh, 'REFHUB': refhub,
        'MSGREF': 'MSG' + refhub, 'MSGSEQ': '1', 'TXID': 'TX' + refhub,
        'KENH_THANH_TOAN': 'ACH-NAPAS', 'TRANG_THAI_LENH': trang_thai,
        'SO_TIEN': so_tien, 'TRACE': "'0000123456", 'SE_TRACE': '',
        'SESSION': _SID, 'LOAI_LENH_OSB': '', 'NH_NHAN': 'NH TEST',
        'MA_GIAO_DICH': 'MGD' + refhub, 'NOI_DUNG': 'nd', 'NGAY_KENH_TRA': '11/07/2026 10:00:00',
    }


def _gl02_row(trbrcd='1000', reference=_REF_NORMAL, dramount='0', cramount='0'):
    return {
        'TRDATE': '20260711', 'TRBRCD': trbrcd, 'USERID': '1000API0', 'JOURSEQ': '1',
        'DYTRSEQ': '1', 'LOCAC': _LOCAC_TARGET, 'CCY': 'VND', 'BUSCD': 'EI', 'UNIT': 'AP',
        'TRCD': '', 'CUSTOMER': _CUSTOMER_ACH, 'TRTP': 'Normal', 'REFERENCE': reference,
        'REMARK': '', 'DRAMOUNT': dramount, 'CRAMOUNT': cramount, 'CRTDTM': '',
    }


def _mis_den_row(chi_nhanh='1000', refhub='REF1', trace="'0000123456", so_tien='100000'):
    return {
        'NGAY_GIAO_DICH': '11/07/2026', 'CHI_NHANH': chi_nhanh, 'REFHUB': refhub,
        'MSGREF': "'MSG1", 'MSGSEQ': "'", 'TXID': 'TX1', 'KENH_THANH_TOAN': 'ACH-NAPAS',
        'TRANG_THAI_LENH': 'SCNL', 'SO_TIEN': so_tien, 'TRACE': trace,
        'SESSION': _SID, 'LOAI_LENH_OSB': '', 'NH_GUI': 'NH X', 'NOI_DUNG': 'nd',
    }


def _make_zip(rows: list[dict], cols: list[str]) -> bytes:
    df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    csv_bytes = df.to_csv(index=False).encode('utf-8-sig')
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                              encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_cfg.zip_password())
        zf.writestr('data.csv', csv_bytes)
    return buf.getvalue()


def _make_mis_di_zip(tmp_path, name: str, rows: list[dict]):
    path = tmp_path / name
    path.write_bytes(_make_zip(rows, _MIS_DI_COLS))
    return str(path)


def _make_gl02_zip(tmp_path, rows: list[dict], name='GL02_20260711_1000.zip'):
    path = tmp_path / name
    path.write_bytes(_make_zip(rows, _GL02_COLS))
    return str(path)


def _make_mis_den_zip(tmp_path, name: str, rows: list[dict]):
    path = tmp_path / name
    path.write_bytes(_make_zip(rows, _MIS_DEN_COLS))
    return str(path)


def _make_gw_xlsx(tmp_path, name: str = 'di GW 11.07.xlsx'):
    """GW khớp đúng 1 dòng với MIS_đi (BRCD+STTLMAMT = CHI_NHANH+SO_TIEN =
    '1000'+'500000') — pipeline chạy hết nhóm timeout mà không phát sinh timeout
    thật ngoài dự kiến (đủ đơn giản để không phụ thuộc chi tiết phân loại timeout)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'đi GW 11.07'
    ws.append(['BRCD', 'STTLMAMT', 'MSGREF', 'SessionId', 'PrcFlg'])
    ws.append(['1000', '500000', 'MSGREF1', _SID, 'Lệnh Hoàn thành'])
    path = tmp_path / name
    wb.save(str(path))
    return str(path)


def _make_gw_xlsx_co_ghi_chu(tmp_path, name: str = 'di GW 11.07.xlsx'):
    """Biến thể của `_make_gw_xlsx()` có thêm cột 'Ghi chú' — cột này
    `doc_gw_di_cho_phub()` (A4) đòi phải có, `_make_gw_xlsx()` gốc không có
    (không cần cho các test khác, tách riêng để không ảnh hưởng chúng)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'đi GW 11.07'
    ws.append(['BRCD', 'STTLMAMT', 'MSGREF', 'SessionId', 'PrcFlg', 'Ghi chú'])
    ws.append(['1000', '500000', 'MSGREF1', _SID, 'Lệnh Hoàn thành', 'ACSP:AUTH:AUTH:/AIR/168283'])
    path = tmp_path / name
    wb.save(str(path))
    return str(path)


def _make_pdf(tmp_path, name='ACH_20260711_VBAAVNVN_NRT_16362_N03_1.pdf'):
    path = tmp_path / name
    path.write_bytes(b'%PDF-fake-content-not-parsed')
    return str(path)


class TestMainFromDirChayGianLuoc:
    def test_thieu_gl02_khong_raise_chay_giam_luoc(self, tmp_path, monkeypatch):
        """Regression đảo ngược so với hành vi cũ — trước đây thiếu GL02 (không
        truyền chi_tim_timeout) raise ngay. Nay KHÔNG raise, chạy ra kết quả
        nhóm timeout thật, nhóm đi/đến ghi CHƯA ĐỐI CHIẾU ĐƯỢC."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx(tmp_path)
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])
        out_dir = tmp_path / 'out'

        output_path = main_from_dir(str(tmp_path), str(out_dir))

        assert output_path is not None
        wb = openpyxl.load_workbook(output_path)
        assert 'TIMEOUT_KHONG_KENH' in wb.sheetnames
        assert wb['MIS_DI_KHOP']['A1'].value.startswith('CHƯA ĐỐI CHIẾU ĐƯỢC')
        assert wb['MIS_DEN_KHOP']['A1'].value.startswith('CHƯA ĐỐI CHIẾU ĐƯỢC')
        assert 'THIẾU FILE' in wb['TONG_KET']['A1'].value

    def test_thieu_mis_di_khong_raise_chi_mat_nhom_timeout_va_di(self, tmp_path, monkeypatch):
        """2026-09-16 — kịch bản trọng tâm: thiếu MIS_đi (đủ PDF+GW+GL02+MIS_đến)
        KHÔNG raise (trước đây luôn raise, kể cả với chi_tim_timeout=True). Nhóm
        timeout + đi mất kết quả, nhóm ĐẾN vẫn ra số liệu thật."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx(tmp_path)
        _make_gl02_zip(tmp_path, [_gl02_row(cramount='0', dramount='100000')])
        _make_mis_den_zip(tmp_path, 'doichieugd_20260711__01_DEN_9999_N.zip', [_mis_den_row()])
        _make_mis_den_zip(tmp_path, 'doichieugd_20260711__02_DEN_9999_N.zip', [])
        out_dir = tmp_path / 'out'

        output_path = main_from_dir(str(tmp_path), str(out_dir))

        assert output_path is not None
        wb = openpyxl.load_workbook(output_path)
        assert wb['TIMEOUT_KHONG_KENH']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file MIS_đi'
        assert wb['MIS_DI_KHOP']['A1'].value == 'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file MIS_đi'
        # MIS_DEN_KHOP đã tính thật (không None) — có header đúng cột, không
        # gắn nhãn thiếu, dù 0 dòng khớp thật (GL02/MIS_đến không cùng khoá ở
        # test này, chỉ cần xác nhận nhóm ĐẾN đã CHẠY, không bị bỏ qua).
        ws = wb['MIS_DEN_KHOP']
        assert ws['A1'].value in ('(Không có dữ liệu)', 'NGAY_GIAO_DICH')

    def test_thieu_ca_gl02_mis_den_mis_di_van_khong_raise(self, tmp_path, monkeypatch):
        """Chỉ có PDF+GW (sàn bắt buộc cuối cùng) — không raise, cả 3 nhóm đều
        CHƯA ĐỐI CHIẾU ĐƯỢC, banner TONG_KET liệt kê đủ GL02/MIS_đi/MIS_đến."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx(tmp_path)
        out_dir = tmp_path / 'out'

        output_path = main_from_dir(str(tmp_path), str(out_dir))

        assert output_path is not None
        wb = openpyxl.load_workbook(output_path)
        banner = wb['TONG_KET']['A1'].value
        assert 'THIẾU FILE' in banner
        assert 'MIS_ĐI' in banner.upper()
        assert 'GL02' in banner
        assert 'MIS_ĐẾN' in banner.upper()

    def test_thieu_pdf_van_raise(self, tmp_path, monkeypatch):
        """PDF vẫn là sàn bắt buộc tuyệt đối — thiếu thì raise như cũ."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_gw_xlsx(tmp_path)
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])

        with pytest.raises(FileNotFoundError):
            main_from_dir(str(tmp_path), str(tmp_path / 'out'))

    def test_thieu_gw_khong_raise_tab2_den_van_chay(self, tmp_path, monkeypatch):
        """D1 (23/09/2026) — thư mục chỉ PDF + GL02 + 2 MIS_đến (KHÔNG GW đi):
        chạy xong, không raise, nhóm ĐẾN (Tab 2) ra số liệu thật; nhóm Đi +
        Timeout tắt hẳn theo D-2 (không chạy một phần kèm cảnh báo)."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gl02_zip(tmp_path, [_gl02_row(cramount='0', dramount='100000')])
        _make_mis_den_zip(tmp_path, 'doichieugd_20260711__01_DEN_9999_N.zip', [_mis_den_row()])
        _make_mis_den_zip(tmp_path, 'doichieugd_20260711__02_DEN_9999_N.zip', [])
        out_dir = tmp_path / 'out'

        output_path = main_from_dir(str(tmp_path), str(out_dir))

        assert output_path is not None
        wb = openpyxl.load_workbook(output_path)
        assert wb['TIMEOUT_KHONG_KENH']['A1'].value.startswith('CHƯA ĐỐI CHIẾU ĐƯỢC')
        assert 'GW đi' in wb['TIMEOUT_KHONG_KENH']['A1'].value
        assert wb['MIS_DI_KHOP']['A1'].value.startswith('CHƯA ĐỐI CHIẾU ĐƯỢC')
        assert 'GW đi' in wb['MIS_DI_KHOP']['A1'].value
        # MIS_DEN_KHOP đã tính thật (Tab 2 không phụ thuộc GW đi) — không gắn nhãn thiếu.
        ws = wb['MIS_DEN_KHOP']
        assert ws['A1'].value in ('(Không có dữ liệu)', 'NGAY_GIAO_DICH')

    def test_2_file_gw_van_raise(self, tmp_path, monkeypatch):
        """Luồng B (không đụng) — có ≥2 file GW đi hợp lệ vẫn raise, kể cả sau D1
        cho phép 0 file. 0 và ≥2 là hai nhánh riêng, không được gộp điều kiện."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx(tmp_path, name='GW ngay 1.xlsx')
        _make_gw_xlsx(tmp_path, name='GW ngay 2.xlsx')
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])

        with pytest.raises(FileNotFoundError):
            main_from_dir(str(tmp_path), str(tmp_path / 'out'))


# ─── A4 (23/09/2026) — xuất GW_CHO_PHUB_<ngày>.csv theo ô tick tuỳ chọn ──────
# Đọc lại doc_gw_di_cho_phub() (b16_phub_loi.py, KHÔNG bị gỡ — chỉ mất lời gọi
# ở Luồng A). Mặc định TẮT (C1 đã chốt), gộp thêm cột NGAY_DOI_CHIEU (C-N) vào
# CẢ HAI file CSV (TIMEOUT_KHONG_KENH + GW_CHO_PHUB).

class TestGwChoPhubA4:
    def test_mac_dinh_tat_khong_xuat_file_khong_ton_them_thoi_gian(self, tmp_path, monkeypatch):
        """Không truyền tao_gw_cho_phub (mặc định False) — KHÔNG có file
        GW_CHO_PHUB_*.csv trong output_dir, KHÔNG có dòng log [TIMING] GW-cho-pHub."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx_co_ghi_chu(tmp_path)
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])
        out_dir = tmp_path / 'out'
        logs = []

        output_path = main_from_dir(
            str(tmp_path), str(out_dir), ngay='11/07/2026', log_callback=logs.append,
        )

        assert output_path is not None
        assert not (out_dir / 'GW_CHO_PHUB_20260711.csv').exists()
        assert not any('GW-cho-pHub' in l for l in logs)

    def test_tick_bat_xuat_file_co_cot_ngay(self, tmp_path, monkeypatch):
        """tao_gw_cho_phub=True + có GW hợp lệ (cột 'Ghi chú') — xuất
        GW_CHO_PHUB_<ngày>.csv với cột NGAY_DOI_CHIEU=YYYYMMDD, có log [TIMING]."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx_co_ghi_chu(tmp_path)
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])
        out_dir = tmp_path / 'out'
        logs = []

        output_path = main_from_dir(
            str(tmp_path), str(out_dir), ngay='11/07/2026', log_callback=logs.append,
            tao_gw_cho_phub=True,
        )

        assert output_path is not None
        csv_path = out_dir / 'GW_CHO_PHUB_20260711.csv'
        assert csv_path.exists()
        df = pd.read_csv(csv_path, dtype=str, encoding='utf-8-sig')
        assert list(df.columns) == ['MSGREF', 'Ghi chú', 'NGAY_DOI_CHIEU']
        assert (df['NGAY_DOI_CHIEU'] == '20260711').all()
        assert any('[TIMING] GW-cho-pHub' in l for l in logs)

    def test_tick_bat_nhung_khong_co_gw_khong_loi_khong_tao_file(self, tmp_path, monkeypatch):
        """tao_gw_cho_phub=True nhưng không có GW đi (0 file) — không raise,
        không tạo file, chỉ log cảnh báo bỏ qua."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gl02_zip(tmp_path, [_gl02_row(cramount='0', dramount='100000')])
        _make_mis_den_zip(tmp_path, 'doichieugd_20260711__01_DEN_9999_N.zip', [_mis_den_row()])
        _make_mis_den_zip(tmp_path, 'doichieugd_20260711__02_DEN_9999_N.zip', [])
        out_dir = tmp_path / 'out'
        logs = []

        output_path = main_from_dir(
            str(tmp_path), str(out_dir), log_callback=logs.append, tao_gw_cho_phub=True,
        )

        assert output_path is not None
        assert not any((out_dir).glob('GW_CHO_PHUB_*.csv'))
        assert any('GW-cho-pHub' in l and 'WARN' in l for l in logs)

    def test_loi_doc_gw_cho_phub_khong_lam_sap_bao_cao_chinh(self, tmp_path, monkeypatch):
        """GW đi hợp lệ cho pipeline chính nhưng THIẾU cột 'Ghi chú' (dùng
        `_make_gw_xlsx()` gốc) — doc_gw_di_cho_phub() raise ValueError bên
        trong, KHÔNG được làm sập báo cáo chính (input tuỳ chọn, đúng tinh thần
        các khối Mục 4/6/7 khác)."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx(tmp_path)   # KHÔNG có cột 'Ghi chú'
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])
        out_dir = tmp_path / 'out'
        logs = []

        output_path = main_from_dir(
            str(tmp_path), str(out_dir), log_callback=logs.append, tao_gw_cho_phub=True,
        )

        assert output_path is not None   # báo cáo chính vẫn ra, không sập
        assert not any(out_dir.glob('GW_CHO_PHUB_*.csv'))
        assert any('GW-cho-pHub' in l and 'WARN' in l for l in logs)

    def test_timeout_khong_kenh_luon_co_cot_ngay_du_khong_tick(self, tmp_path, monkeypatch):
        """C-N: TIMEOUT_KHONG_KENH_<ngày>.csv luôn có cột NGAY_DOI_CHIEU, KHÔNG
        phụ thuộc ô tick GW-cho-pHub (2 tính năng độc lập)."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        _make_pdf(tmp_path)
        _make_gw_xlsx(tmp_path)
        # MSGREF khác GW ở trên (MSGREF1), trạng thái TPAY (không thuộc
        # _TRANG_THAI_DA_DI_KENH) — rơi đúng nhánh 1A "Timeout không đi kênh".
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__01_DI_9999_N.zip',
                         [_mis_di_row(refhub='REF_TIMEOUT', chi_nhanh='9999',
                                      so_tien='777000', trang_thai='TPAY')])
        _make_mis_di_zip(tmp_path, 'doichieugd_20260711__02_DI_9999_N.zip', [])
        out_dir = tmp_path / 'out'

        output_path = main_from_dir(str(tmp_path), str(out_dir), ngay='11/07/2026')

        assert output_path is not None
        csv_path = out_dir / 'TIMEOUT_KHONG_KENH_20260711.csv'
        assert csv_path.exists()
        df = pd.read_csv(csv_path, dtype=str, encoding='utf-8-sig')
        assert len(df) >= 1
        assert 'NGAY_DOI_CHIEU' in df.columns
        assert (df['NGAY_DOI_CHIEU'] == '20260711').all()
        # Cột mới KHÔNG lọt vào sheet TIMEOUT_KHONG_KENH của CHÍNH lượt chạy
        # này (whitelist _COLS_TIMEOUT trong xuat_excel() — Mục 1.1).
        wb = openpyxl.load_workbook(output_path)
        header = [c.value for c in next(wb['TIMEOUT_KHONG_KENH'].iter_rows(min_row=1, max_row=1))]
        assert 'NGAY_DOI_CHIEU' not in header


# ─── ach_service._run() — trạng thái job khi thiếu MIS_đi (bug thật, xem docstring đầu file) ─

class TestAchServiceCheckpointKhiThieuMisDi:
    def test_du_gl02_mis_den_thieu_mis_di_job_ket_thuc_done_khong_phai_cho_xac_nhan(
        self, monkeypatch,
    ):
        """dung_sau_mis_di=True (mặc định UI, KHÔNG tick "chạy thẳng") + thiếu
        MIS_đi — pipeline tự chạy thẳng, KHÔNG dừng ở Checkpoint. Job phải kết
        thúc 'done' với đủ file báo cáo thật trong job['files'], TUYỆT ĐỐI không
        được gắn 'awaiting_confirmation' (đó là job ĐÃ XONG, không có gì để chờ
        xác nhận) — bug thật phát hiện qua Agent phản biện 2026-09-16."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        job_id, input_dir = ach_service.tao_job()
        try:
            _make_pdf(input_dir)
            _make_gw_xlsx(input_dir)
            _make_gl02_zip(input_dir, [_gl02_row(cramount='0', dramount='100000')])
            _make_mis_den_zip(input_dir, 'doichieugd_20260711__01_DEN_9999_N.zip', [_mis_den_row()])
            _make_mis_den_zip(input_dir, 'doichieugd_20260711__02_DEN_9999_N.zip', [])

            job = ach_service.get_job(job_id)
            ach_service._run(
                job_id, str(input_dir), job['output_dir'], ngay=None,
                dung_sau_mis_di=True,
            )

            job = ach_service.get_job(job_id)
            assert job['status'] == 'done', (
                f"Kỳ vọng 'done' (pipeline đã tự chạy thẳng vì thiếu MIS_đi), "
                f"nhận '{job['status']}' — job ĐÃ XONG bị gắn nhầm trạng thái chờ."
            )
            assert job['error'] is None
            assert any(f.startswith('doi_chieu_') for f in job['files'])
            assert job['xac_nhan_file'] is None
        finally:
            ach_service.bo_job(job_id)

    def test_du_mis_di_dung_sau_mis_di_van_dung_o_checkpoint_nhu_cu(self, monkeypatch):
        """Regression — đủ MIS_đi (hành vi CŨ không đổi): dung_sau_mis_di=True
        vẫn phải dừng ở Checkpoint thật, không bị fix sai lệch sang 'done'."""
        monkeypatch.setenv('DOI_CHIEU_ZIP_PASSWORD', 'test_password')
        job_id, input_dir = ach_service.tao_job()
        try:
            _make_pdf(input_dir)
            _make_gw_xlsx(input_dir)
            _make_mis_di_zip(input_dir, 'doichieugd_20260711__01_DI_9999_N.zip', [_mis_di_row()])
            _make_mis_di_zip(input_dir, 'doichieugd_20260711__02_DI_9999_N.zip', [])

            job = ach_service.get_job(job_id)
            ach_service._run(
                job_id, str(input_dir), job['output_dir'], ngay=None,
                dung_sau_mis_di=True,
            )

            job = ach_service.get_job(job_id)
            assert job['status'] == 'awaiting_confirmation'
            assert job['xac_nhan_file'] is not None
            assert job['xac_nhan_file'].endswith('_ACH_ConfirmMISdi.xlsx')
        finally:
            ach_service.bo_job(job_id)
