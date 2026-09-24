"""Schemas cho Thi đua khen thưởng (danh hiệu đơn vị, danh hiệu cá nhân, sáng kiến)."""
import unicodedata
from datetime import date as _date
from typing import Optional

from pydantic import BaseModel, field_validator

from backend.core.enums import ThiDuaCap

_MIN_YEAR = 2000
_MAX_YEAR = 2100


def _clean(v: Optional[str]) -> Optional[str]:
    """NFC + strip; chuỗi rỗng → None."""
    if v is None:
        return None
    v = unicodedata.normalize("NFC", str(v)).strip()
    return v or None


def _clean_date(v: Optional[str]) -> Optional[str]:
    v = _clean(v)
    if not v:
        return None
    try:
        _date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"Ngày không hợp lệ: '{v}' (cần YYYY-MM-DD)")
    return v


class DonViIn(BaseModel):
    year: int
    department_id: Optional[int] = None  # None = Toàn Trung tâm
    danh_hieu: str
    so_quyet_dinh: Optional[str] = None
    ngay_quyet_dinh: Optional[str] = None
    co_quan_ban_hanh: Optional[str] = None
    ghi_chu: Optional[str] = None

    @field_validator("year")
    @classmethod
    def _valid_year(cls, v):
        if not (_MIN_YEAR <= v <= _MAX_YEAR):
            raise ValueError(f"Năm không hợp lệ: {v}")
        return v

    @field_validator("danh_hieu")
    @classmethod
    def _need_danh_hieu(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Tên danh hiệu không được để trống")
        return v

    @field_validator("so_quyet_dinh", "co_quan_ban_hanh", "ghi_chu")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @field_validator("ngay_quyet_dinh")
    @classmethod
    def _dt(cls, v):
        return _clean_date(v)


class CaNhanIn(BaseModel):
    staff_id: int
    year: int
    cap: ThiDuaCap
    danh_hieu: str
    so_quyet_dinh: Optional[str] = None
    ngay_quyet_dinh: Optional[str] = None
    co_quan_ban_hanh: Optional[str] = None
    ghi_chu: Optional[str] = None

    @field_validator("year")
    @classmethod
    def _valid_year(cls, v):
        if not (_MIN_YEAR <= v <= _MAX_YEAR):
            raise ValueError(f"Năm không hợp lệ: {v}")
        return v

    @field_validator("danh_hieu")
    @classmethod
    def _need_danh_hieu(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Tên danh hiệu không được để trống")
        return v

    @field_validator("so_quyet_dinh", "co_quan_ban_hanh", "ghi_chu")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @field_validator("ngay_quyet_dinh")
    @classmethod
    def _dt(cls, v):
        return _clean_date(v)


class SangKienIn(BaseModel):
    staff_id: int
    year: int
    ten_sang_kien: str
    so_quyet_dinh: Optional[str] = None
    ngay_quyet_dinh: Optional[str] = None
    co_quan_cong_nhan: Optional[str] = None
    ghi_chu: Optional[str] = None

    @field_validator("year")
    @classmethod
    def _valid_year(cls, v):
        if not (_MIN_YEAR <= v <= _MAX_YEAR):
            raise ValueError(f"Năm không hợp lệ: {v}")
        return v

    @field_validator("ten_sang_kien")
    @classmethod
    def _need_ten(cls, v):
        v = _clean(v)
        if not v:
            raise ValueError("Tên sáng kiến không được để trống")
        return v

    @field_validator("so_quyet_dinh", "co_quan_cong_nhan", "ghi_chu")
    @classmethod
    def _opt(cls, v):
        return _clean(v)

    @field_validator("ngay_quyet_dinh")
    @classmethod
    def _dt(cls, v):
        return _clean_date(v)
