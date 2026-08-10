"""
Duty Export Service — tạo file Excel lịch trực theo tuần.
Format: A4 ngang, 8 cột (A-H), tiếng Việt đầy đủ.
"""
from io import BytesIO
from datetime import date, timedelta
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.worksheet.page import PageMargins

WEEKDAY_VI = {0: "T2", 1: "T3", 2: "T4", 3: "T5", 4: "T6", 5: "T7", 6: "CN"}

CLR_TITLE_BG  = "1F4E79"
CLR_TITLE_FG  = "FFFFFF"
CLR_HEADER_BG = "BDD7EE"
CLR_SETTLE_BG = "EDE7F6"
CLR_SUB_BG    = "F5F5F5"
CLR_WHITE     = "FFFFFF"
CLR_HOLIDAY   = "E8E8E8"

_thin = Side(style="thin")
BORDER_ALL  = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

_NCOLS = 8

_SHIFT_SUFFIX = {
    "cutoff":          " (C/O)",
    "friday":          " (T6)",
    "settlement_main": " (QT)",
    "settlement_sub":  " (QT-P)",
}


def _ten_lanh_dao(shift: dict) -> str:
    """Một ca có thể có nhiều Lãnh đạo — xuống dòng trong cùng một ô."""
    ten = [p.get("full_name", "") for p in (shift.get("leaders") or [])]
    if not ten and shift.get("leader"):
        ten = [shift["leader"].get("full_name", "")]
    return "\n".join(ten)


def _fill(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color)


def _font(bold=False, size=11, color="000000", italic=False) -> Font:
    return Font(name="Times New Roman", bold=bold, size=size, color=color, italic=italic)


def _align(h="left", v="center", wrap=False) -> Alignment:
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)


def _apply_row(ws, row: int, values: list, bold=False, fill_hex=None,
               border=True, font_colors=None, size=11, wrap=True):
    from openpyxl.cell.cell import MergedCell
    for col_idx, val in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col_idx)
        if isinstance(cell, MergedCell):
            continue
        cell.value = val if val != "" else None
        fc = (font_colors[col_idx - 1] if font_colors and col_idx - 1 < len(font_colors)
              else "000000")
        cell.font = _font(bold=bold, size=size, color=fc)
        cell.alignment = _align(wrap=wrap)
        if fill_hex:
            cell.fill = _fill(fill_hex)
        if border:
            cell.border = BORDER_ALL


def build_week_excel(shifts: list, week_start: date, week_end: date,
                     signer_name: str = "Nguyễn Quốc Hùng",
                     holiday_map: dict = None) -> bytes:
    """
    Tạo file .xlsx cho 1 tuần.
    shifts: list shift dict từ duty_schedule_service._enrich_shift
    Trả về bytes.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = f"Tuan {week_start:%d%m}"

    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins = PageMargins(
        left=0.5, right=0.5, top=0.75, bottom=0.75, header=0.3, footer=0.3,
    )

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 28
    ws.column_dimensions["D"].width = 36
    ws.column_dimensions["E"].width = 38
    ws.column_dimensions["F"].width = 4
    ws.column_dimensions["G"].width = 4
    ws.column_dimensions["H"].width = 4

    is_settlement_week = any(
        s.get("shift_type") == "settlement_main" for s in shifts
    )

    shift_by_date: dict = {}
    for s in shifts:
        d = s.get("shift_date", "")
        shift_by_date.setdefault(d, []).append(s)

    # ── Tiêu đề ────────────────────────────────────────────────
    title = (f"LỊCH TRỰC TỪ NGÀY {week_start:%d/%m/%Y} "
             f"ĐẾN NGÀY {week_end:%d/%m/%Y}")
    ws.merge_cells("A1:H1")
    ws["A1"].value = title
    ws["A1"].font = _font(bold=True, size=13, color=CLR_TITLE_FG)
    ws["A1"].fill = _fill(CLR_TITLE_BG)
    ws["A1"].alignment = _align(h="center", v="center")
    ws.row_dimensions[1].height = 24

    if is_settlement_week:
        header_row = 2
    else:
        ws.row_dimensions[2].height = 6
        header_row = 3

    ws.merge_cells(f"C{header_row}:D{header_row}")
    _apply_row(ws, header_row,
               ["THỨ", "NGÀY", "NHÂN VIÊN", "", "LÃNH ĐẠO", "", "", ""],
               bold=True, fill_hex=CLR_HEADER_BG, size=11)
    for col in range(1, _NCOLS + 1):
        ws.cell(row=header_row, column=col).alignment = _align(h="center", v="center")
    ws.row_dimensions[header_row].height = 20

    # ── Data rows ─────────────────────────────────────────────
    current_row = header_row + 1
    current = week_start
    while current <= week_end:
        wd = current.weekday()
        if wd >= 5:
            current += timedelta(days=1)
            continue

        date_str = current.strftime("%Y-%m-%d")
        day_shifts = shift_by_date.get(date_str, [])

        base_thu = WEEKDAY_VI.get(wd, "")
        shift_type_day = day_shifts[0].get("shift_type", "normal") if day_shifts else "normal"
        thu_label  = base_thu + _SHIFT_SUFFIX.get(shift_type_day, "")
        date_label = current.strftime("%d/%m/%Y")

        # Ca quyết toán nay là MỘT bản ghi, nhóm trực phụ nằm trong nv_phu
        main_shift = day_shifts[0] if day_shifts else None

        if main_shift is None:
            if holiday_map and date_str in holiday_map:
                label = holiday_map[date_str]
                text  = f"(Nghỉ lễ: {label})" if label else "(Nghỉ lễ)"
                ws.merge_cells(f"C{current_row}:E{current_row}")
                _apply_row(ws, current_row,
                           [thu_label, date_label, text, "", "", "", "", ""],
                           fill_hex=CLR_HOLIDAY, font_colors=["808080"] * 8)
            else:
                _apply_row(ws, current_row,
                           [thu_label, date_label, "", "", "", "", "", ""],
                           fill_hex=CLR_WHITE)
            current_row += 1
            current += timedelta(days=1)
            continue

        if is_settlement_week and main_shift:
            main_row_idx = current_row
            leader_name = _ten_lanh_dao(main_shift)
            # SP hiển thị ở đầu danh sách NV
            sp_name = (main_shift.get("sp") or {}).get("full_name", "")
            nv_names = [nv.get("full_name", "") for nv in (main_shift.get("nvs") or [])]
            if sp_name:
                nv_names = [sp_name] + nv_names
            all_nv_str = "\n".join(nv_names)

            ws.merge_cells(f"C{current_row}:D{current_row}")
            _apply_row(ws, current_row,
                       [thu_label, date_label, all_nv_str, "", leader_name, "", "", ""],
                       fill_hex=CLR_SETTLE_BG, wrap=True)
            ws.row_dimensions[current_row].height = max(30, 15 * max(1, len(nv_names)))
            current_row += 1

            sub_nvs = main_shift.get("nv_phu") or []
            if sub_nvs:
                all_sub = [nv.get("full_name", "") for nv in sub_nvs]
                mid = (len(all_sub) + 1) // 2
                _apply_row(ws, current_row,
                           ["", "", "\n".join(all_sub[:mid]), "\n".join(all_sub[mid:]),
                            "", "", "", ""],
                           fill_hex=CLR_SUB_BG, wrap=True)
                ws.row_dimensions[current_row].height = max(18, 15 * max(1, mid))
            else:
                _apply_row(ws, current_row,
                           ["", "", "", "", "", "", "", ""], fill_hex=CLR_SUB_BG)
                ws.row_dimensions[current_row].height = 18

            sub_row_idx = current_row
            ws.merge_cells(f"A{main_row_idx}:A{sub_row_idx}")
            ws.merge_cells(f"B{main_row_idx}:B{sub_row_idx}")
            ws.cell(row=main_row_idx, column=1).alignment = _align(h="center", v="center")
            ws.cell(row=main_row_idx, column=2).alignment = _align(h="center", v="center")
            current_row += 1

        else:
            shift = main_shift
            leader_name = ""
            sp_name = ""
            nv_names: List[str] = []

            if shift:
                leader_name = _ten_lanh_dao(shift)
                sp_name     = (shift.get("sp") or {}).get("full_name", "")
                nv_names    = [nv.get("full_name", "") for nv in (shift.get("nvs") or [])]
                if sp_name:
                    nv_names = [sp_name] + nv_names

            mid = (len(nv_names) + 1) // 2
            _apply_row(ws, current_row,
                       [thu_label, date_label,
                        "\n".join(nv_names[:mid]), "\n".join(nv_names[mid:]),
                        leader_name, "", "", ""],
                       wrap=True)
            ws.row_dimensions[current_row].height = max(20, 15 * max(1, len(nv_names)))
            ws.cell(row=current_row, column=1).alignment = _align(h="center", v="center")
            ws.cell(row=current_row, column=2).alignment = _align(h="center", v="center")
            current_row += 1

        current += timedelta(days=1)

    # ── Ghi chú & chữ ký ──────────────────────────────────────
    current_row += 1
    note_row = current_row

    if is_settlement_week:
        ws.cell(row=note_row, column=1).value = "Ghi chú :"
        ws.cell(row=note_row, column=1).font = _font(bold=True, size=10)
        ws.cell(row=note_row, column=2).value = (
            "- Cán bộ không trực chính làm việc theo giờ của hệ thống là 19h"
        )
        ws.cell(row=note_row, column=2).font = _font(size=10, italic=True)
        ws.cell(row=note_row, column=2).alignment = _align(wrap=True)
        ws.merge_cells(f"B{note_row}:H{note_row}")
        ws.row_dimensions[note_row].height = 15

        note_row += 1
        ws.cell(row=note_row, column=2).value = (
            "- Cán bộ không có tên trong lịch trực làm việc theo giờ làm việc của Agribank"
        )
        ws.cell(row=note_row, column=2).font = _font(size=10, italic=True)
        ws.cell(row=note_row, column=2).alignment = _align(wrap=True)
        ws.merge_cells(f"B{note_row}:H{note_row}")
        ws.row_dimensions[note_row].height = 15

        note_row += 2
        ws.cell(row=note_row, column=5).value = "GIÁM ĐỐC"
        ws.cell(row=note_row, column=5).font = _font(bold=True, size=11)
        ws.cell(row=note_row, column=5).alignment = _align(h="center")
        note_row += 3
    else:
        ws.cell(row=note_row, column=1).value = "Ghi chú :"
        ws.cell(row=note_row, column=1).font = _font(bold=True, size=10)
        ws.merge_cells(f"A{note_row}:H{note_row}")
        note_row += 5

    ws.cell(row=note_row, column=5).value = signer_name
    ws.cell(row=note_row, column=5).font = _font(size=11)
    ws.cell(row=note_row, column=5).alignment = _align(h="center")

    ws.print_area = f"A1:H{note_row}"

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
