import io
import os
import shutil
import subprocess
import tempfile
import time

import pyzipper
import pandas as pd

from .config import ZIP_PASSWORD, COLS_NPO as _COLS_NPO
from .zip_utils import (
    find_zip_tool as _find_zip_tool,
    build_extract_cmd as _build_extract_cmd,
    detect_encoding_path as _detect_encoding_path,
    detect_encoding_from_bytes as _detect_encoding_from_bytes,
)

_COLS_REQUIRED = ['TRBRCD', 'REFERENCE', 'DRAMOUNT', 'CRAMOUNT']
_LOCAC_TARGET  = '502003'
_CUSTOMER_ACH  = '1000-003526275'


def _doc_zip(zip_path: str) -> pd.DataFrame:
    result = _find_zip_tool()
    if result:
        tool_path, tool_type = result
        print(f'[B2][DIAG] {tool_type}: {tool_path} | {os.path.basename(zip_path)}')
        try:
            return _doc_zip_tool(zip_path, tool_path, tool_type)
        except Exception as e:
            print(f'[B2][WARN] {tool_type} lỗi ({e}), dùng pyzipper...')
    else:
        print(f'[B2][DIAG] 7z/WinRAR NOT found — pyzipper | {os.path.basename(zip_path)}')
    return _doc_zip_pyzipper(zip_path)


def _doc_zip_tool(zip_path: str, tool_path: str, tool_type: str) -> pd.DataFrame:
    tmp_dir = tempfile.mkdtemp(prefix='ach_b2_')
    try:
        _t  = time.perf_counter()
        cmd = _build_extract_cmd(tool_path, tool_type, zip_path, tmp_dir, ZIP_PASSWORD.decode())
        r   = subprocess.run(cmd, capture_output=True, timeout=300)
        print(f'[B2][DIAG] extract {os.path.basename(zip_path)}: {time.perf_counter()-_t:.1f}s rc={r.returncode}')
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors='replace'))
        frames = []
        for name in sorted(os.listdir(tmp_dir)):
            if not name.lower().endswith('.csv'):
                continue
            path       = os.path.join(tmp_dir, name)
            enc        = _detect_encoding_path(path)
            file_frames = []
            for i, chunk in enumerate(pd.read_csv(
                path, dtype=str, encoding=enc,
                usecols=lambda c: c.strip() in _COLS_NPO,
                chunksize=100_000, low_memory=False,
            )):
                chunk.columns = [c.strip() for c in chunk.columns]
                if i == 0:
                    missing = [c for c in _COLS_REQUIRED if c not in chunk.columns]
                    if missing:
                        raise ValueError(f'Thiếu cột: {missing}')
                if 'LOCAC' in chunk.columns:
                    chunk = chunk[chunk['LOCAC'].str.strip() == _LOCAC_TARGET]
                if 'CUSTOMER' in chunk.columns:
                    chunk = chunk[chunk['CUSTOMER'].str.strip() == _CUSTOMER_ACH]
                if not chunk.empty:
                    file_frames.append(chunk)
            if file_frames:
                frames.append(pd.concat(file_frames, ignore_index=True))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS_NPO)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _doc_zip_pyzipper(zip_path: str) -> pd.DataFrame:
    frames = []
    with pyzipper.AESZipFile(zip_path, 'r') as z:
        z.setpassword(ZIP_PASSWORD)
        for name in sorted(z.namelist()):
            if not name.lower().endswith('.csv'):
                continue
            data = z.read(name)
            enc  = _detect_encoding_from_bytes(data[:512])
            df   = pd.read_csv(
                io.BytesIO(data), dtype=str, encoding=enc,
                usecols=lambda c: c.strip() in _COLS_NPO,
                low_memory=False, encoding_errors='replace',
            )
            df.columns = [c.strip() for c in df.columns]
            missing = [c for c in _COLS_REQUIRED if c not in df.columns]
            if missing:
                raise ValueError(f'Thiếu cột: {missing}')
            if 'LOCAC' in df.columns:
                df = df[df['LOCAC'].str.strip() == _LOCAC_TARGET]
            if 'CUSTOMER' in df.columns:
                df = df[df['CUSTOMER'].str.strip() == _CUSTOMER_ACH]
            if not df.empty:
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS_NPO)


def xu_ly_gl02(zip_path: str, log_callback=None):
    """Doc GL02 zip, trả về (df_npo_di, df_npo_den)."""
    df = _doc_zip(zip_path)

    df['CRAMOUNT'] = pd.to_numeric(df['CRAMOUNT'], errors='coerce').fillna(0).astype('int64')
    df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0).astype('int64')
    if 'LOCAC' in df.columns:
        df['LOCAC'] = df['LOCAC'].astype(str).str.strip()

    _extracted      = df['REFERENCE'].str.extract(r'[A-Za-z]+(\d+)$', expand=False)
    _stripped       = _extracted.str.lstrip('0')
    df['SO_TRACE']  = _stripped.where(_stripped != '', other='0').where(_extracted.notna(), other='')

    npo_di = df[df['CRAMOUNT'] != 0].copy()
    npo_di['KEY_DI'] = (
        npo_di['TRBRCD'].str.strip()
        + npo_di['SO_TRACE']
        + npo_di['CRAMOUNT'].astype(str)
    )

    npo_den = df[df['CRAMOUNT'] == 0].copy()
    npo_den['KEY_DEN'] = npo_den['SO_TRACE'] + npo_den['DRAMOUNT'].astype(str)

    _log = log_callback or print
    _log(f'[B2] GL02 | NPO_DI: {len(npo_di):,} dòng | NPO_DEN: {len(npo_den):,} dòng')
    return npo_di.reset_index(drop=True), npo_den.reset_index(drop=True)
