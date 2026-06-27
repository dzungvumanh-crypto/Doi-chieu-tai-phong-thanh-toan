"""Service phân loại bút toán tài khoản 459901.

Logic phân loại (3 phase) port nguyên từ phan_loai_459901.py — KHÔNG THAY ĐỔI.
I/O được điều chỉnh để hoạt động với bytes (từ HTTP upload) thay vì file path.
"""

import io
import logging
import shutil
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import pyzipper
    _ZipFile = pyzipper.AESZipFile
except ImportError:
    _ZipFile = zipfile.ZipFile      # fallback nếu pyzipper chưa cài

# ─── Config ───────────────────────────────────────────────────────────────────
TEMP_DIR        = Path("data/temp_cham459901")
ZIP_PASSWORD    = b"DACwLdHi"
FILTER_LOCAC    = "459901"
FILTER_CUSTOMER = "1000-000007709"
FILTER_CCY      = "VND"
CLEANUP_HOURS   = 2
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_COLS = [
    'TRDATE', 'TRBRCD', 'USERID', 'JOURSEQ', 'DYTRSEQ', 'LOCAC', 'CCY',
    'BUSCD', 'UNIT', 'TRCD', 'CUSTOMER', 'TRTP', 'REFERENCE', 'REMARK',
    'DRAMOUNT', 'CRAMOUNT', 'CRTDTM',
]

COL_WIDTHS = {
    'TRDATE': 12, 'TRBRCD': 8, 'USERID': 13, 'JOURSEQ': 10, 'DYTRSEQ': 9,
    'LOCAC': 8, 'CCY': 5, 'BUSCD': 7, 'UNIT': 6, 'TRCD': 6, 'CUSTOMER': 18,
    'TRTP': 8, 'REFERENCE': 22, 'REMARK': 52, 'DRAMOUNT': 18, 'CRAMOUNT': 18,
    'CRTDTM': 20,
}

# Chỉ strip các cột dùng trong filter và xây key — không strip tất cả string cols
_STRIP_COLS = {'LOCAC', 'CUSTOMER', 'CCY', 'TRTP', 'REFERENCE', 'TRBRCD', 'DYTRSEQ', 'REMARK'}

_NUM_COLS = frozenset({'DRAMOUNT', 'CRAMOUNT'})

# A–Z rồi AA, AB, … (đủ cho 30 cột)
_COL_LETTERS = [
    (chr(65 + i) if i < 26 else chr(64 + i // 26) + chr(65 + i % 26))
    for i in range(30)
]

log = logging.getLogger(__name__)

# ─── In-memory progress store ─────────────────────────────────────────────────
# key = task_token; value = {pct, msg, done, error, result, _ts}
_progress: dict[str, dict] = {}


def init_progress() -> str:
    """Khởi tạo entry theo dõi tiến độ, trả về task_token."""
    task_token = str(uuid.uuid4())
    _progress[task_token] = {
        "pct": 0, "msg": "Đang khởi tạo...",
        "done": False, "error": None, "result": None,
        "_ts": time.time(),
    }
    return task_token


def get_progress(task_token: str) -> dict | None:
    p = _progress.get(task_token)
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _set_prog(task_token: str | None, pct: int, msg: str) -> None:
    if task_token and task_token in _progress:
        _progress[task_token]["pct"] = pct
        _progress[task_token]["msg"] = msg


# ─── Public API ───────────────────────────────────────────────────────────────

def run_process(zip_bytes: bytes, task_token: str) -> None:
    """Chạy process_zip trong background thread; cập nhật progress và bắt lỗi."""
    try:
        process_zip(zip_bytes, task_token)
    except Exception as e:
        log.error("process_zip lỗi [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e),
                "msg": "Lỗi xử lý — xem log server",
            })


def process_zip(zip_bytes: bytes, task_token: str | None = None) -> dict:
    """Nhận bytes của file ZIP → phân loại → lưu 3 xlsx → trả metadata."""
    _cleanup_old_results()
    t0 = time.time()

    _set_prog(task_token, 5, "Đang giải mã và đọc dữ liệu...")
    df, filtered_rows = _load_data(zip_bytes)
    total_before = len(df) + filtered_rows

    _set_prog(task_token, 30, "Bước 1 — Xác định lệnh hủy...")
    df_huy, df_di, df_khac = _classify(df, task_token)

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

    _set_prog(task_token, 70, f"Xuất Excel — Lệnh Hủy ({len(df_huy):,} dòng)...")
    _write_excel(df_huy,  out_dir / "huy.xlsx",  "Lệnh Hủy",  "C0392B")

    _set_prog(task_token, 80, f"Xuất Excel — Lệnh Đi ({len(df_di):,} dòng)...")
    _write_excel(df_di,   out_dir / "di.xlsx",   "Lệnh Đi",   "27AE60")

    _set_prog(task_token, 92, f"Xuất Excel — Lệnh Khác ({len(df_khac):,} dòng)...")
    _write_excel(df_khac, out_dir / "khac.xlsx", "Lệnh Khác", "E67E22")

    result = {
        "token":         result_token,
        "huy_rows":      len(df_huy),
        "di_rows":       len(df_di),
        "khac_rows":     len(df_khac),
        "total_rows":    total_before,
        "filtered_rows": filtered_rows,
        "elapsed_s":     round(time.time() - t0, 1),
        "process_date":  datetime.now().strftime("%Y%m%d"),
    }

    if task_token and task_token in _progress:
        _progress[task_token].update({
            "pct": 100, "msg": "Hoàn thành!",
            "done": True, "result": result,
        })

    return result


# ─── Internal ─────────────────────────────────────────────────────────────────

def _load_data(zip_bytes: bytes) -> tuple[pd.DataFrame, int]:
    buf = io.BytesIO(zip_bytes)
    dfs = []
    with _ZipFile(buf) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith('.csv')]
        for csv_name in csv_names:
            raw = zf.read(csv_name, pwd=ZIP_PASSWORD)
            dfs.append(pd.read_csv(
                io.BytesIO(raw),
                encoding='utf-8-sig',
                dtype=str,
                keep_default_na=False,
            ))

    df = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]

    df.columns = df.columns.str.strip()

    # Chỉ strip các cột cần thiết — tránh strip 17 cột × 645k dòng
    for col in _STRIP_COLS:
        if col in df.columns:
            df[col] = df[col].str.strip()

    df['REMARK'] = df['REMARK'].fillna('')
    df['DRAMOUNT'] = pd.to_numeric(df['DRAMOUNT'], errors='coerce').fillna(0.0)
    df['CRAMOUNT'] = pd.to_numeric(df['CRAMOUNT'], errors='coerce').fillna(0.0)

    before = len(df)
    df = df[
        (df['LOCAC']    == FILTER_LOCAC) &
        (df['CUSTOMER'] == FILTER_CUSTOMER) &
        (df['CCY']      == FILTER_CCY)
    ].copy()
    return df, before - len(df)


def _classify(
    df: pd.DataFrame,
    task_token: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Phân loại: Hủy (set giao) → Đi (groupby balance=0) → Khác (còn lại)."""
    # ── Bước 1: Lệnh Hủy ──────────────────────────────────────────────────────
    df['abs_amt']  = (df['DRAMOUNT'] + df['CRAMOUNT']).abs()
    df['_huy_key'] = (df['REFERENCE'] + '|' + df['TRBRCD'] + '|'
                      + df['DYTRSEQ'] + '|' + df['abs_amt'].astype(str))

    cancel_keys = set(df.loc[df['TRTP'] == 'Cancel', '_huy_key'])
    normal_keys = set(df.loc[df['TRTP'] == 'Normal', '_huy_key'])
    huy_keys    = cancel_keys & normal_keys

    df_huy       = df[df['_huy_key'].isin(huy_keys)].copy()
    df_remaining = df[~df['_huy_key'].isin(huy_keys)].copy()

    # ── Bước 2: Lệnh Đi ───────────────────────────────────────────────────────
    _set_prog(task_token, 50, "Bước 2 — Phân loại lệnh đi...")
    df_remaining['_amt']    = df_remaining[['DRAMOUNT', 'CRAMOUNT']].abs().max(axis=1)
    df_remaining['_di_key'] = (df_remaining['TRBRCD'] + '|'
                               + df_remaining['_amt'].astype(str) + '|'
                               + df_remaining['REMARK'])

    # Vectorized — nhanh hơn groupby().apply(lambda) ~10-20x
    grp = df_remaining.groupby('_di_key')[['CRAMOUNT', 'DRAMOUNT']].sum()
    grp['balance'] = (grp['CRAMOUNT'] - grp['DRAMOUNT']).round(2)
    zero_keys = set(grp.index[grp['balance'] == 0])

    df_di   = df_remaining[df_remaining['_di_key'].isin(zero_keys)].copy()
    df_khac = df_remaining[~df_remaining['_di_key'].isin(zero_keys)].copy()

    # Xóa cột tạm
    temp_cols = ['abs_amt', '_huy_key', '_amt', '_di_key']
    for tmp_df in (df_huy, df_di, df_khac):
        tmp_df.drop(columns=[c for c in temp_cols if c in tmp_df.columns], inplace=True)

    assert len(df_huy) + len(df_di) + len(df_khac) == len(df), "Lỗi logic phân loại!"

    return df_huy, df_di, df_khac


def _xe(s: str) -> str:
    """XML-escape cho nội dung text (không phải attribute)."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _styles_xml(header_argb: str) -> str:
    """Tạo styles.xml với 3 fonts, 4 fills, 2 borders, 6 cell styles.

    Styles:
      0 – default          1 – summary (bold white on header, no border)
      2 – col header       3 – number data (#,##0)
      4 – total text       5 – total number (#,##0 bold light-blue)
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0"/></numFmts>'
        '<fonts count="3">'
          '<font><sz val="11"/><name val="Calibri"/></font>'
          f'<font><b/><sz val="11"/><name val="Calibri"/><color rgb="FFFFFFFF"/></font>'
          '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="4">'
          '<fill><patternFill patternType="none"/></fill>'
          '<fill><patternFill patternType="gray125"/></fill>'
          f'<fill><patternFill patternType="solid"><fgColor rgb="{header_argb}"/></patternFill></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFD6EAF8"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
          '<border><left/><right/><top/><bottom/><diagonal/></border>'
          '<border>'
            '<left style="thin"><color rgb="FF000000"/></left>'
            '<right style="thin"><color rgb="FF000000"/></right>'
            '<top style="thin"><color rgb="FF000000"/></top>'
            '<bottom style="thin"><color rgb="FF000000"/></bottom>'
            '<diagonal/>'
          '</border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="6">'
          '<xf numFmtId="0"   fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0"   fontId="1" fillId="2" borderId="0" xfId="0"'
          ' applyFont="1" applyFill="1" applyAlignment="1">'
          '<alignment horizontal="left" vertical="center"/></xf>'
          '<xf numFmtId="0"   fontId="1" fillId="2" borderId="1" xfId="0"'
          ' applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
          '<alignment horizontal="center" vertical="center"/></xf>'
          '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
          '<xf numFmtId="0"   fontId="2" fillId="3" borderId="1" xfId="0"'
          ' applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
          '<alignment horizontal="left" vertical="center"/></xf>'
          '<xf numFmtId="164" fontId="2" fillId="3" borderId="1" xfId="0"'
          ' applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" applyAlignment="1">'
          '<alignment horizontal="right" vertical="center"/></xf>'
        '</cellXfs>'
        '</styleSheet>'
    )


def _write_excel(df: pd.DataFrame, path: Path, sheet_name: str, hex_color: str) -> None:
    """Ghi XLSX bằng direct XML — 8x nhanh hơn xlsxwriter, giữ đủ formatting."""
    df_out   = df[OUTPUT_COLS].reset_index(drop=True)
    n_data   = len(df_out)
    dr_total = float(df_out['DRAMOUNT'].sum())
    cr_total = float(df_out['CRAMOUNT'].sum())
    ncols    = len(OUTPUT_COLS)
    last_col = _COL_LETTERS[ncols - 1]

    summary = (f"{sheet_name}: {n_data:,} dòng  |  "
               f"Tổng Nợ: {dr_total:,.0f}  |  Tổng Có: {cr_total:,.0f}")

    styles   = _styles_xml(f'FF{hex_color.upper()}')
    num_idx  = frozenset(i for i, c in enumerate(OUTPUT_COLS) if c in _NUM_COLS)

    # ── Rows XML ──────────────────────────────────────────────────────────────
    rows: list[str] = []

    # Dòng 1: summary (merge toàn bộ, style 1)
    rows.append(
        f'<row r="1">'
        f'<c r="A1" t="inlineStr" s="1"><is><t>{_xe(summary)}</t></is></c>'
        f'</row>'
    )

    # Dòng 2: tên cột (style 2)
    hdr = ''.join(
        f'<c r="{_COL_LETTERS[i]}2" t="inlineStr" s="2"><is><t>{col}</t></is></c>'
        for i, col in enumerate(OUTPUT_COLS)
    )
    rows.append(f'<row r="2">{hdr}</row>')

    # Dòng 3..N+2: data
    for row_0, row in enumerate(df_out.itertuples(index=False)):
        r_num = row_0 + 3
        cells: list[str] = []
        for c_idx, val in enumerate(row):
            cl = _COL_LETTERS[c_idx]
            if c_idx in num_idx:
                cells.append(f'<c r="{cl}{r_num}" s="3"><v>{val:.2f}</v></c>')
            else:
                v = str(val).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                cells.append(f'<c r="{cl}{r_num}" t="inlineStr"><is><t>{v}</t></is></c>')
        rows.append(f'<row r="{r_num}">{"".join(cells)}</row>')

    # Dòng N+3: tổng cộng
    sum_row = n_data + 3
    total: list[str] = [
        f'<c r="A{sum_row}" t="inlineStr" s="4"><is><t>TỔNG CỘNG</t></is></c>'
    ]
    for c_idx, col in enumerate(OUTPUT_COLS[1:], start=1):
        cl = _COL_LETTERS[c_idx]
        if col == 'DRAMOUNT':
            total.append(f'<c r="{cl}{sum_row}" s="5"><v>{dr_total:.2f}</v></c>')
        elif col == 'CRAMOUNT':
            total.append(f'<c r="{cl}{sum_row}" s="5"><v>{cr_total:.2f}</v></c>')
        else:
            total.append(f'<c r="{cl}{sum_row}" t="inlineStr" s="4"><is><t></t></is></c>')
    rows.append(f'<row r="{sum_row}">{"".join(total)}</row>')

    # ── Sheet XML ─────────────────────────────────────────────────────────────
    cols_xml = '<cols>' + ''.join(
        f'<col min="{i+1}" max="{i+1}" width="{COL_WIDTHS.get(col, 12)}" customWidth="1"/>'
        for i, col in enumerate(OUTPUT_COLS)
    ) + '</cols>'

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        + cols_xml
        + '<sheetData>' + ''.join(rows) + '</sheetData>'
        + f'<mergeCells count="1"><mergeCell ref="A1:{last_col}1"/></mergeCells>'
        + f'<autoFilter ref="A2:{last_col}{n_data + 2}"/>'
        + '</worksheet>'
    )

    # ── Bundle thành XLSX (ZIP) ───────────────────────────────────────────────
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xe(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '</Relationships>'
    )
    pkg_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml"'
        ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '</Types>'
    )

    with zipfile.ZipFile(str(path), 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml',         content_types)
        zf.writestr('_rels/.rels',                  pkg_rels)
        zf.writestr('xl/workbook.xml',              workbook_xml)
        zf.writestr('xl/_rels/workbook.xml.rels',   wb_rels)
        zf.writestr('xl/styles.xml',                styles)
        zf.writestr('xl/worksheets/sheet1.xml',     sheet_xml)


def _cleanup_old_results() -> None:
    """Xóa thư mục kết quả và progress entry cũ hơn CLEANUP_HOURS giờ."""
    cutoff = time.time() - CLEANUP_HOURS * 3600

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            if sub.is_dir() and sub.stat().st_mtime < cutoff:
                try:
                    shutil.rmtree(sub)
                except Exception as e:
                    log.warning("Không xóa được %s: %s", sub, e)

    stale = [k for k, v in _progress.items() if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)
