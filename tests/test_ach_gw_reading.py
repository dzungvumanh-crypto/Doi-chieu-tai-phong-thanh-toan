"""
Test cho logic chọn sheet + loại trùng MSGREF khi đọc file GW — b3_xu_ly_gw.py.

Bối cảnh: file GW thật ngày 06-08/07/2026 có nhiều sheet, trong đó 1 sheet tổng hợp
("Sheet 1") gộp chung nhiều session và 1 sheet lọc riêng cho đúng ngày ("đi GW
<ngày>") chứa cùng dữ liệu — code cũ đọc gộp tất cả sheet khi tên file không trùng
tên sheet nào, khiến session cần đối chiếu bị đếm 2 lần (COUNT_GW gấp đôi thật, che
mất các nhóm CN_TIỀN thực sự thừa ở Requirement C.1). Xem Implementation-notes.html
mục 36-37.

Chạy: python -m pytest tests/test_ach_gw_reading.py -v
"""

import pandas as pd
import pytest

from backend.services.ach.b3_xu_ly_gw import (
    _chon_du_lieu_gw,
    _gop_gw_goc,
    _loai_trung_msgref,
    _phan_loai_sheet_theo_session,
)


def _sheet(session_ids, msgrefs=None, **extra_cols):
    """Tạo 1 sheet GW tối thiểu (đã có header sạch) với cột SessionId + MSGREF."""
    n = len(session_ids)
    msgrefs = msgrefs or [f'MSG{i}' for i in range(n)]
    data = {'SessionId': session_ids, 'MSGREF': msgrefs}
    for k, v in extra_cols.items():
        data[k] = v
    return pd.DataFrame(data)


# ── _phan_loai_sheet_theo_session ───────────────────────────────────────────

class TestPhanLoaiSheet:
    def test_thuan_nhat_khi_chi_1_session_khop(self):
        df = _sheet(['S1', 'S1', 'S1'])
        assert _phan_loai_sheet_theo_session(df, 'S1') == 'thuan_nhat'

    def test_lan_can_khi_lan_nhieu_session(self):
        df = _sheet(['S1', 'S2', 'S1', 'S3'])
        assert _phan_loai_sheet_theo_session(df, 'S1') == 'lan_can'

    def test_khong_lien_quan_khi_khong_co_session_muc_tieu(self):
        df = _sheet(['S2', 'S3'])
        assert _phan_loai_sheet_theo_session(df, 'S1') == 'khong_lien_quan'

    def test_khong_lien_quan_khi_thieu_cot_sessionid(self):
        df = pd.DataFrame({'MSGREF': ['a', 'b']})
        assert _phan_loai_sheet_theo_session(df, 'S1') == 'khong_lien_quan'


# ── _chon_du_lieu_gw — đúng kịch bản lỗi thật đã phát hiện ──────────────────

class TestChonDuLieuGw:
    def test_uu_tien_sheet_thuan_nhat_khong_doc_sheet_khac(self):
        """Mô phỏng đúng file GW thật 06.07: 'Sheet 1' gộp nhiều session, 'đi GW 06.07'
        chỉ đúng 1 session — phải chọn 'đi GW 06.07', KHÔNG được gộp cả 2 sheet."""
        sheet_tong_hop = _sheet(['S1', 'S2', 'S1', 'S3'], msgrefs=['M1', 'M2', 'M3', 'M4'])
        sheet_rieng_ngay = _sheet(['S1', 'S1'], msgrefs=['M1', 'M3'])
        logs = []
        ket_qua = _chon_du_lieu_gw(
            {'Sheet 1': sheet_tong_hop, 'đi GW 06.07': sheet_rieng_ngay},
            'S1', logs.append,
        )
        assert len(ket_qua) == 2
        assert set(ket_qua['MSGREF']) == {'M1', 'M3'}
        assert any('Sheet 1' not in log or 'đi GW 06.07' in log for log in logs)

    def test_khong_gap_doi_khi_2_sheet_trung_du_lieu(self):
        """Bất biến quan trọng nhất: dù workbook có sheet trùng lặp, kết quả cuối
        cùng KHÔNG được đếm 1 giao dịch quá 1 lần."""
        sheet_tong_hop = _sheet(['S1', 'S2'], msgrefs=['M1', 'M2'])
        sheet_rieng_ngay = _sheet(['S1'], msgrefs=['M1'])
        ket_qua = _chon_du_lieu_gw(
            {'Sheet 1': sheet_tong_hop, 'đi GW ngay': sheet_rieng_ngay},
            'S1', lambda *_: None,
        )
        assert len(ket_qua) == 1
        assert list(ket_qua['MSGREF']) == ['M1']

    def test_fallback_loc_va_dedup_khi_khong_co_sheet_thuan_nhat(self):
        """Không sheet nào thuần nhất (mọi sheet đều lẫn session khác) — phải lọc
        đúng session rồi loại trùng MSGREF."""
        sheet_a = _sheet(['S1', 'S2'], msgrefs=['M1', 'M2'])
        sheet_b = _sheet(['S1', 'S3'], msgrefs=['M1', 'M4'])  # M1 trùng voi sheet_a
        ket_qua = _chon_du_lieu_gw({'A': sheet_a, 'B': sheet_b}, 'S1', lambda *_: None)
        assert len(ket_qua) == 1
        assert list(ket_qua['MSGREF']) == ['M1']

    def test_tra_ve_rong_khi_khong_co_session_nao_khop(self):
        sheet_a = _sheet(['S2', 'S3'])
        ket_qua = _chon_du_lieu_gw({'A': sheet_a}, 'S1', lambda *_: None)
        assert len(ket_qua) == 0

    def test_nhieu_sheet_cung_thuan_nhat_van_dedup(self):
        """Trường hợp hiếm: 2 sheet khác nhau nhưng CẢ HAI đều thuần nhất đúng
        session (vd export lặp) — vẫn phải gộp + loại trùng, không được cộng dồn."""
        sheet_1 = _sheet(['S1', 'S1'], msgrefs=['M1', 'M2'])
        sheet_2 = _sheet(['S1', 'S1'], msgrefs=['M1', 'M2'])  # trung hoan toan
        ket_qua = _chon_du_lieu_gw({'X': sheet_1, 'Y': sheet_2}, 'S1', lambda *_: None)
        assert len(ket_qua) == 2
        assert set(ket_qua['MSGREF']) == {'M1', 'M2'}


# ── _gop_gw_goc — "GW gốc" cho BR mới xử lý SESSION=NULL (2026-07-23) ──────────

class TestGopGwGoc:
    """GW gốc = gộp TOÀN BỘ sheet, KHÔNG lọc session, KHÔNG dedup — chỉ dùng để tra
    SessionId theo MSGREF (xem b4_xu_ly_mis_di.py::_loc_session_null_theo_gw_goc)."""

    def test_gop_toan_bo_sheet_khong_loc_session(self):
        """Khác _chon_du_lieu_gw — GW gốc phải giữ CẢ session không liên quan."""
        sheet_a = _sheet(['S1', 'S2'], msgrefs=['M1', 'M2'])
        sheet_b = _sheet(['S3'], msgrefs=['M3'])
        ket_qua = _gop_gw_goc({'A': sheet_a, 'B': sheet_b})
        assert set(ket_qua['MSGREF']) == {'M1', 'M2', 'M3'}
        assert set(ket_qua['SessionId']) == {'S1', 'S2', 'S3'}

    def test_khong_dedup_du_trung_msgref_o_2_sheet(self):
        """Cố ý KHÔNG loại trùng — 1 MSGREF xuất hiện ở 2 sheet với SessionId khác
        nhau phải giữ CẢ 2 dòng (để `_xay_dung_tra_cuu_gw_goc` phát hiện được xung
        đột, không phải bị dedup mất trước khi tới đó)."""
        sheet_a = _sheet(['S1'], msgrefs=['M1'])
        sheet_b = _sheet(['S2'], msgrefs=['M1'])
        ket_qua = _gop_gw_goc({'A': sheet_a, 'B': sheet_b})
        assert len(ket_qua) == 2
        assert sorted(ket_qua['SessionId']) == ['S1', 'S2']

    def test_bo_qua_sheet_thieu_cot_msgref_hoac_sessionid(self):
        sheet_thieu = pd.DataFrame({'X': [1, 2]})
        sheet_du    = _sheet(['S1'], msgrefs=['M1'])
        ket_qua = _gop_gw_goc({'Thieu': sheet_thieu, 'Du': sheet_du})
        assert len(ket_qua) == 1
        assert list(ket_qua['MSGREF']) == ['M1']

    def test_rong_khi_khong_sheet_nao_hop_le(self):
        sheet_thieu = pd.DataFrame({'X': [1]})
        ket_qua = _gop_gw_goc({'A': sheet_thieu})
        assert len(ket_qua) == 0
        assert list(ket_qua.columns) == ['MSGREF', 'SessionId']


# ── _loai_trung_msgref ───────────────────────────────────────────────────────

class TestLoaiTrungMsgref:
    def test_loai_dung_dong_trung(self):
        df = pd.DataFrame({'MSGREF': ['a', 'b', 'a'], 'X': [1, 2, 3]})
        ket_qua = _loai_trung_msgref(df, lambda *_: None)
        assert len(ket_qua) == 2
        assert sorted(ket_qua['MSGREF']) == ['a', 'b']

    def test_khong_doi_khi_khong_trung(self):
        df = pd.DataFrame({'MSGREF': ['a', 'b', 'c']})
        ket_qua = _loai_trung_msgref(df, lambda *_: None)
        assert len(ket_qua) == 3

    def test_rong_khong_loi(self):
        df = pd.DataFrame({'MSGREF': []})
        ket_qua = _loai_trung_msgref(df, lambda *_: None)
        assert len(ket_qua) == 0
