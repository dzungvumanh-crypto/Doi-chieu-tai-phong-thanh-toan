"""Quản lý ngày lễ — dùng để tính ngày làm việc thực trong đơn nghỉ phép"""
from datetime import date as _date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.deps import get_current_staff, require_admin
from backend.models import PublicHoliday

router = APIRouter()


class HolidayCreate(BaseModel):
    date: _date
    name: str


class HolidayOut(BaseModel):
    id: int
    date: _date
    name: str
    class Config: from_attributes = True


@router.get("/", response_model=List[HolidayOut])
def list_holidays(
    year: Optional[int] = Query(None, description="Lọc theo năm"),
    _: object = Depends(get_current_staff),
    db: Session = Depends(get_db),
):
    q = db.query(PublicHoliday)
    if year:
        q = q.filter(
            PublicHoliday.date >= _date(year, 1, 1),
            PublicHoliday.date <= _date(year, 12, 31),
        )
    return q.order_by(PublicHoliday.date).all()


@router.post("/", response_model=HolidayOut)
def create_holiday(
    body: HolidayCreate,
    _: object = Depends(require_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(PublicHoliday).filter(PublicHoliday.date == body.date).first()
    if existing:
        raise HTTPException(400, f"Ngày {body.date} đã được thêm ({existing.name})")
    holiday = PublicHoliday(date=body.date, name=body.name.strip())
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


@router.delete("/{holiday_id}")
def delete_holiday(
    holiday_id: int,
    _: object = Depends(require_admin),
    db: Session = Depends(get_db),
):
    holiday = db.get(PublicHoliday, holiday_id)
    if not holiday:
        raise HTTPException(404, "Không tìm thấy ngày lễ")
    db.delete(holiday)
    db.commit()
    return {"ok": True}
