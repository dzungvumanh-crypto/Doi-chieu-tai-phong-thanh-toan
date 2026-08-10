"""API vắng mặt, đăng ký trực, ngày đặc biệt, cấu hình ca."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.database import get_db
from backend.core.deps import get_current_staff
from backend.schemas.duty import (
    AbsenceCreate, AbsenceRangeCreate, AbsenceOut,
    RequestCreate, RequestOut,
    SpecialDayCreate, SpecialDayOut, ComputeCutoffRequest,
    ShiftConfigOut, ShiftConfigUpsert,
    MessageOut,
)
from backend.services.duty_constraint_service import (
    list_absences, create_absence, create_absence_range,
    delete_absence_range, delete_absence,
    list_requests, create_request, delete_request,
    list_special_days, create_special_day, confirm_special_day, delete_special_day,
    upsert_special_days_bulk, get_holiday_dates, get_shift_config, upsert_shift_config,
)
from backend.services.duty_calendar_utils import compute_cutoff_dates, get_vn_holidays
from backend.services.duty_rules import MAC_DINH_COT

router = APIRouter(prefix="/api/duty/constraints", tags=["duty-constraints"])


# ── Absences ─────────────────────────────────────────────────────────────────

@router.get("/absences", response_model=list[AbsenceOut])
def get_absences(
    month: Optional[int] = Query(None, ge=1, le=12),
    year:  Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return list_absences(db, month, year)


@router.post("/absences", response_model=AbsenceOut)
def add_absence(
    body: AbsenceCreate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return create_absence(db, body.staff_id, body.absence_date)


@router.post("/absences/range")
def add_absence_range(
    body: AbsenceRangeCreate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return create_absence_range(db, body.staff_id, body.from_date, body.to_date)


@router.delete("/absences/range")
def remove_absence_range(
    staff_id: int,
    from_date: str,
    to_date: str,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return delete_absence_range(db, staff_id, from_date, to_date)


@router.delete("/absences/{absence_id}", response_model=MessageOut)
def remove_absence(
    absence_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    if not delete_absence(db, absence_id):
        raise HTTPException(404, "Không tìm thấy khai báo vắng")
    return {"message": "Đã xóa"}


# ── Duty Requests ─────────────────────────────────────────────────────────────

@router.get("/requests", response_model=list[RequestOut])
def get_requests(
    year: Optional[int] = None,
    staff_id: Optional[int] = None,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return list_requests(db, year, staff_id)


@router.post("/requests", response_model=RequestOut)
def add_request(
    body: RequestCreate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    try:
        return create_request(
            db, body.staff_id, body.request_type, body.year,
            body.specific_date, body.day_of_week
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/requests/{request_id}", response_model=MessageOut)
def remove_request(
    request_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    if not delete_request(db, request_id):
        raise HTTPException(404, "Không tìm thấy đăng ký")
    return {"message": "Đã xóa"}


# ── Special Days ──────────────────────────────────────────────────────────────

@router.get("/special-days", response_model=list[SpecialDayOut])
def get_special_days(
    month: Optional[int] = Query(None, ge=1, le=12),
    year:  Optional[int] = None,
    day_type: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return list_special_days(db, month, year, day_type)


@router.post("/special-days", response_model=SpecialDayOut)
def add_special_day(
    body: SpecialDayCreate,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return create_special_day(db, body.date, body.day_type, body.label)


@router.post("/special-days/{special_day_id}/confirm", response_model=SpecialDayOut)
def confirm_day(
    special_day_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    result = confirm_special_day(db, special_day_id)
    if not result:
        raise HTTPException(404, "Không tìm thấy ngày đặc biệt")
    return result


@router.delete("/special-days/{special_day_id}")
def remove_special_day(
    special_day_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return delete_special_day(db, special_day_id)


@router.post("/special-days/compute-cutoff")
def compute_cutoff(
    body: ComputeCutoffRequest,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    """Tính 2 ngày cut-off cuối tháng và lưu vào DB."""
    holiday_dates = get_holiday_dates(db, body.year)
    cutoffs = compute_cutoff_dates(body.month, body.year, holiday_dates)
    result = []
    for ds in cutoffs:
        obj = create_special_day(db, ds, "cutoff", f"Cutoff T{body.month}/{body.year}")
        result.append(obj)
    return result


@router.post("/special-days/seed-holidays")
def seed_holidays(
    year: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    """Seed ngày nghỉ lễ VN cho năm chỉ định."""
    holidays = get_vn_holidays(year)
    result = upsert_special_days_bulk(
        db, [{"date": h["date"], "day_type": "holiday",
              "label": h["label"], "is_confirmed": 1} for h in holidays]
    )
    return {"seeded": len(result)}


# ── Shift Config ─────────────────────────────────────────────────────────────

@router.get("/shift-config/{year}", response_model=ShiftConfigOut)
def get_config(
    year: int,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    """Năm chưa khai báo thì trả bộ mặc định nghiệp vụ, KHÔNG 404.

    Engine (get_cau_hinh_ca) vẫn chạy bằng đúng bộ số này khi thiếu bản ghi, nên
    404 chỉ buộc frontend chép lại một bản mặc định thứ hai — và phải nuốt lỗi để
    404 không hiện thành thông báo đỏ, nuốt luôn cả lỗi hết phiên đăng nhập.
    """
    cfg = get_shift_config(db, year) or {}
    ket_qua = {"year": year, "signer_name": cfg.get("signer_name")}
    for cot, mac_dinh in MAC_DINH_COT.items():
        ket_qua[cot] = mac_dinh if cfg.get(cot) is None else cfg[cot]
    return ket_qua


@router.put("/shift-config/{year}", response_model=ShiftConfigOut)
def update_config(
    year: int,
    body: ShiftConfigUpsert,
    db: sqlite3.Connection = Depends(get_db),
    _=Depends(get_current_staff),
):
    return upsert_shift_config(
        db, year, body.nv_count, body.signer_name,
        ld_count=body.ld_count,
        qt_ld_count=body.qt_ld_count,
        qt_nv_chinh_count=body.qt_nv_chinh_count,
        qt_nv_phu_count=body.qt_nv_phu_count,
    )
