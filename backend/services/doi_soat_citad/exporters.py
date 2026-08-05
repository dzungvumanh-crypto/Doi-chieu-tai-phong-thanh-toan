# -*- coding: utf-8 -*-
"""
exporters.py
------------
Port NGUYÊN xuất Excel từ `citad-fixed/DoiSoatCITAD.py` (`export_doiSoat`,
`_add_filter_sheet`, `_style`, `_apply`, `HEADERS`, `CLR`) — giữ đúng màu,
label, độ rộng cột, freeze pane như bản gốc.

`STATUS_LBL` / `CLR_FG` được gộp thành hằng số dùng chung ở đây (bản gốc
định nghĩa lặp lại y hệt ở 3 nơi: export_doiSoat, _add_filter_sheet, và UI
tkinter) để cả export lẫn trang frontend `doi_soat_citad.py` dùng chung 1
nguồn — không đổi giá trị nào so với bản gốc.
"""
from __future__ import annotations

import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADERS = ['STT', 'Kết quả', 'Loại GD', 'Chiều', 'Số GD (CITAD)', 'Key Agribank',
           'Dịch vụ', 'Số tiền', 'Loại tiền', 'Ngày GD', 'Ngân hàng', 'Trạng thái']

CLR = {
    'title_bg': 'EFF6FF', 'title_fg': '1E3A5F',
    'hdr_dark': '1E3A5F', 'hdr_med': '2E5F9E',
    'red1': 'FFCCCC', 'red2': 'FFE5E5',
    'org1': 'FFF3CD', 'org2': 'FFF8E6',
    'white': 'FFFFFF', 'gray': 'F5F7FA',
    'red_txt': 'A32D2D', 'blue_txt': '185FA5',
    'green_txt': '3B6D11', 'org_txt': 'A05A00',
}

STATUS_LBL = {
    'only_citad': 'Chỉ CITAD', 'only_ipcas': 'Chỉ IPCAS',
    'only_hub': 'Chỉ Hub', 'lech_trang_thai': 'Lệch TT', 'both': 'Khớp',
}
CLR_FG = {
    'only_citad': CLR['red_txt'], 'only_ipcas': CLR['blue_txt'],
    'only_hub': CLR['blue_txt'], 'lech_trang_thai': CLR['org_txt'], 'both': CLR['green_txt'],
}

_COL_WIDTHS = [5, 14, 8, 8, 18, 18, 28, 15, 10, 12, 28, 12]


def _style(bg='FFFFFF', fg='000000', bold=False, sz=10, h='left'):
    thin = Side(style='thin', color='CCCCCC')
    return {
        'font': Font(name='Arial', size=sz, bold=bold, color=fg),
        'fill': PatternFill('solid', fgColor=bg),
        'alignment': Alignment(horizontal=h, vertical='center'),
        'border': Border(top=thin, bottom=thin, left=thin, right=thin),
    }


def _apply(cell, **kw):
    for k, v in kw.items():
        setattr(cell, k, v)


def export_doiSoat(lech_rows, n_khop, ngay_cham, filepath):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Đối soát chi tiết'

    n_lech = len(lech_rows)
    n_total = n_khop + n_lech

    # ── Row 1: tiêu đề ────────────────────────────────────────────
    ws.merge_cells('A1:L1')
    c = ws['A1']
    c.value = f'KẾT QUẢ ĐỐI SOÁT LỆNH — CITAD (NHNN) vs AGRIBANK (IPCAS) — Ngày {ngay_cham}'
    _apply(c, **_style(bg=CLR['title_bg'], fg=CLR['title_fg'], bold=True, sz=13, h='center'))

    # ── Row 2: tổng kết ───────────────────────────────────────────
    ws.merge_cells('A2:L2')
    c = ws['A2']
    c.value = (f'Tổng: {n_total:,} lệnh   |   ✓ Khớp: {n_khop:,}   |   '
               f'✗ Lệch: {n_lech:,}   |   Xuất lúc: {datetime.datetime.now().strftime("%H:%M %d/%m/%Y")}')
    _apply(c, **_style(bg=CLR['title_bg'], fg='374151', sz=9, h='center'))

    # ── Row 3: trống ──────────────────────────────────────────────
    ws.row_dimensions[3].height = 6

    # ── Row 4: group headers ──────────────────────────────────────
    ws.merge_cells('A4:D4'); ws['A4'].value = 'THÔNG TIN CHUNG'
    ws.merge_cells('E4:H4'); ws['E4'].value = 'CITAD (NHNN)'
    ws.merge_cells('I4:L4'); ws['I4'].value = 'AGRIBANK (IPCAS)'
    for col, bg in [('A', CLR['hdr_dark']), ('E', CLR['hdr_dark']), ('I', CLR['hdr_med'])]:
        cell = ws[col + '4']
        _apply(cell, **_style(bg=bg, fg='FFFFFF', bold=True, sz=10, h='center'))
    # fill merged cells
    for rng, bg in [('B4:D4', CLR['hdr_dark']), ('F4:H4', CLR['hdr_dark']), ('J4:L4', CLR['hdr_med'])]:
        for cell in ws[rng][0]:
            _apply(cell, **_style(bg=bg, fg='FFFFFF', bold=True, sz=10, h='center'))

    # ── Row 5: column headers ─────────────────────────────────────
    for ci, h in enumerate(HEADERS, 1):
        bg = CLR['hdr_dark'] if ci <= 8 else CLR['hdr_med']
        cell = ws.cell(5, ci, h)
        _apply(cell, **_style(bg=bg, fg='FFFFFF', bold=True, sz=9, h='center'))

    # ── Data rows ─────────────────────────────────────────────────
    for ri, r in enumerate(lech_rows):
        row_num = ri + 6
        st = r.get('status', '')
        even = ri % 2 == 0
        if st == 'lech_trang_thai':
            bg = CLR['org1'] if even else CLR['org2']
        elif st != 'both':
            bg = CLR['red1'] if even else CLR['red2']
        else:
            bg = CLR['white'] if even else CLR['gray']
        st_lbl = STATUS_LBL.get(st, st)
        st_fg = (CLR['red_txt'] if st == 'only_citad' else
                 CLR['blue_txt'] if st in ('only_ipcas', 'only_hub') else
                 CLR['org_txt'] if st == 'lech_trang_thai' else
                 CLR['green_txt'])

        so_tien = r.get('so_tien') or r.get('so_tien_agri') or ''
        try:
            so_tien = int(so_tien)
        except (ValueError, TypeError):
            so_tien = ''

        vals = [
            ri + 1, st_lbl,
            (r.get('loai') or '').upper(),
            'Đi' if r.get('chieu') == 'di' else 'Đến',
            r.get('so_gd') or '',
            r.get('key_agri') or '',
            r.get('dich_vu') or '',
            so_tien,
            r.get('loai_tien') or 'VNĐ',
            r.get('ngay') or '',
            r.get('nh_nhan') or '',
            r.get('trang_thai') or '',
        ]

        for ci, val in enumerate(vals, 1):
            cell = ws.cell(row_num, ci, val)
            h = 'right' if ci == 8 else ('center' if ci in (1, 2, 3, 4, 9) else 'left')
            fg = st_fg if ci == 2 else '111827'
            bold = ci == 2
            _apply(cell, **_style(bg=bg, fg=fg, bold=bold, sz=10, h=h))
            if ci == 8 and isinstance(val, int):
                cell.number_format = '#,##0'

    # ── Độ rộng cột ───────────────────────────────────────────────
    for i, w in enumerate(_COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Freeze ────────────────────────────────────────────────────
    ws.freeze_panes = 'A6'

    # ── Sheet 2-4: các sheet lọc ─────────────────────────────────
    _add_filter_sheet(wb, lech_rows, n_khop, ngay_cham, 'Chỉ CITAD', 'only_citad')
    _add_filter_sheet(wb, lech_rows, n_khop, ngay_cham, 'Chỉ Agribank', ('only_ipcas', 'only_hub'))
    _add_filter_sheet(wb, lech_rows, n_khop, ngay_cham, 'Lệch trạng thái', 'lech_trang_thai')

    wb.save(filepath)


def _add_filter_sheet(wb, rows, n_khop, ngay_cham, title, status_filter):
    ws = wb.create_sheet(title)
    if isinstance(status_filter, tuple):
        filtered = [r for r in rows if r.get('status') in status_filter]
    else:
        filtered = [r for r in rows if r.get('status') == status_filter]

    ws.merge_cells('A1:L1')
    ws['A1'].value = f'{title} — Ngày {ngay_cham} — {len(filtered):,} lệnh'
    _apply(ws['A1'], **_style(bg=CLR['title_bg'], fg=CLR['title_fg'], bold=True, sz=12, h='center'))

    for ci, h in enumerate(HEADERS, 1):
        cell = ws.cell(2, ci, h)
        _apply(cell, **_style(bg=CLR['hdr_dark'], fg='FFFFFF', bold=True, sz=9, h='center'))

    for ri, r in enumerate(filtered):
        row_num = ri + 3
        st = r.get('status', '')
        bg = (CLR['org1'] if ri % 2 == 0 else CLR['org2']) if st == 'lech_trang_thai' else (
            CLR['red1'] if ri % 2 == 0 else CLR['red2']
        )
        so_tien = r.get('so_tien') or ''
        try:
            so_tien = int(so_tien)
        except Exception:
            so_tien = ''

        vals = [ri + 1, STATUS_LBL.get(st, st),
                (r.get('loai') or '').upper(),
                'Đi' if r.get('chieu') == 'di' else 'Đến',
                r.get('so_gd') or '', r.get('key_agri') or '',
                r.get('dich_vu') or '', so_tien,
                r.get('loai_tien') or 'VNĐ', r.get('ngay') or '',
                r.get('nh_nhan') or '', r.get('trang_thai') or '']

        for ci, val in enumerate(vals, 1):
            cell = ws.cell(row_num, ci, val)
            h = 'right' if ci == 8 else ('center' if ci in (1, 2, 3, 4, 9) else 'left')
            fg = CLR_FG.get(st, '111827') if ci == 2 else '111827'
            _apply(cell, **_style(bg=bg, fg=fg, bold=(ci == 2), sz=10, h=h))
            if ci == 8 and isinstance(val, int):
                cell.number_format = '#,##0'

    for i, w in enumerate(_COL_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A3'
