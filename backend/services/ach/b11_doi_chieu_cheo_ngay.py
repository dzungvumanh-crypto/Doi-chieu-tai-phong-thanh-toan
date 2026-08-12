import pandas as pd

from .b4_xu_ly_mis_di import _chuan_hoa_co_ban, _them_cot_khoa
from .b5_doi_chieu_di import _doi_chieu
from .osb_common import la_lenh_osb_di, la_lenh_osb_den
from .so_tien import doc_so_tien

GHI_CHU_T2 = 'Hạch toán lệnh ngày T-2'

# Báo cáo "KẾT QUẢ" (theo file nghiệp vụ NGUYEN TAC DOI CHIEU DIEN MIS THUA NGAY
# T-1.docx, 2026-08-07) — góc nhìn NGƯỢC với GHI_CHU_T2 ở trên: gắn nhãn lên
# CHÍNH file MIS thừa T-2 thay vì lên NPO thừa T-1. Dòng OSB so với QT ngày T-1,
# dòng thường so với NPO thừa ngày T-1 — nguyên văn nhãn theo đúng docx.
KETQUA_OSB_DI_KHOP  = 'lệnh đi OSB ngày T-2 hạch toán QT ngày T-1'
KETQUA_OSB_DI_CHUA  = 'OSB đi chưa hạch toán'
KETQUA_OSB_DEN_KHOP = 'lệnh đến OSB ngày T-2 hạch toán QT ngày T-1'
KETQUA_OSB_DEN_CHUA = 'OSB đến chưa hạch toán'
KETQUA_KHONG_CO_QT  = 'Không có QT ngày T-1 để đối chiếu'
KETQUA_THUONG_KHOP  = 'lệnh ngày T-2 hạch toán ngày T-1'
KETQUA_THUONG_CHUA  = 'lệnh chưa hạch toán'

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
    làm hỏng TRACE/SE_TRACE khi tính lại khóa đối chiếu).

    2026-08-07 — phát hiện thật trên dữ liệu 03.08: người chấm mở `.csv` chương
    trình tự xuất bằng Excel rồi lưu lại, Excel tự đổi dấu phân cách phẩy → tab
    (giữ nguyên đuôi `.csv`) khiến `pd.read_csv()` mặc định gộp cả dòng thành 1
    cột, báo nhầm "thiếu cột". `sep=None, engine='python'` để tự dò dấu phân
    cách thay vì cố định dấu phẩy — không đổi hành vi với file gốc (phẩy) vẫn tự
    dò ra đúng phẩy, chỉ thêm khả năng chấp nhận tab."""
    if path.lower().endswith('.csv'):
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', sep=None, engine='python')
    else:
        df = pd.read_excel(path, dtype=str, engine='calamine')
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in cols_bat_buoc if c not in df.columns]
    if missing:
        raise ValueError(f'File {nhan} T-2 thiếu cột {missing} — có thể bị sửa cấu trúc: {path}')

    # ── Chuẩn hoá SO_TIEN ngay tại ranh giới đọc file (2026-08-11) ──
    # Cột này có thể mang định dạng ngăn nghìn ('180.000') tuỳ nguồn xuất và tuỳ
    # người chấm có mở ra sửa hay không. Xử lý ở đây để mọi nhánh phía sau
    # (`_chuan_hoa_co_ban()` chiều đi, `_them_key_den_hub_tu_thua()` chiều đến)
    # nhận được chuỗi số thuần như cũ — KHÔNG đụng vào `b4`/`b6` của luồng chính.
    df = df.copy()
    df['SO_TIEN'] = doc_so_tien(df['SO_TIEN'], f'{nhan} T-2: {path}', ten_cot='SO_TIEN').astype(str)
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


def _gan_ket_qua(mis: pd.DataFrame, key_mis: str, doi_tuong: pd.DataFrame | None, key_doi_tuong: str,
                 nhan_khop: str, nhan_chua: str, nhan_khong_co: str, label: str,
                 log_callback=None) -> pd.DataFrame:
    """Helper dùng chung cho cả 2 nhánh (OSB-vs-QT, thường-vs-NPO) của
    `ket_qua_mis_..._thua_t2()`. Trả về `mis` với cột `KET_QUA` gắn thêm, GIỮ ĐỦ
    toàn bộ dòng (không rơi dòng nào — chỉ đổi nhãn)."""
    _log = log_callback or print
    if len(mis) == 0:
        mis = mis.copy()
        mis['KET_QUA'] = pd.Series(dtype=str)
        return mis

    if doi_tuong is None:
        mis = mis.copy()
        mis['KET_QUA'] = nhan_khong_co
        _log(f'[B11][{label}] {len(mis):,} dòng — không có dữ liệu đối chiếu, gán "{nhan_khong_co}"')
        return mis

    _, mis_khop, _, mis_thua = _doi_chieu(doi_tuong, key_doi_tuong, mis, key_mis, label, log_callback)
    mis_khop = mis_khop.copy(); mis_khop['KET_QUA'] = nhan_khop
    mis_thua = mis_thua.copy(); mis_thua['KET_QUA'] = nhan_chua
    _log(f'[B11][{label}] {len(mis_khop):,}/{len(mis):,} dòng khớp ("{nhan_khop}")')
    return pd.concat([mis_khop, mis_thua], ignore_index=True, sort=False)


def ket_qua_mis_di_thua_t2(df_mis_di_thua_t2: pd.DataFrame | None, df_qt_di: pd.DataFrame | None,
                           df_npo_di_thua: pd.DataFrame, log_callback=None) -> pd.DataFrame | None:
    """Báo cáo "KẾT QUẢ" chiều đi (docx NGUYEN TAC DOI CHIEU DIEN MIS THUA NGAY
    T-1) — gắn cột KET_QUA lên CHÍNH file MIS_đi thừa T-2, tách theo LOAI_LENH_OSB:
    dòng OSB ('O') so với QT đi ngày T-1 (khoá CN_TRACE_TIEN — đã tính sẵn trong
    df_qt_di, xem `xu_ly_qt()`), dòng thường so với NPO_đi thừa ngày T-1 (khoá
    KEY_DI, đã có sẵn trong df_npo_di_thua). `df_qt_di=None` (file QT tùy chọn,
    không nạp) → dòng OSB nhận nhãn riêng biệt KETQUA_KHONG_CO_QT, KHÔNG gộp
    chung với "chưa hạch toán" (tránh hiểu lầm đã kiểm tra mà không khớp).

    Trả None nếu không có file MIS thừa T-2 (không có gì để báo cáo)."""
    if df_mis_di_thua_t2 is None or len(df_mis_di_thua_t2) == 0:
        return None

    mis = _them_cot_khoa(_chuan_hoa_co_ban(df_mis_di_thua_t2.drop(columns=['CN tiền Hub'], errors='ignore')))
    mis_osb    = mis[la_lenh_osb_di(mis)].copy()
    mis_thuong = mis[~la_lenh_osb_di(mis)].copy()

    ket_qua_osb = _gan_ket_qua(
        mis_osb, 'KEY_HUB', df_qt_di, 'CN_TRACE_TIEN',
        KETQUA_OSB_DI_KHOP, KETQUA_OSB_DI_CHUA, KETQUA_KHONG_CO_QT, 'KetQua-OSB-Di', log_callback,
    )
    ket_qua_thuong = _gan_ket_qua(
        mis_thuong, 'KEY_HUB', df_npo_di_thua, 'KEY_DI',
        KETQUA_THUONG_KHOP, KETQUA_THUONG_CHUA, KETQUA_THUONG_CHUA, 'KetQua-Thuong-Di', log_callback,
    )
    return pd.concat([ket_qua_osb, ket_qua_thuong], ignore_index=True, sort=False)


def ket_qua_mis_den_thua_t2(df_mis_den_thua_t2: pd.DataFrame | None, df_qt_den: pd.DataFrame | None,
                            df_npo_den_thua: pd.DataFrame, log_callback=None) -> pd.DataFrame | None:
    """Đối xứng `ket_qua_mis_di_thua_t2()`, chiều đến — LOAI_LENH_OSB='1', khoá
    MIS là KEY_DEN_HUB (`_them_key_den_hub_tu_thua()`), khoá NPO là KEY_DEN."""
    if df_mis_den_thua_t2 is None or len(df_mis_den_thua_t2) == 0:
        return None

    mis = _them_key_den_hub_tu_thua(df_mis_den_thua_t2)
    mis_osb    = mis[la_lenh_osb_den(mis)].copy()
    mis_thuong = mis[~la_lenh_osb_den(mis)].copy()

    ket_qua_osb = _gan_ket_qua(
        mis_osb, 'KEY_DEN_HUB', df_qt_den, 'CN_TRACE_TIEN',
        KETQUA_OSB_DEN_KHOP, KETQUA_OSB_DEN_CHUA, KETQUA_KHONG_CO_QT, 'KetQua-OSB-Den', log_callback,
    )
    ket_qua_thuong = _gan_ket_qua(
        mis_thuong, 'KEY_DEN_HUB', df_npo_den_thua, 'KEY_DEN',
        KETQUA_THUONG_KHOP, KETQUA_THUONG_CHUA, KETQUA_THUONG_CHUA, 'KetQua-Thuong-Den', log_callback,
    )
    return pd.concat([ket_qua_osb, ket_qua_thuong], ignore_index=True, sort=False)
