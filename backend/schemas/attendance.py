from datetime import date, datetime
from typing import Optional, Literal, Dict, List
from pydantic import BaseModel, Field, field_validator


# ─── Ký hiệu công ─────────────────────────────────────────────────────────────
class AttendanceSymbolCreate(BaseModel):
    symbol: str
    description: str
    # 1 ngày không thể quá 1 công — khớp giới hạn min=0/max=1 đã có sẵn ở UI
    # "Thêm ký hiệu mới" (frontend/pages/attendance.py), trước đây chỉ chặn phía
    # client, gọi thẳng API vẫn tạo được giá trị âm/>1 (rà soát vòng 3 PR #22).
    work_value: float = Field(ge=0, le=1)
    color: str = "#E5E7EB"
    is_active: bool = True

    @field_validator("symbol")
    @classmethod
    def v_symbol(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) > 10:
            raise ValueError("Ký hiệu không được để trống và tối đa 10 ký tự")
        return v

    @field_validator("description")
    @classmethod
    def v_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Mô tả không được để trống")
        return v

class AttendanceSymbolUpdate(BaseModel):
    description: Optional[str] = None
    work_value: Optional[float] = Field(default=None, ge=0, le=1)
    color: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("description")
    @classmethod
    def v_description(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Mô tả không được để trống")
        return v

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
    makeup_days: List[str] = []   # T7/CN phải đi làm bù — vẫn tính công
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
