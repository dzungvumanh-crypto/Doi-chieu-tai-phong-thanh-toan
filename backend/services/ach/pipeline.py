"""
Pipeline đối chiếu ACH: GL02 (NPO) vs MIS.
Hàm chính: main_from_dir() — thread-safe, dùng cho Web UI.
"""
import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import xlsxwriter

from . import config as _cfg
from .b1_doc_session   import doc_session
from .b2_xu_ly_gl02    import xu_ly_gl02
from .b3_xu_ly_gw      import xu_ly_gw
from .b4_xu_ly_mis_di  import xu_ly_mis_di, _doc_mis_di_raw, _process_mis_di
from .b5_doi_chieu_di  import doi_chieu_di
from .b6_xu_ly_mis_den import xu_ly_mis_den
from .b7_doi_chieu_den import doi_chieu_den
from .b8_phan_tich     import phan_tich

_COLS_NPO = _cfg.COLS_NPO

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

# Sheet vượt ngưỡng này → xuất CSV thay vì ghi vào Excel
CSV_THRESHOLD = 15_000

_XANH_LA    = '#C6EFCE'
_DO         = '#FFC7CE'
_CAM        = '#FFEB9C'
_XANH_LAM   = '#DDEBF7'
_XANH_NHAT  = '#E2EFDA'


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


def _tao_cap_cn_tien(mis_di_final, df_timeout, dict_gw_count):
    cn_col = 'CN tiền Hub'
    frames = []
    if mis_di_final is not None and len(mis_di_final) > 0:
        frames.append(mis_di_final)
    if df_timeout is not None and len(df_timeout) > 0:
        frames.append(df_timeout)

    if not frames:
        return pd.DataFrame(columns=['CHI_NHANH', 'SO_TIEN', 'COUNT_MIS', 'COUNT_GW', 'CHENH_LECH', 'SO_TIMEOUT'])

    df_all = pd.concat(frames, ignore_index=True)
    if cn_col not in df_all.columns:
        return pd.DataFrame(columns=['CHI_NHANH', 'SO_TIEN', 'COUNT_MIS', 'COUNT_GW', 'CHENH_LECH', 'SO_TIMEOUT'])

    cnt = df_all.groupby(cn_col, sort=False).size().rename('COUNT_MIS').reset_index()
    cnt['COUNT_GW']   = cnt[cn_col].map(dict_gw_count).fillna(0).astype(int)
    cnt['CHENH_LECH'] = cnt['COUNT_MIS'] - cnt['COUNT_GW']

    if df_timeout is not None and len(df_timeout) > 0 and cn_col in df_timeout.columns:
        to_cnt = df_timeout.groupby(cn_col, sort=False).size().rename('SO_TIMEOUT')
        cnt    = cnt.merge(to_cnt, on=cn_col, how='left')
        cnt['SO_TIMEOUT'] = cnt['SO_TIMEOUT'].fillna(0).astype(int)
    else:
        cnt['SO_TIMEOUT'] = 0

    ref       = df_all.drop_duplicates(subset=[cn_col])
    lookup    = ref.set_index(cn_col)[['CHI_NHANH', 'SO_TIEN']]
    cnt['CHI_NHANH'] = cnt[cn_col].map(lookup['CHI_NHANH'].to_dict())
    cnt['SO_TIEN']   = cnt[cn_col].map(lookup['SO_TIEN'].to_dict())

    result = cnt[cnt['CHENH_LECH'] > 0][
        ['CHI_NHANH', 'SO_TIEN', 'COUNT_MIS', 'COUNT_GW', 'CHENH_LECH', 'SO_TIMEOUT']
    ].copy()
    return result.sort_values('CHENH_LECH', ascending=False).reset_index(drop=True)


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


def _tim_gw_xlsx(input_dir: str) -> str:
    abs_dir   = os.path.abspath(input_dir)
    all_xlsx  = glob.glob(os.path.join(abs_dir, '**', '*.xlsx'), recursive=True)
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
    raise FileNotFoundError('Không tìm thấy file GW .xlsx trong: ' + abs_dir)


# ─── Xuất Excel ───────────────────────────────────────────────────────────────

def _viet_phan_tich(workbook, worksheet, df: pd.DataFrame):
    if df is None or len(df) == 0:
        worksheet.write(0, 0, '(Không có dữ liệu)')
        return

    fmt_col_hdr  = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#DDEBF7', 'border': 1})
    fmt_header   = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#BDD7EE', 'border': 1})
    fmt_sub      = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#E2EFDA', 'border': 1})
    fmt_canh_bao = workbook.add_format({'bold': True, 'font_size': 10, 'bg_color': '#FFEB9C', 'border': 1})
    fmt_data     = workbook.add_format({'font_size': 10, 'border': 1})

    cols   = ['Chi tieu', 'Gia tri', 'Ghi chu']
    widths = [60, 30, 70]
    for ci, (col, w) in enumerate(zip(cols, widths)):
        worksheet.write(0, ci, col, fmt_col_hdr)
        worksheet.set_column(ci, ci, w)

    for row_idx, row in df.iterrows():
        typ = str(row.get('_type', ''))
        fmt = {'header': fmt_header, 'sub_header': fmt_sub, 'canh_bao': fmt_canh_bao}.get(typ, fmt_data)
        for ci, col in enumerate(cols):
            worksheet.write(row_idx + 1, ci, str(row[col]) if row[col] else '', fmt)


def _viet_sheet(workbook, worksheet, df: pd.DataFrame, header_color: str):
    if df is None or len(df) == 0:
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


def _viet_tong_ket(workbook, ws, session_id, ngay_str,
                   n_di_khop, s_di_khop,
                   n_npo_di_thua, s_npo_di_thua,
                   n_mis_di_thua, s_mis_di_thua,
                   n_timeout, s_timeout,
                   n_den_khop, s_den_khop,
                   n_npo_den_thua, s_npo_den_thua,
                   n_mis_den_thua, s_mis_den_thua):
    fmt_label  = workbook.add_format({'bold': True, 'font_size': 10})
    fmt_header = workbook.add_format({'bold': True, 'font_size': 10,
                                      'bg_color': '#DDEBF7', 'border': 1})
    fmt_num    = workbook.add_format({'font_size': 10, 'num_format': '#,##0'})
    fmt_val    = workbook.add_format({'font_size': 10})

    ws.write(0, 0, 'Chỉ tiêu',           fmt_header)
    ws.write(0, 1, 'Số giao dịch',       fmt_header)
    ws.write(0, 2, 'Tổng số tiền (VND)', fmt_header)
    ws.set_column(0, 0, 30); ws.set_column(1, 1, 16); ws.set_column(2, 2, 22)

    n_npo_di       = n_di_khop + n_npo_di_thua
    n_npo_den      = n_den_khop + n_npo_den_thua
    n_mis_di_total = n_di_khop + n_mis_di_thua + n_timeout

    data = [
        ('Ngày đối chiếu', ngay_str, ''),
        ('Session',         session_id, ''),
        ('', '', ''),
        ('=== CHIỀU ĐI ===', '', ''),
        ('Số GD khớp (MIS)',      n_di_khop,      s_di_khop),
        ('NPO_DI thừa',           n_npo_di_thua,  s_npo_di_thua),
        ('MIS_DI thừa',           n_mis_di_thua,  s_mis_di_thua),
        ('Timeout không kênh',    n_timeout,      s_timeout),
        ('Tổng NPO_DI (cần đối)', n_npo_di,
            f'{n_di_khop:,} khớp + {n_npo_di_thua:,} thừa'),
        ('Tổng MIS_DI (cần đối)', n_mis_di_total,
            f'{n_di_khop:,} khớp + {n_mis_di_thua:,} thừa + {n_timeout:,} timeout'),
        ('', '', ''),
        ('=== CHIỀU ĐẾN ===', '', ''),
        ('Số GD khớp (MIS)',       n_den_khop,     s_den_khop),
        ('NPO_DEN thừa',           n_npo_den_thua, s_npo_den_thua),
        ('MIS_DEN thừa',           n_mis_den_thua, s_mis_den_thua),
        ('Tổng NPO_DEN (cần đối)', n_npo_den,
            f'{n_den_khop:,} khớp + {n_npo_den_thua:,} thừa'),
        ('Tổng MIS_DEN (cần đối)', n_den_khop + n_mis_den_thua,
            f'{n_den_khop:,} khớp + {n_mis_den_thua:,} thừa'),
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


def xuat_excel(output_path: str, session_id: str,
               df_mis_di_khop, df_npo_di_thua, df_mis_di_thua,
               df_timeout, df_mis_den_khop, df_npo_den_thua,
               df_mis_den_thua, df_gw_raw,
               df_cap_cn_tien=None, df_phan_tich=None,
               log_callback=None):

    output_dir   = os.path.dirname(os.path.abspath(output_path))
    ngay_str     = os.path.basename(output_path).replace('doi_chieu_', '').replace('.xlsx', '')
    ngay_display = datetime.strptime(ngay_str, '%Y%m%d').strftime('%d/%m/%Y')
    df_gw_clean  = df_gw_raw.drop(columns=['KEY_GW'], errors='ignore') if df_gw_raw is not None else None
    _log         = log_callback or print

    sheets = [
        ('TONG_KET',           None,                                                     '#FFFFFF'),
        ('PHAN_TICH',          df_phan_tich,                                             _XANH_NHAT),
        ('MIS_DI_KHOP',        _clean(df_mis_di_khop,  _COLS_MIS_DI, 'MIS_DI_KHOP'),   _XANH_LA),
        ('NPO_DI_THUA',        _clean(df_npo_di_thua,  _COLS_NPO,    'NPO_DI_THUA'),   _DO),
        ('MIS_DI_THUA',        _clean(df_mis_di_thua,  _COLS_MIS_DI, 'MIS_DI_THUA'),   _DO),
        ('TIMEOUT_KHONG_KENH', _clean(df_timeout, _COLS_MIS_DI + ['CO_TRONG_GW'], 'TIMEOUT'), _CAM),
        ('CAP_CN_TIEN',        df_cap_cn_tien,                                           _CAM),
        ('MIS_DEN_KHOP',       _clean(df_mis_den_khop, _COLS_MIS_DEN, 'MIS_DEN_KHOP'), _XANH_LA),
        ('NPO_DEN_THUA',       _clean(df_npo_den_thua, _COLS_NPO,    'NPO_DEN_THUA'),  _DO),
        ('MIS_DEN_THUA',       _clean(df_mis_den_thua, _COLS_MIS_DEN, 'MIS_DEN_THUA'), _DO),
        ('RAW_GW',             df_gw_clean,                                              _XANH_LAM),
    ]

    workbook   = xlsxwriter.Workbook(output_path, {'strings_to_numbers': False, 'constant_memory': True})
    csv_writes = []
    total      = len(sheets)

    with ThreadPoolExecutor(max_workers=3) as csv_pool:
        for i, (sheet_name, df, color) in enumerate(sheets, 1):
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
                    workbook, ws, session_id, ngay_display,
                    len(df_mis_di_khop)  if df_mis_di_khop  is not None else 0,
                    _tong_tien(df_mis_di_khop,   'SO_TIEN'),
                    len(df_npo_di_thua)  if df_npo_di_thua  is not None else 0,
                    _tong_tien(df_npo_di_thua,   'CRAMOUNT'),
                    len(df_mis_di_thua)  if df_mis_di_thua  is not None else 0,
                    _tong_tien(df_mis_di_thua,   'SO_TIEN'),
                    len(df_timeout)      if df_timeout      is not None else 0,
                    _tong_tien(df_timeout,        'SO_TIEN'),
                    len(df_mis_den_khop) if df_mis_den_khop is not None else 0,
                    _tong_tien(df_mis_den_khop,  'SO_TIEN'),
                    len(df_npo_den_thua) if df_npo_den_thua is not None else 0,
                    _tong_tien(df_npo_den_thua,  'DRAMOUNT'),
                    len(df_mis_den_thua) if df_mis_den_thua is not None else 0,
                    _tong_tien(df_mis_den_thua,  'SO_TIEN'),
                )
            elif sheet_name == 'PHAN_TICH':
                _viet_phan_tich(workbook, ws, df)
            else:
                _viet_sheet(workbook, ws, df, color)

        workbook.close()
        _log(f'[DONE] Excel: {output_path}')

    for name, path, fut in csv_writes:
        fut.result()
        _log(f'       CSV  : {path}  ({name})')


# ─── Cancel helper ────────────────────────────────────────────────────────────

def _cancelled(ev) -> bool:
    return ev is not None and ev.is_set()


# ─── main_from_dir (dùng cho Web UI) ─────────────────────────────────────────

def main_from_dir(input_dir: str, output_dir: str,
                  ngay: str = None, log_callback=None,
                  cancel_event=None) -> str | None:
    """
    Chạy pipeline đối chiếu ACH từ thư mục đã có file.
    Trả về đường dẫn file .xlsx kết quả, hoặc None nếu cancelled.
    Thread-safe: không mutate config module-level.
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

    tpay_tu  = (ngay_dt - timedelta(days=1)).replace(hour=23, minute=0, second=0)
    tpay_den = ngay_dt.replace(hour=23, minute=0, second=0)

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
    gw_path       = _tim_gw_xlsx(input_dir)
    mis_di_files  = _tim_file(input_dir, '*_DI_*.zip')
    mis_den_files = _tim_file(input_dir, '*_DEN_*.zip')

    if not gl02_files:
        raise FileNotFoundError('Không tìm thấy GL02*.zip')
    if len(mis_di_files) < 2:
        raise FileNotFoundError(f'Cần 2 file MIS_DI zip, chỉ tìm thấy {len(mis_di_files)}')
    if len(mis_den_files) < 2:
        raise FileNotFoundError(f'Cần 2 file MIS_DEN zip, chỉ tìm thấy {len(mis_den_files)}')

    log(f'Tìm thấy: GL02={len(gl02_files)}, DI={len(mis_di_files)}, DEN={len(mis_den_files)}')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng. Không xử lý.')
        return None

    _t0 = time.perf_counter()

    # Phase 1: B2 + B3 + B6 + B4_IO song song
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_gl02       = ex.submit(xu_ly_gl02,      gl02_files[0], log_callback)
        f_gw         = ex.submit(xu_ly_gw,        gw_path, session_id, log_callback)
        f_mis_den    = ex.submit(xu_ly_mis_den,   mis_den_files, session_id, ngay_dt, log_callback)
        f_mis_di_raw = ex.submit(_doc_mis_di_raw, mis_di_files, session_id, log_callback)

        dict_gw_count, df_gw_raw = f_gw.result()

        if _cancelled(cancel_event):
            log('[CANCELLED] Người dùng đã dừng sau B3.')
            f_gl02.result(); f_mis_den.result(); f_mis_di_raw.result()
            return None

        df_mis_di_data           = f_mis_di_raw.result()
        mis_di_final, df_timeout = _process_mis_di(
            df_mis_di_data, dict_gw_count, session_id,
            df_gw_raw, tpay_tu, tpay_den, log_callback,
        )

        npo_di, npo_den = f_gl02.result()
        df_mis_den      = f_mis_den.result()

    log(f'[TIMING] Phase 1 IO: {time.perf_counter()-_t0:.1f}s')

    if _cancelled(cancel_event):
        log('[CANCELLED] Người dùng đã dừng sau Phase 1.')
        return None

    df_cap_cn_tien = _tao_cap_cn_tien(mis_di_final, df_timeout, dict_gw_count)
    _t1 = time.perf_counter()

    # Phase 2: B5 + B7 song song
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_di  = ex.submit(doi_chieu_di,  npo_di,  mis_di_final, log_callback)
        f_den = ex.submit(doi_chieu_den, npo_den, df_mis_den,   log_callback)

        df_mis_di_khop, df_npo_di_thua, df_mis_di_thua    = f_di.result()
        df_mis_den_khop, df_npo_den_thua, df_mis_den_thua = f_den.result()

    log(f'[TIMING] Phase 2 đối chiếu: {time.perf_counter()-_t1:.1f}s')

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
    log(f'[TIMING] Phase 3 Excel: {time.perf_counter()-_t2:.1f}s')
    log(f'[TIMING] TỔNG: {time.perf_counter()-_t0:.1f}s')
    log(f'Hoàn thành: {output_path}')
    return output_path
