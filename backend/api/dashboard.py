"""Dashboard API — KPI tổng hợp và pending counts cho sidebar badge"""
from datetime import date, timedelta
from typing import FrozenSet
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.deps import get_current_staff, TONG_HOP_CODES
from backend.models import (
    KSNBStaff, LeaveRecord, DocumentEntry, Handover, Department,
    DelegationRecord, PublicHoliday, _vn_now,
)

router = APIRouter()


def _working_days_between(
    start_exclusive: date,
    end_inclusive: date,
    holiday_dates: FrozenSet[date],
    leave_dates: FrozenSet[date] = frozenset(),
) -> int:
    """Số ngày làm việc thực trong (start_exclusive, end_inclusive].
    Trừ T7/CN, ngày lễ, ngày nghỉ phép của người phụ trách nhận bàn giao."""
    count = 0
    d = start_exclusive + timedelta(days=1)
    while d <= end_inclusive:
        if d.weekday() < 5 and d not in holiday_dates and d not in leave_dates:
            count += 1
        d += timedelta(days=1)
    return count


def _is_tong_hop(staff: KSNBStaff, db: Session) -> bool:
    if not staff.department_id:
        return False
    dept = db.get(Department, staff.department_id)
    return bool(dept and dept.code.upper() in TONG_HOP_CODES)


@router.get("/pending-counts")
def pending_counts(
    current: KSNBStaff = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Số việc đang chờ current user — dùng cho badge sidebar."""
    role = current.role
    leaves_count = 0
    handovers_count = 0

    # ── Đơn phép đang chờ ───────────────────────────────────────────────────
    if role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        leaves_count = db.query(func.count(LeaveRecord.id)).filter(
            LeaveRecord.ksv_approver_id == current.id,
            LeaveRecord.status == "pending_ksv",
        ).scalar() or 0

    elif _is_tong_hop(current, db):
        leaves_count = db.query(func.count(LeaveRecord.id)).filter(
            LeaveRecord.status == "pending_tong_hop",
        ).scalar() or 0

    elif role in ("giam_doc", "pho_giam_doc"):
        today = _vn_now().date()
        can_approve = (role == "giam_doc") or db.query(DelegationRecord).filter(
            DelegationRecord.pho_giam_doc_id == current.id,
            DelegationRecord.is_active == True,
            DelegationRecord.start_date <= today,
            DelegationRecord.end_date >= today,
        ).first() is not None
        if can_approve:
            leaves_count = db.query(func.count(LeaveRecord.id)).filter(
                LeaveRecord.gd_approver_id == current.id,
                LeaveRecord.status == "pending_gd",
            ).scalar() or 0
    # admin, chuyen_vien → 0

    # ── Chứng từ chờ xác nhận ────────────────────────────────────────────────
    handovers_by_dept: list[dict] = []

    def _dept_breakdown(extra_filter=None):
        q = (
            db.query(Department.name, func.count(DocumentEntry.id))
            .join(Handover, DocumentEntry.handover_id == Handover.id)
            .join(Department, Handover.department_id == Department.id)
            .filter(DocumentEntry.entry_status == "pending_confirm")
        )
        if extra_filter is not None:
            q = q.filter(extra_filter)
        rows = q.group_by(Department.name).order_by(Department.name).all()
        return [{"dept_name": name, "count": cnt} for name, cnt in rows]

    if role == "hau_kiem_vien":
        handovers_count = db.query(func.count(DocumentEntry.id)).filter(
            DocumentEntry.entry_status == "pending_confirm",
        ).scalar() or 0
        handovers_by_dept = _dept_breakdown()

    elif role == "chuyen_vien" and current.id:
        handovers_count = db.query(func.count(DocumentEntry.id)).filter(
            DocumentEntry.entry_status == "pending_confirm",
            DocumentEntry.entered_by_id == current.id,
        ).scalar() or 0
        handovers_by_dept = _dept_breakdown(DocumentEntry.entered_by_id == current.id)
    # Còn lại → 0

    return {"leaves": leaves_count, "handovers": handovers_count, "handovers_by_dept": handovers_by_dept}


@router.get("/summary")
def dashboard_summary(
    year: int = Query(None, description="Năm (mặc định năm hiện tại)"),
    month: int = Query(None, description="Tháng 1-12 (mặc định tháng hiện tại)"),
    current: KSNBStaff = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    """Tỷ lệ nộp chứng từ đúng hạn theo tháng, phân nhóm theo phòng."""
    today = _vn_now().date()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    period_start = date(year, month, 1)
    period_end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    # Mở rộng 35 ngày về trước để bao phủ transaction_date tháng trước
    lookup_start = period_start - timedelta(days=35)

    # ── Preload ngày lễ ───────────────────────────────────────────────────────
    holiday_dates: FrozenSet[date] = frozenset(
        r.date for r in db.query(PublicHoliday.date).filter(
            PublicHoliday.date >= lookup_start,
            PublicHoliday.date < period_end,
        ).all()
    )

    # ── Preload ngày nghỉ phép được duyệt của từng nhân viên KSNB ────────────
    # (dùng để loại trừ ngày nhân viên nhận không làm việc)
    leave_rows = db.query(
        LeaveRecord.staff_id,
        LeaveRecord.start_date,
        LeaveRecord.end_date,
    ).filter(
        LeaveRecord.status == "approved",
        LeaveRecord.end_date >= lookup_start,
        LeaveRecord.start_date < period_end,
    ).all()

    _raw_leave: dict[int, set] = defaultdict(set)
    for staff_id, lv_start, lv_end in leave_rows:
        d = max(lv_start, lookup_start)
        while d <= lv_end and d < period_end:
            if d.weekday() < 5:  # chỉ ngày làm việc mới cần lưu
                _raw_leave[staff_id].add(d)
            d += timedelta(days=1)
    staff_leave: dict[int, FrozenSet[date]] = {
        sid: frozenset(dates) for sid, dates in _raw_leave.items()
    }

    # ── Query entries đã bàn giao trong period ───────────────────────────────
    rows = (
        db.query(
            DocumentEntry.transaction_date,
            Handover.handover_date,
            Handover.received_by_id,
            Department.name.label("dept_name"),
        )
        .join(Handover, DocumentEntry.handover_id == Handover.id)
        .join(Department, Handover.department_id == Department.id)
        .filter(
            Handover.handover_date >= period_start,
            Handover.handover_date < period_end,
        )
        .all()
    )

    # ── Tính on_time: <= 1 ngày làm việc thực từ transaction_date ────────────
    # (bỏ T7/CN, ngày lễ, ngày nghỉ phép của người phụ trách nhận)
    by_dept: dict[str, dict] = {}
    overall_total = 0
    overall_on_time = 0

    for transaction_date, handover_date, received_by_id, dept_name in rows:
        receiver_leave = staff_leave.get(received_by_id, frozenset()) if received_by_id else frozenset()
        working_days   = _working_days_between(
            transaction_date, handover_date, holiday_dates, receiver_leave
        )
        on_time = working_days <= 1

        if dept_name not in by_dept:
            by_dept[dept_name] = {"total": 0, "on_time": 0}
        by_dept[dept_name]["total"] += 1
        if on_time:
            by_dept[dept_name]["on_time"] += 1
        overall_total += 1
        if on_time:
            overall_on_time += 1

    overall_late = overall_total - overall_on_time
    overall_rate = round(overall_on_time / overall_total * 100, 1) if overall_total > 0 else None

    by_dept_list = []
    for dept_name, data in sorted(by_dept.items()):
        t  = data["total"]
        ot = data["on_time"]
        by_dept_list.append({
            "dept_name": dept_name,
            "total":     t,
            "on_time":   ot,
            "late":      t - ot,
            "rate":      round(ot / t * 100, 1) if t > 0 else None,
        })

    return {
        "period":  f"{year:04d}-{month:02d}",
        "overall": {
            "total":   overall_total,
            "on_time": overall_on_time,
            "late":    overall_late,
            "rate":    overall_rate,
        },
        "by_dept": by_dept_list,
    }
