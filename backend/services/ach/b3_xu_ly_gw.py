import time
import pandas as pd

from .so_tien import doc_so_tien


def _xu_ly_sheet(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Tìm header row có BRCD, trả về DataFrame có header đúng."""
    header_row = 0
    for i, row in df_raw.iterrows():
        if 'BRCD' in row.values:
            header_row = i
            break
    df      = df_raw.iloc[header_row + 1:].reset_index(drop=True)
    raw_cols = [str(c).strip() for c in df_raw.iloc[header_row]]
    seen: dict[str, int] = {}
    deduped = []
    for c in raw_cols:
        if c in seen:
            seen[c] += 1
            deduped.append(f'{c}.{seen[c]}')
        else:
            seen[c] = 0
            deduped.append(c)
    df.columns = deduped
    return df


def _phan_loai_sheet_theo_session(df: pd.DataFrame, session_id: str) -> str:
    """Phân loại 1 sheet (đã làm sạch header) theo SessionId so với session mục tiêu.

    'thuan_nhat'      — sheet chỉ chứa đúng 1 SessionId và bằng session mục tiêu.
    'lan_can'         — sheet có session mục tiêu nhưng lẫn cả session khác.
    'khong_lien_quan' — không có cột SessionId, hoặc không chứa session mục tiêu.
    """
    if 'SessionId' not in df.columns:
        return 'khong_lien_quan'
    sids = df['SessionId'].astype(str).str.strip().unique()
    sid  = str(session_id).strip()
    if len(sids) == 1 and sids[0] == sid:
        return 'thuan_nhat'
    if sid in sids:
        return 'lan_can'
    return 'khong_lien_quan'


def _loai_trung_msgref(df: pd.DataFrame, log_fn) -> pd.DataFrame:
    """Phòng vệ cuối: loại dòng trùng MSGREF (mỗi giao dịch chỉ tính 1 lần)."""
    if 'MSGREF' not in df.columns or len(df) == 0:
        return df.reset_index(drop=True)
    truoc = len(df)
    df    = df.drop_duplicates(subset=['MSGREF'], keep='first')
    if len(df) < truoc:
        log_fn(f'[B3][WARN] Loại {truoc - len(df):,} dòng trùng MSGREF (nhiều sheet cùng chứa dữ '
                f'liệu 1 giao dịch) — giữ lại {len(df):,} dòng.')
    return df.reset_index(drop=True)


def _gop_gw_goc(sheets: dict) -> pd.DataFrame:
    """GW gốc (Requirement BR mới xử lý SESSION=NULL, 2026-07-23) — gộp TOÀN BỘ
    sheet đã đọc (chưa lọc session, chưa lọc PrcFlg, chưa xử lý làm sạch), chỉ giữ
    MSGREF + SessionId, dùng riêng để tra cứu SessionId thật của 1 MSGREF. Tái sử
    dụng `sheets` đã có sẵn trong bộ nhớ — không đọc file lần 2."""
    frames = [
        df[['MSGREF', 'SessionId']] for df in sheets.values()
        if 'MSGREF' in df.columns and 'SessionId' in df.columns
    ]
    if not frames:
        return pd.DataFrame(columns=['MSGREF', 'SessionId'])
    return pd.concat(frames, ignore_index=True)


def _chon_du_lieu_gw(sheets: dict, session_id: str, log_fn) -> pd.DataFrame:
    """Chọn dữ liệu GW đúng session_id từ các sheet đã đọc.

    Ưu tiên: sheet có SessionId THUẦN NHẤT khớp session mục tiêu — đọc riêng sheet
    đó, không đụng tới sheet khác (tránh đọc trùng dữ liệu khi 1 workbook có sheet
    tổng hợp nhiều session VÀ sheet lọc riêng cho từng ngày, như đã phát hiện ở file
    GW ngày 06-08/07/2026 — "Sheet 1" gộp 4 session, "đi GW <ngày>" chỉ 1 session).
    Fallback (chỉ khi KHÔNG có sheet thuần nhất nào): gộp dòng đúng session từ các
    sheet lẫn nhiều session, rồi loại trùng theo MSGREF.
    """
    thuan_nhat, lan_can = [], []
    for name, df in sheets.items():
        loai = _phan_loai_sheet_theo_session(df, session_id)
        if loai == 'thuan_nhat':
            thuan_nhat.append((name, df))
        elif loai == 'lan_can':
            lan_can.append((name, df))

    if len(thuan_nhat) == 1:
        name, df = thuan_nhat[0]
        log_fn(f'[B3] Chọn sheet "{name}" ({len(df):,} dòng) — SessionId thuần nhất = {session_id}, '
                f'không đọc/gộp sheet khác trong file.')
        return df.reset_index(drop=True)

    if len(thuan_nhat) > 1:
        names = [n for n, _ in thuan_nhat]
        log_fn(f'[B3][WARN] Có {len(thuan_nhat)} sheet cùng thuần nhất session {session_id}: '
                f'{names} — gộp lại và loại trùng theo MSGREF.')
        df = pd.concat([d for _, d in thuan_nhat], ignore_index=True)
        return _loai_trung_msgref(df, log_fn)

    if lan_can:
        names = [n for n, _ in lan_can]
        log_fn(f'[B3][WARN] Không tìm thấy sheet SessionId thuần nhất cho session {session_id} — '
                f'lọc dòng đúng session từ {len(lan_can)} sheet lẫn nhiều session ({names}) rồi '
                f'loại trùng theo MSGREF.')
        frames = []
        for _, df in lan_can:
            sid = str(session_id).strip()
            frames.append(df[df['SessionId'].astype(str).str.strip() == sid])
        df = pd.concat(frames, ignore_index=True)
        return _loai_trung_msgref(df, log_fn)

    log_fn(f'[B3][WARN] Không tìm thấy dữ liệu GW nào cho session {session_id} trong file.')
    cot_mau = next((df.columns for df in sheets.values() if 'SessionId' in df.columns), None)
    return pd.DataFrame(columns=cot_mau) if cot_mau is not None else pd.DataFrame()


def _doc_bang_fastexcel(xlsx_path: str, session_id: str, log_fn):
    import fastexcel
    wb          = fastexcel.read_excel(xlsx_path)
    sheet_names = wb.sheet_names
    log_fn(f'[B3][DIAG] fastexcel: {len(sheet_names)} sheet trong file, đang phân loại theo SessionId...')
    sheets = {}
    for name in sheet_names:
        raw_df = wb.load_sheet_by_name(name, header_row=None).to_pandas()
        sheets[name] = _xu_ly_sheet(raw_df.astype(str))
    return _chon_du_lieu_gw(sheets, session_id, log_fn), _gop_gw_goc(sheets)


def _doc_bang_calamine(xlsx_path: str, session_id: str, log_fn):
    all_sheets = pd.read_excel(xlsx_path, sheet_name=None, header=None,
                               dtype=str, engine='calamine')
    log_fn(f'[B3][DIAG] calamine: {len(all_sheets)} sheet trong file, đang phân loại theo SessionId...')
    sheets = {name: _xu_ly_sheet(df_raw) for name, df_raw in all_sheets.items()}
    return _chon_du_lieu_gw(sheets, session_id, log_fn), _gop_gw_goc(sheets)


def xu_ly_gw(xlsx_path: str, session_id: str, log_callback=None):
    """
    Đọc file GW Excel, trả về (dict_gw_count, df_gw_raw, df_gw_goc).
    dict_gw_count: {KEY_GW: count}  KEY_GW = str(BRCD) + str(STTLMAMT_int) — đã qua
      đủ 3 bước mục 3.1 (lọc session đúng, bỏ ACH từ chối, định dạng STTLMAMT).
    df_gw_goc: TOÀN BỘ sheet gộp lại (chưa lọc session/PrcFlg/làm sạch), chỉ có
      MSGREF + SessionId — dùng để tra cứu SessionId thật cho giao dịch SESSION=NULL
      (BR mới, xem `b4_xu_ly_mis_di.py::_loc_session_null_theo_gw_goc()`).
    """
    _log = log_callback or print
    _t   = time.perf_counter()
    try:
        df, df_gw_goc = _doc_bang_fastexcel(xlsx_path, session_id, _log)
        _log(f'[B3][DIAG] fastexcel total: {time.perf_counter()-_t:.1f}s')
    except ImportError:
        df, df_gw_goc = _doc_bang_calamine(xlsx_path, session_id, _log)
        _log(f'[B3][DIAG] calamine total: {time.perf_counter()-_t:.1f}s')

    # Bước 1 — session đúng (đã đảm bảo ở _chon_du_lieu_gw, lọc lại ở đây để phòng vệ)
    # + bỏ trạng thái ACH từ chối (PrcFlg).
    n_truoc          = len(df)
    mask_sai_session = df['SessionId'].astype(str).str.strip() != str(session_id)
    mask_tu_choi     = df['PrcFlg'].astype(str).str.strip() == 'ACH Từ chối'
    df = df[~mask_sai_session & ~mask_tu_choi].copy()
    # Audit 2026-08-04 — trước đây chỉ log tổng số dòng còn lại (dòng 176-177),
    # không tách được đóng góp của từng điều kiện lọc khi cần chẩn đoán.
    _log(f'[B3] Bước 1: loại {int(mask_sai_session.sum()):,} dòng sai session, '
         f'{int((mask_tu_choi & ~mask_sai_session).sum()):,} dòng "ACH Từ chối" '
         f'(giữ {len(df):,}/{n_truoc:,} dòng)')

    # Bước 2 — định dạng lại STTLMAMT (bỏ chữ VND, ra số). Chỉ xoá 'VND'/khoảng
    # trắng ở đây — GIỮ dấu phẩy/chấm ngăn-nghìn để doc_so_tien() tự validate,
    # xoá sớm quá sẽ mất khả năng bắt lỗi thật (mẫu lạ ngoài 3 dạng chấp nhận).
    df['STTLMAMT'] = (
        df['STTLMAMT'].astype(str)
        .str.replace(r'[VND\s]', '', regex=True)
    )
    df['STTLMAMT'] = doc_so_tien(df['STTLMAMT'], nguon='GW', ten_cot='STTLMAMT')

    # Bước 3 — tạo cột CN TIỀN = BRCD + STTLMAMT.
    df['KEY_GW'] = df['BRCD'].astype(str).str.strip() + df['STTLMAMT'].astype(str)

    dict_gw_count = df['KEY_GW'].value_counts().to_dict()
    _log(f'[B3] GW | {len(df):,} dòng (session {session_id}) | {len(dict_gw_count):,} KEY_GW unique | '
         f'GW gốc (chưa lọc): {len(df_gw_goc):,} dòng')
    return dict_gw_count, df.reset_index(drop=True), df_gw_goc.reset_index(drop=True)
