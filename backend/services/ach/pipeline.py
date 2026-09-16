"""
Pipeline đối chiếu ACH: GL02 (NPO) vs MIS.
Hàm chính: main_from_dir() — thread-safe, dùng cho Web UI.
"""
import glob
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import xlsxwriter

from . import config as _cfg
from .b1_doc_session   import doc_session
from .b2_xu_ly_gl02    import xu_ly_gl02
from .b3_xu_ly_gw      import xu_ly_gw
from .b4_xu_ly_mis_di  import (
    _doc_mis_di_raw, _process_mis_di, khop_voi_gw, tim_nhom_gw_thua, ap_dung_confirm_mis_di,
    tim_giao_dich_bi_loai_session_null, doc_mis_di_khong_loc_session,
    tim_toan_bo_giao_dich_bi_loai_session_null,
)
from .b5_doi_chieu_di  import doi_chieu_di
from .b6_xu_ly_mis_den import xu_ly_mis_den
from .b7_doi_chieu_den import doi_chieu_den
from .b9_doi_chieu_osb import xu_ly_qt, doi_chieu_osb_di, doi_chieu_osb_den, tach_dien_huy_qt
from .b10_xu_ly_npo_di_thua import tach_dien_huy
from .b11_doi_chieu_cheo_ngay import (
    danh_dau_da_can_di, danh_dau_da_can_den, doc_mis_di_thua_t2, doc_mis_den_thua_t2,
    ket_qua_mis_di_thua_t2, ket_qua_mis_den_thua_t2,
    KETQUA_THUONG_KHOP, KETQUA_OSB_DI_KHOP, KETQUA_OSB_DEN_KHOP,
    doc_npo_di_thua_t2, doi_chieu_huy_cheo_ngay,
    doc_qt_di_thua_t2, doi_chieu_huy_cheo_ngay_qt,
    doc_timeout_cu,
)
from .b12_ghi_chu_timeout import (
    gan_ghi_chu_timeout, gan_ghi_chu_npo_di_thua, gan_ghi_chu_qt_di_thua,
    doi_chieu_timeout_cu,
)
from .b13_xu_ly_gw_den import xu_ly_gw_den, doi_chieu_gw_den
from .b15_napas import doc_pdf_napas, doc_napas_csv, doi_chieu_napas_gw

_COLS_NPO = _cfg.COLS_NPO
# Điểm 4 — thêm cột ghi chú đối chiếu chéo ngày CHỈ trên sheet NPO_DI_THUA/
# NPO_DEN_THUA (không áp cho sheet huỷ Điểm 3 — cột này không có ý nghĩa ở đó).
_COLS_NPO_THUA = _COLS_NPO + ['GHI_CHU_T2', 'GHI_CHU']

_COLS_MIS_DI = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'CN tiền Hub', 'REFHUB', 'MSGREF',
    'MSGSEQ', 'TXID', 'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN',
    'TRACE', 'SE_TRACE', 'SESSION', 'LOAI_LENH_OSB', 'NH_NHAN',
    'MA_GIAO_DICH', 'NOI_DUNG', 'NGAY_KENH_TRA', 'MATCH_TYPE',
    'LY_DO_GIU_SESSION_NULL', 'PHAN_LOAI_TIMEOUT',
]

# Sheet TIMEOUT_KHONG_KENH dùng riêng — MATCH_TYPE bị xoá có chủ đích khỏi
# df_timeout ở b4_xu_ly_mis_di.py (luôn rỗng cho đúng nhóm dòng này, xem
# docstring `khop_voi_gw()`), không phải cột thiếu do lỗi. Dùng chung
# _COLS_MIS_DI ở đây sẽ luôn ra warning vô hại — tách riêng để log sạch.
_COLS_TIMEOUT = [c for c in _COLS_MIS_DI if c != 'MATCH_TYPE'] + ['GHI_CHU']

_COLS_MIS_DI_CONFIRM = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'CN tiền Hub', 'REFHUB', 'MSGREF',
    'MSGSEQ', 'TXID', 'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN',
    'TRACE', 'SE_TRACE', 'SO_TRACE', 'SESSION', 'LOAI_LENH_OSB', 'NH_NHAN',
    'MA_GIAO_DICH', 'NOI_DUNG', 'NGAY_KENH_TRA', 'LY_DO_GIU_SESSION_NULL',
]

_COLS_MIS_DEN = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SESSION', 'LOAI_LENH_OSB', 'NH_GUI', 'NOI_DUNG',
]

# Sheet vượt ngưỡng này → xuất CSV thay vì ghi vào Excel
CSV_THRESHOLD = 15_000

_XANH_LA    = '#C6EFCE'
_DO         = '#FFC7CE'
_CAM        = '#FFEB9C'
_XANH_LAM   = '#DDEBF7'


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean(df: pd.DataFrame, cols: list, label: str = '') -> pd.DataFrame:
    if df is None or len(df) == 0:
        return df
    existing = [c for c in cols if c in df.columns]
    missing  = [c for c in cols if c not in df.columns]
    if missing:
        print(f'[WARN] _clean({label}): thiếu cột {missing}')
    return df[existing]


def _tong_tien(df: pd.DataFrame, col: str) -> int:
    if df is None or len(df) == 0 or col not in df.columns:
        return 0
    return int(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())


def _tong_an_toan(*vals):
    """Tổng các giá trị TONG_KET, nhưng trả None nếu BẤT KỲ giá trị nào None (nghĩa
    là 1 phần chưa đối chiếu được, chi_tim_timeout) — tránh cộng lẫn 0 giả (chưa
    tính) với số thật, ra tổng thấp hơn thực tế mà không có dấu hiệu gì báo lỗi."""
    return None if any(v is None for v in vals) else sum(vals)


def _tao_cap_cn_tien(df_mis_di, df_timeout, dict_gw_count):
    """Bảng tham khảo (mục 3.2 bullet 1) — cặp CN TIỀN thừa ở MIS_đi so với GW."""
    cn_col = 'CN tiền Hub'
    if df_mis_di is None or len(df_mis_di) == 0 or cn_col not in df_mis_di.columns:
        return pd.DataFrame(columns=['CHI_NHANH', 'SO_TIEN', 'COUNT_MIS', 'COUNT_GW', 'CHENH_LECH', 'SO_TIMEOUT'])

    cnt = df_mis_di.groupby(cn_col, sort=False).size().rename('COUNT_MIS').reset_index()
    cnt['COUNT_GW']   = cnt[cn_col].map(dict_gw_count).fillna(0).astype(int)
    cnt['CHENH_LECH'] = cnt['COUNT_MIS'] - cnt['COUNT_GW']

    if df_timeout is not None and len(df_timeout) > 0 and cn_col in df_timeout.columns:
        to_cnt = df_timeout.groupby(cn_col, sort=False).size().rename('SO_TIMEOUT')
        cnt    = cnt.merge(to_cnt, on=cn_col, how='left')
        cnt['SO_TIMEOUT'] = cnt['SO_TIMEOUT'].fillna(0).astype(int)
    else:
        cnt['SO_TIMEOUT'] = 0

    ref       = df_mis_di.drop_duplicates(subset=[cn_col])
    lookup    = ref.set_index(cn_col)[['CHI_NHANH', 'SO_TIEN']]
    cnt['CHI_NHANH'] = cnt[cn_col].map(lookup['CHI_NHANH'].to_dict())
    cnt['SO_TIEN']   = cnt[cn_col].map(lookup['SO_TIEN'].to_dict())

    result = cnt[cnt['CHENH_LECH'] > 0][
        ['CHI_NHANH', 'SO_TIEN', 'COUNT_MIS', 'COUNT_GW', 'CHENH_LECH', 'SO_TIMEOUT']
    ].copy()
    return result.sort_values('CHENH_LECH', ascending=False).reset_index(drop=True)


def _loai_osb_da_khop_khoi_thua(df_mis_thua: pd.DataFrame | None,
                                df_osb_khop: pd.DataFrame | None) -> pd.DataFrame | None:
    """Mục 2 (bổ sung 11.09.2026) — loại các dòng OSB đã khớp QT (df_osb_khop, GIỮ
    NGUYÊN index gốc từ doi_chieu_osb_di()/doi_chieu_osb_den()) ra khỏi MIS_đi/đến
    thừa, tránh hiện trùng ở cả sheet MIS_..._THUA lẫn file OSB riêng
    (_ACH_OSB.xlsx). Loại theo INDEX GỐC, không theo khoá — nhiều dòng cùng khoá
    CN_TRACE_TIEN có thể chỉ MỘT PHẦN khớp QT (đối chiếu theo count ở
    _doi_chieu()); loại theo khoá sẽ xoá nhầm cả các dòng cùng khoá còn CHƯA khớp.
    """
    if df_mis_thua is None or df_osb_khop is None or len(df_osb_khop) == 0:
        return df_mis_thua
    if not df_mis_thua.index.is_unique:
        raise ValueError('_loai_osb_da_khop_khoi_thua: df_mis_thua có index trùng lặp — không loại được chính xác theo index.')
    return df_mis_thua.drop(index=df_osb_khop.index).reset_index(drop=True)


# ─── Tìm file ─────────────────────────────────────────────────────────────────

def _tim_ngay_tu_pdf(input_dir: str) -> str | None:
    import re as _re
    for root, _, files in os.walk(os.path.abspath(input_dir)):
        for f in files:
            if f.endswith('.pdf'):
                m = _re.search(r'_(\d{8})_', f)
                if m:
                    d = datetime.strptime(m.group(1), '%Y%m%d') - timedelta(days=1)
                    return d.strftime('%d/%m/%Y')
    return None


def _tim_file(input_dir: str, pattern: str) -> list:
    abs_dir = os.path.abspath(input_dir)
    return sorted(glob.glob(os.path.join(abs_dir, '**', pattern), recursive=True))


def _tim_file_ngoai_output(input_dir: str, pattern: str) -> list:
    """Giống `_tim_file()` nhưng loại các file nằm trong thư mục con 'Output'
    (kết quả tự copy về của CHÍNH lần chạy trước cùng thư mục — xem
    `ach_service.py::_OUTPUT_SUBFOLDER`). Điểm 4 dò file MIS thừa T-2 bằng
    pattern trùng tên với file chương trình tự xuất — nếu không loại trừ, chạy
    lại 1 thư mục đã có Output/ cũ sẽ tự khớp nhầm với kết quả của chính ngày
    đang chạy thay vì file T-2 thật (khác thư mục ngày hôm trước)."""
    return [
        f for f in _tim_file(input_dir, pattern)
        if 'output' not in {p.lower() for p in os.path.normpath(f).split(os.sep)}
    ]


def _chuan_hoa_ten_file(ten: str) -> str:
    """Bỏ dấu tiếng Việt, bỏ mọi ký tự không phải chữ/số, về chữ thường.
    'MIS đi thừa 09.08' / 'MIS đi thưa 09.08' / 'MIS_DI_THUA_20260809' /
    'Mis den thua 09.08' đều quy về cùng một dạng để so khớp."""
    kd = unicodedata.normalize('NFD', ten)
    kd = ''.join(c for c in kd if unicodedata.category(c) != 'Mn')
    kd = kd.replace('đ', 'd').replace('Đ', 'd')
    return re.sub(r'[^0-9a-z]', '', kd.lower())


# Tiền tố đã chuẩn hoá của file MIS thừa T-2 theo chiều. Giữ tiền tố 'mis' để
# KHÔNG bắt nhầm 'OSB đi thừa*.xlsx' (Điểm 2) — file đó cấu trúc cột giống hệt
# nhưng không phải input T-2, chỉ tên file mới phân biệt được chắc chắn.
_TIEN_TO_THUA_T2 = {'di': 'misdithua', 'den': 'misdenthua'}
_DUOI_THUA_T2    = ('.csv', '.xlsx')


def _tim_file_thua_t2(input_dir: str, chieu: str) -> list:
    """Điểm 4 (2026-08-03) — dò file MIS thừa T-2, chấp nhận cả file chương trình
    tự xuất (`MIS_DI_THUA_<ngày>.csv`) lẫn file người chấm tự đặt tên
    (`MIS đi thừa 09.08.xlsx`).

    2026-08-11 — chuyển từ so khớp `fnmatch` chính xác từng ký tự sang so khớp
    theo TÊN ĐÃ CHUẨN HOÁ. Lý do: dữ liệu thật ngày 10.08 có `MIS đi thưa
    09.08.xlsx` (thiếu dấu huyền) và `Mis den thua 09.08.xlsx` (không dấu) —
    mẫu cũ trượt cả hai, chương trình **bỏ qua im lặng** vì file này là tùy chọn.
    Người chấm gõ tên tay thì sai dấu là chuyện bình thường.

    Loại trừ `*_T2_KETQUA_*` — đó là file BÁO CÁO chương trình tự xuất, không bao
    giờ là input (bẫy 4.6 trong docs/BOI-CANH-DU-AN.md)."""
    tien_to = _TIEN_TO_THUA_T2[chieu]
    found = []
    for f in _tim_file_ngoai_output(input_dir, '*'):
        ten = os.path.basename(f)
        if not ten.lower().endswith(_DUOI_THUA_T2):
            continue
        chuan = _chuan_hoa_ten_file(os.path.splitext(ten)[0])
        if chuan.startswith(tien_to) and 't2ketqua' not in chuan:
            found.append(f)
    return sorted(found)


def _tim_file_npo_di_thua_t2(input_dir: str) -> list:
    """Mục 5 (bổ sung 11.09.2026) — dò file NPO_đi thừa T-2, cùng cơ chế chuẩn hoá
    tên file với _tim_file_thua_t2() (chấp nhận file chương trình tự xuất lẫn file
    người chấm tự đặt tên, không phân biệt hoa/thường/dấu). Loại trừ *_T2_KETQUA_*
    (file báo cáo tự xuất, không bao giờ là input)."""
    found = []
    for f in _tim_file_ngoai_output(input_dir, '*'):
        ten = os.path.basename(f)
        if not ten.lower().endswith(_DUOI_THUA_T2):
            continue
        chuan = _chuan_hoa_ten_file(os.path.splitext(ten)[0])
        if chuan.startswith('npodithua') and 't2ketqua' not in chuan:
            found.append(f)
    return sorted(found)


def _tim_file_qt_di_thua_t2(input_dir: str) -> list:
    """Mục 5.1 (bổ sung 14.09.2026) — dò file QT đi thừa T-2, đối xứng
    `_tim_file_npo_di_thua_t2()` (cùng cơ chế chuẩn hoá tên file). Loại trừ
    *_T2_KETQUA_* (file báo cáo tự xuất, không bao giờ là input)."""
    found = []
    for f in _tim_file_ngoai_output(input_dir, '*'):
        ten = os.path.basename(f)
        if not ten.lower().endswith(_DUOI_THUA_T2):
            continue
        chuan = _chuan_hoa_ten_file(os.path.splitext(ten)[0])
        if chuan.startswith('qtdithua') and 't2ketqua' not in chuan:
            found.append(f)
    return sorted(found)


# Tiền tố đã chuẩn hoá của file "TO ko đi kênh ngày cũ" (Mục 8) — chấp nhận cả
# tên sheet chuẩn 'TIMEOUT_KHONG_KENH' lẫn cách gọi nghiệp vụ 'TO ko đi kênh',
# thử cả 2, không loại trừ lẫn nhau.
_TIEN_TO_TIMEOUT_CU = ('timeoutkhongkenh', 'tokodikenh')


def _tim_file_timeout_cu(input_dir: str) -> list:
    """Mục 8 (bổ sung 14.09.2026) — dò TOÀN BỘ file "TO ko đi kênh ngày cũ" người
    dùng tự nạp thêm (điện timeout không đi kênh của ngày trước, chưa hạch toán).
    KHÔNG giới hạn 1 file như `_tim_file_npo_di_thua_t2()`/`_tim_file_qt_di_thua_t2()`
    — nghiệp vụ có thể đẩy nhiều file của nhiều ngày cũ khác nhau cùng lúc. Loại
    trừ 'ketqua'/'thuacu' (báo cáo tự xuất của module khác, không bao giờ là input
    — cùng lý do loại trừ '*_T2_KETQUA_*' ở các hàm T-2 phía trên)."""
    found = []
    for f in _tim_file_ngoai_output(input_dir, '*'):
        ten = os.path.basename(f)
        if not ten.lower().endswith(_DUOI_THUA_T2):
            continue
        chuan = _chuan_hoa_ten_file(os.path.splitext(ten)[0])
        if chuan.startswith(_TIEN_TO_TIMEOUT_CU) and 'ketqua' not in chuan and 'thuacu' not in chuan:
            found.append(f)
    return sorted(found)


def _tim_di_zip_ngay_khac(input_dir: str, log_callback=None) -> list:
    """Tìm thêm `*_DI_*.zip` ở các thư mục ANH EM (cùng thư mục cha) với
    `input_dir` — phục vụ tra REFHUB bổ sung (Checkpoint Bước 2) từ NGÀY KHÁC khi
    không có trong dữ liệu thô của chính ngày đang chạy (2026-08-04, Business
    Owner cần thêm giao dịch timeout của vài ngày trước vào báo cáo ngày sau, ví
    dụ chạy tuần tự các thư mục `31.07/`, `01.08/`... cùng 1 thư mục cha).

    Chỉ có ý nghĩa ở mode folder (input_dir là thư mục thật, có anh em cùng cấp)
    — mode upload không có khái niệm này, tự nhiên trả về rỗng vì input_dir nằm
    trong `data/temp_ach/<job_id>/input`, thư mục cha chỉ có đúng 1 con."""
    _log    = log_callback or print
    abs_dir = os.path.abspath(input_dir)
    parent  = os.path.dirname(abs_dir)
    if not os.path.isdir(parent):
        return []
    found = []
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if entry.is_dir() and os.path.abspath(entry.path) != abs_dir:
                    found.extend(_tim_file(entry.path, '*_DI_*.zip'))
    except OSError as e:
        # Audit 2026-08-04 — trước đây lỗi OS khi quét thư mục anh em bị nuốt im
        # lặng (return []) — không phân biệt được với "thật sự không có dữ liệu
        # ngày khác", khiến REFHUB bổ sung báo "không tìm thấy" gây hiểu lầm.
        _log(f'[Bước 2][WARN] Lỗi quét thư mục anh em của {abs_dir}: {e}')
        return []
    return found


def _tim_gw_xlsx(input_dir: str, log_callback=None) -> str:
    _log      = log_callback or print
    abs_dir   = os.path.abspath(input_dir)
    all_xlsx  = glob.glob(os.path.join(abs_dir, '**', '*.xlsx'), recursive=True)
    candidates = [f for f in all_xlsx if 'GW' in os.path.basename(f).upper()]
    if not candidates:
        candidates = all_xlsx
    loi_doc = []  # Audit 2026-08-04 — file lỗi khi đọc, phân biệt với "thật sự thiếu file"
    for f in candidates:
        try:
            xl = pd.ExcelFile(f, engine='calamine')
            for sheet in xl.sheet_names:
                df_peek = pd.read_excel(xl, sheet_name=sheet, header=None,
                                        nrows=8, dtype=str, engine='calamine')
                flat = set(str(v).strip() for v in df_peek.values.flatten() if str(v) != 'nan')
                if 'BRCD' in flat and 'SessionId' in flat:
                    return f
        except Exception as e:
            loi_doc.append((os.path.basename(f), str(e)))
            _log(f'[WARN] Lỗi đọc "{os.path.basename(f)}" khi dò file GW, thử file khác: {e}')
            continue
    if loi_doc:
        raise FileNotFoundError(
            f'Không tìm thấy file GW .xlsx hợp lệ trong: {abs_dir} — '
            f'có {len(loi_doc)} file lỗi khi đọc (không phải thiếu file): {loi_doc}'
        )
    raise FileNotFoundError('Không tìm thấy file GW .xlsx trong: ' + abs_dir)


def _tim_gw_den_xlsx(input_dir: str, log_callback=None) -> str | None:
    """Mục 4 (bổ sung 11.09.2026) — dò file đến_GW, giống `_tim_gw_xlsx()` nhưng
    input TÙY CHỌN (không có → trả None, KHÔNG raise, không chặn luồng chính) và
    tiêu chí nhận diện đổi 'SessionId' → 'Session ID' (có khoảng trắng — tên cột
    thật của file đến_GW, khác hẳn file GW đi)."""
    _log       = log_callback or print
    abs_dir    = os.path.abspath(input_dir)
    all_xlsx   = glob.glob(os.path.join(abs_dir, '**', '*.xlsx'), recursive=True)
    candidates = [f for f in all_xlsx if 'GW' in os.path.basename(f).upper()]
    if not candidates:
        candidates = all_xlsx
    for f in candidates:
        try:
            xl = pd.ExcelFile(f, engine='calamine')
            for sheet in xl.sheet_names:
                df_peek = pd.read_excel(xl, sheet_name=sheet, header=None,
                                        nrows=8, dtype=str, engine='calamine')
                flat = set(str(v).strip() for v in df_peek.values.flatten() if str(v) != 'nan')
                if 'BRCD' in flat and 'Session ID' in flat:
                    return f
        except Exception as e:
            _log(f'[WARN] Lỗi đọc "{os.path.basename(f)}" khi dò file đến_GW, thử file khác: {e}')
            continue
    return None


def _tim_napas_pdf(input_dir: str) -> str | None:
    """Mục 6 (bổ sung 11.09.2026) — dò file báo cáo Napas BC.03 (.pdf), TÙY CHỌN.
    Không có → trả None, KHÔNG raise, không chặn luồng chính (đúng tinh thần input
    tùy chọn như Điểm 2/QT, Mục 4/đến_GW). Có nhiều hơn 1 file → raise rõ danh sách,
    KHÔNG tự đoán chọn file nào (xem bank-reconciliation skill: never guess)."""
    found = _tim_file_ngoai_output(input_dir, '*.pdf')
    if len(found) > 1:
        raise FileNotFoundError(
            f'Có nhiều hơn 1 file PDF trong thư mục (Mục 6 cần đúng 1 file báo cáo '
            f'Napas BC.03) — giữ lại đúng 1 file: {found}'
        )
    return found[0] if found else None


def _tim_napas_csv(input_dir: str, loai: str) -> str | None:
    """Mục 7 (bổ sung 14.09.2026) — dò file CSV Napas chi tiết, TÙY CHỌN, riêng
    từng chiều (`loai`: 'ISS' chiều đi hoặc 'BEN' chiều đến — theo đúng tên file
    thật `*_TRANXFEEDETAIL_ISS_1.csv`/`*_TRANXFEEDETAIL_BEN_1.csv`). Không có →
    trả None. Nhiều hơn 1 → raise, không tự đoán."""
    found = _tim_file_ngoai_output(input_dir, f'*_{loai}_*.csv')
    if len(found) > 1:
        raise FileNotFoundError(
            f'Có nhiều hơn 1 file CSV Napas chi tiết {loai} — giữ lại đúng 1 file: {found}'
        )
    return found[0] if found else None


# ─── Xuất Excel ───────────────────────────────────────────────────────────────

def _viet_sheet(workbook, worksheet, df: pd.DataFrame, header_color: str, msg_khi_thieu: str = None):
    """msg_khi_thieu — 2026-08-21: nhãn riêng khi `df is None` (nghĩa là sheet này
    CHƯA ĐƯỢC TÍNH vì thiếu file, chi_tim_timeout), phân biệt với df rỗng thật sự
    (đã đối chiếu, 0 dòng khớp) — không được dùng chung 1 nhãn, dễ hiểu nhầm
    "đã khớp hết" (xem feedback_binary_match_status)."""
    if df is None:
        worksheet.write(0, 0, msg_khi_thieu or '(Không có dữ liệu)')
        return
    if len(df) == 0:
        worksheet.write(0, 0, '(Không có dữ liệu)')
        return

    fmt_header = workbook.add_format({'bold': True, 'bg_color': header_color, 'border': 1, 'font_size': 10})
    fmt_cell   = workbook.add_format({'font_size': 10, 'border': 1})

    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%d/%m/%Y %H:%M:%S')

    for col_idx, col_name in enumerate(df.columns):
        width = min(max(len(str(col_name)), 8) + 2, 30)
        worksheet.set_column(col_idx, col_idx, width)
        worksheet.write(0, col_idx, str(col_name), fmt_header)

    df_filled = df.fillna('')
    for row_idx, row in enumerate(df_filled.itertuples(index=False, name=None), start=1):
        worksheet.write_row(row_idx, 0, row, fmt_cell)


def _viet_sheet_co_tong(workbook, worksheet, df: pd.DataFrame, header_color: str, cot_tien: str,
                        msg_khi_thieu: str = None):
    """Giống `_viet_sheet()` nhưng thêm 1 dòng TỔNG (số món + tổng tiền) cuối sheet
    — Điểm 3 (2026-07-31), dùng cho sheet DIEN_DI_HUY_KHAC_NGAY theo đúng yêu cầu
    PR gốc: "kèm số món + số tiền"."""
    _viet_sheet(workbook, worksheet, df, header_color, msg_khi_thieu)
    if df is None or len(df) == 0:
        return

    fmt_tong  = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#DDEBF7', 'border': 1})
    tong_row  = len(df) + 1
    so_tien   = int(pd.to_numeric(df[cot_tien], errors='coerce').fillna(0).sum())
    worksheet.write(tong_row, 0, f'TỔNG: {len(df):,} món', fmt_tong)
    worksheet.write(tong_row, 1, f'{so_tien:,} VND', fmt_tong)


def _viet_confirm_mis_di(workbook, worksheet, df: pd.DataFrame):
    """Sheet MIS_DI_CONFIRM của file checkpoint xác nhận thủ công tại MIS_đi (Điểm
    1, 2026-07-31 — thay cơ chế Timeout-confirm cũ). Toàn bộ MIS_đi (đầu ra bước 5,
    TRƯỚC khi so khớp GW) + cột LOAI_BO (dropdown: trống = giữ (mặc định), 'loại
    bỏ' = bỏ dòng) + vùng paste REFHUB bổ sung bên dưới. Không đổi dữ liệu gốc."""
    if df is None or len(df) == 0:
        worksheet.write(0, 0, '(MIS_đi rỗng — không có giao dịch nào)')
        return

    fmt_header = workbook.add_format({'bold': True, 'bg_color': _CAM, 'border': 1, 'font_size': 10})
    fmt_cell   = workbook.add_format({'font_size': 10, 'border': 1})
    fmt_note   = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': _XANH_LAM, 'border': 1})

    df = df.sort_values(['REFHUB', 'MSGREF'], kind='stable').reset_index(drop=True).copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime('%d/%m/%Y %H:%M:%S')

    cols = list(df.columns) + ['LOAI_BO']
    for col_idx, col_name in enumerate(cols):
        width = min(max(len(str(col_name)), 8) + 2, 30)
        worksheet.set_column(col_idx, col_idx, width)
        worksheet.write(0, col_idx, str(col_name), fmt_header)

    loai_bo_col = len(df.columns)
    df_filled   = df.fillna('')
    for row_idx, row in enumerate(df_filled.itertuples(index=False, name=None), start=1):
        worksheet.write_row(row_idx, 0, row, fmt_cell)
        worksheet.write(row_idx, loai_bo_col, '', fmt_cell)

    n = len(df_filled)
    worksheet.data_validation(1, loai_bo_col, n, loai_bo_col, {
        'validate': 'list',
        'source': ['loại bỏ'],
    })

    start_row = n + 2
    worksheet.merge_range(start_row, 0, start_row, loai_bo_col,
                          'BỔ SUNG GIAO DỊCH BỊ BỎ SÓT — paste REFHUB vào cột bên dưới', fmt_note)
    worksheet.write(start_row + 1, 0, 'REFHUB', fmt_header)


_COLS_CAN_KIEM_TRA_HIEN_THI = {
    'REFHUB':             'REFHUB',
    'MSGREF':             'MSGREF',
    'CHI_NHANH':          'Chi nhánh',
    'CN tiền Hub':        'CN_TIỀN',
    'SO_TIEN':            'Số tiền',
    'SESSION':            'Session',
    'NGAY_GIAO_DICH':     'Ngày giao dịch',
    'NGAY_KENH_TRA':      'Ngày kênh trả',
    'TRANG_THAI_LENH':    'Trạng thái lệnh',
    'LY_DO_CAN_KIEM_TRA': 'Lý do phải kiểm tra',
}


def xuat_excel_confirm_mis_di(output_dir: str, session_id: str, ngay_dt: datetime,
                              df_mis_di: pd.DataFrame, df_bi_loai: pd.DataFrame,
                              log_callback=None) -> str:
    """Checkpoint xác nhận thủ công tại MIS_đi (Điểm 1, 2026-07-31 — thay hẳn cơ chế
    Timeout-confirm cũ, xem project_ach_4diem_pr_plan) — xuất file 2 sheet ngay sau
    `_process_mis_di()` (bước 5) rồi dừng pipeline:
    - MIS_DI_CONFIRM: sheet chính, người chấm điền cột LOAI_BO + bổ sung REFHUB.
    - CAN_KIEM_TRA_THU_CONG: CHỈ ĐỂ XEM — giao dịch SESSION=NULL bị `_process_mis_di()`
      loại thẳng khỏi MIS_đi (không thuộc MIS_đi nên không có cột chấm, gộp thay
      cho file `_ACH_CanKiemTraThuCong.xlsx` riêng của Milestone F cũ)."""
    _log        = log_callback or print
    ngay_str    = ngay_dt.strftime('%Y%m%d')
    output_path = os.path.join(output_dir, f'{ngay_str}_ACH_ConfirmMISdi.xlsx')

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})

    ws1 = workbook.add_worksheet('MIS_DI_CONFIRM')
    ws1.set_tab_color(_CAM)
    _viet_confirm_mis_di(workbook, ws1, _clean(df_mis_di, _COLS_MIS_DI_CONFIRM, 'MIS_DI_CONFIRM'))

    ws2 = workbook.add_worksheet('CAN_KIEM_TRA_THU_CONG')
    ws2.set_tab_color(_CAM)
    df_bi_loai_hien_thi = _clean(df_bi_loai, list(_COLS_CAN_KIEM_TRA_HIEN_THI.keys()), 'CAN_KIEM_TRA_THU_CONG')
    if df_bi_loai_hien_thi is not None and len(df_bi_loai_hien_thi) > 0:
        df_bi_loai_hien_thi = df_bi_loai_hien_thi.rename(columns=_COLS_CAN_KIEM_TRA_HIEN_THI)
    _viet_sheet(workbook, ws2, df_bi_loai_hien_thi, _CAM)

    workbook.close()
    _log(f'[DONE] File confirm MIS_đi: {output_path}')
    return output_path


def _viet_tong_ket(workbook, ws, session_id, ngay_display, ngay_display_t2,
                   n_di_khop, s_di_khop,
                   n_npo_di_thua, s_npo_di_thua,
                   n_huy_trong_ngay, s_huy_trong_ngay,
                   n_huy_khac_ngay, s_huy_khac_ngay,
                   n_mis_di_thua, s_mis_di_thua,
                   n_timeout, s_timeout,
                   n_den_khop, s_den_khop,
                   n_npo_den_thua, s_npo_den_thua,
                   n_mis_den_thua, s_mis_den_thua,
                   n_gw_di, s_gw_di,
                   n_osb_di_khop_cn, s_osb_di_khop_cn,
                   n_osb_den_khop_cn, s_osb_den_khop_cn,
                   s_qt_di_tong, s_qt_den_tong,
                   n_thuong_t2_di, s_thuong_t2_di,
                   n_osb_t2_di, s_osb_t2_di,
                   n_thuong_t2_den, s_thuong_t2_den,
                   n_osb_t2_den, s_osb_t2_den,
                   ly_do_thieu_tang1: str = None,
                   n_gwden_khop: int = None, s_gwden_khop: int = None,
                   n_napas_di: int = None, s_napas_di: int = None,
                   n_napas_den: int = None, s_napas_den: int = None):
    """Bảng tổng kết TONG_KET — layout song song 2 khối (Chiều Đi | Chiều Đến),
    theo mẫu Business Owner cung cấp (`G:\\NGUYEN TAC DOI CHIEU ACH\\Copy of chinh
    sua man hinh tong hop doi chieu ACH hang ngay.xlsx`, 2026-08-07). Cột A-C =
    chiều đi, cột E-G = chiều đến (cột D để trống làm khoảng cách). Nhãn ngày
    trong từng dòng dùng NGÀY THẬT (không phải chữ "t-1"/"t-2" tĩnh như trong file
    mẫu — Business Owner xác nhận rõ trong phiên). Các chỉ tiêu kỹ thuật không có
    trong mẫu (GW thừa, NPO_DI/MIS_DI thừa, SESSION_NULL_BI_LOAI) KHÔNG còn hiển
    thị ở đây — vẫn xem được ở sheet riêng cùng tên, không mất dữ liệu.

    ly_do_thieu_tang1 — 2026-08-21 (chi_tim_timeout): khi có, TOÀN BỘ chỉ tiêu
    Tầng 1 (mọi dòng trừ "GW đi"/"TO ko đi kênh", Tầng 0) bị bỏ trống + gắn nhãn
    "CHƯA ĐỐI CHIẾU ĐƯỢC" thay vì hiện số — tránh đọc nhầm 0 = đã khớp hết."""
    fmt_label   = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_section = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#DDEBF7'})
    fmt_header  = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#DDEBF7', 'border': 1})
    fmt_num     = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val     = workbook.add_format({'font_size': 10})
    fmt_canh_bao = workbook.add_format({'bold': True, 'font_size': 11, 'font_color': '#FFFFFF',
                                        'bg_color': _DO, 'text_wrap': True})

    ws.set_column(0, 0, 55); ws.set_column(1, 1, 14); ws.set_column(2, 2, 20)
    ws.set_column(3, 3, 3)
    ws.set_column(4, 4, 55); ws.set_column(5, 5, 14); ws.set_column(6, 6, 20)

    # chi_tim_timeout — Tầng 1 (mọi thứ trừ GW đi/Timeout) bị bỏ trống hẳn, KHÔNG
    # tính (kể cả để cộng dồn) khi thiếu GL02/MIS_đến — 0 giả sẽ làm sai luôn các
    # tổng dưới đây nếu không chặn ở đây.
    if ly_do_thieu_tang1:
        (n_di_khop, s_di_khop, n_npo_di_thua, s_npo_di_thua,
         n_huy_trong_ngay, s_huy_trong_ngay, n_huy_khac_ngay, s_huy_khac_ngay,
         n_mis_di_thua, s_mis_di_thua,
         n_den_khop, s_den_khop, n_npo_den_thua, s_npo_den_thua,
         n_mis_den_thua, s_mis_den_thua,
         n_osb_di_khop_cn, s_osb_di_khop_cn, n_osb_den_khop_cn, s_osb_den_khop_cn,
         s_qt_di_tong, s_qt_den_tong,
         n_thuong_t2_di, s_thuong_t2_di, n_osb_t2_di, s_osb_t2_di,
         n_thuong_t2_den, s_thuong_t2_den, n_osb_t2_den, s_osb_t2_den) = (None,) * 30

    # "Mis đi/đến" và "IPCAS" (Tổng NPO cần đối) suy ra từ các khoản đã có —
    # _tong_an_toan trả None nếu bất kỳ phần nào chưa tính được (Tầng 1 bị tắt).
    # Cộng thêm OSB đã khớp QT (n/s_osb_..._khop_cn) — Thảo xác nhận 15.09.2026:
    # Mục 2 loại OSB đã khớp QT khỏi MIS thừa vì bản chất vẫn là MIS đã khớp, loại
    # ra chỉ để MIS thừa còn lại là gd CHƯA hạch toán NPO/QT — không phải để giảm
    # tổng "Mis đi/đến ngày" ở TONG_KET. Thiếu cộng lại thì tổng này bị hụt đúng
    # phần OSB đã loại.
    n_mis_di_tong  = _tong_an_toan(n_di_khop, n_mis_di_thua, n_timeout, n_osb_di_khop_cn)
    s_mis_di_tong  = _tong_an_toan(s_di_khop, s_mis_di_thua, s_timeout, s_osb_di_khop_cn)
    n_mis_den_tong = _tong_an_toan(n_den_khop, n_mis_den_thua, n_osb_den_khop_cn)
    s_mis_den_tong = _tong_an_toan(s_den_khop, s_mis_den_thua, s_osb_den_khop_cn)

    n_npo_di_tong  = _tong_an_toan(n_di_khop, n_npo_di_thua, n_huy_trong_ngay, n_huy_khac_ngay)
    s_npo_di_tong  = _tong_an_toan(s_di_khop, s_npo_di_thua, s_huy_trong_ngay, s_huy_khac_ngay)
    n_npo_den_tong = _tong_an_toan(n_den_khop, n_npo_den_thua)
    s_npo_den_tong = _tong_an_toan(s_den_khop, s_npo_den_thua)

    _hau_to = f'  [CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu {ly_do_thieu_tang1}]' if ly_do_thieu_tang1 else ''

    lbl_di_khop_npo  = f'Lệnh đi ngày {ngay_display} hạch toán NPO ngày {ngay_display}{_hau_to}'
    lbl_den_khop_npo = f'Lệnh đến ngày {ngay_display} hạch toán NPO ngày {ngay_display}{_hau_to}'
    lbl_di_khop_qt   = f'Lệnh OSB đi ngày {ngay_display} hạch toán QT ngày {ngay_display}{_hau_to}'
    lbl_den_khop_qt  = f'Lệnh OSB đến ngày {ngay_display} hạch toán QT ngày {ngay_display}{_hau_to}'

    # Mỗi dòng: (label_di, n_di, s_di, label_den, n_den, s_den). label=None → ô
    # trống.
    # Mục 4 (bổ sung 11.09.2026) — GW đến khớp MIS_đến qua TXID/MSGREF. Cố ý KHÔNG
    # nằm trong nhóm bị bỏ trống bởi ly_do_thieu_tang1: Mục 4 chỉ phụ thuộc
    # MIS_đến, không phụ thuộc GL02 — thiếu GL02 đơn thuần không cản Mục 4 chạy.
    # None (Mục 4 không chạy vì thiếu file đến_GW hoặc thiếu MIS_đến) → để trống ô,
    # không hiện số 0 giả.
    lbl_gwden_khop = f'GW đến ngày {ngay_display} khớp MIS_đến (Mục 4)' if n_gwden_khop is not None else None

    # Mục 6/7 (bổ sung 11.09.2026 + 14.09.2026) — Tổng Napas (BC.03 PDF hoặc CSV chi
    # tiết, ưu tiên CSV — xem xuat_excel()) đối chiếu GHI NỢ=chiều đi/GHI CÓ=chiều
    # đến. Cố ý KHÔNG nằm trong nhóm bị bỏ trống bởi ly_do_thieu_tang1, giống Mục 4
    # — Mục 6/7 chỉ phụ thuộc file Napas tùy chọn của chính nó, không phụ thuộc
    # GL02/MIS_đến. None (không có file Napas) → để trống ô, không hiện số 0 giả.
    lbl_napas_di  = f'Napas Ghi nợ (đi) ngày {ngay_display}'  if n_napas_di  is not None else None
    lbl_napas_den = f'Napas Ghi có (đến) ngày {ngay_display}' if n_napas_den is not None else None

    def _hieu_an_toan(a, b):
        """Hiệu số CHÊNH LỆCH — None nếu 1 trong 2 vế chưa tính được (tránh 0 giả,
        cùng nguyên tắc _tong_an_toan() ở trên)."""
        return None if a is None or b is None else a - b

    n_chenh_napas_gw_di  = _hieu_an_toan(n_napas_di,  n_gw_di)
    s_chenh_napas_gw_di  = _hieu_an_toan(s_napas_di,  s_gw_di)
    # GW đến "tổng" không có ô riêng ở TONG_KET (chỉ có phần đã khớp MIS_đến, Mục
    # 4) — dùng n_gwden_khop/s_gwden_khop làm mốc so sánh GW đến duy nhất đang
    # hiển thị; None khi Mục 4 không chạy, đúng tinh thần để trống thay vì đoán.
    n_chenh_napas_gw_den = _hieu_an_toan(n_napas_den, n_gwden_khop)
    s_chenh_napas_gw_den = _hieu_an_toan(s_napas_den, s_gwden_khop)

    n_chenh_gw_mis_di    = _hieu_an_toan(n_gw_di,      n_mis_di_tong)
    s_chenh_gw_mis_di    = _hieu_an_toan(s_gw_di,      s_mis_di_tong)
    n_chenh_gw_mis_den   = _hieu_an_toan(n_gwden_khop, n_mis_den_tong)
    s_chenh_gw_mis_den   = _hieu_an_toan(s_gwden_khop, s_mis_den_tong)

    lbl_chenh_napas_gw_di  = 'Chênh lệch Napas − GW (đi)'  if n_chenh_napas_gw_di  is not None else None
    lbl_chenh_napas_gw_den = 'Chênh lệch Napas − GW (đến)' if n_chenh_napas_gw_den is not None else None
    lbl_chenh_gw_mis_di    = 'Chênh lệch GW − MIS (đi)'    if n_chenh_gw_mis_di    is not None else None
    lbl_chenh_gw_mis_den   = 'Chênh lệch GW − MIS (đến)'   if n_chenh_gw_mis_den   is not None else None

    rows = [
        (f'GW đi ngày {ngay_display}', n_gw_di, s_gw_di, None, None, None),
        (None, None, None, None, None, None),
        (None, None, None, lbl_gwden_khop, n_gwden_khop, s_gwden_khop),
        (None, None, None, None, None, None),
        (lbl_napas_di, n_napas_di, s_napas_di, lbl_napas_den, n_napas_den, s_napas_den),
        (lbl_chenh_napas_gw_di, n_chenh_napas_gw_di, s_chenh_napas_gw_di,
         lbl_chenh_napas_gw_den, n_chenh_napas_gw_den, s_chenh_napas_gw_den),
        (lbl_chenh_gw_mis_di, n_chenh_gw_mis_di, s_chenh_gw_mis_di,
         lbl_chenh_gw_mis_den, n_chenh_gw_mis_den, s_chenh_gw_mis_den),
        (None, None, None, None, None, None),
        (f'Mis đi ngày {ngay_display}{_hau_to}',  n_mis_di_tong,  s_mis_di_tong,
         f'Mis đến ngày {ngay_display}{_hau_to}', n_mis_den_tong, s_mis_den_tong),
        (None, None, None, None, None, None),
        (lbl_di_khop_npo, n_di_khop, s_di_khop, lbl_den_khop_npo, n_den_khop, s_den_khop),
        (None, None, None, None, None, None),
        (lbl_di_khop_qt, n_osb_di_khop_cn, s_osb_di_khop_cn,
         lbl_den_khop_qt, n_osb_den_khop_cn, s_osb_den_khop_cn),
        (None, None, None, None, None, None),
        (f'IPCAS{_hau_to}', n_npo_di_tong, s_npo_di_tong, f'IPCAS{_hau_to}', n_npo_den_tong, s_npo_den_tong),
        (None, None, None, None, None, None),
        # 1 dòng duy nhất mang cả nhãn lẫn số liệu T-2 (khớp mẫu cập nhật
        # 2026-08-07: công thức đặt ở CHÍNH dòng tiêu đề, không tách dòng phụ).
        (f'Điện thanh toán thường đi (không phải OSB) ngày {ngay_display_t2} hạch toán ngày {ngay_display}{_hau_to}',
         n_thuong_t2_di, s_thuong_t2_di,
         f'Điện thanh toán thường đến (không phải OSB) ngày {ngay_display_t2} hạch toán ngày {ngay_display}{_hau_to}',
         n_thuong_t2_den, s_thuong_t2_den),
        # Lặp lại Y HỆT dòng "khớp NPO cùng ngày" phía trên (cùng nhãn, cùng số
        # liệu n_di_khop/s_di_khop) — đúng mẫu (dòng 21, giống hệt dòng 10), làm
        # mốc so sánh ngay cạnh số liệu T-2 — KHÔNG được xoá dòng này (đã xoá
        # nhầm 1 lần, người dùng phản hồi lại 2026-08-07: "mong muốn có hai dòng
        # giống nhau"). Đối xứng với dòng lặp lại lbl_di_khop_qt ở mục OSB bên
        # dưới, đã làm đúng từ đầu.
        (lbl_di_khop_npo, n_di_khop, s_di_khop, lbl_den_khop_npo, n_den_khop, s_den_khop),
        (f'huỷ trong ngày {ngay_display}{_hau_to}',     n_huy_trong_ngay, s_huy_trong_ngay, None, None, None),
        (f'huỷ khác ngày {ngay_display}{_hau_to}',      n_huy_khac_ngay,  s_huy_khac_ngay,  None, None, None),
        (f'TO ko đi kênh ngày {ngay_display}', n_timeout,        s_timeout,        None, None, None),
        (None, None, None, None, None, None),
        (f'OSB{_hau_to}', None, s_qt_di_tong, f'OSB{_hau_to}', None, s_qt_den_tong),
        (None, None, None, None, None, None),
        (f'Điện OSB đi ngày {ngay_display_t2} hạch toán QT ngày {ngay_display}{_hau_to}', n_osb_t2_di, s_osb_t2_di,
         f'Điện OSB đến ngày {ngay_display_t2} hạch toán QT ngày {ngay_display}{_hau_to}', n_osb_t2_den, s_osb_t2_den),
        (lbl_di_khop_qt, n_osb_di_khop_cn, s_osb_di_khop_cn,
         lbl_den_khop_qt, n_osb_den_khop_cn, s_osb_den_khop_cn),
    ]

    row0 = 0
    if ly_do_thieu_tang1:
        ws.merge_range(0, 0, 0, 6,
            f'⚠ THIẾU FILE {ly_do_thieu_tang1.upper()} — CHỈ TÍNH ĐƯỢC "TO KO ĐI KÊNH" '
            f'(TIMEOUT KHÔNG ĐI KÊNH), CÁC CHỈ TIÊU KHÁC BÊN DƯỚI CHƯA ĐỐI CHIẾU ĐƯỢC',
            fmt_canh_bao)
        ws.set_row(0, 30)
        row0 = 1

    ws.write_string(row0 + 0, 0, 'Ngày đối chiếu', fmt_label)
    ws.write_string(row0 + 0, 1, ngay_display, fmt_val)
    ws.write_string(row0 + 1, 0, 'Session', fmt_label)
    ws.write_string(row0 + 1, 1, str(session_id), fmt_val)

    ws.write(row0 + 3, 1, 'Số món',  fmt_header); ws.write(row0 + 3, 2, 'Số tiền', fmt_header)
    ws.write(row0 + 3, 5, 'Số món',  fmt_header); ws.write(row0 + 3, 6, 'Số tiền', fmt_header)
    ws.write_string(row0 + 4, 0, 'CHIỀU ĐI',  fmt_section)
    ws.write_string(row0 + 4, 4, 'CHIỀU ĐẾN', fmt_section)

    def _ghi_so(row_idx, col, val):
        if val is None or val == '':
            return
        ws.write(row_idx, col, val, fmt_num)

    row_idx = row0 + 6
    for label_di, n_di, s_di, label_den, n_den, s_den in rows:
        if label_di is not None:
            ws.write_string(row_idx, 0, label_di, fmt_label)
            _ghi_so(row_idx, 1, n_di)
            _ghi_so(row_idx, 2, s_di)
        if label_den is not None:
            ws.write_string(row_idx, 4, label_den, fmt_label)
            _ghi_so(row_idx, 5, n_den)
            _ghi_so(row_idx, 6, s_den)
        row_idx += 1


def xuat_excel(output_path: str, session_id: str,
               df_mis_di_khop, df_npo_di_thua, df_mis_di_thua,
               df_timeout, df_mis_den_khop, df_npo_den_thua,
               df_mis_den_thua, df_gw_raw,
               df_cap_cn_tien=None,
               df_gw_thua_xac_dinh=None, df_gw_can_doi_chieu=None,
               df_dien_huy_trong_ngay=None, df_dien_huy_khac_ngay=None,
               df_session_null_bi_loai=None,
               df_osb_di_khop=None, df_osb_den_khop=None,
               df_qt_di=None, df_qt_den=None,
               df_ketqua_di_t2=None, df_ketqua_den_t2=None,
               df_gwden_khop=None,
               n_napas_di=None, s_napas_di=None, n_napas_den=None, s_napas_den=None,
               log_callback=None, summary_callback=None,
               ly_do_thieu_tang1: str = None):
    """n_napas_di/s_napas_di/n_napas_den/s_napas_den (Mục 6/7, bổ sung
    11.09.2026 + 14.09.2026) — số ĐÃ ĐƯỢC CHỌN NGUỒN bởi nơi gọi (main_from_dir()):
    ưu tiên CSV chi tiết (Mục 7) khi có, chỉ dùng PDF BC.03 (Mục 6) khi không có
    CSV cho chiều đó. Truyền thẳng số đã chọn (không phải DataFrame) vì việc chọn
    nguồn cần cả dict (PDF) lẫn DataFrame (CSV) — để logic đó ở main_from_dir(),
    nơi cả 2 nguồn đều sẵn có, tránh xuat_excel() phải biết về 2 định dạng input
    khác nhau."""

    output_dir      = os.path.dirname(os.path.abspath(output_path))
    ngay_str        = os.path.basename(output_path).replace('doi_chieu_', '').replace('.xlsx', '')
    ngay_dt_local   = datetime.strptime(ngay_str, '%Y%m%d')
    ngay_display    = ngay_dt_local.strftime('%d/%m/%Y')
    ngay_display_t2 = (ngay_dt_local - timedelta(days=1)).strftime('%d/%m/%Y')
    df_gw_clean  = df_gw_raw.drop(columns=['KEY_GW'], errors='ignore') if df_gw_raw is not None else None
    df_gw_thua_xac_dinh_clean = (
        df_gw_thua_xac_dinh.drop(columns=['KEY_GW'], errors='ignore')
        if df_gw_thua_xac_dinh is not None else None
    )

    # TONG_KET theo mẫu mới (2026-08-07) — số liệu OSB khớp cùng ngày, tổng QT, và
    # kết quả đối chiếu chéo ngày T-2, tính từ DataFrame đã có sẵn ở nơi gọi.
    n_gw_di = len(df_gw_raw) if df_gw_raw is not None else 0
    s_gw_di = _tong_tien(df_gw_raw, 'STTLMAMT')

    # Mục 4 (bổ sung 11.09.2026) — None nghĩa là Mục 4 KHÔNG chạy (thiếu file
    # đến_GW hoặc thiếu MIS_đến) → TONG_KET để trống ô, không hiện số 0 giả.
    n_gwden_khop = len(df_gwden_khop) if df_gwden_khop is not None else None
    s_gwden_khop = _tong_tien(df_gwden_khop, 'SO_TIEN') if df_gwden_khop is not None else None

    n_osb_di_khop_cn  = len(df_osb_di_khop)  if df_osb_di_khop  is not None else 0
    s_osb_di_khop_cn  = _tong_tien(df_osb_di_khop,  'SO_TIEN')
    n_osb_den_khop_cn = len(df_osb_den_khop) if df_osb_den_khop is not None else 0
    s_osb_den_khop_cn = _tong_tien(df_osb_den_khop, 'SO_TIEN')

    s_qt_di_tong  = _tong_tien(df_qt_di,  'SO_TIEN')
    s_qt_den_tong = _tong_tien(df_qt_den, 'SO_TIEN')

    def _dem_tong_ket_qua(df, nhan):
        if df is None or len(df) == 0:
            return 0, 0
        m = df['KET_QUA'] == nhan
        return int(m.sum()), _tong_tien(df[m], 'SO_TIEN')

    n_thuong_t2_di,  s_thuong_t2_di  = _dem_tong_ket_qua(df_ketqua_di_t2,  KETQUA_THUONG_KHOP)
    n_osb_t2_di,     s_osb_t2_di     = _dem_tong_ket_qua(df_ketqua_di_t2,  KETQUA_OSB_DI_KHOP)
    n_thuong_t2_den, s_thuong_t2_den = _dem_tong_ket_qua(df_ketqua_den_t2, KETQUA_THUONG_KHOP)
    n_osb_t2_den,    s_osb_t2_den    = _dem_tong_ket_qua(df_ketqua_den_t2, KETQUA_OSB_DEN_KHOP)

    n_mis_di_khop  = len(df_mis_di_khop)  if df_mis_di_khop  is not None else 0
    s_mis_di_khop  = _tong_tien(df_mis_di_khop,  'SO_TIEN')
    n_npo_di_thua  = len(df_npo_di_thua)  if df_npo_di_thua  is not None else 0
    s_npo_di_thua  = _tong_tien(df_npo_di_thua,  'CRAMOUNT')
    n_huy_trong_ngay = len(df_dien_huy_trong_ngay) if df_dien_huy_trong_ngay is not None else 0
    s_huy_trong_ngay = _tong_tien(df_dien_huy_trong_ngay, 'CRAMOUNT')
    n_huy_khac_ngay  = len(df_dien_huy_khac_ngay)  if df_dien_huy_khac_ngay  is not None else 0
    s_huy_khac_ngay  = _tong_tien(df_dien_huy_khac_ngay,  'CRAMOUNT')
    n_mis_di_thua  = len(df_mis_di_thua)  if df_mis_di_thua  is not None else 0
    s_mis_di_thua  = _tong_tien(df_mis_di_thua,  'SO_TIEN')
    n_timeout      = len(df_timeout)      if df_timeout      is not None else 0
    s_timeout      = _tong_tien(df_timeout,       'SO_TIEN')
    n_mis_den_khop = len(df_mis_den_khop) if df_mis_den_khop is not None else 0
    s_mis_den_khop = _tong_tien(df_mis_den_khop, 'SO_TIEN')
    n_npo_den_thua = len(df_npo_den_thua) if df_npo_den_thua is not None else 0
    s_npo_den_thua = _tong_tien(df_npo_den_thua, 'DRAMOUNT')
    n_mis_den_thua = len(df_mis_den_thua) if df_mis_den_thua is not None else 0
    s_mis_den_thua = _tong_tien(df_mis_den_thua, 'SO_TIEN')

    if summary_callback:
        summary_callback({
            'khop_npo_di':        n_mis_di_khop,       'tien_khop_npo_di':  s_mis_di_khop,
            'khop_npo_den':       n_mis_den_khop,       'tien_khop_npo_den': s_mis_den_khop,
            'khop_osb_di':        n_osb_di_khop_cn,     'tien_khop_osb_di':  s_osb_di_khop_cn,
            'khop_osb_den':       n_osb_den_khop_cn,    'tien_khop_osb_den': s_osb_den_khop_cn,
            'timeout':            n_timeout,            'tien_timeout':      s_timeout,
            'huy_trong_ngay':     n_huy_trong_ngay,      'tien_huy_trong_ngay': s_huy_trong_ngay,
            'huy_khac_ngay':      n_huy_khac_ngay,       'tien_huy_khac_ngay':  s_huy_khac_ngay,
            'thua_di':            n_npo_di_thua + n_mis_di_thua,
            'tien_thua_di':       s_npo_di_thua + s_mis_di_thua,
            'thua_den':           n_npo_den_thua + n_mis_den_thua,
            'tien_thua_den':      s_npo_den_thua + s_mis_den_thua,
        })

    df_gw_can_doi_chieu_clean = (
        df_gw_can_doi_chieu.drop(columns=['KEY_GW', 'CN tiền Hub'], errors='ignore')
        if df_gw_can_doi_chieu is not None else None
    )
    _log         = log_callback or print

    # 2026-08-21 (chi_tim_timeout) — sheet phụ thuộc GL02/MIS_đến hiện "CHƯA ĐỐI
    # CHIẾU ĐƯỢC" thay vì "(Không có dữ liệu)" khi df is None (bị bỏ qua vì thiếu
    # file, không phải 0 dòng thật) — None ở đây phân biệt msg cho từng sheet.
    _msg_thieu_tang1 = (
        f'CHƯA ĐỐI CHIẾU ĐƯỢC — thiếu file {ly_do_thieu_tang1}' if ly_do_thieu_tang1 else None
    )

    sheets = [
        ('TONG_KET',           None,                                                     '#FFFFFF', None),
        ('MIS_DI_KHOP',        _clean(df_mis_di_khop,  _COLS_MIS_DI, 'MIS_DI_KHOP'),   _XANH_LA, _msg_thieu_tang1),
        ('NPO_DI_THUA',        _clean(df_npo_di_thua,  _COLS_NPO_THUA, 'NPO_DI_THUA'), _DO, _msg_thieu_tang1),
        ('DIEN_DI_HUY_TRONG_NGAY', _clean(df_dien_huy_trong_ngay, _COLS_NPO, 'DIEN_DI_HUY_TRONG_NGAY'), _XANH_LAM, _msg_thieu_tang1),
        ('DIEN_DI_HUY_KHAC_NGAY',  _clean(df_dien_huy_khac_ngay,  _COLS_NPO, 'DIEN_DI_HUY_KHAC_NGAY'),  _XANH_LAM, _msg_thieu_tang1),
        ('MIS_DI_THUA',        _clean(df_mis_di_thua,  _COLS_MIS_DI, 'MIS_DI_THUA'),   _DO, _msg_thieu_tang1),
        ('TIMEOUT_KHONG_KENH', _clean(df_timeout, _COLS_TIMEOUT, 'TIMEOUT'),             _CAM, None),
        ('SESSION_NULL_BI_LOAI', df_session_null_bi_loai,                                _CAM, None),
        ('CAP_CN_TIEN',        df_cap_cn_tien,                                           _CAM, None),
        ('GW_THUA_XAC_DINH',   df_gw_thua_xac_dinh_clean,                                _DO, None),
        ('GW_CAN_DOI_CHIEU',   df_gw_can_doi_chieu_clean,                                _CAM, None),
        ('MIS_DEN_KHOP',       _clean(df_mis_den_khop, _COLS_MIS_DEN, 'MIS_DEN_KHOP'), _XANH_LA, _msg_thieu_tang1),
        ('NPO_DEN_THUA',       _clean(df_npo_den_thua, _COLS_NPO_THUA, 'NPO_DEN_THUA'), _DO, _msg_thieu_tang1),
        ('MIS_DEN_THUA',       _clean(df_mis_den_thua, _COLS_MIS_DEN, 'MIS_DEN_THUA'), _DO, _msg_thieu_tang1),
        ('RAW_GW',             df_gw_clean,                                              _XANH_LAM, None),
    ]

    workbook   = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False, 'constant_memory': True})
    csv_writes = []
    total      = len(sheets)

    with ThreadPoolExecutor(max_workers=3) as csv_pool:
        for i, (sheet_name, df, color, msg) in enumerate(sheets, 1):
            _log(f'[EXCEL] ({i}/{total}) Ghi sheet: {sheet_name}...')
            if df is not None and len(df) > CSV_THRESHOLD:
                csv_path = os.path.join(output_dir, f'{sheet_name}_{ngay_str}.csv')
                fut      = csv_pool.submit(df.to_csv, csv_path, index=False, encoding='utf-8-sig')
                csv_writes.append((sheet_name, csv_path, fut))
                ws = workbook.add_worksheet(sheet_name)
                ws.set_tab_color(color)
                ws.write(0, 0, f'[Dữ liệu lớn - xem file: {os.path.basename(csv_path)}]')
                ws.write(1, 0, f'Tổng số dòng: {len(df):,}')
                ws.write(2, 0, 'LƯU Ý: Mở file CSV qua Excel > Data > Từ Văn bản/CSV (không double-click trực tiếp).')
                _log(f'[CSV] {sheet_name}: {len(df):,} dòng → đang ghi nền...')
                continue

            ws = workbook.add_worksheet(sheet_name)
            ws.set_tab_color(color)
            if sheet_name == 'TONG_KET':
                _viet_tong_ket(
                    workbook, ws, session_id, ngay_display, ngay_display_t2,
                    n_mis_di_khop,      s_mis_di_khop,
                    n_npo_di_thua,      s_npo_di_thua,
                    n_huy_trong_ngay,   s_huy_trong_ngay,
                    n_huy_khac_ngay,    s_huy_khac_ngay,
                    n_mis_di_thua,      s_mis_di_thua,
                    n_timeout,          s_timeout,
                    n_mis_den_khop,     s_mis_den_khop,
                    n_npo_den_thua,     s_npo_den_thua,
                    n_mis_den_thua,     s_mis_den_thua,
                    n_gw_di, s_gw_di,
                    n_osb_di_khop_cn, s_osb_di_khop_cn,
                    n_osb_den_khop_cn, s_osb_den_khop_cn,
                    s_qt_di_tong, s_qt_den_tong,
                    n_thuong_t2_di, s_thuong_t2_di,
                    n_osb_t2_di, s_osb_t2_di,
                    n_thuong_t2_den, s_thuong_t2_den,
                    n_osb_t2_den, s_osb_t2_den,
                    ly_do_thieu_tang1=ly_do_thieu_tang1,
                    n_gwden_khop=n_gwden_khop, s_gwden_khop=s_gwden_khop,
                    n_napas_di=n_napas_di, s_napas_di=s_napas_di,
                    n_napas_den=n_napas_den, s_napas_den=s_napas_den,
                )
            elif sheet_name == 'DIEN_DI_HUY_KHAC_NGAY':
                _viet_sheet_co_tong(workbook, ws, df, color, 'CRAMOUNT', msg_khi_thieu=msg)
            else:
                _viet_sheet(workbook, ws, df, color, msg_khi_thieu=msg)

        workbook.close()
        _log(f'[DONE] Excel: {output_path}')

    for name, path, fut in csv_writes:
        fut.result()
        _log(f'       CSV  : {path}  ({name})')


# ─── Điểm 2 — file OSB riêng (không đụng doi_chieu_<ngày>.xlsx chính) ─────────

def _viet_tong_ket_osb(workbook, ws, session_id, ngay_str,
                       n_di_khop, s_di_khop, n_di_mis_thua, n_di_qt_thua,
                       n_den_khop, s_den_khop, n_den_mis_thua, n_den_qt_thua):
    fmt_label  = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10,
                                      'bg_color': '#DDEBF7', 'border': 1})
    fmt_num    = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val    = workbook.add_format({'font_size': 10})

    ws.write(0, 0, 'Chỉ tiêu',           fmt_header)
    ws.write(0, 1, 'Số giao dịch',       fmt_header)
    ws.write(0, 2, 'Tổng số tiền (VND)', fmt_header)
    ws.set_column(0, 0, 40); ws.set_column(1, 1, 16); ws.set_column(2, 2, 22)

    data = [
        ('Ngày đối chiếu', ngay_str, ''),
        ('Session',         session_id, ''),
        ('', '', ''),
        ('=== CHIỀU ĐI ===', '', ''),
        ('OSB đã quyết toán (MIS khớp QT đi)', n_di_khop, s_di_khop),
        ('OSB chưa khớp — phía MIS_đi thừa', n_di_mis_thua, ''),
        ('OSB chưa khớp — phía QT đi',        n_di_qt_thua, ''),
        ('', '', ''),
        ('=== CHIỀU ĐẾN ===', '', ''),
        ('OSB đã quyết toán (MIS khớp QT đến)', n_den_khop, s_den_khop),
        ('OSB chưa khớp — phía MIS_đến thừa', n_den_mis_thua, ''),
        ('OSB chưa khớp — phía QT đến',        n_den_qt_thua, ''),
    ]

    for row_idx, (label, val, tien) in enumerate(data, start=1):
        ws.write_string(row_idx, 0, label, fmt_label)
        if isinstance(val, int):
            ws.write(row_idx, 1, val, fmt_num)
        else:
            ws.write(row_idx, 1, val, fmt_val)
        if isinstance(tien, int) and tien > 0:
            ws.write(row_idx, 2, tien, fmt_num)
        elif tien:
            ws.write(row_idx, 2, tien, fmt_val)


def xuat_excel_osb(output_dir: str, session_id: str, ngay_dt: datetime,
                   df_osb_di_khop=None, df_di_chua_khop=None,
                   df_osb_den_khop=None, df_den_chua_khop=None,
                   log_callback=None) -> str:
    """Điểm 2 (2026-07-31, Implementation-notes.html mục 56/63b) — đối chiếu lệnh
    OSB (đi & đến) qua file Quyết toán OSB "QT", xuất RIÊNG khỏi
    doi_chieu_<ngày>.xlsx chính (không đụng số liệu/sheet báo cáo chính). 5 sheet:
    TONG_KET, OSB_DI_DA_QUYET_TOAN, OSB_DEN_DA_QUYET_TOAN, DI_CHUA_KHOP (gộp OSB-
    MIS chưa khớp + QT chưa khớp, phân biệt cột NGUON), DEN_CHUA_KHOP (tương tự)."""
    _log        = log_callback or print
    ngay_str    = ngay_dt.strftime('%Y%m%d')
    ngay_display = ngay_dt.strftime('%d/%m/%Y')
    output_path = os.path.join(output_dir, f'{ngay_str}_ACH_OSB.xlsx')

    def _bo_khoa(df, cols):
        return df.drop(columns=cols, errors='ignore') if df is not None else df

    df_di_khop_clean  = _bo_khoa(df_osb_di_khop,  ['KEY_HUB'])
    df_den_khop_clean = _bo_khoa(df_osb_den_khop, ['KEY_DEN_HUB'])
    df_di_ck_clean    = _bo_khoa(df_di_chua_khop,  ['KEY_HUB', 'CN_TRACE_TIEN'])
    df_den_ck_clean   = _bo_khoa(df_den_chua_khop, ['KEY_DEN_HUB', 'CN_TRACE_TIEN'])

    def _dem_nguon(df, nguon):
        return int((df['NGUON'] == nguon).sum()) if df is not None and len(df) else 0

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})

    ws0 = workbook.add_worksheet('TONG_KET')
    _viet_tong_ket_osb(
        workbook, ws0, session_id, ngay_display,
        len(df_osb_di_khop) if df_osb_di_khop is not None else 0,
        _tong_tien(df_osb_di_khop, 'SO_TIEN'),
        _dem_nguon(df_di_chua_khop, 'MIS'),
        _dem_nguon(df_di_chua_khop, 'QT'),
        len(df_osb_den_khop) if df_osb_den_khop is not None else 0,
        _tong_tien(df_osb_den_khop, 'SO_TIEN'),
        _dem_nguon(df_den_chua_khop, 'MIS'),
        _dem_nguon(df_den_chua_khop, 'QT'),
    )

    sheets = [
        ('OSB_DI_DA_QUYET_TOAN',  df_di_khop_clean,  _XANH_LA),
        ('OSB_DEN_DA_QUYET_TOAN', df_den_khop_clean, _XANH_LA),
        ('DI_CHUA_KHOP',          df_di_ck_clean,     _DO),
        ('DEN_CHUA_KHOP',         df_den_ck_clean,    _DO),
    ]
    for sheet_name, df, color in sheets:
        ws = workbook.add_worksheet(sheet_name)
        ws.set_tab_color(color)
        _viet_sheet(workbook, ws, df, color)

    workbook.close()
    _log(f'[DONE] File OSB: {output_path}')
    return output_path


# ─── Mục 4 (bổ sung 11.09.2026) — file GW đến riêng (không đụng doi_chieu_<ngày> ──
# .xlsx chính, giống Điểm 2/OSB) ───────────────────────────────────────────────

def _viet_tong_ket_gw_den(workbook, ws, session_id, ngay_str,
                          n_khop, s_khop, n_gw_thua, s_gw_thua,
                          n_mis_thua, s_mis_thua):
    fmt_label  = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10,
                                      'bg_color': '#DDEBF7', 'border': 1})
    fmt_num    = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val    = workbook.add_format({'font_size': 10})

    ws.write(0, 0, 'Chỉ tiêu',           fmt_header)
    ws.write(0, 1, 'Số giao dịch',       fmt_header)
    ws.write(0, 2, 'Tổng số tiền (VND)', fmt_header)
    ws.set_column(0, 0, 45); ws.set_column(1, 1, 16); ws.set_column(2, 2, 22)

    data = [
        ('Ngày đối chiếu', ngay_str, ''),
        ('Session',         session_id, ''),
        ('', '', ''),
        ('Khớp đúng (TXID MIS_đến = MSGREF GW đến)', n_khop, s_khop),
        ('GW thừa (chỉ có ở GW đến)',                 n_gw_thua, s_gw_thua),
        ('MIS_đến thừa (chỉ có ở MIS_đến)',           n_mis_thua, s_mis_thua),
    ]

    for row_idx, (label, val, tien) in enumerate(data, start=1):
        ws.write_string(row_idx, 0, label, fmt_label)
        if isinstance(val, int):
            ws.write(row_idx, 1, val, fmt_num)
        else:
            ws.write(row_idx, 1, val, fmt_val)
        if isinstance(tien, int) and tien > 0:
            ws.write(row_idx, 2, tien, fmt_num)
        elif tien:
            ws.write(row_idx, 2, tien, fmt_val)


def xuat_excel_gw_den(output_dir: str, session_id: str, ngay_dt: datetime,
                      df_khop=None, df_gw_thua=None, df_mis_thua=None,
                      log_callback=None) -> str:
    """Mục 4 (bổ sung 11.09.2026) — đối chiếu GW đến (PrcFlg ∈ {'Đã treo', 'Đã trả
    KH'}, đúng session) với MIS_đến qua TXID=MSGREF (`doi_chieu_gw_den()`). Xuất
    RIÊNG khỏi doi_chieu_<ngày>.xlsx chính — không đụng file/sheet chính, theo đúng
    phong cách `xuat_excel_osb()`: 1 sheet TONG_KET + các sheet chi tiết."""
    _log         = log_callback or print
    ngay_str     = ngay_dt.strftime('%Y%m%d')
    ngay_display = ngay_dt.strftime('%d/%m/%Y')
    output_path  = os.path.join(output_dir, f'{ngay_str}_ACH_GWDEN.xlsx')

    df_khop_clean = (
        df_khop.drop(columns=['TXID_SACH'], errors='ignore') if df_khop is not None else None
    )
    df_mis_thua_clean = (
        df_mis_thua.drop(columns=['TXID_SACH'], errors='ignore') if df_mis_thua is not None else None
    )

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})

    ws0 = workbook.add_worksheet('TONG_KET')
    _viet_tong_ket_gw_den(
        workbook, ws0, session_id, ngay_display,
        len(df_khop) if df_khop is not None else 0, _tong_tien(df_khop, 'SO_TIEN'),
        len(df_gw_thua) if df_gw_thua is not None else 0, _tong_tien(df_gw_thua, 'STTLMAMT'),
        len(df_mis_thua) if df_mis_thua is not None else 0, _tong_tien(df_mis_thua, 'SO_TIEN'),
    )

    sheets = [
        ('GWDEN_KHOP_DUNG', df_khop_clean,     _XANH_LA),
        ('GWDEN_THUA',      df_gw_thua,        _DO),
        ('MISDEN_THUA',     df_mis_thua_clean, _DO),
    ]
    for sheet_name, df, color in sheets:
        ws = workbook.add_worksheet(sheet_name)
        ws.set_tab_color(color)
        _viet_sheet(workbook, ws, df, color)

    workbook.close()
    _log(f'[DONE] File GW đến (Mục 4): {output_path}')
    return output_path


# ─── Mục 6/7 (bổ sung 11.09.2026 + 14.09.2026) — file Napas riêng (không đụng ──
# doi_chieu_<ngày>.xlsx chính, giống Điểm 2/OSB và Mục 4/GW đến) ──────────────

def _viet_tong_ket_napas(workbook, ws, session_id, ngay_str,
                         n_di_khop, s_di_khop, n_di_napas_thua, n_di_gw_thua,
                         n_den_khop, s_den_khop, n_den_napas_thua, n_den_gw_thua):
    fmt_label  = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10,
                                      'bg_color': '#DDEBF7', 'border': 1})
    fmt_num    = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val    = workbook.add_format({'font_size': 10})

    ws.write(0, 0, 'Chỉ tiêu',           fmt_header)
    ws.write(0, 1, 'Số giao dịch',       fmt_header)
    ws.write(0, 2, 'Tổng số tiền (VND)', fmt_header)
    ws.set_column(0, 0, 48); ws.set_column(1, 1, 16); ws.set_column(2, 2, 22)

    data = [
        ('Ngày đối chiếu', ngay_str, ''),
        ('Session',         session_id, ''),
        ('', '', ''),
        ('=== CHIỀU ĐI (CSV Napas ISS ⟷ GW đi) ===', '', ''),
        ('Khớp đúng (MsgId Napas = MSGREF GW đi)', n_di_khop, s_di_khop),
        ('Napas đi thừa (chỉ có ở CSV Napas)',      n_di_napas_thua, ''),
        ('GW đi thừa (chỉ có ở GW đi)',              n_di_gw_thua, ''),
        ('', '', ''),
        ('=== CHIỀU ĐẾN (CSV Napas BEN ⟷ GW đến, Mục 4) ===', '', ''),
        ('Khớp đúng (MsgId Napas = MSGREF GW đến)', n_den_khop, s_den_khop),
        ('Napas đến thừa (chỉ có ở CSV Napas)',      n_den_napas_thua, ''),
        ('GW đến thừa (chỉ có ở GW đến)',            n_den_gw_thua, ''),
    ]

    for row_idx, (label, val, tien) in enumerate(data, start=1):
        ws.write_string(row_idx, 0, label, fmt_label)
        if isinstance(val, int):
            ws.write(row_idx, 1, val, fmt_num)
        else:
            ws.write(row_idx, 1, val, fmt_val)
        if isinstance(tien, int) and tien > 0:
            ws.write(row_idx, 2, tien, fmt_num)
        elif tien:
            ws.write(row_idx, 2, tien, fmt_val)


def xuat_excel_napas(output_dir: str, session_id: str, ngay_dt: datetime,
                     df_di_khop=None, df_di_napas_thua=None, df_di_gw_thua=None,
                     df_den_khop=None, df_den_napas_thua=None, df_den_gw_thua=None,
                     log_callback=None) -> str | None:
    """Mục 7 (bổ sung 14.09.2026) — đối chiếu CSV Napas chi tiết (ISS/BEN) với GW
    qua MsgId=MSGREF (`doi_chieu_napas_gw()`, b15_napas.py). Xuất RIÊNG khỏi
    doi_chieu_<ngày>.xlsx chính, theo đúng phong cách `xuat_excel_gw_den()`: 1 sheet
    TONG_KET + sheet chi tiết mỗi chiều ĐÃ CHẠY ĐƯỢC (khớp / Napas lệch / GW lệch).
    Chiều nào không có CSV (cả 3 df đều None) → không thêm sheet chiều đó. Trả None
    nếu KHÔNG chiều nào chạy được (không có CSV Napas nào) — không tạo file thừa,
    giống `xuat_excel_mis_thua_t2()`."""
    da_chay_di  = df_di_khop is not None or df_di_napas_thua is not None or df_di_gw_thua is not None
    da_chay_den = df_den_khop is not None or df_den_napas_thua is not None or df_den_gw_thua is not None
    if not da_chay_di and not da_chay_den:
        return None

    _log         = log_callback or print
    ngay_str     = ngay_dt.strftime('%Y%m%d')
    ngay_display = ngay_dt.strftime('%d/%m/%Y')
    output_path  = os.path.join(output_dir, f'{ngay_str}_ACH_Napas.xlsx')

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})

    ws0 = workbook.add_worksheet('TONG_KET')
    _viet_tong_ket_napas(
        workbook, ws0, session_id, ngay_display,
        len(df_di_khop) if df_di_khop is not None else 0, _tong_tien(df_di_khop, 'SttlmAmount'),
        len(df_di_napas_thua) if df_di_napas_thua is not None else 0,
        len(df_di_gw_thua)    if df_di_gw_thua    is not None else 0,
        len(df_den_khop) if df_den_khop is not None else 0, _tong_tien(df_den_khop, 'SttlmAmount'),
        len(df_den_napas_thua) if df_den_napas_thua is not None else 0,
        len(df_den_gw_thua)    if df_den_gw_thua    is not None else 0,
    )

    sheets = []
    if da_chay_di:
        sheets += [
            ('NAPAS_DI_KHOP',    df_di_khop,       _XANH_LA),
            ('NAPAS_DI_THUA',    df_di_napas_thua, _DO),
            ('GW_DI_THUA_NAPAS', df_di_gw_thua,    _DO),
        ]
    if da_chay_den:
        sheets += [
            ('NAPAS_DEN_KHOP',    df_den_khop,       _XANH_LA),
            ('NAPAS_DEN_THUA',    df_den_napas_thua, _DO),
            ('GW_DEN_THUA_NAPAS', df_den_gw_thua,    _DO),
        ]

    csv_writes = []
    with ThreadPoolExecutor(max_workers=3) as csv_pool:
        for sheet_name, df, color in sheets:
            ws = workbook.add_worksheet(sheet_name)
            ws.set_tab_color(color)
            if df is not None and len(df) > CSV_THRESHOLD:
                csv_path = os.path.join(output_dir, f'{sheet_name}_{ngay_str}.csv')
                fut      = csv_pool.submit(df.to_csv, csv_path, index=False, encoding='utf-8-sig')
                csv_writes.append((sheet_name, csv_path, fut))
                ws.write(0, 0, f'[Dữ liệu lớn - xem file: {os.path.basename(csv_path)}]')
                ws.write(1, 0, f'Tổng số dòng: {len(df):,}')
                ws.write(2, 0, 'LƯU Ý: Mở file CSV qua Excel > Data > Từ Văn bản/CSV (không double-click trực tiếp).')
                _log(f'[CSV] {sheet_name}: {len(df):,} dòng → đang ghi nền...')
                continue
            _viet_sheet(workbook, ws, df, color)

        workbook.close()

    for name, path, fut in csv_writes:
        fut.result()
        _log(f'       CSV  : {path}  ({name})')

    _log(f'[DONE] File Napas (Mục 6/7): {output_path}')
    return output_path


# ─── Báo cáo "KẾT QUẢ" đối chiếu MIS thừa T-2 (docx nghiệp vụ NGUYEN TAC DOI ──
# CHIEU DIEN MIS THUA NGAY T-1, 2026-08-07) — xuất RIÊNG khỏi doi_chieu_<ngày>
# .xlsx chính, giống Điểm 2/OSB. Góc nhìn NGƯỢC với cột GHI_CHU_T2 (Điểm 4): gắn
# nhãn lên chính MIS thừa T-2, không phải lên NPO thừa T-1.

def xuat_excel_mis_thua_t2(output_dir: str, ngay_dt: datetime,
                           df_ketqua_di=None, df_ketqua_den=None,
                           log_callback=None) -> str | None:
    """Trả None nếu cả 2 df đều None/rỗng (không có gì để báo cáo, không tạo file
    thừa — đối xứng cách `xuat_excel_osb()` chỉ gọi khi có QT)."""
    _log = log_callback or print
    sheets_data = [
        ('MIS_DI_THUA_T2_KETQUA',  df_ketqua_di),
        ('MIS_DEN_THUA_T2_KETQUA', df_ketqua_den),
    ]
    if all(df is None or len(df) == 0 for _, df in sheets_data):
        return None

    ngay_str    = ngay_dt.strftime('%Y%m%d')
    output_path = os.path.join(output_dir, f'{ngay_str}_ACH_MISThuaT2.xlsx')

    workbook   = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})
    csv_writes = []

    with ThreadPoolExecutor(max_workers=2) as csv_pool:
        for sheet_name, df in sheets_data:
            ws = workbook.add_worksheet(sheet_name)
            ws.set_tab_color(_CAM)
            if df is not None and len(df) > CSV_THRESHOLD:
                csv_path = os.path.join(output_dir, f'{sheet_name}_{ngay_str}.csv')
                fut      = csv_pool.submit(df.to_csv, csv_path, index=False, encoding='utf-8-sig')
                csv_writes.append((sheet_name, csv_path, fut))
                ws.write(0, 0, f'[Dữ liệu lớn - xem file: {os.path.basename(csv_path)}]')
                ws.write(1, 0, f'Tổng số dòng: {len(df):,}')
                ws.write(2, 0, 'LƯU Ý: Mở file CSV qua Excel > Data > Từ Văn bản/CSV (không double-click trực tiếp).')
                _log(f'[CSV] {sheet_name}: {len(df):,} dòng → đang ghi nền...')
                continue
            _viet_sheet(workbook, ws, df, _CAM)

        workbook.close()

    for name, path, fut in csv_writes:
        fut.result()
        _log(f'       CSV  : {path}  ({name})')

    _log(f'[DONE] File KẾT QUẢ MIS thừa T-2: {output_path}')
    return output_path


def xuat_excel_huy_cheo_ngay_t2(output_dir: str, ngay_dt: datetime,
                                df_npo_thua_t2_ketqua, df_huy_khac_ngay_ketqua,
                                log_callback=None,
                                df_qt_thua_t2_ketqua=None,
                                df_huy_khac_ngay_qt_ketqua=None) -> str | None:
    """Mục 5 (11.09.2026) — báo cáo đối chiếu chéo NPO_đi thừa T-2 ⟷ huỷ khác ngày
    T-1, 2 sheet: NPO_THUA_T2_KETQUA, HUY_KHAC_NGAY_KETQUA. Chỉ xuất khi có ít
    nhất 1 trong 2 nguồn (NPO hoặc QT) có file T-2 để đối chiếu.

    Mục 5.1 (14.09.2026) — thêm 2 sheet QT_THUA_T2_KETQUA/HUY_KHAC_NGAY_QT_KETQUA
    khi có (tham số tùy chọn, None = bỏ qua, không đổi hành vi cũ của 2 sheet
    NPO). Điều kiện xuất file đổi từ "chỉ cần df_npo_thua_t2_ketqua" sang "1
    trong 2 nguồn có" — nếu giữ nguyên điều kiện cũ, ngày không có file NPO_đi
    thừa T-2 nhưng CÓ file QT đi thừa T-2 sẽ bị bỏ qua hẳn cả sheet QT, im lặng
    mất báo cáo Mục 5.1."""
    if df_npo_thua_t2_ketqua is None and df_qt_thua_t2_ketqua is None:
        return None
    _log = log_callback or print
    ngay_str    = ngay_dt.strftime('%Y%m%d')
    output_path = os.path.join(output_dir, f'{ngay_str}_ACH_HuyCheoNgay.xlsx')
    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})
    ws1 = workbook.add_worksheet('NPO_THUA_T2_KETQUA')
    _viet_sheet(workbook, ws1, df_npo_thua_t2_ketqua, _CAM)
    ws2 = workbook.add_worksheet('HUY_KHAC_NGAY_KETQUA')
    _viet_sheet(workbook, ws2, df_huy_khac_ngay_ketqua, _CAM)
    if df_qt_thua_t2_ketqua is not None:
        ws3 = workbook.add_worksheet('QT_THUA_T2_KETQUA')
        _viet_sheet(workbook, ws3, df_qt_thua_t2_ketqua, _CAM)
    if df_huy_khac_ngay_qt_ketqua is not None:
        ws4 = workbook.add_worksheet('HUY_KHAC_NGAY_QT_KETQUA')
        _viet_sheet(workbook, ws4, df_huy_khac_ngay_qt_ketqua, _CAM)
    workbook.close()
    _log(f'[DONE] File đối chiếu chéo huỷ: {output_path}')
    return output_path


def xuat_excel_timeout_cu(output_dir: str, ngay_dt: datetime,
                          df_timeout_cu_ketqua=None, log_callback=None) -> str | None:
    """Mục 8 (bổ sung 14.09.2026) — báo cáo đối chiếu "TO ko đi kênh ngày cũ" (input
    tuỳ chọn người dùng tự nạp thêm) với NPO_đi thừa/QT_đi thừa/Huỷ trong ngày của
    ngày đang chạy (`doi_chieu_timeout_cu()` ở b12_ghi_chu_timeout.py). Chỉ xuất
    khi có ít nhất 1 file timeout ngày cũ được tìm thấy — không tạo file rỗng khi
    không ai cung cấp file này (đối xứng `xuat_excel_mis_thua_t2()`)."""
    if df_timeout_cu_ketqua is None or len(df_timeout_cu_ketqua) == 0:
        return None
    _log        = log_callback or print
    ngay_str    = ngay_dt.strftime('%Y%m%d')
    output_path = os.path.join(output_dir, f'{ngay_str}_ACH_TimeoutCu.xlsx')

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False})
    ws = workbook.add_worksheet('TIMEOUT_CU_KETQUA')
    ws.set_tab_color(_CAM)
    if len(df_timeout_cu_ketqua) > CSV_THRESHOLD:
        csv_path = os.path.join(output_dir, f'TIMEOUT_CU_KETQUA_{ngay_str}.csv')
        df_timeout_cu_ketqua.to_csv(csv_path, index=False, encoding='utf-8-sig')
        ws.write(0, 0, f'[Dữ liệu lớn - xem file: {os.path.basename(csv_path)}]')
        ws.write(1, 0, f'Tổng số dòng: {len(df_timeout_cu_ketqua):,}')
        ws.write(2, 0, 'LƯU Ý: Mở file CSV qua Excel > Data > Từ Văn bản/CSV (không double-click trực tiếp).')
        _log(f'[CSV] TIMEOUT_CU_KETQUA: {len(df_timeout_cu_ketqua):,} dòng → {csv_path}')
    else:
        _viet_sheet(workbook, ws, df_timeout_cu_ketqua, _CAM)
    workbook.close()
    _log(f'[DONE] File Timeout ngày cũ (Mục 8): {output_path}')
    return output_path


# ─── Cancel helper ────────────────────────────────────────────────────────────

def _cancelled(ev) -> bool:
    return ev is not None and ev.is_set()


# ─── main_from_dir (dùng cho Web UI) ─────────────────────────────────────────

def main_from_dir(input_dir: str, output_dir: str,
                  ngay: str = None, log_callback=None,
                  cancel_event=None,
                  dung_sau_mis_di: bool = False,
                  xac_nhan_path: str = None,
                  summary_callback=None,
                  chi_tim_timeout: bool = False) -> str | None:
    """
    Chạy pipeline đối chiếu ACH từ thư mục đã có file.
    Trả về đường dẫn file .xlsx kết quả, hoặc None nếu cancelled.
    Thread-safe: không mutate config module-level.

    summary_callback — nếu có, được gọi ĐÚNG 1 LẦN ngay trước khi ghi Excel (khi
    chạy hết Phase 2, KHÔNG áp dụng ở nhánh dừng Checkpoint `dung_sau_mis_di`) với
    dict số liệu các nhóm nghiệp vụ thật (khớp NPO/OSB đi-đến, timeout, huỷ,
    thừa...) — phục vụ hiển thị "Kết quả tạm thời" ở UI, không ảnh hưởng file xuất.

    chi_tim_timeout — 2026-08-21 (xem project_ach_gl02_optional_tiered_deps): mặc
    định False giữ nguyên hành vi cũ (bắt buộc đủ GL02 + MIS_đến×2, thiếu là raise
    FileNotFoundError). True cho phép chạy khi thiếu GL02 và/hoặc MIS_đến — CHỈ
    tính phần Tầng 0 (Timeout không đi kênh + MIS_đi khớp GW + GW-thừa +
    Checkpoint, độc lập GL02/MIS_đến), Tầng 1 (NPO/MIS thừa đi-đến, huỷ, Điểm 2
    OSB, Điểm 4 chéo ngày T-2) bị TẮT HẲN và ghi rõ "CHƯA ĐỐI CHIẾU ĐƯỢC" thay vì
    hiện số 0 (tránh hiểu nhầm "đã khớp hết" — xem feedback_binary_match_status).
    KHÔNG miễn trừ yêu cầu tối thiểu PDF+GW+MIS_đi×2 — thiếu 1 trong 3 vẫn raise.

    dung_sau_mis_di=True — Checkpoint xác nhận thủ công tại MIS_đi (Điểm 1,
    2026-07-31 — Bước 1): dừng ngay sau `_process_mis_di()` (bước 5), TRƯỚC khi gọi
    `khop_voi_gw()`, xuất file confirm MIS_đi (2 sheet) thay vì chạy tiếp
    khop_voi_gw()/Phase 2/báo cáo cuối. Mặc định False.

    xac_nhan_path — Checkpoint xác nhận thủ công (Bước 3): đường dẫn file confirm
    (Bước 1) đã được người đối chiếu điền (cột LOAI_BO + khu bổ sung REFHUB). Nếu
    có, áp dụng `ap_dung_confirm_mis_di()` (Bước 2) NGAY SAU `_process_mis_di()`,
    TRƯỚC khi gọi `khop_voi_gw()`, để tính MIS_đi chuẩn — rồi chạy tiếp
    `khop_voi_gw()`/Phase 2/báo cáo cuối như bình thường, KHÔNG dừng lại lần 2 (đã
    bỏ hẳn Checkpoint xác nhận Timeout cũ). Không dùng đồng thời với
    dung_sau_mis_di=True (mutually exclusive — dung_sau_mis_di luôn dừng trước).
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    if ngay:
        ngay_dt      = datetime.strptime(ngay.strip(), '%d/%m/%Y')
        ngay_str_cfg = ngay.strip()
    else:
        auto_ngay = _tim_ngay_tu_pdf(input_dir)
        if auto_ngay:
            ngay_dt      = datetime.strptime(auto_ngay, '%d/%m/%Y')
            ngay_str_cfg = auto_ngay
            log(f'[AUTO] Phát hiện ngày đối chiếu từ PDF: {ngay_str_cfg}')
        else:
            ngay_dt      = _cfg.NGAY_DT
            ngay_str_cfg = ngay_dt.strftime('%d/%m/%Y')

    os.makedirs(output_dir, exist_ok=True)

    ngay_check  = ngay_dt.strftime('%Y%m%d')
    output_xlsx = os.path.join(output_dir, f'doi_chieu_{ngay_check}.xlsx')
    if os.path.exists(output_xlsx):
        try:
            with open(output_xlsx, 'a'):
                pass
        except PermissionError:
            raise PermissionError(
                f'[LỖI] File đang mở trong Excel. Vui lòng ĐÓNG FILE rồi chạy lại:\n'
                f'       {os.path.abspath(output_xlsx)}'
            )

    log(f'Ngày đối chiếu: {ngay_str_cfg}')

    session_id    = doc_session(input_dir, log_callback)
    gl02_files    = _tim_file(input_dir, 'GL02*.zip')
    gw_path       = _tim_gw_xlsx(input_dir, log_callback)
    gw_den_path   = _tim_gw_den_xlsx(input_dir, log_callback)  # Mục 4 — tùy chọn, None = bỏ qua
    mis_di_files  = _tim_file(input_dir, '*_DI_*.zip')
    mis_den_files = _tim_file(input_dir, '*_DEN_*.zip')

    # Tầng 0 (Timeout không đi kênh + GW-thừa + Checkpoint) — LUÔN bắt buộc, không
    # được miễn trừ bởi chi_tim_timeout: đây là mức tối thiểu thật sự.
    if len(mis_di_files) < 2:
        raise FileNotFoundError(f'Cần 2 file MIS_DI zip, chỉ tìm thấy {len(mis_di_files)}')

    # Tầng 1 (NPO/MIS thừa đi-đến, huỷ, Điểm 2/4) — cần GL02 + MIS_đến×2. Bắt buộc
    # như cũ trừ khi chi_tim_timeout=True (2026-08-21, xem
    # project_ach_gl02_optional_tiered_deps): khi đó cho phép chạy thiếu, Tầng 1 sẽ
    # tự tắt và ghi rõ "CHƯA ĐỐI CHIẾU ĐƯỢC" (xử lý ở dưới), không phải raise.
    thieu_gl02    = not gl02_files
    thieu_mis_den = len(mis_den_files) < 2
    if not chi_tim_timeout:
        if thieu_gl02:
            raise FileNotFoundError('Không tìm thấy GL02*.zip')
        if thieu_mis_den:
            raise FileNotFoundError(f'Cần 2 file MIS_DEN zip, chỉ tìm thấy {len(mis_den_files)}')
    tang1_thieu = thieu_gl02 or thieu_mis_den
    ly_do_thieu_tang1 = ', '.join(
        n for n, thieu in (('GL02', thieu_gl02), ('MIS_đến', thieu_mis_den)) if thieu
    ) or None

    # Điểm 4 (tùy chọn) — file MIS thừa T-2 do chương trình tự xuất ra lần chạy
    # trước, đính kèm để đối chiếu chéo ngày. Không có → bỏ qua, không chặn luồng
    # chính (đúng tinh thần file tùy chọn như Điểm 2/QT).
    mis_di_thua_t2_files  = _tim_file_thua_t2(input_dir, 'di')
    mis_den_thua_t2_files = _tim_file_thua_t2(input_dir, 'den')
    if len(mis_di_thua_t2_files) > 1:
        raise FileNotFoundError(
            f'Có nhiều hơn 1 file MIS_đi thừa T-2 (MIS_DI_THUA*.csv/.xlsx hoặc "MIS đi thừa*") — '
            f'giữ lại đúng 1 file: {mis_di_thua_t2_files}'
        )
    if len(mis_den_thua_t2_files) > 1:
        raise FileNotFoundError(
            f'Có nhiều hơn 1 file MIS_đến thừa T-2 (MIS_DEN_THUA*.csv/.xlsx hoặc "MIS đến thừa*") — '
            f'giữ lại đúng 1 file: {mis_den_thua_t2_files}'
        )

    npo_di_thua_t2_files = _tim_file_npo_di_thua_t2(input_dir)
    if len(npo_di_thua_t2_files) > 1:
        raise FileNotFoundError(
            f'Có nhiều hơn 1 file NPO_đi thừa T-2 — giữ lại đúng 1 file: {npo_di_thua_t2_files}'
        )

    # Mục 5.1 (bổ sung 14.09.2026) — đối xứng NPO_đi thừa T-2 ở trên, nguồn QT.
    qt_di_thua_t2_files = _tim_file_qt_di_thua_t2(input_dir)
    if len(qt_di_thua_t2_files) > 1:
        raise FileNotFoundError(
            f'Có nhiều hơn 1 file QT đi thừa T-2 — giữ lại đúng 1 file: {qt_di_thua_t2_files}'
        )

    # Mục 8 (bổ sung 14.09.2026, tùy chọn) — file "TO ko đi kênh ngày cũ", KHÔNG
    # giới hạn số lượng (đối chiếu gộp toàn bộ, xem doi_chieu_timeout_cu() ở B12).
    timeout_cu_files = _tim_file_timeout_cu(input_dir)

    # Điểm 2 (tùy chọn) — file Quyết toán OSB "QT" (đi và/hoặc đến, tự phân loại
    # theo nội dung cột 'Chiều giao dịch', không theo tên file). Không có → bỏ qua
    # nhánh OSB, luồng ACH chính vẫn chạy bình thường.
    qt_files = _tim_file_ngoai_output(input_dir, 'QT*.xlsx')
    df_qt_di, df_qt_den = None, None
    for qt_path in qt_files:
        qt_chieu, df_qt_1file = xu_ly_qt(qt_path, log_callback)
        if qt_chieu == 'đi':
            if df_qt_di is not None:
                raise FileNotFoundError(
                    f'Có nhiều hơn 1 file QT chiều đi trong thư mục — giữ lại đúng 1 file: {qt_path}'
                )
            df_qt_di = df_qt_1file
        else:
            if df_qt_den is not None:
                raise FileNotFoundError(
                    f'Có nhiều hơn 1 file QT chiều đến trong thư mục — giữ lại đúng 1 file: {qt_path}'
                )
            df_qt_den = df_qt_1file

    # Mục 6 (bổ sung 11.09.2026, tùy chọn) — báo cáo Napas BC.03 dạng PDF. Đọc NGAY
    # (không đợi Phase 1) vì hoàn toàn độc lập với GL02/MIS/GW — không có file →
    # bỏ qua toàn bộ Mục 6 (không raise, đúng tinh thần input tùy chọn như Điểm
    # 2/QT, Mục 4). n_napas_di/s_napas_di/n_napas_den/s_napas_den giữ giá trị PDF
    # ban đầu — có thể bị Mục 7 (CSV chi tiết) GHI ĐÈ ưu tiên bên dưới, sau Phase 1.
    #
    # `_tim_napas_pdf()` dò theo ĐUÔI FILE thôi (không sniff nội dung như
    # `_tim_gw_xlsx()`/`_tim_gw_den_xlsx()` làm với 'BRCD'), vì cùng file .pdf này
    # cũng được `_tim_ngay_tu_pdf()` dùng để tự nhận ngày TỪ TÊN FILE từ trước khi
    # có Mục 6 — không đọc nội dung. Vì vậy nếu file KHÔNG PHẢI báo cáo Napas hợp lệ
    # (PDF hỏng, hoặc PDF khác lẫn vào thư mục), chỉ log WARN + bỏ qua Mục 6, KHÔNG
    # raise chặn cả luồng chính — một PDF lạ không liên quan không được phép làm
    # hỏng toàn bộ đối chiếu GL02/MIS/GW.
    napas_pdf_path = _tim_napas_pdf(input_dir)
    n_napas_di = s_napas_di = n_napas_den = s_napas_den = None
    if napas_pdf_path:
        try:
            napas_pdf_ketqua = doc_pdf_napas(napas_pdf_path)
        except Exception as e:
            log(f"[Mục 6][WARN] Bỏ qua — {os.path.basename(napas_pdf_path)} không đọc được như "
                f"báo cáo Napas BC.03 hợp lệ: {e}")
        else:
            n_napas_di, s_napas_di   = napas_pdf_ketqua['n_di'],  napas_pdf_ketqua['s_di']
            n_napas_den, s_napas_den = napas_pdf_ketqua['n_den'], napas_pdf_ketqua['s_den']
            log(f'[Mục 6] Báo cáo Napas BC.03 ({os.path.basename(napas_pdf_path)}): '
                f'Ghi nợ(đi) SL={n_napas_di:,} Giá trị={s_napas_di:,} | '
                f'Ghi có(đến) SL={n_napas_den:,} Giá trị={s_napas_den:,}')

    # Mục 7 (bổ sung 14.09.2026, tùy chọn) — CSV Napas chi tiết ISS (đi)/BEN (đến).
    # Chỉ DÒ file ở đây — đối chiếu với GW thật sự chạy sau Phase 1 (cần df_gw_raw/
    # df_gw_den sẵn sàng).
    napas_iss_path = _tim_napas_csv(input_dir, 'ISS')
    napas_ben_path = _tim_napas_csv(input_dir, 'BEN')

    log(f'Tìm thấy: GL02={len(gl02_files)}, DI={len(mis_di_files)}, DEN={len(mis_den_files)}, '
        f'MIS_đi thừa T-2={len(mis_di_thua_t2_files)}, MIS_đến thừa T-2={len(mis_den_thua_t2_files)}, '
        f'NPO_đi thừa T-2={len(npo_di_thua_t2_files)}, QT đi thừa T-2={len(qt_di_thua_t2_files)}, '
        f'TO ko đi kênh ngày cũ (Mục 8)={len(timeout_cu_files)}, '
        f'QT đi={"có" if df_qt_di is not None else "không"}, QT đến={"có" if df_qt_den is not None else "không"}, '
        f'GW đến (Mục 4)={"có" if gw_den_path else "không"}, '
        f'Napas PDF (Mục 6)={"có" if napas_pdf_path else "không"}, '
        f'Napas CSV ISS/BEN (Mục 7)={"có" if napas_iss_path else "không"}/{"có" if napas_ben_path else "không"}')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng. Không xử lý.')
        return None

    _t0 = time.perf_counter()

    # Phase 1: B2 + B3 + B6 + B4_IO + B13(Mục 4, tùy chọn) song song. GL02/MIS_đến
    # chỉ submit khi có đủ file — chi_tim_timeout=True cho phép thiếu, npo_di/
    # npo_den/df_mis_den ở lại None (Tầng 1 sẽ tự tắt ở Phase 2 bên dưới). GW đến
    # chỉ submit khi tìm thấy file (Mục 4 là input tùy chọn, không chặn luồng chính).
    with ThreadPoolExecutor(max_workers=5) as ex:
        f_gl02       = ex.submit(xu_ly_gl02, gl02_files[0], log_callback) if not thieu_gl02 else None
        f_gw         = ex.submit(xu_ly_gw,        gw_path, session_id, log_callback)
        f_mis_den    = (
            ex.submit(xu_ly_mis_den, mis_den_files, session_id, ngay_dt, log_callback)
            if not thieu_mis_den else None
        )
        f_mis_di_raw = ex.submit(_doc_mis_di_raw, mis_di_files, session_id, log_callback)
        f_gw_den     = (
            ex.submit(xu_ly_gw_den, gw_den_path, session_id, log_callback)
            if gw_den_path else None
        )

        dict_gw_count, df_gw_raw, df_gw_goc = f_gw.result()

        if _cancelled(cancel_event):
            log('[CANCELLED] Người dùng đã dừng sau B3.')
            if f_gl02: f_gl02.result()
            if f_mis_den: f_mis_den.result()
            f_mis_di_raw.result()
            if f_gw_den: f_gw_den.result()
            return None

        df_mis_di_data = f_mis_di_raw.result()
        # Mục 2 — bỏ trạng thái CALD/ERPO/TPER (bước 1), lọc session (bước 2).
        df_mis_di = _process_mis_di(
            df_mis_di_data, session_id, ngay_dt, df_gw_goc, log_callback,
        )

        npo_di, npo_den = f_gl02.result() if f_gl02 else (None, None)
        df_mis_den      = f_mis_den.result() if f_mis_den else None
        df_gw_den       = f_gw_den.result()  if f_gw_den else None

    log(f'[TIMING] Phase 1 IO: {time.perf_counter()-_t0:.1f}s')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng sau Phase 1.')
        return None

    # Mục 4 (bổ sung 11.09.2026) — đối chiếu GW đến với MIS_đến qua TXID/MSGREF,
    # NGAY SAU khi df_mis_den sẵn sàng. Thiếu 1 trong 2 (không có file đến_GW, hoặc
    # thiếu MIS_đến do chi_tim_timeout) → bỏ qua nhánh, KHÔNG raise, không chặn
    # luồng chính (đúng tinh thần file tùy chọn như Điểm 2/OSB).
    df_gwden_khop = df_gwden_thua = df_misden_thua_gwden = None
    if df_gw_den is not None and df_mis_den is not None:
        df_gwden_khop, df_gwden_thua, df_misden_thua_gwden = doi_chieu_gw_den(
            df_gw_den, df_mis_den, log_callback,
        )
    elif df_gw_den is not None:
        log('[Mục 4] Bỏ qua đối chiếu GW đến — thiếu MIS_đến (GL02/MIS_đến chưa đủ).')

    # Mục 7 (bổ sung 14.09.2026) — đối chiếu CSV Napas chi tiết (ISS/BEN) với GW
    # qua MsgId=MSGREF, ngay khi df_gw_raw/df_gw_den sẵn sàng. Chiều đi chỉ cần
    # df_gw_raw (luôn có, không phụ thuộc GL02/MIS_đến). Chiều đến cần df_gw_den —
    # KHÔNG cần df_mis_den (khác điều kiện Mục 4): thiếu BEN, hoặc có BEN nhưng
    # thiếu file đến_GW → bỏ qua nhánh chi tiết chiều đến, KHÔNG raise.
    df_napas_di_khop = df_napas_di_thua = df_gwdi_thua_napas = None
    if napas_iss_path:
        df_napas_iss = doc_napas_csv(napas_iss_path, log_callback)
        # TONG_KET ưu tiên số từ CSV chi tiết (đếm được từng dòng) — ghi đè số PDF
        # (Mục 6) đã gán ở trên, CHỈ dùng PDF khi không có CSV cho chiều này.
        n_napas_di = len(df_napas_iss)
        s_napas_di = _tong_tien(df_napas_iss, 'SttlmAmount')
        df_napas_di_khop, df_napas_di_thua, df_gwdi_thua_napas = doi_chieu_napas_gw(
            df_napas_iss, df_gw_raw, 'MSGREF', log_callback,
        )
        log('[Mục 6/7] TONG_KET chiều đi lấy số từ CSV chi tiết (có ISS).')
    elif n_napas_di is not None:
        log('[Mục 6/7] TONG_KET chiều đi lấy số từ PDF (không có ISS).')

    df_napas_den_khop = df_napas_den_thua = df_gwden_thua_napas = None
    if napas_ben_path and df_gw_den is not None:
        df_napas_ben = doc_napas_csv(napas_ben_path, log_callback)
        n_napas_den = len(df_napas_ben)
        s_napas_den = _tong_tien(df_napas_ben, 'SttlmAmount')
        df_napas_den_khop, df_napas_den_thua, df_gwden_thua_napas = doi_chieu_napas_gw(
            df_napas_ben, df_gw_den, 'MSGREF', log_callback,
        )
        log('[Mục 6/7] TONG_KET chiều đến lấy số từ CSV chi tiết (có BEN + GW đến).')
    elif napas_ben_path and df_gw_den is None:
        log('[Mục 6/7] Bỏ qua đối chiếu chi tiết Napas chiều đến — có BEN nhưng '
            'thiếu file đến_GW (Mục 4). TONG_KET chiều đến (nếu có) vẫn dùng số PDF.')
    elif n_napas_den is not None:
        log('[Mục 6/7] TONG_KET chiều đến lấy số từ PDF (không có BEN).')

    if dung_sau_mis_di:
        log(f'[TIMING] Đến checkpoint MIS_đi: {time.perf_counter()-_t0:.1f}s')
        df_bi_loai = tim_giao_dich_bi_loai_session_null(
            df_mis_di_data, session_id, ngay_dt, df_gw_goc, log_callback,
        )
        xac_nhan_out_path = xuat_excel_confirm_mis_di(
            output_dir, session_id, ngay_dt, df_mis_di, df_bi_loai, log_callback,
        )
        log(f'[CHECKPOINT] Dừng để chờ xác nhận thủ công. File: {xac_nhan_out_path}')
        return xac_nhan_out_path

    # Audit 2026-08-04 — LUÔN tính (không chỉ ở Checkpoint) để giao dịch SESSION=NULL
    # bị loại (mọi lý do — xem tim_toan_bo_giao_dich_bi_loai_session_null()) không
    # còn biến mất hoàn toàn khỏi báo cáo cuối khi chạy thẳng/chạy tiếp.
    df_session_null_bi_loai = tim_toan_bo_giao_dich_bi_loai_session_null(
        df_mis_di_data, session_id, ngay_dt, df_gw_goc, log_callback,
    )

    if xac_nhan_path:
        def _doc_them_ngay_khac():
            zip_khac = _tim_di_zip_ngay_khac(input_dir, log_callback)
            if not zip_khac:
                return pd.DataFrame(columns=df_mis_di_data.columns)
            log(f'[Bước 2] Không thấy REFHUB bổ sung ở dữ liệu ngày đang chạy — '
                f'tra thêm {len(zip_khac)} file MIS_đi ở thư mục khác...')
            return doc_mis_di_khong_loc_session(zip_khac, log_callback)

        df_mis_di = ap_dung_confirm_mis_di(
            xac_nhan_path, df_mis_di, df_mis_di_data, log_callback,
            doc_them_ngay_khac=_doc_them_ngay_khac,
        )

    # Mục 3 — so khớp CN TIỀN giữa MIS_đi (đã confirm nếu có) và GW.
    df_mis_di_khop_gw, df_timeout = khop_voi_gw(df_mis_di, dict_gw_count, df_gw_raw, log_callback)

    df_cap_cn_tien = _tao_cap_cn_tien(df_mis_di, df_timeout, dict_gw_count)

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng trước Phase 2.')
        return None

    _t1 = time.perf_counter()

    # Phase 2: B5 + B7 + C.1a (GW-thừa) song song. Mục 4 — đối chiếu NPO_đi với
    # "điện MIS_đi khớp đúng" (đầu ra mục 3), không phải MIS_đi thô. doi_chieu_di/
    # doi_chieu_den cần GL02 (npo_di/npo_den) — bỏ qua khi thiếu (chi_tim_timeout);
    # GW-thừa (Tầng 0, không cần GL02/MIS_đến) luôn chạy.
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_di = (
            ex.submit(doi_chieu_di, npo_di, df_mis_di_khop_gw, log_callback)
            if npo_di is not None else None
        )
        f_den = (
            ex.submit(doi_chieu_den, npo_den, df_mis_den, log_callback)
            if (npo_den is not None and df_mis_den is not None) else None
        )
        f_gwthua = ex.submit(tim_nhom_gw_thua, df_mis_di, df_gw_raw, log_callback)

        if f_di:
            df_mis_di_khop, df_npo_di_thua, df_mis_di_thua = f_di.result()
        else:
            df_mis_di_khop = df_npo_di_thua = df_mis_di_thua = None
        if f_den:
            df_mis_den_khop, df_npo_den_thua, df_mis_den_thua = f_den.result()
        else:
            df_mis_den_khop = df_npo_den_thua = df_mis_den_thua = None
        df_gw_thua_xac_dinh, df_gw_can_doi_chieu = f_gwthua.result()

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng sau Phase 2.')
        return None

    # Điểm 3 — tách "điện đi huỷ trong ngày/khác ngày" khỏi NPO_đi thừa TRƯỚC khi
    # ghi báo cáo (df_npo_di_thua sau dòng này chỉ còn phần thật sự chưa giải
    # thích được — không phải NPO_đi thừa gốc nữa). Cần GL02 — bỏ qua khi thiếu.
    if df_npo_di_thua is not None:
        df_dien_huy_trong_ngay, df_dien_huy_khac_ngay, df_npo_di_thua = tach_dien_huy(
            df_npo_di_thua, log_callback,
        )
    else:
        df_dien_huy_trong_ngay = df_dien_huy_khac_ngay = None

    # Mục 5 (bổ sung 11.09.2026) — đối chiếu chéo NPO_đi thừa T-2 với huỷ khác
    # ngày T-1 (df_dien_huy_khac_ngay vừa tính ở trên, KHÔNG phải file mới).
    df_npo_di_thua_t2 = doc_npo_di_thua_t2(npo_di_thua_t2_files[0]) if npo_di_thua_t2_files else None
    df_npo_thua_t2_ketqua, df_huy_khac_ngay_ketqua = doi_chieu_huy_cheo_ngay(
        df_npo_di_thua_t2, df_dien_huy_khac_ngay, log_callback,
    ) if df_dien_huy_khac_ngay is not None else (None, None)

    # Điểm 4 — đối chiếu chéo ngày: MIS thừa (T-2) ⟷ NPO thừa (T-1, phần còn lại
    # SAU Điểm 3), cả 2 chiều. Không có file T-2 → chỉ thêm cột GHI_CHU_T2 rỗng.
    # Cần GL02 (df_npo_..._thua) — bỏ qua khi thiếu.
    df_mis_di_thua_t2  = doc_mis_di_thua_t2(mis_di_thua_t2_files[0])   if mis_di_thua_t2_files  else None
    df_mis_den_thua_t2 = doc_mis_den_thua_t2(mis_den_thua_t2_files[0]) if mis_den_thua_t2_files else None
    if df_npo_di_thua is not None:
        df_npo_di_thua = danh_dau_da_can_di(df_npo_di_thua, df_mis_di_thua_t2, log_callback)
    if df_npo_den_thua is not None:
        df_npo_den_thua = danh_dau_da_can_den(df_npo_den_thua, df_mis_den_thua_t2, log_callback)

    # Báo cáo "KẾT QUẢ" (docx NGUYEN TAC DOI CHIEU DIEN MIS THUA NGAY T-1,
    # 2026-08-07) — góc nhìn ngược với GHI_CHU_T2: gắn nhãn lên chính MIS thừa T-2.
    # Dòng OSB so QT ngày T-1 (df_qt_di/den đã đọc ở khối Điểm 2 bên dưới), dòng
    # thường so NPO thừa ngày T-1 (df_npo_..._thua vừa tính xong ở trên, sau Điểm 3).
    df_ketqua_di_t2 = (
        ket_qua_mis_di_thua_t2(df_mis_di_thua_t2, df_qt_di, df_npo_di_thua, log_callback)
        if df_npo_di_thua is not None else None
    )
    df_ketqua_den_t2 = (
        ket_qua_mis_den_thua_t2(df_mis_den_thua_t2, df_qt_den, df_npo_den_thua, log_callback)
        if df_npo_den_thua is not None else None
    )

    # Điểm 2 — đối chiếu lệnh OSB (đi & đến) qua QT, độc lập hoàn toàn với Điểm
    # 3/4 (dùng df_mis_di_thua/df_mis_den_thua, không đụng df_npo_..._thua). Không
    # có file QT nào → bỏ qua hẳn, không tạo file OSB. Thiếu GL02/MIS_đến →
    # df_mis_..._thua không đáng tin cậy, Business Owner đã chốt (2026-08-03):
    # TẮT HẲN Điểm 2, không chạy kèm cảnh báo.
    df_osb_di_khop = df_di_chua_khop = df_osb_den_khop = df_den_chua_khop = None
    if df_qt_di is not None and df_mis_di_thua is not None:
        df_osb_di_khop, df_di_chua_khop = doi_chieu_osb_di(df_mis_di_thua, df_qt_di, log_callback)
    if df_qt_den is not None and df_mis_den_thua is not None:
        df_osb_den_khop, df_den_chua_khop = doi_chieu_osb_den(df_mis_den_thua, df_qt_den, log_callback)
    if tang1_thieu and (df_qt_di is not None or df_qt_den is not None):
        log(f'[ĐIỂM 2] Bỏ qua đối chiếu OSB — thiếu {ly_do_thieu_tang1}, '
            f'không đủ dữ liệu để xác định MIS_đi/MIS_đến thừa đáng tin cậy.')

    # Mục 2 (bổ sung 11.09.2026) — loại khỏi MIS_đi/đến thừa các dòng OSB đã
    # khớp QT (đã tính ở khối trên), tránh hiện trùng với file OSB riêng.
    df_mis_di_thua  = _loai_osb_da_khop_khoi_thua(df_mis_di_thua,  df_osb_di_khop)
    df_mis_den_thua = _loai_osb_da_khop_khoi_thua(df_mis_den_thua, df_osb_den_khop)

    # Mục 1.1 + 1.1.1 (bổ sung 11.09 + 14.09.2026) — gắn GHI_CHU lên TIMEOUT,
    # NPO_DI_THUA, và QT đi thừa (đối chiếu chéo cùng ngày T).
    df_timeout = gan_ghi_chu_timeout(df_timeout, df_npo_di_thua, df_qt_di, log_callback)
    df_npo_di_thua = gan_ghi_chu_npo_di_thua(df_npo_di_thua, df_timeout, log_callback)

    # Mục 5.1 (bổ sung 14.09.2026) — tách huỷ trong/khác ngày khỏi QT đi thừa
    # TRƯỚC khi gắn GHI_CHU (Mục 1.1.1), đối xứng cách NPO làm ở Điểm 3. Nguồn:
    # subset NGUON=='QT' của df_di_chua_khop (đầu ra doi_chieu_osb_di()).
    df_qt_di_thua_raw = (
        df_di_chua_khop[df_di_chua_khop['NGUON'] == 'QT'].copy()
        if df_di_chua_khop is not None else None
    )
    if df_qt_di_thua_raw is not None and len(df_qt_di_thua_raw) > 0:
        df_qt_huy_trong_ngay, df_qt_huy_khac_ngay, df_qt_di_thua_raw = tach_dien_huy_qt(
            df_qt_di_thua_raw, log_callback,
        )
    else:
        df_qt_huy_trong_ngay = df_qt_huy_khac_ngay = None
    # gan_ghi_chu_qt_di_thua() tự lọc lại NGUON=='QT' bên trong — vô hại ở đây vì
    # df_qt_di_thua_raw đã toàn bộ là QT rồi (cột NGUON còn nguyên, tach_dien_huy_qt()
    # không drop cột nào ngoài _CHECK_TRUNG tạm).
    df_qt_di_thua = gan_ghi_chu_qt_di_thua(df_qt_di_thua_raw, df_timeout, log_callback)

    # Mục 8 (bổ sung 14.09.2026) — đối chiếu TO ko đi kênh NGÀY CŨ (nếu có) với
    # NPO_đi thừa/QT_đi thừa/Huỷ trong ngày CỦA NGÀY ĐANG CHẠY (df_dien_huy_trong_ngay
    # tính ở Điểm 3, GIỮ nguyên KEY_DI). Đặt SAU gan_ghi_chu_qt_di_thua() và TRƯỚC
    # 2 khối xuất CSV NPO_DI_THUA_/QT_DI_THUA_ bên dưới — để GHI_CHU bổ sung ở đây
    # có mặt trong 2 file CSV đó ngay từ lần xuất này.
    df_timeout_cu = (
        pd.concat([doc_timeout_cu(f) for f in timeout_cu_files], ignore_index=True)
        if timeout_cu_files else None
    )
    df_timeout_cu_ketqua, df_npo_di_thua, df_qt_di_thua = doi_chieu_timeout_cu(
        df_timeout_cu, df_npo_di_thua, df_qt_di_thua, df_dien_huy_trong_ngay, log_callback,
    )

    # Mục 5.1 — đối chiếu chéo QT đi thừa T-2 với "huỷ khác ngày" của QT đi T-1
    # (df_qt_huy_khac_ngay vừa tính ở trên, KHÔNG phải file mới).
    df_qt_di_thua_t2 = doc_qt_di_thua_t2(qt_di_thua_t2_files[0]) if qt_di_thua_t2_files else None
    df_qt_thua_t2_ketqua, df_huy_khac_ngay_qt_ketqua = doi_chieu_huy_cheo_ngay_qt(
        df_qt_di_thua_t2, df_qt_huy_khac_ngay, log_callback,
    ) if df_qt_huy_khac_ngay is not None else (None, None)

    log(f'[TIMING] Phase 2 đối chiếu: {time.perf_counter()-_t1:.1f}s')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng trước khi ghi Excel.')
        return None

    _t2 = time.perf_counter()

    # Mục 5 — luôn xuất NPO_đi thừa dạng file riêng để mang sang ngày hôm sau
    # (input cho _tim_file_npo_di_thua_t2() của lần chạy kế tiếp).
    if df_npo_di_thua is not None:
        df_npo_di_thua.to_csv(
            os.path.join(output_dir, f'NPO_DI_THUA_{ngay_dt.strftime("%Y%m%d")}.csv'),
            index=False, encoding='utf-8-sig',
        )

    # Mục 5.1 — luôn xuất QT đi thừa dạng file riêng để mang sang ngày hôm sau
    # (input cho _tim_file_qt_di_thua_t2() của lần chạy kế tiếp).
    if df_qt_di_thua is not None:
        df_qt_di_thua.to_csv(
            os.path.join(output_dir, f'QT_DI_THUA_{ngay_dt.strftime("%Y%m%d")}.csv'),
            index=False, encoding='utf-8-sig',
        )

    # Mục 8 — luôn xuất TIMEOUT_KHONG_KENH dạng file riêng (df_timeout đã có
    # GHI_CHU từ Mục 1.1) để mang sang ngày hôm sau làm input "TO ko đi kênh
    # ngày cũ" cho lần chạy kế tiếp (input cho _tim_file_timeout_cu()).
    if df_timeout is not None:
        df_timeout.to_csv(
            os.path.join(output_dir, f'TIMEOUT_KHONG_KENH_{ngay_dt.strftime("%Y%m%d")}.csv'),
            index=False, encoding='utf-8-sig',
        )

    output_path = os.path.join(output_dir, f'doi_chieu_{ngay_dt.strftime("%Y%m%d")}.xlsx')
    xuat_excel(
        output_path, session_id,
        df_mis_di_khop, df_npo_di_thua, df_mis_di_thua,
        df_timeout,
        df_mis_den_khop, df_npo_den_thua, df_mis_den_thua,
        df_gw_raw,
        df_cap_cn_tien=df_cap_cn_tien,
        df_gw_thua_xac_dinh=df_gw_thua_xac_dinh,
        df_gw_can_doi_chieu=df_gw_can_doi_chieu,
        df_dien_huy_trong_ngay=df_dien_huy_trong_ngay,
        df_dien_huy_khac_ngay=df_dien_huy_khac_ngay,
        df_session_null_bi_loai=df_session_null_bi_loai,
        df_osb_di_khop=df_osb_di_khop, df_osb_den_khop=df_osb_den_khop,
        summary_callback=summary_callback,
        df_qt_di=df_qt_di, df_qt_den=df_qt_den,
        df_ketqua_di_t2=df_ketqua_di_t2, df_ketqua_den_t2=df_ketqua_den_t2,
        df_gwden_khop=df_gwden_khop,
        n_napas_di=n_napas_di, s_napas_di=s_napas_di,
        n_napas_den=n_napas_den, s_napas_den=s_napas_den,
        log_callback=log_callback,
        ly_do_thieu_tang1=ly_do_thieu_tang1,
    )

    if not tang1_thieu and (df_qt_di is not None or df_qt_den is not None):
        xuat_excel_osb(
            output_dir, session_id, ngay_dt,
            df_osb_di_khop, df_di_chua_khop, df_osb_den_khop, df_den_chua_khop,
            log_callback,
        )

    # Mục 4 (bổ sung 11.09.2026) — chỉ xuất khi nhánh thực sự chạy (có cả file
    # đến_GW lẫn MIS_đến), giống cách xuat_excel_osb() chỉ gọi khi có QT.
    if df_gwden_khop is not None:
        xuat_excel_gw_den(
            output_dir, session_id, ngay_dt,
            df_gwden_khop, df_gwden_thua, df_misden_thua_gwden,
            log_callback,
        )

    # Mục 6/7 (bổ sung 11.09.2026 + 14.09.2026) — chỉ xuất khi ít nhất 1 chiều CSV
    # chi tiết chạy được, giống cách xuat_excel_gw_den() chỉ gọi khi Mục 4 chạy.
    xuat_excel_napas(
        output_dir, session_id, ngay_dt,
        df_napas_di_khop, df_napas_di_thua, df_gwdi_thua_napas,
        df_napas_den_khop, df_napas_den_thua, df_gwden_thua_napas,
        log_callback,
    )

    if df_ketqua_di_t2 is not None or df_ketqua_den_t2 is not None:
        xuat_excel_mis_thua_t2(
            output_dir, ngay_dt, df_ketqua_di_t2, df_ketqua_den_t2, log_callback,
        )

    xuat_excel_huy_cheo_ngay_t2(
        output_dir, ngay_dt, df_npo_thua_t2_ketqua, df_huy_khac_ngay_ketqua, log_callback,
        df_qt_thua_t2_ketqua=df_qt_thua_t2_ketqua,
        df_huy_khac_ngay_qt_ketqua=df_huy_khac_ngay_qt_ketqua,
    )

    # Mục 8 (bổ sung 14.09.2026) — chỉ xuất khi có ít nhất 1 file timeout ngày cũ.
    xuat_excel_timeout_cu(output_dir, ngay_dt, df_timeout_cu_ketqua, log_callback)

    log(f'[TIMING] Phase 3 Excel: {time.perf_counter()-_t2:.1f}s')
    log(f'[TIMING] TỔNG: {time.perf_counter()-_t0:.1f}s')
    log(f'Hoàn thành: {output_path}')
    return output_path
