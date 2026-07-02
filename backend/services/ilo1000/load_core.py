"""Đọc file GL02 (CSV hoặc ZIP chứa nhiều CSV) → DataFrame, filter DRAMOUNT=0."""

import zipfile
from pathlib import Path

import pandas as pd

from .config import CORE_HEADER


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


def _from_zip(path: Path) -> pd.DataFrame:
    frames = []
    with zipfile.ZipFile(path, 'r') as zf:
        for name in zf.namelist():
            if name.lower().endswith('.csv'):
                data = zf.read(name)
                frames.append(_read_csv_bytes(data))
    if not frames:
        return pd.DataFrame(columns=CORE_HEADER)
    return pd.concat(frames, ignore_index=True)


def load_core(paths: list[Path]) -> pd.DataFrame:
    """
    Đọc GL02 từ danh sách path (CSV và/hoặc ZIP).
    Trả DataFrame đã filter DRAMOUNT = 0.
    """
    frames = []
    for p in paths:
        if p.suffix.lower() == '.zip':
            frames.append(_from_zip(p))
        else:
            frames.append(_read_csv_path(p))

    if not frames:
        return pd.DataFrame(columns=CORE_HEADER)

    df = pd.concat(frames, ignore_index=True)
    df.columns = df.columns.str.strip()

    # Chuẩn hóa DRAMOUNT về số, filter DRAMOUNT = 0
    if 'DRAMOUNT' in df.columns:
        df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0)
        df = df[df['DRAMOUNT'] == 0].copy()

    return df.reset_index(drop=True)
