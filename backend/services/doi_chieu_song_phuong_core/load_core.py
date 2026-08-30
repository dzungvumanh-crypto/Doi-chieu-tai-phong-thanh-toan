"""Đọc & tiền xử lý dữ liệu CORE — output `{ma_nh}_DEN.csv` của
`doi_chieu_song_phuong_service.process_zip()` (module phân loại IPCAS đã có sẵn, không sửa).
"""

from pathlib import Path

import pandas as pd

from backend.services.ach.so_tien import doc_so_tien

from .config import (
    CORE_REQUIRED_COLS, PREFIX_TRACE_CORE, QT_VON_REMARK_KEYWORD, QT_VON_TRBRCD,
    REFERENCE_QT_OSB,
)


def load_core_den_csv(path: str | Path) -> pd.DataFrame:
    """Đọc 1 file `{ma_nh}_DEN.csv` (đã phân loại sẵn, luôn CRAMOUNT ∈ ZERO_AMOUNTS)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = CORE_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"File core thiếu cột bắt buộc: {', '.join(sorted(missing))}")
    return df


def build_so_trace(df: pd.DataFrame) -> pd.Series:
    """Bước 1.2: bỏ tiền tố `1000API` khỏi REFERENCE, giữ phần còn lại, bỏ số 0 đầu (verify dữ
    liệu thật — xem `config.py`). Dòng REFERENCE không có tiền tố này → chuỗi rỗng (không tính
    được SO_TRACE, sẽ không khớp khoá nào — đúng ý, vì đó là loại giao dịch khác, VD `1000OSB`)."""
    ref = df["REFERENCE"].fillna("")
    mask = ref.str.startswith(PREFIX_TRACE_CORE)
    so_trace = pd.Series("", index=df.index)
    so_trace.loc[mask] = ref.loc[mask].str[len(PREFIX_TRACE_CORE):].str.lstrip("0")
    return so_trace


def build_key_den(df: pd.DataFrame, so_trace: pd.Series) -> pd.Series:
    """Bước 1.4: KEY = TRBRCD + SO_TRACE + DRAMOUNT."""
    dramount = doc_so_tien(df["DRAMOUNT"], nguon="core", ten_cot="DRAMOUNT")
    return df["TRBRCD"].astype(str).str.strip() + so_trace + dramount.astype(str)


def mask_huy_cung_ngay(df: pd.DataFrame) -> pd.Series:
    """Bước 1.3: nhóm TRBRCD+REFERENCE trùng ≥2 dòng, tổng DRAMOUNT = 0 (tập DEN, CRAMOUNT luôn
    ∈ ZERO_AMOUNTS nên chỉ cần xét DRAMOUNT) → giao dịch huỷ cùng ngày. Trả boolean mask."""
    dramount = doc_so_tien(df["DRAMOUNT"], nguon="core", ten_cot="DRAMOUNT")
    khoa = df["TRBRCD"].astype(str).str.strip() + "\x00" + df["REFERENCE"].astype(str)
    tong = khoa.map(dramount.groupby(khoa).sum())
    dem = khoa.map(khoa.value_counts())
    return (dem >= 2) & (tong == 0)


def mask_qt_osb(df: pd.DataFrame) -> pd.Series:
    """Bước 1.8 — điện quyết toán OSB hàng ngày."""
    return df["REFERENCE"].fillna("") == REFERENCE_QT_OSB


def mask_qt_von(df: pd.DataFrame) -> pd.Series:
    """Bước 1.9 — quyết toán vốn."""
    trbrcd_ok = df["TRBRCD"].astype(str).str.strip() == QT_VON_TRBRCD
    remark_ok = df["REMARK"].fillna("").str.lower().str.contains(QT_VON_REMARK_KEYWORD, regex=False)
    return trbrcd_ok & remark_ok
