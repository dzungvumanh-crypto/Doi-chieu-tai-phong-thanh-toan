"""Dashboard API — KPI tổng hợp và pending counts cho sidebar badge"""
import sqlite3
from fastapi import APIRouter, Depends, Query
from backend.database import get_db, _vn_now
from backend.core.deps import get_current_staff, TONG_HOP_CODES
from backend.services.handover_report_service import compute_period, SUBMIT_ACTIONS

router = APIRouter()


def _is_tong_hop(staff: dict, db: sqlite3.Connection) -> bool:
    dept_id = staff.get("department_id")
    if not dept_id:
        return False
    r = db.execute("SELECT code FROM departments WHERE id = ?", (dept_id,)).fetchone()
    return bool(r and r["code"].upper() in TONG_HOP_CODES)


# ── Bộ lọc "việc đang chờ chính người này xử lý" ──────────────────────────────
# Nguồn sự thật duy nhất cho cả /pending-counts và /pending-items. Tách ra vì nếu
# viết SQL hai lần, số trên sidebar và danh sách chi tiết sẽ lệch nhau khi một
# bên được sửa mà bên kia quên.
# Trả (mệnh đề WHERE, tham số) — None nghĩa là vai trò này không có việc loại đó.

def _leave_filter(current: dict, db: sqlite3.Connection) -> tuple[str, list] | None:
    role = current["role"]
    is_th = _is_tong_hop(current, db)

    if is_th and role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        # PP/TP Tổng hợp: vừa duyệt KSV phòng mình, vừa gác cửa TH toàn trung tâm
        return ("((lr.ksv_approver_id = ? AND lr.status = 'pending_ksv')"
                " OR lr.status = 'pending_tong_hop')", [current["id"]])

    if role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        return ("lr.ksv_approver_id = ? AND lr.status = 'pending_ksv'", [current["id"]])

    if is_th:
        return ("lr.status = 'pending_tong_hop'", [])

    if role in ("giam_doc", "pho_giam_doc"):
        today = _vn_now().date().isoformat()
        can_approve = role == "giam_doc" or db.execute(
            """SELECT id FROM delegation_records
               WHERE pho_giam_doc_id = ? AND is_active = 1
                 AND start_date <= ? AND end_date >= ?""",
            (current["id"], today, today),
        ).fetchone() is not None
        if can_approve:
            return ("lr.gd_approver_id = ? AND lr.status = 'pending_gd'", [current["id"]])

    return None


def _handover_filter(current: dict) -> tuple[str, list] | None:
    role = current["role"]
    if role == "hau_kiem_vien":
        return ("de.entry_status = 'pending_confirm'", [])
    if role == "chuyen_vien" and current.get("id"):
        return ("de.entry_status = 'pending_confirm' AND de.entered_by_id = ?", [current["id"]])
    return None


@router.get("/pending-counts")
def pending_counts(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    leaves_count = 0
    handovers_count = 0
    handovers_by_dept: list = []

    # ── Đơn phép đang chờ ──
    lf = _leave_filter(current, db)
    if lf:
        leaves_count = db.execute(
            f"SELECT COUNT(*) FROM leave_records lr WHERE {lf[0]}", lf[1]
        ).fetchone()[0] or 0

    # ── Chứng từ chờ xác nhận ──
    hf = _handover_filter(current)
    if hf:
        handovers_count = db.execute(
            f"SELECT COUNT(*) FROM document_entries de WHERE {hf[0]}", hf[1]
        ).fetchone()[0] or 0
        rows = db.execute(
            f"""SELECT d.name AS dept_name, COUNT(de.id) AS cnt
                FROM document_entries de
                JOIN handovers h ON de.handover_id = h.id
                JOIN departments d ON h.department_id = d.id
                WHERE {hf[0]}
                GROUP BY d.name ORDER BY d.name""",
            hf[1],
        ).fetchall()
        handovers_by_dept = [{"dept_name": r["dept_name"], "count": r["cnt"]} for r in rows]

    return {"leaves": leaves_count, "handovers": handovers_count, "handovers_by_dept": handovers_by_dept}


# Trần cứng cho danh sách chi tiết. Màn hình theo dõi không phải chỗ duyệt hàng trăm
# việc — quá ngưỡng thì vào thẳng màn hình nghiệp vụ, ở đó có bộ lọc và phân trang.
_ITEMS_LIMIT = 200


# Ngày nộp thật lấy từ log, KHÔNG lấy `handovers.handover_date`: nhập qua lưới thì
# cột đó được gán đúng bằng transaction_date nên luôn trùng ngày chứng từ.
# Cùng nguồn với handover_report_service để hai màn hình không nói hai con số.
_SUBMIT_AT_SQL = f"""(SELECT MIN(ecl.timestamp) FROM entry_change_logs ecl
                       WHERE ecl.entry_id = de.id
                         AND ecl.action IN ({','.join('?' * len(SUBMIT_ACTIONS))}))"""


def _iso_date(raw) -> str | None:
    """'2026-08-04 13:45:08.27' → '2026-08-04'. Không có log nộp → None."""
    s = str(raw or "")[:10]
    return s if len(s) == 10 else None


def _split_iso(iso: str) -> tuple:
    """'2026-08-01' → (2026, 8, 1). Chuỗi lạ → (None, None, None)."""
    parts = (iso or "").split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return (None, None, None)
    return tuple(int(p) for p in parts)


@router.get("/pending-items")
def pending_items(
    current: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    """Chi tiết việc đang chờ + tham số để frontend dựng link tới màn hình thao tác."""
    leaves: list = []
    handovers: list = []

    # ── Đơn phép ──
    lf = _leave_filter(current, db)
    if lf:
        rows = db.execute(
            f"""SELECT lr.id, lr.start_date, lr.end_date, lr.leave_type, lr.status,
                       lr.reason, lr.created_at,
                       s.full_name    AS staff_name,
                       s.ipcas_code   AS staff_code,
                       d.name         AS dept_name,
                       ksv.full_name  AS ksv_name
                FROM leave_records lr
                JOIN user_tttt s ON lr.staff_id = s.id
                LEFT JOIN departments d ON s.department_id = d.id
                LEFT JOIN user_tttt ksv ON lr.ksv_approver_id = ksv.id
                WHERE {lf[0]}
                ORDER BY lr.start_date ASC, lr.id ASC
                LIMIT {_ITEMS_LIMIT}""",
            lf[1],
        ).fetchall()
        leaves = [
            {
                "id":         r["id"],
                "staff_name": r["staff_name"],
                "staff_code": r["staff_code"] or "",
                "dept_name":  r["dept_name"] or "",
                "start_date": r["start_date"],
                "end_date":   r["end_date"],
                "leave_type": r["leave_type"],
                "status":     r["status"],
                "reason":     r["reason"] or "",
                "ksv_name":   r["ksv_name"] or "",
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Chứng từ ──
    # Trả từng chứng từ một (không gộp) — màn hình theo dõi cần biết chứng từ của ai,
    # ai nộp, ngày nào. entry_id là chìa để nhảy đúng ô trên lưới (input mang data-eid).
    hf = _handover_filter(current)
    if hf:
        rows = db.execute(
            f"""SELECT de.id                AS entry_id,
                       de.transaction_date  AS transaction_date,
                       de.sheet_count       AS sheet_count,
                       de.notes             AS notes,
                       {_SUBMIT_AT_SQL}     AS submit_at,
                       d.id                 AS dept_id,
                       d.name               AS dept_name,
                       owner.full_name      AS staff_name,
                       owner.ipcas_code     AS staff_code,
                       entered.full_name    AS entered_by_name
                FROM document_entries de
                JOIN handovers h        ON de.handover_id = h.id
                JOIN departments d      ON h.department_id = d.id
                LEFT JOIN user_tttt owner   ON de.staff_id = owner.id
                LEFT JOIN user_tttt entered ON de.entered_by_id = entered.id
                WHERE {hf[0]}
                ORDER BY de.transaction_date DESC, d.name, owner.ipcas_code
                LIMIT {_ITEMS_LIMIT}""",
            # Tham số subquery trong SELECT đứng TRƯỚC tham số của WHERE
            [*SUBMIT_ACTIONS, *hf[1]],
        ).fetchall()
        for r in rows:
            y, m, dd = _split_iso(r["transaction_date"])
            handovers.append({
                "entry_id":         r["entry_id"],
                "staff_name":       r["staff_name"] or "",
                "staff_code":       r["staff_code"] or "",
                "dept_id":          r["dept_id"],
                "dept_name":        r["dept_name"],
                "sheet_count":      r["sheet_count"],
                "entered_by_name":  r["entered_by_name"] or "",
                "transaction_date": r["transaction_date"],
                "submit_date":      _iso_date(r["submit_at"]),
                "notes":            r["notes"] or "",
                "year":             y,
                "month":            m,
                "day":              dd,
            })

    return {"leaves": leaves, "handovers": handovers}


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
