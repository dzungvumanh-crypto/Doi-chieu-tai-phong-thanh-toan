"""Quản lý nghỉ phép — đăng ký, phê duyệt, tải phiếu"""
import io
import os
import sqlite3
from datetime import date, timedelta
from typing import FrozenSet, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.core.deps import (
    TONG_HOP_CODES, get_current_staff, require_gd_level, require_ksv,
)
from backend.core.enums import LeaveStatus
from backend.database import get_db, _vn_now
from backend.schemas.leaves import LeaveCreate, LeaveReview, TongHopReview

router = APIRouter()

LEAVE_TYPE_LABELS = {
    "annual":   "Nghỉ phép năm",
    "sick":     "Nghỉ ốm",
    "personal": "Nghỉ việc riêng",
    "bat_buoc": "Nghỉ phép bắt buộc",
    "dot_xuat": "Nghỉ đột xuất",
    "other":    "Khác",
}

_VALID_LEAVE_TYPES = frozenset(LEAVE_TYPE_LABELS.keys())

ACTION_LABELS = {
    "create":       ("Nộp đơn",            "blue"),
    "ksv_approve":  ("KSV phê duyệt",      "green"),
    "ksv_reject":   ("KSV từ chối",        "red"),
    "th_forward":   ("TH chuyển GĐ",       "blue"),
    "th_reject":    ("TH từ chối",         "red"),
    "gd_approve":   ("GĐ phê duyệt",       "green"),
    "gd_reject":    ("GĐ từ chối",         "red"),
    "resubmit":     ("Nộp lại",            "orange"),
    "cancel":       ("Hủy đơn",            "grey"),
}

_LEAVE_STATUS_VN = {
    LeaveStatus.PENDING_KSV:      "Chờ KSV duyệt",
    LeaveStatus.PENDING_TONG_HOP: "Chờ Tổng hợp",
    LeaveStatus.PENDING_GD:       "Chờ GĐ duyệt",
    LeaveStatus.APPROVED:         "Đã phê duyệt",
    LeaveStatus.REJECTED:         "Bị từ chối",
    LeaveStatus.CANCELLED:        "Đã hủy",
}

# Các role cấp cao — bỏ qua bước KSV, vào thẳng pending_tong_hop
_HIGH_ROLES = frozenset(("giam_doc", "pho_giam_doc", "admin"))


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_holidays(db: sqlite3.Connection, start: date, end: date) -> FrozenSet[date]:
    rows = db.execute(
        "SELECT date FROM public_holidays WHERE date >= ? AND date <= ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    return frozenset(date.fromisoformat(r["date"]) for r in rows)


def calculate_leave_days(
    start: date, end: date,
    holiday_dates: FrozenSet[date] = frozenset(),
) -> int:
    """Đếm ngày làm việc thực (trừ T7, CN và ngày lễ). Tối thiểu 1 ngày."""
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holiday_dates:
            count += 1
        d += timedelta(days=1)
    return max(count, 1)


def _is_tong_hop_staff(staff: dict, db: sqlite3.Connection) -> bool:
    dept_id = staff.get("department_id")
    if not dept_id:
        return False
    r = db.execute("SELECT code FROM departments WHERE id = ?", (dept_id,)).fetchone()
    return bool(r and r["code"].upper() in TONG_HOP_CODES)


def _can_gd_review(current: dict, db: sqlite3.Connection) -> bool:
    if current["role"] == "giam_doc":
        return True
    if current["role"] == "pho_giam_doc":
        today = _vn_now().date().isoformat()
        return db.execute(
            "SELECT id FROM delegation_records WHERE pho_giam_doc_id = ? AND is_active = 1 AND start_date <= ? AND end_date >= ?",
            (current["id"], today, today),
        ).fetchone() is not None
    return False


def _apply_status_transition(
    leave_id: int, old_status: str, new_status: str,
    start: date, end: date, staff_id: int,
    holiday_dates: FrozenSet[date],
    db: sqlite3.Connection,
):
    """Cập nhật status và điều chỉnh used_leave_days (idempotent)."""
    days = calculate_leave_days(start, end, holiday_dates)
    if old_status != LeaveStatus.APPROVED and new_status == LeaveStatus.APPROVED:
        db.execute(
            "UPDATE user_tttt SET used_leave_days = COALESCE(used_leave_days, 0) + ? WHERE id = ?",
            (days, staff_id),
        )
    elif old_status == LeaveStatus.APPROVED and new_status in (LeaveStatus.CANCELLED, LeaveStatus.REJECTED):
        db.execute(
            "UPDATE user_tttt SET used_leave_days = MAX(0, COALESCE(used_leave_days, 0) - ?) WHERE id = ?",
            (days, staff_id),
        )
    db.execute(
        "UPDATE leave_records SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, str(_vn_now()), leave_id),
    )


def _log_action(
    db: sqlite3.Connection, leave_id: int, actor_id: int, action: str,
    comment: Optional[str], from_status: str, to_status: str,
):
    db.execute(
        "INSERT INTO leave_action_logs (leave_id, actor_id, action, comment, from_status, to_status, created_at) VALUES (?,?,?,?,?,?,?)",
        (leave_id, actor_id, action, comment, from_status, to_status, str(_vn_now())),
    )


def _validate_ksv(ksv_id: Optional[int], current: dict, db: sqlite3.Connection) -> dict:
    if not ksv_id:
        raise HTTPException(400, "Vui lòng chọn người phê duyệt bước KSV")
    ksv = db.execute("SELECT * FROM user_tttt WHERE id = ? AND is_active = 1", (ksv_id,)).fetchone()
    if not ksv:
        raise HTTPException(400, "Người phê duyệt không tồn tại hoặc đã bị vô hiệu")
    if ksv["role"] not in ("truong_phong", "pho_phong", "hau_kiem_vien", "admin"):
        raise HTTPException(400, "Người phê duyệt phải là Trưởng phòng, Phó phòng hoặc Hậu kiểm viên")
    if ksv_id == current["id"]:
        raise HTTPException(400, "Không thể tự phê duyệt")
    return dict(ksv)


def _leave_to_out(leave_id: int, db: sqlite3.Connection) -> dict:
    r = db.execute(
        """SELECT lr.*,
                  s.full_name AS staff_name, s.department_id AS s_dept_id,
                  kv.full_name AS ksv_name,
                  th.full_name AS th_name,
                  gd.full_name AS gd_approver_name, gd.role AS gd_role,
                  d.name AS dept_name
           FROM leave_records lr
           LEFT JOIN user_tttt s  ON lr.staff_id             = s.id
           LEFT JOIN user_tttt kv ON lr.ksv_approver_id      = kv.id
           LEFT JOIN user_tttt th ON lr.tong_hop_approver_id = th.id
           LEFT JOIN user_tttt gd ON lr.gd_approver_id       = gd.id
           LEFT JOIN departments d ON s.department_id          = d.id
           WHERE lr.id = ?""",
        (leave_id,),
    ).fetchone()
    if not r:
        return {}

    start = date.fromisoformat(r["start_date"])
    end   = date.fromisoformat(r["end_date"])
    _h    = _load_holidays(db, start, end)

    return {
        "id":                     r["id"],
        "staff_id":               r["staff_id"],
        "staff_name":             r["staff_name"] or "",
        "department_name":        r["dept_name"],
        "start_date":             r["start_date"],
        "end_date":               r["end_date"],
        "leave_days":             calculate_leave_days(start, end, _h),
        "leave_type":             r["leave_type"],
        "reason":                 r["reason"],
        "status":                 r["status"],
        "ksv_approver_id":        r["ksv_approver_id"],
        "ksv_approver_name":      r["ksv_name"],
        "ksv_approved_at":        r["ksv_approved_at"],
        "ksv_comment":            r["ksv_comment"],
        "tong_hop_approver_id":   r["tong_hop_approver_id"],
        "tong_hop_approver_name": r["th_name"],
        "tong_hop_approved_at":   r["tong_hop_approved_at"],
        "tong_hop_comment":       r["tong_hop_comment"],
        "gd_approver_id":         r["gd_approver_id"],
        "gd_approver_name":       r["gd_approver_name"],
        "gd_is_pgd":              (r["gd_role"] == "pho_giam_doc") if r["gd_role"] else False,
        "gd_approved_at":         r["gd_approved_at"],
        "gd_comment":             r["gd_comment"],
        "created_at":             r["created_at"],
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/approvers")
def get_approvers(
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    _ROLE_LABEL = {
        "truong_phong":  "Trưởng phòng",
        "pho_phong":     "Phó phòng",
        "hau_kiem_vien": "Hậu kiểm viên",
        "admin":         "Quản trị viên",
    }
    rows = db.execute(
        """SELECT id, full_name, role FROM user_tttt
           WHERE is_active = 1 AND role IN ('truong_phong','pho_phong','hau_kiem_vien','admin')
             AND id != ? ORDER BY full_name""",
        (current["id"],),
    ).fetchall()
    return [{"id": r["id"], "full_name": r["full_name"], "role_label": _ROLE_LABEL.get(r["role"], r["role"])} for r in rows]


@router.get("/gd-list")
def get_gd_list(
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if not (_is_tong_hop_staff(current, db) or current["role"] == "admin"):
        raise HTTPException(403, "Chỉ nhân viên Phòng Tổng hợp hoặc Admin mới được xem")
    rows = db.execute(
        "SELECT id, full_name, role FROM user_tttt WHERE is_active = 1 AND role IN ('giam_doc','pho_giam_doc')"
    ).fetchall()
    _ROLE_LABEL = {"giam_doc": "Giám đốc", "pho_giam_doc": "Phó Giám đốc"}
    return [{"id": r["id"], "full_name": r["full_name"], "role_label": _ROLE_LABEL.get(r["role"], r["role"])} for r in rows]


@router.post("/")
def create_leave(
    body: LeaveCreate,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if body.end_date < body.start_date:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")

    if body.leave_type not in _VALID_LEAVE_TYPES:
        raise HTTPException(400, f"Loại nghỉ phép không hợp lệ: {body.leave_type}")

    _h = _load_holidays(db, body.start_date, body.end_date)
    leave_days = calculate_leave_days(body.start_date, body.end_date, _h)

    if body.leave_type == "annual":
        if body.start_date < _vn_now().date():
            raise HTTPException(400, "Nghỉ phép năm phải từ hôm nay trở đi")
        remaining = (current.get("annual_leave_days") or 12) - (current.get("used_leave_days") or 0)
        if leave_days > remaining:
            raise HTTPException(400, f"Vượt quá số ngày phép còn lại ({remaining} ngày)")

    if body.leave_type == "bat_buoc" and leave_days < 5:
        raise HTTPException(400, "Nghỉ phép bắt buộc phải từ 5 ngày làm việc trở lên")

    overlap = db.execute(
        """SELECT id FROM leave_records
           WHERE staff_id = ? AND status NOT IN ('rejected','cancelled')
             AND start_date <= ? AND end_date >= ?""",
        (current["id"], body.end_date.isoformat(), body.start_date.isoformat()),
    ).fetchone()
    if overlap:
        raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")

    if current["role"] in _HIGH_ROLES:
        initial_status  = LeaveStatus.PENDING_TONG_HOP
        ksv_approver_id = None
    else:
        ksv = _validate_ksv(body.ksv_approver_id, current, db)
        initial_status  = LeaveStatus.PENDING_KSV
        ksv_approver_id = ksv["id"]

    cur = db.execute(
        "INSERT INTO leave_records (staff_id, start_date, end_date, leave_type, reason, status, ksv_approver_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (current["id"], body.start_date.isoformat(), body.end_date.isoformat(),
         body.leave_type, body.reason, initial_status, ksv_approver_id,
         str(_vn_now()), str(_vn_now())),
    )
    leave_id = cur.lastrowid
    _log_action(db, leave_id, current["id"], "create", None, "", initial_status)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.get("/")
def list_leaves(
    scope: str = "mine",
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    role = current["role"]
    clauses: list = []
    params: list  = []

    if scope == "mine":
        clauses.append("staff_id = ?")
        params.append(current["id"])

    elif scope == "pending":
        if role == "admin":
            clauses.append("status IN ('pending_ksv','pending_tong_hop','pending_gd')")
        elif role in ("giam_doc", "pho_giam_doc"):
            if not _can_gd_review(current, db):
                return []
            clauses.append("gd_approver_id = ? AND status = 'pending_gd'")
            params.append(current["id"])
        elif _is_tong_hop_staff(current, db):
            clauses.append("status = 'pending_tong_hop'")
        elif role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            clauses.append("ksv_approver_id = ? AND status = 'pending_ksv'")
            params.append(current["id"])
        else:
            return []

    elif scope == "all":
        if role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
            if not _is_tong_hop_staff(current, db):
                raise HTTPException(403, "Không có quyền xem tất cả đơn")

    else:
        raise HTTPException(400, "scope phải là mine | pending | all")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = db.execute(
        f"SELECT id FROM leave_records {where} ORDER BY created_at DESC", params
    ).fetchall()
    return [_leave_to_out(r["id"], db) for r in rows]


@router.get("/calendar")
def leave_calendar(
    year: int,
    month: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    import calendar as _cal
    if not (1 <= month <= 12):
        raise HTTPException(400, "month phải từ 1 đến 12")
    last_day = _cal.monthrange(year, month)[1]
    start = date(year, month, 1)
    end   = date(year, month, last_day)

    leaves = db.execute(
        """SELECT lr.id, lr.start_date, lr.end_date, lr.leave_type, lr.status,
                  ks.full_name
           FROM leave_records lr
           LEFT JOIN user_tttt ks ON lr.staff_id = ks.id
           WHERE lr.status NOT IN ('rejected','cancelled')
             AND lr.start_date <= ? AND lr.end_date >= ?""",
        (end.isoformat(), start.isoformat()),
    ).fetchall()

    day_map: dict = {}
    cur = start
    while cur <= end:
        day_map[cur.isoformat()] = []
        cur += timedelta(days=1)

    for lv in leaves:
        cur = max(date.fromisoformat(lv["start_date"]), start)
        lv_end = min(date.fromisoformat(lv["end_date"]), end)
        while cur <= lv_end:
            day_map[cur.isoformat()].append({
                "staff_name": lv["full_name"] or "",
                "leave_type": lv["leave_type"],
                "status":     lv["status"],
                "leave_id":   lv["id"],
            })
            cur += timedelta(days=1)

    return {"year": year, "month": month, "days": day_map}


@router.get("/export")
def export_leaves(
    scope: str = "all",
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    role = current["role"]
    clauses: list = []
    params: list  = []

    if scope == "mine":
        clauses.append("lr.staff_id = ?")
        params.append(current["id"])
    elif scope == "all":
        if role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
            if not _is_tong_hop_staff(current, db):
                raise HTTPException(403, "Không có quyền xuất tất cả đơn")
    elif scope == "pending":
        if role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            clauses.append("lr.ksv_approver_id = ? AND lr.status = 'pending_ksv'")
            params.append(current["id"])
        elif _is_tong_hop_staff(current, db):
            clauses.append("lr.status = 'pending_tong_hop'")
        elif role in ("giam_doc", "pho_giam_doc", "admin"):
            clauses.append("lr.status = 'pending_gd'")
        else:
            clauses.append("1=0")
    else:
        raise HTTPException(400, "scope phải là mine | pending | all")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    leaves = db.execute(
        f"""SELECT lr.*, s.full_name AS staff_name, s.department_id AS s_dept_id,
                   kv.full_name AS ksv_name, th.full_name AS th_name,
                   gd.full_name AS gd_name, gd.role AS gd_role,
                   d.name AS dept_name
            FROM leave_records lr
            LEFT JOIN user_tttt s  ON lr.staff_id             = s.id
            LEFT JOIN user_tttt kv ON lr.ksv_approver_id      = kv.id
            LEFT JOIN user_tttt th ON lr.tong_hop_approver_id = th.id
            LEFT JOIN user_tttt gd ON lr.gd_approver_id       = gd.id
            LEFT JOIN departments d ON s.department_id          = d.id
            {where}
            ORDER BY lr.created_at DESC""",
        params,
    ).fetchall()

    # Tải tất cả ngày lễ 1 lần cho toàn bộ khoảng
    all_holidays: FrozenSet[date] = frozenset()
    if leaves:
        min_d = min(date.fromisoformat(lv["start_date"]) for lv in leaves)
        max_d = max(date.fromisoformat(lv["end_date"])   for lv in leaves)
        all_holidays = _load_holidays(db, min_d, max_d)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Nghỉ phép"

    hdr_fill = PatternFill("solid", fgColor="C62828")
    hdr_font = Font(bold=True, color="FFFFFF")
    headers  = ["STT", "Họ và tên", "Phòng", "Loại nghỉ",
                "Từ ngày", "Đến ngày", "Số ngày", "Trạng thái",
                "KSV duyệt", "Phòng Tổng hợp", "GĐ/PGĐ", "Ngày tạo"]
    widths   = [6, 25, 20, 18, 12, 12, 9, 18, 22, 22, 22, 14]
    ws.append(headers)
    for cell, w in zip(ws[1], widths):
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, lv in enumerate(leaves, 1):
        s_date = date.fromisoformat(lv["start_date"])
        e_date = date.fromisoformat(lv["end_date"])
        days   = calculate_leave_days(s_date, e_date, all_holidays)
        gd_name = ""
        if lv["gd_name"]:
            gd_name = lv["gd_name"]
            if lv["gd_role"] == "pho_giam_doc":
                gd_name += " (TUQ)"
        created = lv["created_at"] or ""
        try:
            from datetime import datetime as _dt
            created = _dt.fromisoformat(str(created)).strftime("%d/%m/%Y")
        except Exception:
            pass
        ws.append([
            idx,
            lv["staff_name"] or "",
            lv["dept_name"] or "",
            LEAVE_TYPE_LABELS.get(lv["leave_type"] or "", ""),
            s_date.strftime("%d/%m/%Y"),
            e_date.strftime("%d/%m/%Y"),
            days,
            _LEAVE_STATUS_VN.get(lv["status"] or "", lv["status"] or ""),
            lv["ksv_name"] or "",
            lv["th_name"]  or "",
            gd_name,
            created,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''danh_sach_nghi_phep.xlsx"},
    )


@router.get("/{leave_id}")
def get_leave(
    leave_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    r = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    is_th = _is_tong_hop_staff(current, db)
    if (r["staff_id"] != current["id"]
            and r["ksv_approver_id"] != current["id"]
            and r["tong_hop_approver_id"] != current["id"]
            and r["gd_approver_id"] != current["id"]
            and not is_th
            and current["role"] not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")):
        raise HTTPException(403, "Không có quyền xem đơn này")
    return _leave_to_out(leave_id, db)


@router.put("/{leave_id}/ksv-review")
def ksv_review(
    leave_id: int,
    body: LeaveReview,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_ksv),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["status"] != LeaveStatus.PENDING_KSV:
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave['status']}'")
    if leave["ksv_approver_id"] != current["id"]:
        raise HTTPException(403, "Bạn không phải người được chỉ định duyệt bước này")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    old = leave["status"]
    new_status = LeaveStatus.PENDING_TONG_HOP if body.action == "approve" else LeaveStatus.REJECTED
    db.execute(
        "UPDATE leave_records SET ksv_approved_at=?, ksv_comment=? WHERE id=?",
        (str(_vn_now()), body.comment, leave_id),
    )
    start = date.fromisoformat(leave["start_date"])
    end   = date.fromisoformat(leave["end_date"])
    _h    = _load_holidays(db, start, end)
    _apply_status_transition(leave_id, old, new_status, start, end, leave["staff_id"], _h, db)
    _log_action(db, leave_id, current["id"],
                "ksv_approve" if body.action == "approve" else "ksv_reject",
                body.comment, old, new_status)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.post("/{leave_id}/tong-hop-review")
def tong_hop_review(
    leave_id: int,
    body: TongHopReview,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if not _is_tong_hop_staff(current, db):
        raise HTTPException(403, "Chỉ nhân viên Phòng Tổng hợp mới thực hiện được")
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["status"] != LeaveStatus.PENDING_TONG_HOP:
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave['status']}'")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    old = leave["status"]
    db.execute(
        "UPDATE leave_records SET tong_hop_approver_id=?, tong_hop_approved_at=?, tong_hop_comment=? WHERE id=?",
        (current["id"], str(_vn_now()), body.comment, leave_id),
    )

    if body.action == "forward":
        if not body.gd_approver_id:
            raise HTTPException(400, "Vui lòng chọn GĐ/PGĐ phê duyệt")
        gd = db.execute("SELECT * FROM user_tttt WHERE id = ? AND is_active = 1", (body.gd_approver_id,)).fetchone()
        if not gd or gd["role"] not in ("giam_doc", "pho_giam_doc"):
            raise HTTPException(400, "Người được chọn không phải GĐ hoặc PGĐ")
        db.execute("UPDATE leave_records SET gd_approver_id=? WHERE id=?", (body.gd_approver_id, leave_id))
        new_status = LeaveStatus.PENDING_GD
        action_key = "th_forward"
    else:
        new_status = LeaveStatus.REJECTED
        action_key = "th_reject"

    start = date.fromisoformat(leave["start_date"])
    end   = date.fromisoformat(leave["end_date"])
    _h    = _load_holidays(db, start, end)
    _apply_status_transition(leave_id, old, new_status, start, end, leave["staff_id"], _h, db)
    _log_action(db, leave_id, current["id"], action_key, body.comment, old, new_status)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.put("/{leave_id}/gd-review")
def gd_review(
    leave_id: int,
    body: LeaveReview,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_gd_level),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["status"] != LeaveStatus.PENDING_GD:
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave['status']}'")
    if not _can_gd_review(current, db):
        raise HTTPException(403, "Phó Giám đốc chưa được ủy quyền phê duyệt")
    if leave["gd_approver_id"] != current["id"]:
        raise HTTPException(403, "Bạn không phải người được chỉ định duyệt bước này")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    old = leave["status"]
    new_status = LeaveStatus.APPROVED if body.action == "approve" else LeaveStatus.REJECTED
    db.execute(
        "UPDATE leave_records SET gd_approved_at=?, gd_comment=?, gd_approver_id=? WHERE id=?",
        (str(_vn_now()), body.comment, current["id"], leave_id),
    )
    start = date.fromisoformat(leave["start_date"])
    end   = date.fromisoformat(leave["end_date"])
    _h    = _load_holidays(db, start, end)
    _apply_status_transition(leave_id, old, new_status, start, end, leave["staff_id"], _h, db)
    _log_action(db, leave_id, current["id"],
                "gd_approve" if body.action == "approve" else "gd_reject",
                body.comment, old, new_status)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.put("/{leave_id}/resubmit")
def resubmit_leave(
    leave_id: int,
    body: LeaveCreate,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["staff_id"] != current["id"]:
        raise HTTPException(403, "Chỉ chủ nhân đơn mới được nộp lại")
    if leave["status"] != LeaveStatus.REJECTED:
        raise HTTPException(400, "Chỉ có thể nộp lại đơn đã bị từ chối")

    if body.end_date < body.start_date:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")
    _h = _load_holidays(db, body.start_date, body.end_date)
    leave_days = calculate_leave_days(body.start_date, body.end_date, _h)
    if body.leave_type == "annual":
        remaining = (current.get("annual_leave_days") or 12) - (current.get("used_leave_days") or 0)
        if leave_days > remaining:
            raise HTTPException(400, f"Vượt quá số ngày phép còn lại ({remaining} ngày)")

    overlap = db.execute(
        """SELECT id FROM leave_records
           WHERE staff_id = ? AND id != ? AND status NOT IN ('rejected','cancelled')
             AND start_date <= ? AND end_date >= ?""",
        (current["id"], leave_id, body.end_date.isoformat(), body.start_date.isoformat()),
    ).fetchone()
    if overlap:
        raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")

    if current["role"] in _HIGH_ROLES:
        new_status      = LeaveStatus.PENDING_TONG_HOP
        ksv_approver_id = None
    else:
        ksv = _validate_ksv(body.ksv_approver_id, current, db)
        new_status      = LeaveStatus.PENDING_KSV
        ksv_approver_id = ksv["id"]

    old = leave["status"]
    _log_action(db, leave_id, current["id"], "resubmit", None, old, new_status)

    db.execute(
        """UPDATE leave_records SET
               ksv_approver_id=?, ksv_approved_at=NULL, ksv_comment=NULL,
               tong_hop_approver_id=NULL, tong_hop_approved_at=NULL, tong_hop_comment=NULL,
               gd_approver_id=NULL, gd_approved_at=NULL, gd_comment=NULL,
               leave_type=?, start_date=?, end_date=?, reason=?
           WHERE id=?""",
        (ksv_approver_id, body.leave_type, body.start_date.isoformat(),
         body.end_date.isoformat(), body.reason, leave_id),
    )
    _apply_status_transition(leave_id, old, new_status, body.start_date, body.end_date, leave["staff_id"], _h, db)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.patch("/{leave_id}/cancel")
def cancel_leave(
    leave_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["staff_id"] != current["id"] and current["role"] != "admin":
        raise HTTPException(403, "Chỉ chủ nhân đơn hoặc Admin mới được hủy")
    if leave["status"] not in (LeaveStatus.PENDING_KSV, LeaveStatus.PENDING_TONG_HOP, LeaveStatus.PENDING_GD, LeaveStatus.APPROVED):
        raise HTTPException(400, f"Không thể hủy đơn đang ở trạng thái '{leave['status']}'")

    old   = leave["status"]
    start = date.fromisoformat(leave["start_date"])
    end   = date.fromisoformat(leave["end_date"])
    _h    = _load_holidays(db, start, end)
    _apply_status_transition(leave_id, old, LeaveStatus.CANCELLED, start, end, leave["staff_id"], _h, db)
    _log_action(db, leave_id, current["id"], "cancel", None, old, LeaveStatus.CANCELLED)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.get("/{leave_id}/history")
def get_leave_history(
    leave_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    is_th = _is_tong_hop_staff(current, db)
    if (leave["staff_id"] != current["id"]
            and leave["ksv_approver_id"] != current["id"]
            and leave["gd_approver_id"] != current["id"]
            and not is_th
            and current["role"] not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")):
        raise HTTPException(403)

    logs = db.execute(
        """SELECT lal.*, ks.full_name AS actor_name
           FROM leave_action_logs lal
           LEFT JOIN user_tttt ks ON lal.actor_id = ks.id
           WHERE lal.leave_id = ? ORDER BY lal.created_at""",
        (leave_id,),
    ).fetchall()

    return [
        {
            "id":           log["id"],
            "actor_name":   log["actor_name"] or "",
            "action":       log["action"],
            "action_label": ACTION_LABELS.get(log["action"], (log["action"], "grey"))[0],
            "action_color": ACTION_LABELS.get(log["action"], (log["action"], "grey"))[1],
            "comment":      log["comment"],
            "from_status":  log["from_status"],
            "to_status":    log["to_status"],
            "created_at":   log["created_at"],
        }
        for log in logs
    ]


# ─── Word template download ──────────────────────────────────────────────────

_ROLE_VN = {
    "chuyen_vien":   "Chuyên viên",
    "pho_phong":     "Phó phòng",
    "truong_phong":  "Trưởng phòng",
    "hau_kiem_vien": "Hậu kiểm viên",
    "giam_doc":      "Giám đốc",
    "pho_giam_doc":  "Phó Giám đốc",
    "controller":    "Phó phòng",
    "admin":         "Quản trị viên",
}

_TPL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "templates", "don_xin_nghi_phep_tpl.docx",
)


def _fmt_leave_period(start: date, end: date, days: int) -> str:
    if days == 1:
        return f"{days:02d} ngày (ngày {start.day:02d} tháng {start.month:02d} năm {start.year})"
    return (
        f"{days:02d} ngày "
        f"(Từ ngày {start.strftime('%d/%m/%Y')} đến ngày {end.strftime('%d/%m/%Y')})"
    )


@router.get("/{leave_id}/download")
def download_leave_form(
    leave_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    r = db.execute(
        """SELECT lr.*,
                  s.full_name AS staff_name, s.role AS staff_role,
                  s.employee_code, s.annual_leave_days, s.used_leave_days,
                  d.name AS dept_name,
                  kv.full_name AS ksv_name,
                  gd.full_name AS gd_approver_name, gd.role AS gd_role
           FROM leave_records lr
           LEFT JOIN user_tttt s  ON lr.staff_id             = s.id
           LEFT JOIN departments d ON s.department_id          = d.id
           LEFT JOIN user_tttt kv ON lr.ksv_approver_id      = kv.id
           LEFT JOIN user_tttt gd ON lr.gd_approver_id       = gd.id
           WHERE lr.id = ?""",
        (leave_id,),
    ).fetchone()
    if not r:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")

    is_th = _is_tong_hop_staff(current, db)
    if (r["staff_id"] != current["id"]
            and r["ksv_approver_id"] != current["id"]
            and r["gd_approver_id"] != current["id"]
            and not is_th
            and current["role"] not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")):
        raise HTTPException(403, "Không có quyền tải đơn này")

    if not os.path.exists(_TPL_PATH):
        raise HTTPException(500, "Chưa có template đơn nghỉ phép")

    start = date.fromisoformat(r["start_date"])
    end   = date.fromisoformat(r["end_date"])
    now   = _vn_now()
    _h    = _load_holidays(db, start, end)

    leave_days = calculate_leave_days(start, end, _h)
    tong_phep  = r["annual_leave_days"] or 12
    da_nghi    = r["used_leave_days"] or 0
    con_lai    = max(0, tong_phep - da_nghi - leave_days)

    gd_name = ""
    if r["gd_approver_name"]:
        gd_name = r["gd_approver_name"]
        if r["gd_role"] == "pho_giam_doc":
            gd_name = f"{gd_name} (TUQ)"

    # annual/bat_buoc → ngày làm đơn; dot_xuat và các loại khác → ngày bắt đầu nghỉ
    _doc_date = now.date() if r["leave_type"] in ("annual", "bat_buoc") else start
    ctx = {
        "ngay_thang_nam":   f"{_doc_date.day:02d} tháng {_doc_date.month:02d} năm {_doc_date.year}",
        "ho_va_ten":        r["staff_name"] or "",
        "chuc_vu":          _ROLE_VN.get(r["staff_role"] or "", r["staff_role"] or ""),
        "don_vi":           r["dept_name"] or "",
        "nam_phep":         str(start.year),
        "tong_so_phep":     str(tong_phep),
        "so_ngay_da_nghi":  str(da_nghi),
        "so_ngay_xin_nghi": _fmt_leave_period(start, end, leave_days),
        "so_ngay_con_lai":  str(con_lai),
        "ly_do":            r["reason"] or "",
        "ksv_name":         r["ksv_name"] or "",
        "gd_name":          gd_name,
    }

    from docxtpl import DocxTemplate
    tpl = DocxTemplate(_TPL_PATH)
    tpl.render(ctx)
    buf = io.BytesIO()
    tpl.save(buf)
    buf.seek(0)

    ec = r["employee_code"] or "staff"
    safe_name = f"don_nghi_phep_{ec}_{r['start_date']}.docx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )
