import pandas as pd

from .b4_xu_ly_mis_di import _tao_so_trace

GHI_CHU_KHOP_NPO   = 'NPO đi ngày T'
GHI_CHU_KHOP_QT    = 'QT đi ngày T'
GHI_CHU_KHONG_CO   = 'Không có'
GHI_CHU_TIMEOUT_KHOP = 'TO ko đi kênh ngày T'

# ─── Mục 8 (bổ sung 14.09.2026) — TO ko đi kênh NGÀY CŨ (người dùng tự nạp thêm)
# đối chiếu với NPO_đi thừa/QT_đi thừa/Huỷ trong ngày CỦA NGÀY ĐANG CHẠY. Nhãn
# 'TO ko đi kênh' (KHÔNG hậu tố 'ngày T') để phân biệt nguồn gốc với
# GHI_CHU_TIMEOUT_KHOP ở trên (đối chiếu TIMEOUT của CHÍNH ngày đang chạy) ──
# GHI_CHU_TIMEOUT_CU (hằng số) CHỈ còn dùng cho NPO đi thừa — Thảo xác nhận
# 15.09.2026: QT đi thừa khớp timeout cũ phải ghi RÕ ngày của timeout cũ đó
# (xem 'TO ko đi kênh ngày {NGAY_GIAO_DICH}' trong doi_chieu_timeout_cu() bên
# dưới), bất đối xứng có chủ đích với NPO — KHÔNG sửa cho giống nhau.
GHI_CHU_TIMEOUT_CU    = 'TO ko đi kênh'
TT_DOI_CHIEU_NPO      = 'Hạch toán NPO đi ngày T-1'
TT_DOI_CHIEU_QT       = 'QT đi ngày T-1'
TT_DOI_CHIEU_HUY      = 'Hủy trong ngày T-1'
TT_DOI_CHIEU_KHONG_CO = 'Không có'


def gan_ghi_chu_timeout(df_timeout: pd.DataFrame, df_npo_di_thua: pd.DataFrame | None,
                        df_qt_di: pd.DataFrame | None, log_callback=None) -> pd.DataFrame:
    """Mục 1.1 (bổ sung 11.09.2026) — thêm cột GHI_CHU lên TIMEOUT_KHONG_KENH, đánh
    dấu điện timeout đã được hạch toán NPO đi ngày T hay QT đi ngày T. Ưu tiên NPO
    trước QT khi (hiếm khi) khớp cả hai — đúng thứ tự liệt kê trong tài liệu gốc.
    Không khớp cả NPO lẫn QT → giữ nguyên mặc định GHI_CHU_KHONG_CO ('Không có') —
    Thảo xác nhận 16.09.2026 đây đúng là hành vi mong muốn, không cần thêm nhãn khác."""
    _log = log_callback or print
    if df_timeout is None or len(df_timeout) == 0:
        return df_timeout

    df = df_timeout.copy()
    df['GHI_CHU'] = GHI_CHU_KHONG_CO

    if df_qt_di is not None and len(df_qt_di) > 0:
        keys_qt = set(df_qt_di['CN_TRACE_TIEN'])
        df.loc[df['KEY_HUB'].isin(keys_qt), 'GHI_CHU'] = GHI_CHU_KHOP_QT

    if df_npo_di_thua is not None and len(df_npo_di_thua) > 0:
        keys_npo = set(df_npo_di_thua['KEY_DI'])
        df.loc[df['KEY_HUB'].isin(keys_npo), 'GHI_CHU'] = GHI_CHU_KHOP_NPO

    n_npo = int((df['GHI_CHU'] == GHI_CHU_KHOP_NPO).sum())
    n_qt  = int((df['GHI_CHU'] == GHI_CHU_KHOP_QT).sum())
    _log(f'[B12][Mục 1.1] TIMEOUT: {n_npo:,} khớp NPO đi, {n_qt:,} khớp QT đi, '
         f'{len(df) - n_npo - n_qt:,} không khớp')
    return df


def gan_ghi_chu_npo_di_thua(df_npo_di_thua: pd.DataFrame | None, df_timeout: pd.DataFrame | None,
                            log_callback=None) -> pd.DataFrame | None:
    """Mục 1.1 — chiều ngược lại: đánh dấu trên NPO_DI_THUA dòng nào là do timeout
    không đi kênh giải thích được. Cột GHI_CHU ở đây KHÁC GHI_CHU_T2 (Điểm 4, so
    với MIS thừa T-2) — 2 cột riêng biệt, không ghi đè nhau."""
    _log = log_callback or print
    if df_npo_di_thua is None or len(df_npo_di_thua) == 0:
        return df_npo_di_thua

    df = df_npo_di_thua.copy()
    keys_timeout = set(df_timeout['KEY_HUB']) if df_timeout is not None and len(df_timeout) > 0 else set()
    df['GHI_CHU'] = df['KEY_DI'].isin(keys_timeout).map({True: GHI_CHU_TIMEOUT_KHOP, False: ''})

    n = int((df['GHI_CHU'] == GHI_CHU_TIMEOUT_KHOP).sum())
    _log(f'[B12][Mục 1.1] NPO_DI_THUA: {n:,}/{len(df):,} dòng khớp TO ko đi kênh')
    return df


def gan_ghi_chu_qt_di_thua(df_di_chua_khop: pd.DataFrame | None, df_timeout: pd.DataFrame | None,
                           log_callback=None) -> pd.DataFrame | None:
    """Mục 1.1.1 (bổ sung 14.09.2026) — đối xứng gan_ghi_chu_npo_di_thua(), áp cho
    "QT đi thừa" (subset NGUON=='QT' của df_di_chua_khop, trả về từ
    doi_chieu_osb_di() ở b9_doi_chieu_osb.py). Trả về CHỈ subset QT đã gắn cột
    GHI_CHU (không trả lại phần MIS trong df_di_chua_khop — đó không phải "QT đi
    thừa")."""
    _log = log_callback or print
    if df_di_chua_khop is None or len(df_di_chua_khop) == 0:
        return None
    if 'NGUON' not in df_di_chua_khop.columns:
        raise ValueError('gan_ghi_chu_qt_di_thua: df_di_chua_khop thiếu cột NGUON — không phải dữ liệu từ doi_chieu_osb_di().')

    df_qt_thua = df_di_chua_khop[df_di_chua_khop['NGUON'] == 'QT'].copy()
    keys_timeout = set(df_timeout['KEY_HUB']) if df_timeout is not None and len(df_timeout) > 0 else set()
    df_qt_thua['GHI_CHU'] = df_qt_thua['CN_TRACE_TIEN'].isin(keys_timeout).map({True: GHI_CHU_TIMEOUT_KHOP, False: ''})

    n = int((df_qt_thua['GHI_CHU'] == GHI_CHU_TIMEOUT_KHOP).sum())
    _log(f'[B12][Mục 1.1.1] QT_DI_THUA: {n:,}/{len(df_qt_thua):,} dòng khớp TO ko đi kênh')
    return df_qt_thua.reset_index(drop=True)


def _tinh_key_hub_timeout_cu(df: pd.DataFrame) -> pd.Series:
    """Tính lại KEY_HUB cho file TO ko đi kênh ngày cũ khi file KHÔNG có sẵn cột
    này (người dùng tự gõ tay, không phải file chương trình tự xuất). Dùng ĐÚNG
    NGUYÊN `_tao_so_trace()` (b4_xu_ly_mis_di.py) + công thức `_them_cot_khoa()`
    (CHI_NHANH.strip() + SO_TRACE + SO_TIEN) — không viết lại công thức."""
    cn_clean = df['CHI_NHANH'].astype(str).str.strip()
    return cn_clean + _tao_so_trace(df) + df['SO_TIEN'].astype(str)


def doi_chieu_timeout_cu(df_timeout_cu: pd.DataFrame | None,
                         df_npo_di_thua: pd.DataFrame | None,
                         df_qt_di_thua: pd.DataFrame | None,
                         df_dien_huy_trong_ngay: pd.DataFrame | None,
                         log_callback=None):
    """Mục 8 (bổ sung 14.09.2026) — đối chiếu TO ko đi kênh NGÀY CŨ (do người dùng
    tự nạp thêm, điện timeout của ngày trước chưa hạch toán) với NPO_đi thừa/
    QT_đi thừa/Huỷ trong ngày CỦA NGÀY ĐANG CHẠY (T-1 theo đúng quy ước xuyên
    suốt tài liệu). Thứ tự ưu tiên ĐÚNG NHƯ VĂN BẢN, áp lần lượt để mask sau đè
    mask trước: Huỷ trong ngày → QT đi → NPO đi (NPO ưu tiên cao nhất).

    Trả về (df_timeout_cu_ketqua, df_npo_di_thua, df_qt_di_thua) — 2 vế sau CHỈ
    điền thêm GHI_CHU cho dòng CÒN RỖNG (chưa được Mục 1.1/1.1.1 giải thích bằng
    timeout CHÍNH ngày) — KHÔNG ghi đè GHI_CHU đã có, ưu tiên giải thích bằng
    chính ngày đang chạy trước."""
    _log = log_callback or print
    if df_timeout_cu is None or len(df_timeout_cu) == 0:
        return df_timeout_cu, df_npo_di_thua, df_qt_di_thua

    df = df_timeout_cu.copy()
    if 'KEY_HUB' not in df.columns:
        df['KEY_HUB'] = _tinh_key_hub_timeout_cu(df)
    df['TT_DOI_CHIEU'] = TT_DOI_CHIEU_KHONG_CO

    keys_huy = set(df_dien_huy_trong_ngay['KEY_DI']) if df_dien_huy_trong_ngay is not None and len(df_dien_huy_trong_ngay) > 0 else set()
    keys_qt  = set(df_qt_di_thua['CN_TRACE_TIEN']) if df_qt_di_thua is not None and len(df_qt_di_thua) > 0 else set()
    keys_npo = set(df_npo_di_thua['KEY_DI']) if df_npo_di_thua is not None and len(df_npo_di_thua) > 0 else set()

    # ── Bản đồ KEY_HUB → NGAY_GIAO_DICH của timeout cũ (Thảo xác nhận 15.09.2026:
    # QT đi thừa khớp timeout cũ phải ghi RÕ ngày của timeout cũ đó trong GHI_CHU,
    # KHÁC NPO — NPO vẫn giữ nhãn chung GHI_CHU_TIMEOUT_CU, KHÔNG SỬA, đã xác nhận
    # riêng, không phải quên đối xứng). "Ngày" theo Thảo là TRDT của lệnh trong
    # file TO ko đi kênh — Thảo xác nhận 16.09.2026: TRDT CHÍNH LÀ cột NGAY_GIAO_DICH
    # (không phải cột riêng), dùng nguyên như hiện tại, không cần đổi tên cột.
    if 'NGAY_GIAO_DICH' not in df.columns:
        raise ValueError(
            'doi_chieu_timeout_cu: df_timeout_cu thiếu cột NGAY_GIAO_DICH — cần để '
            'ghi nhãn "TO ko đi kênh ngày ..." trên QT đi thừa (Mục 8).'
        )
    # Strip ngay tại điểm đọc — dữ liệu thực dính khoảng trắng thừa (b4_xu_ly_mis_di.py
    # cũng phải .str.strip() cột này trước khi dùng), không strip là nhãn GHI_CHU cuối
    # cùng dính khoảng trắng đầu/cuối.
    df['NGAY_GIAO_DICH'] = df['NGAY_GIAO_DICH'].astype(str).str.strip()
    khoa_trung = df.loc[df['KEY_HUB'].duplicated(keep=False), 'KEY_HUB'].unique()
    if len(khoa_trung) > 0:
        so_ngay_khac = df[df['KEY_HUB'].isin(khoa_trung)].groupby('KEY_HUB')['NGAY_GIAO_DICH'].nunique()
        khoa_khac_ngay = so_ngay_khac[so_ngay_khac > 1].index.tolist()
        if khoa_khac_ngay:
            _log(f'[B12][Mục 8] CẢNH BÁO: {len(khoa_khac_ngay):,} KEY_HUB trùng khoá nhưng khác '
                 f'NGAY_GIAO_DICH trong timeout cũ — lấy dòng đầu tiên: {khoa_khac_ngay[:10]}')
    map_ngay_timeout_cu = df.drop_duplicates(subset='KEY_HUB', keep='first').set_index('KEY_HUB')['NGAY_GIAO_DICH']

    df.loc[df['KEY_HUB'].isin(keys_huy), 'TT_DOI_CHIEU'] = TT_DOI_CHIEU_HUY
    df.loc[df['KEY_HUB'].isin(keys_qt),  'TT_DOI_CHIEU'] = TT_DOI_CHIEU_QT
    df.loc[df['KEY_HUB'].isin(keys_npo), 'TT_DOI_CHIEU'] = TT_DOI_CHIEU_NPO

    n_npo = int((df['TT_DOI_CHIEU'] == TT_DOI_CHIEU_NPO).sum())
    n_qt  = int((df['TT_DOI_CHIEU'] == TT_DOI_CHIEU_QT).sum())
    n_huy = int((df['TT_DOI_CHIEU'] == TT_DOI_CHIEU_HUY).sum())
    _log(f'[B12][Mục 8] TO ko đi kênh ngày cũ: {n_npo:,} khớp NPO, {n_qt:,} khớp QT, '
         f'{n_huy:,} khớp huỷ trong ngày, {len(df)-n_npo-n_qt-n_huy:,} không khớp')

    # ── Chiều ngược lại: điền GHI_CHU cho NPO/QT đi thừa còn RỖNG ──
    # Bất kỳ KEY_HUB nào có mặt trong timeout cũ (không phân biệt nó rơi vào
    # nhánh TT_DOI_CHIEU nào ở trên) — dùng nguyên set KEY_HUB, không lệ thuộc
    # cột TT_DOI_CHIEU (tránh phụ thuộc ngầm vào thứ tự áp mask ở trên).
    keys_timeout_cu = set(df['KEY_HUB'])

    if df_npo_di_thua is not None and len(df_npo_di_thua) > 0 and 'GHI_CHU' in df_npo_di_thua.columns:
        npo = df_npo_di_thua.copy()
        mask_rong = npo['GHI_CHU'].astype(str).str.strip() == ''
        mask_khop = npo['KEY_DI'].isin(keys_timeout_cu)
        npo.loc[mask_rong & mask_khop, 'GHI_CHU'] = GHI_CHU_TIMEOUT_CU
        _log(f'[B12][Mục 8] NPO_DI_THUA: {int((mask_rong & mask_khop).sum()):,} dòng bổ sung GHI_CHU "TO ko đi kênh"')
        df_npo_di_thua = npo

    if df_qt_di_thua is not None and len(df_qt_di_thua) > 0 and 'GHI_CHU' in df_qt_di_thua.columns:
        qt = df_qt_di_thua.copy()
        mask_rong = qt['GHI_CHU'].astype(str).str.strip() == ''
        mask_khop = qt['CN_TRACE_TIEN'].isin(keys_timeout_cu)
        mask_gan  = mask_rong & mask_khop
        # QT đi thừa cần NGÀY CỤ THỂ của timeout cũ đã khớp — khác NPO (nhãn
        # chung GHI_CHU_TIMEOUT_CU ở trên), Thảo xác nhận riêng.
        ngay_khop = qt.loc[mask_gan, 'CN_TRACE_TIEN'].map(map_ngay_timeout_cu)
        qt.loc[mask_gan, 'GHI_CHU'] = 'TO ko đi kênh ngày ' + ngay_khop.astype(str)
        _log(f'[B12][Mục 8] QT_DI_THUA: {int(mask_gan.sum()):,} dòng bổ sung GHI_CHU "TO ko đi kênh ngày ..."')
        df_qt_di_thua = qt

    return df.reset_index(drop=True), df_npo_di_thua, df_qt_di_thua
