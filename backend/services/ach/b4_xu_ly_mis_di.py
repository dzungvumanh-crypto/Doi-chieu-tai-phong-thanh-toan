import io
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List
from datetime import datetime, timedelta

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


def _doc_mis_di_raw(zip_paths: List[str], session_id: str, log_callback=None) -> pd.DataFrame:
    """Đọc 2 ZIP MIS_DI song song, trả về DataFrame thô. Dùng cho parallel I/O."""
    _log = log_callback or print
    _log('[B4] Đọc MIS_DI từ 2 ZIP...')
    sid = str(session_id)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(_doc_zip, p, sid) for p in zip_paths]
        frames  = [f.result() for f in futures]
    return pd.concat(frames, ignore_index=True)


def _them_cot_khoa(df: pd.DataFrame) -> pd.DataFrame:
    """Thêm cột KEY_HUB (đối chiếu NPO) và 'CN tiền Hub' (đối chiếu GW) — dùng chung
    cho cả MIS_đi lẫn nhóm timeout theo trạng thái."""
    cn_clean       = df['CHI_NHANH'].astype(str).str.strip()
    df['KEY_HUB']  = cn_clean + df['SO_TRACE'] + df['SO_TIEN'].astype(str)
    cn_tien        = cn_clean + df['SO_TIEN'].astype(str)
    loc            = df.columns.get_loc('CHI_NHANH') + 1
    df.insert(loc, 'CN tiền Hub', cn_tien)
    return df


def _xay_dung_tra_cuu_gw_goc(df_gw_goc: pd.DataFrame) -> dict:
    """BR mới (2026-07-23, xử lý SESSION=NULL) — dict MSGREF (đã chuẩn hóa) ->
    SessionId (đã chuẩn hóa) tra trên GW gốc. 1 MSGREF chỉ có 1 giá trị đại diện
    (đã chốt với Business Owner); nếu GW gốc thực tế có ≥2 SessionId khác nhau cho
    cùng MSGREF (dữ liệu chưa dedup theo nhiều sheet) → marker '__NHIEU__', KHÔNG
    tự chọn 1 giá trị theo vị trí (đúng nguyên tắc đã áp dụng cho C.1/C.2)."""
    if df_gw_goc is None or len(df_gw_goc) == 0:
        return {}
    msgref = _chuan_hoa_msgref(df_gw_goc['MSGREF'])
    sess   = df_gw_goc['SessionId'].fillna('').astype(str).str.strip()
    sess   = sess.mask(sess.str.lower().isin(['nan', 'none']), '')
    grouped = pd.DataFrame({'MSGREF': msgref, 'SessionId': sess}).groupby('MSGREF')['SessionId'].unique()
    return {m: (v[0] if len(v) == 1 else '__NHIEU__') for m, v in grouped.items()}


def _loc_session_null_theo_gw_goc(df_null: pd.DataFrame, session_id: str,
                                  ngay_dt: datetime, df_gw_goc: pd.DataFrame):
    """BR mới (2026-07-23) — thay thế hoàn toàn logic khung giờ cũ cho giao dịch
    MIS_đi có SESSION=NULL. Trả về (mask_giu, ly_do), cùng index với `df_null`.

    Bước 1: tra SessionId thật của MSGREF trên GW gốc (chưa lọc session/PrcFlg).
    Bước 2: so NGAY_GIAO_DICH (ngày giá trị) với ngày đối chiếu T:
    - NGAY_GIAO_DICH = T: giữ nếu SessionId tìm được thuộc {rỗng, '0000', session
      đối chiếu}, hoặc MSGREF không có trên GW gốc (đánh dấu riêng để chấm thủ công
      phân biệt với "GW có nhưng SessionId rỗng").
    - NGAY_GIAO_DICH = T-1: CHỈ giữ nếu SessionId = session đối chiếu.
    - Khác cả T và T-1: giữ tạm — Business Owner xác nhận (2026-07-23) chưa có quy
      tắc chính thức cho trường hợp này, đánh dấu riêng để xem xét sau.
    GW gốc có ≥2 SessionId khác nhau cho cùng MSGREF → không xác định, giữ + đánh
    dấu riêng (không tự chọn 1 giá trị).
    """
    tra_cuu = _xay_dung_tra_cuu_gw_goc(df_gw_goc)
    sid = str(session_id).strip()

    msgref_norm = _chuan_hoa_msgref(df_null['MSGREF'])
    session_gw  = msgref_norm.map(tra_cuu)

    ngay_gd = pd.to_datetime(df_null['NGAY_GIAO_DICH'].str.strip(), format='%d/%m/%Y', errors='coerce')
    ngay_T  = ngay_dt.date()
    ngay_T1 = (ngay_dt - timedelta(days=1)).date()
    la_ngay_T  = ngay_gd.dt.date == ngay_T
    la_ngay_T1 = ngay_gd.dt.date == ngay_T1
    la_khac    = ~la_ngay_T & ~la_ngay_T1

    khong_tim_thay = session_gw.isna()
    nhieu_gia_tri  = session_gw == '__NHIEU__'
    la_rong        = session_gw == ''
    la_0000        = session_gw == '0000'
    la_dung        = session_gw == sid

    mask_giu = pd.Series(False, index=df_null.index)
    ly_do    = pd.Series('', index=df_null.index)

    m = la_khac
    mask_giu |= m; ly_do = ly_do.mask(m, 'NGAY_GIA_TRI_KHAC_T_VA_T-1')

    m = ~la_khac & nhieu_gia_tri
    mask_giu |= m; ly_do = ly_do.mask(m, 'GW_GOC_NHIEU_SESSIONID_KHAC_NHAU')

    m = la_ngay_T & ~nhieu_gia_tri & khong_tim_thay
    mask_giu |= m; ly_do = ly_do.mask(m, 'KHONG_TIM_THAY_TREN_GW')

    m = la_ngay_T & ~nhieu_gia_tri & ~khong_tim_thay & la_rong
    mask_giu |= m; ly_do = ly_do.mask(m, 'GW_SESSION_NULL')

    m = la_ngay_T & ~nhieu_gia_tri & ~khong_tim_thay & la_0000
    mask_giu |= m; ly_do = ly_do.mask(m, 'GW_SESSION_0000')

    m = (la_ngay_T | la_ngay_T1) & ~nhieu_gia_tri & ~khong_tim_thay & la_dung
    mask_giu |= m; ly_do = ly_do.mask(m, 'GW_SESSION_DOI_CHIEU')

    return mask_giu, ly_do


def _process_mis_di(df: pd.DataFrame, session_id: str, ngay_dt: datetime,
                    df_gw_goc: pd.DataFrame, log_callback=None):
    """Mục 2 tài liệu đối chiếu — xây "MIS_đi sạch" từ MIS_Hub thô.

    Bước 1 (TRẠNG THÁI): bỏ toàn bộ CALD/ERPO/TPER khỏi MIS_đi — loại hẳn, không
    dùng lại các trạng thái này cho bất kỳ mục đích nào khác (BR chính thức, xem
    project_ach_timeout_rule.md — thay thế cơ chế "Nguồn 1" cũ đã gỡ).

    Bước 2 (SESSION, áp dụng cho phần còn lại sau bước 1):
    - SESSION khác NULL: giữ nguyên cách xử lý hiện tại — chỉ lấy đúng session đối
      chiếu.
    - SESSION = NULL: BR mới (2026-07-23) — KHÔNG còn lọc theo khung giờ nữa, xem
      `_loc_session_null_theo_gw_goc()`.

    Bước 3 (trong `_them_cot_khoa()`): tạo khóa CN TIỀN = CHI_NHANH + SO_TIEN.

    Trả về df_mis_di — có thêm cột `LY_DO_GIU_SESSION_NULL` (rỗng với dòng SESSION
    khác NULL, dùng để chấm thủ công phân biệt lý do giữ giao dịch SESSION=NULL).
    """
    _log = log_callback or print
    sid  = str(session_id)

    df = df.copy()
    df['SO_TIEN']   = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    df['SO_TRACE']  = _tao_so_trace(df)
    df['NGAY_KENH_TRA'] = pd.to_datetime(
        df['NGAY_KENH_TRA'].str.strip(), format='%d/%m/%Y %H:%M:%S', errors='coerce'
    )

    df['SESSION']      = df['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
    df['SESSION_NULL'] = df['SESSION'].isin(['', 'nan', 'None', 'NaN'])

    # Bước 1 — TRẠNG THÁI: bỏ CALD/ERPO/TPER khỏi MIS_đi.
    mask_trang_thai_loai_tru = df['TRANG_THAI_LENH'].isin(_TRANG_THAI_LOAI_TRU)

    # Bước 2 — SESSION.
    mask_khac_null = ~df['SESSION_NULL'] & (df['SESSION'] == sid)

    df['LY_DO_GIU_SESSION_NULL'] = ''
    mask_session_null = pd.Series(False, index=df.index)
    df_null = df[df['SESSION_NULL']]
    if len(df_null) > 0:
        mask_null_giu, ly_do_null = _loc_session_null_theo_gw_goc(
            df_null, session_id, ngay_dt, df_gw_goc,
        )
        df.loc[df_null.index, 'LY_DO_GIU_SESSION_NULL'] = ly_do_null
        mask_session_null.loc[df_null.index] = mask_null_giu

    mask_session = mask_khac_null | mask_session_null

    df_mis_di = _them_cot_khoa(df[~mask_trang_thai_loai_tru & mask_session].copy())

    _log(f'[B4] MIS_đi (bước 1+2): {len(df_mis_di):,} dòng '
         f'(SESSION=NULL giữ lại: {int((mask_session_null & ~mask_trang_thai_loai_tru).sum()):,})')
    return df_mis_di.reset_index(drop=True)


def _chuan_hoa_msgref(s: pd.Series) -> pd.Series:
    return s.fillna('').astype(str).str.strip().str.lstrip("'")


_COLS_CAN_KIEM_TRA_THU_CONG = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'CN tiền Hub', 'REFHUB', 'MSGREF', 'TRANG_THAI_LENH',
    'SO_TIEN', 'SESSION', 'NGAY_KENH_TRA', 'LY_DO_CAN_KIEM_TRA',
]


def tim_can_kiem_tra_thu_cong(df: pd.DataFrame, session_id: str, ngay_dt: datetime,
                              df_gw_goc: pd.DataFrame, log_callback=None) -> pd.DataFrame:
    """Milestone F (Option C, Business Owner chốt 2026-07-27) — 2 nhánh SESSION=NULL
    còn treo (chưa có Business Rule tự động chính thức) được xuất RIÊNG để người đối
    chiếu tự quyết định, KHÔNG tự suy luận giữ/loại thay:

    1. `NGAY_GIA_TRI_KHAC_T_VA_T-1` — NGAY_GIAO_DICH không phải T cũng không phải
       T-1. Nhánh này ĐANG được `_process_mis_di()` giữ tạm trong MIS_đi (không đổi)
       — hàm này chỉ hiển thị lại để người chấm biết cần xác nhận.
    2. MSGREF rỗng hoặc không tra được SessionId trên GW gốc tại NGAY_GIAO_DICH=T-1 —
       nhánh này ĐANG bị `_process_mis_di()` loại thẳng khỏi MIS_đi (không đổi hành
       vi loại đó — đúng yêu cầu "không thay đổi Rule tự động"). Hàm này tạo BẢN SAO
       độc lập để hiển thị, không ảnh hưởng gì tới luồng chính.

    Không xử lý case "T-1, có SessionId nhưng rỗng/0000/khác session đối chiếu" —
    đó là hành vi ĐÃ CHỐT ("khác session → loại khỏi lần chạy này", xác nhận
    2026-07-25), không phải 1 trong 2 nhánh còn treo được nêu tên ở đây.

    Trả về DataFrame (có thể rỗng) — KHÔNG rỗng nghĩa là còn giao dịch cần chấm tay,
    không phải dấu hiệu lỗi.
    """
    _log = log_callback or print

    df = df.copy()
    df['SO_TIEN']  = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    df['SO_TRACE'] = _tao_so_trace(df)
    df['NGAY_KENH_TRA'] = pd.to_datetime(
        df['NGAY_KENH_TRA'].str.strip(), format='%d/%m/%Y %H:%M:%S', errors='coerce'
    )
    df['SESSION']      = df['SESSION'].fillna('').astype(str).str.strip().str.lstrip("'")
    df['SESSION_NULL'] = df['SESSION'].isin(['', 'nan', 'None', 'NaN'])

    # CALD/ERPO/TPER không bao giờ vào diện chấm tay (BR đã chốt, không đổi).
    mask_trang_thai_loai_tru = df['TRANG_THAI_LENH'].isin(_TRANG_THAI_LOAI_TRU)
    df_null = df[df['SESSION_NULL'] & ~mask_trang_thai_loai_tru]

    if len(df_null) == 0:
        _log('[Milestone F][Option C] Giao dịch cần kiểm tra thủ công: 0')
        return _them_cot_khoa(df_null.copy())[_COLS_CAN_KIEM_TRA_THU_CONG[:-1]].assign(LY_DO_CAN_KIEM_TRA='')

    mask_giu, ly_do = _loc_session_null_theo_gw_goc(df_null, session_id, ngay_dt, df_gw_goc)

    # Nhánh 1 — NGAY_GIA_TRI_KHAC_T_VA_T-1 (đã được giữ trong MIS_đi).
    mask_nhanh_1 = ly_do == 'NGAY_GIA_TRI_KHAC_T_VA_T-1'

    # Nhánh 2 — T-1 + không tra được SessionId trên GW gốc (đang bị loại khỏi MIS_đi).
    ngay_gd     = pd.to_datetime(df_null['NGAY_GIAO_DICH'].str.strip(), format='%d/%m/%Y', errors='coerce')
    ngay_T1     = (ngay_dt - timedelta(days=1)).date()
    la_ngay_T1  = ngay_gd.dt.date == ngay_T1
    msgref_norm = _chuan_hoa_msgref(df_null['MSGREF'])
    tra_cuu     = _xay_dung_tra_cuu_gw_goc(df_gw_goc)
    session_gw  = msgref_norm.map(tra_cuu)
    khong_tim_thay = session_gw.isna()

    mask_nhanh_2 = la_ngay_T1 & khong_tim_thay & ~mask_giu
    la_rong      = msgref_norm == ''
    ly_do_nhanh_2 = pd.Series('', index=df_null.index)
    ly_do_nhanh_2 = ly_do_nhanh_2.mask(mask_nhanh_2 & la_rong, 'MSGREF_RONG_TAI_T-1')
    ly_do_nhanh_2 = ly_do_nhanh_2.mask(mask_nhanh_2 & ~la_rong, 'MSGREF_KHONG_TIM_THAY_TREN_GW_TAI_T-1')

    mask_can_kiem_tra = mask_nhanh_1 | mask_nhanh_2
    ly_do_cuoi = ly_do.where(mask_nhanh_1, ly_do_nhanh_2)

    df_ket_qua = _them_cot_khoa(df_null[mask_can_kiem_tra].copy())
    df_ket_qua['LY_DO_CAN_KIEM_TRA'] = ly_do_cuoi[mask_can_kiem_tra].values

    _log(f'[Milestone F][Option C] Giao dịch cần kiểm tra thủ công: {len(df_ket_qua):,} '
         f'(NGAY_GIA_TRI_KHAC_T_VA_T-1: {int(mask_nhanh_1.sum()):,}, '
         f'MSGREF rỗng/không tìm thấy tại T-1: {int(mask_nhanh_2.sum()):,})')
    return df_ket_qua[_COLS_CAN_KIEM_TRA_THU_CONG].reset_index(drop=True)


def khop_voi_gw(df_mis_di: pd.DataFrame, dict_gw_count: dict, df_gw: pd.DataFrame,
               log_callback=None):
    """Mục 3 tài liệu đối chiếu — so khớp CN TIỀN (CHI_NHANH+SO_TIEN) giữa MIS_đi và GW.

    BR-ACH-001 (chốt 2026-07-21, qua nhiều vòng xác nhận với Business Owner) — thứ tự
    xử lý BẮT BUỘC, không được đảo:

    Requirement C.1 — xác định NHÓM CN_TIỀN chênh lệch (mức NHÓM, không chọn dòng):
    so tổng COUNT_MIS (mọi trạng thái) với COUNT_GW của cả nhóm. KHÔNG dùng cumcount
    để chọn ra dòng cụ thể nào trong nhóm — đó là suy luận không có căn cứ khi 1 nhóm
    có nhiều dòng trùng CN_TIỀN (y hệt vấn đề đã tránh ở Trường hợp 2/GW-thừa, xem
    `tim_nhom_gw_thua()`).

    Requirement C.2 — CHỈ trong các nhóm đã xác định thừa ở C.1, tra MSGREF (đã chuẩn
    hóa — bỏ dấu nháy đơn đầu) cho TỪNG dòng TPAY để phân loại (không so MSGREF trên
    toàn bộ dữ liệu trước khi có nhóm chênh lệch):
    - MSGREF KHÔNG có trên GW sạch → nhánh 1A, "Timeout không đi kênh" → df_timeout.
    - MSGREF CÓ trên GW sạch → nhánh 1B, "Timeout thật" (đã được kênh xác nhận, KHÔNG
      phải thừa) → df_khop_dung, đánh dấu cột `MATCH_TYPE = 'TIMEOUT'`.
    Tuyệt đối KHÔNG dùng `PrcFlg` của GW để quyết định — chỉ dựa vào MSGREF có tồn
    tại hay không, bất kể GW đang ở trạng thái gì.

    Dòng không phải TPAY trong nhóm thừa (SCNL/TXRT...) → vẫn vào df_khop_dung, không
    có MATCH_TYPE (TPAY là điều kiện lọc duy nhất cho khái niệm timeout, không đổi).

    Trả về (df_khop_dung, df_timeout).
    """
    _log   = log_callback or print
    cn_col = 'CN tiền Hub'

    # C.1 — nhóm nào thừa (mức nhóm, KHÔNG chọn dòng).
    cnt_mis_nhom   = df_mis_di.groupby(cn_col, sort=False)[cn_col].transform('size')
    cnt_gw_nhom    = df_mis_di[cn_col].map(dict_gw_count).fillna(0).astype(int)
    mask_nhom_thua = cnt_mis_nhom > cnt_gw_nhom

    # C.2 — trong nhóm thừa, tra MSGREF cho từng dòng TPAY.
    msgref_mis    = _chuan_hoa_msgref(df_mis_di['MSGREF'])
    msgref_gw_set = frozenset(_chuan_hoa_msgref(df_gw['MSGREF']))

    mask_tpay_trong_nhom_thua = mask_nhom_thua & (df_mis_di['TRANG_THAI_LENH'] == 'TPAY')
    mask_co_tren_gw           = msgref_mis.isin(msgref_gw_set)

    mask_timeout      = mask_tpay_trong_nhom_thua & ~mask_co_tren_gw   # nhánh 1A
    mask_timeout_that = mask_tpay_trong_nhom_thua & mask_co_tren_gw    # nhánh 1B

    df = df_mis_di.copy()
    df['MATCH_TYPE'] = ''
    df.loc[mask_timeout_that, 'MATCH_TYPE'] = 'TIMEOUT'

    df_timeout   = df[mask_timeout].drop(columns=['MATCH_TYPE']).copy()
    df_khop_dung = df[~mask_timeout].copy()

    _log(
        f'[B4][Mục 3] Nhóm CN_TIỀN thừa: {int(mask_nhom_thua.sum()):,} dòng | '
        f'Timeout không đi kênh (nhánh 1A): {len(df_timeout):,} | '
        f'Timeout thật đã khớp GW (nhánh 1B): {int(mask_timeout_that.sum()):,} | '
        f'Khớp đúng (chuyển sang đối chiếu NPO): {len(df_khop_dung):,}'
    )
    return df_khop_dung.reset_index(drop=True), df_timeout.reset_index(drop=True)


def tim_nhom_gw_thua(df_mis_di: pd.DataFrame, df_gw: pd.DataFrame, log_callback=None):
    """Requirement C.1a (Change Plan, Trường hợp 2 của BR-ACH-001) — xác định các
    NHÓM CN_TIỀN có GW nhiều hơn MIS_đi (COUNT_GW > COUNT_MIS), trả về DỮ LIỆU GỐC
    (đầy đủ cột) để người dùng chấm thủ công thẳng, không phải tự map ngược lại.

    Chỉ dựa vào việc bên MIS_đi có bản ghi nào không cho mỗi nhóm CN_TIỀN (KHÔNG
    dùng `PrcFlg`/`SessionId`, KHÔNG ghép cặp MSGREF hay bất kỳ kỹ thuật suy luận
    nào khác — đúng nguyên tắc BR-ACH-001 "không được tự suy luận"):
    - COUNT_MIS == 0 (nhóm chỉ tồn tại ở GW, không trùng khóa với bên nào) → xác
      định CHẮC CHẮN toàn bộ dòng GW của nhóm đó là chênh lệch (Trường hợp 1 — đã
      làm rõ 2026-07-21).
    - COUNT_MIS >= 1 và COUNT_GW > COUNT_MIS (cả 2 bên đều có, lệch số lượng) →
      KHÔNG xác định được bản ghi cụ thể nào là thừa (Trường hợp 2) → xuất TOÀN BỘ
      dòng gốc của CẢ 2 nguồn thuộc nhóm CN_TIỀN đó.

    Trả về (df_xac_dinh, df_can_doi_chieu) — cả 2 đều là dòng dữ liệu GỐC (nguyên
    cột từ df_gw/df_mis_di), kèm thêm cột `SOURCE` ('GW'/'MIS') và `NHOM_CN_TIEN`
    (khóa CN_TIỀN, để gom/lọc theo nhóm khi đối chiếu thủ công).
    """
    _log    = log_callback or print
    mis_col = 'CN tiền Hub'
    gw_col  = 'KEY_GW'

    cnt_mis  = df_mis_di.groupby(mis_col, sort=False).size()
    cnt_gw   = df_gw.groupby(gw_col, sort=False).size()
    all_keys = set(cnt_mis.index) | set(cnt_gw.index)
    cnt_mis  = cnt_mis.reindex(all_keys, fill_value=0)
    cnt_gw   = cnt_gw.reindex(all_keys, fill_value=0)

    gw_thua_keys       = [k for k in all_keys if cnt_gw[k] > cnt_mis[k]]
    keys_xac_dinh      = [k for k in gw_thua_keys if cnt_mis[k] == 0]
    keys_can_doi_chieu = [k for k in gw_thua_keys if cnt_mis[k] > 0]

    def _gan_nguon(df, key_col, keys, source_label):
        sub = df[df[key_col].isin(keys)].copy()
        sub['SOURCE']       = source_label
        sub['NHOM_CN_TIEN'] = sub[key_col]
        return sub

    df_xac_dinh = _gan_nguon(df_gw, gw_col, keys_xac_dinh, 'GW')

    df_can_doi_chieu = pd.concat([
        _gan_nguon(df_gw,     gw_col,  keys_can_doi_chieu, 'GW'),
        _gan_nguon(df_mis_di, mis_col, keys_can_doi_chieu, 'MIS'),
    ], ignore_index=True)

    _log(
        f'[B4][Mục 3 - C.1a] GW-thừa đã xác định: {len(keys_xac_dinh):,} nhóm '
        f'({len(df_xac_dinh):,} dòng) | GW-thừa cần đối chiếu thủ công: '
        f'{len(keys_can_doi_chieu):,} nhóm ({len(df_can_doi_chieu):,} dòng)'
    )
    return df_xac_dinh.reset_index(drop=True), df_can_doi_chieu.reset_index(drop=True)


# ─── Bước 2 — Checkpoint xác nhận thủ công: đọc file xác nhận (Bước 1) ────────

_GIA_TRI_XAC_NHAN_HOP_LE = {'Timeout không đi kênh', 'Timeout không đi kênh khác phiên đối chiếu'}


def _doc_sheet_can_xac_nhan(xac_nhan_path: str):
    """Đọc sheet CAN_XAC_NHAN của file xác nhận do `xuat_excel_xac_nhan()` (Bước 1)
    sinh ra. Trả về (df_can_xac_nhan, msgref_bo_sung) — df có cột KET_QUA_XAC_NHAN
    (vùng dữ liệu chính, phía trên dòng ghi chú "BỔ SUNG..."); msgref_bo_sung là
    list các MSGREF paste vào vùng bổ sung bên dưới. Nếu sheet trống (không có giao
    dịch nào cần xác nhận ở Bước 1) → trả về (DataFrame rỗng, []).

    Dùng openpyxl trực tiếp (không phải pd.read_excel) — pandas yêu cầu
    openpyxl>=3.1.5 để đọc qua engine='openpyxl', nhưng dự án pin 3.1.2."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(xac_nhan_path, data_only=True, read_only=True)
    except Exception as e:
        raise ValueError(f"Không đọc được file xác nhận: {xac_nhan_path} ({e})") from e

    if 'CAN_XAC_NHAN' not in wb.sheetnames:
        raise ValueError(f"File xác nhận thiếu sheet 'CAN_XAC_NHAN': {xac_nhan_path}")

    rows = [list(r) for r in wb['CAN_XAC_NHAN'].iter_rows(values_only=True)]
    if not rows:
        raise ValueError(f'Sheet CAN_XAC_NHAN rỗng: {xac_nhan_path}')

    o_dau = rows[0][0] if rows[0] else None
    chi_1_cot = all(len(r) <= 1 or all(v is None for v in r[1:]) for r in rows)
    if chi_1_cot and isinstance(o_dau, str) and 'không có giao dịch' in o_dau.lower():
        return pd.DataFrame(columns=['MSGREF']), []

    header = [str(c).strip() if c is not None else '' for c in rows[0]]
    if 'KET_QUA_XAC_NHAN' not in header:
        raise ValueError(
            f"Sheet CAN_XAC_NHAN thiếu cột KET_QUA_XAC_NHAN — file có thể bị sửa cấu trúc: {xac_nhan_path}"
        )
    if 'MSGREF' not in header:
        raise ValueError(
            f"Sheet CAN_XAC_NHAN thiếu cột MSGREF — file có thể bị sửa cấu trúc: {xac_nhan_path}"
        )

    note_idx = None
    for i in range(1, len(rows)):
        cell0 = rows[i][0] if rows[i] else None
        if isinstance(cell0, str) and cell0.strip().upper().startswith('BỔ SUNG'):
            note_idx = i
            break
    if note_idx is None:
        raise ValueError(
            "Không tìm thấy vùng 'BỔ SUNG GIAO DỊCH BỊ BỎ SÓT' trong sheet CAN_XAC_NHAN — "
            f"file có thể bị sửa cấu trúc: {xac_nhan_path}"
        )

    n_col = len(header)
    data_rows = [
        (r + [None] * (n_col - len(r)))[:n_col]
        for r in rows[1:note_idx]
        if any(v is not None for v in r)
    ]
    df = pd.DataFrame(data_rows, columns=header)

    msgref_bo_sung = []
    for r in rows[note_idx + 2:]:
        v = r[0] if r else None
        if v is not None and str(v).strip() != '':
            msgref_bo_sung.append(str(v).strip())

    return df, msgref_bo_sung


def ap_dung_xac_nhan(xac_nhan_path: str, df_mis_di_khop_gw: pd.DataFrame,
                     df_timeout: pd.DataFrame, df_mis_di_raw: pd.DataFrame,
                     log_callback=None):
    """Bước 2 — Checkpoint xác nhận thủ công (thay hướng mở rộng Business Rule cho
    Timeout không đi kênh, xem project_ach_timeout_rule.md). `khop_voi_gw()` chỉ
    PHÂN LUỒNG MIS_đi thành 2 nhánh (khớp đúng / Timeout không đi kênh) — file xác
    nhận phúc tra lại PHẠM VI của nhánh Timeout (nhánh 1A), KHÔNG sửa dữ liệu gốc.

    Toàn bộ giao dịch nhánh 1A đều THẬT SỰ là Timeout không đi kênh — không có khái
    niệm "máy phân loại sai". Xác nhận thủ công chỉ phân loại PHẠM VI:
    - KET_QUA_XAC_NHAN = 'Timeout không đi kênh' → Timeout của phiên đang đối chiếu.
    - KET_QUA_XAC_NHAN = 'Timeout không đi kênh khác phiên đối chiếu' → vẫn là
      Timeout, nhưng không thuộc phiên này (đối chiếu ở đúng phiên của nó là quy
      trình thủ công riêng, ngoài phạm vi lần chạy này).
    Cả 2 loại đều Ở LẠI nhánh Timeout, gắn cột `PHAN_LOAI_TIMEOUT` để phân biệt —
    KHÔNG loại nào quay lại pool đối chiếu (`df_mis_di_khop_gw`) của B5.
    - MSGREF bổ sung (giao dịch Timeout bị thuật toán bỏ sót hoàn toàn) → tra trên
      `df_mis_di_raw` (MIS_đi RAW, CHƯA lọc), thêm vào nhánh Timeout, `PHAN_LOAI_
      TIMEOUT='Phiên này'` (bị bỏ sót ở chính phiên này). Trạng thái thuộc
      {CALD, ERPO, TPER} (đã bị BR bước 1 loại hẳn, xem `_process_mis_di()`) →
      từ chối, báo lỗi — không được lách BR bằng đường bổ sung thủ công.

    Trả về (df_mis_di_khop_gw_final, df_timeout_final) — dùng thay
    (df_mis_di_khop_gw, df_timeout) ở phần còn lại của pipeline.
    """
    _log = log_callback or print

    df_can_xac_nhan, msgref_bo_sung = _doc_sheet_can_xac_nhan(xac_nhan_path)

    if len(df_can_xac_nhan) == 0:
        msgref_khac_phien  = []
        msgref_giu_timeout = []
        _log('[Bước 2] CAN_XAC_NHAN: không có giao dịch nào cần xác nhận.')
    else:
        gia_tri = df_can_xac_nhan['KET_QUA_XAC_NHAN'].apply(
            lambda v: str(v).strip() if pd.notna(v) else ''
        )
        thieu = df_can_xac_nhan[gia_tri == '']
        if len(thieu) > 0:
            raise ValueError(
                f'Còn {len(thieu)} dòng chưa chọn KET_QUA_XAC_NHAN trong CAN_XAC_NHAN '
                f"(MSGREF: {thieu['MSGREF'].astype(str).tolist()})"
            )
        sai = df_can_xac_nhan[~gia_tri.isin(_GIA_TRI_XAC_NHAN_HOP_LE)]
        if len(sai) > 0:
            chi_tiet = list(zip(sai['MSGREF'].astype(str), gia_tri[sai.index]))
            raise ValueError(f'Giá trị KET_QUA_XAC_NHAN không hợp lệ: {chi_tiet}')

        msgref_khac_phien  = df_can_xac_nhan.loc[
            gia_tri == 'Timeout không đi kênh khác phiên đối chiếu', 'MSGREF'
        ].astype(str).tolist()
        msgref_giu_timeout = df_can_xac_nhan.loc[gia_tri == 'Timeout không đi kênh', 'MSGREF'].astype(str).tolist()
        _log(f'[Bước 2] CAN_XAC_NHAN: Timeout khác phiên đối chiếu {len(msgref_khac_phien)}, '
             f'Timeout của phiên này {len(msgref_giu_timeout)}')

    msgref_timeout_chuan = _chuan_hoa_msgref(df_timeout['MSGREF']) if len(df_timeout) else pd.Series(dtype=str)

    def _tra_theo_msgref(msgref_list, nhan):
        if not msgref_list:
            return df_timeout.iloc[0:0].copy()
        muc_tieu = {str(m).strip().lstrip("'") for m in msgref_list}
        found    = df_timeout[msgref_timeout_chuan.isin(muc_tieu)].copy()
        thieu    = muc_tieu - set(_chuan_hoa_msgref(found['MSGREF'])) if len(found) else muc_tieu
        if thieu:
            raise ValueError(
                f'MSGREF xác nhận "{nhan}" không tìm thấy trong nhánh Timeout của lần chạy này: '
                f'{sorted(thieu)}'
            )
        return found

    df_khac_phien  = _tra_theo_msgref(msgref_khac_phien, 'Timeout không đi kênh khác phiên đối chiếu')
    df_giu_timeout = _tra_theo_msgref(msgref_giu_timeout, 'Timeout không đi kênh')

    # Checkpoint chỉ phân loại PHẠM VI của Timeout — không đụng pool đối chiếu B5.
    df_mis_di_khop_gw_final = df_mis_di_khop_gw
    _log(f'[Bước 2] MIS_đi khớp đúng: {len(df_mis_di_khop_gw_final)} dòng (không đổi bởi Checkpoint)')

    if len(df_khac_phien) > 0:
        df_khac_phien['PHAN_LOAI_TIMEOUT'] = 'Khác phiên đối chiếu'
    if len(df_giu_timeout) > 0:
        df_giu_timeout['PHAN_LOAI_TIMEOUT'] = 'Phiên này'

    df_bo_sung = df_giu_timeout.iloc[0:0].copy()
    if msgref_bo_sung:
        da_paste = pd.Series(msgref_bo_sung)
        trung_trong_paste = da_paste[da_paste.duplicated()].tolist()
        if trung_trong_paste:
            raise ValueError(f'MSGREF bị paste trùng lặp trong vùng bổ sung: {trung_trong_paste}')

        msgref_da_biet_chuan = {
            str(m).strip().lstrip("'") for m in (msgref_khac_phien + msgref_giu_timeout)
        }
        msgref_raw_chuan = _chuan_hoa_msgref(df_mis_di_raw['MSGREF'])

        rows, khong_tim_thay, trung_voi_da_biet, trang_thai_loai_tru = [], [], [], []
        for m in msgref_bo_sung:
            m_norm = str(m).strip().lstrip("'")
            if m_norm in msgref_da_biet_chuan:
                trung_voi_da_biet.append(m)
                continue
            match = df_mis_di_raw[msgref_raw_chuan == m_norm]
            if len(match) == 0:
                khong_tim_thay.append(m)
                continue
            if match['TRANG_THAI_LENH'].isin(_TRANG_THAI_LOAI_TRU).any():
                trang_thai_loai_tru.append(m)
                continue
            rows.append(match)

        if khong_tim_thay:
            raise ValueError(f'Không tìm thấy MSGREF trên MIS_đi RAW: {khong_tim_thay}')
        if trang_thai_loai_tru:
            raise ValueError(
                f'MSGREF bổ sung có TRANG_THAI_LENH thuộc {sorted(_TRANG_THAI_LOAI_TRU)} '
                f'(đã bị Business Rule bước 1 loại hẳn, không được bổ sung thủ công): {trang_thai_loai_tru}'
            )
        if trung_voi_da_biet:
            raise ValueError(f'MSGREF bổ sung đã có sẵn trong CAN_XAC_NHAN: {trung_voi_da_biet}')

        df_bo_sung = pd.concat(rows, ignore_index=True) if rows else df_bo_sung
        if len(df_bo_sung) > 0:
            df_bo_sung['PHAN_LOAI_TIMEOUT'] = 'Phiên này'

    _log(f'[Bước 2] Bổ sung từ MSGREF paste thêm: {len(df_bo_sung)} giao dịch')

    df_timeout_final = pd.concat(
        [df_giu_timeout, df_khac_phien, df_bo_sung], ignore_index=True, sort=False,
    )
    _log(f'[Bước 2] Timeout không đi kênh (final): {len(df_timeout_final)} dòng '
         f'(khác phiên đối chiếu: {len(df_khac_phien)})')

    return df_mis_di_khop_gw_final, df_timeout_final
