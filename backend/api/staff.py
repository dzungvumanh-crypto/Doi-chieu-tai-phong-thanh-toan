"""KSNB Staff management endpoints"""
import sqlite3
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db
from backend.schemas import StaffCreate, StaffUpdate, StaffOut
from backend.core.security import get_password_hash
from backend.core.deps import get_current_staff, require_admin

router = APIRouter(prefix="/api/staff", tags=["Staff"])

_ROLE_ORDER_SQL = """
    CASE role
        WHEN 'giam_doc'      THEN 0
        WHEN 'pho_giam_doc'  THEN 1
        WHEN 'admin'         THEN 2
        WHEN 'truong_phong'  THEN 3
        WHEN 'pho_phong'     THEN 4
        WHEN 'hau_kiem_vien' THEN 5
        WHEN 'chuyen_vien'   THEN 6
        ELSE 9
    END
"""


def _validate_dept(db: sqlite3.Connection, role: str, department_id):
    if not department_id:
        raise HTTPException(400, "Phải chọn phòng ban")
    dept = db.execute(
        "SELECT * FROM departments WHERE id = ? AND is_active = 1", (department_id,)
    ).fetchone()
    if not dept:
        raise HTTPException(400, "Phòng ban không tồn tại hoặc không còn hoạt động")
    if role == "chuyen_vien" and not dept["is_source"]:
        raise HTTPException(400, "Chuyên viên chỉ thuộc phòng nguồn")
    if role in ("giam_doc", "pho_giam_doc") and dept["is_source"]:
        raise HTTPException(400, "Giám đốc / Phó Giám đốc phải thuộc Ban Giám đốc")


@router.get("/", response_model=List[StaffOut])
def list_staff(
    active_only: bool = True,
    department_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    clauses = []
    params = []
    if active_only:
        clauses.append("is_active = 1")
    if department_id:
        clauses.append("department_id = ?")
        params.append(department_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        f"SELECT * FROM ksnb_staff {where} ORDER BY {_ROLE_ORDER_SQL}, full_name", params
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{staff_id}", response_model=StaffOut)
def get_staff(
    staff_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    row = db.execute("SELECT * FROM ksnb_staff WHERE id = ?", (staff_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    return dict(row)


@router.post("/", response_model=StaffOut)
def create_staff(
    body: StaffCreate,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(require_admin),
):
    if db.execute("SELECT id FROM ksnb_staff WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(400, "Username đã tồn tại")
    emp_code = body.employee_code or body.username
    if db.execute("SELECT id FROM ksnb_staff WHERE employee_code = ?", (emp_code,)).fetchone():
        raise HTTPException(400, "Mã nhân viên đã tồn tại")
    _validate_dept(db, body.role, body.department_id)
    cur = db.execute(
        """INSERT INTO ksnb_staff
           (employee_code, full_name, role, department_id, username, pwd_hash,
            phone, email, start_date, ipcas_code, payment_username, is_active)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
        (emp_code, body.full_name, body.role, body.department_id, body.username,
         get_password_hash(body.password), body.phone, body.email,
         body.start_date.isoformat() if body.start_date else None,
         body.ipcas_code, body.payment_username),
    )
    db.commit()
    row = db.execute("SELECT * FROM ksnb_staff WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(
    staff_id: int,
    body: StaffUpdate,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(require_admin),
):
    row = db.execute("SELECT * FROM ksnb_staff WHERE id = ?", (staff_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    update_data = body.dict(exclude_none=True)
    new_role = update_data.get("role", row["role"])
    new_dept = update_data.get("department_id", row["department_id"])
    _validate_dept(db, new_role, new_dept)
    if update_data:
        sets = ", ".join(f"{k} = ?" for k in update_data)
        params = list(update_data.values()) + [staff_id]
        db.execute(f"UPDATE ksnb_staff SET {sets} WHERE id = ?", params)
        db.commit()
    row = db.execute("SELECT * FROM ksnb_staff WHERE id = ?", (staff_id,)).fetchone()
    return dict(row)


@router.delete("/{staff_id}")
def delete_staff(
    staff_id: int,
    db: sqlite3.Connection = Depends(get_db),
    current: dict = Depends(require_admin),
):
    if staff_id == current["id"]:
        raise HTTPException(400, "Không thể vô hiệu hoá tài khoản của chính mình")
    row = db.execute("SELECT id FROM ksnb_staff WHERE id = ?", (staff_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    db.execute("UPDATE ksnb_staff SET is_active = 0 WHERE id = ?", (staff_id,))
    db.commit()
    return {"message": "Đã vô hiệu hoá tài khoản"}


# ─── Leave records (DEPRECATED — dùng /api/leaves/ thay thế) ────────────────
@router.get("/{staff_id}/leaves", deprecated=True)
def list_leaves_deprecated(
    staff_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: dict = Depends(get_current_staff),
):
    rows = db.execute(
        "SELECT * FROM leave_records WHERE staff_id = ? ORDER BY start_date DESC", (staff_id,)
    ).fetchall()
    return [dict(r) for r in rows]
