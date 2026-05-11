"""Quản lý nghỉ phép — đăng ký, phê duyệt, tải phiếu"""
import io
import os
from datetime import date, timedelta
from typing import List, Optional, FrozenSet

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.deps import (
    get_current_staff, require_ksv, require_gd_level, TONG_HOP_CODES
)
from backend.models import (
    KSNBStaff, LeaveRecord, LeaveActionLog, DelegationRecord, Department, LeaveTypeEnum,
    PublicHoliday, _vn_now,
)
from backend.schemas import LeaveCreate, LeaveReview, TongHopReview, LeaveOut, LeaveActionLogOut

router = APIRouter()

LEAVE_TYPE_LABELS = {
    "annual":   "Nghỉ phép năm",
    "sick":     "Nghỉ ốm",
    "personal": "Nghỉ việc riêng",
    "other":    "Khác",
}

ACTION_LABELS = {
    "ksv_approve":  ("KSV phê duyệt",    "green"),
    "ksv_reject":   ("KSV từ chối",       "red"),
    "th_forward":   ("TH chuyển GĐ",     "blue"),
    "th_reject":    ("TH từ chối",        "red"),
    "gd_approve":   ("GĐ phê duyệt",     "green"),
    "gd_reject":    ("GĐ từ chối",        "red"),
    "resubmit":     ("Nộp lại",           "orange"),
    "cancel":       ("Hủy đơn",           "grey"),
}

# Các role cấp cao — bỏ qua bước KSV, vào thẳng pending_tong_hop
_HIGH_ROLES = frozenset(("giam_doc", "pho_giam_doc", "admin"))


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_holidays(db: Session, start: date, end: date) -> FrozenSet[date]:
    """Tải tập hợp ngày lễ trong khoảng start..end từ DB."""
    rows = db.query(PublicHoliday.date).filter(
        PublicHoliday.date >= start,
        PublicHoliday.date <= end,
    ).all()
    return frozenset(r.date for r in rows)


def calculate_leave_days(
    start: date, end: date,
    holiday_dates: FrozenSet[date] = frozenset(),
) -> int:
    """Đếm ngày làm việc thực (trừ T7, CN và ngày lễ). Tối thiểu 1 ngày."""
    count = 0
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in holiday_dates:  # 0=Thứ 2 ... 4=Thứ 6
            count += 1
        d += timedelta(days=1)
    return max(count, 1)


def _is_tong_hop_staff(staff: KSNBStaff, db: Session) -> bool:
    if not staff.department_id:
        return False
    dept = db.get(Department, staff.department_id)
    return bool(dept and dept.code.upper() in TONG_HOP_CODES)


def _can_gd_review(current: KSNBStaff, db: Session) -> bool:
    if current.role == "giam_doc":
        return True
    if current.role == "pho_giam_doc":
        today = _vn_now().date()
        return db.query(DelegationRecord).filter(
            DelegationRecord.pho_giam_doc_id == current.id,
            DelegationRecord.is_active == True,
            DelegationRecord.start_date <= today,
            DelegationRecord.end_date >= today,
        ).first() is not None
    return False


def _apply_status_transition(leave: LeaveRecord, new_status: str, staff: KSNBStaff,
                              holiday_dates: FrozenSet[date] = frozenset()):
    """Cập nhật status và điều chỉnh used_leave_days (idempotent)."""
    old = leave.status
    days = calculate_leave_days(leave.start_date, leave.end_date, holiday_dates)
    if old != "approved" and new_status == "approved":
        staff.used_leave_days = (staff.used_leave_days or 0) + days
    elif old == "approved" and new_status in ("cancelled", "rejected"):
        staff.used_leave_days = max(0, (staff.used_leave_days or 0) - days)
    leave.status = new_status
    leave.updated_at = _vn_now()


def _log_action(db: Session, leave_id: int, actor_id: int, action: str,
                comment: Optional[str], from_status: str, to_status: str):
    db.add(LeaveActionLog(
        leave_id=leave_id, actor_id=actor_id, action=action,
        comment=comment, from_status=from_status, to_status=to_status,
        created_at=_vn_now(),
    ))


def _validate_ksv(ksv_id: Optional[int], current: KSNBStaff, db: Session) -> KSNBStaff:
    if not ksv_id:
        raise HTTPException(400, "Vui lòng chọn người phê duyệt bước KSV")
    ksv = db.get(KSNBStaff, ksv_id)
    if not ksv or not ksv.is_active:
        raise HTTPException(400, "Người phê duyệt không tồn tại hoặc đã bị vô hiệu")
    if ksv.role not in ("truong_phong", "pho_phong", "hau_kiem_vien", "admin"):
        raise HTTPException(400, "Người phê duyệt phải là Trưởng phòng, Phó phòng hoặc Hậu kiểm viên")
    if ksv_id == current.id:
        raise HTTPException(400, "Không thể tự phê duyệt")
    return ksv


def _dept_name(staff: KSNBStaff, db: Session) -> Optional[str]:
    if not staff or not staff.department_id:
        return None
    dept = db.get(Department, staff.department_id)
    return dept.name if dept else None


def _leave_to_out(leave: LeaveRecord, db: Session) -> dict:
    gd_is_pgd = False
    if leave.gd_approver:
        role_val = leave.gd_approver.role
        if hasattr(role_val, "value"):
            role_val = role_val.value
        gd_is_pgd = role_val == "pho_giam_doc"

    _holidays = _load_holidays(db, leave.start_date, leave.end_date)
    return {
        "id": leave.id,
        "staff_id": leave.staff_id,
        "staff_name": leave.staff.full_name if leave.staff else "",
        "department_name": _dept_name(leave.staff, db) if leave.staff else None,
        "start_date": leave.start_date,
        "end_date": leave.end_date,
        "leave_days": calculate_leave_days(leave.start_date, leave.end_date, _holidays),
        "leave_type": leave.leave_type,
        "reason": leave.reason,
        "status": leave.status,
        "ksv_approver_id": leave.ksv_approver_id,
        "ksv_approver_name": leave.ksv_approver.full_name if leave.ksv_approver else None,
        "ksv_approved_at": leave.ksv_approved_at,
        "ksv_comment": leave.ksv_comment,
        "tong_hop_approver_id": leave.tong_hop_approver_id,
        "tong_hop_approver_name": leave.tong_hop_approver.full_name if leave.tong_hop_approver else None,
        "tong_hop_approved_at": leave.tong_hop_approved_at,
        "tong_hop_comment": leave.tong_hop_comment,
        "gd_approver_id": leave.gd_approver_id,
        "gd_approver_name": leave.gd_approver.full_name if leave.gd_approver else None,
        "gd_is_pgd": gd_is_pgd,
        "gd_approved_at": leave.gd_approved_at,
        "gd_comment": leave.gd_comment,
        "created_at": leave.created_at,
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/approvers")
def get_approvers(
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    """Danh sách TP/PP/HKV/admin để chọn làm người duyệt bước KSV."""
    staffs = db.query(KSNBStaff).filter(
        KSNBStaff.is_active == True,
        KSNBStaff.role.in_(["truong_phong", "pho_phong", "hau_kiem_vien", "admin"]),
        KSNBStaff.id != current.id,
    ).order_by(KSNBStaff.full_name).all()
    _ROLE_LABEL = {
        "truong_phong": "Trưởng phòng", "pho_phong": "Phó phòng",
        "hau_kiem_vien": "Hậu kiểm viên", "admin": "Quản trị viên",
    }
    return [{"id": s.id, "full_name": s.full_name,
             "role_label": _ROLE_LABEL.get(s.role, s.role)} for s in staffs]


@router.get("/gd-list")
def get_gd_list(
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    """Danh sách GĐ/PGĐ để TH chọn người duyệt bước 3."""
    if not (_is_tong_hop_staff(current, db) or current.role == "admin"):
        raise HTTPException(403, "Chỉ nhân viên Phòng Tổng hợp hoặc Admin mới được xem")
    staffs = db.query(KSNBStaff).filter(
        KSNBStaff.is_active == True,
        KSNBStaff.role.in_(["giam_doc", "pho_giam_doc"]),
    ).all()
    _ROLE_LABEL = {"giam_doc": "Giám đốc", "pho_giam_doc": "Phó Giám đốc"}
    return [{"id": s.id, "full_name": s.full_name,
             "role_label": _ROLE_LABEL.get(s.role, s.role)} for s in staffs]


@router.post("/", response_model=LeaveOut)
def create_leave(
    body: LeaveCreate,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    # ── Validate ngày ──
    if body.end_date < body.start_date:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")

    # ── Kiểm tra quota ──
    _h = _load_holidays(db, body.start_date, body.end_date)
    leave_days = calculate_leave_days(body.start_date, body.end_date, _h)
    if body.leave_type == "annual":
        remaining = (current.annual_leave_days or 12) - (current.used_leave_days or 0)
        if leave_days > remaining:
            raise HTTPException(400, f"Vượt quá số ngày phép còn lại ({remaining} ngày)")

    # ── Kiểm tra overlap ──
    overlap = db.query(LeaveRecord).filter(
        LeaveRecord.staff_id == current.id,
        LeaveRecord.status.not_in(["rejected", "cancelled"]),
        LeaveRecord.start_date <= body.end_date,
        LeaveRecord.end_date >= body.start_date,
    ).first()
    if overlap:
        raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")

    # ── Xác định trạng thái và người duyệt ──
    if current.role in _HIGH_ROLES:
        initial_status   = "pending_tong_hop"
        ksv_approver_id  = None
    else:
        ksv = _validate_ksv(body.ksv_approver_id, current, db)
        initial_status   = "pending_ksv"
        ksv_approver_id  = ksv.id

    leave = LeaveRecord(
        staff_id        = current.id,
        start_date      = body.start_date,
        end_date        = body.end_date,
        leave_type      = body.leave_type,
        reason          = body.reason,
        status          = initial_status,
        ksv_approver_id = ksv_approver_id,
        updated_at      = _vn_now(),
    )
    db.add(leave)
    db.flush()
    _log_action(db, leave.id, current.id, "resubmit" if False else "create",
                None, "", initial_status)
    db.commit()
    db.refresh(leave)
    return _leave_to_out(leave, db)


@router.get("/", response_model=List[LeaveOut])
def list_leaves(
    scope: str = "mine",
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    q = db.query(LeaveRecord)
    role = current.role

    if scope == "mine":
        q = q.filter(LeaveRecord.staff_id == current.id)

    elif scope == "pending":
        if role == "admin":
            q = q.filter(LeaveRecord.status.in_(
                ["pending_ksv", "pending_tong_hop", "pending_gd"]
            ))
        elif role in ("giam_doc", "pho_giam_doc"):
            if _can_gd_review(current, db):
                q = q.filter(
                    LeaveRecord.gd_approver_id == current.id,
                    LeaveRecord.status == "pending_gd",
                )
            else:
                q = q.filter(False)
        elif _is_tong_hop_staff(current, db):
            q = q.filter(LeaveRecord.status == "pending_tong_hop")
        elif role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            q = q.filter(
                LeaveRecord.ksv_approver_id == current.id,
                LeaveRecord.status == "pending_ksv",
            )
        else:
            q = q.filter(False)

    elif scope == "all":
        if role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
            if not _is_tong_hop_staff(current, db):
                raise HTTPException(403, "Không có quyền xem tất cả đơn")

    else:
        raise HTTPException(400, "scope phải là mine | pending | all")

    leaves = q.order_by(LeaveRecord.created_at.desc()).all()
    return [_leave_to_out(lv, db) for lv in leaves]


@router.get("/calendar")
def leave_calendar(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff),
):
    """Trả danh sách người nghỉ cho từng ngày trong tháng (status != rejected/cancelled)."""
    import calendar as _cal
    if not (1 <= month <= 12):
        from fastapi import HTTPException as _H
        raise _H(400, "month phải từ 1 đến 12")
    last_day = _cal.monthrange(year, month)[1]
    start = date(year, month, 1)
    end   = date(year, month, last_day)

    leaves = db.query(LeaveRecord).filter(
        LeaveRecord.status.not_in(["rejected", "cancelled"]),
        LeaveRecord.start_date <= end,
        LeaveRecord.end_date >= start,
    ).all()

    # Xây dict: ngày_ISO → list người nghỉ
    day_map: dict[str, list] = {}
    cur = start
    while cur <= end:
        day_map[cur.isoformat()] = []
        cur += timedelta(days=1)

    for lv in leaves:
        cur = max(lv.start_date, start)
        lv_end = min(lv.end_date, end)
        while cur <= lv_end:
            day_map[cur.isoformat()].append({
                "staff_name": lv.staff.full_name if lv.staff else "",
                "leave_type": str(lv.leave_type.value) if hasattr(lv.leave_type, "value") else str(lv.leave_type),
                "status": lv.status,
                "leave_id": lv.id,
            })
            cur += timedelta(days=1)

    return {"year": year, "month": month, "days": day_map}


_LEAVE_STATUS_VN = {
    "pending_ksv":      "Chờ KSV duyệt",
    "pending_tong_hop": "Chờ Tổng hợp",
    "pending_gd":       "Chờ GĐ duyệt",
    "approved":         "Đã phê duyệt",
    "rejected":         "Bị từ chối",
    "cancelled":        "Đã hủy",
}


@router.get("/export")
def export_leaves(
    scope: str = "all",
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    """Xuất danh sách nghỉ phép ra file Excel."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    q = db.query(LeaveRecord)
    if scope == "mine":
        q = q.filter(LeaveRecord.staff_id == current.id)
    elif scope == "all":
        if current.role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
            if not _is_tong_hop_staff(current, db):
                raise HTTPException(403, "Không có quyền xuất tất cả đơn")
    elif scope == "pending":
        role = current.role
        if role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            q = q.filter(LeaveRecord.ksv_approver_id == current.id, LeaveRecord.status == "pending_ksv")
        elif _is_tong_hop_staff(current, db):
            q = q.filter(LeaveRecord.status == "pending_tong_hop")
        elif role in ("giam_doc", "pho_giam_doc", "admin"):
            q = q.filter(LeaveRecord.status == "pending_gd")
        else:
            q = q.filter(False)
    else:
        raise HTTPException(400, "scope phải là mine | pending | all")

    leaves = q.order_by(LeaveRecord.created_at.desc()).all()

    # ── Tạo workbook ──
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
    for i, (cell, w) in enumerate(zip(ws[1], widths), 1):
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, lv in enumerate(leaves, 1):
        dept = db.get(Department, lv.staff.department_id) if (lv.staff and lv.staff.department_id) else None
        _h   = _load_holidays(db, lv.start_date, lv.end_date)
        days = calculate_leave_days(lv.start_date, lv.end_date, _h)
        gd_name = ""
        if lv.gd_approver:
            gd_name = lv.gd_approver.full_name
            gd_role = lv.gd_approver.role.value if hasattr(lv.gd_approver.role, "value") else str(lv.gd_approver.role)
            if gd_role == "pho_giam_doc":
                gd_name += " (TUQ)"
        ws.append([
            idx,
            lv.staff.full_name if lv.staff else "",
            dept.name if dept else "",
            LEAVE_TYPE_LABELS.get(str(lv.leave_type.value) if hasattr(lv.leave_type, "value") else str(lv.leave_type), ""),
            lv.start_date.strftime("%d/%m/%Y"),
            lv.end_date.strftime("%d/%m/%Y"),
            days,
            _LEAVE_STATUS_VN.get(lv.status, lv.status),
            lv.ksv_approver.full_name if lv.ksv_approver else "",
            lv.tong_hop_approver.full_name if lv.tong_hop_approver else "",
            gd_name,
            lv.created_at.strftime("%d/%m/%Y") if lv.created_at else "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''danh_sach_nghi_phep.xlsx"},
    )


@router.get("/{leave_id}", response_model=LeaveOut)
def get_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    role = current.role
    is_th = _is_tong_hop_staff(current, db)
    if (leave.staff_id != current.id
            and leave.ksv_approver_id != current.id
            and leave.tong_hop_approver_id != current.id
            and leave.gd_approver_id != current.id
            and not is_th
            and role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")):
        raise HTTPException(403, "Không có quyền xem đơn này")
    return _leave_to_out(leave, db)


@router.put("/{leave_id}/ksv-review", response_model=LeaveOut)
def ksv_review(
    leave_id: int,
    body: LeaveReview,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_ksv),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave.status != "pending_ksv":
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave.status}'")
    if leave.ksv_approver_id != current.id:
        raise HTTPException(403, "Bạn không phải người được chỉ định duyệt bước này")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    leave.ksv_approved_at = _vn_now()
    leave.ksv_comment     = body.comment

    old = leave.status
    if body.action == "approve":
        new_status = "pending_tong_hop"
    else:
        new_status = "rejected"

    staff = db.get(KSNBStaff, leave.staff_id)
    _h = _load_holidays(db, leave.start_date, leave.end_date)
    _apply_status_transition(leave, new_status, staff, _h)
    _log_action(db, leave.id, current.id,
                "ksv_approve" if body.action == "approve" else "ksv_reject",
                body.comment, old, new_status)
    db.commit()
    db.refresh(leave)
    return _leave_to_out(leave, db)


@router.post("/{leave_id}/tong-hop-review", response_model=LeaveOut)
def tong_hop_review(
    leave_id: int,
    body: TongHopReview,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    if not _is_tong_hop_staff(current, db):
        raise HTTPException(403, "Chỉ nhân viên Phòng Tổng hợp mới thực hiện được")
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave.status != "pending_tong_hop":
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave.status}'")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    old = leave.status
    leave.tong_hop_approver_id = current.id
    leave.tong_hop_approved_at = _vn_now()
    leave.tong_hop_comment     = body.comment

    if body.action == "forward":
        if not body.gd_approver_id:
            raise HTTPException(400, "Vui lòng chọn GĐ/PGĐ phê duyệt")
        gd = db.get(KSNBStaff, body.gd_approver_id)
        if not gd or gd.role not in ("giam_doc", "pho_giam_doc"):
            raise HTTPException(400, "Người được chọn không phải GĐ hoặc PGĐ")
        leave.gd_approver_id = body.gd_approver_id
        new_status = "pending_gd"
        action_key = "th_forward"
    else:
        new_status = "rejected"
        action_key = "th_reject"

    staff = db.get(KSNBStaff, leave.staff_id)
    _h = _load_holidays(db, leave.start_date, leave.end_date)
    _apply_status_transition(leave, new_status, staff, _h)
    _log_action(db, leave.id, current.id, action_key, body.comment, old, new_status)
    db.commit()
    db.refresh(leave)
    return _leave_to_out(leave, db)


@router.put("/{leave_id}/gd-review", response_model=LeaveOut)
def gd_review(
    leave_id: int,
    body: LeaveReview,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_gd_level),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave.status != "pending_gd":
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave.status}'")
    if not _can_gd_review(current, db):
        raise HTTPException(403, "Phó Giám đốc chưa được ủy quyền phê duyệt")
    if leave.gd_approver_id != current.id:
        raise HTTPException(403, "Bạn không phải người được chỉ định duyệt bước này")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    old = leave.status
    leave.gd_approved_at = _vn_now()
    leave.gd_comment     = body.comment
    leave.gd_approver_id = current.id  # Ghi lại PGĐ nếu duyệt thay

    new_status = "approved" if body.action == "approve" else "rejected"
    staff = db.get(KSNBStaff, leave.staff_id)
    _h = _load_holidays(db, leave.start_date, leave.end_date)
    _apply_status_transition(leave, new_status, staff, _h)
    _log_action(db, leave.id, current.id,
                "gd_approve" if body.action == "approve" else "gd_reject",
                body.comment, old, new_status)
    db.commit()
    db.refresh(leave)
    return _leave_to_out(leave, db)


@router.put("/{leave_id}/resubmit", response_model=LeaveOut)
def resubmit_leave(
    leave_id: int,
    body: LeaveCreate,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave.staff_id != current.id:
        raise HTTPException(403, "Chỉ chủ nhân đơn mới được nộp lại")
    if leave.status != "rejected":
        raise HTTPException(400, "Chỉ có thể nộp lại đơn đã bị từ chối")

    # ── Validate nội dung mới ──
    if body.end_date < body.start_date:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")
    _h = _load_holidays(db, body.start_date, body.end_date)
    leave_days = calculate_leave_days(body.start_date, body.end_date, _h)
    if body.leave_type == "annual":
        remaining = (current.annual_leave_days or 12) - (current.used_leave_days or 0)
        if leave_days > remaining:
            raise HTTPException(400, f"Vượt quá số ngày phép còn lại ({remaining} ngày)")
    overlap = db.query(LeaveRecord).filter(
        LeaveRecord.staff_id == current.id,
        LeaveRecord.id != leave_id,
        LeaveRecord.status.not_in(["rejected", "cancelled"]),
        LeaveRecord.start_date <= body.end_date,
        LeaveRecord.end_date >= body.start_date,
    ).first()
    if overlap:
        raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")

    # ── Reset workflow ──
    if current.role in _HIGH_ROLES:
        new_status      = "pending_tong_hop"
        ksv_approver_id = None
    else:
        ksv = _validate_ksv(body.ksv_approver_id, current, db)
        new_status      = "pending_ksv"
        ksv_approver_id = ksv.id

    _log_action(db, leave.id, current.id, "resubmit", None, leave.status, new_status)

    # Reset tất cả approval fields
    leave.ksv_approver_id      = ksv_approver_id
    leave.ksv_approved_at      = None
    leave.ksv_comment          = None
    leave.tong_hop_approver_id = None
    leave.tong_hop_approved_at = None
    leave.tong_hop_comment     = None
    leave.gd_approver_id       = None
    leave.gd_approved_at       = None
    leave.gd_comment           = None

    # Cập nhật nội dung đơn
    leave.leave_type = body.leave_type
    leave.start_date = body.start_date
    leave.end_date   = body.end_date
    leave.reason     = body.reason

    staff = db.get(KSNBStaff, leave.staff_id)
    _apply_status_transition(leave, new_status, staff, _h)
    db.commit()
    db.refresh(leave)
    return _leave_to_out(leave, db)


@router.patch("/{leave_id}/cancel", response_model=LeaveOut)
def cancel_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave.staff_id != current.id and current.role != "admin":
        raise HTTPException(403, "Chỉ chủ nhân đơn hoặc Admin mới được hủy")
    if leave.status not in ("pending_ksv", "pending_tong_hop", "pending_gd", "approved"):
        raise HTTPException(400, f"Không thể hủy đơn đang ở trạng thái '{leave.status}'")

    old = leave.status
    staff = db.get(KSNBStaff, leave.staff_id)
    _h = _load_holidays(db, leave.start_date, leave.end_date)
    _apply_status_transition(leave, "cancelled", staff, _h)
    _log_action(db, leave.id, current.id, "cancel", None, old, "cancelled")
    db.commit()
    db.refresh(leave)
    return _leave_to_out(leave, db)


@router.get("/{leave_id}/history")
def get_leave_history(
    leave_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    role = current.role
    is_th = _is_tong_hop_staff(current, db)
    if (leave.staff_id != current.id
            and leave.ksv_approver_id != current.id
            and leave.gd_approver_id != current.id
            and not is_th
            and role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")):
        raise HTTPException(403)

    logs = db.query(LeaveActionLog).filter(
        LeaveActionLog.leave_id == leave_id,
    ).order_by(LeaveActionLog.created_at).all()

    result = []
    for log in logs:
        label, color = ACTION_LABELS.get(log.action, (log.action, "grey"))
        result.append({
            "id": log.id,
            "actor_name": log.actor.full_name if log.actor else "",
            "action": log.action,
            "action_label": label,
            "action_color": color,
            "comment": log.comment,
            "from_status": log.from_status,
            "to_status": log.to_status,
            "created_at": log.created_at,
        })
    return result


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
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    leave = db.get(LeaveRecord, leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    role = current.role
    is_th = _is_tong_hop_staff(current, db)
    if (leave.staff_id != current.id
            and leave.ksv_approver_id != current.id
            and leave.gd_approver_id != current.id
            and not is_th
            and role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc")):
        raise HTTPException(403, "Không có quyền tải đơn này")

    if not os.path.exists(_TPL_PATH):
        raise HTTPException(500, "Chưa có template đơn nghỉ phép")

    dept = None
    if leave.staff and leave.staff.department_id:
        dept = db.get(Department, leave.staff.department_id)

    staff      = leave.staff
    role_val   = staff.role.value if hasattr(staff.role, "value") else str(staff.role)
    now        = _vn_now()
    _h         = _load_holidays(db, leave.start_date, leave.end_date)
    leave_days = calculate_leave_days(leave.start_date, leave.end_date, _h)
    tong_phep  = staff.annual_leave_days or 12
    da_nghi    = staff.used_leave_days or 0
    con_lai    = max(0, tong_phep - da_nghi - leave_days)

    # Nếu PGĐ ký thay → ghi (TUQ) sau họ tên
    gd_name = ""
    if leave.gd_approver:
        gd_name = leave.gd_approver.full_name
        gd_role = leave.gd_approver.role
        if hasattr(gd_role, "value"):
            gd_role = gd_role.value
        if gd_role == "pho_giam_doc":
            gd_name = f"{gd_name} (TUQ)"

    ctx = {
        "ngay_thang_nam":   f"{now.day:02d} tháng {now.month:02d} năm {now.year}",
        "ho_va_ten":        staff.full_name if staff else "",
        "chuc_vu":          _ROLE_VN.get(role_val, role_val),
        "don_vi":           dept.name if dept else "",
        "nam_phep":         str(leave.start_date.year),
        "tong_so_phep":     str(tong_phep),
        "so_ngay_da_nghi":  str(da_nghi),
        "so_ngay_xin_nghi": _fmt_leave_period(leave.start_date, leave.end_date, leave_days),
        "so_ngay_con_lai":  str(con_lai),
        "ly_do":            leave.reason or "",
        "ksv_name":         leave.ksv_approver.full_name if leave.ksv_approver else "",
        "gd_name":          gd_name,
    }

    from docxtpl import DocxTemplate
    tpl = DocxTemplate(_TPL_PATH)
    tpl.render(ctx)
    buf = io.BytesIO()
    tpl.save(buf)
    buf.seek(0)

    ec = staff.employee_code if staff else "staff"
    safe_name = f"don_nghi_phep_{ec}_{leave.start_date}.docx"
    cd = f"attachment; filename*=UTF-8''{safe_name}"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": cd},
    )
