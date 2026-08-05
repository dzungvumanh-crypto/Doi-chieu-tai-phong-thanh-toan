"""API báo cáo bàn giao chứng từ — đúng hạn / quá hạn theo phòng"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Response

from backend.api.bundles import _download_headers
from backend.core.concurrency import run_heavy
from backend.core.deps import require_feature
from backend.database import get_db, _vn_now
from backend.services.handover_report_docx import build_report_docx
from backend.services.handover_report_service import compute_period

router = APIRouter(prefix="/api/handover-reports", tags=["handover-reports"])

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _resolve_period(year, month) -> tuple:
    """Mặc định về kỳ hiện tại khi không truyền + validate. Dùng chung cho xem và xuất file."""
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
    return year, month


@router.get("/summary")
def handover_summary(
    year: int = Query(None),
    month: int = Query(None),
    _: dict = Depends(require_feature("menu.handover_reports")),
    db: sqlite3.Connection = Depends(get_db),
):
    year, month = _resolve_period(year, month)
    return compute_period(db, year, month)


@router.get("/export")
async def export_handover_report(
    year: int = Query(None),
    month: int = Query(None),
    _: dict = Depends(require_feature("menu.handover_reports")),
    db: sqlite3.Connection = Depends(get_db),
):
    """Xuất báo cáo của đúng kỳ đang xem ra Word khổ A4 ngang."""
    year, month = _resolve_period(year, month)

    # Truy vấn ở luồng request, chỉ sinh file trong bể việc nặng: sqlite3.Connection
    # gắn với luồng tạo ra nó (check_same_thread), không đem sang thread khác được.
    data = compute_period(db, year, month)
    content = await run_heavy(build_report_docx, data, year, month)

    return Response(
        content=content,
        media_type=_DOCX_MIME,
        headers=_download_headers(f"Bao_cao_ban_giao_chung_tu_T{month:02d}_{year:04d}.docx"),
    )
