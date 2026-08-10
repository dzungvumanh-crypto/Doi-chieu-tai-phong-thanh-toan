"""API thống kê phân lịch trực."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query

from backend.database import get_db
from backend.core.deps import require_feature
from backend.schemas.duty import PersonShiftCount, MonthlySummary, RotationStateOut
from backend.services.duty_schedule_service import (
    get_shift_count_by_person, get_monthly_summary, get_rotation_state,
)

router = APIRouter(prefix="/api/duty/stats", tags=["duty-stats"])


@router.get("/shift-count", response_model=list[PersonShiftCount])
def shift_count(
    year: int = Query(...),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("menu.duty_schedule")),
):
    return get_shift_count_by_person(db, year)


@router.get("/monthly-summary", response_model=MonthlySummary)
def monthly_summary(
    month: int = Query(..., ge=1, le=12),
    year:  int = Query(...),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("menu.duty_schedule")),
):
    return get_monthly_summary(db, month, year)


@router.get("/rotation-state", response_model=list[RotationStateOut])
def rotation_state(
    year:  int = Query(...),
    role:  Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("menu.duty_schedule")),
):
    return get_rotation_state(db, year, role)
