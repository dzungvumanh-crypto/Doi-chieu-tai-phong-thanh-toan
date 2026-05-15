"""API endpoints báo cáo hậu kiểm IPCAS / Payment"""
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.core.deps import require_hkv_or_above
from backend.models import KSNBStaff
from backend.services.report_service import (
    parse_ipcas, parse_payment_teller, parse_payment_backchecker,
    enrich_and_group, merge_hkv,
    generate_dept_excel, generate_center_word, build_zip,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


# ── Parse GDV + Teller → JSON grouped by dept ────────────────────────────────

@router.post("/parse-gdv")
async def parse_gdv(
    gdv_file: UploadFile = File(None),
    teller_file: UploadFile = File(None),
    current: KSNBStaff = Depends(require_hkv_or_above),
    db: Session = Depends(get_db),
):
    """
    Upload file GDV (IPCAS .xls) và/hoặc Teller (Payment .xlsx).
    Trả về dữ liệu grouped theo phòng.
    HTTP 422 nếu có GD Hậu kiểm sai ≠ 0.
    """
    result = {"ipcas": {}, "payment": {}, "month": 0, "year": 0}
    violations = []

    if gdv_file and gdv_file.filename:
        try:
            raw = await gdv_file.read()
            rows, viols, month, year = parse_ipcas(raw)
            if viols:
                violations.extend([{**v, "system": "IPCAS"} for v in viols])
            else:
                result["ipcas"] = enrich_and_group(rows, db, is_payment=False)
                if month:
                    result["month"] = month
                if year:
                    result["year"] = year
        except Exception as e:
            log.error("parse_gdv IPCAS error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file GDV: {e}")

    if teller_file and teller_file.filename:
        try:
            raw = await teller_file.read()
            rows, viols = parse_payment_teller(raw)
            if viols:
                violations.extend([{**v, "system": "Payment"} for v in viols])
            else:
                result["payment"] = enrich_and_group(rows, db, is_payment=True)
        except Exception as e:
            log.error("parse_gdv Payment error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file Teller: {e}")

    if violations:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "GD Hậu kiểm sai đang lớn hơn 0. Đề nghị kiểm tra lại",
                "violations": violations,
            },
        )

    return result


# ── Parse HKV + Backchecker → JSON merged HKV list ───────────────────────────

@router.post("/parse-hkv")
async def parse_hkv(
    hkv_file: UploadFile = File(None),
    checker_file: UploadFile = File(None),
    current: KSNBStaff = Depends(require_hkv_or_above),
    db: Session = Depends(get_db),
):
    """
    Upload file HKV (IPCAS .xls) và Backchecker (Payment .xlsx).
    Trả về merged list per HKV user.
    HTTP 422 nếu có vi phạm.
    """
    ipcas_rows, payment_rows = [], []
    violations = []
    month, year = 0, 0

    if hkv_file and hkv_file.filename:
        try:
            raw = await hkv_file.read()
            rows, viols, m, y = parse_ipcas(raw)
            if viols:
                violations.extend([{**v, "system": "IPCAS"} for v in viols])
            else:
                ipcas_rows = rows
                month, year = m or month, y or year
        except Exception as e:
            log.error("parse_hkv IPCAS error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file HKV: {e}")

    if checker_file and checker_file.filename:
        try:
            raw = await checker_file.read()
            rows, viols = parse_payment_backchecker(raw)
            if viols:
                violations.extend([{**v, "system": "Payment"} for v in viols])
            else:
                payment_rows = rows
        except Exception as e:
            log.error("parse_hkv Payment error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file Backchecker: {e}")

    if violations:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "GD Hậu kiểm sai đang lớn hơn 0. Đề nghị kiểm tra lại",
                "violations": violations,
            },
        )

    merged = merge_hkv(ipcas_rows, payment_rows, db)
    return {"hkv_rows": merged, "month": month, "year": year}


# ── Generate Excel báo cáo phòng ─────────────────────────────────────────────

class GenerateDeptRequest(BaseModel):
    dept_name: str
    month: int
    year: int
    ipcas_rows: list = []
    payment_rows: list = []
    staff_name: str = ""


@router.post("/generate-dept")
def generate_dept(
    body: GenerateDeptRequest,
    current: KSNBStaff = Depends(require_hkv_or_above),
):
    try:
        staff_name = body.staff_name or current.full_name or current.username
        excel_bytes = generate_dept_excel(
            dept_name=body.dept_name,
            month=body.month,
            year=body.year,
            ipcas_rows=body.ipcas_rows,
            payment_rows=body.payment_rows,
            staff_name=staff_name,
        )
        filename = f"BC_HK_{body.dept_name}_T{body.month:02d}{body.year}.xlsx"
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=_dl_headers(filename),
        )
    except Exception as e:
        log.error("generate_dept error: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi sinh báo cáo Excel: {e}")


# ── Generate Word báo cáo tổng hợp ───────────────────────────────────────────

class GenerateWordRequest(BaseModel):
    month: int
    year: int
    hkv_ipcas: list = []
    hkv_payment: list = []
    dept_summaries: list = []


@router.post("/generate-word")
def generate_word(
    body: GenerateWordRequest,
    current: KSNBStaff = Depends(require_hkv_or_above),
):
    try:
        word_bytes = generate_center_word(
            month=body.month,
            year=body.year,
            hkv_ipcas=body.hkv_ipcas,
            hkv_payment=body.hkv_payment,
            dept_data=body.dept_summaries,
        )
        filename = f"BC_HK_T{body.month:02d}{body.year}.docx"
        return Response(
            content=word_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=_dl_headers(filename),
        )
    except Exception as e:
        log.error("generate_word error: %s", e)
        raise HTTPException(status_code=500, detail=f"Lỗi sinh báo cáo Word: {e}")


# ── Generate ZIP tất cả báo cáo phòng (1 request) ────────────────────────────

@router.post("/generate-dept-zip")
async def generate_dept_zip(
    gdv_file: UploadFile = File(None),
    teller_file: UploadFile = File(None),
    current: KSNBStaff = Depends(require_hkv_or_above),
    db: Session = Depends(get_db),
):
    """
    Upload GDV + Teller → parse → generate 1 Excel/phòng → trả ZIP.
    HTTP 422 nếu name_5 ≠ 0.
    """
    violations = []
    ipcas_grouped: dict = {}
    payment_grouped: dict = {}
    month, year = 0, 0

    if gdv_file and gdv_file.filename:
        try:
            raw = await gdv_file.read()
            rows, viols, m, y = parse_ipcas(raw)
            if viols:
                violations.extend([{**v, "system": "IPCAS"} for v in viols])
            else:
                ipcas_grouped = enrich_and_group(rows, db, is_payment=False)
                month, year = m or month, y or year
        except Exception as e:
            log.error("generate_dept_zip IPCAS: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file GDV: {e}")

    if teller_file and teller_file.filename:
        try:
            raw = await teller_file.read()
            rows, viols = parse_payment_teller(raw)
            if viols:
                violations.extend([{**v, "system": "Payment"} for v in viols])
            else:
                payment_grouped = enrich_and_group(rows, db, is_payment=True)
        except Exception as e:
            log.error("generate_dept_zip Payment: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file Teller: {e}")

    if violations:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "GD Hậu kiểm sai đang lớn hơn 0. Đề nghị kiểm tra lại",
                "violations": violations,
            },
        )

    all_depts = set(ipcas_grouped.keys()) | set(payment_grouped.keys())
    if not all_depts:
        raise HTTPException(status_code=400, detail="Không có dữ liệu để tạo báo cáo")

    staff_name = current.full_name or current.username
    m_disp = month or 1
    y_disp = year or 2025
    excels = {}
    for dept in sorted(all_depts):
        excel_bytes = generate_dept_excel(
            dept_name=dept,
            month=m_disp,
            year=y_disp,
            ipcas_rows=ipcas_grouped.get(dept, []),
            payment_rows=payment_grouped.get(dept, []),
            staff_name=staff_name,
        )
        excels[f"BC_HK_{dept}_T{m_disp:02d}{y_disp}.xlsx"] = excel_bytes

    zip_bytes = build_zip(excels)
    zip_name = f"BC_HK_phong_T{m_disp:02d}{y_disp}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers=_dl_headers(zip_name),
    )