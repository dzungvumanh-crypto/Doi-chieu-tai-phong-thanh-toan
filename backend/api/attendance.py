"""Chấm công — Phòng Kế toán (ACCT). Raw SQL thuần, không ORM."""
import calendar
import io
import sqlite3
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.core.deps import get_current_staff, require_admin
from backend.database import get_db, _vn_now
from backend.schemas.attendance import (
    AttendanceSymbolCreate, AttendanceSymbolUpdate, AttendanceSymbolOut,
    AttendanceDayUpdate, AdjustmentCreate, AdjustmentReview,
)

router = APIRouter()

_MANAGER_ROLES = ("truong_phong", "pho_phong")


def _require_acct_scope(current: dict, db: sqlite3.Connection) -> None:
    """Admin luôn qua. Vai trò khác phải thuộc phòng code='ACCT'."""
    if current["role"] == "admin":
        return
    row = db.execute(
        "SELECT code FROM departments WHERE id=?", (current.get("department_id"),)
    ).fetchone()
    if not row or row["code"].upper() != "ACCT":
        raise HTTPException(403, "Tính năng này chỉ dành cho Phòng Kế toán")


def _is_manager(current: dict) -> bool:
    return current["role"] == "admin" or current["role"] in _MANAGER_ROLES


def _has_group_feature(db: sqlite3.Connection, staff_id: int, code: str) -> bool:
    """Check quyền theo nhóm (group_features) — dùng để CỘNG THÊM cho GDV được
    admin cấp quyền riêng, không thay thế check role trưởng/phó phòng/admin."""
    row = db.execute(
        """SELECT 1 FROM group_features gf
           JOIN group_members gm ON gm.group_id = gf.group_id
           JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
           WHERE gm.staff_id = ? AND gf.feature_code = ? LIMIT 1""",
        (staff_id, code),
    ).fetchone()
    return bool(row)


def _can_view_dept(current: dict, db: sqlite3.Connection) -> bool:
    """Trưởng/phó phòng/admin luôn xem được cả phòng; GDV thường chỉ xem được
    nếu admin đã gán quyền attendance.view_dept qua màn Phân quyền theo nhóm."""
    return _is_manager(current) or _has_group_feature(db, current["id"], "attendance.view_dept")


def _can_export(current: dict, db: sqlite3.Connection) -> bool:
    """Tương tự _can_view_dept nhưng cho quyền xuất Excel (attendance.export)."""
    return _is_manager(current) or _has_group_feature(db, current["id"], "attendance.export")


def _load_holidays(db: sqlite3.Connection, start: date, end: date):
    rows = db.execute(
        "SELECT date FROM public_holidays WHERE date >= ? AND date <= ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return frozenset(date.fromisoformat(r["date"]) for r in rows)


def _acct_staff_rows(db: sqlite3.Connection):
    return db.execute(
        """SELECT u.id, u.full_name, u.employee_code FROM user_tttt u
           JOIN departments d ON d.id = u.department_id
           WHERE d.code = 'ACCT' AND u.is_active = 1 AND (u.is_deleted = 0 OR u.is_deleted IS NULL)
           ORDER BY u.full_name"""
    ).fetchall()


def _adjustment_to_out(db: sqlite3.Connection, adj_id: int) -> dict:
    row = db.execute(
        """SELECT a.*, u.full_name AS staff_name, r.full_name AS reviewer_name,
                  att.staff_id AS att_staff_id, att.date AS att_date
           FROM attendance_adjustments a
           JOIN attendances att ON att.id = a.attendance_id
           JOIN user_tttt u ON u.id = att.staff_id
           LEFT JOIN user_tttt r ON r.id = a.reviewer_id
           WHERE a.id = ?""",
        (adj_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy yêu cầu điều chỉnh")
    d = dict(row)
    d["staff_id"] = d.pop("att_staff_id")
    d["date"] = d.pop("att_date")
    return d


# ─── Bảng công theo tháng / theo ngày ─────────────────────────────────────────
@router.get("/month")
def get_month(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    scope: str = Query("mine"),
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    # BUG đã sửa (phát hiện khi test thật): trước đây ép scope="mine" cho MỌI
    # chuyên viên vô điều kiện — kể cả GDV đã được admin cấp attendance.view_dept,
    # khiến quyền vừa gán hoàn toàn vô tác dụng ở endpoint này. Giờ chỉ ép về
    # "mine" khi thực sự KHÔNG có quyền xem cả phòng (role manager/admin HOẶC có
    # feature — _can_view_dept đã gộp cả 2 điều kiện).
    if current["role"] == "chuyen_vien" and not _can_view_dept(current, db):
        scope = "mine"
    elif scope not in ("mine", "dept"):
        scope = "mine"
    if scope == "dept" and not _can_view_dept(current, db):
        raise HTTPException(403, "Không có quyền xem bảng công cả phòng")

    days_in_month = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)
    holiday_dates = _load_holidays(db, start, end)

    if scope == "dept":
        staff_rows = _acct_staff_rows(db)
    else:
        staff_rows = db.execute(
            "SELECT id, full_name, employee_code FROM user_tttt WHERE id = ?", (current["id"],)
        ).fetchall()

    staff_ids = [r["id"] for r in staff_rows]
    att_map = {}
    if staff_ids:
        placeholders = ",".join("?" for _ in staff_ids)
        att_rows = db.execute(
            f"""SELECT id, staff_id, date, symbol, work_value, status, note
                FROM attendances WHERE staff_id IN ({placeholders}) AND date >= ? AND date <= ?""",
            (*staff_ids, start.isoformat(), end.isoformat()),
        ).fetchall()
        for r in att_rows:
            att_map[(r["staff_id"], r["date"])] = r

    result_staff = []
    for srow in staff_rows:
        sid = srow["id"]
        days = {}
        total = 0.0
        for day_num in range(1, days_in_month + 1):
            d = date(year, month, day_num)
            arow = att_map.get((sid, d.isoformat()))
            if arow:
                days[d.isoformat()] = {
                    "attendance_id": arow["id"], "staff_id": sid, "date": d.isoformat(),
                    "symbol": arow["symbol"], "work_value": arow["work_value"],
                    "status": arow["status"], "note": arow["note"], "is_virtual": False,
                }
                total += arow["work_value"] or 0
            elif d.weekday() < 5:
                days[d.isoformat()] = {
                    "attendance_id": None, "staff_id": sid, "date": d.isoformat(),
                    "symbol": "x", "work_value": 1.0,
                    "status": None, "note": None, "is_virtual": True,
                }
                total += 1.0
            else:
                days[d.isoformat()] = {
                    "attendance_id": None, "staff_id": sid, "date": d.isoformat(),
                    "symbol": None, "work_value": 0.0,
                    "status": None, "note": None, "is_virtual": True,
                }
        result_staff.append({
            "staff_id": sid, "full_name": srow["full_name"], "employee_code": srow["employee_code"],
            "days": days, "total_work_value": total,
        })

    return {
        "year": year, "month": month, "days_in_month": days_in_month,
        "holidays": [d.isoformat() for d in sorted(holiday_dates)],
        "staff": result_staff,
    }


@router.get("/day")
def get_day(
    staff_id: int = Query(...),
    date_: str = Query(..., alias="date"),
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    # Đồng nhất với /month: chuyên viên được cấp attendance.view_dept cũng xem
    # được công của người khác qua endpoint tra 1 ngày này, không chỉ của mình.
    if current["role"] == "chuyen_vien" and staff_id != current["id"] and not _can_view_dept(current, db):
        raise HTTPException(403, "Chỉ được xem công của chính mình")
    row = db.execute(
        "SELECT * FROM attendances WHERE staff_id=? AND date=?", (staff_id, date_)
    ).fetchone()
    if row:
        return dict(row)
    d = date.fromisoformat(date_)
    if d.weekday() < 5:
        return {"staff_id": staff_id, "date": date_, "symbol": "x", "work_value": 1.0,
                "status": None, "note": None, "is_virtual": True}
    return {"staff_id": staff_id, "date": date_, "symbol": None, "work_value": 0.0,
            "status": None, "note": None, "is_virtual": True}


@router.put("/day")
def put_day(
    body: AttendanceDayUpdate,
    staff_id: int = Query(...),
    date_: str = Query(..., alias="date"),
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    if not _is_manager(current):
        raise HTTPException(403, "Chỉ Trưởng/Phó phòng hoặc Admin được sửa công trực tiếp")
    sym = db.execute(
        "SELECT work_value FROM attendance_symbols WHERE symbol=? AND is_active=1", (body.symbol,)
    ).fetchone()
    if not sym:
        raise HTTPException(400, f"Ký hiệu '{body.symbol}' không hợp lệ")
    staff = db.execute("SELECT id FROM user_tttt WHERE id=?", (staff_id,)).fetchone()
    if not staff:
        raise HTTPException(404, "Không tìm thấy nhân viên")
    now = str(_vn_now())
    db.execute(
        """INSERT INTO attendances
               (staff_id, date, symbol, work_value, status, note, confirmed_by, confirmed_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?)
           ON CONFLICT(staff_id, date) DO UPDATE SET
               symbol=excluded.symbol, work_value=excluded.work_value, status='confirmed',
               note=excluded.note, confirmed_by=excluded.confirmed_by, confirmed_at=excluded.confirmed_at,
               updated_at=excluded.updated_at""",
        (staff_id, date_, body.symbol, sym["work_value"], body.note, current["id"], now, now, now),
    )
    db.commit()
    row = db.execute("SELECT * FROM attendances WHERE staff_id=? AND date=?", (staff_id, date_)).fetchone()
    return dict(row)


# ─── Danh sách trưởng/phó phòng ACCT (cho dropdown "Người kiểm soát" khi xuất) ─
@router.get("/managers")
def list_managers(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    rows = db.execute(
        """SELECT u.id, u.full_name FROM user_tttt u
           JOIN departments d ON d.id = u.department_id
           WHERE d.code = 'ACCT' AND u.role IN ('truong_phong','pho_phong')
             AND u.is_active = 1 AND (u.is_deleted = 0 OR u.is_deleted IS NULL)
           ORDER BY u.full_name"""
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Điều chỉnh công ──────────────────────────────────────────────────────────
@router.post("/adjustments")
def create_adjustment(
    body: AdjustmentCreate,
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    staff_id = body.staff_id or current["id"]
    if current["role"] == "chuyen_vien" and staff_id != current["id"]:
        raise HTTPException(403, "Chỉ được xin điều chỉnh công của chính mình")
    sym = db.execute(
        "SELECT work_value FROM attendance_symbols WHERE symbol=? AND is_active=1", (body.new_symbol,)
    ).fetchone()
    if not sym:
        raise HTTPException(400, f"Ký hiệu '{body.new_symbol}' không hợp lệ")

    date_str = body.date.isoformat()
    now = str(_vn_now())
    row = db.execute("SELECT * FROM attendances WHERE staff_id=? AND date=?", (staff_id, date_str)).fetchone()
    if row:
        attendance_id = row["id"]
        old_symbol, old_work_value = row["symbol"], row["work_value"]
    else:
        if body.date.weekday() >= 5:
            raise HTTPException(400, "Không thể xin điều chỉnh cho ngày nghỉ cuối tuần chưa có dữ liệu")
        init_symbol, init_value = "x", 1.0
        cur = db.execute(
            """INSERT INTO attendances (staff_id, date, symbol, work_value, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'auto', ?, ?)""",
            (staff_id, date_str, init_symbol, init_value, now, now),
        )
        attendance_id = cur.lastrowid
        old_symbol, old_work_value = init_symbol, init_value

    # Chặn lặp yêu cầu: bấm nhanh 2 lần hoặc client tự retry khi mạng chậm đều có
    # thể tạo 2 dòng attendance_adjustments giống hệt nhau cho cùng 1 ngày (đã gặp
    # thực tế — 2 dòng cùng attendance_id, cách nhau 2 giây). Chặn ở đây thay vì chỉ
    # debounce phía frontend vì debounce không chặn được trường hợp do mạng.
    existing_pending = db.execute(
        "SELECT id FROM attendance_adjustments WHERE attendance_id=? AND status='pending'",
        (attendance_id,),
    ).fetchone()
    if existing_pending:
        raise HTTPException(409, "Đã có yêu cầu điều chỉnh đang chờ duyệt cho ngày này — vui lòng đợi xử lý xong trước khi gửi lại")

    db.execute(
        """INSERT INTO attendance_adjustments
               (attendance_id, requested_by, old_symbol, new_symbol, old_work_value, new_work_value, reason, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (attendance_id, current["id"], old_symbol, body.new_symbol, old_work_value, sym["work_value"], body.reason, now),
    )
    db.commit()
    new_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return _adjustment_to_out(db, new_id)


@router.put("/adjustments/{adj_id}/review")
def review_adjustment(
    adj_id: int,
    body: AdjustmentReview,
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    if not _is_manager(current):
        raise HTTPException(403, "Chỉ Trưởng/Phó phòng hoặc Admin được duyệt điều chỉnh công")
    row = db.execute("SELECT * FROM attendance_adjustments WHERE id=?", (adj_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy yêu cầu điều chỉnh")
    if row["status"] != "pending":
        raise HTTPException(400, "Yêu cầu này đã được xử lý")

    now = str(_vn_now())
    if body.action == "approve":
        db.execute(
            "UPDATE attendances SET symbol=?, work_value=?, status='adjusted', updated_at=? WHERE id=?",
            (row["new_symbol"], row["new_work_value"], now, row["attendance_id"]),
        )
        db.execute(
            "UPDATE attendance_adjustments SET status='approved', reviewer_id=?, reviewed_at=? WHERE id=?",
            (current["id"], now, adj_id),
        )
    else:
        if not body.reject_reason or not body.reject_reason.strip():
            raise HTTPException(400, "Cần nhập lý do từ chối")
        db.execute(
            "UPDATE attendance_adjustments SET status='rejected', reviewer_id=?, reviewed_at=?, reject_reason=? WHERE id=?",
            (current["id"], now, body.reject_reason, adj_id),
        )
    db.commit()
    return _adjustment_to_out(db, adj_id)


@router.get("/adjustments")
def list_adjustments(
    scope: str = Query("mine"),
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    clauses, params = [], []
    if current["role"] == "chuyen_vien":
        clauses.append("a.requested_by = ?")
        params.append(current["id"])
    elif scope == "pending":
        clauses.append("a.status = 'pending'")
    elif scope == "mine":
        clauses.append("a.requested_by = ?")
        params.append(current["id"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = db.execute(
        f"""SELECT a.id FROM attendance_adjustments a
            JOIN attendances att ON att.id = a.attendance_id
            {where}
            ORDER BY a.created_at DESC""",
        params,
    ).fetchall()
    return [_adjustment_to_out(db, r["id"]) for r in rows]


# ─── Xuất Excel bảng công tháng ───────────────────────────────────────────────
@router.get("/export")
def export_month(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    kiem_soat_id: int = Query(..., description="staff_id trưởng/phó phòng ACCT ký tên Kiểm soát"),
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    _require_acct_scope(current, db)
    # Cộng thêm quyền theo nhóm (attendance.export) — GDV được admin cấp quyền
    # riêng cũng xuất được, không chỉ trưởng/phó phòng/admin.
    if not _can_export(current, db):
        raise HTTPException(403, "Không có quyền xuất bảng công")

    # "Kiểm soát" bắt buộc là trưởng/phó phòng đang active của đúng phòng ACCT —
    # validate lại ở backend (không tin dữ liệu từ dropdown frontend).
    kiem_soat = db.execute(
        """SELECT full_name FROM user_tttt
           WHERE id = ? AND role IN ('truong_phong','pho_phong') AND is_active = 1
             AND department_id = (SELECT id FROM departments WHERE code='ACCT')""",
        (kiem_soat_id,),
    ).fetchone()
    if not kiem_soat:
        raise HTTPException(400, "Người kiểm soát không hợp lệ (phải là trưởng/phó phòng Kế toán đang hoạt động)")

    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins

    days_in_month = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)
    holiday_dates = _load_holidays(db, start, end)

    staff_rows = _acct_staff_rows(db)
    staff_ids = [r["id"] for r in staff_rows]
    att_map = {}
    if staff_ids:
        placeholders = ",".join("?" for _ in staff_ids)
        att_rows = db.execute(
            f"""SELECT staff_id, date, symbol, work_value FROM attendances
                WHERE staff_id IN ({placeholders}) AND date >= ? AND date <= ?""",
            (*staff_ids, start.isoformat(), end.isoformat()),
        ).fetchall()
        for r in att_rows:
            att_map[(r["staff_id"], r["date"])] = r

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Bang cong {month:02d}-{year}"

    hdr_fill = PatternFill("solid", fgColor="C62828")
    hdr_font = Font(bold=True, color="FFFFFF")
    # Hoạ tiết gạch chéo (hatch) cho cột T7/CN — khớp đúng mẫu Excel thật của
    # Phòng Kế toán (ảnh tham khảo), thay vì tô màu phẳng như bản trước.
    weekend_fill = PatternFill(fill_type="lightUp", fgColor="FFFFFF", bgColor="FFF9C4")
    holiday_fill = PatternFill("solid", fgColor="C8E6C9")
    leave_fill = PatternFill("solid", fgColor="FFCDD2")
    thin = Side(style="thin", color="000000")
    cell_border = Border(left=thin, right=thin, top=thin, bottom=thin)

    total_cols = 2 + days_in_month + 1  # STT + Họ tên + ngày + Tổng công
    last_col_letter = get_column_letter(total_cols)
    left_end = total_cols // 2       # chia đôi bề ngang cho khối tiêu đề trái/phải
    right_start = left_end + 1

    # ── Khối tiêu đề/quốc hiệu (để in trực tiếp trên A4) — khớp mẫu ảnh thật của
    # Phòng Kế toán: dòng 1 để trống, dòng 2-3 tên ngân hàng (trái) / quốc hiệu
    # (phải, căn giữa), dòng 5 tên phòng, dòng 7-8 tiêu đề "BẢNG CHẤM CÔNG" +
    # tháng/năm (căn giữa, merge hết bề ngang). Bảng dữ liệu bắt đầu từ dòng 10.
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=left_end)
    ws.cell(row=2, column=1, value="NGÂN HÀNG NÔNG NGHIỆP").font = Font(bold=True)
    ws.merge_cells(start_row=2, start_column=right_start, end_row=2, end_column=total_cols)
    c = ws.cell(row=2, column=right_start, value="CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM")
    c.font = Font(bold=True)
    c.alignment = Alignment(horizontal="center")

    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=left_end)
    ws.cell(row=3, column=1, value="VÀ PHÁT TRIỂN NÔNG THÔN VIỆT NAM").font = Font(bold=True)
    ws.merge_cells(start_row=3, start_column=right_start, end_row=3, end_column=total_cols)
    c = ws.cell(row=3, column=right_start, value="Độc lập - Tự do - Hạnh phúc")
    c.font = Font(bold=True)
    c.alignment = Alignment(horizontal="center")

    ws.merge_cells(start_row=5, start_column=1, end_row=5, end_column=left_end)
    ws.cell(row=5, column=1, value="Phòng Kế toán - TTTT").font = Font(bold=True)

    ws.merge_cells(start_row=7, start_column=1, end_row=7, end_column=total_cols)
    c = ws.cell(row=7, column=1, value="BẢNG CHẤM CÔNG")
    c.font = Font(bold=True, size=14)
    c.alignment = Alignment(horizontal="center")

    ws.merge_cells(start_row=8, start_column=1, end_row=8, end_column=total_cols)
    c = ws.cell(row=8, column=1, value=f"Tháng {month} năm {year}")
    c.alignment = Alignment(horizontal="center")

    header_row = 10
    headers = ["STT", "Họ và tên"] + [str(d) for d in range(1, days_in_month + 1)] + ["Tổng công"]
    for col_idx, val in enumerate(headers, start=1):
        ws.cell(row=header_row, column=col_idx, value=val)
    for col_idx, cell in enumerate(ws[header_row], start=1):
        cell.alignment = Alignment(horizontal="center")
        cell.border = cell_border
        if 3 <= col_idx <= 2 + days_in_month:
            d = date(year, month, col_idx - 2)
            if d.weekday() >= 5:
                cell.fill, cell.font = weekend_fill, Font(bold=True)
                continue
            if d in holiday_dates:
                cell.fill, cell.font = holiday_fill, Font(bold=True)
                continue
        cell.fill, cell.font = hdr_fill, hdr_font
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 25
    for col_idx in range(3, 3 + days_in_month):
        ws.column_dimensions[get_column_letter(col_idx)].width = 4
    ws.column_dimensions[get_column_letter(3 + days_in_month)].width = 10

    for idx, srow in enumerate(staff_rows, 1):
        sid = srow["id"]
        row_vals = [idx, srow["full_name"]]
        total = 0.0
        for day_num in range(1, days_in_month + 1):
            d = date(year, month, day_num)
            arow = att_map.get((sid, d.isoformat()))
            if arow:
                symbol, value = arow["symbol"], (arow["work_value"] or 0)
            elif d.weekday() < 5:
                symbol, value = "x", 1.0
            else:
                symbol, value = "", 0.0
            row_vals.append(symbol)
            total += value
        row_vals.append(total)
        ws.append(row_vals)
        r = ws.max_row
        # Viền kẻ ô cho toàn bộ dòng (STT + Họ tên + từng ngày + Tổng công) —
        # để giống bảng giấy thật, in ra rõ ràng từng ô thay vì chỉ có màu nền.
        for col_idx in range(1, total_cols + 1):
            ws.cell(row=r, column=col_idx).border = cell_border
        for day_num in range(1, days_in_month + 1):
            d = date(year, month, day_num)
            cell = ws.cell(row=r, column=2 + day_num)
            cell.alignment = Alignment(horizontal="center")
            if cell.value == "P":
                cell.fill = leave_fill
            elif d in holiday_dates:
                cell.fill = holiday_fill
            elif d.weekday() >= 5:
                cell.fill = weekend_fill

    # 2 dòng ký tên: "Lập bảng" tự động = người đang thực hiện xuất (dù là GDV
    # được cấp quyền hay trưởng/phó phòng), "Kiểm soát" = tên đã chọn ở dropdown
    # frontend, đã validate lại phía trên. Tên ghi ngay dưới nhãn — khớp mẫu ảnh.
    last_row = ws.max_row
    sign_col_2 = max(3, 1 + days_in_month)
    ws.cell(row=last_row + 2, column=2, value="Người lập bảng").font = Font(bold=True)
    ws.cell(row=last_row + 3, column=2, value=current["full_name"])
    ws.cell(row=last_row + 2, column=sign_col_2, value="Người kiểm soát").font = Font(bold=True)
    ws.cell(row=last_row + 3, column=sign_col_2, value=kiem_soat["full_name"])

    # ── Cấu hình khổ giấy A4 ngang để in trực tiếp — bảng có tới 34 cột (STT +
    # Họ tên + tối đa 31 ngày + Tổng công) nên bắt buộc landscape mới vừa. fitToWidth=1
    # ép co vừa 1 trang theo bề ngang khi in; fitToHeight=0 cho phép nhiều trang dọc
    # nếu phòng đông người — mỗi trang tự lặp lại phần tiêu đề + header cột.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_margins = PageMargins(left=0.3, right=0.3, top=0.4, bottom=0.4, header=0.2, footer=0.2)
    ws.print_area = f"A1:{last_col_letter}{ws.max_row}"
    ws.print_title_rows = f"1:{header_row}"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''bang_cong_{year}_{month:02d}.xlsx"},
    )


# ─── Cấu hình ký hiệu công (admin) ────────────────────────────────────────────
@router.get("/symbols", response_model=List[AttendanceSymbolOut])
def list_symbols(
    _: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    rows = db.execute("SELECT * FROM attendance_symbols ORDER BY symbol").fetchall()
    return [dict(r) for r in rows]


@router.post("/symbols", response_model=AttendanceSymbolOut)
def create_symbol(
    body: AttendanceSymbolCreate,
    _: dict = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    existing = db.execute("SELECT symbol FROM attendance_symbols WHERE symbol=?", (body.symbol,)).fetchone()
    if existing:
        raise HTTPException(400, f"Ký hiệu '{body.symbol}' đã tồn tại")
    db.execute(
        "INSERT INTO attendance_symbols (symbol, description, work_value, color, is_active) VALUES (?,?,?,?,?)",
        (body.symbol, body.description, body.work_value, body.color, body.is_active),
    )
    db.commit()
    row = db.execute("SELECT * FROM attendance_symbols WHERE symbol=?", (body.symbol,)).fetchone()
    return dict(row)


@router.put("/symbols/{symbol}", response_model=AttendanceSymbolOut)
def update_symbol(
    symbol: str,
    body: AttendanceSymbolUpdate,
    _: dict = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT * FROM attendance_symbols WHERE symbol=?", (symbol,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy ký hiệu")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return dict(row)
    set_clause = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE attendance_symbols SET {set_clause} WHERE symbol=?", (*updates.values(), symbol))
    db.commit()
    row = db.execute("SELECT * FROM attendance_symbols WHERE symbol=?", (symbol,)).fetchone()
    return dict(row)
