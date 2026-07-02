"""Đọc các file CITAD (UUID CSV) và concat thành 1 DataFrame."""

from pathlib import Path

import pandas as pd

from .config import CITAD_COLS_KEEP


def _detect_encoding(path: Path) -> str:
    with path.open('rb') as f:
        header = f.read(512)
    if header[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    try:
        header.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'cp1252'


def _load_one(path: Path) -> pd.DataFrame:
    enc = _detect_encoding(path)
    df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False, on_bad_lines='skip')
    df.columns = df.columns.str.strip()
    # Giữ cột cần thiết
    cols = [c for c in CITAD_COLS_KEEP if c in df.columns]
    return df[cols].copy()


def load_citad(paths: list[Path]) -> pd.DataFrame:
    """Đọc nhiều file CITAD CSV và ghép lại."""
    if not paths:
        return pd.DataFrame(columns=CITAD_COLS_KEEP)
    frames = [_load_one(p) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    # Deduplicate theo SERIAL_NO (cổng khác nhau có thể trùng)
    df = df.drop_duplicates(subset=['SERIAL_NO'], keep='first')
    return df
