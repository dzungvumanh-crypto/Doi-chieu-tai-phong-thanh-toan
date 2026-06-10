"""Pydantic v2 schemas cho API phân lịch trực Phòng Thanh toán."""
from __future__ import annotations
from datetime import date as _date
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


def _valid_date(v: str) -> str:
    try:
        _date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"Ngày không hợp lệ: {v}")
    return v


# ── Staff ─────────────────────────────────────────────────────────────────────

class DutyStaffOut(BaseModel):
    id: int
    full_name: str
    role: str            # user_tttt.role (truong_phong, pho_phong, chuyen_vien)
    duty_role: str       # LD | NV (derived)
    can_do_sp: int = 0
    is_sp_backup: int = 0
    is_on_project: int = 0
    display_order: int = 999


class DutyStaffMetaIn(BaseModel):
    can_do_sp: Optional[int] = None
    is_sp_backup: Optional[int] = None
    is_on_project: Optional[int] = None
    display_order: Optional[int] = None


# ── Absences ─────────────────────────────────────────────────────────────────

class AbsenceCreate(BaseModel):
    staff_id: int
    absence_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("absence_date")
    @classmethod
    def v_date(cls, v: str) -> str:
        return _valid_date(v)


class AbsenceRangeCreate(BaseModel):
    staff_id: int
    from_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    to_date:   str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")

    @field_validator("from_date", "to_date")
    @classmethod
    def v_dates(cls, v: str) -> str:
        return _valid_date(v)

    @model_validator(mode="after")
    def check_order(self) -> "AbsenceRangeCreate":
        if self.to_date < self.from_date:
            raise ValueError("to_date phải >= from_date")
        return self


class AbsenceOut(BaseModel):
    id: int
    staff_id: int
    staff_name: Optional[str] = None
    absence_date: str
    created_at: str


# ── Duty Requests ─────────────────────────────────────────────────────────────

class RequestCreate(BaseModel):
    staff_id: int
    request_type: Literal["once", "weekly"]
    specific_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    day_of_week: Optional[int] = Field(None, ge=0, le=4)
    year: int

    @field_validator("specific_date")
    @classmethod
    def v_specific_date(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _valid_date(v)
        return v

    @model_validator(mode="after")
    def check_fields(self) -> "RequestCreate":
        if self.request_type == "once" and not self.specific_date:
            raise ValueError("specific_date bắt buộc khi request_type='once'")
        if self.request_type == "weekly" and self.day_of_week is None:
            raise ValueError("day_of_week bắt buộc khi request_type='weekly'")
        return self


class RequestOut(BaseModel):
    id: int
    staff_id: int
    staff_name: Optional[str] = None
    request_type: str
    specific_date: Optional[str] = None
    day_of_week: Optional[int] = None
    year: int
    is_active: bool


# ── Special Days ──────────────────────────────────────────────────────────────

class SpecialDayCreate(BaseModel):
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    day_type: Literal["holiday", "cutoff", "settlement", "makeup"]
    label: Optional[str] = None

    @field_validator("date")
    @classmethod
    def v_date(cls, v: str) -> str:
        return _valid_date(v)

    @field_validator("label")
    @classmethod
    def strip_label(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            return v if v else None
        return v


class SpecialDayOut(BaseModel):
    id: int
    date: str
    day_type: str
    label: Optional[str] = None
    is_confirmed: bool


class ComputeCutoffRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int


# ── Shift Config ─────────────────────────────────────────────────────────────

class ShiftConfigOut(BaseModel):
    year: int
    nv_count: int
    signer_name: Optional[str] = None


class ShiftConfigUpsert(BaseModel):
    nv_count: int = Field(..., ge=1, le=5)
    signer_name: Optional[str] = None


# ── Duty Shifts ───────────────────────────────────────────────────────────────

class DutyPersonOut(BaseModel):
    id: int
    full_name: str
    role: str


class ShiftOut(BaseModel):
    id: int
    shift_date: str
    shift_type: str
    leader: Optional[DutyPersonOut] = None
    sp: Optional[DutyPersonOut] = None
    sp_warning: Optional[str] = None
    nvs: List[DutyPersonOut] = []
    nv_count: int
    is_auto: bool
    status: str
    created_at: str


class ShiftUpdate(BaseModel):
    leader_id: Optional[int] = None
    sp_id: Optional[int] = None
    nv_ids: List[int] = []


class GenerateRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int
    overwrite_draft: bool = False


class GenerateResult(BaseModel):
    month: int
    year: int
    created: int
    skipped: int
    warnings: List[dict] = []


class GenerateWeekRequest(BaseModel):
    week_start: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    overwrite_draft: bool = False
    overwrite_confirmed: bool = False


class GenerateWeekResult(BaseModel):
    week_start: str
    created: int
    skipped: int
    warnings: List[dict] = []


# ── Rotation State ────────────────────────────────────────────────────────────

class RotationStateOut(BaseModel):
    staff_id: int
    staff_name: Optional[str] = None
    role: str
    year: int
    shift_count: int
    last_used: Optional[str] = None


# ── Statistics ────────────────────────────────────────────────────────────────

class PersonShiftCount(BaseModel):
    staff_id: int
    full_name: str
    duty_role: str
    normal: int = 0
    friday: int = 0
    cutoff: int = 0
    settlement_main: int = 0
    settlement_sub: int = 0
    total: int = 0


class MonthlySummary(BaseModel):
    month: int
    year: int
    total_shifts: int
    by_type: dict


class MessageOut(BaseModel):
    message: str
