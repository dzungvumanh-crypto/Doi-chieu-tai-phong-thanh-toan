"""API quản lý nhân viên phân lịch trực Phòng Thanh toán."""
import sqlite3
from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_db
from backend.core.deps import require_feature
from backend.schemas.duty import DutyStaffOut, DutyStaffMetaIn
from backend.services.duty_staff_service import get_all_staff, get_staff_by_id, upsert_staff_meta

router = APIRouter(prefix="/api/duty/staff", tags=["duty-staff"])


@router.get("", response_model=list[DutyStaffOut])
def list_duty_staff(
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("menu.duty_schedule")),
):
    return get_all_staff(db)


@router.post("/{user_id}/meta", response_model=DutyStaffOut)
def update_staff_meta(
    user_id: int,
    body: DutyStaffMetaIn,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("duty.manage_staff")),
):
    staff = get_staff_by_id(db, user_id)
    if not staff:
        raise HTTPException(404, "Không tìm thấy nhân viên Phòng Thanh toán")
    return upsert_staff_meta(
        db, user_id,
        can_do_sp=body.can_do_sp,
        is_on_project=body.is_on_project,
        display_order=body.display_order,
    )
