"""Đọc file OSB (bảng 510202, "DỮ LIỆU CHI TIẾT HẠCH TOÁN" IPCAS) → DataFrame chuẩn.

Dùng để khớp nốt các dòng CITAD CÒN THỪA sau khi đã khớp Core (docx mục III —
"Những dòng còn lại tiếp tục map với file OSB ngày cũ và mới"). Khóa OSB =
LEFT(CN thực hiện,4) & Mã giao dịch & Số tiền — xác nhận bằng dữ liệu thật
2026-08-19 là so trực tiếp với cột 'Map dc' đã có sẵn của Citad (56/80 và
54/84 dòng OSB khớp đúng khóa này trên dữ liệu 11-12/8/2026).
"""

from pathlib import Path

import pandas as pd

from backend.services.ach.so_tien import doc_so_tien

from .config import (
    OSB_COL_CN_THUC_HIEN, OSB_COL_MA_GD, OSB_COL_NGAY_HACH_TOAN,
    OSB_COL_SO_TIEN, OSB_COLS_KEEP,
)

_SHEET_NAME = 'Sheet 1'
_HEADER_ROW = 2  # 0-based: title dòng 1, trống dòng 2, header dòng 3


def _ngay_int_to_str(ngay_int: int) -> str:
    return f'{ngay_int % 100:02d}/{(ngay_int // 100) % 100:02d}/{ngay_int // 10000}'


def _load_one(path: Path) -> pd.DataFrame:
    """
    Đọc 1 file OSB XLSX.
    - Row 1: title ("DỮ LIỆU CHI TIẾT HẠCH TOÁN") → bỏ qua
    - Row 2: trống
    - Row 3: header thực sự
    - Row 4+: dữ liệu
    """
    try:
        df = pd.read_excel(path, sheet_name=_SHEET_NAME, dtype=str, engine='calamine', header=_HEADER_ROW)
    except Exception:
        df = pd.read_excel(path, sheet_name=_SHEET_NAME, dtype=str, engine='openpyxl', header=_HEADER_ROW)
    df.columns = df.columns.str.strip()

    result = pd.DataFrame()
    for col in OSB_COLS_KEEP:
        result[col] = df[col].values if col in df.columns else pd.NA

    result = result[result[OSB_COL_MA_GD].notna()].copy()
    return result


def load_osb(paths: list[Path] | Path, ngay_ints: int | set[int] | None = None) -> pd.DataFrame:
    """
    Đọc 1 hoặc nhiều file OSB XLSX và ghép lại. Deduplicate theo Mã giao dịch.

    `ngay_ints`: nếu truyền (1 ngày hoặc tập nhiều ngày — dùng cho carryover
    "OSB cũ chưa đi"), chỉ giữ dòng có 'Ngày hạch toán' khớp. TÊN FILE OSB
    KHÔNG đáng tin để suy ngày — xác nhận thật: file "OSB n 11-12.7.xlsx"
    chứa dữ liệu ngày 11-12/08, không phải tháng 7 như tên gợi ý.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    if not paths:
        return pd.DataFrame(columns=OSB_COLS_KEEP)

    frames = [_load_one(p) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=[OSB_COL_MA_GD], keep='first')

    if ngay_ints is not None:
        if isinstance(ngay_ints, int):
            ngay_ints = {ngay_ints}
        valid_strs = {_ngay_int_to_str(n) for n in ngay_ints}
        df = df[df[OSB_COL_NGAY_HACH_TOAN].isin(valid_strs)].copy()

    return df.reset_index(drop=True)


def build_osb_key(df: pd.DataFrame) -> pd.Series:
    """Map key = LEFT(CN thực hiện,4) & Mã giao dịch & Số tiền."""
    if df.empty:
        return pd.Series(dtype=str)
    cn4 = df[OSB_COL_CN_THUC_HIEN].fillna('').astype(str).str[:4]
    ma_gd = df[OSB_COL_MA_GD].fillna('').astype(str).str.strip()
    so_tien = doc_so_tien(df[OSB_COL_SO_TIEN], nguon='OSB', ten_cot="'Số tiền'")
    return cn4 + ma_gd + so_tien.astype(str)


def label_moi_cu(df: pd.DataFrame, ngay_int: int) -> pd.Series:
    """'OSB mới' (đúng ngày đang chấm) hay 'OSB cũ' (carry từ ngày trước)."""
    if df.empty:
        return pd.Series(dtype=str)
    is_moi = df[OSB_COL_NGAY_HACH_TOAN] == _ngay_int_to_str(ngay_int)
    return is_moi.map({True: 'OSB mới', False: 'OSB cũ'})
