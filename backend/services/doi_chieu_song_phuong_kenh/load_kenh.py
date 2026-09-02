"""Đọc dữ liệu kênh song phương (Excel do ngân hàng đối tác gửi).

Dùng `engine='calamine'` (đã có sẵn trong `requirements.txt`, quy ước chuẩn của dự án ở
ach/ilo1000/459901) — KHÔNG dùng `openpyxl` trực tiếp. File nguồn có lỗi thẻ `<dimension>`
khiến `openpyxl.load_workbook(read_only=True)` đọc sai/mất dữ liệu âm thầm; `calamine` đọc
đúng và nhanh hơn nhiều (đã verify: 372.538 dòng trong 5,6s).
"""

import re
import unicodedata
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .config import KENH_COLS, KENH_KEY_COL, KENH_MTID_PREFIX


def kenh_filename(ma_nh: str, loai: str) -> str:
    """VD `kenh_filename('202', 'SPRT')` -> `kênh đến SPRT 202.xlsx` (tên chuẩn, dữ liệu 21-23.8) —
    dùng để hiển thị trong thông báo lỗi, KHÔNG dùng để tìm file (xem `find_kenh_path`)."""
    return f"kênh đến {loai} {ma_nh}.xlsx"


def _chuan_hoa_ten_file(s: str) -> str:
    """Bỏ dấu tiếng Việt + hạ chữ thường, để so khớp tên file không phân biệt dấu/hoa-thường."""
    s = s.lower().replace("đ", "d")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _tu_khoa_ten_file(filename: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _chuan_hoa_ten_file(filename)))


def find_kenh_path(input_dir: str | Path, ma_nh: str, loai: str) -> Path | None:
    """Tìm file kênh trong thư mục bằng so khớp TỪ KHOÁ trong tên file (không phân biệt dấu/hoa-
    thường/thứ tự) — cần đủ 3 từ khoá `kenh`, mã ngân hàng, loại (`sprt`/`spt`).

    Dữ liệu thật đã xuất hiện ≥3 quy ước đặt tên khác nhau cho cùng 1 loại file (`kênh đến SPRT
    202.xlsx`, `kênh đến 202 SPRT.xlsx`, `kenh SPRT den 201 24.8.xlsx` — không dấu, có kèm ngày)
    — so khớp theo tập từ khoá để không phải thêm 1 hàm biến thể mỗi lần nguồn đổi cách đặt tên.
    Trả `None` nếu không thấy."""
    input_dir = Path(input_dir)
    can_co = {"kenh", ma_nh.lower(), loai.lower()}
    for f in input_dir.glob("*.xlsx"):
        if can_co <= _tu_khoa_ten_file(f.name):
            return f
    return None


def load_kenh_file(source: str | Path | BinaryIO, ma_nh: str, loai: str) -> pd.DataFrame:
    """Đọc 1 file Excel kênh, trả DataFrame dtype=str với đủ `KENH_COLS`.

    Với SPRT: guard-validate 100% `MtId/MsgId` đúng prefix ngân hàng `ma_nh` (xem
    `KENH_MTID_PREFIX`, nguồn lyxink.txt — Business Owner 2026-08-25) — bắt lỗi file
    bị đặt/copy nhầm ngân hàng sớm và rõ ràng, thay vì chỉ thấy tỉ lệ khớp sụt bất
    thường. Không áp dụng cho SPT (chưa có bằng chứng prefix theo NH).
    """
    df = pd.read_excel(source, dtype=str, engine="calamine")
    missing = set(KENH_COLS) - set(df.columns)
    if missing:
        raise ValueError(f"File kênh thiếu cột bắt buộc: {', '.join(sorted(missing))}")

    if loai == "SPRT" and ma_nh in KENH_MTID_PREFIX:
        expected = KENH_MTID_PREFIX[ma_nh]
        mask_sai = df[KENH_KEY_COL].str[:10] != expected
        n_sai = int(mask_sai.sum())
        if n_sai:
            mau = df.loc[mask_sai, KENH_KEY_COL].head(5).tolist()
            raise ValueError(
                f"File kênh SPRT khai báo NH {ma_nh} nhưng có {n_sai} dòng MtId/MsgId "
                f"không đúng prefix '{expected}' — mẫu: {mau}"
            )
    return df
