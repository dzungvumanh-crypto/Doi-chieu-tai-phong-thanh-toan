"""B3 — Đọc file GW (Excel), lọc theo session, dựng KEY_GW để đếm slot kênh."""
import pandas as pd


def _doc_mot_sheet(xl: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """Đọc một sheet GW, tự phát hiện dòng header. Đọc 1 lần, không đọc lại."""
    df_raw = pd.read_excel(xl, sheet_name=sheet_name, header=None,
                           dtype=str, engine='calamine')
    header_row = 0
    for i, row in df_raw.iterrows():
        if 'BRCD' in row.values:
            header_row = i
            break
    df = df_raw.iloc[header_row + 1:].reset_index(drop=True)
    df.columns = [str(c).strip() for c in df_raw.iloc[header_row]]
    return df


def _sheet_co_session(xl: pd.ExcelFile, sheet_name: str, session_id: str) -> bool:
    """Peek 60 dòng đầu xem sheet có SessionId cần tìm không.

    File GW có thể chứa nhiều sheet của nhiều phiên; không peek thì mỗi lần chạy
    phải đọc cả triệu dòng của những sheet không liên quan.
    """
    try:
        df_peek = pd.read_excel(xl, sheet_name=sheet_name, header=None,
                                nrows=60, dtype=str, engine='calamine')
    except Exception:
        return False
    for i, row in df_peek.iterrows():
        if 'SessionId' in row.values:
            try:
                sid_idx = list(row).index('SessionId')
            except ValueError:
                return False
            data = df_peek.iloc[i + 1:, sid_idx].astype(str)
            return str(session_id) in data.values
    return False  # Không có cột SessionId → bỏ qua sheet này


def xu_ly_gw(xlsx_path: str, session_id: str, log_callback=None):
    """Đọc file GW → (dict_gw_count, df_gw_raw).

    dict_gw_count: {KEY_GW: số lần xuất hiện}, KEY_GW = BRCD + STTLMAMT (int).
    df_gw_raw: dữ liệu đầy đủ sau lọc, dùng để xuất sheet RAW_GW.
    """
    xl = pd.ExcelFile(xlsx_path, engine='calamine')

    matching = [s for s in xl.sheet_names if _sheet_co_session(xl, s, session_id)]
    if matching:
        frames = [_doc_mot_sheet(xl, s) for s in matching]
    else:
        # Fallback: peek không thấy thì đọc hết (an toàn hơn là trả rỗng)
        frames = [_doc_mot_sheet(xl, s) for s in xl.sheet_names]

    df = pd.concat(frames, ignore_index=True)

    # Bỏ bản ghi trùng theo MSGREF: xảy ra khi file GW có sheet phụ là bản sao
    # đã lọc của sheet chính (VD "di GW 12.06")
    if 'MSGREF' in df.columns:
        df = df.drop_duplicates(subset=['MSGREF'])

    # Lọc session và bỏ PrcFlg = 'ACH Từ chối' trong 1 bước
    mask = (
        (df['SessionId'].astype(str).str.strip() == str(session_id)) &
        (df['PrcFlg'].astype(str).str.strip() != 'ACH Từ chối')
    )
    df = df[mask].copy()

    # STTLMAMT: bỏ 'VND', dấu phẩy, khoảng trắng → int64
    df['STTLMAMT'] = (
        df['STTLMAMT'].astype(str).str.replace(r'[VND,\s]', '', regex=True)
    )
    df['STTLMAMT'] = pd.to_numeric(df['STTLMAMT'], errors='coerce').fillna(0).astype('int64')

    df['KEY_GW'] = df['BRCD'].astype(str).str.strip() + df['STTLMAMT'].astype(str)
    dict_gw_count = df['KEY_GW'].value_counts().to_dict()

    (log_callback or print)(
        f'[B3] GW | {len(df):,} dòng (session {session_id}) | '
        f'{len(dict_gw_count):,} KEY_GW duy nhất'
    )
    return dict_gw_count, df.reset_index(drop=True)
