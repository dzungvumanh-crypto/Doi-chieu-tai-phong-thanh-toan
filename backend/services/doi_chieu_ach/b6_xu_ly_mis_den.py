"""B6 — Đọc và xử lý MIS chiều ĐẾN."""
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List

import pandas as pd
import pyzipper

from .config import ZIP_PASSWORD

log = logging.getLogger(__name__)

_COLS = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SESSION', 'LOAI_LENH_OSB', 'NH_GUI', 'NOI_DUNG',
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
    """Đọc ZIP CSV MIS_DEN theo kiểu streaming; lọc sẵn theo session nếu có."""
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
                                    sess = (chunk['SESSION'].fillna('').astype(object).astype(str)
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
                        log.warning('[B6] Encoding detect sai trong %s, thử lại errors=replace', name)
                        continue
                    raise
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS)


def xu_ly_mis_den(zip_paths: List[str], session_id: str, ngay_doi_chieu: datetime,
                  log_callback=None):
    """Đọc 2 ZIP MIS_DEN song song → df_mis_den đã lọc, có KEY_DEN_HUB."""
    sid = str(session_id)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_doc_zip, p, sid) for p in zip_paths]
        frames = [f.result() for f in futures]
    df = pd.concat(frames, ignore_index=True)

    df['NGAY_GIAO_DICH'] = pd.to_datetime(
        df['NGAY_GIAO_DICH'].str.strip(), format='%d/%m/%Y', errors='coerce'
    )
    df['SESSION'] = df['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
    df['SESSION_NULL'] = df['SESSION'].isin(['', 'nan', 'None', 'NaN'])

    ngay_ts = pd.Timestamp(ngay_doi_chieu.date())

    # Lọc chính xác: đúng session, hoặc session rỗng nhưng đúng ngày giao dịch
    mask_ok = (df['SESSION'] == sid) | (
        df['SESSION_NULL'] & (df['NGAY_GIAO_DICH'] == ngay_ts)
    )
    df = df[mask_ok].copy()

    # Trả về chuỗi để Excel không hiển thị số serial
    df['NGAY_GIAO_DICH'] = df['NGAY_GIAO_DICH'].dt.strftime('%d/%m/%Y').fillna('')

    df = df[df['TRANG_THAI_LENH'].astype(str).str.strip() != 'RJCT'].copy()
    df['SO_TIEN'] = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    df['TRACE'] = df['TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    df['KEY_DEN_HUB'] = df['TRACE'] + df['SO_TIEN'].astype(str)

    (log_callback or print)(f'[B6] MIS_DEN | {len(df):,} dòng sau lọc')
    return df.reset_index(drop=True)
