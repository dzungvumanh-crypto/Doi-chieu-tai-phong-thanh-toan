"""API endpoints báo cáo hậu kiểm IPCAS / Payment"""
import logging
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel

from backend.database import get_db
from backend.core.deps import require_feature
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


@router.post("/parse-gdv")
async def parse_gdv(
    gdv_file: UploadFile = File(None),
    teller_file: UploadFile = File(None),
    current: dict = Depends(require_feature("menu.reports")),
    db: sqlite3.Connection = Depends(get_db),
):
    result = {"ipcas": {}, "payment": {}, "month": 0, "year": 0}

    if gdv_file and gdv_file.filename:
        try:
            raw = await gdv_file.read()
            rows, month, year = parse_ipcas(raw)
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
            rows = parse_payment_teller(raw)
            result["payment"] = enrich_and_group(rows, db, is_payment=True)
        except Exception as e:
            log.error("parse_gdv Payment error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file Teller: {e}")

    return result


@router.post("/parse-hkv")
async def parse_hkv(
    hkv_file: UploadFile = File(None),
    checker_file: UploadFile = File(None),
    current: dict = Depends(require_feature("menu.reports")),
    db: sqlite3.Connection = Depends(get_db),
):
    ipcas_rows, payment_rows = [], []
    month, year = 0, 0

    if hkv_file and hkv_file.filename:
        try:
            raw = await hkv_file.read()
            rows, m, y = parse_ipcas(raw)
            ipcas_rows = rows
            month, year = m or month, y or year
        except Exception as e:
            log.error("parse_hkv IPCAS error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file HKV: {e}")

    if checker_file and checker_file.filename:
        try:
            raw = await checker_file.read()
            payment_rows = parse_payment_backchecker(raw)
        except Exception as e:
            log.error("parse_hkv Payment error: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file Backchecker: {e}")

    merged = merge_hkv(ipcas_rows, payment_rows, db)
    return {"hkv_rows": merged, "month": month, "year": year}


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
    current: dict = Depends(require_feature("menu.reports")),
):
    try:
        staff_name = body.staff_name or current.get("full_name") or current.get("username", "")
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


class GenerateWordRequest(BaseModel):
    month: int
    year: int
    hkv_ipcas: list = []
    hkv_payment: list = []
    dept_summaries: list = []


@router.post("/generate-word")
def generate_word(
    body: GenerateWordRequest,
    current: dict = Depends(require_feature("menu.reports")),
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


@router.post("/generate-dept-zip")
async def generate_dept_zip(
    gdv_file: UploadFile = File(None),
    teller_file: UploadFile = File(None),
    current: dict = Depends(require_feature("menu.reports")),
    db: sqlite3.Connection = Depends(get_db),
):
    ipcas_grouped: dict = {}
    payment_grouped: dict = {}
    month, year = 0, 0

    if gdv_file and gdv_file.filename:
        try:
            raw = await gdv_file.read()
            rows, m, y = parse_ipcas(raw)
            ipcas_grouped = enrich_and_group(rows, db, is_payment=False)
            month, year = m or month, y or year
        except Exception as e:
            log.error("generate_dept_zip IPCAS: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file GDV: {e}")

    if teller_file and teller_file.filename:
        try:
            raw = await teller_file.read()
            rows = parse_payment_teller(raw)
            payment_grouped = enrich_and_group(rows, db, is_payment=True)
        except Exception as e:
            log.error("generate_dept_zip Payment: %s", e)
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file Teller: {e}")

    all_depts = set(ipcas_grouped.keys()) | set(payment_grouped.keys())
    if not all_depts:
        raise HTTPException(status_code=400, detail="Không có dữ liệu để tạo báo cáo")

    staff_name = current.get("full_name") or current.get("username", "")
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
