"""Handover (Bàn giao chứng từ) endpoints"""
import calendar
from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract, or_
from sqlalchemy.exc import IntegrityError
from backend.database import get_db
from backend.models import (
    Handover, DocumentEntry, Department, SourceUser, KSNBStaff,
    EntryChangeLog, EntryChangeActionEnum, _vn_now,
)
from backend.schemas import (
    HandoverCreate, HandoverOut, DocumentEntryIn, DocumentEntryOut,
    GridEntryOut, GridResponse, EntryUpsertRequest, EntryHistoryOut, EntryHistoryItem,
)
from backend.core.deps import get_current_staff, require_controller, require_handover_write

router = APIRouter(prefix="/api/handovers", tags=["Handovers"])

# ─── Mapping hiển thị lịch sử ────────────────────────────────────────────────
_ACTION_LABEL = {
    "handover":   ("Bàn giao chứng từ",      "blue"),
    "edited_cv":  ("Sửa số tờ (GDV)",         "blue"),
    "confirmed":  ("Xác nhận đã nhận",         "green"),
    "borrowed":   ("Mượn lại chứng từ",        "orange"),
    "returned":   ("Xác nhận đã trả",          "green"),
    "edited_hkv": ("Sửa trực tiếp (HKV/KSV)", "purple"),
}

_STATUS_LABEL = {
    "pending_confirm": "Chờ xác nhận",
    "confirmed":       "Đã xác nhận",
    "borrowed":        "Đang mượn",
}

def _role_label(staff: KSNBStaff) -> str:
    role_map = {
        "admin": "Quản trị viên",
        "hau_kiem_vien": "Hậu kiểm viên",
        "controller": "Kiểm soát viên",
        "viewer": "Xem",
        "chuyen_vien": "Chuyên viên",
    }
    label = role_map.get(str(staff.role), str(staff.role))
    if str(staff.role) == "chuyen_vien":
        return "Giao dịch viên"
    return label


# ─── Grid ─────────────────────────────────────────────────────────────────────
@router.get("/grid", response_model=GridResponse)
def get_handover_grid(
    department_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_handover_write),
):
    # Chuyên viên chỉ được xem đúng phòng của mình
    if str(current.role) == "chuyen_vien" and current.department_id != department_id:
        raise HTTPException(403, "Chỉ được xem dữ liệu phòng của mình")

    days_in_month = calendar.monthrange(year, month)[1]

    # Lấy entries trước để biết user nào có dữ liệu trong tháng
    entries = db.query(DocumentEntry).join(SourceUser).filter(
        SourceUser.department_id == department_id,
        extract("year",  DocumentEntry.transaction_date) == year,
        extract("month", DocumentEntry.transaction_date) == month,
    ).all()

    # Hiển thị: user đang active + user đã ẩn nhưng có entries trong tháng này (giữ lịch sử)
    user_ids_with_entries = {e.source_user_id for e in entries}
    users = db.query(SourceUser).filter(
        SourceUser.department_id == department_id,
        or_(
            SourceUser.is_active == True,
            SourceUser.id.in_(user_ids_with_entries),
        ),
    ).order_by(SourceUser.user_code).all()

    # Build entered_by name lookup
    entered_by_ids = {e.entered_by_id for e in entries if e.entered_by_id}
    entered_by_map = {}
    if entered_by_ids:
        staffs = db.query(KSNBStaff).filter(KSNBStaff.id.in_(entered_by_ids)).all()
        entered_by_map = {s.id: s.full_name for s in staffs}

    grid_entries = [
        GridEntryOut(
            source_user_id=e.source_user_id,
            day=e.transaction_date.day,
            sheet_count=e.sheet_count,
            entry_id=e.id,
            entry_status=e.entry_status or "confirmed",
            entered_by_name=entered_by_map.get(e.entered_by_id) if e.entered_by_id else None,
        )
        for e in entries
    ]
    return GridResponse(users=users, entries=grid_entries, days_in_month=days_in_month)


# ─── Upsert (nhập/sửa ô grid) ────────────────────────────────────────────────
@router.put("/entry-upsert")
def upsert_entry(
    body: EntryUpsertRequest,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_handover_write),
):
    user = db.query(SourceUser).get(body.source_user_id)
    if not user:
        raise HTTPException(404, "Không tìm thấy cán bộ")

    is_cv = str(current.role) == "chuyen_vien"

    # Chuyên viên chỉ được nhập dữ liệu phòng của mình
    if is_cv and current.department_id != user.department_id:
        raise HTTPException(403, "Chỉ được nhập dữ liệu phòng của mình")

    dept_id = user.department_id

    # Tìm hoặc tạo handover cho (dept, date) — chống race condition bằng UNIQUE constraint
    handover = db.query(Handover).filter(
        Handover.department_id == dept_id,
        Handover.handover_date == body.date,
    ).first()
    if not handover:
        handover = Handover(
            department_id=dept_id,
            handover_date=body.date,
            received_by_id=None if is_cv else current.id,
            status="draft",
        )
        db.add(handover)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            handover = db.query(Handover).filter(
                Handover.department_id == dept_id,
                Handover.handover_date == body.date,
            ).first()

    # Tìm entry hiện tại
    entry = db.query(DocumentEntry).filter(
        DocumentEntry.handover_id == handover.id,
        DocumentEntry.source_user_id == body.source_user_id,
        DocumentEntry.transaction_date == body.date,
    ).first()

    if body.sheet_count > 0:
        if entry:
            old_count = entry.sheet_count
            # Xác định action log
            if is_cv:
                action = EntryChangeActionEnum.edited_cv if entry.entry_status == "confirmed" else EntryChangeActionEnum.handover
                new_status = "pending_confirm"
            else:
                action = EntryChangeActionEnum.edited_hkv
                new_status = entry.entry_status or "confirmed"  # HKV sửa không đổi status

            entry.sheet_count = body.sheet_count
            entry.entry_status = new_status
            entry.entered_by_id = current.id
            if not is_cv and entry.confirmed_by_id is None:
                entry.confirmed_by_id = current.id
                entry.confirmed_at = _vn_now()

            db.add(EntryChangeLog(
                entry_id=entry.id,
                action=action,
                performed_by_id=current.id,
                old_sheet_count=old_count,
                new_sheet_count=body.sheet_count,
            ))
        else:
            new_status = "pending_confirm" if is_cv else "confirmed"
            new_entry = DocumentEntry(
                handover_id=handover.id,
                source_user_id=body.source_user_id,
                transaction_date=body.date,
                sheet_count=body.sheet_count,
                entry_status=new_status,
                entered_by_id=current.id,
                confirmed_by_id=None if is_cv else current.id,
                confirmed_at=None if is_cv else _vn_now(),
            )
            db.add(new_entry)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                # Entry đã tồn tại (race condition) — fetch và update
                entry = db.query(DocumentEntry).filter(
                    DocumentEntry.handover_id == handover.id,
                    DocumentEntry.source_user_id == body.source_user_id,
                    DocumentEntry.transaction_date == body.date,
                ).first()
                if entry:
                    entry.sheet_count = body.sheet_count
                    entry.entry_status = new_status
                    entry.entered_by_id = current.id
                db.flush()
                new_entry = entry

            if new_entry and new_entry.id:
                db.add(EntryChangeLog(
                    entry_id=new_entry.id,
                    action=EntryChangeActionEnum.handover if is_cv else EntryChangeActionEnum.edited_hkv,
                    performed_by_id=current.id,
                    old_sheet_count=None,
                    new_sheet_count=body.sheet_count,
                ))
    else:
        if entry:
            # Chuyên viên chỉ xóa được ô đang pending (chưa ai confirm)
            if is_cv and entry.entry_status != "pending_confirm":
                raise HTTPException(400, "Không thể xóa chứng từ đã được xác nhận. Vui lòng liên hệ HKV/KSV.")
            db.delete(entry)

    db.commit()
    return {"ok": True}


# ─── Xác nhận đã nhận (HKV/KSV) ─────────────────────────────────────────────
@router.post("/entries/{entry_id}/confirm-received")
def confirm_received(
    entry_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_controller),
):
    entry = db.query(DocumentEntry).get(entry_id)
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry.entry_status != "pending_confirm":
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry.entry_status, entry.entry_status)}'. Chỉ xác nhận được khi đang chờ xác nhận.")

    entry.entry_status = "confirmed"
    entry.confirmed_by_id = current.id
    entry.confirmed_at = _vn_now()

    # Cập nhật received_by_id của handover nếu chưa có
    handover = db.query(Handover).get(entry.handover_id)
    if handover and handover.received_by_id is None:
        handover.received_by_id = current.id

    db.add(EntryChangeLog(
        entry_id=entry_id,
        action=EntryChangeActionEnum.confirmed,
        performed_by_id=current.id,
        new_sheet_count=entry.sheet_count,
    ))
    db.commit()
    return {"ok": True, "message": "Đã xác nhận nhận chứng từ"}


# ─── Mượn lại (Chuyên viên) ──────────────────────────────────────────────────
@router.post("/entries/{entry_id}/borrow")
def borrow_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_handover_write),
):
    entry = db.query(DocumentEntry).get(entry_id)
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry.entry_status != "confirmed":
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry.entry_status, entry.entry_status)}'. Chỉ mượn được chứng từ đã xác nhận.")

    # Chuyên viên chỉ mượn được chứng từ thuộc phòng mình
    if str(current.role) == "chuyen_vien":
        source_user = db.query(SourceUser).get(entry.source_user_id)
        if source_user and source_user.department_id != current.department_id:
            raise HTTPException(403, "Chỉ được mượn chứng từ thuộc phòng của mình")

    entry.entry_status = "borrowed"
    entry.borrowed_at = _vn_now()

    db.add(EntryChangeLog(
        entry_id=entry_id,
        action=EntryChangeActionEnum.borrowed,
        performed_by_id=current.id,
        new_sheet_count=entry.sheet_count,
    ))
    db.commit()
    return {"ok": True, "message": "Đã đánh dấu mượn chứng từ"}


# ─── Xác nhận đã trả (HKV/KSV) ───────────────────────────────────────────────
@router.post("/entries/{entry_id}/confirm-returned")
def confirm_returned(
    entry_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_controller),
):
    entry = db.query(DocumentEntry).get(entry_id)
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")
    if entry.entry_status != "borrowed":
        raise HTTPException(409, f"Trạng thái không hợp lệ: '{_STATUS_LABEL.get(entry.entry_status, entry.entry_status)}'. Chỉ xác nhận trả được khi đang mượn.")

    entry.entry_status = "confirmed"

    db.add(EntryChangeLog(
        entry_id=entry_id,
        action=EntryChangeActionEnum.returned,
        performed_by_id=current.id,
        new_sheet_count=entry.sheet_count,
    ))
    db.commit()
    return {"ok": True, "message": "Đã xác nhận trả chứng từ"}


# ─── Lịch sử thay đổi ────────────────────────────────────────────────────────
@router.get("/entries/{entry_id}/history", response_model=EntryHistoryOut)
def get_entry_history(
    entry_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    entry = db.query(DocumentEntry).options(
        joinedload(DocumentEntry.source_user)
    ).filter(DocumentEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Không tìm thấy chứng từ")

    # Chuyên viên chỉ được xem lịch sử chứng từ thuộc phòng mình
    if str(current.role) == "chuyen_vien":
        source_user = entry.source_user or db.query(SourceUser).get(entry.source_user_id)
        if source_user and source_user.department_id != current.department_id:
            raise HTTPException(403, "Không có quyền xem lịch sử chứng từ của phòng khác")

    logs = db.query(EntryChangeLog).options(
        joinedload(EntryChangeLog.performed_by)
    ).filter(
        EntryChangeLog.entry_id == entry_id
    ).order_by(EntryChangeLog.timestamp.desc()).all()

    history_items = []
    for log in logs:
        action_key = str(log.action.value) if hasattr(log.action, "value") else str(log.action)
        label, color = _ACTION_LABEL.get(action_key, (action_key, "blue"))

        # Thêm chi tiết số tờ vào label nếu có thay đổi
        if log.old_sheet_count is not None and log.new_sheet_count is not None and log.old_sheet_count != log.new_sheet_count:
            label = f"{label}: {log.old_sheet_count} → {log.new_sheet_count} tờ"
        elif log.new_sheet_count is not None and log.old_sheet_count is None:
            label = f"{label} — {log.new_sheet_count} tờ"

        performer = log.performed_by
        role_label = _role_label(performer) if performer else "?"
        performer_display = f"{performer.full_name} · {role_label}" if performer else "?"

        ts = log.timestamp
        timestamp_str = ts.strftime("%H:%M:%S  %d/%m/%Y") if ts else ""

        history_items.append(EntryHistoryItem(
            id=log.id,
            action=action_key,
            action_label=label,
            action_color=color,
            performed_by=performer.full_name if performer else "?",
            performed_by_role=performer_display,
            timestamp=timestamp_str,
            old_sheet_count=log.old_sheet_count,
            new_sheet_count=log.new_sheet_count,
        ))

    source_user = entry.source_user
    user_name = source_user.vn_name or source_user.full_name or source_user.user_code if source_user else f"ID {entry.source_user_id}"
    current_status = entry.entry_status or "confirmed"

    return EntryHistoryOut(
        entry_id=entry_id,
        source_user_name=user_name,
        transaction_date=entry.transaction_date.strftime("%d/%m/%Y"),
        sheet_count=entry.sheet_count,
        current_status=current_status,
        current_status_label=_STATUS_LABEL.get(current_status, current_status),
        logs=history_items,
    )


# ─── Danh sách handover ──────────────────────────────────────────────────────
@router.get("/", response_model=List[HandoverOut])
def list_handovers(
    department_id: Optional[int] = None,
    status: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff)
):
    # Chuyên viên chỉ được xem handover của phòng mình
    if str(current.role) == "chuyen_vien":
        department_id = current.department_id

    q = db.query(Handover).options(
        joinedload(Handover.department),
        joinedload(Handover.entries).joinedload(DocumentEntry.source_user)
    )
    if department_id:
        q = q.filter(Handover.department_id == department_id)
    if status:
        q = q.filter(Handover.status == status)
    if from_date:
        q = q.filter(Handover.handover_date >= from_date)
    if to_date:
        q = q.filter(Handover.handover_date <= to_date)
    return q.order_by(Handover.handover_date.desc()).all()


@router.get("/{handover_id}", response_model=HandoverOut)
def get_handover(
    handover_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff)
):
    h = db.query(Handover).options(
        joinedload(Handover.department),
        joinedload(Handover.entries).joinedload(DocumentEntry.source_user)
    ).filter(Handover.id == handover_id).first()
    if not h:
        raise HTTPException(404, "Không tìm thấy phiếu bàn giao")
    if str(current.role) == "chuyen_vien" and h.department_id != current.department_id:
        raise HTTPException(403, "Không có quyền xem phiếu của phòng khác")
    return h


@router.post("/", response_model=HandoverOut)
def create_handover(
    body: HandoverCreate,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_controller)
):
    dept = db.query(Department).get(body.department_id)
    if not dept:
        raise HTTPException(404, "Không tìm thấy phòng")

    h = Handover(
        department_id=body.department_id,
        handover_date=body.handover_date,
        received_by_id=current.id,
        delivered_by=body.delivered_by,
        notes=body.notes,
        status="draft"
    )
    db.add(h)
    db.flush()

    for e in body.entries:
        su = db.query(SourceUser).get(e.source_user_id)
        if not su or su.department_id != body.department_id:
            su_code = su.user_code if su else str(e.source_user_id)
            raise HTTPException(400, f"Cán bộ {su_code} không thuộc phòng này")
        entry = DocumentEntry(
            handover_id=h.id,
            source_user_id=e.source_user_id,
            transaction_date=e.transaction_date,
            sheet_count=e.sheet_count,
            notes=e.notes,
            entry_status="confirmed",
            entered_by_id=current.id,
            confirmed_by_id=current.id,
            confirmed_at=_vn_now(),
        )
        db.add(entry)

    db.commit()
    db.refresh(h)
    return get_handover(h.id, db, current)


@router.post("/{handover_id}/entries", response_model=DocumentEntryOut)
def add_entry(
    handover_id: int,
    body: DocumentEntryIn,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_controller)
):
    h = db.query(Handover).get(handover_id)
    if not h:
        raise HTTPException(404, "Không tìm thấy phiếu bàn giao")
    if h.status == "confirmed":
        raise HTTPException(400, "Phiếu đã xác nhận, không thể thêm")

    su = db.query(SourceUser).get(body.source_user_id)
    if not su or su.department_id != h.department_id:
        su_code = su.user_code if su else str(body.source_user_id)
        raise HTTPException(400, f"Cán bộ {su_code} không thuộc phòng của phiếu bàn giao này")

    entry = DocumentEntry(
        handover_id=handover_id,
        entry_status="confirmed",
        entered_by_id=current.id,
        confirmed_by_id=current.id,
        confirmed_at=_vn_now(),
        **body.dict()
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{handover_id}/entries/{entry_id}")
def delete_entry(
    handover_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    entry = db.query(DocumentEntry).filter(
        DocumentEntry.id == entry_id,
        DocumentEntry.handover_id == handover_id
    ).first()
    if not entry:
        raise HTTPException(404, "Không tìm thấy")
    db.delete(entry)
    db.commit()
    return {"message": "Đã xóa"}


@router.post("/{handover_id}/confirm")
def confirm_handover(
    handover_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    h = db.query(Handover).get(handover_id)
    if not h:
        raise HTTPException(404, "Không tìm thấy phiếu bàn giao")
    if not h.entries:
        raise HTTPException(400, "Phiếu chưa có chứng từ nào")
    h.status = "confirmed"
    db.commit()
    return {"message": "Đã xác nhận phiếu bàn giao"}


@router.delete("/{handover_id}")
def delete_handover(
    handover_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_controller)
):
    h = db.query(Handover).get(handover_id)
    if not h:
        raise HTTPException(404, "Không tìm thấy")
    if h.status == "confirmed":
        raise HTTPException(400, "Không thể xóa phiếu đã xác nhận")
    db.delete(h)
    db.commit()
    return {"message": "Đã xóa phiếu bàn giao"}
