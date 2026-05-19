"""Departments endpoints"""
import sqlite3
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db
from backend.schemas.common import DepartmentOut
from backend.core.deps import get_current_staff

dept_router = APIRouter(prefix="/api/departments", tags=["Departments"])


@dept_router.get("/", response_model=List[DepartmentOut])
def list_departments(db: sqlite3.Connection = Depends(get_db), _: dict = Depends(get_current_staff)):
    rows = db.execute(
        "SELECT * FROM departments WHERE is_active = 1 ORDER BY CASE code WHEN 'BGD' THEN 0 ELSE 1 END, name"
    ).fetchall()
    return [dict(r) for r in rows]


@dept_router.get("/{dept_id}", response_model=DepartmentOut)
def get_department(dept_id: int, db: sqlite3.Connection = Depends(get_db), _: dict = Depends(get_current_staff)):
    row = db.execute("SELECT * FROM departments WHERE id = ?", (dept_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy phòng")
    return dict(row)
