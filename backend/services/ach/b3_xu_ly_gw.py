import os
import time
import pandas as pd


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


def _doc_bang_fastexcel(xlsx_path: str, log_fn) -> pd.DataFrame:
    import fastexcel
    stem       = os.path.splitext(os.path.basename(xlsx_path))[0]
    wb         = fastexcel.read_excel(xlsx_path)
    sheet_names = wb.sheet_names
    target     = stem if stem in sheet_names else None

    if target:
        log_fn(f'[B3][DIAG] fastexcel: chỉ đọc sheet "{target}" (1/{len(sheet_names)} sheets)')
        raw_df = wb.load_sheet_by_name(target, header_row=None).to_pandas()
        return _xu_ly_sheet(raw_df.astype(str))
    else:
        log_fn(f'[B3][DIAG] fastexcel: đọc tất cả {len(sheet_names)} sheets')
        frames = []
        for name in sheet_names:
            raw_df = wb.load_sheet_by_name(name, header_row=None).to_pandas()
            frames.append(_xu_ly_sheet(raw_df.astype(str)))
        return pd.concat(frames, ignore_index=True)


def _doc_bang_calamine(xlsx_path: str, log_fn) -> pd.DataFrame:
    all_sheets = pd.read_excel(xlsx_path, sheet_name=None, header=None,
                               dtype=str, engine='calamine')
    log_fn(f'[B3][DIAG] calamine: đọc {len(all_sheets)} sheets')
    frames = [_xu_ly_sheet(df_raw) for df_raw in all_sheets.values()]
    return pd.concat(frames, ignore_index=True)


def xu_ly_gw(xlsx_path: str, session_id: str, log_callback=None):
    """
    Đọc file GW Excel, trả về (dict_gw_count, df_gw_raw).
    dict_gw_count: {KEY_GW: count}  KEY_GW = str(BRCD) + str(STTLMAMT_int)
    """
    _log = log_callback or print
    _t   = time.perf_counter()
    try:
        df = _doc_bang_fastexcel(xlsx_path, _log)
        _log(f'[B3][DIAG] fastexcel total: {time.perf_counter()-_t:.1f}s')
    except ImportError:
        df = _doc_bang_calamine(xlsx_path, _log)
        _log(f'[B3][DIAG] calamine total: {time.perf_counter()-_t:.1f}s')

    if 'MSGREF' in df.columns:
        df = df.drop_duplicates(subset=['MSGREF'])

    mask = (
        (df['SessionId'].astype(str).str.strip() == str(session_id)) &
        (df['PrcFlg'].astype(str).str.strip() != 'ACH Từ chối')
    )
    df = df[mask].copy()

    df['STTLMAMT'] = (
        df['STTLMAMT'].astype(str)
        .str.replace(r'[VND,\s]', '', regex=True)
    )
    df['STTLMAMT'] = pd.to_numeric(df['STTLMAMT'], errors='coerce').fillna(0).astype('int64')
    df['KEY_GW']   = df['BRCD'].astype(str).str.strip() + df['STTLMAMT'].astype(str)

    dict_gw_count = df['KEY_GW'].value_counts().to_dict()
    _log(f'[B3] GW | {len(df):,} dòng (session {session_id}) | {len(dict_gw_count):,} KEY_GW unique')
    return dict_gw_count, df.reset_index(drop=True)
