"""Departments & Source Users endpoints"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Department, SourceUser, KSNBStaff, DocumentEntry
from backend.schemas import DepartmentOut, SourceUserCreate, SourceUserOut
from backend.core.deps import get_current_staff, require_hkv_or_above

dept_router = APIRouter(prefix="/api/departments", tags=["Departments"])
user_router = APIRouter(prefix="/api/source-users", tags=["Source Users"])


# ─── Departments ─────────────────────────────────────────────────────────────
@dept_router.get("/", response_model=List[DepartmentOut])
def list_departments(db: Session = Depends(get_db), _: KSNBStaff = Depends(get_current_staff)):
    return db.query(Department).filter(Department.is_active == True).order_by(Department.name).all()


@dept_router.get("/{dept_id}", response_model=DepartmentOut)
def get_department(dept_id: int, db: Session = Depends(get_db), _: KSNBStaff = Depends(get_current_staff)):
    d = db.query(Department).get(dept_id)
    if not d:
        raise HTTPException(404, "Không tìm thấy phòng")
    return d


# ─── Source Users ─────────────────────────────────────────────────────────────
@user_router.get("/", response_model=List[SourceUserOut])
def list_source_users(
    department_id: int = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff)
):
    q = db.query(SourceUser)
    if department_id:
        q = q.filter(SourceUser.department_id == department_id)
    if active_only:
        q = q.filter(SourceUser.is_active == True)
    return q.order_by(SourceUser.user_code).all()


@user_router.post("/", response_model=SourceUserOut)
def create_source_user(
    body: SourceUserCreate,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_hkv_or_above)
):
    # Check dept exists
    dept = db.query(Department).get(body.department_id)
    if not dept:
        raise HTTPException(404, "Không tìm thấy phòng")
    u = SourceUser(**body.dict())
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@user_router.put("/{user_id}", response_model=SourceUserOut)
def update_source_user(
    user_id: int,
    body: SourceUserCreate,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_hkv_or_above)
):
    u = db.query(SourceUser).get(user_id)
    if not u:
        raise HTTPException(404, "Không tìm thấy user")
    u.user_code = body.user_code
    u.full_name = body.full_name
    u.vn_name = body.vn_name
    u.department_id = body.department_id
    u.is_active = body.is_active
    db.commit()
    db.refresh(u)
    return u


@user_router.delete("/{user_id}")
def delete_source_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(require_hkv_or_above)
):
    u = db.query(SourceUser).get(user_id)
    if not u:
        raise HTTPException(404, "Không tìm thấy cán bộ")
    # Soft delete — giữ toàn bộ lịch sử chứng từ, chỉ ẩn khỏi danh sách hoạt động
    u.is_active = False
    db.commit()
    return {"message": "Đã ẩn cán bộ"}
