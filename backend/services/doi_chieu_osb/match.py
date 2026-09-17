"""So khớp GL02 <-> OSB bằng chiến lược min-count (đếm số lần trùng mỗi khoá, lấy min 2 bên) —
KHÔNG phải merge 1-1 (nhiều dòng có thể cùng khoá, VD nhiều giao dịch trùng cả trace lẫn số tiền).
"""
import numpy as np
import pandas as pd

__all__ = ["khop_min_count", "khop_case"]


def khop_min_count(khoa_nguon: pd.Series, khoa_dich: pd.Series) -> pd.Series:
    """Boolean mask (cùng index `khoa_nguon`) đánh dấu dòng khớp được với `khoa_dich`, dùng
    min(count) mỗi khoá — không phải merge 1-1.

    Cùng thuật toán với `doi_chieu_song_phuong_core/match.py::_khop_min_count()` (viết lại tại
    đây thay vì import thẳng vì đó là hàm riêng — tên có gạch dưới — của module khác; import
    xuyên module 1 hàm nội bộ tạo phụ thuộc ngầm dễ vỡ nếu module kia đổi tên/xoá hàm). Dùng
    `np.minimum(dem_nguon, dem_dich.reindex(...))` (vectorized) thay vì dict comprehension lặp
    Python qua từng khoá chung — xem skill `bank-reconciliation` phần "Vectorize... unique keys":
    ở quy mô thật, số khoá gần bằng số dòng, dict comprehension gần như 1 vòng lặp Python/dòng."""
    if len(khoa_nguon) == 0 or len(khoa_dich) == 0:
        return pd.Series(False, index=khoa_nguon.index)
    dem_nguon = khoa_nguon.value_counts()
    dem_dich = khoa_dich.value_counts()
    gioi_han = np.minimum(dem_nguon, dem_dich.reindex(dem_nguon.index, fill_value=0))
    cc = khoa_nguon.groupby(khoa_nguon).cumcount()
    han = khoa_nguon.map(gioi_han).fillna(0)
    return cc < han


def khop_case(gl02_df: pd.DataFrame, khoa_gl02_col: str,
              osb_df: pd.DataFrame, khoa_osb_col: str = "KHOA_C") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Trả `(gl02_chenh_lech, osb_chenh_lech)` — các dòng KHÔNG khớp được theo min-count."""
    if len(gl02_df) == 0 or len(osb_df) == 0:
        return gl02_df.copy(), osb_df.copy()
    matched_gl02 = khop_min_count(gl02_df[khoa_gl02_col], osb_df[khoa_osb_col])
    matched_osb = khop_min_count(osb_df[khoa_osb_col], gl02_df[khoa_gl02_col])
    return gl02_df[~matched_gl02].copy(), osb_df[~matched_osb].copy()
