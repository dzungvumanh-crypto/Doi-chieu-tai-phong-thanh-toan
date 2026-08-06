# -*- coding: utf-8 -*-
"""
parsers.py
----------
Port NGUYÊN logic parse từ `citad-fixed/DoiSoatCITAD.py` (tool desktop độc
lập) — không đổi bất kỳ quy tắc nhận diện cột/ngày/trạng thái nào.

Sửa duy nhất khi port (không phải đổi logic nghiệp vụ): bản gốc giải nén
ZIP của CITAD vào `/tmp/_citad_<name>` — đường dẫn Unix không hợp lệ trên
Windows (nơi app thực tế chạy). Thay bằng `tempfile.mkdtemp()`, cùng cách
`backend/services/swift_recon/upload_utils.py` đã làm cho module Swift
Recon — chỉ là fix để chạy được, không ảnh hưởng kết quả đối soát.
"""
from __future__ import annotations

import csv
import datetime
import os
import re
import shutil
import tempfile
import zipfile

try:
    import xlrd
    _HAS_XLRD = True
except ImportError:
    _HAS_XLRD = False


class UnknownFileFormat(Exception):
    pass


class _XlrdWs:
    """Wrapper xlrd sheet"""
    def __init__(self, ws):
        self._ws = ws
        self.nrows = ws.nrows
        self.ncols = ws.ncols

    def cell_value(self, row, col):
        try:
            v = self._ws.cell_value(row, col)
            return v if v is not None else ''
        except Exception:
            return ''


class _OpenpyxlWs:
    """Wrapper openpyxl sheet"""
    def __init__(self, ws):
        self._ws = ws
        self.nrows = ws.max_row or 0
        self.ncols = ws.max_column or 0

    def cell_value(self, row, col):
        try:
            v = self._ws.cell(row=row + 1, column=col + 1).value
            return v if v is not None else ''
        except Exception:
            return ''


# ──────────────────────────────────────────────────────────────
# PARSE CITAD
# ──────────────────────────────────────────────────────────────
def parse_citad_xls(filepath):
    """Parse 1 file XLS/XLSX CITAD, trả về list lệnh"""
    ext = os.path.splitext(filepath)[1].lower()
    is_openpyxl = ext == '.xlsx' or not _HAS_XLRD
    try:
        if is_openpyxl:
            from openpyxl import load_workbook
            wb = load_workbook(filepath, read_only=True, data_only=True)
            sheets = [_OpenpyxlWs(wb[name]) for name in wb.sheetnames]
        else:
            wb = xlrd.open_workbook(filepath)
            sheets = [_XlrdWs(wb.sheet_by_index(i)) for i in range(wb.nsheets)]
    except Exception as e:
        return [], f"Lỗi đọc file: {e}"

    rows_out = []
    chieu_ref = [None]  # truyen chieu tu sheet dau sang cac sheet sau
    try:
        for shi, ws in enumerate(sheets):
            rows = _parse_sheet(ws, filepath, shi == 0, chieu_ref)
            rows_out += rows
    finally:
        # Đóng SAU khi đọc xong toàn bộ ô — read_only mode đọc trực tiếp
        # từ ZIP archive theo luồng, đóng sớm (trước khi đọc, như code cũ)
        # làm cell_value() ném ValueError, bị _OpenpyxlWs nuốt im lặng và
        # trả '' cho mọi ô — kết quả: mọi file .xlsx parse ra 0 dòng, không
        # báo lỗi. Đã tái hiện thực tế bằng openpyxl thật để xác nhận.
        if is_openpyxl:
            wb.close()

    return rows_out, None


def _parse_sheet(ws, filepath, is_first, chieu_ref=None):
    # Detect chiều + loaiTien từ 12 dòng đầu (chỉ sheet đầu có header)
    chieu = 'di'
    loai_tien = 'VND'
    loai_file = 'il'

    if is_first:
        for i in range(12):
            txt = ' '.join(str(ws.cell_value(i, j)) for j in range(ws.ncols)).lower()
            if 'chuyển tiền đến' in txt or 'báo cáo chuyển tiền đến' in txt:
                chieu = 'den'
            if 'chuyển tiền đi' in txt or 'báo cáo chuyển tiền đi' in txt:
                chieu = 'di'
            if 'đô la mỹ' in txt or ' usd' in txt:
                loai_tien = 'USD'
            if 'euro' in txt or ' eur' in txt:
                loai_tien = 'EUR'
            if 'giá trị cao' in txt:
                loai_file = 'ih'
            if 'giá trị thấp' in txt:
                loai_file = 'il'
        if chieu_ref is not None:
            chieu_ref[0] = chieu  # luu chieu de sheet sau dung
    elif chieu_ref is not None and chieu_ref[0] is not None:
        chieu = chieu_ref[0]  # sheet sau ke thua chieu tu sheet dau

    # Tìm header row
    h_row_idx = -1
    i_so_gd = 2
    i_dich_vu = 5
    i_no_den = 16 if loai_tien == 'VND' else 15
    i_co_di = 24 if loai_tien == 'VND' else 23
    i_ngay = 0

    if is_first:
        for i in range(min(20, ws.nrows)):
            row_txt = ' '.join(str(ws.cell_value(i, j)) for j in range(ws.ncols)).lower()
            if 'số gd' in row_txt or 'số giao dịch' in row_txt:
                h_row_idx = i
                for j in range(ws.ncols):
                    c = str(ws.cell_value(i, j)).strip().lower()
                    if c in ('số gd', 'số giao dịch'):
                        i_so_gd = j
                    if c == 'dịch vụ':
                        i_dich_vu = j
            if 'nợ' in row_txt or 'có' in row_txt:
                for j in range(ws.ncols):
                    c = str(ws.cell_value(i, j)).strip().lower()
                    if c == 'nợ':
                        i_no_den = j
                    if c == 'có':
                        i_co_di = j
            if h_row_idx >= 0 and (i_no_den >= 0 or i_co_di >= 0):
                break

    data_start = (h_row_idx + 3) if (is_first and h_row_idx >= 0) else 0

    # Verify cột tiền: scan data để tìm cột đúng (header có thể lệch 1)
    def _verify_col(col_idx, max_scan=30):
        checked = 0
        for vi in range(data_start, ws.nrows):
            sogd = ''.join(
                c for c in str(ws.cell_value(vi, i_so_gd)).replace("'", "").replace(".0", "") if c.isdigit()
            )
            if len(sogd) < 6:
                continue
            checked += 1
            v = str(ws.cell_value(vi, col_idx)).strip().replace("'", "")
            if v and v not in ('0', '0.0', 'nan', ''):
                if re.search(r'[1-9]', v):
                    return True
            if checked >= max_scan:
                break
        return False

    # File Đi: verify iCoDi (tiền luôn ở Có)
    # File Đến: verify iNoDen (Chuyển có chiếm đa số đầu file)
    if chieu == 'di':
        for d in [0, -1, 1, -2, 2]:
            if 0 <= i_co_di + d < ws.ncols and _verify_col(i_co_di + d):
                i_co_di = i_co_di + d
                break
    else:
        for d in [0, -1, 1, -2, 2]:
            if 0 <= i_no_den + d < ws.ncols and _verify_col(i_no_den + d):
                i_no_den = i_no_den + d
                break

    result = []
    for i in range(data_start, ws.nrows):
        so_gd_raw = str(ws.cell_value(i, i_so_gd)).strip().replace("'", "").replace(".0", "")
        so_gd = ''.join(c for c in so_gd_raw if c.isdigit())
        if len(so_gd) < 6:
            continue

        # Đọc dịch vụ từ col i_dich_vu, fallback col-2
        dich_vu = str(ws.cell_value(i, i_dich_vu)).strip().replace("'", "")
        if not dich_vu and i_dich_vu >= 2:
            dich_vu = str(ws.cell_value(i, i_dich_vu - 2)).strip().replace("'", "")

        dv_low = dich_vu.lower()

        # Cột tiền theo chiều file và dịch vụ:
        # File Đi:  tiền luôn ở cột Có (i_co_di)
        # File Đến: "Chuyển có" → cột Nợ, "Chuyển nợ" → cột Có
        if chieu == 'di':
            col_tien = i_co_di
        elif 'chuyển nợ' in dv_low:
            col_tien = i_co_di
        else:
            col_tien = i_no_den

        tien_raw = str(ws.cell_value(i, col_tien)).strip().replace("'", "")
        so_tien = ''.join(c for c in tien_raw if c.isdigit())
        if not so_tien or so_tien == '0':
            continue

        ngay = str(ws.cell_value(i, i_ngay)).strip()
        loai = 'ih' if 'giá trị cao' in dv_low else loai_file
        dich_vu_final = dich_vu or ('Chuyển có giá trị cao' if loai == 'ih' else 'Chuyển có giá trị thấp')

        result.append({
            'so_gd': so_gd,
            'dich_vu': dich_vu_final,
            'loai': loai,
            'chieu': chieu,
            'loai_tien': loai_tien,
            'so_tien': int(so_tien),
            'ngay': ngay,
        })
    return result


def parse_citad_files(filepaths, progress_cb=None):
    """Parse nhiều file CITAD (XLS hoặc ZIP chứa XLS).

    Khác bản gốc: giải nén ZIP vào thư mục tạm qua `tempfile.mkdtemp()`
    (bản gốc dùng `/tmp/_citad_<name>` — không hợp lệ trên Windows) và tự
    dọn sạch thư mục tạm sau khi parse xong. Không đổi cách nhận diện dòng.
    """
    all_rows = []
    errors = []
    for fp in filepaths:
        ext = os.path.splitext(fp)[1].lower()
        if ext == '.zip':
            extract_dir = tempfile.mkdtemp(prefix='citad_soat_')
            try:
                with zipfile.ZipFile(fp) as z:
                    for name in z.namelist():
                        if name.lower().endswith('.xls') or name.lower().endswith('.xlsx'):
                            tmp = os.path.join(extract_dir, os.path.basename(name))
                            with z.open(name) as src, open(tmp, 'wb') as dst:
                                dst.write(src.read())
                            rows, err = parse_citad_xls(tmp)
                            all_rows += rows
                            if err:
                                errors.append(f"{name}: {err}")
            except Exception as e:
                errors.append(f"{os.path.basename(fp)}: {e}")
            finally:
                shutil.rmtree(extract_dir, ignore_errors=True)
        elif ext in ('.xls', '.xlsx'):
            rows, err = parse_citad_xls(fp)
            all_rows += rows
            if err:
                errors.append(f"{os.path.basename(fp)}: {err}")
    return all_rows, errors


# ──────────────────────────────────────────────────────────────
# PARSE IPCAS
# ──────────────────────────────────────────────────────────────
def _strip_apos(s):
    return s.lstrip("'").strip() if s else ''


def _parse_ipcas_text(text, filename, ngay_cham):
    """Parse nội dung text CSV của IPCAS"""
    text = text.lstrip('﻿')
    lines = text.splitlines()
    if not lines:
        return []

    # Build header map
    header = lines[0]
    cols = [c.strip().lstrip("'").lstrip('﻿') for c in header.split(',')]
    hmap = {name: i for i, name in enumerate(cols)}
    n_headers = len(cols)
    has_nkt = 'NGAY_KENH_TRA' in hmap

    # Detect chiều từ 50 dòng đầu
    sample = ' '.join(lines[1:51]).upper()
    n_scnl = sample.count('SCNL')
    n_den = sum(sample.count(s) for s in ['PYED', 'PYEK', 'SBFL', 'SBSC'])
    fname = (filename or '').lower()
    if n_scnl > 0 and n_scnl >= n_den:
        chieu = 'di'
    elif n_den > 0 and n_den > n_scnl:
        chieu = 'den'
    elif 'den' in fname or '_den_' in fname:
        chieu = 'den'
    else:
        chieu = 'di'

    i_nh = hmap.get('NH_NHAN', hmap.get('NH_GUI', -1))
    i_nkt = hmap.get('NGAY_KENH_TRA', -1)

    seen = set()
    result = []

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        # Parse CSV có thể có quoted fields
        try:
            vals = list(csv.reader([line]))[0]
        except Exception:
            vals = line.split(',')

        if len(vals) < 8:
            continue

        # Tính shift do NH_NHAN chứa dấu phẩy
        shift = max(0, len(vals) - n_headers)

        def gv(name):
            idx = hmap.get(name, -1)
            if idx < 0:
                return ''
            if i_nh >= 0 and idx > i_nh:
                idx += shift
            if idx >= len(vals):
                return ''
            return _strip_apos(vals[idx])

        # NGAY_KENH_TRA: doc theo index cot, khong dung vals[-1] vi NOI_DUNG co dau ;
        nkt = ''
        if i_nkt >= 0 and i_nkt < len(vals):
            last = _strip_apos(vals[i_nkt]).strip()
            # Dang chuan: 4/6/2026 hoac 04/06/2026
            m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', last)
            if m:
                d, mo, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
                nkt = f'{d}/{mo}/{y}'
            else:
                # Excel serial date (vi du: 46011.34583)
                try:
                    serial = float(last)
                    if 40000 < serial < 60000:
                        base = datetime.date(1899, 12, 30)
                        d_obj = base + datetime.timedelta(days=int(serial))
                        nkt = d_obj.strftime('%d/%m/%Y')
                except (ValueError, TypeError):
                    pass

        tt = gv('TRANG_THAI_LENH')
        ngay_gd_raw = gv('NGAY_GIAO_DICH').strip()
        # Chuan hoa ngay_gd: 4/6/2026 -> 04/06/2026
        _m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', ngay_gd_raw)
        ngay_gd = f'{_m.group(1).zfill(2)}/{_m.group(2).zfill(2)}/{_m.group(3)}' if _m else ngay_gd_raw[:10]
        so_tien = re.sub(r'[^0-9]', '', gv('SO_TIEN'))
        kenh = gv('KENH_THANH_TOAN').lower()

        # Filter theo chiều
        if chieu == 'di':
            # Giu: SCNL (thanh cong) + WFPG/SBFL/RFED/SDEB (dang xu ly, co the lech TT)
            # Bo: ERPO (loi xu ly), CALD (huy), rong
            KEEP_DI = {'SCNL', 'WFPG', 'SBFL', 'RFED', 'SDEB', 'SBSC', 'RTSC'}
            if tt not in KEEP_DI:
                continue
            if ngay_cham:
                if has_nkt:
                    if nkt and nkt != ngay_cham:
                        # nkt co gia tri nhung khac ngay cham -> bo
                        continue
                    elif not nkt:
                        # nkt trong (cot bi lech hoac chua xu ly) -> fallback ngay_gd
                        if ngay_gd and ngay_gd != ngay_cham:
                            continue
                else:
                    if ngay_gd and ngay_gd != ngay_cham:
                        continue
        else:
            # Chiều Đến: KHÔNG lọc bỏ theo trạng thái nào cả — CITAD ghi
            # nhận hết kể cả SBSC/SBFL/RFED, chỉ lọc theo ngày.
            if ngay_cham and ngay_gd and ngay_gd != ngay_cham:
                continue

        txid_raw = _strip_apos(gv('TXID'))
        if chieu == 'den':
            txid = re.sub(r'[^0-9]', '', txid_raw.split('-')[0].split()[0])
        else:
            txid = txid_raw

        msgref = _strip_apos(gv('MSGREF'))
        nh_nhan = gv('NH_NHAN') or gv('NH_GUI')
        loai = 'ih' if 'cao' in kenh else 'il'

        # Dedup
        key = f"{ngay_gd}|{gv('CHI_NHANH')}|{txid_raw}|{so_tien}|{gv('TRACE')}|{tt}"
        if key in seen:
            continue
        seen.add(key)

        result.append({
            'txid': txid,
            'msgref': msgref,
            'loai': loai,
            'chieu': chieu,
            'so_tien': int(so_tien) if so_tien else 0,
            'trang_thai': tt,
            'nkt': nkt,
            'kenh': gv('KENH_THANH_TOAN'),
            'nh_nhan': nh_nhan,
            'ngay': ngay_gd,
        })
    return result


def parse_ipcas_files(filepaths, ngay_cham, progress_cb=None):
    """Parse nhiều file IPCAS (CSV hoặc ZIP chứa CSV)"""
    all_rows = []
    errors = []

    for fp in filepaths:
        ext = os.path.splitext(fp)[1].lower()
        fname = os.path.basename(fp)
        if progress_cb:
            progress_cb(f'Đọc IPCAS: {fname}')

        if ext == '.zip':
            try:
                with zipfile.ZipFile(fp) as z:
                    for name in z.namelist():
                        n_ext = os.path.splitext(name)[1].lower()
                        if n_ext in ('.csv', '.txt'):
                            raw = z.read(name)
                            text = None
                            for enc in ('utf-8-sig', 'utf-8', 'cp1258', 'latin-1'):
                                try:
                                    text = raw.decode(enc)
                                    break
                                except Exception:
                                    continue  # 'latin-1' ở cuối luôn thành công (không raise)
                            rows = _parse_ipcas_text(text, name, ngay_cham)
                            all_rows += rows
            except Exception as e:
                errors.append(f"{fname}: {e}")

        elif ext in ('.csv', '.txt'):
            try:
                raw = open(fp, 'rb').read()
                text = None
                for enc in ('utf-8-sig', 'utf-8', 'cp1258', 'latin-1'):
                    try:
                        text = raw.decode(enc)
                        break
                    except Exception:
                        continue  # 'latin-1' ở cuối luôn thành công (không raise)
                rows = _parse_ipcas_text(text, fname, ngay_cham)
                all_rows += rows
            except Exception as e:
                errors.append(f"{fname}: {e}")

        else:
            errors.append(f"{fname}: định dạng không hỗ trợ (cần CSV hoặc ZIP)")

    return all_rows, errors


# ──────────────────────────────────────────────────────────────
# PARSE HUB NGOẠI TỆ
# ──────────────────────────────────────────────────────────────
def parse_hub_files(filepaths, ngay_cham):
    """Parse file Hub ngoại tệ (XLS/XLSX) -> list of dicts"""
    all_rows = []
    errors = []
    for fp in filepaths:
        ext = os.path.splitext(fp)[1].lower()
        fname = os.path.basename(fp).lower()
        try:
            rows = _parse_hub_xls(fp, ext, fname, ngay_cham)
            all_rows += rows
        except Exception as e:
            errors.append(f"{os.path.basename(fp)}: {e}")
    return all_rows, errors


def _parse_hub_xls(filepath, ext, fname, ngay_cham):
    """Parse 1 file Hub XLS/XLSX"""
    if ext == '.xlsx':
        from openpyxl import load_workbook
        wb = load_workbook(filepath, data_only=True)  # khong read_only de doc dung max_row
        sheets = [(name, _OpenpyxlWs(wb[name])) for name in wb.sheetnames]
        wb.close()
    else:
        if not _HAS_XLRD:
            raise RuntimeError(
                f"Không đọc được file .xls '{fname}': thiếu thư viện xlrd "
                "(chỉ hỗ trợ .xlsx nếu không có xlrd)."
            )
        wb = xlrd.open_workbook(filepath)
        sheets = [(wb.sheet_by_index(i).name, _XlrdWs(wb.sheet_by_index(i)))
                  for i in range(wb.nsheets)]

    # Detect chiều từ tên file
    chieu_file = 'den' if ('den' in fname or 'đến' in fname) else 'di'

    result = []
    for sheet_name, ws in sheets:
        chieu = chieu_file
        if 'den' in sheet_name.lower() or 'đến' in sheet_name.lower():
            chieu = 'den'
        elif 'di' in sheet_name.lower():
            chieu = 'di'

        # Tìm header row
        h_row = -1
        i_so_tc = -1   # Số thành công / Số GD
        i_so_tien = -1
        i_loai_tien = -1
        i_ngay = -1
        i_nh = -1

        for i in range(min(10, ws.nrows)):
            row_txt = ' '.join(str(ws.cell_value(i, j)).lower() for j in range(ws.ncols))
            if any(k in row_txt for k in ['số thành công', 'so thanh cong', 'số giao dịch', 'msgid', 'msg_key']):
                h_row = i
                for j in range(ws.ncols):
                    hdr = str(ws.cell_value(i, j)).strip().lower()
                    # Uu tien 'so thanh cong' truoc, sau moi den msgid
                    if any(k in hdr for k in ['thành công', 'so tc', 'số tc']):
                        i_so_tc = j
                    elif any(k in hdr for k in ['msgid', 'msg_key']) and i_so_tc < 0:
                        i_so_tc = j
                    if 'số tiền' in hdr or 'so tien' in hdr or 'amount' in hdr:
                        i_so_tien = j
                    if 'loại tiền' in hdr or 'currency' in hdr or 'loai tien' in hdr:
                        i_loai_tien = j
                    if 'kênh trả' in hdr or 'kenh tra' in hdr:
                        i_ngay = j  # uu tien ngay kenh tra
                    elif 'ngày' in hdr and ('nhận' in hdr or 'gd' in hdr or 'giao' in hdr) and i_ngay < 0:
                        i_ngay = j  # fallback ngay nhan
                    if 'ngân hàng' in hdr or 'nh ' in hdr:
                        i_nh = j
                break

        if h_row < 0 or i_so_tc < 0:
            continue

        data_start = h_row + 1
        for i in range(data_start, ws.nrows):
            so_tc = str(ws.cell_value(i, i_so_tc)).strip().replace("'", "")
            so_tc_clean = ''.join(ch for ch in so_tc if ch.isdigit() or ch.isalpha())
            if not so_tc_clean or len(so_tc_clean) < 4:
                continue

            # Số tiền
            tien_raw = str(ws.cell_value(i, i_so_tien)).strip() if i_so_tien >= 0 else ''
            so_tien = ''.join(ch for ch in tien_raw if ch.isdigit())
            if not so_tien:
                continue

            # Loại tiền
            loai_tien = 'USD'
            if i_loai_tien >= 0:
                lt = str(ws.cell_value(i, i_loai_tien)).strip().upper()
                if lt in ('USD', 'EUR', 'GBP', 'JPY', 'CNY'):
                    loai_tien = lt

            # Ngày
            ngay = ''
            if i_ngay >= 0:
                ngay = str(ws.cell_value(i, i_ngay)).strip()[:10]

            # Lọc ngày chấm
            if ngay_cham and ngay and ngay != ngay_cham:
                continue

            nh = str(ws.cell_value(i, i_nh)).strip() if i_nh >= 0 else ''

            result.append({
                'so_gd': so_tc_clean,   # Số thành công = key ghép với CITAD
                'loai': 'ih',            # Hub ngoại tệ luôn là IH
                'chieu': chieu,
                'loai_tien': loai_tien,
                'so_tien': int(so_tien),
                'nh_nhan': nh,
                'ngay': ngay,
            })
    return result
