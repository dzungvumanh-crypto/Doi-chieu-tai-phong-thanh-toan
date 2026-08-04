"""API báo cáo bàn giao chứng từ — đúng hạn / quá hạn theo phòng"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.deps import require_feature
from backend.database import get_db, _vn_now
from backend.services.handover_report_service import compute_period

router = APIRouter(prefix="/api/handover-reports", tags=["handover-reports"])


@router.get("/summary")
def handover_summary(
    year: int = Query(None),
    month: int = Query(None),
    _: dict = Depends(require_feature("menu.handover_reports")),
    db: sqlite3.Connection = Depends(get_db),
):
    today = _vn_now().date()
    # Phân biệt "không truyền" với "truyền số 0": `or` coi 0 là falsy nên
    # month=0 từng bị thay âm thầm bằng tháng hiện tại — trả số liệu tháng khác
    # với thứ được hỏi, không cảnh báo gì.
    year = today.year if year is None else year
    month = today.month if month is None else month

    if not 1 <= month <= 12:
        raise HTTPException(400, "Tháng phải nằm trong khoảng 1–12")
    if not 2000 <= year <= 2100:
        raise HTTPException(400, "Năm không hợp lệ")

    return compute_period(db, year, month)
