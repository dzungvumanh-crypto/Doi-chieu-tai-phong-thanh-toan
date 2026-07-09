"""Quản lý nghỉ phép — đăng ký, phê duyệt, tải phiếu"""
import io
import json
import os
import sqlite3
from datetime import date, timedelta
from typing import FrozenSet, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.core.deps import TONG_HOP_CODES, get_current_staff, require_feature
from backend.core.enums import LeaveStatus
from backend.database import get_db, _vn_now, compute_annual_leave, compute_carry_over
from backend.schemas.leaves import (
    LeaveCreate, LeaveReview, TongHopReview,
    DirectLeaveCreate, RecallCreate, LeaveQuotaUpsert,
)

router = APIRouter()

LEAVE_TYPE_LABELS = {
    "bat_buoc":  "Nghỉ phép bắt buộc",
    "annual":    "Nghỉ phép năm",
    "thai_san":  "Nghỉ thai sản",
    "bao_hiem":  "Nghỉ bảo hiểm",
    "other":     "Khác",
    # Legacy types (giữ để tương thích với data cũ)
    "sick":      "Nghỉ ốm",
    "personal":  "Nghỉ việc riêng",
    "dot_xuat":  "Nghỉ đột xuất",
}

_VALID_LEAVE_TYPES = frozenset(LEAVE_TYPE_LABELS.keys())
# Các loại nghỉ không tính vào/trừ hạn mức phép năm
_NO_QUOTA_TYPES = frozenset({"thai_san", "bao_hiem"})

ACTION_LABELS = {
    "create":         ("Nộp đơn",            "blue"),
    "ksv_approve":    ("KSV phê duyệt",      "green"),
    "ksv_reject":     ("KSV từ chối",        "red"),
    "th_forward":     ("TH chuyển GĐ",       "blue"),
    "th_reject":      ("TH từ chối",         "red"),
    "gd_approve":     ("GĐ phê duyệt",       "green"),
    "gd_reject":      ("GĐ từ chối",         "red"),
    "resubmit":       ("Nộp lại",            "orange"),
    "cancel":         ("Hủy đơn",            "grey"),
    "direct_create":  ("Khai báo hộ",        "purple"),
    "recall_request": ("Yêu cầu rút đơn",    "orange"),
    "recall_approve": ("Xác nhận rút đơn",   "grey"),
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
_HIGH_ROLES = frozenset(("giam_doc", "pho_giam_doc", "admin", "truong_phong"))


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
    days: Optional[int] = None,
):
    """Cập nhật status và điều chỉnh used_leave_days (idempotent)."""
    if days is None:
        rec = db.execute("SELECT spread_dates, leave_type FROM leave_records WHERE id=?", (leave_id,)).fetchone()
        if rec and rec["spread_dates"]:
            days = len(json.loads(rec["spread_dates"]))
        else:
            days = calculate_leave_days(start, end, holiday_dates)
        leave_type = rec["leave_type"] if rec else None
    else:
        rec2 = db.execute("SELECT leave_type FROM leave_records WHERE id=?", (leave_id,)).fetchone()
        leave_type = rec2["leave_type"] if rec2 else None

    if leave_type not in _NO_QUOTA_TYPES:
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
    # KSV phải cùng phòng (trừ hau_kiem_vien được duyệt cross-department)
    if ksv["role"] not in ("hau_kiem_vien", "admin"):
        staff_dept = current.get("department_id")
        ksv_dept   = ksv["department_id"]
        if staff_dept and ksv_dept and staff_dept != ksv_dept:
            raise HTTPException(400, "Người phê duyệt phải thuộc cùng phòng ban với người nộp đơn")
    return dict(ksv)


def _leave_to_out(leave_id: int, db: sqlite3.Connection) -> dict:
    r = db.execute(
        """SELECT lr.*,
                  s.full_name AS staff_name, s.department_id AS s_dept_id,
                  kv.full_name AS ksv_name,
                  th.full_name AS th_name,
                  gd.full_name AS gd_approver_name, gd.role AS gd_role,
                  d.name AS dept_name,
                  db_user.full_name AS declarer_name
           FROM leave_records lr
           LEFT JOIN user_tttt s       ON lr.staff_id             = s.id
           LEFT JOIN user_tttt kv      ON lr.ksv_approver_id      = kv.id
           LEFT JOIN user_tttt th      ON lr.tong_hop_approver_id = th.id
           LEFT JOIN user_tttt gd      ON lr.gd_approver_id       = gd.id
           LEFT JOIN departments d     ON s.department_id          = d.id
           LEFT JOIN user_tttt db_user ON lr.direct_by             = db_user.id
           WHERE lr.id = ?""",
        (leave_id,),
    ).fetchone()
    if not r:
        return {}

    start = date.fromisoformat(r["start_date"])
    end   = date.fromisoformat(r["end_date"])
    _h    = _load_holidays(db, start, end)
    _days = len(json.loads(r["spread_dates"])) if r["spread_dates"] else calculate_leave_days(start, end, _h)

    return {
        "id":                     r["id"],
        "staff_id":               r["staff_id"],
        "staff_name":             r["staff_name"] or "",
        "department_name":        r["dept_name"],
        "start_date":             r["start_date"],
        "end_date":               r["end_date"],
        "leave_days":             _days,
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
        "is_direct":              bool(r["is_direct"]) if r["is_direct"] is not None else False,
        "declarer_name":          r["declarer_name"] or "",
        "spread_dates":           json.loads(r["spread_dates"]) if r["spread_dates"] else None,
        "recall_reason":          r["recall_reason"],
        "created_at":             r["created_at"],
        "rejected_step":          (
            "GĐ"  if r["status"] == "rejected" and r["gd_approved_at"]
            else "TH"  if r["status"] == "rejected" and r["tong_hop_approved_at"]
            else "KSV" if r["status"] == "rejected"
            else None
        ),
        "is_resubmitted": bool(db.execute(
            "SELECT 1 FROM leave_action_logs WHERE leave_id=? AND action='resubmit' LIMIT 1",
            (leave_id,)
        ).fetchone()),
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
    dept_id = current.get("department_id")
    if dept_id:
        # Chỉ lấy KSV cùng phòng + hậu kiểm viên (cross-department)
        rows = db.execute(
            """SELECT id, full_name, role FROM user_tttt
               WHERE is_active = 1 AND id != ?
                 AND (
                   (role IN ('truong_phong','pho_phong') AND department_id = ?)
                   OR role = 'hau_kiem_vien'
                 )
               ORDER BY full_name""",
            (current["id"], dept_id),
        ).fetchall()
    else:
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
    if current.get("role") == "admin":
        raise HTTPException(403, "Admin không tham gia quy trình nghỉ phép")
    if body.leave_type not in _VALID_LEAVE_TYPES:
        raise HTTPException(400, f"Loại nghỉ phép không hợp lệ: {body.leave_type}")

    # ── Xử lý spread_dates (nghỉ ngày lẻ không liên tục) ──
    if body.spread_dates:
        spread = sorted(set(body.spread_dates))
        if len(spread) < 1:
            raise HTTPException(400, "spread_dates phải có ít nhất 1 ngày")
        eff_start = date.fromisoformat(spread[0])
        eff_end   = date.fromisoformat(spread[-1])
        leave_days = len(spread)
        spread_json = json.dumps(spread)
        _h = _load_holidays(db, eff_start, eff_end)
    else:
        if body.end_date < body.start_date:
            raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")
        eff_start   = body.start_date
        eff_end     = body.end_date
        _h          = _load_holidays(db, eff_start, eff_end)
        leave_days  = calculate_leave_days(eff_start, eff_end, _h)
        spread_json = None

    if body.leave_type == "annual":
        if eff_start < _vn_now().date():
            raise HTTPException(400, "Nghỉ phép năm phải từ hôm nay trở đi")

    # Kiểm tra hạn mức (không áp dụng cho bat_buoc, thai_san, bao_hiem)
    if body.leave_type not in _NO_QUOTA_TYPES and body.leave_type != "bat_buoc":
        ref_year  = eff_start.year
        carry_eff = compute_carry_over(current["id"], ref_year, db,
                                       effective=True, ref_date=eff_start)
        quota     = (current.get("annual_leave_days") or 12)
        used_r2   = db.execute(
            """SELECT COALESCE(SUM(
                   CASE WHEN spread_dates IS NOT NULL AND spread_dates != ''
                        THEN json_array_length(spread_dates)
                        ELSE (julianday(end_date) - julianday(start_date) + 1)
                   END), 0)
               FROM leave_records
               WHERE staff_id=? AND status IN ('approved','pending_ksv','pending_tong_hop','pending_gd')
                 AND strftime('%Y', start_date)=?
                 AND leave_type NOT IN ('thai_san','bao_hiem')""",
            (current["id"], str(ref_year))
        ).fetchone()
        used_total = float(used_r2[0]) if used_r2 else 0.0
        remaining  = quota + carry_eff - used_total
        if leave_days > remaining:
            raise HTTPException(400, f"Vượt quá số ngày phép còn lại ({remaining:.0f} ngày)")

    if body.leave_type == "bat_buoc" and leave_days < 5:
        raise HTTPException(400, "Nghỉ phép bắt buộc phải từ 5 ngày làm việc trở lên")

    # Kiểm tra trùng ngày theo spread_dates thực tế (không dùng envelope khi có spread)
    if body.spread_dates:
        _existing = db.execute(
            """SELECT start_date, end_date, spread_dates FROM leave_records
               WHERE staff_id=? AND status NOT IN ('rejected','cancelled')""",
            (current["id"],)
        ).fetchall()
        _new_days = set(spread)
        for _el in _existing:
            if _el["spread_dates"]:
                if _new_days & set(json.loads(_el["spread_dates"])):
                    raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")
            elif any(_el["start_date"] <= d <= _el["end_date"] for d in spread):
                raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")
    else:
        if db.execute(
            """SELECT id FROM leave_records WHERE staff_id=? AND status NOT IN ('rejected','cancelled')
               AND start_date<=? AND end_date>=?""",
            (current["id"], eff_end.isoformat(), eff_start.isoformat())
        ).fetchone():
            raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")

    if current["role"] in _HIGH_ROLES:
        initial_status  = LeaveStatus.PENDING_TONG_HOP
        ksv_approver_id = None
    else:
        ksv = _validate_ksv(body.ksv_approver_id, current, db)
        initial_status  = LeaveStatus.PENDING_KSV
        ksv_approver_id = ksv["id"]

    # Nếu user chọn trước Ban lãnh đạo, validate
    gd_approver_id = None
    if body.gd_approver_id:
        gd_staff = db.execute(
            "SELECT id, role FROM user_tttt WHERE id=? AND is_active=1", (body.gd_approver_id,)
        ).fetchone()
        if gd_staff and gd_staff["role"] in ("giam_doc", "pho_giam_doc"):
            gd_approver_id = gd_staff["id"]

    cur = db.execute(
        """INSERT INTO leave_records
               (staff_id, start_date, end_date, leave_type, reason, status,
                ksv_approver_id, gd_approver_id, spread_dates, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (current["id"], eff_start.isoformat(), eff_end.isoformat(),
         body.leave_type, body.reason, initial_status, ksv_approver_id,
         gd_approver_id, spread_json, str(_vn_now()), str(_vn_now())),
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
            if role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
                # PP/TP Tổng hợp: duyệt bước TH cho toàn trung tâm
                # VÀ duyệt bước KSV cho nhân viên phòng mình
                clauses.append(
                    "(status = 'pending_tong_hop' OR "
                    "(ksv_approver_id = ? AND status = 'pending_ksv'))"
                )
                params.append(current["id"])
            else:
                clauses.append("status = 'pending_tong_hop'")
        elif role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            clauses.append("ksv_approver_id = ? AND status = 'pending_ksv'")
            params.append(current["id"])
        else:
            return []

    elif scope == "declared":
        # Người khai báo hộ xem các đơn mình đã khai báo
        clauses.append("direct_by = ?")
        params.append(current["id"])

    elif scope == "dept":
        # Phó phòng / Trưởng phòng xem tất cả đơn của nhân viên trong phòng mình
        if role not in ("truong_phong", "pho_phong", "hau_kiem_vien", "admin"):
            raise HTTPException(403, "Không có quyền xem đơn phòng")
        dept_id = current.get("department_id")
        if not dept_id:
            return []
        clauses.append("staff_id IN (SELECT id FROM user_tttt WHERE department_id = ? AND is_active = 1)")
        params.append(dept_id)

    elif scope == "all":
        if role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
            if not _is_tong_hop_staff(current, db):
                raise HTTPException(403, "Không có quyền xem tất cả đơn")

    else:
        raise HTTPException(400, "scope phải là mine | pending | declared | dept | all")

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
    ids: str = "",        # danh sách id cách nhau bởi dấu phẩy, ưu tiên hơn scope
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    role = current["role"]
    clauses: list = []
    params: list  = []

    # Nếu có danh sách ID cụ thể → xuất đúng những dòng đó
    if ids:
        id_list = [int(i.strip()) for i in ids.split(",") if i.strip().isdigit()]
        if not id_list:
            raise HTTPException(400, "ids không hợp lệ")
        placeholders = ",".join("?" * len(id_list))
        clauses.append(f"lr.id IN ({placeholders})")
        params.extend(id_list)
    elif scope == "mine":
        clauses.append("lr.staff_id = ?")
        params.append(current["id"])
    elif scope == "all":
        if role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
            if not _is_tong_hop_staff(current, db):
                raise HTTPException(403, "Không có quyền xuất tất cả đơn")
    elif scope == "pending":
        if _is_tong_hop_staff(current, db) and role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            clauses.append(
                "(lr.status = 'pending_tong_hop' OR "
                "(lr.ksv_approver_id = ? AND lr.status = 'pending_ksv'))"
            )
            params.append(current["id"])
        elif role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
            clauses.append("lr.ksv_approver_id = ? AND lr.status = 'pending_ksv'")
            params.append(current["id"])
        elif _is_tong_hop_staff(current, db):
            clauses.append("lr.status = 'pending_tong_hop'")
        elif role in ("giam_doc", "pho_giam_doc", "admin"):
            clauses.append("lr.status = 'pending_gd'")
        else:
            clauses.append("1=0")
    elif scope in ("dept", "declared"):
        clauses.append("1=1")  # allow all, scope already handled by client
    else:
        raise HTTPException(400, "scope phải là mine | pending | all | dept | declared")

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
                "Ngày nghỉ", "Số ngày", "Trạng thái",
                "KSV duyệt", "Phòng Tổng hợp", "GĐ/PGĐ", "Ngày tạo"]
    widths   = [6, 25, 20, 18, 40, 9, 18, 22, 22, 22, 14]
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
        # Ngày nghỉ: liệt kê từng ngày nếu không liên nhau
        import json as _j
        if lv["spread_dates"]:
            try:
                spread = _j.loads(lv["spread_dates"])
                dates_str = ", ".join(date.fromisoformat(d).strftime("%d/%m/%Y") for d in sorted(spread))
            except Exception:
                dates_str = s_date.strftime("%d/%m/%Y")
        else:
            dates_str = f"{s_date.strftime('%d/%m/%Y')} → {e_date.strftime('%d/%m/%Y')}"

        row_data = [
            idx,
            lv["staff_name"] or "",
            lv["dept_name"] or "",
            LEAVE_TYPE_LABELS.get(lv["leave_type"] or "", ""),
            dates_str,
            days,
            _LEAVE_STATUS_VN.get(lv["status"] or "", lv["status"] or ""),
            lv["ksv_name"] or "",
            lv["th_name"]  or "",
            gd_name,
            created,
        ]
        ws.append(row_data)
        # Wrap text cho cột Ngày nghỉ (cột E = index 5)
        ws.cell(ws.max_row, 5).alignment = Alignment(wrap_text=True, horizontal="left")

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


@router.delete("/{leave_id}")
def delete_leave(
    leave_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    """Xóa đơn khai báo hộ — chỉ người khai báo hoặc admin mới được xóa."""
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn")
    if not leave["is_direct"]:
        raise HTTPException(403, "Chỉ có thể xóa đơn khai báo hộ")
    if leave["direct_by"] != current["id"] and current["role"] != "admin":
        raise HTTPException(403, "Không có quyền xóa đơn này")
    # Hoàn trả used_leave_days nếu đơn đã approved
    if leave["status"] == "approved":
        if leave["spread_dates"]:
            days = len(json.loads(leave["spread_dates"]))
        else:
            from datetime import date as _d
            s = _d.fromisoformat(leave["start_date"])
            e = _d.fromisoformat(leave["end_date"])
            _h = _load_holidays(db, s, e)
            days = calculate_leave_days(s, e, _h)
        db.execute(
            "UPDATE user_tttt SET used_leave_days = MAX(0, COALESCE(used_leave_days,0) - ?) WHERE id = ?",
            (days, leave["staff_id"]),
        )
    db.execute("DELETE FROM leave_action_logs WHERE leave_id = ?", (leave_id,))
    db.execute("DELETE FROM leave_records WHERE id = ?", (leave_id,))
    db.commit()
    return {"message": "Đã xóa đơn khai báo hộ"}


@router.put("/{leave_id}/ksv-review")
def ksv_review(
    leave_id: int,
    body: LeaveReview,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.approve_ksv")),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["status"] != LeaveStatus.PENDING_KSV:
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave['status']}'")
    if leave["ksv_approver_id"] != current["id"] and current["role"] != "admin":
        raise HTTPException(403, "Bạn không phải người được chỉ định duyệt bước này")
    if body.action == "reject" and not body.comment:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    old = leave["status"]
    new_status = LeaveStatus.PENDING_TONG_HOP if body.action == "approve" else LeaveStatus.REJECTED
    # Nếu admin thực hiện: ghi lại chính admin là người duyệt bước này
    if current["role"] == "admin":
        db.execute("UPDATE leave_records SET ksv_approver_id=? WHERE id=?", (current["id"], leave_id))
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
    if not _is_tong_hop_staff(current, db) and current["role"] != "admin":
        raise HTTPException(403, "Chỉ nhân viên Phòng Tổng hợp hoặc Admin mới thực hiện được")
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["status"] != LeaveStatus.PENDING_TONG_HOP:
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave['status']}'")
    if leave["recall_reason"]:
        raise HTTPException(400, "Đây là yêu cầu rút đơn — dùng /recall-approve để xử lý")
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
    current: dict = Depends(require_feature("leaves.approve_gd")),
):
    leave = db.execute("SELECT * FROM leave_records WHERE id = ?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn nghỉ phép")
    if leave["status"] != LeaveStatus.PENDING_GD:
        raise HTTPException(400, f"Đơn đang ở trạng thái '{leave['status']}'")
    if current["role"] != "admin":
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

    if body.spread_dates:
        spread = sorted(set(body.spread_dates))
        eff_start  = date.fromisoformat(spread[0])
        eff_end    = date.fromisoformat(spread[-1])
        leave_days = len(spread)
        spread_json = json.dumps(spread)
        _h = _load_holidays(db, eff_start, eff_end)
    else:
        if body.end_date < body.start_date:
            raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")
        eff_start   = body.start_date
        eff_end     = body.end_date
        _h          = _load_holidays(db, eff_start, eff_end)
        leave_days  = calculate_leave_days(eff_start, eff_end, _h)
        spread_json = None

    if body.leave_type == "annual":
        remaining = (current.get("annual_leave_days") or 12) - (current.get("used_leave_days") or 0)
        if leave_days > remaining:
            raise HTTPException(400, f"Vượt quá số ngày phép còn lại ({remaining} ngày)")

    # Kiểm tra trùng ngày theo spread_dates thực tế
    if body.spread_dates:
        _existing = db.execute(
            """SELECT start_date, end_date, spread_dates FROM leave_records
               WHERE staff_id=? AND id!=? AND status NOT IN ('rejected','cancelled')""",
            (current["id"], leave_id)
        ).fetchall()
        _new_days = set(spread)
        for _el in _existing:
            if _el["spread_dates"]:
                if _new_days & set(json.loads(_el["spread_dates"])):
                    raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")
            elif any(_el["start_date"] <= d <= _el["end_date"] for d in spread):
                raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")
    else:
        if db.execute(
            """SELECT id FROM leave_records WHERE staff_id=? AND id!=? AND status NOT IN ('rejected','cancelled')
               AND start_date<=? AND end_date>=?""",
            (current["id"], leave_id, eff_end.isoformat(), eff_start.isoformat())
        ).fetchone():
            raise HTTPException(409, "Khoảng ngày nghỉ bị trùng với đơn hiện có")

    if current["role"] in _HIGH_ROLES:
        new_status      = LeaveStatus.PENDING_TONG_HOP
        ksv_approver_id = None
    else:
        ksv = _validate_ksv(body.ksv_approver_id, current, db)
        new_status      = LeaveStatus.PENDING_KSV
        ksv_approver_id = ksv["id"]

    # Validate và lưu GĐ/PGĐ approver nếu người dùng chọn
    new_gd_approver_id = None
    if body.gd_approver_id:
        gd_row = db.execute(
            "SELECT id FROM user_tttt WHERE id=? AND role IN ('giam_doc','pho_giam_doc') AND is_active=1",
            (body.gd_approver_id,)
        ).fetchone()
        if gd_row:
            new_gd_approver_id = gd_row["id"]

    old = leave["status"]
    _log_action(db, leave_id, current["id"], "resubmit", None, old, new_status)

    db.execute(
        """UPDATE leave_records SET
               ksv_approver_id=?, ksv_approved_at=NULL, ksv_comment=NULL,
               tong_hop_approver_id=NULL, tong_hop_approved_at=NULL, tong_hop_comment=NULL,
               gd_approver_id=?, gd_approved_at=NULL, gd_comment=NULL,
               leave_type=?, start_date=?, end_date=?, reason=?, spread_dates=?
           WHERE id=?""",
        (ksv_approver_id, new_gd_approver_id, body.leave_type, eff_start.isoformat(),
         eff_end.isoformat(), body.reason, spread_json, leave_id),
    )
    _apply_status_transition(leave_id, old, new_status, eff_start, eff_end, leave["staff_id"], _h, db)
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
    if leave["status"] == LeaveStatus.CANCELLED:
        raise HTTPException(400, "Đơn đã được hủy trước đó")

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

_TPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "templates", "Phòng Tổng hợp", "Nghỉ phép",
)
_TPL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "templates", "don_xin_nghi_phep_tpl.docx",
)

def _pick_template(staff_role: str) -> str:
    """Chọn file docx theo role. Fallback về template gốc nếu chưa có."""
    _map = {
        "chuyen_vien":   "don_xin_nghi_phep_nv.docx",
        "pho_phong":     "don_xin_nghi_phep_tp.docx",
        "truong_phong":  "don_xin_nghi_phep_tp.docx",
        "giam_doc":      "don_xin_nghi_phep_gd.docx",
        "pho_giam_doc":  "don_xin_nghi_phep_gd.docx",
        "hau_kiem_vien": "don_xin_nghi_phep_tp.docx",
        "admin":         "don_xin_nghi_phep_tp.docx",
    }
    fname = _map.get(staff_role or "", "don_xin_nghi_phep_tp.docx")
    path  = os.path.join(_TPL_DIR, fname)
    return path if os.path.exists(path) else _TPL_PATH


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
                  s.join_industry_date,
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

    tpl_path = _pick_template(r["staff_role"])
    if not os.path.exists(tpl_path):
        raise HTTPException(500, "Chưa có template đơn nghỉ phép")

    start = date.fromisoformat(r["start_date"])
    end   = date.fromisoformat(r["end_date"])
    now   = _vn_now()
    _h    = _load_holidays(db, start, end)

    leave_days = len(json.loads(r["spread_dates"])) if r["spread_dates"] else calculate_leave_days(start, end, _h)
    tong_phep      = compute_annual_leave(r["join_industry_date"], start.year) if r["join_industry_date"] else (r["annual_leave_days"] or 12)
    carry_original = compute_carry_over(r["staff_id"], start.year, db, effective=False)
    # Carryover hiệu lực theo ngày bắt đầu của đơn (Q1 → có carryover, sau Q1 → 0)
    carry_eff_doc  = compute_carry_over(r["staff_id"], start.year, db, effective=True, ref_date=start)
    # Số ngày đã nghỉ TRONG CÙNG NĂM (trừ đơn hiện tại) — tính từ leave_records theo năm
    _prev_rows = db.execute(
        """SELECT start_date, end_date, spread_dates FROM leave_records
           WHERE staff_id=? AND status='approved' AND id!=?
             AND strftime('%Y', start_date)=?""",
        (r["staff_id"], leave_id, str(start.year)),
    ).fetchall()
    _year_start = date(start.year, 1, 1)
    _year_end   = date(start.year, 12, 31)
    _h_year     = _load_holidays(db, _year_start, _year_end)
    da_nghi = 0.0
    for _pr in _prev_rows:
        if _pr["spread_dates"]:
            da_nghi += len(json.loads(_pr["spread_dates"]))
        else:
            _s = date.fromisoformat(_pr["start_date"])
            _e = date.fromisoformat(_pr["end_date"])
            da_nghi += calculate_leave_days(_s, _e, _h_year)
    con_lai = max(0.0, tong_phep + carry_eff_doc - da_nghi - leave_days)

    # ── Biến 2-năm cho trường hợp có ngày dư ──
    has_carryover   = carry_eff_doc > 0
    carryover_used  = min(float(carry_eff_doc), float(leave_days))
    new_year_days   = leave_days - carryover_used
    if has_carryover:
        _prev_year = start.year - 1
        _q_prev = db.execute(
            "SELECT quota_days FROM leave_quotas WHERE staff_id=? AND year=?",
            (r["staff_id"], _prev_year),
        ).fetchone()
        tong_so_phep_prev = float(_q_prev["quota_days"]) if _q_prev else float(
            compute_annual_leave(r["join_industry_date"], _prev_year) if r["join_industry_date"] else 12
        )
        _prev_year_rows = db.execute(
            """SELECT start_date, end_date, spread_dates FROM leave_records
               WHERE staff_id=? AND status='approved'
                 AND strftime('%Y', start_date)=?""",
            (r["staff_id"], str(_prev_year)),
        ).fetchall()
        _h_prev = _load_holidays(db, date(_prev_year, 1, 1), date(_prev_year, 12, 31))
        da_nghi_prev = 0.0
        for _ppr in _prev_year_rows:
            if _ppr["spread_dates"]:
                da_nghi_prev += len(json.loads(_ppr["spread_dates"]))
            else:
                _s2 = date.fromisoformat(_ppr["start_date"])
                _e2 = date.fromisoformat(_ppr["end_date"])
                da_nghi_prev += calculate_leave_days(_s2, _e2, _h_prev)
        con_lai_prev = max(0.0, tong_so_phep_prev - da_nghi_prev - carryover_used)
        con_lai_cur  = max(0.0, tong_phep - da_nghi - new_year_days)
    else:
        _prev_year = start.year - 1
        tong_so_phep_prev = 0.0
        da_nghi_prev = 0.0
        con_lai_prev = 0.0
        con_lai_cur  = con_lai

    # Tên GĐ/PGĐ
    gd_name = r["gd_approver_name"] or ""

    # Tên phòng ngắn (bỏ tiền tố "Phòng ")
    dept_raw  = r["dept_name"] or ""
    dept_short = dept_raw.upper()
    if dept_short.startswith("PHÒNG "):
        dept_short = dept_short[6:]

    # Nhãn KSV — theo role của KSV approver (không phải staff_role)
    ksv_sign = r["staff_role"] not in ("truong_phong", "giam_doc", "pho_giam_doc") \
               and bool(r["ksv_approver_id"])
    ksv_role = ""
    if r["ksv_approver_id"]:
        ksv_r = db.execute("SELECT role FROM user_tttt WHERE id=?", (r["ksv_approver_id"],)).fetchone()
        if ksv_r:
            ksv_role = ksv_r["role"]

    if ksv_role == "pho_phong":
        ksv_dept_label      = f"TUQ. TRƯỞNG PHÒNG {dept_short}"
        ksv_dept_label_line2 = "PHÓ TRƯỞNG PHÒNG"
    else:  # truong_phong hoặc không xác định
        ksv_dept_label      = f"TRƯỞNG PHÒNG {dept_short}"
        ksv_dept_label_line2 = ""

    # Nhãn ký tên cho Ban lãnh đạo
    gd_role = r["gd_role"] or ""
    if gd_role == "pho_giam_doc":
        gd_title_line1 = "TUQ. GIÁM ĐỐC TTTT"
        gd_title_line2 = "PHÓ GIÁM ĐỐC"
    elif gd_role == "giam_doc":
        gd_title_line1 = "GIÁM ĐỐC TTTT"
        gd_title_line2 = ""
    else:
        gd_title_line1 = "GIÁM ĐỐC TTTT"
        gd_title_line2 = ""

    # annual/bat_buoc → ngày làm đơn; dot_xuat và các loại khác → ngày bắt đầu nghỉ
    _doc_date = now.date() if r["leave_type"] in ("annual", "bat_buoc") else start
    ctx = {
        "ngay_thang_nam":   f"{_doc_date.day:02d} tháng {_doc_date.month:02d} năm {_doc_date.year}",
        "ho_va_ten":        r["staff_name"] or "",
        "chuc_vu":          _ROLE_VN.get(r["staff_role"] or "", r["staff_role"] or ""),
        "don_vi":           r["dept_name"] or "",
        "nam_phep":         str(start.year),
        "tong_so_phep":      str(tong_phep),
        "so_ngay_da_nghi":   f"{da_nghi:g}",
        "so_ngay_xin_nghi":  _fmt_leave_period(start, end, leave_days),
        "so_ngay_con_lai":   f"{con_lai_cur:g}",
        # 2-năm (carryover)
        "has_carryover":     has_carryover,
        "prev_year":         str(_prev_year),
        "tong_so_phep_prev": f"{int(tong_so_phep_prev)}",
        "da_nghi_prev":      f"{da_nghi_prev:g}",
        "da_nghi_cur":       f"{da_nghi:g}",
        "con_lai_prev":      f"{con_lai_prev:g}",
        "con_lai_cur":       f"{con_lai_cur:g}",
        "ly_do":            r["reason"] or "",
        "ksv_name":         (r["ksv_name"] or "") if ksv_sign else "",
        "gd_name":          gd_name,
        "gd_title_line1":        gd_title_line1,
        "gd_title_line2":        gd_title_line2,
    }

    ctx["ksv_dept_label"] = ksv_dept_label if ksv_sign else ""
    ctx["ksv_dept_label_line2"] = ksv_dept_label_line2 if ksv_sign else ""
    from docxtpl import DocxTemplate
    tpl = DocxTemplate(tpl_path)
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


# ─── Hạn mức phép (quota) ──────────────────────────────────────────────────────

@router.get("/quotas/{year}")
def get_quotas(
    year: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.quota_admin")),
):
    """Trả danh sách hạn mức phép của tất cả nhân viên trong năm."""
    staffs = db.execute(
        """SELECT u.id, u.full_name, u.join_industry_date, d.name AS dept_name
           FROM user_tttt u
           LEFT JOIN departments d ON u.department_id = d.id
           WHERE u.is_active=1 AND u.is_deleted=0
           ORDER BY d.name, u.full_name"""
    ).fetchall()
    result = []
    for s in staffs:
        q = db.execute(
            "SELECT quota_days FROM leave_quotas WHERE staff_id=? AND year=?", (s["id"], year)
        ).fetchone()
        from datetime import date as _today_d
        quota = float(q["quota_days"]) if q else float(compute_annual_leave(s["join_industry_date"], year))
        is_current_year = (year == _today_d.today().year)
        carry          = compute_carry_over(s["id"], year, db, effective=True)    # hiển thị Chuyển kỳ
        # Chỉ dùng carry_original để bù khi đang xem năm hiện tại (sau Q1).
        # Năm cũ → Q1 đã qua lâu rồi, carry-over không còn liên quan nữa.
        carry_original = compute_carry_over(s["id"], year, db, effective=False) if is_current_year else 0.0
        used_row = db.execute(
            """SELECT COALESCE(SUM(
                   CASE WHEN lr.spread_dates IS NOT NULL AND lr.spread_dates != ''
                        THEN json_array_length(lr.spread_dates)
                        ELSE (julianday(lr.end_date) - julianday(lr.start_date) + 1)
                   END), 0)
               FROM leave_records lr
               WHERE lr.staff_id=? AND lr.status='approved'
                 AND lr.leave_type NOT IN ('thai_san','bao_hiem')
                 AND strftime('%Y', lr.start_date)=?""",
            (s["id"], str(year)),
        ).fetchone()
        used = float(used_row[0]) if used_row else 0.0
        result.append({
            "staff_id":         s["id"],
            "staff_name":       s["full_name"],
            "dept_name":        s["dept_name"] or "",
            "join_industry_date": str(s["join_industry_date"])[:10] if s["join_industry_date"] else "",
            "year":             year,
            "quota_days":       quota,
            "carry_over":       carry,
            "carry_original":   carry_original,
            "used_days":        used,
            "remaining":        max(0.0, quota - used),
        })
    return result


@router.post("/quotas")
def upsert_quota(
    body: LeaveQuotaUpsert,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.quota_admin")),
):
    """Ghi đè hạn mức phép cho nhân viên trong năm cụ thể."""
    if body.quota_days < 0:
        raise HTTPException(400, "quota_days không được âm")
    staff = db.execute("SELECT id FROM user_tttt WHERE id=? AND is_active=1", (body.staff_id,)).fetchone()
    if not staff:
        raise HTTPException(404, "Nhân viên không tồn tại")
    db.execute(
        "INSERT INTO leave_quotas (staff_id, year, quota_days) VALUES (?,?,?) ON CONFLICT(staff_id, year) DO UPDATE SET quota_days=excluded.quota_days",
        (body.staff_id, body.year, body.quota_days),
    )
    db.commit()
    return {"ok": True, "staff_id": body.staff_id, "year": body.year, "quota_days": body.quota_days}


@router.patch("/quotas/staff/{staff_id}/join-date")
def update_join_date(
    staff_id: int,
    body: dict,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.quota_admin")),
):
    """Cập nhật ngày vào ngành — chỉ dành cho quota admin."""
    join_date = body.get("join_industry_date", "")
    if not join_date:
        raise HTTPException(400, "join_industry_date không được để trống")
    staff = db.execute("SELECT id FROM user_tttt WHERE id=? AND is_active=1", (staff_id,)).fetchone()
    if not staff:
        raise HTTPException(404, "Không tìm thấy nhân viên")
    db.execute("UPDATE user_tttt SET join_industry_date=? WHERE id=?", (join_date, staff_id))
    db.commit()
    return {"ok": True, "staff_id": staff_id, "join_industry_date": join_date}


@router.get("/quotas/{year}/export")
def export_quotas(
    year: int,
    ids: str = "",   # staff_id cách nhau bởi dấu phẩy
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.quota_admin")),
):
    """Xuất bảng hạn mức phép năm ra Excel."""
    import openpyxl, io
    from openpyxl.styles import Alignment, Font, PatternFill
    from fastapi.responses import Response

    id_filter = {int(i.strip()) for i in ids.split(",") if i.strip().isdigit()} if ids else None

    staffs = db.execute(
        """SELECT u.id, u.full_name, u.join_industry_date, d.name AS dept_name
           FROM user_tttt u
           LEFT JOIN departments d ON u.department_id = d.id
           WHERE u.is_active=1 AND u.is_deleted=0
           ORDER BY d.name, u.full_name"""
    ).fetchall()

    data = []
    for s in staffs:
        if id_filter and s["id"] not in id_filter:
            continue
        q = db.execute("SELECT quota_days FROM leave_quotas WHERE staff_id=? AND year=?",
                       (s["id"], year)).fetchone()
        quota  = float(q["quota_days"]) if q else float(compute_annual_leave(s["join_industry_date"], year))
        carry  = compute_carry_over(s["id"], year, db, effective=False)
        used_r = db.execute(
            """SELECT COALESCE(SUM(
                   CASE WHEN lr.spread_dates IS NOT NULL AND lr.spread_dates != ''
                        THEN json_array_length(lr.spread_dates)
                        ELSE (julianday(lr.end_date) - julianday(lr.start_date) + 1)
                   END), 0)
               FROM leave_records lr
               WHERE lr.staff_id=? AND lr.status='approved'
                 AND lr.leave_type NOT IN ('thai_san','bao_hiem')
                 AND strftime('%Y', lr.start_date)=?""",
            (s["id"], str(year))).fetchone()
        used = float(used_r[0]) if used_r else 0.0
        join_date = s["join_industry_date"] or ""
        data.append({"name": s["full_name"], "dept": s["dept_name"] or "",
                     "join_date": join_date,
                     "quota": quota, "carry": carry, "used": used,
                     "remaining": max(0.0, quota - used)})

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Han muc phep {year}"

    # Dòng tiêu đề năm
    ws.merge_cells("A1:H1")
    title_cell = ws.cell(row=1, column=1, value=f"BẢNG HẠN MỨC NGHỈ PHÉP NĂM {year}")
    title_cell.font      = Font(bold=True, size=13)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    header_fill = PatternFill("solid", fgColor="8B0000")
    hdr_font    = Font(color="FFFFFF", bold=True)
    headers     = ["STT", "Họ và tên", "Phòng ban", "Ngày vào ngành", "Hạn mức", "Chuyển kỳ", "Đã dùng", "Ngày phép của năm"]
    col_widths  = [6, 30, 30, 18, 12, 12, 12, 12]
    for ci, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.font, cell.fill = hdr_font, header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w
    for ri, r in enumerate(data, 3):
        ws.cell(ri, 1, ri - 2).alignment = Alignment(horizontal="center")
        ws.cell(ri, 2, r["name"]).alignment = Alignment(horizontal="left")
        ws.cell(ri, 3, r["dept"]).alignment = Alignment(horizontal="left")
        ws.cell(ri, 4, r["join_date"]).alignment = Alignment(horizontal="center")
        for ci, val in enumerate([r["quota"], r["carry"], r["used"]], 5):
            ws.cell(ri, ci, round(val, 1)).alignment = Alignment(horizontal="center")
        cell_rem = ws.cell(ri, 8, round(r["remaining"], 1))
        cell_rem.font = Font(color="157A3A" if r["remaining"] > 0 else "CC0000", bold=True)
        cell_rem.alignment = Alignment(horizontal="center")
    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="han_muc_phep_{year}.xlsx"'},
    )


@router.get("/export/annual")
def export_all_leaves_annual(
    year: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.stats_export")),
):
    """Xuất tất cả đơn nghỉ phép trong năm ra Excel."""
    import openpyxl, io
    from openpyxl.styles import Alignment, Font, PatternFill
    from fastapi.responses import Response

    rows = db.execute(
        """SELECT lr.*, s.full_name AS staff_name, d.name AS dept_name,
                  kv.full_name AS ksv_name, th.full_name AS th_name,
                  gd.full_name AS gd_name
           FROM leave_records lr
           LEFT JOIN user_tttt s  ON lr.staff_id = s.id
           LEFT JOIN departments d ON s.department_id = d.id
           LEFT JOIN user_tttt kv ON lr.ksv_approver_id = kv.id
           LEFT JOIN user_tttt th ON lr.tong_hop_approver_id = th.id
           LEFT JOIN user_tttt gd ON lr.gd_approver_id = gd.id
           WHERE strftime('%Y', lr.start_date) = ?
           ORDER BY lr.created_at DESC""",
        (str(year),)
    ).fetchall()

    import json as _json

    def _fmt_date(d_str):
        """YYYY-MM-DD → DD/MM/YYYY"""
        try:
            y, mo, dd = d_str[:10].split("-")
            return f"{dd}/{mo}/{y}"
        except Exception:
            return d_str or ""

    _STATUS_VN = {
        "pending_ksv": "Chờ KSV duyệt", "pending_tong_hop": "Chờ Tổng hợp",
        "pending_gd": "Chờ GĐ duyệt", "approved": "Đã duyệt",
        "rejected": "Từ chối", "cancelled": "Đã hủy"
    }
    headers = ["STT", "Ngày tạo", "Họ và tên", "Phòng", "Loại nghỉ", "Ngày nghỉ",
               "Số ngày", "Trạng thái", "KSV duyệt", "Phòng Tổng hợp", "GĐ/PGĐ"]
    widths  = [6, 14, 28, 28, 18, 40, 10, 18, 22, 22, 20]
    hfill = PatternFill("solid", fgColor="8B0000")
    hfont = Font(bold=True, color="FFFFFF")

    # Sắp xếp theo ngày bắt đầu tăng dần
    rows_sorted = sorted(rows, key=lambda r: r["start_date"] or "")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Don nghi phep {year}"

    ws.merge_cells("A1:L1")
    tc = ws.cell(1, 1, f"TẤT CẢ ĐƠN NGHỈ PHÉP NĂM {year}")
    tc.font = Font(bold=True, size=13)
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    for ci, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(2, ci, h)
        cell.fill = hfill; cell.font = hfont
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, r in enumerate(rows_sorted, 1):
        try:
            nd = len(_json.loads(r["spread_dates"])) if r["spread_dates"] else (
                (date.fromisoformat(r["end_date"]) - date.fromisoformat(r["start_date"])).days + 1)
        except Exception:
            nd = 1
        ri = idx + 2
        ws.cell(ri, 1, idx).alignment = Alignment(horizontal="center")
        # Ngày nghỉ: ghi từng ngày riêng nếu không liên nhau
        if r["spread_dates"]:
            try:
                spread = _json.loads(r["spread_dates"])
                dates_str = ", ".join(_fmt_date(d) for d in sorted(spread))
            except Exception:
                dates_str = _fmt_date(r["start_date"])
        else:
            dates_str = f"{_fmt_date(r['start_date'])} → {_fmt_date(r['end_date'])}"

        ws.cell(ri, 2, _fmt_date((r["created_at"] or "")[:10])).alignment = Alignment(horizontal="center")
        ws.cell(ri, 3, r["staff_name"] or "").alignment = Alignment(horizontal="left")
        ws.cell(ri, 4, r["dept_name"] or "").alignment = Alignment(horizontal="left")
        ws.cell(ri, 5, LEAVE_TYPE_LABELS.get(r["leave_type"] or "", r["leave_type"] or ""))
        ws.cell(ri, 6, dates_str).alignment = Alignment(horizontal="left", wrap_text=True)
        ws.cell(ri, 7, nd).alignment = Alignment(horizontal="center")
        ws.cell(ri, 8, _STATUS_VN.get(r["status"] or "", r["status"] or ""))
        ws.cell(ri, 9, r["ksv_name"] or "")
        ws.cell(ri, 10, r["th_name"] or "")
        ws.cell(ri, 11, r["gd_name"] or "")

    buf = io.BytesIO(); wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="bao_cao_don_nghi_phep_{year}.xlsx"'},
    )


# ─── Báo cáo năm ────────────────────────────────────────────────────────────

@router.get("/stats/annual/{year}")
def stats_annual(
    year: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.stats_export")),
):
    """Tổng hợp phép năm — số ngày quota, carry-over, đã dùng, còn lại theo từng nhân viên."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    staffs = db.execute(
        """SELECT u.id, u.full_name, u.join_industry_date, d.name AS dept_name
           FROM user_tttt u
           LEFT JOIN departments d ON u.department_id = d.id
           WHERE u.is_active=1 AND u.is_deleted=0
           ORDER BY d.name, u.full_name"""
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Tổng hợp phép {year}"

    # Dòng tiêu đề năm
    ws.merge_cells("A1:H1")
    title_cell = ws.cell(row=1, column=1, value=f"BÁO CÁO TỔNG HỢP NGHỈ PHÉP NĂM {year}")
    title_cell.font      = Font(bold=True, size=13)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24

    hdr_fill = PatternFill("solid", fgColor="8B0000")
    hdr_font = Font(bold=True, color="FFFFFF")
    headers = ["STT", "Họ và tên", "Phòng ban", "Ngày vào ngành", "Hạn mức", "Chuyển kỳ", "Đã dùng", "Ngày phép của năm"]
    widths  = [6, 28, 28, 18, 12, 12, 12, 12]
    for ci, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=2, column=ci, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, s in enumerate(staffs, 1):
        q = db.execute(
            "SELECT quota_days FROM leave_quotas WHERE staff_id=? AND year=?", (s["id"], year)
        ).fetchone()
        quota = float(q["quota_days"]) if q else float(compute_annual_leave(s["join_industry_date"], year))
        carry = compute_carry_over(s["id"], year, db, effective=False)
        used_row = db.execute(
            """SELECT COALESCE(SUM(
                   CASE WHEN lr.spread_dates IS NOT NULL AND lr.spread_dates != ''
                        THEN json_array_length(lr.spread_dates)
                        ELSE (julianday(lr.end_date) - julianday(lr.start_date) + 1)
                   END), 0)
               FROM leave_records lr
               WHERE lr.staff_id=? AND lr.leave_type='annual' AND lr.status='approved'
                 AND strftime('%Y', lr.start_date)=?""",
            (s["id"], str(year)),
        ).fetchone()
        used = float(used_row[0]) if used_row else 0.0
        remaining = max(0.0, quota - used)
        ri = idx + 2
        ws.cell(ri, 1, idx).alignment = Alignment(horizontal="center")
        ws.cell(ri, 2, s["full_name"]).alignment = Alignment(horizontal="left")
        ws.cell(ri, 3, s["dept_name"] or "").alignment = Alignment(horizontal="left")
        ws.cell(ri, 4, s["join_industry_date"] or "").alignment = Alignment(horizontal="center")
        for ci, val in enumerate([quota, carry, used], 5):
            ws.cell(ri, ci, round(val, 1)).alignment = Alignment(horizontal="center")
        cell_rem = ws.cell(ri, 8, round(remaining, 1))
        cell_rem.font = Font(color="157A3A" if remaining > 0 else "CC0000", bold=True)
        cell_rem.alignment = Alignment(horizontal="center")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''bao_cao_phep_{year}.xlsx"},
    )


# ─── Dashboard lãnh đạo ─────────────────────────────────────────────────────

@router.get("/stats/leader-dashboard")
def leader_dashboard(
    year: int = None,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.dashboard")),
):
    """Thống kê tổng quan: số đơn theo trạng thái, top nghỉ nhiều, chờ duyệt."""
    from datetime import date as _date
    yr = year or _date.today().year

    # Đơn chờ duyệt — filter theo role, giống list_leaves(scope="pending")
    role = current["role"]
    p_where = ""
    p_params: list = []
    if role == "admin":
        p_where = "lr.status IN ('pending_ksv','pending_tong_hop','pending_gd')"
    elif role in ("giam_doc", "pho_giam_doc"):
        if _can_gd_review(current, db):
            p_where = "lr.gd_approver_id = ? AND lr.status = 'pending_gd'"
            p_params.append(current["id"])
    elif _is_tong_hop_staff(current, db) and role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        # PP/TP Tổng hợp: xem cả KSV phòng mình + TH toàn trung tâm
        p_where = "(lr.status = 'pending_tong_hop' OR (lr.ksv_approver_id = ? AND lr.status = 'pending_ksv'))"
        p_params.append(current["id"])
    elif _is_tong_hop_staff(current, db):
        p_where = "lr.status = 'pending_tong_hop'"
    elif role in ("truong_phong", "pho_phong", "hau_kiem_vien"):
        p_where = "lr.ksv_approver_id = ? AND lr.status = 'pending_ksv'"
        p_params.append(current["id"])

    if p_where:
        pending_rows = db.execute(
            f"""SELECT lr.id, s.full_name, lr.status, lr.start_date, lr.end_date, lr.leave_type
               FROM leave_records lr
               JOIN user_tttt s ON lr.staff_id = s.id
               WHERE {p_where}
               ORDER BY lr.created_at""",
            p_params,
        ).fetchall()
    else:
        pending_rows = []

    # by_status: đếm từ danh sách pending đã filter + approved trong năm
    by_status: dict = {}
    for r in pending_rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    approved_cnt = db.execute(
        "SELECT COUNT(*) FROM leave_records WHERE status='approved' AND strftime('%Y', start_date)=?",
        (str(yr),),
    ).fetchone()[0]
    by_status["approved"] = approved_cnt
    by_status["direct"] = db.execute(
        "SELECT COUNT(*) FROM leave_records WHERE is_direct=1 AND status='approved' AND strftime('%Y', start_date)=?",
        (str(yr),),
    ).fetchone()[0]
    pending = [
        {
            "id": r["id"], "staff_name": r["full_name"],
            "status": r["status"], "status_label": _LEAVE_STATUS_VN.get(r["status"], r["status"]),
            "start_date": r["start_date"], "end_date": r["end_date"],
            "leave_type": LEAVE_TYPE_LABELS.get(r["leave_type"], r["leave_type"]),
        }
        for r in pending_rows
    ]

    # Top 10 nhân viên nghỉ nhiều nhất trong năm (approved)
    top_rows = db.execute(
        """SELECT s.full_name,
                  SUM(CASE WHEN lr.spread_dates IS NOT NULL AND lr.spread_dates != ''
                           THEN json_array_length(lr.spread_dates)
                           ELSE (julianday(lr.end_date) - julianday(lr.start_date) + 1)
                      END) AS total_days
           FROM leave_records lr
           JOIN user_tttt s ON lr.staff_id = s.id
           WHERE lr.status='approved' AND strftime('%Y', lr.start_date)=?
           GROUP BY lr.staff_id ORDER BY total_days DESC LIMIT 10""",
        (str(yr),),
    ).fetchall()
    top_staff = [{"staff_name": r["full_name"], "total_days": r["total_days"]} for r in top_rows]

    return {
        "year": yr,
        "by_status": by_status,
        "pending": pending,
        "top_staff": top_staff,
    }


# ─── Khai báo hộ (direct leave) ──────────────────────────────────────────────

@router.post("/direct")
def create_direct_leave(
    body: DirectLeaveCreate,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.declare_direct")),
):
    """Khai báo hộ — tạo đơn approved ngay, cộng used_leave_days thủ công."""
    staff = db.execute(
        "SELECT * FROM user_tttt WHERE id=? AND is_active=1", (body.staff_id,)
    ).fetchone()
    if not staff:
        raise HTTPException(404, "Nhân viên không tồn tại")

    if body.leave_type not in _VALID_LEAVE_TYPES:
        raise HTTPException(400, f"Loại nghỉ phép không hợp lệ: {body.leave_type}")

    if body.spread_dates:
        spread = sorted(set(body.spread_dates))
        eff_start  = date.fromisoformat(spread[0])
        eff_end    = date.fromisoformat(spread[-1])
        leave_days = len(spread)
        spread_json = json.dumps(spread)
    else:
        if body.end_date < body.start_date:
            raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")
        eff_start   = body.start_date
        eff_end     = body.end_date
        _h          = _load_holidays(db, eff_start, eff_end)
        leave_days  = calculate_leave_days(eff_start, eff_end, _h)
        spread_json = None

    # Kiểm tra trùng ngày với đơn đã tồn tại (kể cả khai báo hộ và đơn thường)
    all_dates = json.loads(spread_json) if spread_json else [
        (eff_start + __import__('datetime').timedelta(days=i)).isoformat()
        for i in range((eff_end - eff_start).days + 1)
    ]
    existing = db.execute(
        """SELECT lr.id, lr.start_date, lr.end_date, lr.spread_dates
           FROM leave_records lr
           WHERE lr.staff_id=? AND lr.status NOT IN ('cancelled','rejected')""",
        (body.staff_id,)
    ).fetchall()
    conflict_dates = []
    for ex in existing:
        ex_dates = json.loads(ex["spread_dates"]) if ex["spread_dates"] else [
            (date.fromisoformat(ex["start_date"]) + __import__('datetime').timedelta(days=i)).isoformat()
            for i in range((date.fromisoformat(ex["end_date"]) - date.fromisoformat(ex["start_date"])).days + 1)
        ]
        overlap = set(all_dates) & set(ex_dates)
        if overlap:
            conflict_dates.extend(sorted(overlap))
    if conflict_dates:
        conflict_str = ", ".join(sorted(set(conflict_dates))[:5])
        raise HTTPException(409, f"Nhân viên đã có đơn nghỉ vào ngày: {conflict_str}. Vui lòng kiểm tra lại.")

    # Kiểm tra hạn mức (không áp dụng cho thai_san, bao_hiem)
    if body.leave_type not in _NO_QUOTA_TYPES:
        quota = float(
            (db.execute("SELECT quota_days FROM leave_quotas WHERE staff_id=? AND year=?",
                        (body.staff_id, eff_start.year)).fetchone() or {}).get("quota_days", 0)
            or compute_annual_leave(staff["join_industry_date"], eff_start.year)
        )
        carry = compute_carry_over(body.staff_id, eff_start.year, db, effective=True, ref_date=eff_start)
        used_r = db.execute(
            """SELECT COALESCE(SUM(
                   CASE WHEN spread_dates IS NOT NULL AND spread_dates != ''
                        THEN json_array_length(spread_dates)
                        ELSE (julianday(end_date) - julianday(start_date) + 1)
                   END), 0)
               FROM leave_records
               WHERE staff_id=? AND status IN ('approved','pending_ksv','pending_tong_hop','pending_gd')
                 AND strftime('%Y', start_date)=?
                 AND leave_type NOT IN ('thai_san','bao_hiem')""",
            (body.staff_id, str(eff_start.year))
        ).fetchone()
        used = float(used_r[0]) if used_r else 0.0
        remaining = quota + carry - used
        if leave_days > remaining:
            raise HTTPException(400,
                f"Vượt quá hạn mức phép năm {eff_start.year}. "
                f"Còn lại {remaining:.0f} ngày, khai báo {leave_days} ngày.")

    cur = db.execute(
        """INSERT INTO leave_records
               (staff_id, start_date, end_date, leave_type, reason, status,
                is_direct, direct_by, spread_dates, created_at, updated_at)
           VALUES (?,?,?,?,?,'approved',1,?,?,?,?)""",
        (body.staff_id, eff_start.isoformat(), eff_end.isoformat(),
         body.leave_type, body.reason,
         current["id"], spread_json, str(_vn_now()), str(_vn_now())),
    )
    leave_id = cur.lastrowid
    if body.leave_type not in _NO_QUOTA_TYPES:
        db.execute(
            "UPDATE user_tttt SET used_leave_days = COALESCE(used_leave_days,0) + ? WHERE id=?",
            (leave_days, body.staff_id),
        )
    _log_action(db, leave_id, current["id"], "direct_create", None, "", LeaveStatus.APPROVED)
    db.commit()
    return _leave_to_out(leave_id, db)


# ─── Recall (rút đơn đã duyệt) ───────────────────────────────────────────────

@router.post("/{leave_id}/recall")
def request_recall(
    leave_id: int,
    body: RecallCreate,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.recall")),
):
    """Yêu cầu rút đơn đã duyệt — ghi recall_reason, chuyển sang pending_tong_hop để xác nhận."""
    leave = db.execute("SELECT * FROM leave_records WHERE id=?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn")
    if leave["status"] != LeaveStatus.APPROVED:
        raise HTTPException(400, "Chỉ rút được đơn đã duyệt")
    if leave["staff_id"] != current["id"] and current["role"] != "admin":
        raise HTTPException(403, "Chỉ chủ nhân đơn hoặc Admin mới được yêu cầu rút")
    if not body.reason:
        raise HTTPException(400, "Vui lòng nhập lý do rút đơn")

    old = leave["status"]
    db.execute(
        "UPDATE leave_records SET recall_reason=?, status=?, updated_at=? WHERE id=?",
        (body.reason, LeaveStatus.PENDING_TONG_HOP, str(_vn_now()), leave_id),
    )
    _log_action(db, leave_id, current["id"], "recall_request", body.reason, old, LeaveStatus.PENDING_TONG_HOP)
    db.commit()
    return _leave_to_out(leave_id, db)


@router.put("/{leave_id}/recall-approve")
def approve_recall(
    leave_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("leaves.recall")),
):
    """Phòng Tổng hợp xác nhận rút đơn — chuyển sang cancelled."""
    if not _is_tong_hop_staff(current, db) and current["role"] != "admin":
        raise HTTPException(403, "Chỉ Phòng Tổng hợp hoặc Admin mới xác nhận rút đơn")
    leave = db.execute("SELECT * FROM leave_records WHERE id=?", (leave_id,)).fetchone()
    if not leave:
        raise HTTPException(404, "Không tìm thấy đơn")
    if leave["status"] != LeaveStatus.PENDING_TONG_HOP or not leave["recall_reason"]:
        raise HTTPException(400, "Đơn này không trong trạng thái chờ xác nhận rút")
    old = leave["status"]
    # Trừ used_leave_days khi xác nhận rút (approved → cancelled)
    start = date.fromisoformat(leave["start_date"])
    end   = date.fromisoformat(leave["end_date"])
    _h    = _load_holidays(db, start, end)
    days  = len(json.loads(leave["spread_dates"])) if leave["spread_dates"] else calculate_leave_days(start, end, _h)
    db.execute(
        "UPDATE user_tttt SET used_leave_days = MAX(0, COALESCE(used_leave_days,0) - ?) WHERE id=?",
        (days, leave["staff_id"]),
    )
    db.execute(
        "UPDATE leave_records SET status=?, updated_at=? WHERE id=?",
        (LeaveStatus.CANCELLED, str(_vn_now()), leave_id),
    )
    _log_action(db, leave_id, current["id"], "recall_approve", None, old, LeaveStatus.CANCELLED)
    db.commit()
    return _leave_to_out(leave_id, db)
