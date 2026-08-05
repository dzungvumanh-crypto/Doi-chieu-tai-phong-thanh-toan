"""B2 — Đọc GL02 (NPO/IPCAS), tách thành NPO_DI và NPO_DEN."""
import io
import logging

import pandas as pd
import pyzipper

from .config import ZIP_PASSWORD, COLS_NPO as _COLS_NPO

log = logging.getLogger(__name__)

_COLS_REQUIRED = ['TRBRCD', 'REFERENCE', 'DRAMOUNT', 'CRAMOUNT']

_LOCAC_TARGET = '502003'
_CUSTOMER_ACH = '1000-003526275'  # Mã khách hàng kênh ACH — lọc khi LOCAC 502003 có nhiều CUSTOMER


def _detect_encoding(z: pyzipper.AESZipFile, name: str) -> str:
    """Phát hiện encoding bằng cách peek 512 byte đầu — tránh re-read toàn bộ file."""
    with z.open(name) as f:
        raw = f.read(512)
    if raw[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'cp1252'


def _doc_zip(zip_path: str) -> pd.DataFrame:
    """Đọc ZIP nhiều CSV, lọc LOCAC=502003 ngay từng chunk (không đọc hết rồi mới lọc)."""
    frames = []
    with pyzipper.AESZipFile(zip_path, 'r') as z:
        z.setpassword(ZIP_PASSWORD)
        for name in sorted(z.namelist()):
            if not name.lower().endswith('.csv'):
                continue
            enc = _detect_encoding(z, name)
            for errors in ('strict', 'replace'):
                try:
                    with z.open(name) as raw_f:
                        wrapped = io.TextIOWrapper(raw_f, encoding=enc, errors=errors)
                        file_frames = []
                        for i, chunk in enumerate(
                            pd.read_csv(
                                wrapped, dtype=str,
                                usecols=lambda c: c.strip() in _COLS_NPO,
                                chunksize=100_000, low_memory=False,
                            )
                        ):
                            chunk.columns = [c.strip() for c in chunk.columns]
                            if i == 0:
                                missing = [c for c in _COLS_REQUIRED if c not in chunk.columns]
                                if missing:
                                    raise ValueError(f'File GL02 thiếu cột: {missing}')
                            if 'LOCAC' in chunk.columns:
                                chunk = chunk[chunk['LOCAC'].str.strip() == _LOCAC_TARGET]
                            if 'CUSTOMER' in chunk.columns:
                                chunk = chunk[chunk['CUSTOMER'].str.strip() == _CUSTOMER_ACH]
                            if not chunk.empty:
                                file_frames.append(chunk)
                        if file_frames:
                            frames.append(pd.concat(file_frames, ignore_index=True))
                    break
                except UnicodeDecodeError:
                    if errors == 'strict':
                        log.warning('[B2] Encoding detect sai trong %s, thử lại errors=replace', name)
                        continue
                    raise
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS_NPO)


def xu_ly_gl02(zip_path: str, log_callback=None):
    """Đọc GL02 zip → (df_npo_di, df_npo_den)."""
    df = _doc_zip(zip_path)

    # ── Chuẩn hoá số tiền ──
    df['CRAMOUNT'] = pd.to_numeric(df['CRAMOUNT'], errors='coerce').fillna(0).astype('int64')
    df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0).astype('int64')

    # LOCAC đã lọc trong _doc_zip — chỉ chuẩn hoá lại chuỗi
    if 'LOCAC' in df.columns:
        df['LOCAC'] = df['LOCAC'].astype(str).str.strip()

    # ── SO_TRACE: phần số cuối REFERENCE, bỏ số 0 đứng đầu ──
    _extracted = df['REFERENCE'].str.extract(r'[A-Za-z]+(\d+)$', expand=False)
    _stripped = _extracted.str.lstrip('0')
    # lstrip hết → số là '0'; không match → None (giữ nguyên ngữ nghĩa bản gốc)
    df['SO_TRACE'] = _stripped.where(_stripped != '', other='0').where(_extracted.notna(), other=None)
    df['_trace_str'] = df['SO_TRACE'].fillna('')

    # NPO_DI: CRAMOUNT != 0 (ghi Có — lệnh chuyển đi)
    npo_di = df[df['CRAMOUNT'] != 0].copy()
    npo_di['KEY_DI'] = (
        npo_di['TRBRCD'].str.strip()
        + npo_di['_trace_str']
        + npo_di['CRAMOUNT'].astype(str)
    )

    # NPO_DEN: CRAMOUNT == 0 (ghi Nợ — lệnh nhận về)
    npo_den = df[df['CRAMOUNT'] == 0].copy()
    npo_den['KEY_DEN'] = (
        npo_den['_trace_str']
        + npo_den['DRAMOUNT'].astype(str)
    )

    (log_callback or print)(
        f'[B2] GL02 | NPO_DI: {len(npo_di):,} dòng | NPO_DEN: {len(npo_den):,} dòng'
    )
    return npo_di.reset_index(drop=True), npo_den.reset_index(drop=True)
