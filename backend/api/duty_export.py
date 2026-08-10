"""API xuất Excel lịch trực theo tuần."""
import sqlite3
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from backend.database import get_db
from backend.core.deps import require_feature
from backend.services.duty_schedule_service import get_shifts_for_week
from backend.services.duty_constraint_service import (
    get_shift_config, list_special_days,
)
from backend.services.duty_export_service import build_week_excel
from backend.services.duty_calendar_utils import get_week_dates

router = APIRouter(prefix="/api/duty/export", tags=["duty-export"])


@router.get("/week")
def export_week(
    week_start: str = Query(..., description="Ngày thứ 2 đầu tuần (YYYY-MM-DD)"),
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(require_feature("duty.export")),
):
    """Xuất lịch trực tuần ra file Excel (.xlsx)."""
    year = int(week_start[:4])
    dates = get_week_dates(week_start)
    week_end_str = dates[-1]  # Thứ 6

    week_start_date = date.fromisoformat(week_start)
    week_end_date   = date.fromisoformat(week_end_str)

    shifts = get_shifts_for_week(db, week_start)
    config = get_shift_config(db, year)
    signer_name = (config or {}).get("signer_name") or "Nguyễn Quốc Hùng"

    # Lấy ngày lễ trong tuần
    holiday_rows = list_special_days(db, day_type="holiday", year=year)
    holiday_map = {h["date"]: h.get("label", "") for h in holiday_rows
                   if week_start <= h["date"] <= week_end_str}

    file_bytes = build_week_excel(
        shifts, week_start_date, week_end_date,
        signer_name=signer_name,
        holiday_map=holiday_map,
    )

    filename = f"lich_truc_{week_start.replace('-', '')}.xlsx"
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
