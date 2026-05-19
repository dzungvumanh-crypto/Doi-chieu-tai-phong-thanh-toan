"""Handover (Bàn giao chứng từ) endpoints"""
import calendar
import io
import sqlite3
from datetime import date
from typing import List, Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl.styles import Alignment, Font, PatternFill

from backend.core.deps import (
    get_current_staff, require_pho_phong_or_above, require_handover_write,
)
from backend.core.enums import EntryStatus
from backend.database import get_db, _vn_now
from backend.schemas.handovers import (
    BorrowRequest, DocumentEntryIn, EntryHistoryItem, EntryHistoryOut,
    EntryUpsertRequest, GridEntryOut, GridResponse, HandbackRequest,
    HandoverCreate, RejectRequest,
)

router = APIRouter(prefix="/api/handovers", tags=["Handovers"])

# ─── Mapping hiển thị lịch sử ────────────────────────────────────────────────
_ACTION_LABEL = {
    "handover":           ("Bàn giao chứng từ",       "blue"),
    "edited_cv":          ("Sửa số tờ (CV)",           "blue"),
    "confirmed":          ("Xác nhận đã nhận",          "green"),
    "borrow_requested":   ("Yêu cầu mượn lại",          "orange"),
    "borrowed":           ("Xác nhận cho mượn",         "orange"),
    "returned":           ("Bàn giao lại",               "blue"),
    "edited_hkv":         ("Sửa trực tiếp (HKV/KSV)",  "purple"),
    "rejected_borrow":    ("Từ chối yêu cầu mượn",      "red"),
    "rejected_return":    ("Từ chối bàn giao lại",       "red"),
    "rejected_handover":  ("Từ chối chứng từ mới",       "red"),
}

_STATUS_LABEL = {
    EntryStatus.PENDING:   "Chờ xác nhận",
    EntryStatus.CONFIRMED: "Đã xác nhận",
    EntryStatus.BORROWED:  "Đang mượn",
}

_ROLE_LABEL = {
    "admin":         "Quản trị viên",
    "hau_kiem_vien": "Hậu kiểm viên",
    "giam_doc":      "Giám đốc",
    "pho_giam_doc":  "Phó Giám đốc",
    "truong_phong":  "Trưởng phòng",
    "pho_phong":     "Phó phòng",
    "chuyen_vien":   "Chuyên viên",
}


def _handover_to_dict(h: dict, db: sqlite3.Connection) -> dict:
    dept = db.execute("SELECT * FROM departments WHERE id = ?", (h["department_id"],)).fetchone()
    rows = db.execute(
        """SELECT de.id, de.handover_id, de.staff_id, de.transaction_date, de.sheet_count,
                  de.notes, de.entry_status, de.borrow_reason, de.entered_by_id,
                  de.confirmed_by_id, de.confirmed_at,
                  ks.employee_code AS s_emp_code, ks.full_name AS s_full_name,
                  ks.role AS s_role, ks.department_id AS s_dept_id, ks.username AS s_username,
                  ks.phone AS s_phone, ks.email AS s_email, ks.start_date AS s_start_date,
                  ks.ipcas_code AS s_ipcas_code, ks.payment_username AS s_pay_user,
                  ks.is_active AS s_is_active
           FROM document_entries de
           LEFT JOIN user_tttt ks ON de.staff_id = ks.id
           WHERE de.handover_id = ? ORDER BY de.transaction_date""",
        (h["id"],),
    ).fetchall()

    entries = []
    for e in rows:
        staff = None
        if e["staff_id"]:
            staff = {
                "id": e["staff_id"],
                "employee_code": e["s_emp_code"] or "",
                "full_name": e["s_full_name"] or "",
                "role": e["s_role"] or "",
                "department_id": e["s_dept_id"],
                "username": e["s_username"] or "",
                "phone": e["s_phone"],
                "email": e["s_email"],
                "start_date": e["s_start_date"],
                "ipcas_code": e["s_ipcas_code"],
                "payment_username": e["s_pay_user"],
                "is_active": bool(e["s_is_active"]),
            }
        entries.append({
            "id": e["id"],
            "handover_id": e["handover_id"],
            "staff_id": e["staff_id"],
            "transaction_date": e["transaction_date"],
            "sheet_count": e["sheet_count"],
            "notes": e["notes"],
            "entry_status": e["entry_status"] or EntryStatus.CONFIRMED,
            "borrow_reason": e["borrow_reason"],
            "entered_by_id": e["entered_by_id"],
            "confirmed_by_id": e["confirmed_by_id"],
            "confirmed_at": e["confirmed_at"],
            "staff": staff,
        })

    return {
        "id": h["id"],
        "department_id": h["department_id"],
        "handover_date": h["handover_date"],
        "received_by_id": h["received_by_id"],
        "delivered_by": h["delivered_by"],
        "notes": h["notes"],
        "status": h["status"] or "draft",
        "created_at": h["created_at"],
        "department": dict(dept) if dept else None,
        "entries": entries,
    }


# ─── Grid ─────────────────────────────────────────────────────────────────────
@router.get("/grid", response_model=GridResponse)
def get_handover_grid(
    department_id: int,
    year: int,
    month: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_handover_write),
):
    if current["role"] == "chuyen_vien" and current.get("department_id") != department_id:
        raise HTTPException(403, "Chỉ được xem dữ liệu phòng của mình")

    days_in_month = calendar.monthrange(year, month)[1]
    period_start = date(year, month, 1).isoformat()
    period_end = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)).isoformat()

    # Entries trong tháng
    entry_rows = db.execute(
        """SELECT de.id, de.handover_id, de.staff_id, de.transaction_date, de.sheet_count,
                  de.entry_status, de.entered_by_id
           FROM document_entries de
           JOIN user_tttt ks ON de.staff_id = ks.id
           WHERE ks.department_id = ?
             AND de.transaction_date >= ? AND de.transaction_date < ?""",
        (department_id, period_start, period_end),
    ).fetchall()

    staff_ids_with_entries = {e["staff_id"] for e in entry_rows}
    entered_by_ids = {e["entered_by_id"] for e in entry_rows if e["entered_by_id"]}

    # Staff: đang active + có entries trong tháng này
    if staff_ids_with_entries:
        ph = ",".join("?" * len(staff_ids_with_entries))
        user_rows = db.execute(
            f"SELECT * FROM user_tttt WHERE department_id = ? AND (is_active = 1 OR id IN ({ph})) ORDER BY ipcas_code",
            [department_id] + list(staff_ids_with_entries),
        ).fetchall()
    else:
        user_rows = db.execute(
            "SELECT * FROM user_tttt WHERE department_id = ? AND is_active = 1 ORDER BY ipcas_code",
            (department_id,),
        ).fetchall()

    # Tên người nhập
    entered_by_map: dict = {}
    if entered_by_ids:
        ph2 = ",".join("?" * len(entered_by_ids))
        for r in db.execute(
            f"SELECT id, full_name FROM user_tttt WHERE id IN ({ph2})", list(entered_by_ids)
        ).fetchall():
            entered_by_map[r["id"]] = r["full_name"]

    grid_entries = [
        GridEntryOut(
            staff_id=e["staff_id"],
            day=int(e["transaction_date"].split("-")[2]),
            sheet_count=e["sheet_count"],
            entry_id=e["id"],
            entry_status=e["entry_status"] or EntryStatus.CONFIRMED,
            entered_by_name=entered_by_map.get(e["entered_by_id"]) if e["entered_by_id"] else None,
        )
        for e in entry_rows
    ]
    return GridResponse(users=[dict(u) for u in user_rows], entries=grid_entries, days_in_month=days_in_month)


# ─── Upsert (nhập/sửa ô grid) ────────────────────────────────────────────────
@router.put("/entry-upsert")
def upsert_entry(
    body: EntryUpsertRequest,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_handover_write),
):
    staff_row = db.execute("SELECT * FROM user_tttt WHERE id = ?", (body.staff_id,)).fetchone()
    if not staff_row:
        raise HTTPException(404, "Không tìm thấy cán bộ")

    is_cv = current["role"] == "chuyen_vien"
    if is_cv and current.get("department_id") != staff_row["department_id"]:
        raise HTTPException(403, "Chỉ được nhập dữ liệu phòng của mình")

    dept_id = staff_row["department_id"]

    # ── Get/create handover (INSERT OR IGNORE để chống race condition) ──
    db.execute(
        "INSERT OR IGNORE INTO handovers (department_id, handover_date, received_by_id, status, created_at) VALUES (?,?,?,?,?)",
        (dept_id, body.date, None if is_cv else current["id"], "draft", str(_vn_now())),
    )
    h_row = db.execute(
        "SELECT * FROM handovers WHERE department_id = ? AND handover_date = ?",
        (dept_id, body.date),
    ).fetchone()
    if not h_row:
        raise HTTPException(500, "Không thể tạo phiếu bàn giao — hãy báo admin")
    handover_id = h_row["id"]

    # ── Entry hiện tại ──
    entry_row = db.execute(
        "SELECT * FROM document_entries WHERE handover_id = ? AND staff_id = ? AND transaction_date = ?",
        (handover_id, body.staff_id, body.date),
    ).fetchone()

    if body.sheet_count > 0:
        if entry_row:
            old_count = entry_row["sheet_count"]
            if is_cv:
                action = "edited_cv" if entry_row["entry_status"] == EntryStatus.CONFIRMED else "handover"
                new_status = EntryStatus.PENDING
            else:
                action = "edited_hkv"
                new_status = entry_row["entry_status"] or EntryStatus.CONFIRMED

            set_extra, params_extra = "", []
            if not is_cv and entry_row["confirmed_by_id"] is None:
                set_extra = ", confirmed_by_id=?, confirmed_at=?"
                params_extra = [current["id"], str(_vn_now())]

            db.execute(
                f"UPDATE document_entries SET sheet_count=?, entry_status=?, entered_by_id=?{set_extra} WHERE id=?",
                [body.sheet_count, new_status, current["id"]] + params_extra + [entry_row["id"]],
            )
            db.execute(
                "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, old_sheet_count, new_sheet_count, timestamp) VALUES (?,?,?,?,?,?)",
                (entry_row["id"], action, current["id"], old_count, body.sheet_count, str(_vn_now())),
            )
        else:
            new_status = EntryStatus.PENDING if is_cv else EntryStatus.CONFIRMED
            # Dùng INSERT thường (không IGNORE) để lỗi duplicate nổi lên thay vì âm thầm bỏ qua
            db.execute(
                "INSERT INTO document_entries (handover_id, staff_id, transaction_date, sheet_count, entry_status, entered_by_id, confirmed_by_id, confirmed_at) VALUES (?,?,?,?,?,?,?,?)",
                (handover_id, body.staff_id, body.date, body.sheet_count, new_status, current["id"],
                 None if is_cv else current["id"], None if is_cv else str(_vn_now())),
            )
            entry_row = db.execute(
                "SELECT * FROM document_entries WHERE handover_id = ? AND staff_id = ? AND transaction_date = ?",
                (handover_id, body.staff_id, body.date),
            ).fetchone()
            if entry_row:
                db.execute(
                    "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, old_sheet_count, new_sheet_count, timestamp) VALUES (?,?,?,?,?,?)",
                    (entry_row["id"], "handover" if is_cv else "edited_hkv", current["id"], None, body.sheet_count, str(_vn_now())),
                )
            else:
                raise HTTPException(500, "Không thể lưu chứng từ — vui lòng thử lại")
    else:
        if entry_row:
            if is_cv and entry_row["entry_status"] != EntryStatus.PENDING:
                raise HTTPException(400, "Không thể xóa chứng từ đã được xác nhận. Vui lòng liên hệ HKV/KSV.")
            db.execute("DELETE FROM entry_change_logs WHERE entry_id = ?", (entry_row["id"],))
            db.execute("DELETE FROM document_entries WHERE id = ?", (entry_row["id"],))

    db.commit()
    return {"ok": True}


# ─── Xác nhận đã nhận / xác nhận cho mượn (HKV/KSV) ────────────────────────
@router.post("/entries/{entry_id}/confirm-received")
def confirm_received(
    entry_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_pho_phong_or_above),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.PENDING:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ xác nhận được khi đang chờ xác nhận.")

    if entry["borrow_reason"]:
        db.execute(
            "UPDATE document_entries SET entry_status=?, borrowed_at=?, borrow_reason=NULL WHERE id=?",
            (EntryStatus.BORROWED, str(_vn_now()), entry_id),
        )
        action = "borrowed"
        message = "Đã xác nhận cho mượn chứng từ"
    else:
        db.execute(
            "UPDATE document_entries SET entry_status=?, confirmed_by_id=?, confirmed_at=? WHERE id=?",
            (EntryStatus.CONFIRMED, current["id"], str(_vn_now()), entry_id),
        )
        action = "confirmed"
        message = "Đã xác nhận nhận chứng từ"
        # Cập nhật received_by_id của handover nếu chưa có
        db.execute(
            "UPDATE handovers SET received_by_id=? WHERE id=(SELECT handover_id FROM document_entries WHERE id=?) AND received_by_id IS NULL",
            (current["id"], entry_id),
        )

    db.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, timestamp) VALUES (?,?,?,?,?)",
        (entry_id, action, current["id"], entry["sheet_count"], str(_vn_now())),
    )
    db.commit()
    return {"ok": True, "message": message}


# ─── Gửi yêu cầu mượn lại (Chuyên viên) ─────────────────────────────────────
@router.post("/entries/{entry_id}/borrow")
def borrow_entry(
    entry_id: int,
    body: BorrowRequest,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_handover_write),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.CONFIRMED:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ mượn được chứng từ đã xác nhận.")

    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "Vui lòng nhập lý do mượn")

    if current["role"] == "chuyen_vien" and entry["staff_id"]:
        s = db.execute("SELECT department_id FROM user_tttt WHERE id = ?", (entry["staff_id"],)).fetchone()
        if s and s["department_id"] != current.get("department_id"):
            raise HTTPException(403, "Chỉ được mượn chứng từ thuộc phòng của mình")

    db.execute(
        "UPDATE document_entries SET entry_status=?, borrow_reason=? WHERE id=?",
        (EntryStatus.PENDING, reason, entry_id),
    )
    db.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, timestamp) VALUES (?,?,?,?,?)",
        (entry_id, "borrow_requested", current["id"], entry["sheet_count"], str(_vn_now())),
    )
    db.commit()
    return {"ok": True, "message": "Đã gửi yêu cầu mượn chứng từ"}


# ─── Bàn giao lại (Chuyên viên, sau khi mượn) ────────────────────────────────
@router.post("/entries/{entry_id}/handback")
def handback_entry(
    entry_id: int,
    body: HandbackRequest,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_handover_write),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.BORROWED:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ bàn giao lại được khi đang mượn.")

    if current["role"] == "chuyen_vien" and entry["staff_id"]:
        s = db.execute("SELECT department_id FROM user_tttt WHERE id = ?", (entry["staff_id"],)).fetchone()
        if s and s["department_id"] != current.get("department_id"):
            raise HTTPException(403, "Chỉ được bàn giao lại chứng từ thuộc phòng của mình")

    old_count = entry["sheet_count"]
    db.execute(
        "UPDATE document_entries SET entry_status=?, borrow_reason=NULL, sheet_count=?, entered_by_id=? WHERE id=?",
        (EntryStatus.PENDING, body.sheet_count, current["id"], entry_id),
    )
    db.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, old_sheet_count, new_sheet_count, timestamp) VALUES (?,?,?,?,?,?)",
        (entry_id, "returned", current["id"], old_count, body.sheet_count, str(_vn_now())),
    )
    db.commit()
    return {"ok": True, "message": "Đã bàn giao lại chứng từ"}


# ─── Endpoint đã ngừng sử dụng ───────────────────────────────────────────────
@router.post("/entries/{entry_id}/confirm-returned")
def confirm_returned(entry_id: int, _: dict = Depends(require_pho_phong_or_above)):
    raise HTTPException(410, "Endpoint đã ngừng sử dụng. Dùng /handback + /confirm-received")


# ─── Từ chối (HKV/KSV) ───────────────────────────────────────────────────────
@router.post("/entries/{entry_id}/reject")
def reject_entry(
    entry_id: int,
    body: RejectRequest,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_pho_phong_or_above),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.PENDING:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ từ chối được khi đang chờ xác nhận.")

    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "Vui lòng nhập lý do từ chối")

    if entry["borrow_reason"]:
        # Từ chối yêu cầu mượn → quay về confirmed
        db.execute(
            "UPDATE document_entries SET entry_status=?, borrow_reason=NULL WHERE id=?",
            (EntryStatus.CONFIRMED, entry_id),
        )
        db.execute(
            "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, notes, timestamp) VALUES (?,?,?,?,?,?)",
            (entry_id, "rejected_borrow", current["id"], entry["sheet_count"], reason, str(_vn_now())),
        )
        db.commit()
        return {"ok": True, "message": "Đã từ chối yêu cầu mượn chứng từ"}

    # Xét log cuối để phân loại
    last_log = db.execute(
        "SELECT * FROM entry_change_logs WHERE entry_id = ? ORDER BY timestamp DESC LIMIT 1",
        (entry_id,),
    ).fetchone()
    last_action = last_log["action"] if last_log else None

    if last_action == "returned":
        # Từ chối bàn giao lại → quay về borrowed, khôi phục số tờ cũ
        restore_count = last_log["old_sheet_count"] if last_log["old_sheet_count"] is not None else entry["sheet_count"]
        db.execute(
            "UPDATE document_entries SET entry_status=?, sheet_count=? WHERE id=?",
            (EntryStatus.BORROWED, restore_count, entry_id),
        )
        db.execute(
            "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, notes, timestamp) VALUES (?,?,?,?,?,?)",
            (entry_id, "rejected_return", current["id"], restore_count, reason, str(_vn_now())),
        )
        db.commit()
        return {"ok": True, "message": "Đã từ chối bàn giao lại. Chứng từ vẫn đang mượn."}

    # Chứng từ mới chưa xác nhận → từ chối → xóa (manual cascade)
    db.execute("DELETE FROM entry_change_logs WHERE entry_id = ?", (entry_id,))
    db.execute("DELETE FROM document_entries WHERE id = ?", (entry_id,))
    db.commit()
    return {"ok": True, "message": "Đã từ chối và xóa chứng từ"}


# ─── Lịch sử thay đổi ────────────────────────────────────────────────────────
@router.get("/entries/{entry_id}/history", response_model=EntryHistoryOut)
def get_entry_history(
    entry_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    entry = db.execute(
        "SELECT de.*, ks.full_name AS s_name, ks.ipcas_code, ks.payment_username, ks.department_id AS s_dept_id "
        "FROM document_entries de LEFT JOIN user_tttt ks ON de.staff_id = ks.id WHERE de.id = ?",
        (entry_id,),
    ).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")

    if current["role"] == "chuyen_vien":
        if entry["s_dept_id"] and entry["s_dept_id"] != current.get("department_id"):
            raise HTTPException(403, "Không có quyền xem lịch sử chứng từ của phòng khác")

    logs = db.execute(
        """SELECT ecl.*, ks.full_name AS p_name, ks.role AS p_role
           FROM entry_change_logs ecl
           LEFT JOIN user_tttt ks ON ecl.performed_by_id = ks.id
           WHERE ecl.entry_id = ? ORDER BY ecl.timestamp DESC""",
        (entry_id,),
    ).fetchall()

    history_items = []
    for log in logs:
        action_key = log["action"] or ""
        label, color = _ACTION_LABEL.get(action_key, (action_key, "blue"))

        if log["old_sheet_count"] is not None and log["new_sheet_count"] is not None and log["old_sheet_count"] != log["new_sheet_count"]:
            label = f"{label}: {log['old_sheet_count']} → {log['new_sheet_count']} tờ"
        elif log["new_sheet_count"] is not None and log["old_sheet_count"] is None:
            label = f"{label} — {log['new_sheet_count']} tờ"

        if log["notes"]:
            label = f"{label} · Lý do: {log['notes']}"

        p_name = log["p_name"] or "?"
        role_label = _ROLE_LABEL.get(log["p_role"] or "", log["p_role"] or "?")
        performer_display = f"{p_name} · {role_label}"

        ts = log["timestamp"] or ""
        if ts:
            from datetime import datetime
            try:
                ts_dt = datetime.fromisoformat(str(ts))
                ts = ts_dt.strftime("%H:%M:%S  %d/%m/%Y")
            except Exception:
                pass

        history_items.append(EntryHistoryItem(
            id=log["id"],
            action=action_key,
            action_label=label,
            action_color=color,
            performed_by=p_name,
            performed_by_role=performer_display,
            timestamp=ts,
            old_sheet_count=log["old_sheet_count"],
            new_sheet_count=log["new_sheet_count"],
        ))

    s_name = entry["s_name"] or entry["payment_username"] or entry["ipcas_code"] or f"ID {entry['staff_id']}"
    current_status = entry["entry_status"] or EntryStatus.CONFIRMED
    tx_date = date.fromisoformat(entry["transaction_date"]).strftime("%d/%m/%Y") if entry["transaction_date"] else ""

    return EntryHistoryOut(
        entry_id=entry_id,
        source_user_name=s_name,
        transaction_date=tx_date,
        sheet_count=entry["sheet_count"],
        current_status=current_status,
        current_status_label=_STATUS_LABEL.get(current_status, current_status),
        borrow_reason=entry["borrow_reason"],
        logs=history_items,
    )


# ─── Danh sách handover ──────────────────────────────────────────────────────
@router.get("/")
def list_handovers(
    department_id: Optional[int] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    if current["role"] == "chuyen_vien":
        department_id = current.get("department_id")

    clauses = []
    params: list = []
    if department_id:
        clauses.append("department_id = ?")
        params.append(department_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if from_date:
        clauses.append("handover_date >= ?")
        params.append(from_date.isoformat())
    if to_date:
        clauses.append("handover_date <= ?")
        params.append(to_date.isoformat())

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        f"SELECT * FROM handovers {where} ORDER BY handover_date DESC", params
    ).fetchall()
    return [_handover_to_dict(dict(r), db) for r in rows]


@router.get("/export")
def export_handovers(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    department_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    """Xuất danh sách chứng từ bàn giao ra Excel."""
    if current["role"] == "chuyen_vien":
        department_id = current.get("department_id")

    clauses = []
    params: list = []
    if department_id:
        clauses.append("h.department_id = ?")
        params.append(department_id)
    if from_date:
        clauses.append("h.handover_date >= ?")
        params.append(from_date.isoformat())
    if to_date:
        clauses.append("h.handover_date <= ?")
        params.append(to_date.isoformat())

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    entries = db.execute(
        f"""SELECT de.id, de.transaction_date, de.sheet_count, de.entry_status,
                   h.handover_date, h.delivered_by,
                   d.name AS dept_name,
                   ks.ipcas_code, ks.full_name, ks.payment_username
            FROM document_entries de
            JOIN handovers h ON de.handover_id = h.id
            JOIN departments d ON h.department_id = d.id
            LEFT JOIN user_tttt ks ON de.staff_id = ks.id
            {where}
            ORDER BY h.handover_date DESC, d.name""",
        params,
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bàn giao chứng từ"

    hdr_fill = PatternFill("solid", fgColor="1565C0")
    hdr_font = Font(bold=True, color="FFFFFF")
    headers = ["STT", "Phòng", "Ngày bàn giao", "Ngày giao dịch",
               "User IPCAS", "Họ và tên", "Số tờ", "Trạng thái", "Người nộp"]
    widths  = [6, 20, 14, 14, 16, 25, 9, 16, 22]
    ws.append(headers)
    for cell, w in zip(ws[1], widths):
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[cell.column_letter].width = w

    for idx, e in enumerate(entries, 1):
        ho_date = date.fromisoformat(e["handover_date"]).strftime("%d/%m/%Y") if e["handover_date"] else ""
        tx_date = date.fromisoformat(e["transaction_date"]).strftime("%d/%m/%Y") if e["transaction_date"] else ""
        display_name = e["full_name"] or e["payment_username"] or ""
        ws.append([
            idx,
            e["dept_name"] or "",
            ho_date,
            tx_date,
            e["ipcas_code"] or "",
            display_name,
            e["sheet_count"],
            _STATUS_LABEL.get(e["entry_status"] or "confirmed", e["entry_status"] or ""),
            e["delivered_by"] or "",
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''chung_tu_ban_giao.xlsx"},
    )


@router.get("/{handover_id}")
def get_handover(
    handover_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    h = db.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
    if not h:
        raise HTTPException(404, "Không tìm thấy phiếu bàn giao")
    if current["role"] == "chuyen_vien" and h["department_id"] != current.get("department_id"):
        raise HTTPException(403, "Không có quyền xem phiếu của phòng khác")
    return _handover_to_dict(dict(h), db)


@router.post("/")
def create_handover(
    body: HandoverCreate,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_pho_phong_or_above),
):
    dept = db.execute("SELECT id FROM departments WHERE id = ?", (body.department_id,)).fetchone()
    if not dept:
        raise HTTPException(404, "Không tìm thấy phòng")

    cur = db.execute(
        "INSERT INTO handovers (department_id, handover_date, received_by_id, delivered_by, notes, status, created_at) VALUES (?,?,?,?,?,?,?)",
        (body.department_id, body.handover_date, current["id"], body.delivered_by, body.notes, "draft", str(_vn_now())),
    )
    h_id = cur.lastrowid

    for e in body.entries:
        s = db.execute("SELECT * FROM user_tttt WHERE id = ?", (e.staff_id,)).fetchone()
        if not s or s["department_id"] != body.department_id:
            s_code = s["ipcas_code"] if s else str(e.staff_id)
            raise HTTPException(400, f"Cán bộ {s_code} không thuộc phòng này")
        db.execute(
            "INSERT INTO document_entries (handover_id, staff_id, transaction_date, sheet_count, notes, entry_status, entered_by_id, confirmed_by_id, confirmed_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (h_id, e.staff_id, e.transaction_date, e.sheet_count, e.notes, EntryStatus.CONFIRMED, current["id"], current["id"], str(_vn_now())),
        )

    db.commit()
    h_row = db.execute("SELECT * FROM handovers WHERE id = ?", (h_id,)).fetchone()
    return _handover_to_dict(dict(h_row), db)


@router.post("/{handover_id}/entries")
def add_entry(
    handover_id: int,
    body: DocumentEntryIn,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_pho_phong_or_above),
):
    h = db.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
    if not h:
        raise HTTPException(404, "Không tìm thấy phiếu bàn giao")
    if h["status"] == "confirmed":
        raise HTTPException(400, "Phiếu đã xác nhận, không thể thêm")

    s = db.execute("SELECT * FROM user_tttt WHERE id = ?", (body.staff_id,)).fetchone()
    if not s or s["department_id"] != h["department_id"]:
        s_code = s["ipcas_code"] if s else str(body.staff_id)
        raise HTTPException(400, f"Cán bộ {s_code} không thuộc phòng của phiếu bàn giao này")

    cur = db.execute(
        "INSERT INTO document_entries (handover_id, staff_id, transaction_date, sheet_count, notes, entry_status, entered_by_id, confirmed_by_id, confirmed_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (handover_id, body.staff_id, body.transaction_date, body.sheet_count, body.notes, EntryStatus.CONFIRMED, current["id"], current["id"], str(_vn_now())),
    )
    db.commit()
    entry_id = cur.lastrowid
    row = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row)


@router.delete("/{handover_id}/entries/{entry_id}")
def delete_entry(
    handover_id: int,
    entry_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(require_pho_phong_or_above),
):
    row = db.execute(
        "SELECT id FROM document_entries WHERE id = ? AND handover_id = ?", (entry_id, handover_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy")
    db.execute("DELETE FROM entry_change_logs WHERE entry_id = ?", (entry_id,))
    db.execute("DELETE FROM document_entries WHERE id = ?", (entry_id,))
    db.commit()
    return {"message": "Đã xóa"}


@router.post("/{handover_id}/confirm")
def confirm_handover(
    handover_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(require_pho_phong_or_above),
):
    h = db.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
    if not h:
        raise HTTPException(404, "Không tìm thấy phiếu bàn giao")
    count = db.execute(
        "SELECT COUNT(*) FROM document_entries WHERE handover_id = ?", (handover_id,)
    ).fetchone()[0]
    if not count:
        raise HTTPException(400, "Phiếu chưa có chứng từ nào")
    db.execute("UPDATE handovers SET status='confirmed' WHERE id=?", (handover_id,))
    db.commit()
    return {"message": "Đã xác nhận phiếu bàn giao"}


@router.delete("/{handover_id}")
def delete_handover(
    handover_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(require_pho_phong_or_above),
):
    h = db.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
    if not h:
        raise HTTPException(404, "Không tìm thấy")
    if h["status"] == "confirmed":
        raise HTTPException(400, "Không thể xóa phiếu đã xác nhận")

    entry_ids = [r["id"] for r in db.execute(
        "SELECT id FROM document_entries WHERE handover_id = ?", (handover_id,)
    ).fetchall()]
    if entry_ids:
        ph = ",".join("?" * len(entry_ids))
        db.execute(f"DELETE FROM entry_change_logs WHERE entry_id IN ({ph})", entry_ids)
    db.execute("DELETE FROM document_entries WHERE handover_id = ?", (handover_id,))
    db.execute("DELETE FROM handovers WHERE id = ?", (handover_id,))
    db.commit()
    return {"message": "Đã xóa phiếu bàn giao"}
