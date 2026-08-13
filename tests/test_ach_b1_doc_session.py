"""Test `b1_doc_session.py::doc_session()` — audit 2026-08-04, cảnh báo khi có
≥2 file PDF ứng viên (trước đây chọn im lặng theo vị trí sort tên).

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_ach_b1_doc_session.py -v
"""
import pytest

from backend.services.ach.b1_doc_session import doc_session


def _tao_pdf(tmp_path, ten_file):
    (tmp_path / ten_file).write_bytes(b'%PDF-fake')


class TestDocSession:
    def test_doc_dung_session_tu_ten_file(self, tmp_path):
        _tao_pdf(tmp_path, 'ACH_20260612_VBAAVNVN_NRT_15882_N03_1.pdf')
        session_id = doc_session(str(tmp_path))
        assert session_id == '15882'

    def test_khong_co_pdf_bao_loi_ro(self, tmp_path):
        with pytest.raises(FileNotFoundError, match='Không tìm thấy file PDF'):
            doc_session(str(tmp_path))

    def test_ten_file_sai_dinh_dang_bao_loi_ro(self, tmp_path):
        _tao_pdf(tmp_path, 'khong_dung_dinh_dang.pdf')
        with pytest.raises(ValueError, match='Không thể lấy session'):
            doc_session(str(tmp_path))

    def test_nhieu_pdf_ung_vien_canh_bao_ro(self, tmp_path):
        """Trước đây: chọn PDF đầu tiên theo sort tên, KHÔNG cảnh báo gì — bug đã
        biết từ 2026-07-23 (case 16.7, 3 PDF do gửi lại). Giờ phải log WARN liệt
        kê đủ tên file ứng viên, dù vẫn giữ nguyên logic chọn cũ (chưa đổi)."""
        _tao_pdf(tmp_path, 'ACH_20260612_VBAAVNVN_NRT_15882_N03_1.pdf')
        _tao_pdf(tmp_path, 'ACH_20260612_VBAAVNVN_NRT_15999_N03_2.pdf')

        logs = []
        session_id = doc_session(str(tmp_path), log_callback=logs.append)

        canh_bao = [l for l in logs if '[B1][WARN]' in l]
        assert len(canh_bao) == 1
        assert 'ACH_20260612_VBAAVNVN_NRT_15882_N03_1.pdf' in canh_bao[0]
        assert 'ACH_20260612_VBAAVNVN_NRT_15999_N03_2.pdf' in canh_bao[0]
        # Vẫn chọn theo đúng logic cũ (sort tên) — chỉ thêm cảnh báo, không đổi hành vi.
        assert session_id == '15882'

    def test_1_pdf_khong_canh_bao(self, tmp_path):
        _tao_pdf(tmp_path, 'ACH_20260612_VBAAVNVN_NRT_15882_N03_1.pdf')
        logs = []
        doc_session(str(tmp_path), log_callback=logs.append)
        assert not any('[B1][WARN]' in l for l in logs)
