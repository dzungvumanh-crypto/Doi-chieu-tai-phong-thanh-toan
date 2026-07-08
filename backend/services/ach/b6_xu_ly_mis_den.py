import io
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List
from datetime import datetime

import pyzipper
import pandas as pd

from .config import ZIP_PASSWORD
from .zip_utils import (
    find_zip_tool as _find_zip_tool,
    build_extract_cmd as _build_extract_cmd,
    detect_encoding_path as _detect_encoding_path,
    detect_encoding_from_bytes as _detect_encoding_from_bytes,
    NULL_SESSION as _NULL_SESSION,
)

_COLS = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SESSION', 'LOAI_LENH_OSB', 'NH_GUI', 'NOI_DUNG',
]


def _doc_zip(zip_path: str, session_filter: str = None) -> pd.DataFrame:
    result = _find_zip_tool()
    if result:
        tool_path, tool_type = result
        print(f'[B6][DIAG] {tool_type}: {tool_path} | {os.path.basename(zip_path)}')
        try:
            return _doc_zip_tool(zip_path, session_filter, tool_path, tool_type)
        except Exception as e:
            print(f'[B6][WARN] {tool_type} lỗi ({e}), dùng pyzipper...')
    else:
        print(f'[B6][DIAG] 7z/WinRAR NOT found — pyzipper | {os.path.basename(zip_path)}')
    return _doc_zip_pyzipper(zip_path, session_filter)


def _doc_zip_tool(zip_path: str, session_filter, tool_path: str, tool_type: str) -> pd.DataFrame:
    tmp_dir = tempfile.mkdtemp(prefix='ach_b6_')
    try:
        _t  = time.perf_counter()
        cmd = _build_extract_cmd(tool_path, tool_type, zip_path, tmp_dir, ZIP_PASSWORD.decode())
        r   = subprocess.run(cmd, capture_output=True, timeout=300)
        print(f'[B6][DIAG] extract {os.path.basename(zip_path)}: {time.perf_counter()-_t:.1f}s rc={r.returncode}')
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors='replace'))
        frames = []
        for name in sorted(os.listdir(tmp_dir)):
            if not name.lower().endswith('.csv'):
                continue
            path = os.path.join(tmp_dir, name)
            enc  = _detect_encoding_path(path)
            if session_filter:
                sid  = str(session_filter)
                keep = frozenset({sid} | _NULL_SESSION)
                chunk_list = []
                for chunk in pd.read_csv(
                    path, dtype=str, encoding=enc,
                    usecols=lambda c: c in _COLS,
                    chunksize=200_000, low_memory=False,
                ):
                    if 'SESSION' in chunk.columns:
                        sess = chunk['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
                        chunk_list.append(chunk[sess.isin(keep)])
                if chunk_list:
                    frames.append(pd.concat(chunk_list, ignore_index=True))
            else:
                frames.append(pd.read_csv(
                    path, dtype=str, encoding=enc,
                    usecols=lambda c: c in _COLS, low_memory=False,
                ))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _doc_zip_pyzipper(zip_path: str, session_filter: str = None) -> pd.DataFrame:
    frames = []
    with pyzipper.AESZipFile(zip_path, 'r') as z:
        z.setpassword(ZIP_PASSWORD)
        for name in z.namelist():
            if not name.lower().endswith('.csv'):
                continue
            data = z.read(name)
            enc  = _detect_encoding_from_bytes(data[:512])
            df   = pd.read_csv(
                io.BytesIO(data), dtype=str, encoding=enc,
                usecols=lambda c: c in _COLS, low_memory=False,
                encoding_errors='replace',
            )
            if session_filter:
                sid  = str(session_filter)
                keep = frozenset({sid} | _NULL_SESSION)
                if 'SESSION' in df.columns:
                    sess = df['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
                    df   = df[sess.isin(keep)]
            if not df.empty:
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS)


def xu_ly_mis_den(zip_paths: List[str], session_id: str, ngay_doi_chieu: datetime, log_callback=None):
    """Đọc 2 ZIP MIS_DEN song song, trả về df_mis_den đã xử lý."""
    sid = str(session_id)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_doc_zip, p, sid) for p in zip_paths]
        frames  = [f.result() for f in futures]
    df = pd.concat(frames, ignore_index=True)

    df['NGAY_GIAO_DICH'] = pd.to_datetime(
        df['NGAY_GIAO_DICH'].str.strip(), format='%d/%m/%Y', errors='coerce'
    )
    df['SESSION']      = df['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
    df['SESSION_NULL'] = df['SESSION'].isin(['', 'nan', 'None', 'NaN'])

    ngay_ts = pd.Timestamp(ngay_doi_chieu.date())
    mask_ok = (df['SESSION'] == sid) | (
        df['SESSION_NULL'] & (df['NGAY_GIAO_DICH'] == ngay_ts)
    )
    df = df[mask_ok].copy()

    df['NGAY_GIAO_DICH'] = df['NGAY_GIAO_DICH'].dt.strftime('%d/%m/%Y').fillna('')
    df = df[df['TRANG_THAI_LENH'].astype(str).str.strip() != 'RJCT'].copy()
    df['SO_TIEN'] = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    df['TRACE']   = df['TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    df['KEY_DEN_HUB'] = df['TRACE'] + df['SO_TIEN'].astype(str)

    _log = log_callback or print
    _log(f'[B6] MIS_DEN | {len(df):,} dòng sau lọc')
    return df.reset_index(drop=True)
