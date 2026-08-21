"""API phân lịch trực: sinh lịch, CRUD ca, xác nhận."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.database import get_db
from backend.core.deps import get_current_staff
from backend.schemas.duty import (
    ShiftOut, ShiftUpdate, ShiftUpdateResult, MessageOut,
    GenerateRequest, GenerateResult,
    GenerateWeekRequest, GenerateWeekResult,
)
from backend.services.duty_rules import validate_shift_members
from backend.services.duty_schedule_service import (
    get_shifts_for_month, get_shifts_for_week, get_shifts_for_date,
    get_shift_by_id, update_shift, confirm_shift, unconfirm_shift,
    confirm_shifts_for_week, delete_shifts_for_week, delete_shift,
)
from backend.services.duty_scheduler_engine import (
    generate_schedule, generate_schedule_for_week, reset_rotation,
)

router = APIRouter(prefix="/api/duty/schedule", tags=["duty-schedule"])


# ── Read ──────────────────────────────────────────────────────────────────────

@router.get("/month", response_model=list[ShiftOut])
def shifts_month(
    month: int = Query(..., ge=1, le=12),
    year:  int = Query(...),
    status: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return get_shifts_for_month(db, month, year, status)


@router.get("/week", response_model=list[ShiftOut])
def shifts_week(
    week_start: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return get_shifts_for_week(db, week_start)


@router.get("/date/{date_str}", response_model=list[ShiftOut])
def shifts_date(
    date_str: str,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return get_shifts_for_date(db, date_str)


@router.get("/{shift_id}", response_model=ShiftOut)
def shift_detail(
    shift_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    shift = get_shift_by_id(db, shift_id)
    if not shift:
        raise HTTPException(404, "Không tìm thấy ca trực")
    return shift


# ── Generate ──────────────────────────────────────────────────────────────────

@router.post("/generate-week", response_model=GenerateWeekResult)
def do_generate_week(
    body: GenerateWeekRequest,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return generate_schedule_for_week(
        db, body.week_start,
        overwrite_draft=body.overwrite_draft,
        overwrite_confirmed=body.overwrite_confirmed,
    )


@router.post("/generate-month", response_model=GenerateResult)
def do_generate_month(
    body: GenerateRequest,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return generate_schedule(db, body.month, body.year, body.overwrite_draft)


# ── Update ────────────────────────────────────────────────────────────────────

@router.put("/{shift_id}", response_model=ShiftUpdateResult)
def edit_shift(
    shift_id: int,
    body: ShiftUpdate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    """Sửa tay ca trực.
    Vi phạm luật CỨNG (1 Lãnh đạo + 2 nhân viên) → 400, không ghi gì.
    Vi phạm luật MỀM → vẫn ghi, trả kèm cảnh báo để người dùng biết."""
    shift = get_shift_by_id(db, shift_id)
    if not shift:
        raise HTTPException(404, "Không tìm thấy ca trực")

    loi_cung, canh_bao, _ns = validate_shift_members(
        db, shift["shift_date"], shift["shift_type"],
        body.leader_ids, body.nv_chinh_ids, body.nv_phu_ids,
    )
    if loi_cung:
        raise HTTPException(400, " ".join(loi_cung))

    result = update_shift(db, shift_id, body.leader_ids, body.nv_chinh_ids, body.nv_phu_ids)
    if not result:
        raise HTTPException(404, "Không tìm thấy ca trực")
    return {"shift": result, "warnings": canh_bao}


@router.post("/{shift_id}/confirm", response_model=ShiftOut)
def do_confirm(
    shift_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    result = confirm_shift(db, shift_id)
    if not result:
        raise HTTPException(404, "Không tìm thấy ca trực")
    return result


@router.post("/{shift_id}/unconfirm", response_model=ShiftOut)
def do_unconfirm(
    shift_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    result = unconfirm_shift(db, shift_id)
    if not result:
        raise HTTPException(404, "Không tìm thấy ca trực")
    return result


@router.post("/confirm-week", response_model=MessageOut)
def do_confirm_week(
    week_start: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    count = confirm_shifts_for_week(db, week_start)
    return {"message": f"Đã xác nhận {count} ca"}


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/week", response_model=MessageOut)
def do_delete_week(
    week_start: str = Query(...),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    count = delete_shifts_for_week(db, week_start)
    return {"message": f"Đã xóa {count} ca"}


@router.delete("/{shift_id}", response_model=MessageOut)
def do_delete_shift(
    shift_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    if not delete_shift(db, shift_id):
        raise HTTPException(404, "Không tìm thấy ca trực")
    return {"message": "Đã xóa"}


# ── Rotation Management ───────────────────────────────────────────────────────

@router.post("/rotation/reset", response_model=MessageOut)
def do_reset_rotation(
    year: int = Query(...),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    reset_rotation(db, year)
    return {"message": f"Đã reset vòng xoay năm {year}"}
