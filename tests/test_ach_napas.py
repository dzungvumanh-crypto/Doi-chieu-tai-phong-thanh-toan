"""Test Mục 6/7 (bổ sung 11.09.2026 + 14.09.2026) — b15_napas.py: trích Tổng
SL/Giá trị Ghi nợ (đi)/Ghi có (đến) từ báo cáo Napas BC.03 (PDF), đọc CSV Napas
chi tiết (ISS/BEN), và đối chiếu MsgId (Napas) với MSGREF (GW).

TestDocPdfNapas (golden, dùng dữ liệu thật) — Bước 0 đo cấu trúc dòng "Tổng" trên
3 ngày thật (04.09/05.09/06.09.2026, `G:\\NGUYEN TAC DOI CHIEU ACH\\04-06.09\\`)
bằng pypdfium2, xác nhận index cố định giống nhau cả 3 ngày và khớp đúng 4 số
Business Owner đọc trực tiếp từ bản render PDF TRƯỚC khi viết code trích số này
(04.09: SL Ghi nợ=533,896 Giá trị=3,081,559,142,449 SL Ghi có=569,337
Giá trị=3,593,883,470,596; 05.09: SL Ghi nợ=576,184 Giá trị=1,514,859,623,896
SL Ghi có=572,966 Giá trị=1,812,607,203,892). Test golden này FAIL trên máy không
có ổ G: — bị skip tự động (`@pytest.mark.skipif`), không phá CI/máy khác.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_napas.py -v
"""
import os

import pandas as pd
import pytest

from backend.services.ach.b15_napas import doc_pdf_napas, doc_napas_csv, doi_chieu_napas_gw
import backend.services.ach.b15_napas as b15


# ── Golden test — file PDF thật, đường dẫn tuyệt đối ──────────────────────────

_DIR_0409 = r'G:\NGUYEN TAC DOI CHIEU ACH\04-06.09\dữ liệu ngày 04.09'
_DIR_0509 = r'G:\NGUYEN TAC DOI CHIEU ACH\04-06.09\dữ liệu ngày 05.09'
_PDF_0409 = os.path.join(_DIR_0409, 'ACH_20260905_VBAAVNVN_NRT_16536_N03_1.pdf')
_PDF_0509 = os.path.join(_DIR_0509, 'ACH_20260906_VBAAVNVN_NRT_16538_N03_1.pdf')

_CO_O_G = os.path.isdir(r'G:\NGUYEN TAC DOI CHIEU ACH')


@pytest.mark.skipif(not _CO_O_G, reason='Cần ổ G: (dữ liệu thật NGUYEN TAC DOI CHIEU ACH) — bỏ qua trên máy không có.')
class TestDocPdfNapasGolden:
    def test_04_09(self):
        ket_qua = doc_pdf_napas(_PDF_0409)
        assert ket_qua == {
            'n_di': 533_896, 's_di': 3_081_559_142_449,
            'n_den': 569_337, 's_den': 3_593_883_470_596,
        }

    def test_05_09(self):
        ket_qua = doc_pdf_napas(_PDF_0509)
        assert ket_qua == {
            'n_di': 576_184, 's_di': 1_514_859_623_896,
            'n_den': 572_966, 's_den': 1_812_607_203_892,
        }


# ── doc_pdf_napas() — validate/raise, dùng text giả lập (monkeypatch I/O) ────

_DONG_TONG_HOP_LE = (
    'Tổng 100 1,000,000 10 5 0 0 15 1,000,015 200 2,000,000 0 0 0 0 0 2,000,000 500,000 15'
)


def _gia_lap_text(monkeypatch, text: str):
    monkeypatch.setattr(b15, '_doc_full_text_pdf', lambda path: text)


class TestDocPdfNapasValidate:
    def test_khong_co_dong_tong_raise(self, monkeypatch):
        _gia_lap_text(monkeypatch, 'Tổng phí Tổng cộng Tổng phí Tổng cộng\nkhông có gì khác')
        with pytest.raises(ValueError, match='Không tìm thấy'):
            doc_pdf_napas('gia_lap.pdf')

    def test_nhieu_hon_1_dong_tong_raise(self, monkeypatch):
        text = f'{_DONG_TONG_HOP_LE}\n{_DONG_TONG_HOP_LE}'
        _gia_lap_text(monkeypatch, text)
        with pytest.raises(ValueError, match='Tìm thấy 2 dòng'):
            doc_pdf_napas('gia_lap.pdf')

    def test_sai_so_luong_so_raise(self, monkeypatch):
        _gia_lap_text(monkeypatch, 'Tổng 100 1,000,000 10')
        with pytest.raises(ValueError, match='kỳ vọng 18'):
            doc_pdf_napas('gia_lap.pdf')

    def test_tu_kiem_chung_sai_lech_raise(self, monkeypatch):
        """Đổi Tổng cộng Ghi nợ (index 7) sai — không còn bằng Giá trị + Tổng phí —
        phải raise, KHÔNG được âm thầm trả số sai."""
        dong = (
            'Tổng 100 1,000,000 10 5 0 0 15 999,999,999 200 2,000,000 0 0 0 0 0 2,000,000 500,000 15'
        )
        _gia_lap_text(monkeypatch, dong)
        with pytest.raises(ValueError, match='Tự kiểm chứng thất bại'):
            doc_pdf_napas('gia_lap.pdf')

    def test_dong_hop_le_tra_dung_4_so(self, monkeypatch):
        _gia_lap_text(monkeypatch, _DONG_TONG_HOP_LE)
        ket_qua = doc_pdf_napas('gia_lap.pdf')
        assert ket_qua == {'n_di': 100, 's_di': 1_000_000, 'n_den': 200, 's_den': 2_000_000}

    def test_khong_bat_nham_nhan_cot_tong_phi(self, monkeypatch):
        """'Tổng phí Tổng cộng...' không có số theo sau — không được coi là dòng
        'Tổng' thật (đúng đặc tả: 'Tổng ' có khoảng trắng rồi số ngay sau)."""
        text = f'Tổng phí Tổng cộng Tổng phí Tổng cộng\n{_DONG_TONG_HOP_LE}'
        _gia_lap_text(monkeypatch, text)
        ket_qua = doc_pdf_napas('gia_lap.pdf')  # phải chạy được, chỉ 1 dòng "Tổng <số>" thật
        assert ket_qua['n_di'] == 100


# ── doc_napas_csv() ────────────────────────────────────────────────────────────

def _viet_csv_napas(path, rows):
    df = pd.DataFrame(rows)
    df.to_csv(path, sep=';', index=False, encoding='utf-8-sig')


class TestDocNapasCsv:
    def test_loai_dong_trailer(self, tmp_path):
        """Cột '001'=='003' là trailer/checksum, không phải giao dịch — phải bị
        loại (bẫy thật: BEN/ISS 04.09 & 05.09 đều có đúng 1 dòng trailer cuối
        file, MsgId rỗng)."""
        path = tmp_path / 'napas.csv'
        _viet_csv_napas(path, [
            {'001': '002', 'MsgId': 'M1', 'SttlmAmount': '100000'},
            {'001': '002', 'MsgId': 'M2', 'SttlmAmount': '200000'},
            {'001': '003', 'MsgId': '', 'SttlmAmount': ''},
        ])
        df = doc_napas_csv(str(path))
        assert len(df) == 2
        assert sorted(df['MsgId']) == ['M1', 'M2']

    def test_boc_dau_nhay_don_dau_msgid(self, tmp_path):
        path = tmp_path / 'napas.csv'
        _viet_csv_napas(path, [
            {'001': '002', 'MsgId': "'M1", 'SttlmAmount': '100000'},
        ])
        df = doc_napas_csv(str(path))
        assert list(df['MsgId']) == ['M1']

    def test_msgid_rong_giu_lai_khong_mat(self, tmp_path):
        """Bẫy thực nghiệm 14.09.2026 — dòng giao dịch thật (cột '001'=='002')
        nhưng MsgId RỖNG (lỗi dữ liệu nguồn, đo được ở BEN 04.09: đúng 2 dòng) vẫn
        phải được GIỮ LẠI trong kết quả (không lọc bỏ), MsgId đổi về chuỗi rỗng
        '' (không phải NaN) — để tầng đối chiếu không làm nó biến mất khỏi cả 2
        bên (xem TestDoiChieuNapasGw.test_msgid_rong_lam_napas_thua_khong_bien_mat)."""
        path = tmp_path / 'napas.csv'
        _viet_csv_napas(path, [
            {'001': '002', 'MsgId': 'M1', 'SttlmAmount': '100000'},
            {'001': '002', 'MsgId': '', 'SttlmAmount': '300000'},
        ])
        df = doc_napas_csv(str(path))
        assert len(df) == 2
        assert '' in df['MsgId'].tolist()
        assert df['MsgId'].isna().sum() == 0

    def test_thieu_cot_msgid_raise(self, tmp_path):
        path = tmp_path / 'napas.csv'
        pd.DataFrame([{'001': '002', 'SttlmAmount': '100000'}]).to_csv(
            path, sep=';', index=False, encoding='utf-8-sig',
        )
        with pytest.raises(ValueError, match='MsgId'):
            doc_napas_csv(str(path))


# ── doi_chieu_napas_gw() ───────────────────────────────────────────────────────

def _napas_df(msgid_list, amt=100000):
    n = len(msgid_list)
    return pd.DataFrame({'MsgId': msgid_list, 'SttlmAmount': [str(amt)] * n})


def _gw_df(msgref_list, amt=100000):
    n = len(msgref_list)
    return pd.DataFrame({'MSGREF': msgref_list, 'STTLMAMT': [amt] * n})


class TestDoiChieuNapasGw:
    def test_khop_dung_napas_thua_gw_thua(self):
        df_napas = _napas_df(['M1', 'M3'])
        df_gw    = _gw_df(['M1', 'M2'])
        df_khop, df_napas_thua, df_gw_thua = doi_chieu_napas_gw(df_napas, df_gw, 'MSGREF')
        assert list(df_khop['MsgId']) == ['M1']
        assert list(df_napas_thua['MsgId']) == ['M3']
        assert list(df_gw_thua['MSGREF']) == ['M2']

    def test_khop_giu_cot_napas_khong_phai_cot_gw(self):
        """df_khop phải là phía Napas (nhiều cột chi tiết hơn), cùng quy ước
        doi_chieu_gw_den() trả về phía MIS."""
        df_khop, _, _ = doi_chieu_napas_gw(_napas_df(['M1']), _gw_df(['M1']), 'MSGREF')
        assert 'SttlmAmount' in df_khop.columns

    def test_trung_so_luong_theo_count(self):
        """2 dòng M1 ở Napas, 1 dòng M1 ở GW — chỉ khớp 1 (theo count), 1 dòng
        Napas còn lại là Napas thừa."""
        df_napas = _napas_df(['M1', 'M1'])
        df_gw    = _gw_df(['M1'])
        df_khop, df_napas_thua, df_gw_thua = doi_chieu_napas_gw(df_napas, df_gw, 'MSGREF')
        assert len(df_khop) == 1
        assert len(df_napas_thua) == 1
        assert len(df_gw_thua) == 0

    def test_msgid_rong_lam_napas_thua_khong_bien_mat(self):
        """Regression 14.09.2026 — dòng Napas MsgId RỖNG ('' — dạng doc_napas_csv()
        trả về sau khi fillna('') từ NA thật) phải rơi vào Napas thừa, KHÔNG được
        biến mất khỏi cả 2 bên. Bug thật đã đo trên BEN 04.09 TRƯỚC khi thêm
        fillna(''): pandas groupby(dropna=True mặc định) bỏ hẳn nhóm có khoá NA,
        cumcount() của các dòng đó = NaN, so sánh 'NaN < 0' VÀ 'NaN >= 0' đều ra
        False → dòng biến mất khỏi CẢ df_khop LẪN df_napas_thua mà không có lỗi
        nào báo (đo được: mất đúng 2/569,337 dòng theo cách này)."""
        df_napas = _napas_df(['M1', ''])
        df_gw    = _gw_df(['M1'])
        df_khop, df_napas_thua, df_gw_thua = doi_chieu_napas_gw(df_napas, df_gw, 'MSGREF')
        assert len(df_khop) + len(df_napas_thua) == len(df_napas)
        assert list(df_napas_thua['MsgId']) == ['']
