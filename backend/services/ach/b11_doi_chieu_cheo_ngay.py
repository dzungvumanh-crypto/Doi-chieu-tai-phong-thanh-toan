import pandas as pd

from .b4_xu_ly_mis_di import _chuan_hoa_co_ban, _them_cot_khoa
from .osb_common import la_lenh_osb_di, la_lenh_osb_den

GHI_CHU_T2 = 'Hạch toán lệnh ngày T-2'

# Cột bắt buộc phải có trong file MIS thừa T-2 (đúng schema chương trình tự xuất
# ra — _COLS_MIS_DI/_COLS_MIS_DEN ở pipeline.py) để tính lại khóa đối chiếu.
_COLS_BAT_BUOC_DI  = ['CHI_NHANH', 'SO_TIEN', 'TRACE', 'SE_TRACE', 'NGAY_KENH_TRA', 'LOAI_LENH_OSB']
_COLS_BAT_BUOC_DEN = ['CHI_NHANH', 'SO_TIEN', 'TRACE', 'LOAI_LENH_OSB']


def _doc_file_thua_t2(path: str, cols_bat_buoc: list, nhan: str) -> pd.DataFrame:
    """Đọc file MIS thừa T-2 — chấp nhận CẢ 2 loại: `.csv` chương trình tự xuất
    (sheet quá `CSV_THRESHOLD`) LẪN `.xlsx` do người chấm tự sửa tay rồi lưu lại
    (2026-08-03, Business Owner cần dùng khi kết quả chương trình tự xuất bị sai,
    phải nạp lại file đã chỉnh). `dtype=str` cho cả 2 nhánh để giữ đúng hành vi
    cột số/mã tham chiếu dạng chuỗi như trước (tránh Excel tự suy ra kiểu số/ngày
    làm hỏng TRACE/SE_TRACE khi tính lại khóa đối chiếu)."""
    if path.lower().endswith('.csv'):
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', low_memory=False)
    else:
        df = pd.read_excel(path, dtype=str, engine='calamine')
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in cols_bat_buoc if c not in df.columns]
    if missing:
        raise ValueError(f'File {nhan} T-2 thiếu cột {missing} — có thể bị sửa cấu trúc: {path}')
    return df


def doc_mis_di_thua_t2(path: str) -> pd.DataFrame:
    """Đọc file MIS_đi thừa T-2 — file chương trình tự xuất (`.csv`) hoặc file
    người chấm tự sửa tay rồi lưu lại (`.xlsx`, tên bắt đầu bằng "MIS đi thừa") —
    chỉ validate đúng cấu trúc cột, không parser mới."""
    return _doc_file_thua_t2(path, _COLS_BAT_BUOC_DI, 'MIS_đi thừa')


def doc_mis_den_thua_t2(path: str) -> pd.DataFrame:
    """Đọc file MIS_đến thừa T-2 — file chương trình tự xuất (`.csv`) hoặc file
    người chấm tự sửa tay rồi lưu lại (`.xlsx`, tên bắt đầu bằng "MIS đến thừa") —
    chỉ validate đúng cấu trúc cột, không parser mới."""
    return _doc_file_thua_t2(path, _COLS_BAT_BUOC_DEN, 'MIS_đến thừa')


def danh_dau_da_can_di(df_npo_di_thua: pd.DataFrame, df_mis_di_thua_t2: pd.DataFrame | None,
                       log_callback=None) -> pd.DataFrame:
    """Điểm 4 (2026-07-31, Implementation-notes.html mục 58) — đối chiếu chéo ngày
    chiều đi: MIS_đi thừa (T-2) ⟷ NPO_đi thừa (T-1, chính là `df_npo_di_thua`
    truyền vào — đã qua Điểm 3, chỉ còn phần thật sự chưa giải thích được).

    Ghép khóa KEY_DI (NPO)/KEY_HUB (MIS) — công thức có sẵn, không tạo khóa mới.
    Loại bỏ lệnh OSB khỏi MIS T-2 TRƯỚC khi so khớp (lệnh OSB không bao giờ khớp
    NPO qua khóa từng-giao-dịch — khác bản chất với lệch ngày do phiên, xem mục
    56/58) — không dựa vào việc mẫu dữ liệu tình cờ không có OSB nào khớp chéo.

    KHÔNG xoá/tách dòng khỏi `df_npo_di_thua` — chỉ thêm cột `GHI_CHU_T2` ('Hạch
    toán lệnh ngày T-2' cho dòng khớp, rỗng cho dòng còn lại/không có file T-2).
    """
    _log = log_callback or print
    df = df_npo_di_thua.copy()
    df['GHI_CHU_T2'] = ''

    if df_mis_di_thua_t2 is None or len(df_mis_di_thua_t2) == 0:
        return df

    # File T-2 do chương trình tự xuất đã có sẵn 'CN tiền Hub' (nằm trong
    # _COLS_MIS_DI) — bỏ đi trước khi gọi lại `_them_cot_khoa()` (hàm này tự
    # insert cột mới, lỗi nếu cột đã tồn tại).
    mis = _chuan_hoa_co_ban(df_mis_di_thua_t2.drop(columns=['CN tiền Hub'], errors='ignore'))
    mis = mis[~la_lenh_osb_di(mis)]
    mis = _them_cot_khoa(mis)
    keys_t2 = set(mis['KEY_HUB'])

    mask = df['KEY_DI'].isin(keys_t2)
    df.loc[mask, 'GHI_CHU_T2'] = GHI_CHU_T2

    _log(
        f'[B11][Điểm 4] Chiều đi: {int(mask.sum()):,}/{len(df):,} dòng NPO_đi thừa '
        f'khớp MIS_đi thừa T-2 (đã loại lệnh OSB khỏi input T-2)'
    )
    return df


def _them_key_den_hub_tu_thua(df: pd.DataFrame) -> pd.DataFrame:
    """Tính lại KEY_DEN_HUB từ file MIS_đến thừa T-2 — đúng công thức
    `b6_xu_ly_mis_den.py::xu_ly_mis_den()` (CHI_NHANH + TRACE(lstrip '0) + SO_TIEN),
    không viết thuật toán khóa mới."""
    df = df.copy()
    df['SO_TIEN'] = pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).astype('int64')
    trace = df['TRACE'].fillna('').astype(str).str.strip().str.lstrip("'0")
    df['KEY_DEN_HUB'] = df['CHI_NHANH'].astype(str).str.strip() + trace + df['SO_TIEN'].astype(str)
    return df


def danh_dau_da_can_den(df_npo_den_thua: pd.DataFrame, df_mis_den_thua_t2: pd.DataFrame | None,
                        log_callback=None) -> pd.DataFrame:
    """Điểm 4, chiều đến — đối xứng hoàn toàn với `danh_dau_da_can_di()`, chỉ đổi
    khóa/cột: KEY_DEN (NPO)/KEY_DEN_HUB (MIS), lọc OSB theo `la_lenh_osb_den()`."""
    _log = log_callback or print
    df = df_npo_den_thua.copy()
    df['GHI_CHU_T2'] = ''

    if df_mis_den_thua_t2 is None or len(df_mis_den_thua_t2) == 0:
        return df

    mis = df_mis_den_thua_t2[~la_lenh_osb_den(df_mis_den_thua_t2)]
    mis = _them_key_den_hub_tu_thua(mis)
    keys_t2 = set(mis['KEY_DEN_HUB'])

    mask = df['KEY_DEN'].isin(keys_t2)
    df.loc[mask, 'GHI_CHU_T2'] = GHI_CHU_T2

    _log(
        f'[B11][Điểm 4] Chiều đến: {int(mask.sum()):,}/{len(df):,} dòng NPO_đến thừa '
        f'khớp MIS_đến thừa T-2 (đã loại lệnh OSB khỏi input T-2)'
    )
    return df
