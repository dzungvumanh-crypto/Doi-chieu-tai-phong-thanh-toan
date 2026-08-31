"""Schemas Quản lý nhân sự.

Chỉ khai báo những phản hồi có HÌNH DẠNG CỐ ĐỊNH (thống kê, nhắc lịch, tra cứu
danh sách). Thân request của 7 phân hệ hồ sơ nhận dict và được kiểm bằng
`hr_service.chuan_hoa()` theo đặc tả `SECTIONS`: cột của các phân hệ đó khai một
chỗ duy nhất trong `hr_service.py`, dựng thêm 7 cặp model Pydantic ở đây chỉ tạo
ra bản mô tả thứ hai để hai bên lệch nhau.
"""
from typing import Optional

from pydantic import BaseModel


class StaffBrief(BaseModel):
    staff_id: int
    employee_code: Optional[str] = None
    full_name: str
    department: Optional[str] = None
    role: Optional[str] = None
    position_title: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    co_ho_so: bool = False


class ReminderOut(BaseModel):
    loai: str                 # nang_luong | bo_nhiem_lai | cap_moi
    staff_id: int
    employee_code: Optional[str] = None
    full_name: str
    department: Optional[str] = None
    ngay_moc: str
    con_lai: int              # số ngày còn lại; âm = đã quá hạn
    mo_ta: Optional[str] = None


class StatBucket(BaseModel):
    nhan: str
    so_luong: int


class StatsOut(BaseModel):
    tong: int
    theo_phong: list[StatBucket]
    theo_gioi: list[StatBucket]
    theo_trinh_do: list[StatBucket]
    theo_tuoi: list[StatBucket]
    qua_chi_nhanh: list[StatBucket]


class DirectoryRow(BaseModel):
    staff_id: int
    employee_code: Optional[str] = None
    full_name: str
    department: Optional[str] = None
    role: Optional[str] = None
    chuc_vu: Optional[str] = None
    quy_hoach: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
