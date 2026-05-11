"""Quản lý ủy quyền Giám đốc → Phó Giám đốc"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.deps import get_current_staff, require_admin, TONG_HOP_CODES
from backend.models import KSNBStaff, DelegationRecord, Department
from backend.models import _vn_now
from backend.schemas import DelegationCreate, DelegationOut

router = APIRouter()


def _deleg_to_out(d: DelegationRecord) -> dict:
    return {
        "id":                d.id,
        "giam_doc_id":       d.giam_doc_id,
        "giam_doc_name":     d.giam_doc.full_name if d.giam_doc else "",
        "pho_giam_doc_id":   d.pho_giam_doc_id,
        "pho_giam_doc_name": d.pho_giam_doc.full_name if d.pho_giam_doc else "",
        "start_date":        d.start_date,
        "end_date":          d.end_date,
        "note":              d.note,
        "is_active":         d.is_active,
        "created_by_name":   d.created_by.full_name if d.created_by else "",
        "created_at":        d.created_at,
    }


@router.post("/", response_model=DelegationOut)
def create_delegation(
    body: DelegationCreate,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    """Tạo ủy quyền — Admin hoặc staff thuộc phòng Tổng hợp."""
    role = current.role
    is_tong_hop = False
    if current.department_id:
        dept = db.query(Department).filter(Department.id == current.department_id).first()
        if dept and dept.code.upper() in TONG_HOP_CODES:
            is_tong_hop = True
    if role != "admin" and not is_tong_hop:
        raise HTTPException(403, "Chỉ Admin hoặc phòng Tổng hợp mới được tạo ủy quyền")

    gd = db.query(KSNBStaff).filter(
        KSNBStaff.id == body.giam_doc_id,
        KSNBStaff.role == "giam_doc",
        KSNBStaff.is_active == True,
    ).first()
    if not gd:
        raise HTTPException(400, "Giám đốc không tồn tại hoặc không còn hoạt động")

    pgd = db.query(KSNBStaff).filter(
        KSNBStaff.id == body.pho_giam_doc_id,
        KSNBStaff.role == "pho_giam_doc",
        KSNBStaff.is_active == True,
    ).first()
    if not pgd:
        raise HTTPException(400, "Phó Giám đốc không tồn tại hoặc không còn hoạt động")

    if body.end_date < body.start_date:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu")

    # ── Kiểm tra overlap ──
    overlap = db.query(DelegationRecord).filter(
        DelegationRecord.pho_giam_doc_id == body.pho_giam_doc_id,
        DelegationRecord.is_active == True,
        DelegationRecord.start_date <= body.end_date,
        DelegationRecord.end_date >= body.start_date,
    ).first()
    if overlap:
        raise HTTPException(409, "PGĐ này đã có ủy quyền trong khoảng thời gian trên")

    deleg = DelegationRecord(
        giam_doc_id     = body.giam_doc_id,
        pho_giam_doc_id = body.pho_giam_doc_id,
        start_date      = body.start_date,
        end_date        = body.end_date,
        note            = body.note,
        created_by_id   = current.id,
        is_active       = True,
        created_at      = _vn_now(),
    )
    db.add(deleg)
    db.commit()
    db.refresh(deleg)
    return _deleg_to_out(deleg)


@router.get("/", response_model=List[DelegationOut])
def list_delegations(
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    q = db.query(DelegationRecord).order_by(DelegationRecord.created_at.desc())
    # Chỉ admin/GĐ/PGĐ/HKV thấy toàn bộ; role khác chỉ thấy đang hiệu lực
    if current.role not in ("admin", "hau_kiem_vien", "giam_doc", "pho_giam_doc"):
        q = q.filter(DelegationRecord.is_active == True)
    return [_deleg_to_out(d) for d in q.all()]


@router.patch("/{deleg_id}/deactivate", response_model=DelegationOut)
def deactivate_delegation(
    deleg_id: int,
    db: Session = Depends(get_db),
    current: KSNBStaff = Depends(get_current_staff),
):
    role = current.role
    is_tong_hop = False
    if current.department_id:
        dept = db.query(Department).filter(Department.id == current.department_id).first()
        if dept and dept.code.upper() in TONG_HOP_CODES:
            is_tong_hop = True
    if role != "admin" and not is_tong_hop:
        raise HTTPException(403, "Chỉ Admin hoặc phòng Tổng hợp mới được hủy ủy quyền")

    deleg = db.query(DelegationRecord).filter(DelegationRecord.id == deleg_id).first()
    if not deleg:
        raise HTTPException(404, "Không tìm thấy bản ghi ủy quyền")
    if not deleg.is_active:
        raise HTTPException(400, "Bản ghi ủy quyền đã được hủy trước đó")

    deleg.is_active = False
    db.commit()
    db.refresh(deleg)
    return _deleg_to_out(deleg)


@router.get("/staff/giam-doc", response_model=List[dict])
def list_giam_doc(
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff),
):
    """Danh sách Giám đốc active (cho dropdown frontend)."""
    staff = db.query(KSNBStaff).filter(
        KSNBStaff.role == "giam_doc",
        KSNBStaff.is_active == True,
    ).all()
    return [{"id": s.id, "full_name": s.full_name, "employee_code": s.employee_code} for s in staff]


@router.get("/staff/pho-giam-doc", response_model=List[dict])
def list_pho_giam_doc(
    db: Session = Depends(get_db),
    _: KSNBStaff = Depends(get_current_staff),
):
    """Danh sách Phó Giám đốc active (cho dropdown frontend)."""
    staff = db.query(KSNBStaff).filter(
        KSNBStaff.role == "pho_giam_doc",
        KSNBStaff.is_active == True,
    ).all()
    return [{"id": s.id, "full_name": s.full_name, "employee_code": s.employee_code} for s in staff]
