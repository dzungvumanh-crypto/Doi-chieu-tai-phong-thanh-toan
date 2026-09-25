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


# ─── Mục 5 (bổ sung 11.09.2026, đã nối vào main_from_dir() ở pipeline.py) — đối
# chiếu chéo NPO_đi thừa (T-2) với "huỷ khác ngày"
# (T-1, chính là df_dien_huy_khac_ngay đang có trong bộ nhớ ở lần chạy hiện tại,
# output của tach_dien_huy() ở b10_xu_ly_npo_di_thua.py — KHÔNG phải file mới) ──

HUY_NGAY_T1 = 'huỷ ngày T-1'
NPO_NGAY_T2 = 'NPO ngày T-2'

_COLS_BAT_BUOC_NPO_THUA_T2 = ['TRBRCD', 'REFERENCE', 'CRAMOUNT']


def doc_npo_di_thua_t2(path: str) -> pd.DataFrame:
    """Đọc file NPO_đi thừa T-2 — chấp nhận .csv (chương trình tự xuất, khi vượt
    CSV_THRESHOLD) lẫn .xlsx (người chấm tự sửa tay). Tính lại SO_TRACE từ
    REFERENCE — sheet NPO_DI_THUA xuất Excel KHÔNG có cột SO_TRACE (_COLS_NPO ở
    pipeline.py không liệt kê SO_TRACE, xem b2_xu_ly_gl02.py::xu_ly_gl02()), phải
    tính lại ĐÚNG NGUYÊN công thức gốc (copy y hệt, không diễn giải lại):
    REFERENCE[7:19], lstrip('0') rồi mặc định '0' nếu rỗng SAU lstrip, nhưng ''
    (không phải '0') nếu REFERENCE gốc null/quá ngắn (_extracted là NaN)."""
    if path.lower().endswith('.csv'):
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', sep=None, engine='python')
    else:
        df = pd.read_excel(path, dtype=str, engine='calamine')
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in _COLS_BAT_BUOC_NPO_THUA_T2 if c not in df.columns]
    if missing:
        raise ValueError(f'File NPO_đi thừa T-2 thiếu cột {missing} — có thể bị sửa cấu trúc: {path}')

    df = df.copy()
    df['CRAMOUNT'] = doc_so_tien(df['CRAMOUNT'], f'NPO_đi thừa T-2: {path}', ten_cot='CRAMOUNT')

    # SO_TRACE — copy Y HỆT công thức gốc b2_xu_ly_gl02.py::xu_ly_gl02(), KHÔNG
    # được rút gọn còn 1 nhánh (dự án đã bị phản biện phát hiện bản rút gọn sai).
    # KHÔNG được thêm .astype(str) trước .str[7:19] — REFERENCE null (dtype=str
    # khi đọc file giữ NaN dạng float) sẽ bị .astype(str) biến thành chuỗi 'nan',
    # làm mất luôn nhánh NaN của where() phía dưới, không còn phân biệt được với
    # REFERENCE có giá trị thật.
    _extracted     = df['REFERENCE'].str[7:19]
    _stripped      = _extracted.str.lstrip('0')
    df['SO_TRACE'] = _stripped.where(_stripped != '', other='0').where(_extracted.notna(), other='')

    df['_CHECK_TRUNG'] = df['TRBRCD'].astype(str).str.strip() + df['SO_TRACE'].astype(str)
    return df


def doi_chieu_huy_cheo_ngay(df_npo_thua_t2: pd.DataFrame | None,
                           df_huy_khac_ngay_t1: pd.DataFrame,
                           log_callback=None):
    """Mục 5 (11.09.2026) — trả về (df_npo_thua_t2_ket_qua, df_huy_ket_qua) với
    cột KET_QUA gắn thêm, GIỮ ĐỦ toàn bộ dòng (không rơi dòng nào).

    THẬN TRỌNG (phát hiện qua phản biện, 11.09.2026): CHỈ gắn nhãn khi 1 nhóm
    CHECK_TRÙNG có ĐÚNG 1 dòng ở MỖI nguồn (1 NPO thừa T-2 <-> 1 huỷ khác ngày
    T-1) VÀ tổng CRAMOUNT = 0 — khác tach_dien_huy() ở b10 (cho phép nhóm ≥2
    dòng CÙNG 1 nguồn vì đã verify dữ liệu thật luôn đúng 2 dòng). Ở đây gộp
    CHÉO 2 FILE KHÁC NHAU, CHƯA có dữ liệu thật để verify giả định tương tự —
    nhóm có ≥2 dòng ở 1 trong 2 nguồn bị coi là MƠ HỒ, KHÔNG gắn nhãn (an toàn
    hơn là đoán), chỉ log số nhóm mơ hồ để người chấm tự kiểm tra tay."""
    _log = log_callback or print
    if df_npo_thua_t2 is None or len(df_npo_thua_t2) == 0:
        return df_npo_thua_t2, df_huy_khac_ngay_t1

    npo_t2 = df_npo_thua_t2.copy()
    if '_CHECK_TRUNG' not in npo_t2.columns:
        raise ValueError("doi_chieu_huy_cheo_ngay: df_npo_thua_t2 thiếu cột '_CHECK_TRUNG' — phải đọc qua doc_npo_di_thua_t2() trước.")

    huy = df_huy_khac_ngay_t1.copy()
    huy['_CHECK_TRUNG'] = huy['TRBRCD'].astype(str).str.strip() + huy['SO_TRACE'].astype(str)

    npo_t2['_NGUON'] = 'NPO_T2'
    huy['_NGUON']    = 'HUY_T1'
    gop = pd.concat([
        npo_t2[['_CHECK_TRUNG', 'CRAMOUNT', '_NGUON']],
        huy[['_CHECK_TRUNG', 'CRAMOUNT', '_NGUON']],
    ], ignore_index=True)

    so_dong_nhom = gop.groupby('_CHECK_TRUNG')['_CHECK_TRUNG'].transform('size')
    tong_nhom    = gop.groupby('_CHECK_TRUNG')['CRAMOUNT'].transform('sum')
    # Đúng 1-đối-1: tổng đúng 2 dòng trong nhóm (so_dong_nhom==2) VÀ cả 2 nguồn
    # đều có mặt (đảm bảo là 1 NPO + 1 huỷ, không phải 2 dòng cùng 1 nguồn).
    co_ca_2_nguon = gop.groupby('_CHECK_TRUNG')['_NGUON'].transform(lambda s: s.nunique() == 2)
    mask_khop_1doi1 = (so_dong_nhom == 2) & co_ca_2_nguon & (tong_nhom == 0)
    keys_khop = set(gop.loc[mask_khop_1doi1, '_CHECK_TRUNG'])

    mask_mo_ho = (so_dong_nhom > 2) & co_ca_2_nguon
    so_nhom_mo_ho = gop.loc[mask_mo_ho, '_CHECK_TRUNG'].nunique()
    if so_nhom_mo_ho > 0:
        _log(f'[B11][Mục 5][WARN] {so_nhom_mo_ho:,} nhóm CHECK_TRÙNG có >2 dòng khi gộp '
             f'NPO thừa T-2 + huỷ khác ngày T-1 — KHÔNG gắn nhãn (mơ hồ, cần chấm tay).')

    npo_t2['KET_QUA'] = npo_t2['_CHECK_TRUNG'].isin(keys_khop).map({True: HUY_NGAY_T1, False: ''})
    huy['KET_QUA']    = huy['_CHECK_TRUNG'].isin(keys_khop).map({True: NPO_NGAY_T2, False: ''})

    _log(f'[B11][Mục 5] {len(keys_khop):,} cặp khớp 1-đối-1 (tổng=0) giữa '
         f'NPO_đi thừa T-2 ({len(npo_t2):,} dòng) và huỷ khác ngày T-1 ({len(huy):,} dòng).')

    npo_t2 = npo_t2.drop(columns=['_CHECK_TRUNG', '_NGUON'])
    huy    = huy.drop(columns=['_CHECK_TRUNG', '_NGUON'])
    return npo_t2.reset_index(drop=True), huy.reset_index(drop=True)


# ─── Mục 5.1 (bổ sung 14.09.2026) — đối xứng Mục 5 ở trên nhưng nguồn QT đi
# thừa thay vì NPO_đi thừa ──

_COLS_BAT_BUOC_QT_THUA_T2 = ['CN thực hiện', 'Mã giao dịch', 'SO_TIEN']


def doc_qt_di_thua_t2(path: str) -> pd.DataFrame:
    """Mục 5.1 (14.09.2026) — đọc file QT đi thừa T-2, tính lại _CHECK_TRUNG =
    mã CN (từ 'CN thực hiện') + SO_TRACE ('Mã giao dịch'.lstrip('0')) — ĐÚNG công
    thức tach_dien_huy_qt() ở b9_doi_chieu_osb.py."""
    if path.lower().endswith('.csv'):
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', sep=None, engine='python')
    else:
        df = pd.read_excel(path, dtype=str, engine='calamine')
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in _COLS_BAT_BUOC_QT_THUA_T2 if c not in df.columns]
    if missing:
        raise ValueError(f'File QT đi thừa T-2 thiếu cột {missing} — có thể bị sửa cấu trúc: {path}')

    df = df.copy()
    df['SO_TIEN'] = doc_so_tien(df['SO_TIEN'], f'QT đi thừa T-2: {path}', ten_cot='SO_TIEN')
    ma_cn = df['CN thực hiện'].astype(str).str.strip().str.extract(r'^(\d+)', expand=False)
    if ma_cn.isna().any():
        raise ValueError(f"File QT đi thừa T-2 có 'CN thực hiện' sai định dạng '<mã CN> - <tên>': {path}")
    trace = df['Mã giao dịch'].astype(str).str.strip().str.lstrip('0')
    df['_CHECK_TRUNG'] = ma_cn + trace
    return df


def doi_chieu_huy_cheo_ngay_qt(df_qt_thua_t2: pd.DataFrame | None,
                               df_huy_khac_ngay_qt_t1: pd.DataFrame,
                               log_callback=None):
    """Mục 5.1 — đối xứng doi_chieu_huy_cheo_ngay() nhưng nguồn QT (cột tiền
    SO_TIEN thay vì CRAMOUNT). Đổi tên cột tạm để TÁI DÙNG NGUYÊN thuật toán đã
    có, không viết lại logic khớp.

    LƯU Ý (phát hiện khi rà lại `doi_chieu_huy_cheo_ngay()`, KHÔNG có trong bản
    mô tả gốc): hàm đó tự tính lại `_CHECK_TRUNG` cho vế "huy" bằng công thức
    HARDCODE `TRBRCD + SO_TRACE` (cột NPO) — `df_huy_khac_ngay_qt_t1` (đầu ra
    `tach_dien_huy_qt()` ở b9) không có 2 cột này, chỉ có 'CN thực hiện'/'Mã
    giao dịch' (cột QT). Phải thêm 2 cột tạm TRBRCD/SO_TRACE cùng công thức
    trích xuất với `doc_qt_di_thua_t2()`/`tach_dien_huy_qt()` (mã CN + SO_TRACE,
    không ký tự phân tách) rồi xoá lại sau — nếu không sẽ KeyError('TRBRCD') ngay
    lần chạy đầu có dữ liệu thật."""
    if df_qt_thua_t2 is None or len(df_qt_thua_t2) == 0:
        return df_qt_thua_t2, df_huy_khac_ngay_qt_t1

    qt_t2_tam = df_qt_thua_t2.rename(columns={'SO_TIEN': 'CRAMOUNT'})

    huy_tam = df_huy_khac_ngay_qt_t1.rename(columns={'SO_TIEN': 'CRAMOUNT'}).copy()
    huy_tam['TRBRCD']   = huy_tam['CN thực hiện'].astype(str).str.strip().str.extract(r'^(\d+)', expand=False)
    huy_tam['SO_TRACE'] = huy_tam['Mã giao dịch'].astype(str).str.strip().str.lstrip('0')

    ket_qua_qt_t2, ket_qua_huy = doi_chieu_huy_cheo_ngay(qt_t2_tam, huy_tam, log_callback)
    if ket_qua_qt_t2 is not None:
        ket_qua_qt_t2 = ket_qua_qt_t2.rename(columns={'CRAMOUNT': 'SO_TIEN'})
    if ket_qua_huy is not None:
        ket_qua_huy = ket_qua_huy.drop(columns=['TRBRCD', 'SO_TRACE'], errors='ignore') \
                                  .rename(columns={'CRAMOUNT': 'SO_TIEN'})
    return ket_qua_qt_t2, ket_qua_huy


# ─── Mục 8 (bổ sung 14.09.2026) — đọc file TO ko đi kênh NGÀY CŨ (người dùng tự
# nạp thêm, có thể nhiều file/nhiều ngày cùng lúc — xử lý gộp ở pipeline.py) ──

_COLS_BAT_BUOC_TIMEOUT_CU = ['CHI_NHANH', 'TRACE', 'SE_TRACE', 'SO_TIEN', 'NGAY_GIAO_DICH']


def doc_timeout_cu(path: str) -> pd.DataFrame:
    """Đọc 1 file "TO ko đi kênh ngày cũ" — dùng lại NGUYÊN `_doc_file_thua_t2()`
    (chấp nhận .csv chương trình tự xuất lẫn .xlsx người chấm tự sửa tay, dtype=str,
    tự dò dấu phân cách CSV, chuẩn hoá SO_TIEN qua `doc_so_tien()`). Không bắt buộc
    có sẵn KEY_HUB/GHI_CHU — `doi_chieu_timeout_cu()` ở b12_ghi_chu_timeout.py tự
    tính lại KEY_HUB nếu thiếu (file chương trình tự xuất `TIMEOUT_KHONG_KENH_*.csv`
    thì luôn có sẵn, không cần tính lại)."""
    return _doc_file_thua_t2(path, _COLS_BAT_BUOC_TIMEOUT_CU, 'TO ko đi kênh ngày cũ')
