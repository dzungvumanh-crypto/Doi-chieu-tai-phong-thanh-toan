import io
import os
import shutil
import subprocess
import tempfile
import time

import pyzipper
import pandas as pd

from .config import zip_password, COLS_NPO as _COLS_NPO
from .zip_utils import (
    find_zip_tool as _find_zip_tool,
    build_extract_cmd as _build_extract_cmd,
    detect_encoding_path as _detect_encoding_path,
    detect_encoding_from_bytes as _detect_encoding_from_bytes,
    bao_dung_cong_cu as _bao_dung_cong_cu,
    bao_giai_nen_xong as _bao_giai_nen_xong,
    bao_lui_ve_pyzipper as _bao_lui_ve_pyzipper,
)

_COLS_REQUIRED = ['TRBRCD', 'REFERENCE', 'DRAMOUNT', 'CRAMOUNT']
# LOCAC = mã đơn vị hạch toán kênh ACH trên GL02 (nguồn: modules/b2_xu_ly_gl02.py
# bản gốc PR). CUSTOMER lọc thêm vì 1 LOCAC=502003 có thể có nhiều CUSTOMER khác
# nhau — chỉ đúng mã khách hàng này mới là giao dịch kênh ACH thật.
_LOCAC_TARGET  = '502003'
_CUSTOMER_ACH  = '1000-003526275'


def _log_loc_filter(n_truoc: int, n_sau: int, ten_file: str, log_callback) -> None:
    """Audit 2026-08-04 — trước đây lọc LOCAC/CUSTOMER (2 nhánh 7z/pyzipper) không
    log số dòng bị loại, dễ khiến 1 chi nhánh/khách hàng biến mất khỏi NPO mà
    không ai biết.

    2026-08-22 — nhận thẳng số dòng (không phải DataFrame) để `_doc_zip_tool()`
    có thể gộp TOÀN BỘ chunk của 1 file thành 1 dòng log duy nhất — GL02 là sổ
    cái toàn ngân hàng, một file vật lý đọc theo chunk 100k có thể bị lọc sạch
    hàng chục lần liên tiếp (đúng thiết kế, không phải lỗi), log riêng từng
    chunk tạo ra hàng chục dòng gần giống hệt nhau, khó rà khi cần soát lại."""
    _log = log_callback or print
    if n_truoc != n_sau:
        _log(f'[B2] {ten_file}: loại {n_truoc - n_sau:,} dòng theo LOCAC={_LOCAC_TARGET}/'
             f'CUSTOMER={_CUSTOMER_ACH} (giữ {n_sau:,}/{n_truoc:,})')


def _doc_zip(zip_path: str, log_callback=None) -> pd.DataFrame:
    result = _find_zip_tool()
    if result:
        tool_path, tool_type = result
        _bao_dung_cong_cu('B2', zip_path, tool_type, tool_path, log_callback)
        try:
            return _doc_zip_tool(zip_path, tool_path, tool_type, log_callback)
        except Exception as e:
            _bao_lui_ve_pyzipper('B2', zip_path, str(e), log_callback)
    else:
        _bao_lui_ve_pyzipper('B2', zip_path, '', log_callback)
    return _doc_zip_pyzipper(zip_path, log_callback)


def _doc_zip_tool(zip_path: str, tool_path: str, tool_type: str, log_callback=None) -> pd.DataFrame:
    tmp_dir = tempfile.mkdtemp(prefix='ach_b2_')
    try:
        _t  = time.perf_counter()
        cmd = _build_extract_cmd(tool_path, tool_type, zip_path, tmp_dir, zip_password().decode())
        r   = subprocess.run(cmd, capture_output=True, timeout=300)
        _bao_giai_nen_xong('B2', zip_path, time.perf_counter() - _t, r.returncode, log_callback)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors='replace'))
        frames = []
        for name in sorted(os.listdir(tmp_dir)):
            if not name.lower().endswith('.csv'):
                continue
            path       = os.path.join(tmp_dir, name)
            enc        = _detect_encoding_path(path)
            file_frames = []
            n_truoc_tong, n_sau_tong = 0, 0
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
                n_truoc_tong += len(chunk)
                if 'LOCAC' in chunk.columns:
                    chunk = chunk[chunk['LOCAC'].str.strip() == _LOCAC_TARGET]
                if 'CUSTOMER' in chunk.columns:
                    chunk = chunk[chunk['CUSTOMER'].str.strip() == _CUSTOMER_ACH]
                n_sau_tong += len(chunk)
                if not chunk.empty:
                    file_frames.append(chunk)
            _log_loc_filter(n_truoc_tong, n_sau_tong, name, log_callback)
            if file_frames:
                frames.append(pd.concat(file_frames, ignore_index=True))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS_NPO)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _doc_zip_pyzipper(zip_path: str, log_callback=None) -> pd.DataFrame:
    frames = []
    with pyzipper.AESZipFile(zip_path, 'r') as z:
        z.setpassword(zip_password())
        for name in sorted(z.namelist()):
            if not name.lower().endswith('.csv'):
                continue
            if log_callback:
                log_callback(f'[B2] Đang nạp {name} vào bộ nhớ (cách dự phòng)...')
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
            n_truoc = len(df)
            if 'LOCAC' in df.columns:
                df = df[df['LOCAC'].str.strip() == _LOCAC_TARGET]
            if 'CUSTOMER' in df.columns:
                df = df[df['CUSTOMER'].str.strip() == _CUSTOMER_ACH]
            _log_loc_filter(n_truoc, len(df), name, log_callback)
            if not df.empty:
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=_COLS_NPO)


def xu_ly_gl02(zip_path: str, log_callback=None):
    """Doc GL02 zip, trả về (df_npo_di, df_npo_den)."""
    df = _doc_zip(zip_path, log_callback)

    df['CRAMOUNT'] = pd.to_numeric(df['CRAMOUNT'], errors='coerce').fillna(0).astype('int64')
    df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0).astype('int64')
    if 'LOCAC' in df.columns:
        df['LOCAC'] = df['LOCAC'].astype(str).str.strip()

    # SO_TRACE = 12 ký tự từ ký tự thứ 8 của REFERENCE (mục 4.1 tài liệu đối chiếu).
    _extracted      = df['REFERENCE'].str[7:19]
    _stripped       = _extracted.str.lstrip('0')
    df['SO_TRACE']  = _stripped.where(_stripped != '', other='0').where(_extracted.notna(), other='')

    npo_di = df[df['CRAMOUNT'] != 0].copy()
    npo_di['KEY_DI'] = (
        npo_di['TRBRCD'].str.strip()
        + npo_di['SO_TRACE']
        + npo_di['CRAMOUNT'].astype(str)
    ) if len(npo_di) > 0 else pd.Series(dtype=object, index=npo_di.index)

    npo_den = df[df['CRAMOUNT'] == 0].copy()
    npo_den['KEY_DEN'] = (
        npo_den['TRBRCD'].str.strip()
        + npo_den['SO_TRACE']
        + npo_den['DRAMOUNT'].astype(str)
    ) if len(npo_den) > 0 else pd.Series(dtype=object, index=npo_den.index)

    _log = log_callback or print
    _log(f'[B2] GL02 | NPO_DI: {len(npo_di):,} dòng | NPO_DEN: {len(npo_den):,} dòng')
    return npo_di.reset_index(drop=True), npo_den.reset_index(drop=True)
