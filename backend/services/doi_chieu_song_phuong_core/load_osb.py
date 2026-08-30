"""Đọc file OSB (`osb {ma_nh}.xlsx`) — dữ liệu hạch toán chi tiết kênh OSB, dùng làm nguồn đối
chiếu cuối cùng cho các dòng HUB còn thừa sau khi so hết với CORE (Bước 2.6).

Cấu trúc thật (verify 21.8): 2 sheet — `Config` (bảng mã loại chi nhánh, không dùng) và
`Sheet 1` (dữ liệu thật, header nằm ở dòng thứ 3 → `header=2`).
"""

from pathlib import Path
from typing import BinaryIO

import pandas as pd

_REQUIRED_COLS = {"CN thực hiện", "Mã giao dịch", "Ngày hạch toán"}


def load_osb_file(source: str | Path | BinaryIO) -> pd.DataFrame:
    df = pd.read_excel(source, sheet_name="Sheet 1", dtype=str, header=2, engine="calamine")
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"File OSB thiếu cột bắt buộc: {', '.join(sorted(missing))}")
    return df


def find_osb_by_ma_dich_vu(input_dir: str | Path, ma_nh: str) -> Path | None:
    """Dò file OSB không đúng tên chuẩn `osb {ma_nh}.xlsx`/`osb den {ma_nh} {ngày}.xlsx` — dữ
    liệu thật ngày 26/8 xuất thẳng từ IPCAS tên `DULIEUCHITIETHACHTOAN_*.xlsx` (không mang mã NH
    trong tên file, nhưng đúng sheet `Sheet 1`/header dòng 3/tiêu đề "DỮ LIỆU CHI TIẾT HẠCH TOÁN"
    — cùng 1 nguồn OSB, người chấm xác nhận 2026-08-28 chưa được map do đổi tên).

    Định tuyến đúng ngân hàng qua cột `Mã dịch vụ` = `BPO{ma_nh}` — verify 100% đồng nhất trong
    1 file (26/8: 8.493/8.493 dòng NH 202, 12.308/12.308 dòng NH 203, không trộn lẫn 2 NH/file).
    Trả `None` nếu không có file `DULIEUCHITIETHACHTOAN*.xlsx` nào, hoặc không file nào khớp mã
    dịch vụ của `ma_nh`."""
    ma_dich_vu = f"BPO{ma_nh}"
    for f in Path(input_dir).glob("DULIEUCHITIETHACHTOAN*.xlsx"):
        try:
            mau = pd.read_excel(
                f, sheet_name="Sheet 1", dtype=str, header=2,
                usecols=["Mã dịch vụ"], nrows=20, engine="calamine",
            )
        except (ValueError, KeyError):
            continue
        if set(mau["Mã dịch vụ"].dropna().unique()) == {ma_dich_vu}:
            return f
    return None


def build_key_osb(df: pd.DataFrame) -> pd.Series:
    """Khoá = 4 ký tự đầu `CN thực hiện` + `Mã giao dịch` — verify dữ liệu thật 21.8 (NH 202):
    khớp RAW 100% (8.117/8.117) với `CHI_NHANH+TRACE` hub, KHÔNG cần lstrip('0') (khác khoá
    core↔hub)."""
    cn4 = df["CN thực hiện"].fillna("").str[:4]
    ma_gd = df["Mã giao dịch"].fillna("")
    return cn4 + ma_gd


def build_key_hub_osb(hub_df: pd.DataFrame) -> pd.Series:
    """Khoá HUB dùng riêng để đối chiếu với OSB (Bước 2.6): `CHI_NHANH + TRACE` nguyên bản,
    KHÔNG lstrip('0'), KHÔNG kèm số tiền — khác hẳn `build_key_hub_core` (dùng cho khớp CORE,
    có lstrip('0') + kèm SO_TIEN). Verify dữ liệu thật: khớp raw 100% (8.117/8.117, NH 202 21.8)."""
    return hub_df["CHI_NHANH"].astype(str).str.strip() + hub_df["TRACE"].fillna("").str.strip()
