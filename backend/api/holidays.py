"""Quản lý ngày lễ — dùng để tính ngày làm việc thực trong đơn nghỉ phép"""
import sqlite3
from datetime import date as _date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from backend.database import get_db
from backend.core.deps import get_current_staff, require_admin

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
    year: Optional[int] = Query(None),
    _: dict = Depends(get_current_staff),
    db: sqlite3.Connection = Depends(get_db),
):
    if year:
        rows = db.execute(
            "SELECT * FROM public_holidays WHERE date >= ? AND date <= ? ORDER BY date",
            (f"{year}-01-01", f"{year}-12-31"),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM public_holidays ORDER BY date").fetchall()
    return [dict(r) for r in rows]


@router.post("/", response_model=HolidayOut)
def create_holiday(
    body: HolidayCreate,
    _: dict = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    existing = db.execute(
        "SELECT * FROM public_holidays WHERE date = ?", (body.date.isoformat(),)
    ).fetchone()
    if existing:
        raise HTTPException(400, f"Ngày {body.date} đã được thêm ({existing['name']})")
    cur = db.execute(
        "INSERT INTO public_holidays (date, name) VALUES (?, ?)",
        (body.date.isoformat(), body.name.strip()),
    )
    db.commit()
    row = db.execute("SELECT * FROM public_holidays WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.delete("/{holiday_id}")
def delete_holiday(
    holiday_id: int,
    _: dict = Depends(require_admin),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute("SELECT id FROM public_holidays WHERE id = ?", (holiday_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy ngày lễ")
    db.execute("DELETE FROM public_holidays WHERE id = ?", (holiday_id,))
    db.commit()
    return {"ok": True}
