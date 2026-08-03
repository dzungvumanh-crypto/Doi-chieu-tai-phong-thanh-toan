"""Business logic Đối chiếu CITAD ↔ PaymentHub.

- Buffer CITAD/PaymentHub: dict in-memory tạm giữ dữ liệu Extension vừa gửi
  lên cho tới khi người dùng bấm "Nạp" — KHÔNG cần bền vững qua restart,
  giống bản gốc. Khác bản gốc ở 1 điểm bắt buộc: bản gốc chạy 1 server cục
  bộ trên máy từng người nên buffer vốn chỉ có 1 chủ; nay dùng chung 1
  backend cho cả Phòng Thanh toán nên buffer phải tách theo `owner`.

  `owner` KHÔNG do client tự khai (đã sửa sau review bảo mật — trước đây
  Extension tự gửi `owner` trong payload, ai có khoá chung cũng ghi được
  buffer dưới bất kỳ tên nào, kể cả chèn số liệu giả để chênh lệch ra đúng
  0). Giờ `owner` = username suy ra từ 1 "mã kết nối" (extension token) cá
  nhân — mỗi người tự tạo trên `/doi_chieu_citad` sau khi đã đăng nhập thật,
  dán vào Extension 1 lần (xem `generate_extension_token`/
  `resolve_extension_token` bên dưới). Token bị lộ chỉ ảnh hưởng đúng 1
  người, thu hồi riêng lẻ được — không cần đổi khoá chung cho cả phòng.
- `_build_xlsx()`: port NGUYÊN 1:1 từ `citad-fixed/server.py::_build_xlsx`
  — đây là mẫu báo cáo "BÁO CÁO ĐỐI CHIẾU GIAO DỊCH HỆ THỐNG THANH TOÁN
  ĐIỆN TỬ LIÊN NGÂN HÀNG" đã duyệt, KHÔNG được đổi bất kỳ dòng
  format/màu/border/công thức nào khi port. NGOẠI LỆ duy nhất (theo yêu
  cầu bổ sung sau khi port): dòng ngày ở tiêu đề A4 đổi từ "(dd/mm/yyyy)"
  sang "(Ngày d tháng m năm yyyy)" — xem `_format_vn_date()`.
- Session lưu theo `ngay` — 1 bản CHUNG cho cả phòng (bản gốc dùng SQLite
  riêng, khoá theo ngay+user_id tự nhập, vốn chỉ 1 người/máy nên không có
  khái niệm "chung"). Nhiều người cùng chấm 1 ngày: ai lưu sau cùng là bản
  hiện hành (ghi đè `doi_chieu_citad_sessions`), nhưng mỗi lần lưu đều ghi
  thêm 1 dòng vào `doi_chieu_citad_history` (ngay, staff_id, created_at) —
  xem `get_reconciliation_history()` — nút "Lịch sử đối chiếu" trên trang
  hiển thị đúng thứ tự ai đã chấm ngày đó lúc nào.
- `build_extension_zip()`: nén thư mục `extension_citad/` (nằm ở gốc repo,
  cạnh `backend/`) thành 1 file .zip TẠI THỜI ĐIỂM TẢI — không lưu sẵn file
  zip nào, luôn khớp đúng code hiện tại của extension, không cần bước build
  riêng. Phục vụ nút "Tải Extension" trên `/doi_chieu_citad` (Chrome không
  cho web tự cài extension — đây chỉ là tải file để người dùng tự Load
  unpacked, xem `extension_citad/README.md`).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import secrets
import sqlite3
import zipfile
from datetime import datetime

from backend.core.config import BASE_DIR
from backend.database import _vn_now
from backend.schemas.doi_chieu_citad import ExportIn

EXTENSION_DIR = BASE_DIR / "extension_citad"


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


def buffer_save_citad(owner: str, data: dict) -> None:
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


# ── Extension token — mỗi staff 1 token cá nhân (thay khoá tĩnh dùng chung) ──
# Chỉ lưu SHA-256 hash, không lưu plaintext — không thể xem lại token cũ,
# chỉ tạo mã mới (tự thu hồi mã cũ vì PRIMARY KEY staff_id, 1 token/người).
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_extension_token(db: sqlite3.Connection, staff_id: int) -> str:
    """Tạo token mới cho staff_id, GHI ĐÈ token cũ nếu có (thu hồi tự động).
    Trả về token PLAINTEXT — CHỈ lần này, gọi lại sẽ ra token khác."""
    token = secrets.token_urlsafe(32)
    now = _vn_now()
    db.execute(
        """INSERT INTO doi_chieu_citad_extension_tokens (staff_id, token_hash, created_at, last_used_at)
           VALUES (?,?,?,NULL)
           ON CONFLICT(staff_id) DO UPDATE SET token_hash=excluded.token_hash,
                                                created_at=excluded.created_at,
                                                last_used_at=NULL""",
        (staff_id, _hash_token(token), now),
    )
    db.commit()
    return token


# last_used_at chỉ phục vụ hiển thị trạng thái tương đối trên UI ("lần dùng
# gần nhất") — không cần chính xác từng giây. Extension gọi buffer liên tục
# (mỗi lần MutationObserver bắt được kết quả mới), nếu ghi lại last_used_at
# trên MỌI request thì mỗi request tốn thêm 1 giao dịch ghi (khoá cả file
# SQLite, cạnh tranh trực tiếp với audit_logs của AuditMiddleware và mọi
# module khác dùng chung data/ksnb.db) chỉ để đổi 1 con số hiển thị không ai
# cần xem realtime. Gộp lại: chỉ ghi khi đã quá _LAST_USED_THROTTLE_SECONDS
# kể từ lần ghi trước.
_LAST_USED_THROTTLE_SECONDS = 300


def resolve_extension_token(db: sqlite3.Connection, token: str) -> tuple[int, str] | None:
    """Token hợp lệ -> trả về (staff_id, username) chủ token — staff_id để
    caller ghi audit đúng người (xem `_resolve_extension_owner` trong
    `backend/api/doi_chieu_citad.py`), username để dùng làm khoá buffer như
    trước. Chỉ ghi lại last_used_at nếu đã "cũ" hơn
    _LAST_USED_THROTTLE_SECONDS (xem comment trên) — phần lớn request KHÔNG
    còn tốn giao dịch ghi nào ở đây nữa.
    Token sai/rỗng/đã bị thu hồi -> None (caller trả 403, không đoán bừa)."""
    if not token:
        return None
    row = db.execute(
        """SELECT t.staff_id, t.last_used_at, u.username FROM doi_chieu_citad_extension_tokens t
           JOIN user_tttt u ON u.id = t.staff_id AND u.is_active = 1
           WHERE t.token_hash = ?""",
        (_hash_token(token),),
    ).fetchone()
    if not row:
        return None
    now = _vn_now()
    last_used = row["last_used_at"]
    stale = last_used is None or (
        now - datetime.fromisoformat(str(last_used))
    ).total_seconds() >= _LAST_USED_THROTTLE_SECONDS
    if stale:
        db.execute(
            "UPDATE doi_chieu_citad_extension_tokens SET last_used_at=? WHERE staff_id=?",
            (now, row["staff_id"]),
        )
        db.commit()
    return row["staff_id"], row["username"]


def revoke_extension_token(db: sqlite3.Connection, staff_id: int) -> None:
    db.execute("DELETE FROM doi_chieu_citad_extension_tokens WHERE staff_id=?", (staff_id,))
    db.commit()


def get_extension_token_status(db: sqlite3.Connection, staff_id: int) -> dict:
    row = db.execute(
        "SELECT created_at, last_used_at FROM doi_chieu_citad_extension_tokens WHERE staff_id=?",
        (staff_id,),
    ).fetchone()
    if not row:
        return {"connected": False, "created_at": None, "last_used_at": None}
    return {
        "connected": True,
        "created_at": str(row["created_at"]) if row["created_at"] else None,
        "last_used_at": str(row["last_used_at"]) if row["last_used_at"] else None,
    }


# ── Session theo ngày — 1 bản CHUNG cho cả phòng (không tách theo người) ────
# Nhiều người cùng chấm 1 ngày: ai lưu sau cùng là bản hiện hành (ghi đè),
# nhưng mỗi lần lưu đều lưu NGUYÊN VẸN số liệu phiên chấm đó vào
# doi_chieu_citad_history — xem get_reconciliation_history()/
# get_history_entry_data() — nên xem/tải lại đúng bản của từng lần lưu,
# không chỉ biết ai đã sửa lúc nào.
def session_save(db: sqlite3.Connection, ngay: str, staff_id: int, data: dict) -> None:
    now = _vn_now()
    data_json = json.dumps(data)
    db.execute(
        """INSERT INTO doi_chieu_citad_sessions (ngay, data, updated_at, updated_by)
           VALUES (?,?,?,?)
           ON CONFLICT(ngay) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at,
                                            updated_by=excluded.updated_by""",
        (ngay, data_json, now, staff_id),
    )
    db.execute(
        "INSERT INTO doi_chieu_citad_history (ngay, staff_id, data, created_at) VALUES (?,?,?,?)",
        (ngay, staff_id, data_json, now),
    )
    db.commit()


def session_get(db: sqlite3.Connection, ngay: str) -> dict | None:
    row = db.execute(
        "SELECT data FROM doi_chieu_citad_sessions WHERE ngay=?",
        (ngay,),
    ).fetchone()
    return json.loads(row["data"]) if row else None


def session_list(db: sqlite3.Connection) -> list:
    rows = db.execute(
        "SELECT data FROM doi_chieu_citad_sessions ORDER BY ngay DESC",
    ).fetchall()
    return [json.loads(r["data"]) for r in rows]


def _parse_ngay(ngay: str) -> datetime | None:
    try:
        return datetime.strptime(ngay.strip(), "%d/%m/%Y")
    except Exception:
        return None


def get_reconciliation_days(
    db: sqlite3.Connection, tu_ngay: str | None = None, den_ngay: str | None = None
) -> list:
    """1 dòng/ngày đã có ai chấm — ngày, người lưu sau cùng, số lần lưu,
    cập nhật lúc — phục vụ tab "Lịch sử" (bảng nhiều ngày cùng lúc, lọc
    theo khoảng ngày). Lọc/sắp xếp bằng Python vì cột `ngay` lưu dạng text
    dd/mm/yyyy — so sánh chuỗi trực tiếp trong SQL sẽ SAI thứ tự thời gian
    (ví dụ "01/12/2026" < "05/01/2026" theo string nhưng đến sau)."""
    rows = db.execute(
        """SELECT s.ngay, s.updated_at, u.username AS updated_by_username,
                  (SELECT COUNT(*) FROM doi_chieu_citad_history h WHERE h.ngay = s.ngay) AS so_lan_luu
           FROM doi_chieu_citad_sessions s
           LEFT JOIN user_tttt u ON u.id = s.updated_by"""
    ).fetchall()

    tu_dt = _parse_ngay(tu_ngay) if tu_ngay else None
    den_dt = _parse_ngay(den_ngay) if den_ngay else None

    parsed = []
    for r in rows:
        d = _parse_ngay(r["ngay"])
        if d is None:  # bỏ qua dòng ngày lỗi định dạng, không để sập cả danh sách
            continue
        if tu_dt and d < tu_dt:
            continue
        if den_dt and d > den_dt:
            continue
        parsed.append((d, {
            "ngay": r["ngay"],
            "updated_by_username": r["updated_by_username"],
            "updated_at": str(r["updated_at"]) if r["updated_at"] else None,
            "so_lan_luu": r["so_lan_luu"],
        }))
    parsed.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in parsed]


def get_reconciliation_history(db: sqlite3.Connection, ngay: str) -> list:
    """Lịch sử từng lần lưu đối chiếu CITAD của 1 ngày cụ thể, theo đúng thứ
    tự thời gian đã lưu (cũ -> mới) — mỗi dòng gắn với username người đã
    chấm, để biết ngày nào nhiều người cùng làm thì ai sửa lúc nào. KHÔNG
    trả kèm số liệu (có thể nặng nếu nhiều dòng) — xem từng bản cụ thể qua
    get_history_entry_data(id)."""
    rows = db.execute(
        """SELECT h.id, h.staff_id, u.username, h.created_at
           FROM doi_chieu_citad_history h
           JOIN user_tttt u ON u.id = h.staff_id
           WHERE h.ngay = ?
           ORDER BY h.created_at ASC, h.id ASC""",
        (ngay,),
    ).fetchall()
    return [
        {
            "id": r["id"], "staff_id": r["staff_id"], "username": r["username"],
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def get_history_entry_data(db: sqlite3.Connection, history_id: int) -> dict | None:
    """Số liệu NGUYÊN VẸN của đúng 1 lần lưu trong lịch sử — phục vụ nút
    "Tải" trên từng dòng lịch sử, xem lại/khôi phục đúng bản của lần lưu
    đó (khác nút "Tải" chính, luôn lấy bản HIỆN HÀNH mới nhất)."""
    row = db.execute(
        "SELECT data FROM doi_chieu_citad_history WHERE id=?", (history_id,)
    ).fetchone()
    return json.loads(row["data"]) if row else None


def session_delete(db: sqlite3.Connection, ngay: str) -> None:
    db.execute("DELETE FROM doi_chieu_citad_sessions WHERE ngay=?", (ngay,))
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
    # openpyxl raise lỗi (500 không kiểm soát) nếu tên sheet chứa ký tự Excel
    # cấm (: \ / ? * [ ]) — lọc trước khi gán, không đổi nội dung số liệu.
    safe_sheet_name = re.sub(r'[:\\/?*\[\]]', '_', data.sheet_name) or 'Sheet1'
    ws.title = safe_sheet_name[:31]
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


# ── Tải Extension Chrome dạng .zip (phục vụ nút "Tải Extension") ──────────
def build_extension_zip() -> bytes:
    """Nén `extension_citad/` thành .zip trong bộ nhớ — không lưu file tạm,
    không cần bước build riêng, luôn khớp đúng code hiện tại trên server.

    File nằm NGAY GỐC zip (không bọc thêm 1 lớp thư mục "extension_citad/"
    bên trong) — nếu bọc thêm, công cụ giải nén của Windows ("Extract All")
    sẽ tạo 1 thư mục ngoài cùng trùng tên file zip (cũng "extension_citad"),
    cộng với lớp bên trong zip → lồng 2 lần
    (extension_citad/extension_citad/manifest.json), khiến Chrome báo lỗi
    "Manifest file is missing or unreadable" vì manifest.json không nằm
    ngay trong thư mục người dùng chọn ở "Load unpacked"."""
    if not EXTENSION_DIR.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục {EXTENSION_DIR}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(EXTENSION_DIR))
    return buf.getvalue()
