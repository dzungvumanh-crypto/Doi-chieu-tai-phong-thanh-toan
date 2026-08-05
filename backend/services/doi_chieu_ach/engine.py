"""Engine Đối chiếu ACH — điều phối B1..B8 và xuất file Excel/CSV kết quả.

Port từ `main.py` của app gốc. Khác biệt so với bản gốc:
- Bỏ lớp CLI (argparse) và thanh tiến độ tqdm — tiến độ đi qua log_callback.
- Ngày đối chiếu KHÔNG có mặc định trong config: lấy từ tham số hoặc suy ra từ
  tên file PDF; không suy được thì báo lỗi thay vì âm thầm dùng ngày cũ.
"""
import glob
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import xlsxwriter

from . import config
from .b1_doc_session import doc_session
from .b2_xu_ly_gl02 import xu_ly_gl02
from .b3_xu_ly_gw import xu_ly_gw
from .b4_xu_ly_mis_di import _doc_mis_di_raw, _process_mis_di
from .b5_doi_chieu_di import doi_chieu_di
from .b6_xu_ly_mis_den import xu_ly_mis_den
from .b7_doi_chieu_den import doi_chieu_den
from .b8_phan_tich import phan_tich

# ─── Cột giữ lại cho từng loại DataFrame ──────────────────────────────────────
_COLS_NPO = config.COLS_NPO

_COLS_MIS_DI = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'CN tiền Hub', 'REFHUB', 'MSGREF',
    'MSGSEQ', 'TXID', 'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN',
    'TRACE', 'SE_TRACE', 'SESSION', 'LOAI_LENH_OSB', 'NH_NHAN',
    'MA_GIAO_DICH', 'NOI_DUNG', 'NGAY_KENH_TRA',
]

_COLS_MIS_DEN = [
    'NGAY_GIAO_DICH', 'CHI_NHANH', 'REFHUB', 'MSGREF', 'MSGSEQ', 'TXID',
    'KENH_THANH_TOAN', 'TRANG_THAI_LENH', 'SO_TIEN', 'TRACE',
    'SESSION', 'LOAI_LENH_OSB', 'NH_GUI', 'NOI_DUNG',
]

# Ngưỡng: sheet lớn hơn sẽ xuất ra CSV thay vì ghi vào Excel
CSV_THRESHOLD = 15_000

# ─── Màu tab sheet ────────────────────────────────────────────────────────────
_XANH_LA = '#C6EFCE'
_DO = '#FFC7CE'
_CAM = '#FFEB9C'
_XANH_LAM = '#DDEBF7'
_XANH_NHAT = '#E2EFDA'


# ─── Helper ───────────────────────────────────────────────────────────────────

def _clean(df: pd.DataFrame, cols: list, label: str = '') -> pd.DataFrame:
    """Chỉ giữ cột có trong df và thuộc danh sách cols."""
    if df is None or len(df) == 0:
        return df
    existing = [c for c in cols if c in df.columns]
    return df[existing]


def _tong_tien(df: pd.DataFrame, col: str) -> int:
    if df is None or len(df) == 0 or col not in df.columns:
        return 0
    return int(pd.to_numeric(df[col], errors='coerce').fillna(0).sum())


def _tao_cap_cn_tien(mis_di_final, df_timeout, dict_gw_count):
    """So sánh số lượng cặp CN+TIỀN giữa TẤT CẢ MIS (SCNL+TXRT+TPAY) và GW.

    Phải đếm cả SCNL/TXRT chứ không riêng TPAY, vì SCNL có thể đã dùng hết slot
    GW khiến TPAY thành timeout. VD: CN=3617 SO_TIEN=35000 → MIS=2 (1 SCNL +
    1 TPAY timeout), GW=1 → CHENH_LECH=1.
    """
    cn_col = 'CN tiền Hub'
    cols_out = ['CHI_NHANH', 'SO_TIEN', 'COUNT_MIS', 'COUNT_GW', 'CHENH_LECH', 'SO_TIMEOUT']

    frames = []
    if mis_di_final is not None and len(mis_di_final) > 0:
        frames.append(mis_di_final)
    if df_timeout is not None and len(df_timeout) > 0:
        frames.append(df_timeout)
    if not frames:
        return pd.DataFrame(columns=cols_out)

    df_all = pd.concat(frames, ignore_index=True)
    if cn_col not in df_all.columns:
        return pd.DataFrame(columns=cols_out)

    cnt = df_all.groupby(cn_col, sort=False).size().rename('COUNT_MIS').reset_index()
    cnt['COUNT_GW'] = cnt[cn_col].map(dict_gw_count).fillna(0).astype(int)
    cnt['CHENH_LECH'] = cnt['COUNT_MIS'] - cnt['COUNT_GW']

    if df_timeout is not None and len(df_timeout) > 0 and cn_col in df_timeout.columns:
        to_cnt = df_timeout.groupby(cn_col, sort=False).size().rename('SO_TIMEOUT')
        cnt = cnt.merge(to_cnt, on=cn_col, how='left')
        cnt['SO_TIMEOUT'] = cnt['SO_TIMEOUT'].fillna(0).astype(int)
    else:
        cnt['SO_TIMEOUT'] = 0

    ref = df_all.drop_duplicates(subset=[cn_col])
    lookup = ref.set_index(cn_col)[['CHI_NHANH', 'SO_TIEN']]
    cnt['CHI_NHANH'] = cnt[cn_col].map(lookup['CHI_NHANH'].to_dict())
    cnt['SO_TIEN'] = cnt[cn_col].map(lookup['SO_TIEN'].to_dict())

    result = cnt[cnt['CHENH_LECH'] > 0][cols_out].copy()
    return result.sort_values('CHENH_LECH', ascending=False).reset_index(drop=True)


# ─── Ghi Excel ────────────────────────────────────────────────────────────────

def _viet_phan_tich(workbook, worksheet, df: pd.DataFrame):
    """Ghi sheet PHAN_TICH, tô màu theo cột _type."""
    if df is None or len(df) == 0:
        worksheet.write(0, 0, '(Khong co du lieu)')
        return

    fmt_col_hdr = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#DDEBF7', 'border': 1})
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#BDD7EE', 'border': 1})
    fmt_sub = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#E2EFDA', 'border': 1})
    fmt_canh_bao = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#FFEB9C', 'border': 1})
    fmt_data = workbook.add_format({'font_size': 10, 'border': 1})

    cols = ['Chi tieu', 'Gia tri', 'Ghi chu']
    widths = [60, 30, 70]
    for ci, (col, w) in enumerate(zip(cols, widths)):
        worksheet.write(0, ci, col, fmt_col_hdr)
        worksheet.set_column(ci, ci, w)

    for row_idx, row in df.iterrows():
        typ = str(row.get('_type', ''))
        if typ == 'header':
            fmt = fmt_header
        elif typ == 'sub_header':
            fmt = fmt_sub
        elif typ == 'canh_bao':
            fmt = fmt_canh_bao
        else:
            fmt = fmt_data
        for ci, col in enumerate(cols):
            val = row[col] if row[col] else ''
            worksheet.write(row_idx + 1, ci, str(val), fmt)


def _viet_sheet(workbook, worksheet, df: pd.DataFrame, header_color: str):
    if df is None or len(df) == 0:
        worksheet.write(0, 0, '(Khong co du lieu)')
        return

    fmt_header = workbook.add_format({'bold': True, 'bg_color': header_color, 'border': 1, 'font_size': 10})
    fmt_cell = workbook.add_format({'font_size': 10, 'border': 1})

    # Cột datetime → chuỗi, tránh Excel hiện số serial
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


def _viet_tong_ket(workbook, ws, session_id, ngay_doi_chieu_str,
                   n_di_khop, s_di_khop,
                   n_npo_di_thua, s_npo_di_thua,
                   n_mis_di_thua, s_mis_di_thua,
                   n_timeout, s_timeout,
                   n_den_khop, s_den_khop,
                   n_npo_den_thua, s_npo_den_thua,
                   n_mis_den_thua, s_mis_den_thua):
    fmt_label = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#DDEBF7', 'border': 1})
    fmt_num = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val = workbook.add_format({'font_size': 10})

    ws.write(0, 0, 'Chi tieu', fmt_header)
    ws.write(0, 1, 'So giao dich', fmt_header)
    ws.write(0, 2, 'Tong so tien (VND)', fmt_header)
    ws.set_column(0, 0, 30)
    ws.set_column(1, 1, 16)
    ws.set_column(2, 2, 22)

    n_npo_di = n_di_khop + n_npo_di_thua
    n_npo_den = n_den_khop + n_npo_den_thua
    n_mis_di_total = n_di_khop + n_mis_di_thua + n_timeout   # MIS_DI trước khi bỏ timeout

    data = [
        ('Ngay doi chieu',          ngay_doi_chieu_str, ''),
        ('Session',                 session_id,         ''),
        ('',                        '',                 ''),
        ('=== CHIEU DI ===',        '',                 ''),
        ('So giao dich khop (MIS)', n_di_khop,     s_di_khop),
        ('NPO_DI thua',             n_npo_di_thua, s_npo_di_thua),
        ('MIS_DI thua',             n_mis_di_thua, s_mis_di_thua),
        ('Timeout khong kenh',      n_timeout,     s_timeout),
        ('Tong NPO_DI (can doi)',   n_npo_di,      f'{n_di_khop:,} khop + {n_npo_di_thua:,} thua'),
        ('Tong MIS_DI (can doi)',   n_mis_di_total,
         f'{n_di_khop:,} khop + {n_mis_di_thua:,} thua + {n_timeout:,} timeout'),
        ('',                        '',                 ''),
        ('=== CHIEU DEN ===',       '',                 ''),
        ('So giao dich khop (MIS)', n_den_khop,     s_den_khop),
        ('NPO_DEN thua',            n_npo_den_thua, s_npo_den_thua),
        ('MIS_DEN thua',            n_mis_den_thua, s_mis_den_thua),
        ('Tong NPO_DEN (can doi)',  n_npo_den,      f'{n_den_khop:,} khop + {n_npo_den_thua:,} thua'),
        ('Tong MIS_DEN (can doi)',  n_den_khop + n_mis_den_thua,
         f'{n_den_khop:,} khop + {n_mis_den_thua:,} thua'),
    ]

    for row_idx, (label, val, tien) in enumerate(data, start=1):
        ws.write_string(row_idx, 0, label, fmt_label)
        if isinstance(val, int):
            ws.write(row_idx, 1, val, fmt_num)
        else:
            ws.write(row_idx, 1, val, fmt_val)
        if isinstance(tien, int) and tien > 0:
            ws.write(row_idx, 2, tien, fmt_num)
        elif tien != '':
            ws.write(row_idx, 2, tien, fmt_val)


def xuat_excel(output_path: str, session_id: str,
               df_mis_di_khop, df_npo_di_thua, df_mis_di_thua,
               df_timeout, df_mis_den_khop, df_npo_den_thua,
               df_mis_den_thua, df_gw_raw,
               df_cap_cn_tien=None, df_phan_tich=None,
               log_callback=None):
    output_dir = os.path.dirname(os.path.abspath(output_path))
    ngay_str = os.path.basename(output_path).replace('doi_chieu_', '').replace('.xlsx', '')
    ngay_display = datetime.strptime(ngay_str, '%Y%m%d').strftime('%d/%m/%Y')
    df_gw_clean = df_gw_raw.drop(columns=['KEY_GW'], errors='ignore') if df_gw_raw is not None else None

    sheets = [
        ('TONG_KET',           None,                                                        '#FFFFFF'),
        ('PHAN_TICH',          df_phan_tich,                                                _XANH_NHAT),
        ('MIS_DI_KHOP',        _clean(df_mis_di_khop,  _COLS_MIS_DI,  'MIS_DI_KHOP'),       _XANH_LA),
        ('NPO_DI_THUA',        _clean(df_npo_di_thua,  _COLS_NPO,     'NPO_DI_THUA'),       _DO),
        ('MIS_DI_THUA',        _clean(df_mis_di_thua,  _COLS_MIS_DI,  'MIS_DI_THUA'),       _DO),
        ('TIMEOUT_KHONG_KENH', _clean(df_timeout, _COLS_MIS_DI + ['CO_TRONG_GW'], 'TIMEOUT'), _CAM),
        ('CAP_CN_TIEN',        df_cap_cn_tien,                                              _CAM),
        ('MIS_DEN_KHOP',       _clean(df_mis_den_khop, _COLS_MIS_DEN, 'MIS_DEN_KHOP'),      _XANH_LA),
        ('NPO_DEN_THUA',       _clean(df_npo_den_thua, _COLS_NPO,     'NPO_DEN_THUA'),      _DO),
        ('MIS_DEN_THUA',       _clean(df_mis_den_thua, _COLS_MIS_DEN, 'MIS_DEN_THUA'),      _DO),
        ('RAW_GW',             df_gw_clean,                                                 _XANH_LAM),
    ]

    workbook = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False, 'constant_memory': True})
    csv_writes = []
    _log = log_callback or print
    total_sheets = len(sheets)

    with ThreadPoolExecutor(max_workers=3) as csv_pool:
        for i, (sheet_name, df, color) in enumerate(sheets, 1):
            _log(f'[EXCEL] ({i}/{total_sheets}) Ghi sheet: {sheet_name}...')
            # Sheet quá lớn → ghi CSV song song, Excel chỉ ghi ghi chú trỏ sang
            if df is not None and len(df) > CSV_THRESHOLD:
                csv_path = os.path.join(output_dir, f'{sheet_name}_{ngay_str}.csv')
                fut = csv_pool.submit(df.to_csv, csv_path, index=False, encoding='utf-8-sig')
                csv_writes.append((sheet_name, csv_path, fut))
                ws = workbook.add_worksheet(sheet_name)
                ws.set_tab_color(color)
                ws.write(0, 0, f'[Du lieu lon - xem file: {os.path.basename(csv_path)}]')
                ws.write(1, 0, f'Tong so dong: {len(df):,}')
                ws.write(2, 0, 'LUU Y: Mo file CSV qua Excel > Data > Tu Van ban/CSV (khong double-click truc tiep).')
                ws.write(3, 0, 'Double-click co the mat so 0 dau o cot TRACE, MSGSEQ va sai dinh dang so tien.')
                _log(f'[CSV] {sheet_name}: {len(df):,} dòng → đang ghi nền...')
                continue

            ws = workbook.add_worksheet(sheet_name)
            ws.set_tab_color(color)
            if sheet_name == 'TONG_KET':
                _viet_tong_ket(
                    workbook, ws, session_id, ngay_display,
                    len(df_mis_di_khop) if df_mis_di_khop is not None else 0,
                    _tong_tien(df_mis_di_khop, 'SO_TIEN'),
                    len(df_npo_di_thua) if df_npo_di_thua is not None else 0,
                    _tong_tien(df_npo_di_thua, 'CRAMOUNT'),
                    len(df_mis_di_thua) if df_mis_di_thua is not None else 0,
                    _tong_tien(df_mis_di_thua, 'SO_TIEN'),
                    len(df_timeout) if df_timeout is not None else 0,
                    (lambda s, n: f'{s} | {n} dien co MSGREF trong GW' if n > 0 else s)(
                        _tong_tien(df_timeout, 'SO_TIEN'),
                        int(df_timeout['CO_TRONG_GW'].sum())
                        if df_timeout is not None and 'CO_TRONG_GW' in df_timeout.columns else 0
                    ),
                    len(df_mis_den_khop) if df_mis_den_khop is not None else 0,
                    _tong_tien(df_mis_den_khop, 'SO_TIEN'),
                    len(df_npo_den_thua) if df_npo_den_thua is not None else 0,
                    _tong_tien(df_npo_den_thua, 'DRAMOUNT'),
                    len(df_mis_den_thua) if df_mis_den_thua is not None else 0,
                    _tong_tien(df_mis_den_thua, 'SO_TIEN'),
                )
            elif sheet_name == 'PHAN_TICH':
                _viet_phan_tich(workbook, ws, df)
            else:
                _viet_sheet(workbook, ws, df, color)

        workbook.close()
        _log('[DONE] Đã ghi xong file Excel')

    for name, path, fut in csv_writes:
        fut.result()   # raise nếu ghi CSV lỗi
        _log(f'[CSV] Xong: {os.path.basename(path)}')


# ─── Tìm file trong thư mục input ─────────────────────────────────────────────

def _tim_ngay_tu_pdf(input_dir: str) -> str | None:
    """Suy ngày đối chiếu từ tên file PDF.

    ACH_20260612_VBAAVNVN_NRT_15882_... → file là của ngày T+1 = 20260612
    → ngày đối chiếu T = 11/06/2026.
    """
    for root, _, files in os.walk(os.path.abspath(input_dir)):
        for f in files:
            if f.lower().endswith('.pdf'):
                m = re.search(r'_(\d{8})_', f)
                if m:
                    try:
                        d = datetime.strptime(m.group(1), '%Y%m%d') - timedelta(days=1)
                    except ValueError:
                        continue
                    return d.strftime('%d/%m/%Y')
    return None


def _tim_file(input_dir: str, pattern: str) -> list:
    abs_dir = os.path.abspath(input_dir)
    return sorted(glob.glob(os.path.join(abs_dir, '**', pattern), recursive=True))


def _tim_gw_xlsx(input_dir: str) -> str:
    """Tìm file .xlsx có cột BRCD và SessionId. Ưu tiên file có 'GW' trong tên."""
    abs_dir = os.path.abspath(input_dir)
    all_xlsx = glob.glob(os.path.join(abs_dir, '**', '*.xlsx'), recursive=True)
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
                if 'BRCD' in flat and 'SessionId' in flat:
                    return f
        except Exception:
            continue
    raise FileNotFoundError('Không tìm thấy file GW (.xlsx có cột BRCD và SessionId)')


# ─── Flow chính ───────────────────────────────────────────────────────────────

def _cancelled(ev) -> bool:
    return ev is not None and ev.is_set()


def chay_doi_chieu(input_dir: str, output_dir: str,
                   ngay: str = None, log_callback=None,
                   cancel_event=None) -> "tuple[str, dict] | None":
    """Chạy toàn bộ pipeline. Trả (đường dẫn .xlsx, số liệu tóm tắt), None nếu bị huỷ.

    - input_dir: thư mục đã chứa file người dùng tải lên
    - ngay: 'dd/mm/yyyy'; None = tự suy từ tên file PDF
    Thread-safe: ngày đối chiếu tính cục bộ, không mutate state toàn cục.
    """
    def log(msg):
        if log_callback:
            log_callback(msg)

    # ── Xác định ngày đối chiếu ──
    if ngay:
        ngay_dt = datetime.strptime(ngay.strip(), '%d/%m/%Y')
        ngay_str_cfg = ngay.strip()
    else:
        auto_ngay = _tim_ngay_tu_pdf(input_dir)
        if not auto_ngay:
            raise ValueError(
                'Không xác định được ngày đối chiếu từ tên file PDF. '
                'Vui lòng nhập ngày đối chiếu thủ công.'
            )
        ngay_dt = datetime.strptime(auto_ngay, '%d/%m/%Y')
        ngay_str_cfg = auto_ngay
        log(f'[AUTO] Ngày đối chiếu suy từ tên file PDF: {ngay_str_cfg}')

    # Mốc TPAY truyền tường minh xuống B4 (thread-safe)
    tpay_tu = (ngay_dt - timedelta(days=1)).replace(hour=23, minute=0, second=0)
    tpay_den = ngay_dt.replace(hour=23, minute=0, second=0)

    os.makedirs(output_dir, exist_ok=True)
    log(f'Ngày đối chiếu: {ngay_str_cfg}')

    # ── Tìm file đầu vào ──
    session_id = doc_session(input_dir, log_callback)
    gl02_files = _tim_file(input_dir, 'GL02*.zip')
    gw_path = _tim_gw_xlsx(input_dir)
    mis_di_files = _tim_file(input_dir, '*_DI_*.zip')
    mis_den_files = _tim_file(input_dir, '*_DEN_*.zip')

    if not gl02_files:
        raise FileNotFoundError('Không tìm thấy file GL02*.zip')
    if len(mis_di_files) < 2:
        raise FileNotFoundError(f'Cần 2 file MIS chiều ĐI (*_DI_*.zip), mới có {len(mis_di_files)}')
    if len(mis_den_files) < 2:
        raise FileNotFoundError(f'Cần 2 file MIS chiều ĐẾN (*_DEN_*.zip), mới có {len(mis_den_files)}')

    log(f'Đã nhận: GL02={len(gl02_files)}, ĐI={len(mis_di_files)}, ĐẾN={len(mis_den_files)}')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng trước khi xử lý.')
        return None

    _t0 = time.perf_counter()

    # ── Pha 1: B2 + B3 + B6 + đọc MIS_DI song song ──
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_gl02 = ex.submit(xu_ly_gl02, gl02_files[0], log_callback)
        f_gw = ex.submit(xu_ly_gw, gw_path, session_id, log_callback)
        f_mis_den = ex.submit(xu_ly_mis_den, mis_den_files, session_id, ngay_dt, log_callback)
        f_mis_di_raw = ex.submit(_doc_mis_di_raw, mis_di_files, session_id, log_callback)

        # B3 phải xong trước để có dict_gw_count cho B4
        dict_gw_count, df_gw_raw = f_gw.result()

        if _cancelled(cancel_event):
            log('[CANCELLED] Người dùng đã dừng sau B3. Chờ các luồng còn lại kết thúc...')
            f_gl02.result()
            f_mis_den.result()
            f_mis_di_raw.result()
            return None

        df_mis_di_data = f_mis_di_raw.result()
        mis_di_final, df_timeout = _process_mis_di(
            df_mis_di_data, dict_gw_count, session_id,
            df_gw_raw, tpay_tu, tpay_den, log_callback,
        )

        npo_di, npo_den = f_gl02.result()
        df_mis_den = f_mis_den.result()

    log(f'[TIMING] Pha 1 (đọc file): {time.perf_counter() - _t0:.1f}s')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng sau pha 1.')
        return None

    df_cap_cn_tien = _tao_cap_cn_tien(mis_di_final, df_timeout, dict_gw_count)

    _t1 = time.perf_counter()

    # ── Pha 2: B5 + B7 song song ──
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_di = ex.submit(doi_chieu_di, npo_di, mis_di_final, log_callback)
        f_den = ex.submit(doi_chieu_den, npo_den, df_mis_den, log_callback)

        df_mis_di_khop, df_npo_di_thua, df_mis_di_thua = f_di.result()
        df_mis_den_khop, df_npo_den_thua, df_mis_den_thua = f_den.result()

    log(f'[TIMING] Pha 2 (đối chiếu): {time.perf_counter() - _t1:.1f}s')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng trước khi ghi Excel.')
        return None

    _t2 = time.perf_counter()

    df_phan_tich = phan_tich(
        df_npo_di_thua, df_mis_di_thua,
        df_npo_den_thua, df_mis_den_thua,
        len(df_mis_di_khop), len(df_mis_den_khop), df_timeout,
    )

    output_path = os.path.join(output_dir, f'doi_chieu_{ngay_dt.strftime("%Y%m%d")}.xlsx')
    xuat_excel(
        output_path, session_id,
        df_mis_di_khop, df_npo_di_thua, df_mis_di_thua,
        df_timeout,
        df_mis_den_khop, df_npo_den_thua, df_mis_den_thua,
        df_gw_raw,
        df_cap_cn_tien=df_cap_cn_tien,
        df_phan_tich=df_phan_tich,
        log_callback=log_callback,
    )
    log(f'[TIMING] Pha 3 (ghi Excel): {time.perf_counter() - _t2:.1f}s')
    log(f'[TIMING] Tổng: {time.perf_counter() - _t0:.1f}s')

    # ── Số liệu tóm tắt cho giao diện ──
    _summary = {
        'session_id': session_id,
        'ngay_doi_chieu': ngay_str_cfg,
        'di_khop': len(df_mis_di_khop),
        'npo_di_thua': len(df_npo_di_thua),
        'mis_di_thua': len(df_mis_di_thua),
        'timeout': len(df_timeout),
        'timeout_tien': _tong_tien(df_timeout, 'SO_TIEN'),
        'den_khop': len(df_mis_den_khop),
        'npo_den_thua': len(df_npo_den_thua),
        'mis_den_thua': len(df_mis_den_thua),
    }
    return output_path, _summary
