"""Đọc file pHub XLSX → DataFrame chuẩn."""

from pathlib import Path

import pandas as pd

from .config import HUB_COLS_KEEP, HUB_COL_RENAME


def load_hub(path: Path) -> pd.DataFrame:
    """
    Đọc pHub XLSX.
    - Row 0: title ("DANH SÁCH GIAO DỊCH CHUYỂN TIỀN ĐI") → bỏ qua
    - Row 1: header thực sự
    - Row 2+: dữ liệu
    """
    # calamine đọc XLSX nhanh hơn openpyxl ~3-4x; fallback nếu chưa cài
    try:
        df = pd.read_excel(path, dtype=str, engine='calamine', header=1)
    except Exception:
        df = pd.read_excel(path, dtype=str, engine='openpyxl', header=1)
    df.columns = df.columns.str.strip()

    # Rename cột pHub → tên chuẩn pipeline
    df = df.rename(columns=HUB_COL_RENAME)

    # Giữ cột cần thiết, bổ sung cột thiếu bằng NaN
    result = pd.DataFrame()
    for col in HUB_COLS_KEEP:
        result[col] = df[col].values if col in df.columns else pd.NA

    return result.copy()
