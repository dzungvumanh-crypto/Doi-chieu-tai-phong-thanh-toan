"""Đọc file pHub XLSX → DataFrame chuẩn."""

from pathlib import Path

import pandas as pd

from .config import HUB_COLS_KEEP, HUB_COL_RENAME, HUB_COL_SO_GD


def _load_one(path: Path) -> pd.DataFrame:
    """
    Đọc 1 file pHub XLSX.
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

    # Dòng "Tổng tiền" cuối file pHub (Excel tự thêm) không phải giao dịch —
    # STT="Tổng tiền", mọi cột giao dịch (kể cả Số giao dịch) đều rỗng, chỉ có
    # "Số tiền thực chuyển" = tổng cộng cả file → nếu không loại sẽ cộng dồn
    # sai vào tổng Hub (xác nhận qua dữ liệu thật: lệch đúng bằng giá trị dòng
    # tổng, 561.304.218.679 và 557.634.971.560 ở 2 file 04-06/7/2026).
    result = result[result[HUB_COL_SO_GD].notna()].copy()

    return result


def load_hub(paths: list[Path] | Path) -> pd.DataFrame:
    """
    Đọc 1 hoặc nhiều file pHub XLSX cùng ngày và ghép lại (có thể export theo nhiều đợt/batch).
    Deduplicate theo Số giao dịch — phòng trường hợp cùng 1 giao dịch xuất hiện ở nhiều file.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    frames = [_load_one(p) for p in paths]
    if not frames:
        return pd.DataFrame(columns=HUB_COLS_KEEP)
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=[HUB_COL_SO_GD], keep='first')
    return df.reset_index(drop=True)
