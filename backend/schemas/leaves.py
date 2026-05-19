from datetime import date, datetime
from typing import Optional, Literal
from pydantic import BaseModel


# ─── Leave ───────────────────────────────────────────────────────────────────
class LeaveCreate(BaseModel):
    start_date: date
    end_date: date
    leave_type: str = "annual"
    reason: Optional[str] = None
    ksv_approver_id: Optional[int] = None  # Bắt buộc với chuyen_vien/pho_phong/truong_phong

class LeaveReview(BaseModel):
    action: Literal["approve", "reject"]
    comment: Optional[str] = None

class TongHopReview(BaseModel):
    action: Literal["forward", "reject"]
    gd_approver_id: Optional[int] = None  # Bắt buộc khi action="forward"
    comment: Optional[str] = None

class LeaveOut(BaseModel):
    id: int
    staff_id: int
    staff_name: str
    department_name: Optional[str] = None
    start_date: date
    end_date: date
    leave_days: int
    leave_type: str
    reason: Optional[str]
    status: str
    ksv_approver_id: Optional[int] = None
    ksv_approver_name: Optional[str] = None
    ksv_approved_at: Optional[datetime] = None
    ksv_comment: Optional[str] = None
    tong_hop_approver_id: Optional[int] = None
    tong_hop_approver_name: Optional[str] = None
    tong_hop_approved_at: Optional[datetime] = None
    tong_hop_comment: Optional[str] = None
    gd_approver_id: Optional[int] = None
    gd_approver_name: Optional[str] = None
    gd_is_pgd: bool = False              # True nếu người ký là PGĐ → hiện (TUQ)
    gd_approved_at: Optional[datetime] = None
    gd_comment: Optional[str] = None
    created_at: datetime
    class Config: from_attributes = True

class LeaveActionLogOut(BaseModel):
    id: int
    actor_name: str
    action: str
    action_label: str
    comment: Optional[str]
    from_status: Optional[str]
    to_status: Optional[str]
    created_at: datetime
    class Config: from_attributes = True


# ─── Delegation ───────────────────────────────────────────────────────────────
class DelegationCreate(BaseModel):
    giam_doc_id: int
    pho_giam_doc_id: int
    start_date: date
    end_date: date
    note: Optional[str] = None

class DelegationOut(BaseModel):
    id: int
    giam_doc_id: int
    giam_doc_name: str
    pho_giam_doc_id: int
    pho_giam_doc_name: str
    start_date: date
    end_date: date
    note: Optional[str]
    is_active: bool
    created_by_name: str
    created_at: datetime
    class Config: from_attributes = True
