"""Đọc file pHub XLSX → DataFrame chuẩn."""

from pathlib import Path

import pandas as pd

from .config import HUB_COLS_KEEP, HUB_COL_NGAY_GIO, HUB_COL_RENAME, HUB_COL_SO_GD


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


def load_hub(paths: list[Path] | Path, ngay_ints: int | set[int] | None = None) -> pd.DataFrame:
    """
    Đọc 1 hoặc nhiều file pHub XLSX và ghép lại (có thể export theo nhiều đợt/batch).
    Deduplicate theo Số giao dịch — phòng trường hợp cùng 1 giao dịch xuất hiện ở nhiều file.

    `ngay_ints`: nếu truyền (1 ngày hoặc tập nhiều ngày — dùng cho carryover
    "chờ đi kênh" T + T-1), chỉ giữ dòng có 'Ngày giờ kênh trả' khớp. TÊN FILE
    pHub KHÔNG đáng tin để suy ngày — xác nhận thật 2026-08-19: 5 file pHub
    cùng tên ngày xuất 13/08 nhưng bên trong trộn lẫn dữ liệu 4 ngày khác nhau
    (10-13/08). Lọc theo NGÀY ĐẦY ĐỦ (năm-tháng-ngày), không chỉ số ngày trong
    tháng như cờ "Chờ đi kênh" trong process_hub() đang dùng.
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    frames = [_load_one(p) for p in paths]
    if not frames:
        return pd.DataFrame(columns=HUB_COLS_KEEP)
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=[HUB_COL_SO_GD], keep='first')

    if ngay_ints is not None:
        if isinstance(ngay_ints, int):
            ngay_ints = {ngay_ints}
        parsed = pd.to_datetime(df[HUB_COL_NGAY_GIO], dayfirst=True, errors='coerce')
        ngay_full = parsed.dt.year * 10000 + parsed.dt.month * 100 + parsed.dt.day
        df = df[ngay_full.isin(ngay_ints)].copy()

    return df.reset_index(drop=True)
