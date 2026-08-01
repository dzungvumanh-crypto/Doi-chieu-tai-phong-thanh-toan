from datetime import date, datetime
from typing import Optional, Literal, Dict, List
from pydantic import BaseModel


# ─── Ký hiệu công ─────────────────────────────────────────────────────────────
class AttendanceSymbolCreate(BaseModel):
    symbol: str
    description: str
    work_value: float
    color: str = "#E5E7EB"
    is_active: bool = True

class AttendanceSymbolUpdate(BaseModel):
    description: Optional[str] = None
    work_value: Optional[float] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None

class AttendanceSymbolOut(BaseModel):
    symbol: str
    description: str
    work_value: float
    color: str
    is_active: bool
    class Config: from_attributes = True


# ─── Chấm công theo ngày / theo tháng ─────────────────────────────────────────
class AttendanceDayUpdate(BaseModel):
    symbol: str
    note: Optional[str] = None

class AttendanceDayOut(BaseModel):
    attendance_id: Optional[int] = None
    staff_id: int
    date: date
    symbol: Optional[str] = None
    work_value: float = 0
    status: Optional[str] = None
    note: Optional[str] = None
    is_virtual: bool = False

class AttendanceMonthStaffOut(BaseModel):
    staff_id: int
    full_name: str
    employee_code: Optional[str] = None
    days: Dict[str, AttendanceDayOut]
    total_work_value: float

class AttendanceMonthOut(BaseModel):
    year: int
    month: int
    days_in_month: int
    holidays: List[str]
    staff: List[AttendanceMonthStaffOut]


# ─── Điều chỉnh công ──────────────────────────────────────────────────────────
class AdjustmentCreate(BaseModel):
    staff_id: Optional[int] = None   # None = chính người gửi
    date: date
    new_symbol: str
    reason: str

class AdjustmentReview(BaseModel):
    action: Literal["approve", "reject"]
    reject_reason: Optional[str] = None

class AdjustmentOut(BaseModel):
    id: int
    attendance_id: int
    staff_id: int
    staff_name: str
    date: date
    old_symbol: Optional[str] = None
    new_symbol: str
    old_work_value: Optional[float] = None
    new_work_value: float
    reason: str
    status: str
    reviewer_id: Optional[int] = None
    reviewer_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    reject_reason: Optional[str] = None
    created_at: datetime
    class Config: from_attributes = True
