"""Đọc pool tồn đọng xuyên batch (Core thừa / OSB thừa).

Xem `process.py` phần "Pool tồn đọng xuyên batch" để hiểu cơ chế nghiệp vụ,
và `detect.py::_sniff_pool_xlsx()` để hiểu cách nhận dạng file này (theo NỘI
DUNG — có cột 'Đối chiếu' — không theo tên file).
"""

from pathlib import Path

import pandas as pd

from .detect import find_pool_header_row

# Chuẩn hóa tên cột — file pool do người chấm tự dựng bằng tay, casing/khoảng
# trắng có thể lệch so với quy ước code (xác nhận thật: "Core thừa 5-8.9.xlsx"
# dùng "map dc" chữ thường, trong khi mọi nơi khác của pipeline dùng "Map dc").
_CANONICAL_COLS = {
    'map dc':      'Map dc',
    'ngay':        'Ngày',
    'ngày':        'Ngày',
    'tt':          'TT',
    'đối chiếu':   'Đối chiếu',
    'doi chieu':   'Đối chiếu',
    # Xác nhận thật 2026-09-15: người chấm tự đổi tên cột này thành "Cham"
    # khi chỉnh sửa lại file — xem detect.py::_DOI_CHIEU_MARKER_ALIASES
    # (cùng danh sách alias, dùng ở bước NHẬN DẠNG loại file; ở đây dùng để
    # CHUẨN HOÁ tên cột sau khi đã đọc, cho các hàm downstream luôn thấy
    # đúng 1 tên 'Đối chiếu').
    'cham':        'Đối chiếu',
    'chấm':        'Đối chiếu',
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        canonical = _CANONICAL_COLS.get(key)
        if canonical and col != canonical:
            rename[col] = canonical
    return df.rename(columns=rename) if rename else df


def _load_one_pool(path: Path) -> pd.DataFrame:
    header_row = find_pool_header_row(path)
    if header_row is None:
        return pd.DataFrame()
    # keep_default_na=False: pandas mặc định tự đổi chuỗi "#N/A" (và các biến
    # thể NA khác) thành NaN khi đọc — pool này dùng LITERAL "#N/A" làm giá trị
    # nghiệp vụ ("chưa khớp"), không phải ô trống, nên phải giữ nguyên chuỗi.
    read_kwargs = dict(sheet_name=0, header=header_row, dtype=str, keep_default_na=False, na_values=[])
    try:
        df = pd.read_excel(path, engine='calamine', **read_kwargs)
    except Exception:
        df = pd.read_excel(path, engine='openpyxl', **read_kwargs)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.startswith('Unnamed:')]
    return _normalize_columns(df)


def load_pool_files(paths: 'list[Path] | Path') -> pd.DataFrame:
    """
    Đọc 1 hoặc nhiều file pool tồn đọng (Core thừa HOẶC OSB thừa — cùng cơ
    chế đọc/nhận header, khác nhau ở tập cột thực tế bên trong nên không tách
    2 hàm riêng). Giữ TOÀN BỘ cột gốc (đã có sẵn Trace/Map dc/TT/Đối chiếu từ
    lần chấm trước) — không lọc cột như các loader dữ liệu THÔ khác
    (Hub/Citad/OSB).

    `dtype=str` cho MỌI cột — pool có thể chứa cột số tiền/mã tham chiếu,
    ép kiểu ngay từ lúc đọc để tránh pandas/calamine tự nâng float64 làm mất
    số 0 đầu (cùng nguyên tắc `doc_so_tien()`/các loader khác trong module).
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    if not paths:
        return pd.DataFrame()

    frames = [_load_one_pool(p) for p in paths]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
