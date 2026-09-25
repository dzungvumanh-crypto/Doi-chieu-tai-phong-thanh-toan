"""Mục 3 (bổ sung 11.09.2026, Thảo xác nhận ưu tiên làm 16.09.2026) — module riêng,
độc lập với đối chiếu ACH chính: đối chiếu file "pHub_Danh sách giao dịch chuyển
tiền đi" (điện pHub báo lỗi/chưa rõ trạng thái) với GW đi (để xác nhận đã thực sự
"Hoàn thành") và với "TO ko đi kênh" (để tìm "TT lệnh lỗi ngày T").

Cấu trúc file pHub thật (xác nhận từ mẫu G:\\NGUYEN TAC DOI CHIEU ACH\\04-06.09\\
pHub_Danh sach giao dich chuyen tien di_20260914.xlsx, 16.09.2026): dòng đầu là ô
tiêu đề gộp "DANH SÁCH GIAO DỊCH CHUYÊN TIỀN ĐI", dòng kế mới là header thật (có
cột 'Số thành công') — dò header theo nội dung, không hard-code offset dòng, đúng
tinh thần `_xu_ly_sheet()` ở b3_xu_ly_gw.py.

'Số thành công' (pHub) cùng định dạng/giá trị với 'MSGREF' (GW đi) — xác nhận bằng
đối chiếu dữ liệu thật (VD '0200970405090409451220260000168283'), không suy đoán
từ tên cột. GW đi thật có cột 'Ghi chú' chứa chuỗi dạng
'ACSP:AUTH:AUTH:/AIR/168283;/FAI/...' — Thảo xác nhận so khớp 3 mã ACSP:NOAN/
ACSP:AUTH/ACSC:AUTH bằng "chứa" (contains), không phải so khớp tuyệt đối cả chuỗi.
"""
import pandas as pd

from .b3_xu_ly_gw import _xu_ly_sheet, _chon_du_lieu_gw
from .b4_xu_ly_mis_di import _tao_so_trace

_MA_DA_XU_LY = ('ACSP:NOAN', 'ACSP:AUTH', 'ACSC:AUTH')

_COT_CAN_THIET_PHUB = ['Chi nhánh', 'Số thành công', 'Số Trace 2', 'Số tiền thực chuyển']


def doc_phub(xlsx_path: str, log_callback=None) -> pd.DataFrame:
    """Đọc 1 file pHub, dò header theo nội dung (cột 'Số thành công')."""
    _log = log_callback or print
    raw = pd.read_excel(xlsx_path, header=None, dtype=str, engine='calamine')

    header_row = None
    for i, row in raw.iterrows():
        if 'Số thành công' in row.values:
            header_row = i
            break
    if header_row is None:
        raise ValueError(
            f"[B16] Không tìm thấy dòng header (cột 'Số thành công') trong file pHub: {xlsx_path}"
        )

    df = raw.iloc[header_row + 1:].reset_index(drop=True)
    df.columns = [str(c).strip() for c in raw.iloc[header_row]]
    if 'STT' in df.columns:
        df = df[df['STT'].notna()].reset_index(drop=True)

    thieu = [c for c in _COT_CAN_THIET_PHUB if c not in df.columns]
    if thieu:
        raise ValueError(f"[B16] File pHub thiếu cột {thieu}: {xlsx_path}")

    df['Số thành công'] = df['Số thành công'].astype(str).str.strip().str.lstrip("'")
    _log(f"[B16][Mục 3] Đọc {len(df):,} dòng từ file pHub: {xlsx_path}")
    return df


def doc_gw_di_cho_phub(xlsx_path: str, session_id: str, log_callback=None) -> pd.DataFrame:
    """Đọc lại GW đi RIÊNG cho pHub — chỉ giữ MSGREF + Ghi chú, đúng session, KHÔNG
    lọc PrcFlg 'ACH Từ chối' như `b3_xu_ly_gw.xu_ly_gw()`: 1 điện pHub báo lỗi hoàn
    toàn có thể khớp MSGREF với 1 dòng GW bị từ chối — vẫn cần thấy để đi đúng
    nhánh (Ghi chú của dòng bị từ chối sẽ không chứa mã ACSP/ACSC nên tự nhiên rơi
    xuống Bước 3-6, không cần lọc trước)."""
    _log = log_callback or print
    all_sheets = pd.read_excel(xlsx_path, sheet_name=None, header=None,
                                dtype=str, engine='calamine')
    sheets = {name: _xu_ly_sheet(df_raw) for name, df_raw in all_sheets.items()}
    df = _chon_du_lieu_gw(sheets, session_id, _log)

    if 'Ghi chú' not in df.columns:
        raise ValueError(f"[B16] File GW đi thiếu cột 'Ghi chú': {xlsx_path}")

    df = df[['MSGREF', 'Ghi chú']].copy()
    df['MSGREF']  = df['MSGREF'].astype(str).str.strip().str.lstrip("'")
    df['Ghi chú'] = df['Ghi chú'].fillna('').astype(str)
    return df.reset_index(drop=True)


def _tao_cn_trace_tien_phub(df: pd.DataFrame) -> pd.Series:
    """Bước 3 văn bản — SỐ TRACE = Số Trace 2 (bỏ số 0 đầu). CN trace tiền = Chi
    nhánh + SỐ TRACE + Số tiền thực chuyển."""
    so_trace  = df['Số Trace 2'].fillna('').astype(str).str.strip().str.lstrip("'0")
    chi_nhanh = df['Chi nhánh'].fillna('').astype(str).str.strip()
    so_tien   = df['Số tiền thực chuyển'].fillna('').astype(str).str.strip()
    return chi_nhanh + so_trace + so_tien


def _tao_cn_trace_tien_timeout(df: pd.DataFrame) -> pd.Series:
    """Bước 4 văn bản — SỐ TRACE ưu tiên SE_TRACE, rỗng thì TRACE (tái dùng
    `_tao_so_trace()` từ b4_xu_ly_mis_di.py — cùng luật, không viết lại). CN trace
    tiền = CHI_NHANH + SỐ TRACE + SO_TIEN."""
    so_trace  = _tao_so_trace(df)
    chi_nhanh = df['CHI_NHANH'].fillna('').astype(str).str.strip()
    so_tien   = df['SO_TIEN'].fillna('').astype(str).str.strip()
    return chi_nhanh + so_trace + so_tien


def xu_ly_phub_loi(df_phub: pd.DataFrame, df_gw: pd.DataFrame, df_timeout: pd.DataFrame,
                    log_callback=None) -> pd.DataFrame:
    """Gộp Bước 1-6 văn bản. Trả về df_phub gốc (giữ nguyên thứ tự dòng) kèm cột
    TRANG_THAI_CAP_NHAT ∈ {'Hoàn thành', 'TT lệnh lỗi ngày T', 'Trạng thái khác'}.
    """
    _log = log_callback or print
    df = df_phub.copy()

    # Bước 2 — map Số thành công (pHub) ↔ MSGREF (GW đi); nhiều dòng GW có thể
    # trùng MSGREF hiếm gặp (nhiều sheet) nên gộp Ghi chú bằng '|' trước khi soát.
    ghi_chu_theo_msgref = df_gw.groupby('MSGREF')['Ghi chú'].apply('|'.join).to_dict()
    ghi_chu_khop     = df['Số thành công'].map(ghi_chu_theo_msgref).fillna('')
    mask_hoan_thanh  = ghi_chu_khop.apply(lambda s: any(ma in s for ma in _MA_DA_XU_LY))

    # Bước 3-6 — chỉ cần tính cho toàn bộ (mask sẽ tự loại phần đã 'Hoàn thành').
    cn_trace_tien_phub = _tao_cn_trace_tien_phub(df)
    keys_timeout        = frozenset(_tao_cn_trace_tien_timeout(df_timeout))
    mask_loi             = cn_trace_tien_phub.isin(keys_timeout)

    df['TRANG_THAI_CAP_NHAT'] = 'Trạng thái khác'
    df.loc[~mask_hoan_thanh & mask_loi, 'TRANG_THAI_CAP_NHAT'] = 'TT lệnh lỗi ngày T'
    df.loc[mask_hoan_thanh, 'TRANG_THAI_CAP_NHAT']             = 'Hoàn thành'

    _log(
        f'[B16][Mục 3] Hoàn thành: {int(mask_hoan_thanh.sum()):,} | '
        f'TT lệnh lỗi ngày T: {int((~mask_hoan_thanh & mask_loi).sum()):,} | '
        f'Trạng thái khác: {int((~mask_hoan_thanh & ~mask_loi).sum()):,} / tổng {len(df):,}'
    )
    return df
