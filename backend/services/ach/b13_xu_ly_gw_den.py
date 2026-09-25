"""Mục 4 (bổ sung 11.09.2026) — đối chiếu file "đến_GW" (chiều ĐẾN, khác hẳn
b3_xu_ly_gw.py xử lý GW ĐI) với MIS_đến qua TXID/MSGREF.

File "đến_GW" thường có nhiều sheet, header dò theo nội dung có 'BRCD' — dùng lại
`_xu_ly_sheet()` từ b3_xu_ly_gw.py, KHÔNG viết lại logic dò header. KHÔNG được coi
sheet đầu tiên có đủ cột 'BRCD'+'Session ID' là sheet đúng (bug thật phát hiện
14.09.2026 — file ngày 05.09 có 2 sheet cùng đủ 2 cột đó: Sheet 1 = 1.000.000 dòng
GỘP NHIỀU SESSION/NHIỀU NGÀY, Sheet 2 = 143.453 dòng THUẦN 1 session đúng ngày. Lọc
theo session trên Sheet 1 vẫn ra sai số vì Sheet 1 không phải bản sao sạch của
Sheet 2). Dùng lại `_chon_du_lieu_gw()`/`_phan_loai_sheet_theo_session()` từ
b3_xu_ly_gw.py — logic này đã giải đúng bẫy y hệt cho file GW đi (ưu tiên sheet
"thuần nhất" đúng 1 session, chỉ fallback lọc+dedup khi không có sheet thuần nhất).

LƯU Ý CỘT SESSION: file đến_GW dùng tên cột 'Session ID' (CÓ khoảng trắng), KHÁC
'SessionId' (liền) của file GW đi — đọc nhầm cột sẽ luôn ra "không có dữ liệu" mà
không lỗi nào báo. Truyền `session_col='Session ID'` cho các hàm dùng chung này.

Đối chiếu dùng lại `_doi_chieu()` (đối chiếu theo count, vectorized) từ
b5_doi_chieu_di.py — KHÔNG viết thuật toán khớp mới.
"""
import pandas as pd

from .b3_xu_ly_gw import _xu_ly_sheet, _phan_loai_sheet_theo_session, _chon_du_lieu_gw, _loai_trung_msgref
from .b5_doi_chieu_di import _doi_chieu
from .so_tien import doc_so_tien

# PrcFlg giữ lại theo yêu cầu nghiệp vụ Mục 4 — bỏ 'Đã từ chối' và mọi giá trị khác.
_PRC_FLG_GIU = {'Đã treo', 'Đã trả KH'}


def xu_ly_gw_den(xlsx_path: str, session_id: str, log_callback=None) -> pd.DataFrame:
    """Đọc file đến_GW, lọc PrcFlg ∈ {'Đã treo', 'Đã trả KH'} và Session ID đúng
    session đang đối chiếu. Trả về DataFrame đã lọc, cột STTLMAMT đã ép int64
    (qua `doc_so_tien()` — VND luôn số nguyên, không được dùng to_numeric() trần)."""
    _log = log_callback or print
    all_sheets = pd.read_excel(xlsx_path, sheet_name=None, header=None,
                               dtype=str, engine='calamine')

    # Làm sạch header từng sheet, chỉ giữ sheet có đủ cột dữ liệu (loại sheet tiêu
    # đề không có BRCD). Không chọn sheet đầu tiên tìm thấy ở đây — có thể có NHIỀU
    # sheet đủ cột (1 sheet thuần đúng session, 1 sheet trộn nhiều session/nhiều
    # ngày) — việc chọn đúng sheet giao cho `_chon_du_lieu_gw()` bên dưới.
    sheets = {}
    for name, df_raw in all_sheets.items():
        candidate = _xu_ly_sheet(df_raw)
        if 'BRCD' in candidate.columns and 'Session ID' in candidate.columns:
            sheets[name] = candidate
    if not sheets:
        raise ValueError(
            f"Không tìm thấy sheet dữ liệu (cần cột 'BRCD' và 'Session ID') trong "
            f"file đến_GW: {xlsx_path}"
        )
    _log(f'[B13][Mục 4] {len(sheets)} sheet có đủ cột BRCD + Session ID trong file đến_GW '
         f'({list(sheets.keys())}) — đang chọn đúng sheet cho session {session_id}.')

    df = _chon_du_lieu_gw(sheets, session_id, _log, session_col='Session ID')

    n_truoc  = len(df)
    mask_prc = df['PrcFlg'].astype(str).str.strip().isin(_PRC_FLG_GIU)
    df = df[mask_prc].copy()
    _log(f'[B13][Mục 4] GW đến: giữ {len(df):,}/{n_truoc:,} dòng đúng session {session_id} '
         f'(PrcFlg đúng {int(mask_prc.sum()):,}).')

    # STTLMAMT — cùng định dạng GW đi (có thể kèm 'VND'/khoảng trắng), bỏ trước khi
    # doc_so_tien() tự validate ngăn-nghìn (xem b3_xu_ly_gw.py::xu_ly_gw() Bước 2).
    df['STTLMAMT'] = df['STTLMAMT'].astype(str).str.replace(r'[VND\s]', '', regex=True)
    df['STTLMAMT'] = doc_so_tien(df['STTLMAMT'], nguon='GW_DEN', ten_cot='STTLMAMT')
    df['MSGREF']   = df['MSGREF'].astype(str).str.strip()

    return df.reset_index(drop=True)


def doi_chieu_gw_den(df_gw_den: pd.DataFrame, df_mis_den: pd.DataFrame, log_callback=None):
    """Đối chiếu TXID (MIS_đến, bóc dấu nháy đơn đầu nếu có) với MSGREF (GW đến).

    Trả về (df_khop, df_gw_den_thua, df_mis_den_thua):
    - df_khop        — phía MIS_đến của các dòng khớp đúng (giữ nguyên cột MIS_đến,
                        nhiều thông tin hơn phía GW — cùng quy ước với
                        doi_chieu_di()/doi_chieu_den() trả về phía MIS).
    - df_gw_den_thua  — dòng GW đến không có TXID tương ứng bên MIS_đến ("GW thừa").
    - df_mis_den_thua — dòng MIS_đến không có MSGREF tương ứng bên GW đến
                        ("MIS_đến thừa").
    """
    _log = log_callback or print
    mis = df_mis_den.copy()
    mis['TXID_SACH'] = mis['TXID'].astype(str).str.strip().str.lstrip("'")

    gw_khop, mis_khop, gw_thua, mis_thua = _doi_chieu(
        df_gw_den, 'MSGREF', mis, 'TXID_SACH', 'B13-GW-DEN', log_callback,
    )
    _log(f'[B13][Mục 4] Khớp đúng: {len(mis_khop):,} | GW thừa: {len(gw_thua):,} | '
         f'MIS_đến thừa: {len(mis_thua):,}')
    return (
        mis_khop.reset_index(drop=True),
        gw_thua.reset_index(drop=True),
        mis_thua.reset_index(drop=True),
    )
