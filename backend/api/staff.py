"""KSNB Staff management endpoints"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import KSNBStaff, LeaveRecord, Department
from backend.schemas import StaffCreate, StaffUpdate, StaffOut, LeaveCreate, LeaveOut
from backend.core.security import get_password_hash
from backend.core.deps import get_current_staff, require_admin

_ROLE_ORDER = case(
    {"admin": 0, "controller": 1, "hau_kiem_vien": 2, "chuyen_vien": 3, "viewer": 4},
    value=KSNBStaff.role,
    else_=9,
)

def _validate_dept(db: Session, role: str, department_id):
    """Validate department_id — bắt buộc với mọi role."""
    if not department_id:
        raise HTTPException(400, "Phải chọn phòng ban")
    dept = db.query(Department).filter(Department.id == department_id, Department.is_active == True).first()
    if not dept:
        raise HTTPException(400, "Phòng ban không tồn tại hoặc không còn hoạt động")
    if role == "chuyen_vien" and not dept.is_source:
        raise HTTPException(400, "Giao dịch viên chỉ thuộc phòng nguồn")

router = APIRouter(prefix="/api/staff", tags=["Staff"])


@router.get("/", response_model=List[StaffOut])
def list_staff(
    active_only: bool = True,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff)
):
    q = db.query(KSNBStaff)
    if active_only:
        q = q.filter(KSNBStaff.is_active == True)
    return q.order_by(_ROLE_ORDER, KSNBStaff.full_name).all()


@router.get("/{staff_id}", response_model=StaffOut)
def get_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff)
):
    s = db.query(KSNBStaff).get(staff_id)
    if not s:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    return s


@router.post("/", response_model=StaffOut)
def create_staff(
    body: StaffCreate,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_admin)
):
    if db.query(KSNBStaff).filter(KSNBStaff.username == body.username).first():
        raise HTTPException(400, "Username đã tồn tại")
    emp_code = body.employee_code or body.username
    if db.query(KSNBStaff).filter(KSNBStaff.employee_code == emp_code).first():
        raise HTTPException(400, "Mã nhân viên đã tồn tại")
    _validate_dept(db, body.role, body.department_id)
    s = KSNBStaff(
        employee_code=emp_code,
        full_name=body.full_name,
        role=body.role,
        department_id=body.department_id,
        username=body.username,
        pwd_hash=get_password_hash(body.password),
        phone=body.phone,
        email=body.email,
        start_date=body.start_date,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(
    staff_id: int,
    body: StaffUpdate,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_admin)
):
    s = db.query(KSNBStaff).get(staff_id)
    if not s:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    update_data = body.dict(exclude_none=True)
    new_role = update_data.get("role", str(s.role))
    new_dept = update_data.get("department_id", s.department_id)
    _validate_dept(db, new_role, new_dept)
    for field, val in update_data.items():
        setattr(s, field, val)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/{staff_id}")
def delete_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_admin)
):
    if staff_id == current.id:
        raise HTTPException(400, "Không thể vô hiệu hoá tài khoản của chính mình")
    s = db.query(KSNBStaff).get(staff_id)
    if not s:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    s.is_active = False
    db.commit()
    return {"message": "Đã vô hiệu hoá tài khoản"}


# ─── Leave records ───────────────────────────────────────────────────────────
@router.get("/{staff_id}/leaves", response_model=List[LeaveOut])
def list_leaves(
    staff_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff)
):
    return db.query(LeaveRecord).filter(LeaveRecord.staff_id == staff_id).order_by(
        LeaveRecord.start_date.desc()
    ).all()


@router.post("/{staff_id}/leaves", response_model=LeaveOut)
def create_leave(
    staff_id: int,
    body: LeaveCreate,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_admin)
):
    leave = LeaveRecord(staff_id=staff_id, **body.dict())
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


@router.put("/leaves/{leave_id}/approve")
def approve_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(require_admin)
):
    leave = db.query(LeaveRecord).get(leave_id)
    if not leave:
        raise HTTPException(404, "Không tìm thấy bản ghi nghỉ phép")
    leave.status = "approved"
    leave.approved_by_id = current.id
    db.commit()
    return {"message": "Đã phê duyệt"}
