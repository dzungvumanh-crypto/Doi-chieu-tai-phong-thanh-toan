from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

from backend.core.enums import VALID_ROLES


def _kiem_tra_role(v):
    """`role` là chuỗi tự do trong lược đồ nên gõ sai không ai chặn — mà sai một
    ký tự ("truong_phong " thừa dấu cách) là tài khoản đó rớt KHỎI MỌI kiểm tra
    quyền: không lỗi, không cảnh báo, chỉ là người dùng bấm gì cũng bị từ chối.
    Chặn tại cửa vào thay vì đi tìm nguyên nhân sau."""
    if v is None:
        return v
    if v not in VALID_ROLES:
        raise ValueError(
            f"Vai trò '{v}' không tồn tại. Giá trị hợp lệ: {', '.join(sorted(VALID_ROLES))}"
        )
    return v


class StaffCreate(BaseModel):
    employee_code: Optional[str] = None  # auto-filled from username if omitted
    full_name: str
    role: str = "chuyen_vien"
    department_id: Optional[int] = None  # bắt buộc khi role=chuyen_vien
    username: str
    password: str
    phone: Optional[str] = None
    email: Optional[str] = None
    start_date: Optional[date] = None
    join_industry_date: Optional[date] = None
    ipcas_code: Optional[str] = None
    payment_username: Optional[str] = None

    _role_hop_le = field_validator("role")(_kiem_tra_role)


class StaffUpdate(BaseModel):
    employee_code: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None
    join_industry_date: Optional[date] = None
    ipcas_code: Optional[str] = None
    payment_username: Optional[str] = None

    _role_hop_le = field_validator("role")(_kiem_tra_role)


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
    join_industry_date: Optional[date] = None
    annual_leave_days: Optional[int] = None
    ipcas_code: Optional[str] = None
    payment_username: Optional[str] = None
    is_active: bool

    # Cột user_tttt.is_active không NOT NULL, không DEFAULT → NULL lọt được vào
    # (dữ liệu cũ, đường "Nhập DB"). Không ép ở đây thì CẢ danh sách /api/staff/
    # trả 500 chỉ vì một dòng hỏng — pydantic bỏ nguyên response.
    # NULL = không hoạt động, khớp `WHERE is_active = 1` ở auth.py và list_staff.
    @field_validator("is_active", mode="before")
    @classmethod
    def _null_la_khoa(cls, v):
        return False if v is None else v

    model_config = ConfigDict(from_attributes=True)
