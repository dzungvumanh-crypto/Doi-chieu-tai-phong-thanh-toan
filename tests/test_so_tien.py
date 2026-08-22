"""Test backend/services/ach/so_tien.py — đọc cột số tiền định dạng VN an toàn."""

import pandas as pd
import pytest

from backend.services.ach.so_tien import doc_so_tien, doc_so_tien_mem


# ── doc_so_tien() — raise cứng khi gặp mẫu lạ ───────────────────────────────

class TestDocSoTien:
    def test_plain_integer_parsed_correctly(self):
        out = doc_so_tien(pd.Series(['1000000']), nguon='TEST')
        assert list(out) == [1_000_000]

    def test_dot_grouped_parsed_correctly_not_truncated(self):
        """Bẫy đã xảy ra thật: '180.000' bị to_numeric() trần hiểu thành 180."""
        out = doc_so_tien(pd.Series(['180.000']), nguon='TEST')
        assert list(out) == [180_000]

    def test_comma_grouped_parsed_correctly(self):
        """Case thật 2026-08-21: MIS_DI_THUA_20260819.csv có 3 dòng dùng dấu phẩy
        ngăn nghìn ('839,000', '122,568,332'). Business Owner xác nhận VND luôn là
        số nguyên nên dấu phẩy an toàn để coi là ngăn nghìn giống dấu chấm."""
        out = doc_so_tien(pd.Series(['839,000', '122,568,332']), nguon='TEST')
        assert list(out) == [839_000, 122_568_332]

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match='không đúng định dạng'):
            doc_so_tien(pd.Series(['1.5']), nguon='TEST')


# ── doc_so_tien_mem() — biến thể không raise, dùng cho cột khóa đối chiếu ───

class TestDocSoTienMem:
    def test_parses_plain_and_dot_grouped_correctly(self):
        out = doc_so_tien_mem(pd.Series(['1000000', '180.000']), nguon='TEST', ten_cot='X')
        assert list(out) == [1_000_000, 180_000], "'180.000' phải ra 180000, không phải 180"

    def test_negative_values_parsed_correctly(self):
        out = doc_so_tien_mem(pd.Series(['-500000', '-2.500.000']), nguon='TEST', ten_cot='X')
        assert list(out) == [-500_000, -2_500_000]

    def test_comma_grouped_parsed_correctly(self):
        out = doc_so_tien_mem(pd.Series(['1000000', '839,000', '-2,500,000']), nguon='TEST', ten_cot='X')
        assert list(out) == [1_000_000, 839_000, -2_500_000]

    def test_invalid_format_defaults_to_zero_not_raise(self):
        out = doc_so_tien_mem(pd.Series(['1.5', 'abc']), nguon='TEST', ten_cot='X')
        assert list(out) == [0, 0]

    def test_logs_warning_on_invalid_format(self):
        logs = []
        doc_so_tien_mem(pd.Series(['abc']), nguon='CITAD', ten_cot='AMOUNT', log=logs.append)
        warn = [l for l in logs if '[WARN]' in l]
        assert warn, "Phải log cảnh báo khi có giá trị không đúng định dạng"
        assert 'AMOUNT' in warn[0] and 'CITAD' in warn[0] and 'abc' in warn[0]

    def test_no_log_when_all_valid(self):
        logs = []
        doc_so_tien_mem(pd.Series(['1000', '2.000']), nguon='TEST', ten_cot='X', log=logs.append)
        assert logs == []

    def test_preserves_row_count_and_order(self):
        out = doc_so_tien_mem(pd.Series(['100', 'abc', '2.000', '3.5']), nguon='TEST', ten_cot='X')
        assert list(out) == [100, 0, 2_000, 0]

    def test_int64_dtype(self):
        out = doc_so_tien_mem(pd.Series(['1000']), nguon='TEST', ten_cot='X')
        assert out.dtype == 'int64'
