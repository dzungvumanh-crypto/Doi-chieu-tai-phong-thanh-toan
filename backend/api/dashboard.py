"""Dashboard API — KPI tổng hợp và pending counts cho sidebar badge"""
import sqlite3
from fastapi import APIRouter, Depends, Query
from backend.database import get_db, _vn_now
from backend.core.deps import get_current_staff, TONG_HOP_CODES
from backend.services.handover_report_service import compute_period

router = APIRouter()


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
    """KPI đúng hạn — dùng chung logic với Báo cáo bàn giao chứng từ."""
    today = _vn_now().date()
    result = compute_period(db, year or today.year, month or today.month)
    return {
        "period":         result["period"],
        "overall":        result["overall"],
        "by_dept":        result["by_dept"],
        "no_submit_date": result["no_submit_date"],
    }
