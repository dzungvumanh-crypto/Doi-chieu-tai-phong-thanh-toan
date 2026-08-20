import pandas as pd

from .b5_doi_chieu_di import _doi_chieu
from .osb_common import la_lenh_osb_di, la_lenh_osb_den
from .so_tien import doc_so_tien

# Cột bắt buộc phải có trong file QT (Quyết toán OSB) — dò header theo nội dung,
# không phụ thuộc vị trí cột (đã verify: số cột phụ không tên trước 'Seq' lệch
# giữa các file/chiều — xem Implementation-notes.html mục 63b).
_COLS_BAT_BUOC_QT = ['Chiều giao dịch', 'CN thực hiện', 'Mã giao dịch', 'Số tiền']


def _tim_header_row(df_raw: pd.DataFrame) -> int | None:
    """Tìm dòng header — có cả 'STT' và 'Số tiền' (đúng pattern _xu_ly_sheet() ở
    b3_xu_ly_gw.py, dò theo nội dung thay vì cố định vị trí dòng). None nếu sheet
    này không có (VD sheet 'Config' phụ trong file QT thật — không phải dữ liệu)."""
    for i, row in df_raw.iterrows():
        vals = set(row.values)
        if 'STT' in vals and 'Số tiền' in vals:
            return i
    return None


def _xu_ly_sheet_qt(df_raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    df = df_raw.iloc[header_row + 1:].reset_index(drop=True)
    raw_cols = [str(c).strip() if c is not None else '' for c in df_raw.iloc[header_row]]
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


def _doc_sheet_du_lieu_qt(path: str) -> pd.DataFrame:
    """File QT thật có ≥2 sheet (VD 'Config' tham chiếu mã CN + 'Sheet 1' dữ liệu
    thật) — dò TOÀN BỘ sheet theo nội dung (không cố định 'Sheet 1'/vị trí 0),
    lấy đúng sheet có header 'STT'+'Số tiền'. Báo lỗi rõ nếu không sheet nào khớp
    hoặc có ≥2 sheet cùng khớp (không tự chọn theo vị trí)."""
    all_sheets = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine='calamine')
    ung_vien = []
    for name, df_raw in all_sheets.items():
        header_row = _tim_header_row(df_raw)
        if header_row is not None:
            ung_vien.append((name, df_raw, header_row))

    if not ung_vien:
        raise ValueError(f"Không tìm thấy sheet dữ liệu (cần có cả 'STT' và 'Số tiền') trong file QT: {path}")
    if len(ung_vien) > 1:
        names = [n for n, _, _ in ung_vien]
        raise ValueError(f"Có nhiều hơn 1 sheet dữ liệu hợp lệ trong file QT — không tự chọn: {names} ({path})")

    _, df_raw, header_row = ung_vien[0]
    return _xu_ly_sheet_qt(df_raw, header_row)


def xu_ly_qt(path: str, log_callback=None):
    """Đọc 1 file QT (Quyết toán OSB — đi hoặc đến, tự phân loại theo nội dung).

    Tính lại khóa `CN_TRACE_TIEN` = mã CN thực hiện + Mã giao dịch (bỏ số 0 đầu) +
    Số tiền — ĐÚNG công thức đã dùng bên MIS (`KEY_HUB`/`KEY_DEN_HUB`). File QT có
    sẵn 1 cột không tên trùng giá trị (đã verify 100% trên 3 ngày dữ liệu thật) —
    CỐ Ý không dùng cột đó vì vị trí lệch giữa các file/chiều và không có nhãn xác
    nhận đúng ý nghĩa nghiệp vụ; tự tính lại từ cột có nhãn rõ ràng an toàn hơn.

    'Kiểu giao dịch'='Cancel' (chỉ thấy ở QT đi, Số tiền âm) — GIỮ NGUYÊN, không
    lọc riêng (Business Owner xác nhận 2026-07-31): số tiền âm tự nhiên không khớp
    được key dương bên MIS, không cần xử lý đặc biệt.

    Trả về (chiều, df) — chiều là 'đi' hoặc 'đến'.
    """
    _log = log_callback or print
    df = _doc_sheet_du_lieu_qt(path)

    missing = [c for c in _COLS_BAT_BUOC_QT if c not in df.columns]
    if missing:
        raise ValueError(f'File QT thiếu cột {missing} — có thể sai định dạng: {path}')

    chieu_gd = [
        c for c in df['Chiều giao dịch'].astype(str).str.strip().unique()
        if c and c.lower() != 'nan'
    ]
    if len(chieu_gd) != 1 or chieu_gd[0] not in ('GD đi', 'GD về'):
        raise ValueError(
            f"File QT phải chỉ chứa đúng 1 giá trị 'Chiều giao dịch' (GD đi hoặc GD về), "
            f"tìm thấy {chieu_gd}: {path}"
        )
    chieu = 'đi' if chieu_gd[0] == 'GD đi' else 'đến'

    df = df.copy()
    ma_cn = df['CN thực hiện'].astype(str).str.strip().str.extract(r'^(\d+)', expand=False)
    if ma_cn.isna().any():
        raise ValueError(f"Cột 'CN thực hiện' có giá trị không đúng định dạng '<mã CN> - <tên>': {path}")
    trace   = df['Mã giao dịch'].astype(str).str.strip().str.lstrip('0')

    df['SO_TIEN']       = doc_so_tien(df['Số tiền'], path, ten_cot="'Số tiền'")
    df['CN_TRACE_TIEN'] = ma_cn + trace + df['SO_TIEN'].astype(str)

    _log(f"[B9] QT {chieu}: {len(df):,} dòng ({path})")
    return chieu, df.reset_index(drop=True)


def _gan_nguon(df: pd.DataFrame, nguon: str) -> pd.DataFrame:
    df = df.copy()
    df['NGUON'] = nguon
    return df


def doi_chieu_osb_di(df_mis_di_thua: pd.DataFrame, df_qt_di: pd.DataFrame, log_callback=None):
    """Tách lệnh OSB khỏi MIS_đi thừa, đối chiếu với QT đi qua CN_TRACE_TIEN (tái
    dùng `_doi_chieu()` có sẵn). Trả về (df_da_quyet_toan, df_chua_khop) — vế 2 gộp
    cả phần OSB-MIS chưa khớp lẫn phần QT chưa khớp, phân biệt bằng cột NGUON."""
    _log = log_callback or print
    osb = df_mis_di_thua[la_lenh_osb_di(df_mis_di_thua)].copy() if len(df_mis_di_thua) else df_mis_di_thua
    mis_khop, qt_khop, mis_thua, qt_thua = _doi_chieu(
        osb, 'KEY_HUB', df_qt_di, 'CN_TRACE_TIEN', 'B9-OSB-DI', log_callback,
    )
    df_chua_khop = pd.concat(
        [_gan_nguon(mis_thua, 'MIS'), _gan_nguon(qt_thua, 'QT')], ignore_index=True, sort=False,
    )
    _log(f'[B9][Điểm 2] OSB đi: {len(mis_khop):,} lệnh MIS đã quyết toán khớp QT, '
         f'{len(df_chua_khop):,} dòng chưa khớp (cả 2 nguồn)')
    return mis_khop.reset_index(drop=True), df_chua_khop.reset_index(drop=True)


def doi_chieu_osb_den(df_mis_den_thua: pd.DataFrame, df_qt_den: pd.DataFrame, log_callback=None):
    """Đối xứng `doi_chieu_osb_di()` — chiều đến, khóa KEY_DEN_HUB."""
    _log = log_callback or print
    osb = df_mis_den_thua[la_lenh_osb_den(df_mis_den_thua)].copy() if len(df_mis_den_thua) else df_mis_den_thua
    mis_khop, qt_khop, mis_thua, qt_thua = _doi_chieu(
        osb, 'KEY_DEN_HUB', df_qt_den, 'CN_TRACE_TIEN', 'B9-OSB-DEN', log_callback,
    )
    df_chua_khop = pd.concat(
        [_gan_nguon(mis_thua, 'MIS'), _gan_nguon(qt_thua, 'QT')], ignore_index=True, sort=False,
    )
    _log(f'[B9][Điểm 2] OSB đến: {len(mis_khop):,} lệnh MIS đã quyết toán khớp QT, '
         f'{len(df_chua_khop):,} dòng chưa khớp (cả 2 nguồn)')
    return mis_khop.reset_index(drop=True), df_chua_khop.reset_index(drop=True)
