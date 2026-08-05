"""B4 — Đọc và xử lý MIS chiều ĐI, tách lệnh TPAY timeout không đi được kênh."""
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List

import pandas as pd
import pyzipper

from .config import ZIP_PASSWORD

log = logging.getLogger(__name__)

_TRANG_THAI_LOAI_TRU = {'CALD', 'ERPO', 'TPER'}

_COLS = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SE_TRACE', 'SESSION', 'LOAI_LENH_OSB', 'NH_NHAN',
    'MA_GIAO_DICH', 'NOI_DUNG', 'NGAY_KENH_TRA',
]

_NULL_SESSION = frozenset({'', 'nan', 'None', 'NaN'})


def _detect_encoding(z: pyzipper.AESZipFile, name: str) -> str:
    """Phát hiện encoding bằng cách peek 512 byte đầu."""
    with z.open(name) as f:
        raw = f.read(512)
    if raw[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'cp1252'


def _doc_zip(zip_path: str, session_filter: str = None) -> pd.DataFrame:
    """Đọc ZIP CSV MIS_DI theo kiểu streaming để giảm RAM.

    session_filter: chỉ giữ dòng có SESSION trùng hoặc rỗng — cắt ~60-70% dữ liệu
    ngay lúc đọc.
    """
    frames = []
    with pyzipper.AESZipFile(zip_path, 'r') as z:
        z.setpassword(ZIP_PASSWORD)
        for name in z.namelist():
            if not name.lower().endswith('.csv'):
                continue
            enc = _detect_encoding(z, name)
            for errors in ('strict', 'replace'):
                try:
                    with z.open(name) as raw_f:
                        wrapped = io.TextIOWrapper(raw_f, encoding=enc, errors=errors)
                        if session_filter:
                            sid = str(session_filter)
                            keep_sessions = frozenset({sid} | _NULL_SESSION)
                            chunk_list = []
                            for chunk in pd.read_csv(
                                wrapped, dtype=str,
                                usecols=lambda c: c in _COLS,
                                chunksize=200_000, low_memory=False,
                            ):
                                if 'SESSION' in chunk.columns:
                                    sess = (chunk['SESSION'].fillna('').astype(str)
                                            .str.strip().str.lstrip("'"))
                                    chunk = chunk[sess.isin(keep_sessions)]
                                if not chunk.empty:
                                    chunk_list.append(chunk)
                            if chunk_list:
                                frames.append(pd.concat(chunk_list, ignore_index=True))
                        else:
                            frames.append(pd.read_csv(
                                wrapped, dtype=str,
                                usecols=lambda c: c in _COLS,
                                low_memory=False,
                            ))
                    break
                except UnicodeDecodeError:
                    if errors == 'strict':
                        log.warning('[B4] Encoding detect sai trong %s, thử lại errors=replace', name)
                        continue
                    raise
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS)


def _tao_so_trace(df: pd.DataFrame) -> pd.Series:
    """SE_TRACE nếu có, ngược lại TRACE. Bỏ dấu nháy đơn và số 0 đứng đầu."""
    se = df['SE_TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    tr = df['TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    return se.where(se.ne(''), tr)


def _get_timeout_indices(df_tpay: pd.DataFrame, df_non_tpay: pd.DataFrame,
                         dict_gw_count: Dict[str, int]) -> pd.Index:
    """Index các dòng TPAY thừa so với GW.

    df_non_tpay (SCNL + TXRT) là các lệnh đã chiếm slot GW.
    surplus = tổng lệnh MIS - số slot GW; n_timeout = min(surplus, số TPAY).
    """
    if df_tpay.empty:
        return pd.Index([], dtype='int64')

    key_col = 'CN tiền Hub'
    cnt_tpay = df_tpay[key_col].value_counts()
    cnt_non = (df_non_tpay[key_col].value_counts()
               if not df_non_tpay.empty else pd.Series(dtype='int64'))

    keys = cnt_tpay.index
    c_gw = pd.Series({k: dict_gw_count.get(str(k), 0) for k in keys}, dtype='int64')
    c_non = cnt_non.reindex(keys, fill_value=0)
    available = (c_gw - c_non).clip(lower=0)
    n_thua = (cnt_tpay - available).clip(lower=0)

    cc_rev = df_tpay.groupby(key_col, sort=False).cumcount(ascending=False)
    threshold = df_tpay[key_col].map(n_thua.to_dict()).fillna(0)
    return df_tpay.index[cc_rev < threshold]


def _doc_mis_di_raw(zip_paths: List[str], session_id: str, log_callback=None) -> pd.DataFrame:
    """Đọc 2 ZIP MIS_DI song song, trả DataFrame thô (chưa xử lý)."""
    (log_callback or print)('[B4] Đọc MIS_DI từ 2 ZIP...')
    sid = str(session_id)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_doc_zip, p, sid) for p in zip_paths]
        frames = [f.result() for f in futures]
    return pd.concat(frames, ignore_index=True)


def _process_mis_di(df: pd.DataFrame, dict_gw_count: Dict[str, int], session_id: str,
                    df_gw: pd.DataFrame = None,
                    tpay_tu: datetime = None, tpay_den: datetime = None,
                    log_callback=None):
    """Xử lý DataFrame MIS_DI đã đọc trước → (df_mis_di_final, df_timeout)."""
    if tpay_tu is None or tpay_den is None:
        # Bản gốc lấy mặc định từ config toàn cục. Ở đây ngày đối chiếu là của
        # từng lần chạy nên không có mặc định hợp lệ — thiếu là lỗi lập trình.
        raise ValueError('Thiếu mốc thời gian TPAY (tpay_tu / tpay_den)')

    _log = log_callback or print
    sid = str(session_id)

    # ── Chuẩn hoá ──
    df = df[~df['TRANG_THAI_LENH'].isin(_TRANG_THAI_LOAI_TRU)].copy()
    df['SO_TIEN'] = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    df['SO_TRACE'] = _tao_so_trace(df)
    df['NGAY_KENH_TRA'] = pd.to_datetime(
        df['NGAY_KENH_TRA'].str.strip(), format='%d/%m/%Y %H:%M:%S', errors='coerce'
    )
    df['SESSION'] = df['SESSION'].fillna('').astype(object).astype(str).str.strip().str.lstrip("'")
    df['SESSION_NULL'] = df['SESSION'].isin(['', 'nan', 'None', 'NaN'])

    # ── Chọn lệnh thuộc phiên đang đối chiếu ──
    mask_scnl = df['TRANG_THAI_LENH'] == 'SCNL'
    df_scnl = df[mask_scnl & (df['SESSION'] == sid)].copy()

    # TXRT: chỉ lấy trong session hiện tại (tránh lấy nhầm TXRT phiên cũ)
    df_txrt = df[(df['TRANG_THAI_LENH'] == 'TXRT') & (df['SESSION'] == sid)].copy()

    # TPAY: SESSION khớp HOẶC (SESSION rỗng VÀ NGAY_KENH_TRA nằm trong khoảng)
    mask_tpay = df['TRANG_THAI_LENH'] == 'TPAY'
    mask_session_ok = df['SESSION'] == sid
    mask_null_ok = (
        df['SESSION_NULL']
        & df['NGAY_KENH_TRA'].notna()
        & (df['NGAY_KENH_TRA'] >= tpay_tu)
        & (df['NGAY_KENH_TRA'] < tpay_den)
    )
    df_tpay = df[mask_tpay & (mask_session_ok | mask_null_ok)].copy()

    df_mis_di = pd.concat([df_scnl, df_txrt, df_tpay])   # giữ index gốc

    # ── Khoá đối chiếu ──
    cn_clean = df_mis_di['CHI_NHANH'].astype(str).str.strip()
    df_mis_di['KEY_HUB'] = cn_clean + df_mis_di['SO_TRACE'] + df_mis_di['SO_TIEN'].astype(str)
    cn_tien = cn_clean + df_mis_di['SO_TIEN'].astype(str)
    loc = df_mis_di.columns.get_loc('CHI_NHANH') + 1
    df_mis_di.insert(loc, 'CN tiền Hub', cn_tien)

    # ── Timeout: SCNL và TXRT đều chiếm slot GW ──
    df_non_tpay_in_mis = df_mis_di[df_mis_di['TRANG_THAI_LENH'].isin(['SCNL', 'TXRT'])]
    df_tpay_in_mis = df_mis_di[df_mis_di['TRANG_THAI_LENH'] == 'TPAY']
    timeout_idx = _get_timeout_indices(df_tpay_in_mis, df_non_tpay_in_mis, dict_gw_count)

    df_timeout_candidates = df_mis_di.loc[timeout_idx].copy()
    df_mis_di_final = df_mis_di[~df_mis_di.index.isin(timeout_idx)].copy()

    # TPAY có MSGREF trong GW → vẫn để trong timeout nhưng đánh dấu CO_TRONG_GW
    # (lệnh này có thể đã đi kênh thành công, cần kiểm tra thủ công)
    _QUOTE = "'"
    df_timeout = df_timeout_candidates.copy()
    n_in_gw = 0
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
            _log(f'[B4] MSGREF check: {n_in_gw} lệnh TPAY có MSGREF trong GW '
                 f'→ đánh dấu CO_TRONG_GW (cần kiểm tra thủ công)')
    else:
        df_timeout['CO_TRONG_GW'] = False

    _log(
        f'[B4] MIS_DI → tổng trước timeout: {len(df_mis_di):,} | '
        f'SCNL: {len(df_scnl):,} | TXRT: {len(df_txrt):,} | TPAY: {len(df_tpay):,} | '
        f'Timeout không kênh: {len(df_timeout):,} (có trong GW: {n_in_gw}) | '
        f'Còn lại: {len(df_mis_di_final):,}'
    )
    return df_mis_di_final.reset_index(drop=True), df_timeout.reset_index(drop=True)
