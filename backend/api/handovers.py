"""Handover (Bàn giao chứng từ) endpoints"""
import calendar
import io
import sqlite3
from datetime import date
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl.styles import Alignment, Font, PatternFill

from backend.core.deps import get_current_staff, require_feature
from backend.core.enums import EntryStatus, StaffRole
from backend.database import get_db, _vn_now
from backend.schemas.handovers import (
    BorrowRequest, EntryHistoryItem, EntryHistoryOut,
    EntryUpsertRequest, GridEntryOut, GridResponse, HandbackRequest,
    RejectRequest,
)

router = APIRouter(prefix="/api/handovers", tags=["Handovers"])


# ─── Phòng của cán bộ theo lịch sử đổi phòng ─────────────────────────────────
def _dept_at(db: sqlite3.Connection, staff_id: int, date_iso: str):
    """Phòng cán bộ thuộc về tại một ngày (dòng lịch sử mới nhất còn hiệu lực)."""
    row = db.execute(
        """SELECT department_id FROM staff_department_history
           WHERE staff_id = ? AND effective_from <= ?
           ORDER BY effective_from DESC, id DESC LIMIT 1""",
        (staff_id, date_iso),
    ).fetchone()
    if row:
        return row["department_id"]
    u = db.execute("SELECT department_id FROM user_tttt WHERE id = ?", (staff_id,)).fetchone()
    return u["department_id"] if u else None

# ─── Mapping hiển thị lịch sử ────────────────────────────────────────────────
_ACTION_LABEL = {
    "handover":           ("Bàn giao chứng từ",       "blue"),
    "edited_cv":          ("Sửa số tờ (CV)",           "blue"),
    "confirmed":          ("Xác nhận đã nhận",          "green"),
    "borrow_requested":   ("Yêu cầu mượn lại",          "orange"),
    "borrowed":           ("Xác nhận cho mượn",         "orange"),
    "returned":           ("Bàn giao lại",               "blue"),
    "edited_hkv":         ("HKV sửa trực tiếp",          "purple"),
    "rejected_borrow":    ("Từ chối yêu cầu mượn",      "red"),
    "rejected_return":    ("Từ chối bàn giao lại",       "red"),
    "rejected_handover":  ("Từ chối chứng từ mới",       "red"),
}

_STATUS_LABEL = {
    EntryStatus.PENDING:   "Chờ xác nhận",
    EntryStatus.CONFIRMED: "Đã xác nhận",
    EntryStatus.BORROWED:  "Đang mượn",
    EntryStatus.REJECTED:  "Bị từ chối",
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


# ─── Grid ─────────────────────────────────────────────────────────────────────
@router.get("/grid", response_model=GridResponse)
def get_handover_grid(
    department_id: int,
    year: int,
    month: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("menu.handovers")),
):
    days_in_month = calendar.monthrange(year, month)[1]
    period_start = date(year, month, 1).isoformat()
    period_end = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)).isoformat()

    # Entries trong tháng — lọc theo phòng ĐÓNG BĂNG trong phiếu bàn giao
    # (handovers.department_id), KHÔNG theo phòng hiện tại của user. Nhờ vậy chứng
    # từ của cán bộ đã chuyển phòng vẫn nằm ở phòng cũ cho các tháng trước khi chuyển.
    entry_rows = db.execute(
        """SELECT de.id, de.handover_id, de.staff_id, de.transaction_date, de.sheet_count,
                  de.entry_status, de.entered_by_id
           FROM document_entries de
           JOIN handovers h ON de.handover_id = h.id
           WHERE h.department_id = ?
             AND de.staff_id IS NOT NULL
             AND de.transaction_date >= ? AND de.transaction_date < ?""",
        (department_id, period_start, period_end),
    ).fetchall()

    staff_ids_with_entries = {e["staff_id"] for e in entry_rows if e["staff_id"]}
    entered_by_ids = {e["entered_by_id"] for e in entry_rows if e["entered_by_id"]}

    # Cán bộ TỪNG thuộc phòng này trong bất kỳ ngày nào của tháng (theo lịch sử đổi
    # phòng) → hiện dòng trống để có thể nhập bù. Khoảng của mỗi mốc lịch sử là
    # [effective_from, mốc kế tiếp); giao với tháng ⇔ eff < period_end và (kế tiếp
    # NULL hoặc kế tiếp > period_start).
    overlap_rows = db.execute(
        """WITH hist AS (
               SELECT staff_id, department_id, effective_from,
                      LEAD(effective_from) OVER (
                          PARTITION BY staff_id ORDER BY effective_from, id
                      ) AS next_from
               FROM staff_department_history
           )
           SELECT DISTINCT staff_id FROM hist
           WHERE department_id = ?
             AND effective_from < ?
             AND (next_from IS NULL OR next_from > ?)""",
        (department_id, period_end, period_start),
    ).fetchall()
    overlap_ids = {r["staff_id"] for r in overlap_rows}

    # Staff rows: (thuộc phòng tháng đó & active) HOẶC có chứng từ (bất kể active).
    # CHỈ giao dịch viên (chuyen_vien) — trưởng/phó phòng, HKV, GĐ, admin không lên lưới.
    _GRID_ROLE = StaffRole.CHUYEN_VIEN.value
    eligible_ids = overlap_ids | staff_ids_with_entries
    if eligible_ids:
        ph = ",".join("?" * len(eligible_ids))
        if staff_ids_with_entries:
            ph2 = ",".join("?" * len(staff_ids_with_entries))
            user_rows = db.execute(
                f"SELECT * FROM user_tttt WHERE role = '{_GRID_ROLE}'"
                f"   AND id IN ({ph})"
                f"   AND (is_active = 1 OR id IN ({ph2}))"
                f" ORDER BY ipcas_code",
                list(eligible_ids) + list(staff_ids_with_entries),
            ).fetchall()
        else:
            user_rows = db.execute(
                f"SELECT * FROM user_tttt WHERE role = '{_GRID_ROLE}'"
                f"   AND id IN ({ph}) AND is_active = 1 ORDER BY ipcas_code",
                list(eligible_ids),
            ).fetchall()
    else:
        user_rows = []

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
    current: dict = Depends(require_feature("handovers.save_entry")),
):
    staff_row = db.execute("SELECT * FROM user_tttt WHERE id = ?", (body.staff_id,)).fetchone()
    if not staff_row:
        raise HTTPException(404, "Không tìm thấy cán bộ")

    # Chỉ giao dịch viên mới có chứng từ bàn giao — chặn tận gốc, không để lọt entry rác
    if staff_row["role"] != StaffRole.CHUYEN_VIEN.value:
        raise HTTPException(400, "Chỉ giao dịch viên mới có chứng từ bàn giao")

    # User có quyền confirm entry → tạo entry ở trạng thái CONFIRMED ngay
    can_confirm = current["role"] == "admin" or bool(db.execute(
        """SELECT 1 FROM group_features gf
           JOIN group_members gm ON gm.group_id = gf.group_id
           JOIN user_groups g ON g.id = gm.group_id AND g.is_active = 1
           WHERE gm.staff_id = ? AND gf.feature_code = 'handovers.confirm_entry'
           LIMIT 1""",
        (current["id"],),
    ).fetchone())

    # Phòng của chứng từ = phòng cán bộ thuộc về TẠI NGÀY GIAO DỊCH (không phải phòng
    # hiện tại) → nhập bù cho cán bộ đã chuyển phòng vẫn vào đúng phòng cũ.
    dept_id = _dept_at(db, body.staff_id, body.date.isoformat()) or staff_row["department_id"]

    # ── Get/create handover (INSERT OR IGNORE để chống race condition) ──
    db.execute(
        "INSERT OR IGNORE INTO handovers (department_id, handover_date, received_by_id, status, created_at) VALUES (?,?,?,?,?)",
        (dept_id, body.date, None if not can_confirm else current["id"], "draft", str(_vn_now())),
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
            if not can_confirm:
                if entry_row["entry_status"] in (EntryStatus.CONFIRMED, EntryStatus.BORROWED):
                    raise HTTPException(403, "Chứng từ đã được xác nhận, không thể sửa trực tiếp")
                action = "handover"
                new_status = EntryStatus.PENDING
            else:
                action = "edited_hkv"
                new_status = EntryStatus.CONFIRMED

            set_extra, params_extra = "", []
            if can_confirm and entry_row["confirmed_by_id"] is None:
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
            new_status = EntryStatus.PENDING if not can_confirm else EntryStatus.CONFIRMED
            # Dùng INSERT thường (không IGNORE) để lỗi duplicate nổi lên thay vì âm thầm bỏ qua
            db.execute(
                "INSERT INTO document_entries (handover_id, staff_id, transaction_date, sheet_count, entry_status, entered_by_id, confirmed_by_id, confirmed_at) VALUES (?,?,?,?,?,?,?,?)",
                (handover_id, body.staff_id, body.date, body.sheet_count, new_status, current["id"],
                 None if not can_confirm else current["id"], None if not can_confirm else str(_vn_now())),
            )
            entry_row = db.execute(
                "SELECT * FROM document_entries WHERE handover_id = ? AND staff_id = ? AND transaction_date = ?",
                (handover_id, body.staff_id, body.date),
            ).fetchone()
            if entry_row:
                db.execute(
                    "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, old_sheet_count, new_sheet_count, timestamp) VALUES (?,?,?,?,?,?)",
                    (entry_row["id"], "handover" if not can_confirm else "edited_hkv", current["id"], None, body.sheet_count, str(_vn_now())),
                )
            else:
                raise HTTPException(500, "Không thể lưu chứng từ — vui lòng thử lại")
    else:
        if entry_row:
            if not can_confirm and entry_row["entry_status"] not in (EntryStatus.PENDING, EntryStatus.REJECTED):
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
    current: dict = Depends(require_feature("handovers.confirm_entry")),
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
    current: dict = Depends(require_feature("handovers.borrow")),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.CONFIRMED:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ mượn được chứng từ đã xác nhận.")

    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "Vui lòng nhập lý do mượn")

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
    current: dict = Depends(require_feature("handovers.handback")),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.BORROWED:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ bàn giao lại được khi đang mượn.")

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
def confirm_returned(entry_id: int, _: dict = Depends(get_current_staff)):
    raise HTTPException(410, "Endpoint đã ngừng sử dụng. Dùng /handback + /confirm-received")


# ─── Từ chối (HKV/KSV) ───────────────────────────────────────────────────────
@router.post("/entries/{entry_id}/reject")
def reject_entry(
    entry_id: int,
    body: RejectRequest,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("handovers.reject_entry")),
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

    # Chứng từ mới chưa xác nhận → từ chối → giữ entry + log để lưu lịch sử
    db.execute(
        "UPDATE document_entries SET entry_status=? WHERE id=?",
        (EntryStatus.REJECTED, entry_id),
    )
    db.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, notes, timestamp) VALUES (?,?,?,?,?,?)",
        (entry_id, "rejected_handover", current["id"], entry["sheet_count"], reason, str(_vn_now())),
    )
    db.commit()
    return {"ok": True, "message": "Đã từ chối chứng từ. Cán bộ có thể nộp lại."}


# ─── Nộp lại chứng từ bị từ chối (GDV) ───────────────────────────────────────
@router.post("/entries/{entry_id}/resubmit")
def resubmit_entry(
    entry_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_feature("handovers.save_entry")),
):
    entry = db.execute("SELECT * FROM document_entries WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry["entry_status"] != EntryStatus.REJECTED:
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry['entry_status'], entry['entry_status'])}'. Chỉ nộp lại được chứng từ bị từ chối.")

    db.execute(
        "UPDATE document_entries SET entry_status=?, entered_by_id=? WHERE id=?",
        (EntryStatus.PENDING, current["id"], entry_id),
    )
    db.execute(
        "INSERT INTO entry_change_logs (entry_id, action, performed_by_id, new_sheet_count, timestamp) VALUES (?,?,?,?,?)",
        (entry_id, "handover", current["id"], entry["sheet_count"], str(_vn_now())),
    )
    db.commit()
    return {"ok": True, "message": "Đã nộp lại chứng từ, chờ HKV xác nhận"}


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


@router.get("/export")
def export_handovers(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    department_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(get_current_staff),
):
    """Xuất danh sách chứng từ bàn giao ra Excel."""
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
