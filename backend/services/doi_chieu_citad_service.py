"""Business logic Đối chiếu CITAD ↔ PaymentHub.

- Buffer CITAD/PaymentHub: dict in-memory tạm giữ dữ liệu Extension vừa gửi
  lên cho tới khi người dùng bấm "Nạp" — KHÔNG cần bền vững qua restart,
  giống bản gốc. Khác bản gốc ở 1 điểm bắt buộc: bản gốc chạy 1 server cục
  bộ trên máy từng người nên buffer vốn chỉ có 1 chủ; nay dùng chung 1
  backend cho cả Phòng Thanh toán nên buffer phải tách theo `owner`
  (username TTTT gửi kèm từ Extension) — nếu không, 2 người cùng đối chiếu
  một lúc sẽ ghi đè/xoá dữ liệu của nhau (đã phát hiện khi review).
- `_build_xlsx()`: port NGUYÊN 1:1 từ `citad-fixed/server.py::_build_xlsx`
  — đây là mẫu báo cáo "BÁO CÁO ĐỐI CHIẾU GIAO DỊCH HỆ THỐNG THANH TOÁN
  ĐIỆN TỬ LIÊN NGÂN HÀNG" đã duyệt, KHÔNG được đổi bất kỳ dòng
  format/màu/border/công thức nào khi port. NGOẠI LỆ duy nhất (theo yêu
  cầu bổ sung sau khi port): dòng ngày ở tiêu đề A4 đổi từ "(dd/mm/yyyy)"
  sang "(Ngày d tháng m năm yyyy)" — xem `_format_vn_date()`.
- Session lưu theo (ngay, staff_id): bản gốc dùng SQLite riêng (file
  doichieu.db, khoá theo ngay+user_id tự nhập) — port sang dùng chung DB
  của TTTT (bảng `doi_chieu_citad_sessions`), khoá theo `staff_id` thật từ
  JWT thay vì chuỗi 'default' hard code.
"""
from __future__ import annotations

import io
import json
import sqlite3

from backend.database import _vn_now
from backend.schemas.doi_chieu_citad import ExportIn


def _format_vn_date(day_str: str) -> str:
    """'dd/mm/yyyy' -> 'Ngày dd tháng m năm yyyy' (khớp mẫu báo cáo NHNN).
    Nếu không parse được (định dạng lạ), trả nguyên chuỗi gốc trong ngoặc."""
    try:
        d, m, y = day_str.strip().split('/')
        return f'Ngày {int(d)} tháng {int(m)} năm {y}'
    except Exception:
        return day_str

# ── CITAD / PaymentHub buffer (in-memory) — tách theo owner (username) ────
# {owner: {key: data}} — mỗi người dùng chỉ thấy/xoá buffer của chính mình.
_citad_buffer: dict[str, dict] = {}
_ph_buffer: dict[str, dict] = {}


def buffer_save_citad(data: dict) -> None:
    owner = data["owner"]
    _citad_buffer.setdefault(owner, {})[data["key"]] = data


def buffer_get_citad(owner: str) -> list:
    return list(_citad_buffer.get(owner, {}).values())


def buffer_clear_citad(owner: str) -> None:
    _citad_buffer.pop(owner, None)


def buffer_save_ph(owner: str, items: list) -> None:
    bucket = _ph_buffer.setdefault(owner, {})
    for item in items:
        bucket[item["key"]] = item


def buffer_get_ph(owner: str) -> list:
    return list(_ph_buffer.get(owner, {}).values())


def buffer_clear_ph(owner: str) -> None:
    _ph_buffer.pop(owner, None)


# ── Session theo ngày + staff_id ────────────────────────────────────────────
def session_save(db: sqlite3.Connection, ngay: str, staff_id: int, data: dict) -> None:
    db.execute(
        """INSERT INTO doi_chieu_citad_sessions (ngay, staff_id, data, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(ngay, staff_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
        (ngay, staff_id, json.dumps(data), _vn_now()),
    )
    db.commit()


def session_get(db: sqlite3.Connection, ngay: str, staff_id: int) -> dict | None:
    row = db.execute(
        "SELECT data FROM doi_chieu_citad_sessions WHERE ngay=? AND staff_id=?",
        (ngay, staff_id),
    ).fetchone()
    return json.loads(row["data"]) if row else None


def session_list(db: sqlite3.Connection, staff_id: int) -> list:
    rows = db.execute(
        "SELECT data FROM doi_chieu_citad_sessions WHERE staff_id=? ORDER BY ngay DESC",
        (staff_id,),
    ).fetchall()
    return [json.loads(r["data"]) for r in rows]


def session_delete(db: sqlite3.Connection, ngay: str, staff_id: int) -> None:
    db.execute(
        "DELETE FROM doi_chieu_citad_sessions WHERE ngay=? AND staff_id=?", (ngay, staff_id)
    )
    db.commit()


# ── Xuất Excel — port NGUYÊN 1:1 từ citad-fixed/server.py::_build_xlsx ─────
def build_xlsx(data: ExportIn) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    CONGS = [1, 9, 18, 17, 12]
    CURS = ['VNĐ', 'USD', 'EUR']
    FK = ['di_ih_m', 'di_ih_t', 'di_il_m', 'di_il_t', 'den_ih_m', 'den_ih_t', 'den_il_m', 'den_il_t']
    TNR = 'Times New Roman'

    def nv(v):
        try:
            return float(str(v).replace(',', '')) if v else 0
        except Exception:
            return 0

    def F(bold=False, size=14, color='000000'):
        return Font(name=TNR, bold=bold, size=size, color=color)

    def AL(h='center', v='center', wrap=False):
        return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

    def Bdr(w='thin', bw=None):
        s = Side(style=w)
        bs = Side(style=bw or w)
        return Border(top=s, bottom=bs, left=s, right=s)

    def Fill(h):
        return PatternFill('solid', fgColor=h)

    ci = [0] * 8
    for c in CONGS:
        for u in CURS:
            src = (data.gD.get(str(c), {}) or {}).get(u, {}) or {}
            for i, f in enumerate(FK):
                ci[i] += nv(src.get(f, 0))
    # Chỉ cộng Napas (nm/nt) vào tổng CITAD — KHÔNG cộng Ebanking (em/et).
    # Đã đối chiếu với DoiChieuCITAD.py::_calc() của tool desktop gốc: gốc
    # CŨNG chỉ cộng napas.den_ih_m/t vào ci['den_ih_m'/'t'], không có dòng
    # tương ứng cho ebank — đây là hành vi gốc, KHÔNG phải sai sót khi port.
    # Ebanking vẫn được in đúng vị trí cột trong Excel (dòng 'Ebanking' dùng
    # data.em/et riêng) nhưng không tính vào dòng Chênh lệch. Nếu Phòng
    # Thanh toán xác nhận đây là bug nghiệp vụ của bản gốc (không phải chủ
    # ý), cần sửa ở đây (ci[4] += nv(data.em); ci[5] += nv(data.et)) — không
    # tự ý đổi vì ảnh hưởng trực tiếp số liệu báo cáo gửi NHNN.
    ci[4] += nv(data.nm)
    ci[5] += nv(data.nt)
    ph = [0] * 8
    for u in CURS:
        src = (data.phD.get(u, {}) or {})
        for i, f in enumerate(FK):
            ph[i] += nv(src.get(f, 0))
    diff = [ci[i] - ph[i] for i in range(8)]
    wb = Workbook()
    ws = wb.active
    ws.title = data.sheet_name[:31]
    NUM = '#,##0'
    for col, wd in zip('ABCDEFGHIJ', [24.43, 7, 11.43, 30.14, 11.43, 28.57, 10.86, 30.14, 12.43, 28.57]):
        ws.column_dimensions[col].width = wd

    def rh(r, h=18.75):
        ws.row_dimensions[r].height = h

    BLU = '4472C4'

    def hcell(r, c, val, merge_to=None):
        cell = ws.cell(r, c)
        cell.value = val
        cell.font = Font(name=TNR, bold=True, size=11, color='FFFFFF')
        cell.alignment = AL()
        cell.fill = Fill(BLU)
        cell.border = Bdr()
        if merge_to:
            ws.merge_cells(f'{chr(64+c)}{r}:{chr(64+merge_to)}{r}')

    rh(1, 53.25)
    ws.merge_cells('B1:E1')
    ws['B1'] = 'NGÂN HÀNG NÔNG NGHIỆP\nVÀ PHÁT TRIỂN NÔNG THÔN VIỆT NAM'
    ws['B1'].font = F()
    ws['B1'].alignment = AL(wrap=True)
    rh(2)
    ws.merge_cells('B2:E2')
    ws['B2'] = 'TRUNG TÂM THANH TOÁN'
    ws['B2'].font = F(bold=True)
    ws['B2'].alignment = AL()
    rh(3)
    rh(4, 57)
    ws.merge_cells('A4:J4')
    ws['A4'] = f'BÁO CÁO ĐỐI CHIẾU GIAO DỊCH HỆ THỐNG THANH TOÁN ĐIỆN TỬ LIÊN NGÂN HÀNG\n({_format_vn_date(data.day_str)})'
    ws['A4'].font = F(bold=True)
    ws['A4'].alignment = AL(wrap=True)
    for c in range(1, 11):
        rh(5)
        rh(6)
        rh(7)
        ws.cell(5, c).fill = Fill(BLU)
        ws.cell(5, c).border = Bdr()
        ws.cell(6, c).fill = Fill(BLU)
        ws.cell(6, c).border = Bdr()
        ws.cell(7, c).fill = Fill(BLU)
        ws.cell(7, c).border = Bdr()
    hcell(5, 3, 'LỆNH ĐI', 6)
    hcell(5, 7, 'LỆNH ĐẾN', 10)
    hcell(6, 3, 'IH', 4)
    hcell(6, 5, 'IL', 6)
    hcell(6, 7, 'IH', 8)
    hcell(6, 9, 'IL', 10)
    for c, lbl in zip(range(3, 11), ['SỐ MÓN', 'SỐ TIỀN'] * 4):
        hcell(7, c, lbl)

    def wr(r, lbl, cur, vals, bold=False, fh=None, lc='000000'):
        rh(r)
        fl = Fill(fh) if fh else None
        for ci2, (val, is_lbl, is_cur) in enumerate(
            [(lbl, True, False), (cur, False, True)] + [(v, False, False) for v in vals]
        ):
            c = ws.cell(r, ci2 + 1)
            if is_lbl:
                c.value = val
                c.font = Font(name=TNR, bold=bold, size=14, color=lc)
                c.alignment = AL()
            elif is_cur:
                c.value = val
                c.font = F()
                c.alignment = AL()
            else:
                if val:
                    c.value = float(val)
                    c.number_format = NUM
                c.font = Font(name=TNR, bold=bold, size=14, color='000000')
                c.alignment = AL('right')
            c.border = Bdr()
            if fl:
                c.fill = fl

    for ri, cur in enumerate(['EUR', 'USD', 'VNĐ']):
        v = [nv((data.phD.get(cur, {}) or {}).get(f, 0)) for f in FK]
        wr(8 + ri, f'Payment {cur}', cur, v, bold=True)
    wr(11, 'CITAD', '', ci, bold=True, fh='BDD7EE', lc='1F3864')
    row = 12
    for cong in CONGS:
        for ci2, cur in enumerate(CURS):
            v = [nv((data.gD.get(str(cong), {}).get(cur, {}) or {}).get(f, 0)) for f in FK]
            wr(row, f'Cổng {cong}' if ci2 == 0 else '', cur, v, bold=(ci2 == 0))
            row += 1
    for lbl in ['Waiting for AUTO', 'Waiting for manual']:
        rh(row)
        ws.cell(row, 1).value = lbl
        ws.cell(row, 1).font = F(bold=True)
        ws.cell(row, 1).alignment = AL()
        for c in range(1, 11):
            ws.cell(row, c).border = Bdr()
        row += 1
    wr(row, 'Napas', '', [0, 0, 0, 0, data.nm, data.nt, 0, 0])
    row += 1
    wr(row, 'Ebanking', '', [0, 0, 0, 0, data.em, data.et, 0, 0])
    row += 1
    rh(row)
    ws.cell(row, 1).value = 'Chênh lệch'
    ws.cell(row, 1).font = Font(name=TNR, bold=True, size=14, color='7F0000')
    ws.cell(row, 1).alignment = AL()
    ws.cell(row, 1).fill = Fill('FFE699')
    ws.cell(row, 1).border = Bdr('thin', 'medium')
    ws.cell(row, 2).value = 0
    ws.cell(row, 2).font = F(bold=True)
    ws.cell(row, 2).alignment = AL()
    ws.cell(row, 2).fill = Fill('FFE699')
    ws.cell(row, 2).border = Bdr('thin', 'medium')
    for i, v in enumerate(diff):
        c = ws.cell(row, 3 + i)
        c.value = v if v else None
        c.number_format = NUM
        c.font = Font(name=TNR, bold=True, size=14, color='006100' if v == 0 else 'FF0000')
        c.alignment = AL('right')
        c.fill = Fill('FFE699')
        c.border = Bdr('thin', 'medium')
    row += 2
    rh(row - 1)
    rh(row)
    ws.merge_cells(f'A{row}:C{row}')
    ws.cell(row, 1).value = '                  LẬP BẢNG'
    ws.cell(row, 1).font = F(bold=True)
    ws.cell(row, 1).alignment = AL()
    ws.merge_cells(f'H{row}:I{row}')
    ws.cell(row, 8).value = 'KIỂM SOÁT'
    ws.cell(row, 8).font = F(bold=True)
    ws.cell(row, 8).alignment = AL()
    row += 1
    for _ in range(4):
        rh(row)
        row += 1
    rh(row)
    ws.cell(row, 2).value = data.lb
    ws.cell(row, 2).font = F(bold=True)
    ws.cell(row, 2).alignment = AL()
    ws.merge_cells(f'H{row}:I{row}')
    ws.cell(row, 8).value = data.ks
    ws.cell(row, 8).font = F(bold=True)
    ws.cell(row, 8).alignment = AL()
    ws.print_area = f'A1:J{row}'

    from openpyxl.worksheet.page import PageMargins
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.3, bottom=0.3, header=0.1, footer=0.1)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
