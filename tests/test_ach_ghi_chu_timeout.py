"""Test thuật toán Mục 1.1 + 1.1.1 — b12_ghi_chu_timeout.py (gắn GHI_CHU lên
TIMEOUT_KHONG_KENH, NPO_DI_THUA, và QT đi thừa — đối chiếu chéo cùng ngày T).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_ghi_chu_timeout.py -v
"""
import pandas as pd
import pytest

from backend.services.ach.b12_ghi_chu_timeout import (
    GHI_CHU_KHOP_NPO, GHI_CHU_KHOP_QT, GHI_CHU_KHONG_CO, GHI_CHU_TIMEOUT_KHOP,
    gan_ghi_chu_timeout, gan_ghi_chu_npo_di_thua, gan_ghi_chu_qt_di_thua,
    GHI_CHU_TIMEOUT_CU, TT_DOI_CHIEU_NPO, TT_DOI_CHIEU_QT, TT_DOI_CHIEU_HUY,
    TT_DOI_CHIEU_KHONG_CO, doi_chieu_timeout_cu,
)


# ── Fixtures dùng chung ─────────────────────────────────────────────────────

def _timeout_row(key_hub):
    return {'KEY_HUB': key_hub, 'CHI_NHANH': '1240', 'SO_TIEN': '1000000'}


def _npo_di_thua_row(key_di):
    return {'KEY_DI': key_di, 'TRBRCD': '1240', 'CRAMOUNT': 1_000_000}


def _qt_row(cn_trace_tien):
    return {'CN_TRACE_TIEN': cn_trace_tien, 'SO_TIEN': 1_000_000}


# ── gan_ghi_chu_timeout ──────────────────────────────────────────────────────

class TestGanGhiChuTimeout:
    def test_3_nhan_npo_qt_khong_co(self):
        df_timeout = pd.DataFrame([
            _timeout_row('KEY_NPO'),
            _timeout_row('KEY_QT'),
            _timeout_row('KEY_KHONG'),
        ])
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row('KEY_NPO')])
        df_qt_di       = pd.DataFrame([_qt_row('KEY_QT')])

        out = gan_ghi_chu_timeout(df_timeout, df_npo_di_thua, df_qt_di)

        assert out.loc[out['KEY_HUB'] == 'KEY_NPO', 'GHI_CHU'].iloc[0] == GHI_CHU_KHOP_NPO
        assert out.loc[out['KEY_HUB'] == 'KEY_QT',  'GHI_CHU'].iloc[0] == GHI_CHU_KHOP_QT
        assert out.loc[out['KEY_HUB'] == 'KEY_KHONG', 'GHI_CHU'].iloc[0] == GHI_CHU_KHONG_CO

    def test_khop_ca_hai_uu_tien_npo(self):
        df_timeout     = pd.DataFrame([_timeout_row('KEY_CA_HAI')])
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row('KEY_CA_HAI')])
        df_qt_di       = pd.DataFrame([_qt_row('KEY_CA_HAI')])

        out = gan_ghi_chu_timeout(df_timeout, df_npo_di_thua, df_qt_di)

        assert out['GHI_CHU'].iloc[0] == GHI_CHU_KHOP_NPO

    def test_khong_co_file_qt_van_khop_npo(self):
        df_timeout     = pd.DataFrame([_timeout_row('KEY_NPO'), _timeout_row('KEY_KHONG')])
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row('KEY_NPO')])

        out = gan_ghi_chu_timeout(df_timeout, df_npo_di_thua, None)

        assert out.loc[out['KEY_HUB'] == 'KEY_NPO', 'GHI_CHU'].iloc[0] == GHI_CHU_KHOP_NPO
        assert out.loc[out['KEY_HUB'] == 'KEY_KHONG', 'GHI_CHU'].iloc[0] == GHI_CHU_KHONG_CO

    def test_df_timeout_rong_tra_ve_nguyen(self):
        df_timeout = pd.DataFrame(columns=['KEY_HUB'])
        out = gan_ghi_chu_timeout(df_timeout, None, None)
        assert len(out) == 0

    def test_df_timeout_none_tra_ve_none(self):
        assert gan_ghi_chu_timeout(None, None, None) is None


# ── gan_ghi_chu_npo_di_thua ──────────────────────────────────────────────────

class TestGanGhiChuNpoDiThua:
    def test_khop_va_khong_khop(self):
        df_npo_di_thua = pd.DataFrame([
            _npo_di_thua_row('KEY_KHOP'),
            _npo_di_thua_row('KEY_KHONG_KHOP'),
        ])
        df_timeout = pd.DataFrame([_timeout_row('KEY_KHOP')])

        out = gan_ghi_chu_npo_di_thua(df_npo_di_thua, df_timeout)

        assert out.loc[out['KEY_DI'] == 'KEY_KHOP', 'GHI_CHU'].iloc[0] == GHI_CHU_TIMEOUT_KHOP
        assert out.loc[out['KEY_DI'] == 'KEY_KHONG_KHOP', 'GHI_CHU'].iloc[0] == ''

    def test_df_timeout_rong_toan_bo_rong(self):
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row('KEY_A')])
        out = gan_ghi_chu_npo_di_thua(df_npo_di_thua, pd.DataFrame(columns=['KEY_HUB']))
        assert (out['GHI_CHU'] == '').all()

    def test_df_timeout_none_toan_bo_rong_khong_loi(self):
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row('KEY_A')])
        out = gan_ghi_chu_npo_di_thua(df_npo_di_thua, None)
        assert (out['GHI_CHU'] == '').all()

    def test_df_npo_di_thua_none_tra_ve_none(self):
        assert gan_ghi_chu_npo_di_thua(None, None) is None

    def test_df_npo_di_thua_rong_tra_ve_nguyen(self):
        df_npo_di_thua = pd.DataFrame(columns=['KEY_DI'])
        out = gan_ghi_chu_npo_di_thua(df_npo_di_thua, None)
        assert len(out) == 0


# ── gan_ghi_chu_qt_di_thua ───────────────────────────────────────────────────

class TestGanGhiChuQtDiThua:
    def test_chi_tra_ve_phan_qt_khong_lan_mis(self):
        df_di_chua_khop = pd.DataFrame([
            {'NGUON': 'MIS', 'KEY_HUB': 'KEY_MIS_1'},
            {'NGUON': 'QT',  'CN_TRACE_TIEN': 'KEY_QT_KHOP'},
            {'NGUON': 'QT',  'CN_TRACE_TIEN': 'KEY_QT_KHONG_KHOP'},
        ])
        df_timeout = pd.DataFrame([_timeout_row('KEY_QT_KHOP')])

        out = gan_ghi_chu_qt_di_thua(df_di_chua_khop, df_timeout)

        assert set(out['NGUON']) == {'QT'}
        assert len(out) == 2
        assert out.loc[out['CN_TRACE_TIEN'] == 'KEY_QT_KHOP', 'GHI_CHU'].iloc[0] == GHI_CHU_TIMEOUT_KHOP
        assert out.loc[out['CN_TRACE_TIEN'] == 'KEY_QT_KHONG_KHOP', 'GHI_CHU'].iloc[0] == ''

    def test_thieu_cot_nguon_raise(self):
        df_di_chua_khop = pd.DataFrame([{'CN_TRACE_TIEN': 'X'}])
        with pytest.raises(ValueError):
            gan_ghi_chu_qt_di_thua(df_di_chua_khop, None)

    def test_df_di_chua_khop_none_tra_ve_none(self):
        assert gan_ghi_chu_qt_di_thua(None, None) is None

    def test_df_di_chua_khop_rong_tra_ve_none(self):
        df_di_chua_khop = pd.DataFrame(columns=['NGUON', 'CN_TRACE_TIEN'])
        assert gan_ghi_chu_qt_di_thua(df_di_chua_khop, None) is None

    def test_khong_co_timeout_toan_bo_rong(self):
        df_di_chua_khop = pd.DataFrame([{'NGUON': 'QT', 'CN_TRACE_TIEN': 'KEY_QT_1'}])
        out = gan_ghi_chu_qt_di_thua(df_di_chua_khop, None)
        assert (out['GHI_CHU'] == '').all()


# ── Mục 8 (bổ sung 14.09.2026) — doi_chieu_timeout_cu() ─────────────────────
# Đối chiếu TO ko đi kênh NGÀY CŨ (input tuỳ chọn người dùng tự nạp thêm) với
# NPO_đi thừa/QT_đi thừa/Huỷ trong ngày CỦA NGÀY ĐANG CHẠY.

def _timeout_cu_row(key_hub, ngay_giao_dich='03/09/2026'):
    return {'KEY_HUB': key_hub, 'CHI_NHANH': '1240', 'SO_TIEN': '1000000',
            'NGAY_GIAO_DICH': ngay_giao_dich}


def _huy_trong_ngay_row(key_di):
    return {'KEY_DI': key_di, 'TRBRCD': '1240', 'CRAMOUNT': 1_000_000}


class TestDoiChieuTimeoutCu:
    def test_4_nhan_npo_qt_huy_khong_co(self):
        df_timeout_cu = pd.DataFrame([
            _timeout_cu_row('KEY_NPO'),
            _timeout_cu_row('KEY_QT'),
            _timeout_cu_row('KEY_HUY'),
            _timeout_cu_row('KEY_KHONG'),
        ])
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row('KEY_NPO')])
        df_qt_di_thua  = pd.DataFrame([_qt_row('KEY_QT')])
        df_huy_trong_ngay = pd.DataFrame([_huy_trong_ngay_row('KEY_HUY')])

        out, _, _ = doi_chieu_timeout_cu(
            df_timeout_cu, df_npo_di_thua, df_qt_di_thua, df_huy_trong_ngay,
        )

        assert out.loc[out['KEY_HUB'] == 'KEY_NPO',   'TT_DOI_CHIEU'].iloc[0] == TT_DOI_CHIEU_NPO
        assert out.loc[out['KEY_HUB'] == 'KEY_QT',    'TT_DOI_CHIEU'].iloc[0] == TT_DOI_CHIEU_QT
        assert out.loc[out['KEY_HUB'] == 'KEY_HUY',   'TT_DOI_CHIEU'].iloc[0] == TT_DOI_CHIEU_HUY
        assert out.loc[out['KEY_HUB'] == 'KEY_KHONG', 'TT_DOI_CHIEU'].iloc[0] == TT_DOI_CHIEU_KHONG_CO

    def test_khop_huy_va_npo_uu_tien_npo(self):
        """Ưu tiên theo đúng thứ tự liệt kê trong văn bản: NPO > QT > Huỷ."""
        df_timeout_cu     = pd.DataFrame([_timeout_cu_row('KEY_CA_HAI')])
        df_npo_di_thua    = pd.DataFrame([_npo_di_thua_row('KEY_CA_HAI')])
        df_huy_trong_ngay = pd.DataFrame([_huy_trong_ngay_row('KEY_CA_HAI')])

        out, _, _ = doi_chieu_timeout_cu(
            df_timeout_cu, df_npo_di_thua, None, df_huy_trong_ngay,
        )

        assert out['TT_DOI_CHIEU'].iloc[0] == TT_DOI_CHIEU_NPO

    def test_tu_tinh_key_hub_khi_thieu(self):
        """File người dùng tự gõ tay không có sẵn KEY_HUB — phải tự tính lại từ
        CHI_NHANH/TRACE/SE_TRACE/SO_TIEN (đúng công thức _them_cot_khoa())."""
        df_timeout_cu = pd.DataFrame([
            {'CHI_NHANH': '1240', 'TRACE': '000142755985', 'SE_TRACE': '', 'SO_TIEN': '1000000',
             'NGAY_GIAO_DICH': '03/09/2026'},
        ])
        key_hub = '1240' + '142755985' + '1000000'
        df_npo_di_thua = pd.DataFrame([_npo_di_thua_row(key_hub)])

        out, _, _ = doi_chieu_timeout_cu(df_timeout_cu, df_npo_di_thua, None, None)

        assert out.loc[0, 'TT_DOI_CHIEU'] == TT_DOI_CHIEU_NPO

    def test_df_timeout_cu_none_tra_ve_nguyen(self):
        df_npo = pd.DataFrame([_npo_di_thua_row('X')])
        out, out_npo, out_qt = doi_chieu_timeout_cu(None, df_npo, None, None)
        assert out is None
        assert out_npo is df_npo

    def test_ghi_chu_npo_khong_ghi_de_da_co_san(self):
        """1 dòng NPO ĐÃ có GHI_CHU sẵn (giả lập Mục 1.1 đã giải thích bằng chính
        ngày đang chạy) khớp với timeout cũ — GHI_CHU KHÔNG bị ghi đè. 1 dòng
        GHI_CHU rỗng khớp timeout cũ — được điền 'TO ko đi kênh'."""
        df_timeout_cu = pd.DataFrame([
            _timeout_cu_row('KEY_DA_CO'),
            _timeout_cu_row('KEY_RONG'),
        ])
        df_npo_di_thua = pd.DataFrame([
            {**_npo_di_thua_row('KEY_DA_CO'), 'GHI_CHU': GHI_CHU_KHOP_NPO},
            {**_npo_di_thua_row('KEY_RONG'),  'GHI_CHU': ''},
        ])

        _, out_npo, _ = doi_chieu_timeout_cu(df_timeout_cu, df_npo_di_thua, None, None)

        assert out_npo.loc[out_npo['KEY_DI'] == 'KEY_DA_CO', 'GHI_CHU'].iloc[0] == GHI_CHU_KHOP_NPO
        assert out_npo.loc[out_npo['KEY_DI'] == 'KEY_RONG',  'GHI_CHU'].iloc[0] == GHI_CHU_TIMEOUT_CU

    def test_ghi_chu_qt_khong_ghi_de_da_co_san(self):
        """QT đi thừa khớp timeout cũ phải nhận nhãn KÈM NGÀY cụ thể (NGAY_GIAO_DICH
        của dòng timeout cũ đã khớp) — KHÁC NPO vẫn giữ nhãn chung GHI_CHU_TIMEOUT_CU
        (bất đối xứng có chủ đích, Thảo xác nhận 15.09.2026)."""
        df_timeout_cu = pd.DataFrame([
            _timeout_cu_row('KEY_DA_CO', ngay_giao_dich='01/09/2026'),
            _timeout_cu_row('KEY_RONG',  ngay_giao_dich='02/09/2026'),
        ])
        df_qt_di_thua = pd.DataFrame([
            {**_qt_row('KEY_DA_CO'), 'GHI_CHU': GHI_CHU_KHOP_QT},
            {**_qt_row('KEY_RONG'),  'GHI_CHU': ''},
        ])

        _, _, out_qt = doi_chieu_timeout_cu(df_timeout_cu, None, df_qt_di_thua, None)

        assert out_qt.loc[out_qt['CN_TRACE_TIEN'] == 'KEY_DA_CO', 'GHI_CHU'].iloc[0] == GHI_CHU_KHOP_QT
        assert out_qt.loc[out_qt['CN_TRACE_TIEN'] == 'KEY_RONG',  'GHI_CHU'].iloc[0] == 'TO ko đi kênh ngày 02/09/2026'

    def test_ghi_chu_npo_van_la_nhan_chung_khong_kem_ngay(self):
        """Đối xứng ngược lại của test trên — NPO đi thừa khớp timeout cũ VẪN dùng
        nhãn chung 'TO ko đi kênh', KHÔNG kèm ngày, dù timeout cũ có NGAY_GIAO_DICH."""
        df_timeout_cu = pd.DataFrame([
            _timeout_cu_row('KEY_RONG', ngay_giao_dich='05/09/2026'),
        ])
        df_npo_di_thua = pd.DataFrame([
            {**_npo_di_thua_row('KEY_RONG'), 'GHI_CHU': ''},
        ])

        _, out_npo, _ = doi_chieu_timeout_cu(df_timeout_cu, df_npo_di_thua, None, None)

        assert out_npo.loc[out_npo['KEY_DI'] == 'KEY_RONG', 'GHI_CHU'].iloc[0] == GHI_CHU_TIMEOUT_CU
        assert '05/09/2026' not in out_npo.loc[out_npo['KEY_DI'] == 'KEY_RONG', 'GHI_CHU'].iloc[0]

    def test_thieu_cot_ngay_giao_dich_raise(self):
        """df_timeout_cu không có cột NGAY_GIAO_DICH (VD gọi doi_chieu_timeout_cu()
        trực tiếp, bỏ qua doc_timeout_cu() vốn đã bắt buộc cột này) — raise rõ ràng,
        không âm thầm bỏ qua nhãn ngày."""
        df_timeout_cu = pd.DataFrame([
            {'KEY_HUB': 'KEY_X', 'CHI_NHANH': '1240', 'SO_TIEN': '1000000'},
        ])
        with pytest.raises(ValueError):
            doi_chieu_timeout_cu(df_timeout_cu, None, None, None)

    def test_khoa_trung_khac_ngay_lay_dong_dau_tien_va_canh_bao(self):
        """1 KEY_HUB trùng khoá nhưng khác NGAY_GIAO_DICH (hiếm, dữ liệu trùng khoá)
        — lấy dòng ĐẦU TIÊN theo thứ tự dữ liệu, không suy luận phức tạp hơn."""
        df_timeout_cu = pd.DataFrame([
            _timeout_cu_row('KEY_TRUNG', ngay_giao_dich='01/09/2026'),
            _timeout_cu_row('KEY_TRUNG', ngay_giao_dich='02/09/2026'),
        ])
        df_qt_di_thua = pd.DataFrame([
            {**_qt_row('KEY_TRUNG'), 'GHI_CHU': ''},
        ])
        logs = []

        _, _, out_qt = doi_chieu_timeout_cu(
            df_timeout_cu, None, df_qt_di_thua, None, log_callback=logs.append,
        )

        assert out_qt['GHI_CHU'].iloc[0] == 'TO ko đi kênh ngày 01/09/2026'
        assert any('CẢNH BÁO' in m and 'KEY_HUB' in m for m in logs)

    def test_khong_co_gi_khop_toan_bo_khong_co(self):
        df_timeout_cu = pd.DataFrame([_timeout_cu_row('KEY_LE_LOI')])
        out, _, _ = doi_chieu_timeout_cu(df_timeout_cu, None, None, None)
        assert (out['TT_DOI_CHIEU'] == TT_DOI_CHIEU_KHONG_CO).all()

    def test_ngay_giao_dich_dinh_khoang_trang_thua_duoc_strip(self):
        """NGAY_GIAO_DICH của timeout cũ dính khoảng trắng thừa đầu/cuối (dữ liệu
        thực đã gặp — b4_xu_ly_mis_di.py cũng phải .str.strip() cột này) — nhãn
        GHI_CHU cuối cùng trên QT đi thừa KHÔNG được dính khoảng trắng thừa."""
        df_timeout_cu = pd.DataFrame([
            _timeout_cu_row('KEY_RONG', ngay_giao_dich='  04/09/2026 '),
        ])
        df_qt_di_thua = pd.DataFrame([
            {**_qt_row('KEY_RONG'), 'GHI_CHU': ''},
        ])

        _, _, out_qt = doi_chieu_timeout_cu(df_timeout_cu, None, df_qt_di_thua, None)

        ghi_chu = out_qt.loc[out_qt['CN_TRACE_TIEN'] == 'KEY_RONG', 'GHI_CHU'].iloc[0]
        assert ghi_chu == 'TO ko đi kênh ngày 04/09/2026'
        assert ghi_chu == ghi_chu.strip()
