"""Dashboard API — KPI tổng hợp và pending counts cho sidebar badge"""
import sqlite3
from datetime import date, timedelta
from typing import FrozenSet
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from backend.database import get_db, _vn_now
from backend.core.deps import get_current_staff, TONG_HOP_CODES

router = APIRouter()


def _working_days_between(
    start_exclusive: date,
    end_inclusive: date,
    holiday_dates: FrozenSet[date],
    leave_dates: FrozenSet[date] = frozenset(),
) -> int:
    count = 0
    d = start_exclusive + timedelta(days=1)
    while d <= end_inclusive:
        if d.weekday() < 5 and d not in holiday_dates and d not in leave_dates:
            count += 1
        d += timedelta(days=1)
    return count


def _is_tong_hop(staff: dict, db: sqlite3.Connection) -> bool:
    dept_id = staff.get("department_id")
    if not dept_id:
        return False
    r = db.execute("SELECT code FROM departments WHERE id = ?", (dept_id,)).fetchone()
    return bool(r and r["code"].upper() in TONG_HOP_CODES)


@router.get("/pending-counts")
def pending_counts(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    role = current["role"]
    leaves_count = 0
    handovers_count = 0
    handovers_by_dept: list = []

    # ── Đơn phép đang chờ ──
    if _is_tong_hop(current, db) and role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        # PP/TP Tổng hợp: đếm cả KSV phòng mình + TH toàn trung tâm
        ksv_cnt = db.execute(
            "SELECT COUNT(*) FROM leave_records WHERE ksv_approver_id = ? AND status = 'pending_ksv'",
            (current["id"],),
        ).fetchone()[0] or 0
        th_cnt = db.execute(
            "SELECT COUNT(*) FROM leave_records WHERE status = 'pending_tong_hop'"
        ).fetchone()[0] or 0
        leaves_count = ksv_cnt + th_cnt

    elif role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        leaves_count = db.execute(
            "SELECT COUNT(*) FROM leave_records WHERE ksv_approver_id = ? AND status = 'pending_ksv'",
            (current["id"],),
        ).fetchone()[0] or 0

    elif _is_tong_hop(current, db):
        leaves_count = db.execute(
            "SELECT COUNT(*) FROM leave_records WHERE status = 'pending_tong_hop'"
        ).fetchone()[0] or 0

    elif role in ("giam_doc", "pho_giam_doc"):
        today = _vn_now().date()
        can_approve = role == "giam_doc" or db.execute(
            """SELECT id FROM delegation_records
               WHERE pho_giam_doc_id = ? AND is_active = 1
                 AND start_date <= ? AND end_date >= ?""",
            (current["id"], today.isoformat(), today.isoformat()),
        ).fetchone() is not None
        if can_approve:
            leaves_count = db.execute(
                "SELECT COUNT(*) FROM leave_records WHERE gd_approver_id = ? AND status = 'pending_gd'",
                (current["id"],),
            ).fetchone()[0] or 0

    # ── Chứng từ chờ xác nhận ──
    if role == "hau_kiem_vien":
        handovers_count = db.execute(
            "SELECT COUNT(*) FROM document_entries WHERE entry_status = 'pending_confirm'"
        ).fetchone()[0] or 0
        rows = db.execute(
            """SELECT d.name AS dept_name, COUNT(de.id) AS cnt
               FROM document_entries de
               JOIN handovers h ON de.handover_id = h.id
               JOIN departments d ON h.department_id = d.id
               WHERE de.entry_status = 'pending_confirm'
               GROUP BY d.name ORDER BY d.name"""
        ).fetchall()
        handovers_by_dept = [{"dept_name": r["dept_name"], "count": r["cnt"]} for r in rows]

    elif role == "chuyen_vien" and current.get("id"):
        handovers_count = db.execute(
            "SELECT COUNT(*) FROM document_entries WHERE entry_status = 'pending_confirm' AND entered_by_id = ?",
            (current["id"],),
        ).fetchone()[0] or 0
        rows = db.execute(
            """SELECT d.name AS dept_name, COUNT(de.id) AS cnt
               FROM document_entries de
               JOIN handovers h ON de.handover_id = h.id
               JOIN departments d ON h.department_id = d.id
               WHERE de.entry_status = 'pending_confirm' AND de.entered_by_id = ?
               GROUP BY d.name ORDER BY d.name""",
            (current["id"],),
        ).fetchall()
        handovers_by_dept = [{"dept_name": r["dept_name"], "count": r["cnt"]} for r in rows]

    return {"leaves": leaves_count, "handovers": handovers_count, "handovers_by_dept": handovers_by_dept}


@router.get("/leave-today")
def leave_today_stats(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    """Thống kê đơn nghỉ phép hôm nay (approved): tổng + theo phòng."""
    today = _vn_now().date().isoformat()

    # Lấy tất cả phòng có nhân viên
    depts = db.execute(
        """SELECT id, name, code FROM departments WHERE is_active=1
           ORDER BY CASE code
               WHEN 'BGD'     THEN 1
               WHEN 'PAYMENT' THEN 2
               WHEN 'NOSTRO'  THEN 3
               WHEN 'SWIFT'   THEN 4
               WHEN 'ACCT'    THEN 5
               WHEN 'KSNB'    THEN 6
               WHEN 'TH'      THEN 7
               ELSE 8 END"""
    ).fetchall()

    # Đếm người nghỉ theo phòng (approved, ngày nghỉ chứa hôm nay)
    leave_rows = db.execute(
        """SELECT s.department_id, COUNT(DISTINCT s.id) AS cnt
           FROM leave_records lr
           JOIN user_tttt s ON lr.staff_id = s.id
           WHERE lr.status = 'approved'
             AND lr.start_date <= ? AND lr.end_date >= ?
             AND s.department_id IS NOT NULL
           GROUP BY s.department_id""",
        (today, today),
    ).fetchall()
    dept_map = {r["department_id"]: r["cnt"] for r in leave_rows}

    total = sum(dept_map.values())
    by_dept = [
        {"dept_name": d["name"], "dept_code": d["code"], "count": dept_map.get(d["id"], 0)}
        for d in depts
    ]
    return {"total": total, "by_dept": by_dept, "date": today}


@router.get("/summary")
def dashboard_summary(
    year: int = Query(None),
    month: int = Query(None),
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    today = _vn_now().date()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    period_start = date(year, month, 1)
    period_end   = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    lookup_start = period_start - timedelta(days=35)

    # ── Ngày lễ ──
    holiday_rows = db.execute(
        "SELECT date FROM public_holidays WHERE date >= ? AND date < ?",
        (lookup_start.isoformat(), period_end.isoformat()),
    ).fetchall()
    holiday_dates: FrozenSet[date] = frozenset(
        date.fromisoformat(r["date"]) for r in holiday_rows
    )

    # ── Ngày nghỉ phép được duyệt ──
    leave_rows = db.execute(
        """SELECT staff_id, start_date, end_date FROM leave_records
           WHERE status = 'approved' AND end_date >= ? AND start_date < ?""",
        (lookup_start.isoformat(), period_end.isoformat()),
    ).fetchall()

    _raw_leave: dict = defaultdict(set)
    for lr in leave_rows:
        lv_start = date.fromisoformat(lr["start_date"])
        lv_end   = date.fromisoformat(lr["end_date"])
        d = max(lv_start, lookup_start)
        while d <= lv_end and d < period_end:
            if d.weekday() < 5:
                _raw_leave[lr["staff_id"]].add(d)
            d += timedelta(days=1)
    staff_leave: dict = {sid: frozenset(dates) for sid, dates in _raw_leave.items()}

    # ── Entries trong period ──
    rows = db.execute(
        """SELECT de.transaction_date, h.handover_date, h.received_by_id, d.name AS dept_name
           FROM document_entries de
           JOIN handovers h ON de.handover_id = h.id
           JOIN departments d ON h.department_id = d.id
           WHERE h.handover_date >= ? AND h.handover_date < ?""",
        (period_start.isoformat(), period_end.isoformat()),
    ).fetchall()

    by_dept: dict = {}
    overall_total = 0
    overall_on_time = 0

    for row in rows:
        tx_date      = date.fromisoformat(row["transaction_date"])
        ho_date      = date.fromisoformat(row["handover_date"])
        recv_id      = row["received_by_id"]
        dept_name    = row["dept_name"]
        receiver_leave = staff_leave.get(recv_id, frozenset()) if recv_id else frozenset()
        working_days   = _working_days_between(tx_date, ho_date, holiday_dates, receiver_leave)
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
