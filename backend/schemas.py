"""Pydantic Schemas"""
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ─── Auth ───────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str
    force: bool = False  # override active session on another IP

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff_id: int
    full_name: str
    role: str


# ─── Department ─────────────────────────────────────────────────────────────
class DepartmentOut(BaseModel):
    id: int
    code: str
    name: str
    is_source: bool
    is_active: bool
    class Config: from_attributes = True


# ─── KSNB Staff ─────────────────────────────────────────────────────────────
class StaffCreate(BaseModel):
    employee_code: Optional[str] = None  # auto-filled from username if omitted
    full_name: str
    role: str = "controller"
    department_id: Optional[int] = None  # bắt buộc khi role=chuyen_vien
    username: str
    password: str
    phone: Optional[str] = None
    email: Optional[str] = None
    start_date: Optional[date] = None

class StaffUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None

class StaffOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    role: str
    department_id: Optional[int] = None
    username: str
    phone: Optional[str]
    email: Optional[str]
    start_date: Optional[date]
    is_active: bool
    class Config: from_attributes = True

class PasswordChange(BaseModel):
    old_password: str
    new_password: str

class AdminPasswordReset(BaseModel):
    staff_id: int
    new_password: str


# ─── Storage view ────────────────────────────────────────────────────────────
class StorageViewRow(BaseModel):
    days: List[int]
    bundle_sheets: List[int]
    n_bundles: int

class StorageViewResponse(BaseModel):
    department_name: str
    period: str
    rows: List[StorageViewRow]
    total_sheets: int
    total_bundles: int


# ─── Source User ─────────────────────────────────────────────────────────────
class SourceUserCreate(BaseModel):
    user_code: str
    full_name: Optional[str] = None   # User PaymentHub
    vn_name: Optional[str] = None     # Họ và tên thực
    department_id: int
    is_active: bool = True

class SourceUserOut(BaseModel):
    id: int
    user_code: str
    full_name: Optional[str]
    vn_name: Optional[str] = None
    department_id: int
    is_active: bool
    department: Optional[DepartmentOut] = None
    class Config: from_attributes = True


# ─── Document Entry ─────────────────────────────────────────────────────────
class DocumentEntryIn(BaseModel):
    source_user_id: int
    transaction_date: date
    sheet_count: int = Field(gt=0)
    notes: Optional[str] = None

class DocumentEntryOut(BaseModel):
    id: int
    source_user_id: int
    transaction_date: date
    sheet_count: int
    notes: Optional[str]
    source_user: Optional[SourceUserOut] = None
    class Config: from_attributes = True


# ─── Handover ────────────────────────────────────────────────────────────────
class HandoverCreate(BaseModel):
    department_id: int
    handover_date: date
    delivered_by: Optional[str] = None
    notes: Optional[str] = None
    entries: List[DocumentEntryIn] = []

class HandoverOut(BaseModel):
    id: int
    department_id: int
    handover_date: date
    received_by_id: Optional[int]
    delivered_by: Optional[str]
    notes: Optional[str]
    status: str
    created_at: datetime
    department: Optional[DepartmentOut] = None
    entries: List[DocumentEntryOut] = []
    class Config: from_attributes = True


# ─── Bundle ──────────────────────────────────────────────────────────────────
class BundleItemOut(BaseModel):
    id: int
    entry_id: int
    entry: Optional[DocumentEntryOut] = None
    class Config: from_attributes = True

class BundleOut(BaseModel):
    id: int
    group_id: int
    sequence: int
    total_sheets: int
    custodian_id: Optional[int]
    storage_box: Optional[str]
    storage_location: Optional[str]
    cover_printed_at: Optional[datetime]
    status: str
    items: List[BundleItemOut] = []
    class Config: from_attributes = True

class BundleGroupOut(BaseModel):
    id: int
    department_id: int
    total_bundles: int
    created_at: datetime
    notes: Optional[str]
    department: Optional[DepartmentOut] = None
    bundles: List[BundleOut] = []
    created_by_staff: Optional[StaffOut] = None
    class Config: from_attributes = True

class BundleGenerateRequest(BaseModel):
    department_id: int
    entry_ids: List[int]      # Các document entry IDs để gom
    custodian_id: Optional[int] = None
    notes: Optional[str] = None

class BundleUpdateRequest(BaseModel):
    custodian_id: Optional[int] = None
    storage_box: Optional[str] = None
    storage_location: Optional[str] = None


# ─── Handover Grid ───────────────────────────────────────────────────────────
class GridEntryOut(BaseModel):
    source_user_id: int
    day: int
    sheet_count: int
    entry_id: Optional[int] = None
    entry_status: str = "confirmed"         # pending_confirm | confirmed | borrowed
    entered_by_name: Optional[str] = None   # Tên người nhập

class GridResponse(BaseModel):
    users: List[SourceUserOut]
    entries: List[GridEntryOut]
    days_in_month: int

class EntryUpsertRequest(BaseModel):
    source_user_id: int
    date: date
    sheet_count: int = Field(ge=0)


# ─── Entry History ────────────────────────────────────────────────────────────
class EntryHistoryItem(BaseModel):
    id: int
    action: str                         # key enum
    action_label: str                   # mô tả tiếng Việt
    action_color: str                   # blue | green | orange | purple
    performed_by: str                   # full_name
    performed_by_role: str              # vai trò + phòng
    timestamp: str                      # "HH:MM:SS DD/MM/YYYY"
    old_sheet_count: Optional[int] = None
    new_sheet_count: Optional[int] = None

class EntryHistoryOut(BaseModel):
    entry_id: int
    source_user_name: str
    transaction_date: str               # "DD/MM/YYYY"
    sheet_count: int
    current_status: str
    current_status_label: str
    logs: List[EntryHistoryItem]


# ─── Archive handover ────────────────────────────────────────────────────────
class ArchiveRecord(BaseModel):
    ngay_mo: str
    ngay_kt: str
    tieu_de: str

class HandoverArchiveResponse(BaseModel):
    records: List[ArchiveRecord]
    total: int


# ─── Leave ───────────────────────────────────────────────────────────────────
class LeaveCreate(BaseModel):
    start_date: date
    end_date: date
    leave_type: str = "annual"
    reason: Optional[str] = None

class LeaveOut(BaseModel):
    id: int
    staff_id: int
    start_date: date
    end_date: date
    leave_type: str
    reason: Optional[str]
    status: str
    created_at: datetime
    class Config: from_attributes = True
