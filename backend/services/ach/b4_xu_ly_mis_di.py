import io
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List
from datetime import datetime

import pyzipper
import pandas as pd

from .config import ZIP_PASSWORD, TPAY_TU as _DEFAULT_TPAY_TU, TPAY_DEN as _DEFAULT_TPAY_DEN
from .zip_utils import (
    find_zip_tool as _find_zip_tool,
    build_extract_cmd as _build_extract_cmd,
    detect_encoding_path as _detect_encoding_path,
    detect_encoding_from_bytes as _detect_encoding_from_bytes,
    NULL_SESSION as _NULL_SESSION,
)

_TRANG_THAI_LOAI_TRU = {'CALD', 'ERPO', 'TPER'}

_COLS = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SE_TRACE', 'SESSION', 'LOAI_LENH_OSB', 'NH_NHAN',
    'MA_GIAO_DICH', 'NOI_DUNG', 'NGAY_KENH_TRA',
]


def _doc_zip(zip_path: str, session_filter: str = None) -> pd.DataFrame:
    result = _find_zip_tool()
    if result:
        tool_path, tool_type = result
        print(f'[B4][DIAG] {tool_type}: {tool_path} | {os.path.basename(zip_path)}')
        try:
            return _doc_zip_tool(zip_path, session_filter, tool_path, tool_type)
        except Exception as e:
            print(f'[B4][WARN] {tool_type} lỗi ({e}), dùng pyzipper...')
    else:
        print(f'[B4][DIAG] 7z/WinRAR NOT found — pyzipper | {os.path.basename(zip_path)}')
    return _doc_zip_pyzipper(zip_path, session_filter)


def _doc_zip_tool(zip_path: str, session_filter, tool_path: str, tool_type: str) -> pd.DataFrame:
    tmp_dir = tempfile.mkdtemp(prefix='ach_b4_')
    try:
        _t  = time.perf_counter()
        cmd = _build_extract_cmd(tool_path, tool_type, zip_path, tmp_dir, ZIP_PASSWORD.decode())
        r   = subprocess.run(cmd, capture_output=True, timeout=300)
        print(f'[B4][DIAG] extract {os.path.basename(zip_path)}: {time.perf_counter()-_t:.1f}s rc={r.returncode}')
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


def _tao_so_trace(df: pd.DataFrame) -> pd.Series:
    se = df['SE_TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    tr = df['TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    return se.where(se.ne(''), tr)


def _get_timeout_indices(df_tpay: pd.DataFrame, df_non_tpay: pd.DataFrame,
                         dict_gw_count: Dict[str, int]) -> pd.Index:
    if df_tpay.empty:
        return pd.Index([], dtype='int64')

    key_col  = 'CN tiền Hub'
    cnt_tpay = df_tpay[key_col].value_counts()
    cnt_non  = (df_non_tpay[key_col].value_counts()
                if not df_non_tpay.empty else pd.Series(dtype='int64'))

    keys      = cnt_tpay.index
    c_gw      = pd.Series({k: dict_gw_count.get(str(k), 0) for k in keys}, dtype='int64')
    c_non     = cnt_non.reindex(keys, fill_value=0)
    available = (c_gw - c_non).clip(lower=0)
    n_thua    = (cnt_tpay - available).clip(lower=0)

    cc_rev    = df_tpay.groupby(key_col, sort=False).cumcount(ascending=False)
    threshold = df_tpay[key_col].map(n_thua.to_dict()).fillna(0)
    return df_tpay.index[cc_rev < threshold]


def _doc_mis_di_raw(zip_paths: List[str], session_id: str, log_callback=None) -> pd.DataFrame:
    """Đọc 2 ZIP MIS_DI song song, trả về DataFrame thô. Dùng cho parallel I/O."""
    _log = log_callback or print
    _log('[B4] Đọc MIS_DI từ 2 ZIP...')
    sid = str(session_id)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_doc_zip, p, sid) for p in zip_paths]
        frames  = [f.result() for f in futures]
    return pd.concat(frames, ignore_index=True)


def _process_mis_di(df: pd.DataFrame, dict_gw_count: Dict[str, int], session_id: str,
                    df_gw: pd.DataFrame = None,
                    tpay_tu: datetime = None, tpay_den: datetime = None,
                    log_callback=None):
    """Xử lý DataFrame MIS_DI đã đọc trước."""
    _tpay_tu  = tpay_tu  if tpay_tu  is not None else _DEFAULT_TPAY_TU
    _tpay_den = tpay_den if tpay_den is not None else _DEFAULT_TPAY_DEN

    _log = log_callback or print
    sid  = str(session_id)

    df = df[~df['TRANG_THAI_LENH'].isin(_TRANG_THAI_LOAI_TRU)].copy()
    df['SO_TIEN']   = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    df['SO_TRACE']  = _tao_so_trace(df)
    df['NGAY_KENH_TRA'] = pd.to_datetime(
        df['NGAY_KENH_TRA'].str.strip(), format='%d/%m/%Y %H:%M:%S', errors='coerce'
    )

    df['SESSION']      = df['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
    df['SESSION_NULL'] = df['SESSION'].isin(['', 'nan', 'None', 'NaN'])

    mask_scnl = df['TRANG_THAI_LENH'] == 'SCNL'
    df_scnl   = df[mask_scnl & (df['SESSION'] == sid)].copy()
    df_txrt   = df[(df['TRANG_THAI_LENH'] == 'TXRT') & (df['SESSION'] == sid)].copy()

    mask_tpay       = df['TRANG_THAI_LENH'] == 'TPAY'
    mask_session_ok = df['SESSION'] == sid
    mask_null_ok    = (
        df['SESSION_NULL']
        & df['NGAY_KENH_TRA'].notna()
        & (df['NGAY_KENH_TRA'] >= _tpay_tu)
        & (df['NGAY_KENH_TRA'] < _tpay_den)
    )
    df_tpay = df[mask_tpay & (mask_session_ok | mask_null_ok)].copy()

    df_mis_di = pd.concat([df_scnl, df_txrt, df_tpay])

    cn_clean         = df_mis_di['CHI_NHANH'].astype(str).str.strip()
    df_mis_di['KEY_HUB'] = cn_clean + df_mis_di['SO_TRACE'] + df_mis_di['SO_TIEN'].astype(str)
    cn_tien          = cn_clean + df_mis_di['SO_TIEN'].astype(str)
    loc              = df_mis_di.columns.get_loc('CHI_NHANH') + 1
    df_mis_di.insert(loc, 'CN tiền Hub', cn_tien)

    df_non_tpay_in_mis = df_mis_di[df_mis_di['TRANG_THAI_LENH'].isin(['SCNL', 'TXRT'])]
    df_tpay_in_mis     = df_mis_di[df_mis_di['TRANG_THAI_LENH'] == 'TPAY']
    timeout_idx        = _get_timeout_indices(df_tpay_in_mis, df_non_tpay_in_mis, dict_gw_count)

    df_timeout_candidates = df_mis_di.loc[timeout_idx].copy()
    df_mis_di_final       = df_mis_di[~df_mis_di.index.isin(timeout_idx)].copy()

    _QUOTE  = "'"
    df_timeout = df_timeout_candidates.copy()
    n_in_gw    = 0
    if df_gw is not None and 'MSGREF' in df_gw.columns and len(df_timeout_candidates) > 0:
        gw_msgref_set = set(
            df_gw['MSGREF'].fillna('').astype(object).astype(str)
            .str.strip().str.lstrip(_QUOTE)
        )
        tpay_msgref = (
            df_timeout['MSGREF'].fillna('').astype(object).astype(str)
            .str.strip().str.lstrip(_QUOTE)
        )
        mask_in_gw = tpay_msgref.isin(gw_msgref_set)
        df_timeout.insert(df_timeout.columns.get_loc('MSGREF') + 1, 'CO_TRONG_GW', mask_in_gw.values)
        n_in_gw = int(mask_in_gw.sum())
        if n_in_gw > 0:
            _log(f'[B4] MSGREF check: {n_in_gw} TPAY có MSGREF trong GW → đánh dấu CO_TRONG_GW')
    else:
        df_timeout['CO_TRONG_GW'] = False

    _log(
        f'[B4] MIS_DI → tổng trước timeout: {len(df_mis_di):,} | '
        f'SCNL: {len(df_scnl):,} | TXRT: {len(df_txrt):,} | TPAY: {len(df_tpay):,} | '
        f'Timeout không kênh: {len(df_timeout):,} (có trong GW: {n_in_gw}) | Final: {len(df_mis_di_final):,}'
    )
    return df_mis_di_final.reset_index(drop=True), df_timeout.reset_index(drop=True)


def xu_ly_mis_di(zip_paths: List[str], dict_gw_count: Dict[str, int], session_id: str,
                 df_gw: pd.DataFrame = None,
                 tpay_tu: datetime = None, tpay_den: datetime = None, log_callback=None):
    df_raw = _doc_mis_di_raw(zip_paths, session_id, log_callback)
    return _process_mis_di(df_raw, dict_gw_count, session_id, df_gw, tpay_tu, tpay_den, log_callback)
