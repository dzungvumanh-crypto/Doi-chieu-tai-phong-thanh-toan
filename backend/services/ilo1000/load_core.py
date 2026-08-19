"""Đọc file GL02 (CSV hoặc ZIP chứa nhiều CSV) → DataFrame, filter DRAMOUNT=0."""

import zipfile
from pathlib import Path

import pandas as pd

from .config import CORE_FILTER_CUSTOMER, CORE_FILTER_LOCAC, CORE_HEADER, ZIP_PASSWORD

try:
    import pyzipper
    _ZipFile = pyzipper.AESZipFile
except ImportError:
    _ZipFile = zipfile.ZipFile  # fallback nếu pyzipper chưa cài


def _detect_encoding(sample: bytes) -> str:
    if sample[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    try:
        sample.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'cp1252'


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    enc = _detect_encoding(data[:512])
    import io
    df = pd.read_csv(
        io.BytesIO(data),
        encoding=enc,
        dtype=str,
        low_memory=False,
        on_bad_lines='skip',
    )
    df.columns = df.columns.str.strip()
    return df


def _read_csv_path(path: Path) -> pd.DataFrame:
    with path.open('rb') as f:
        data = f.read()
    return _read_csv_bytes(data)


def _filter_channel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Chỉ giữ bút toán kênh Citad Thấp/ILO1000 — GL02 chi nhánh 1000 gồm mọi kênh
    (~98% dữ liệu không liên quan ILO1000). PHẢI lọc ngay từng file/part, TRƯỚC
    khi gộp: nồng dồn hết rồi mới lọc (cách cũ) gây MemoryError khi 1 batch có
    nhiều file/part GL02 lớn — xác nhận qua dữ liệu thật 14-15/7/2026 (9
    file/part, gộp thô ~9,5 triệu dòng vượt RAM máy thường).
    """
    if 'LOCAC' in df.columns and 'CUSTOMER' in df.columns:
        df = df[
            (df['LOCAC'].astype(str).str.strip() == CORE_FILTER_LOCAC) &
            (df['CUSTOMER'].astype(str).str.strip() == CORE_FILTER_CUSTOMER)
        ]
    return df.copy()


def _from_zip(path: Path, log=None) -> pd.DataFrame:
    frames = []
    try:
        with _ZipFile(path, 'r') as zf:
            for name in zf.namelist():
                if not name.lower().endswith('.csv'):
                    continue
                try:
                    data = zf.read(name, pwd=ZIP_PASSWORD)
                except RuntimeError as e:
                    # Sai mật khẩu hoặc entry mã hóa kiểu khác — bỏ qua
                    if log:
                        log(f'  [WARN] ZIP entry mã hóa, bỏ qua: {name} ({e})')
                    continue
                frames.append(_filter_channel(_read_csv_bytes(data)))
    except zipfile.BadZipFile as e:
        if log:
            log(f'  [WARN] File ZIP không hợp lệ, bỏ qua: {path.name} ({e})')
    if not frames:
        return pd.DataFrame(columns=CORE_HEADER)
    return pd.concat(frames, ignore_index=True)


def load_core(paths: list[Path], log=None) -> pd.DataFrame:
    """
    Đọc GL02 từ danh sách path (CSV và/hoặc ZIP).
    Trả DataFrame đã filter DRAMOUNT = 0.
    """
    frames = []
    for p in paths:
        if p.suffix.lower() == '.zip':
            frames.append(_from_zip(p, log=log))
        else:
            frames.append(_filter_channel(_read_csv_path(p)))

    if not frames:
        return pd.DataFrame(columns=CORE_HEADER)

    df = pd.concat(frames, ignore_index=True)
    df.columns = df.columns.str.strip()

    # ZIP và CSV rời có thể chứa cùng 1 phần dữ liệu (CSV rời là bản export tay
    # trùng 1 phần của ZIP) — dedup dòng giống hệt nhau trước khi xử lý tiếp.
    df = df.drop_duplicates().reset_index(drop=True)

    # Chuẩn hóa DRAMOUNT về số, filter DRAMOUNT = 0
    if 'DRAMOUNT' in df.columns:
        df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0)
        df = df[df['DRAMOUNT'] == 0].copy()

    return df.reset_index(drop=True)
