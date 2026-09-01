"""Test thuật toán b2_xu_ly_gl02.py (GL02 -> NPO_đi/NPO_đến) và b6_xu_ly_mis_den.py
(MIS_đến) — dùng file zip AES thu nhỏ thật (không mock I/O), theo đúng pattern
_make_gl02_zip ở tests/test_cham459901_api.py.

Công thức theo DOI CHIEU ACH_v2.docx (đối chiếu với project_ach_timeout_rule.md):
- SO_TRACE (mục 4.1)   = 12 ký tự từ ký tự thứ 8 của REFERENCE (REFERENCE[7:19]),
  lstrip('0'); rỗng nếu REFERENCE None/rỗng; '0' nếu toàn số 0.
- KEY_DI  (mục 1)      = TRBRCD + SO_TRACE + CRAMOUNT   (NPO_đi,  CRAMOUNT != 0)
- KEY_DEN (mục 5)      = TRBRCD + SO_TRACE + DRAMOUNT   (NPO_đến, CRAMOUNT == 0)
- KEY_DEN_HUB (mục 5)  = CHI_NHANH + TRACE + SO_TIEN    (MIS_đến, sau lọc session/RJCT)

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_gl02_misden_algorithm.py -v
"""

import io
from datetime import datetime

import pandas as pd
import pyzipper

from backend.services.ach import config as _cfg
from backend.services.ach.b2_xu_ly_gl02 import xu_ly_gl02
from backend.services.ach.b6_xu_ly_mis_den import xu_ly_mis_den

_LOCAC_TARGET = '502003'
_CUSTOMER_ACH = '1000-003526275'

# REFERENCE[7:19] (0-index) = 12 ký tự bắt đầu từ vị trí thứ 8 (1-index).
# '1234567' (7 ký tự đệm) + '000123456789' (12 ký tự SO_TRACE thô) + đuôi bất kỳ.
_REF_NORMAL   = '1234567' + '000123456789' + 'XYZ'   # SO_TRACE -> '123456789'
_REF_ALL_ZERO = '1234567' + '000000000000' + 'XYZ'   # SO_TRACE -> '0' (không rỗng)


def _make_zip(rows: list[dict], cols: list[str]) -> bytes:
    df = pd.DataFrame(rows)[cols]
    csv_bytes = df.to_csv(index=False).encode('utf-8-sig')
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED,
                              encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(_cfg.zip_password())
        zf.writestr('data.csv', csv_bytes)
    return buf.getvalue()


# ─── B2 — GL02 -> NPO_đi / NPO_đến ────────────────────────────────────────────

_GL02_COLS = ['TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
              'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
              'DRAMOUNT', 'CRAMOUNT', 'CRTDTM']


def _gl02_row(trbrcd='1000', reference=_REF_NORMAL, dramount='0', cramount='0',
             locac=_LOCAC_TARGET, customer=_CUSTOMER_ACH):
    return {
        'TRDATE': '20260601', 'TRBRCD': trbrcd, 'USERID': '1000API0', 'JOURSEQ': '1',
        'DYTRSEQ': '1', 'LOCAC': locac, 'CCY': 'VND', 'BUSCD': 'EI', 'UNIT': 'AP',
        'TRCD': '', 'CUSTOMER': customer, 'TRTP': 'Normal', 'REFERENCE': reference,
        'REMARK': '', 'DRAMOUNT': dramount, 'CRAMOUNT': cramount, 'CRTDTM': '',
    }


def _write_gl02_zip(tmp_path, rows: list[dict]):
    path = tmp_path / 'GL02_20260601_1000.zip'
    path.write_bytes(_make_zip(rows, _GL02_COLS))
    return str(path)


class TestGl02SoTrace:
    def test_so_trace_lay_dung_12_ky_tu_tu_vi_tri_thu_8_va_bo_so_0_dau(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [_gl02_row(reference=_REF_NORMAL, cramount='100000')])
        npo_di, _ = xu_ly_gl02(zpath)
        assert npo_di.loc[0, 'SO_TRACE'] == '123456789'

    def test_so_trace_toan_so_0_giu_lai_1_ky_tu_0_khong_rong(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [_gl02_row(reference=_REF_ALL_ZERO, cramount='100000')])
        npo_di, _ = xu_ly_gl02(zpath)
        assert npo_di.loc[0, 'SO_TRACE'] == '0'

    def test_reference_rong_cho_so_trace_rong(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [_gl02_row(reference='', cramount='100000')])
        npo_di, _ = xu_ly_gl02(zpath)
        assert npo_di.loc[0, 'SO_TRACE'] == ''


class TestGl02PhanLoaiDiDen:
    def test_cramount_khac_0_vao_npo_di_cramount_bang_0_vao_npo_den(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='500000', dramount='0'),
            _gl02_row(reference=_REF_NORMAL, cramount='0', dramount='300000'),
        ])
        npo_di, npo_den = xu_ly_gl02(zpath)
        assert len(npo_di) == 1 and len(npo_den) == 1
        assert npo_di.loc[0, 'CRAMOUNT'] == 500000
        assert npo_den.loc[0, 'DRAMOUNT'] == 300000

    def test_bat_bien_tong_dong_bao_toan_qua_2_nhom(self, tmp_path):
        rows = [_gl02_row(reference=_REF_NORMAL, cramount=str(i * 1000), dramount='0')
                for i in range(1, 4)] + [
                _gl02_row(reference=_REF_NORMAL, cramount='0', dramount=str(i * 2000))
                for i in range(1, 3)]
        zpath = _write_gl02_zip(tmp_path, rows)
        npo_di, npo_den = xu_ly_gl02(zpath)
        assert len(npo_di) + len(npo_den) == len(rows)

    def test_key_di_ghep_dung_thu_tu_trbrcd_sotrace_cramount(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(trbrcd='2207', reference=_REF_NORMAL, cramount='500000'),
        ])
        npo_di, _ = xu_ly_gl02(zpath)
        assert npo_di.loc[0, 'KEY_DI'] == '2207' + '123456789' + '500000'

    def test_key_den_ghep_dung_thu_tu_trbrcd_sotrace_dramount(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(trbrcd='6320', reference=_REF_NORMAL, cramount='0', dramount='400000'),
        ])
        _, npo_den = xu_ly_gl02(zpath)
        assert npo_den.loc[0, 'KEY_DEN'] == '6320' + '123456789' + '400000'

    def test_cramount_ngan_nghin_khong_bi_cat_khi_build_key(self, tmp_path):
        """Regression: '180.000' phải ra 180000 khi build KEY_DI, không bị
        to_numeric() cắt còn 180 (xem backend/services/ach/so_tien.py)."""
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='180.000', dramount='0'),
        ])
        npo_di, _ = xu_ly_gl02(zpath)
        assert npo_di.loc[0, 'CRAMOUNT'] == 180_000
        assert npo_di.loc[0, 'KEY_DI'].endswith('180000')

    def test_dramount_ngan_nghin_phay_khong_bi_mat_ve_0(self, tmp_path):
        """'400,000' (dấu phẩy ngăn nghìn) phải ra 400000, không bị to_numeric()
        coerce về 0 (chuỗi có dấu phẩy không phải float hợp lệ)."""
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='0', dramount='400,000'),
        ])
        _, npo_den = xu_ly_gl02(zpath)
        assert npo_den.loc[0, 'DRAMOUNT'] == 400_000

    def test_cramount_khong_hop_le_raise(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='1.5', dramount='0'),
        ])
        try:
            xu_ly_gl02(zpath)
            assert False, "Phải raise ValueError khi CRAMOUNT không đúng định dạng"
        except ValueError as e:
            assert 'không đúng định dạng' in str(e)


class TestGl02LocLocacCustomer:
    def test_loai_dong_sai_locac(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='100000', locac='999999'),
        ])
        npo_di, npo_den = xu_ly_gl02(zpath)
        assert len(npo_di) == 0 and len(npo_den) == 0

    def test_loai_dong_sai_customer(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='100000', customer='khac'),
        ])
        npo_di, npo_den = xu_ly_gl02(zpath)
        assert len(npo_di) == 0 and len(npo_den) == 0

    def test_giu_dong_dung_ca_locac_va_customer(self, tmp_path):
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='100000',
                     locac=_LOCAC_TARGET, customer=_CUSTOMER_ACH),
        ])
        npo_di, _ = xu_ly_gl02(zpath)
        assert len(npo_di) == 1

    def test_toan_bo_dong_bi_loc_het_khong_crash_tra_ve_2_df_rong(self, tmp_path):
        """Regression: trước khi sửa, npo_di['KEY_DI'] = ... trên DataFrame rỗng
        (0 dòng qua được lọc LOCAC/CUSTOMER) raise TypeError ('radd' not supported)
        do dtype ArrowStringArray rỗng cộng với cột .astype(str) rỗng — crash toàn
        bộ pipeline dù đây là tình huống thật có thể xảy ra (vd sai ngày file GL02)."""
        zpath = _write_gl02_zip(tmp_path, [
            _gl02_row(reference=_REF_NORMAL, cramount='100000', locac='999999'),
            _gl02_row(reference=_REF_NORMAL, cramount='0', dramount='50000', locac='999999'),
        ])
        npo_di, npo_den = xu_ly_gl02(zpath)
        assert len(npo_di) == 0
        assert len(npo_den) == 0
        assert 'KEY_DI' in npo_di.columns
        assert 'KEY_DEN' in npo_den.columns


# ─── B6 — MIS_đến ─────────────────────────────────────────────────────────────

_MIS_DEN_COLS = ['NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
                  'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
                  'SESSION', 'LOAI_LENH_OSB', 'NH_GUI', 'NOI_DUNG']

_SID   = '16302'
_NGAY  = datetime(2026, 7, 7)
_NGAY_STR = '07/07/2026'


def _mis_den_row(chi_nhanh='1000', refhub='REF1', trace="'0000123456", so_tien='100000',
                 session=_SID, trang_thai='SCNL', ngay=_NGAY_STR):
    return {
        'NGAY_GIAO_DICH': ngay, 'CHI_NHANH': chi_nhanh, 'REFHUB': refhub,
        'MSGREF': "'MSG1", 'MSGSEQ': "'", 'TXID': 'TX1', 'KENH_THANH_TOAN': 'ACH-NAPAS',
        'TRANG_THAI_LENH': trang_thai, 'SO_TIEN': so_tien, 'TRACE': trace,
        'SESSION': session, 'LOAI_LENH_OSB': '', 'NH_GUI': 'NH X', 'NOI_DUNG': 'nd',
    }


def _write_mis_den_zip(tmp_path, rows: list[dict], name='doichieugd_20260707__01_DEN_9999_N.zip'):
    path = tmp_path / name
    path.write_bytes(_make_zip(rows, _MIS_DEN_COLS))
    return str(path)


class TestMisDenLocSession:
    def test_dung_session_doi_chieu_duoc_giu(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [_mis_den_row(session=_SID)])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert len(df) == 1

    def test_session_khac_khong_rong_bi_loai(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [_mis_den_row(session='99999')])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert len(df) == 0

    def test_session_rong_dung_ngay_doi_chieu_duoc_giu(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(session='', ngay=_NGAY_STR),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert len(df) == 1

    def test_session_rong_khac_ngay_doi_chieu_bi_loai(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(session='', ngay='06/07/2026'),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert len(df) == 0

    def test_trang_thai_rjct_bi_loai_du_dung_session(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(session=_SID, trang_thai='RJCT'),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert len(df) == 0


class TestMisDenKeyDenHub:
    def test_key_den_hub_ghep_dung_thu_tu_chinhanh_trace_sotien(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(chi_nhanh='6320', trace="'0000123456", so_tien='400000', session=_SID),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        # TRACE "'0000123456".lstrip("'0") -> "123456"
        assert df.loc[0, 'KEY_DEN_HUB'] == '6320' + '123456' + '400000'

    def test_trace_bo_dau_nhay_va_so_0_dau(self, tmp_path):
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(trace="'00789", session=_SID),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert df.loc[0, 'TRACE'] == '789'

    def test_toan_bo_dong_bi_loc_het_khong_crash(self, tmp_path):
        """Cùng loại rủi ro dtype-rỗng đã tìm thấy và sửa ở b2_xu_ly_gl02.py — kiểm
        tra b6 không dính lỗi tương tự khi mọi dòng bị loại (vd session khác hết)."""
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(session='99999'),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert len(df) == 0
        assert 'KEY_DEN_HUB' in df.columns

    def test_key_den_hub_so_tien_ngan_nghin_khong_bi_cat(self, tmp_path):
        """Regression: '180.000' phải ra 180000 khi build KEY_DEN_HUB, không bị
        to_numeric() cắt còn 180."""
        zpath = _write_mis_den_zip(tmp_path, [
            _mis_den_row(chi_nhanh='6320', trace="'0000123456", so_tien='180.000', session=_SID),
        ])
        df = xu_ly_mis_den([zpath], _SID, _NGAY)
        assert df.loc[0, 'SO_TIEN'] == 180_000
        assert df.loc[0, 'KEY_DEN_HUB'].endswith('180000')
