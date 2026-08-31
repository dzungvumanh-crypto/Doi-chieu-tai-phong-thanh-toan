"""Test backend/services/ach/so_tien.py — đọc cột số tiền định dạng VN an toàn."""

import numpy as np
import pandas as pd
import pytest

from backend.services.ach.so_tien import LoiDinhDangSoTien, doc_so_tien


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

    def test_float64_dtype_whole_numbers_parsed_correctly(self):
        """Bug thực nghiệm 2026-08-27: cột dtype float64 do pandas tự nâng kiểu
        (NaN xen kẽ, đọc từ Excel) khiến '1000000.0' bị coi là mẫu lạ và raise sai."""
        out = doc_so_tien(pd.Series([1000000.0, 2000000.0]), nguon='TEST')
        assert list(out) == [1_000_000, 2_000_000]

    def test_float64_negative_whole_number_parsed_correctly(self):
        out = doc_so_tien(pd.Series([-500000.0]), nguon='TEST')
        assert list(out) == [-500_000]

    def test_float64_with_nonzero_fraction_still_raises(self):
        """Không được làm yếu khả năng bắt lỗi — phần thập phân khác 0 vẫn phải raise."""
        with pytest.raises(ValueError, match='không đúng định dạng'):
            doc_so_tien(pd.Series([1000000.5]), nguon='TEST')

    def test_two_decimal_zero_string_parsed_correctly(self):
        """Review PR#69: Excel/CSV xuất số tiền có 2 số lẻ ('0.00', '150000.00')
        trước đây bị raise oan — chỉ mỗi đuôi 1 chữ số '.0' được bỏ."""
        out = doc_so_tien(pd.Series(['0.00', '150000.00']), nguon='TEST')
        assert list(out) == [0, 150_000]

    def test_two_decimal_nonzero_still_raises(self):
        with pytest.raises(ValueError, match='không đúng định dạng'):
            doc_so_tien(pd.Series(['150000.50']), nguon='TEST')

    def test_three_zero_group_stays_ngan_nghin_not_stripped_as_decimal(self):
        """Ranh giới quan trọng nhất: '180.000' PHẢI ra 180000 (ngăn nghìn),
        KHÔNG được hiểu nhầm thành '180.0' rồi cắt còn 180 — đây chính là lỗi
        '1000 lần' mà module tồn tại để chặn. Regex bỏ đuôi thập phân chỉ được
        khớp 1-2 số 0, không bao giờ được khớp đúng 3 số 0."""
        out = doc_so_tien(pd.Series(['180.000']), nguon='TEST')
        assert list(out) == [180_000]

    def test_int64_dtype_unaffected(self):
        out = doc_so_tien(pd.Series([1000000], dtype='int64'), nguon='TEST')
        assert list(out) == [1_000_000]

    def test_raises_LoiDinhDangSoTien_a_ValueError_subclass(self):
        """Cho phép caller phân biệt (ach_service.py B2) mà không phá vỡ
        `except ValueError` cũ ở nơi khác — LoiDinhDangSoTien PHẢI là ValueError."""
        with pytest.raises(LoiDinhDangSoTien):
            doc_so_tien(pd.Series(['1.5']), nguon='TEST')


# ── Ô trống/NaN = chưa hạch toán → 0, KHÔNG raise ────────────────────────────
# Review PR#66 (khanhbq693) A1: trước module này, to_numeric(errors='coerce')
# .fillna(0) coi ô trống là 0. `astype(str)` biến ô trống/NaN thành 'nan'/''
# không khớp regex nào — phải chặn tường minh, không để rơi vào nhánh raise.

class TestDocSoTienOTrong:
    def test_empty_string_cell_treated_as_zero(self):
        """GL02 sổ cái: dòng ghi Có thường bỏ trống cột Nợ (DRAMOUNT='')."""
        out = doc_so_tien(pd.Series(['150000', '']), nguon='GL02', ten_cot='DRAMOUNT')
        assert list(out) == [150_000, 0]

    def test_nan_cell_treated_as_zero(self):
        """Excel/CSV đọc dtype=str vẫn cho NaN thật (không phải chuỗi 'NaN')
        khi ô trống hẳn — pandas biến thành float('nan')."""
        out = doc_so_tien(pd.Series(['150000', np.nan]), nguon='GW', ten_cot='STTLMAMT')
        assert list(out) == [150_000, 0]

    def test_all_cells_empty_treated_as_zero(self):
        out = doc_so_tien(pd.Series(['', np.nan]), nguon='TEST', ten_cot='X')
        assert list(out) == [0, 0]

    def test_none_python_object_treated_as_zero(self):
        out = doc_so_tien(pd.Series(['150000', None]), nguon='TEST', ten_cot='X')
        assert list(out) == [150_000, 0]

    def test_empty_cell_does_not_suppress_real_invalid_format(self):
        """Ô trống được tha, nhưng mẫu lạ thật sự bên cạnh vẫn phải raise."""
        with pytest.raises(LoiDinhDangSoTien, match='không đúng định dạng'):
            doc_so_tien(pd.Series(['', 'abc']), nguon='TEST', ten_cot='X')

    def test_pandas_na_dtype_string_treated_as_zero(self):
        """Review PR#66 (khanhbq693) mục 2: pd.NA (dtype 'string' nullable, khác
        object dtype) sau astype(str) ra '' — không nằm trong _O_TRONG bằng
        chuỗi, nhưng trong_nan = sr.isna() bắt được TRƯỚC khi ép chuỗi nên vẫn
        an toàn. Test này khoá hành vi, không để ai dọn nhầm trong_nan vì
        tưởng thừa (chỉ thấy _O_TRONG cũng đủ nếu test bằng dtype object)."""
        out = doc_so_tien(
            pd.Series(['150000', pd.NA], dtype='string'), nguon='TEST', ten_cot='X',
        )
        assert list(out) == [150_000, 0]

    def test_dash_cell_still_raises_not_treated_as_zero(self):
        """Review PR#66 mục 3, Business Owner xác nhận 2026-08-31: dấu '-' là
        bút toán đảo/huỷ/điều chỉnh — có ý nghĩa nghiệp vụ thật, KHÔNG phải ô
        trống/0. Coi ngầm là 0 sẽ làm biến mất một giao dịch thật khỏi khoá đối
        chiếu. PHẢI raise để lộ ra, không được lặng lẽ nuốt vào _O_TRONG."""
        with pytest.raises(LoiDinhDangSoTien, match='không đúng định dạng'):
            doc_so_tien(pd.Series(['150000', '-']), nguon='TEST', ten_cot='X')

    def test_pandas_nat_treated_as_zero(self):
        """NaT (Not-a-Time, dtype datetime lẫn vào cột tưởng toàn số) ra chuỗi
        'NaT' sau astype(str) — không khớp _O_TRONG bằng chuỗi, chỉ trong_nan
        (sr.isna()) bắt được vì NaT cũng là missing value của pandas."""
        out = doc_so_tien(
            pd.Series(['150000', pd.NaT]), nguon='TEST', ten_cot='X',
        )
        assert list(out) == [150_000, 0]
