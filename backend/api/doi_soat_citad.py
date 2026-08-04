# -*- coding: utf-8 -*-
"""
backend/api/doi_soat_citad.py
------------------------------
API đối soát lệnh CITAD (NHNN) ↔ IPCAS (Agribank) — Phòng Thanh toán.

Logic parse/đối soát/xuất Excel lấy NGUYÊN từ `parsers.py`/`reconcile.py`/
`exporters.py` (port từ `citad-fixed/DoiSoatCITAD.py`, không sửa logic) —
xem docstring từng file trong `backend/services/doi_soat_citad/`.

Router MỚI — đã đăng ký sẵn trong `backend/api/registry.py` và bảng
`doi_soat_citad_history` đã thêm sẵn trong `backend/db/migrations.py` (cùng
PR này, cần Người 1 duyệt vì đây là 2 file dùng chung).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.database import get_db
from backend.core.deps import require_feature
from backend.schemas.doi_soat_citad import ExportIn, HistoryOut, ReconcileResultOut
from backend.services.doi_soat_citad import exporters, parsers, reconcile
from backend.services.doi_soat_citad.history_service import (
    get_recon_detail,
    list_recon_history,
    save_recon_history,
)


def _safe_filename(name: str) -> str:
    """Lọc ký tự có thể phá cấu trúc header Content-Disposition (dấu ngoặc
    kép, xuống dòng, backslash) — `ngay_cham` đến từ input người dùng."""
    return re.sub(r'[\r\n"\\]', '_', name)

router = APIRouter(prefix="/api/doi-soat-citad", tags=["doi-soat-citad"])


def _save_uploads(files: Optional[List[UploadFile]]) -> tuple[list[str], list[str], callable]:
    """Lưu danh sách UploadFile ra file tạm, trả về (đường dẫn, tên gốc, cleanup).
    parsers.py tự xử lý .zip nội bộ (CITAD/IPCAS) nên ở đây chỉ cần ghi bytes
    ra đúng phần mở rộng gốc — không cần giải nén ở lớp API."""
    if not files:
        return [], [], lambda: None
    paths, names = [], []
    for f in files:
        suffix = os.path.splitext(f.filename or "")[1] or ".dat"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(f.file.read())
            paths.append(tmp.name)
        names.append(f.filename or os.path.basename(paths[-1]))

    def cleanup():
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass

    return paths, names, cleanup


@router.post("/reconcile", response_model=ReconcileResultOut)
async def do_reconcile(
    ngay_cham: str = Form(...),
    citad_files: List[UploadFile] = File(default=[]),
    ipcas_files: List[UploadFile] = File(default=[]),
    hub_files: List[UploadFile] = File(default=[]),
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    if not citad_files or not ipcas_files:
        raise HTTPException(400, "Cần ít nhất file CITAD và file IPCAS")

    # Đọc/ghi file tạm (I/O) + parse Excel/CSV (CPU, có thể mất vài giây với
    # file lớn/nhiều dòng) đều là hàm ĐỒNG BỘ — chạy thẳng trong endpoint
    # async sẽ CHẶN CẢ event loop của FastAPI, ảnh hưởng MỌI người dùng khác
    # đang thao tác trên app TTTT (không riêng module CITAD) trong lúc xử
    # lý. Gộp hết vào 1 hàm sync, chạy qua asyncio.to_thread để nhường lại
    # event loop cho các request khác.
    def _blocking_parse_and_reconcile():
        citad_paths, citad_names, cleanup_citad = _save_uploads(citad_files)
        ipcas_paths, ipcas_names, cleanup_ipcas = _save_uploads(ipcas_files)
        hub_paths, hub_names, cleanup_hub = _save_uploads(hub_files)
        try:
            citad_rows, citad_errors = parsers.parse_citad_files(citad_paths)
            ipcas_rows, ipcas_errors = parsers.parse_ipcas_files(ipcas_paths, ngay_cham)
            hub_rows, hub_errors = parsers.parse_hub_files(hub_paths, ngay_cham)
        finally:
            cleanup_citad()
            cleanup_ipcas()
            cleanup_hub()
        errors = citad_errors + ipcas_errors + hub_errors
        n_khop, lech = reconcile.run_doiSoat_ram(citad_rows, ipcas_rows, hub_rows)
        return (
            citad_rows, ipcas_rows, hub_rows, citad_names, ipcas_names, hub_names,
            errors, n_khop, lech,
        )

    (
        citad_rows, ipcas_rows, hub_rows, citad_names, ipcas_names, hub_names,
        errors, n_khop, lech,
    ) = await asyncio.to_thread(_blocking_parse_and_reconcile)

    if errors and not (citad_rows or ipcas_rows or hub_rows):
        raise HTTPException(422, "; ".join(errors))

    history_saved, history_error = True, None
    try:
        # save_recon_history() json.dumps() nguyên danh sách lech (có thể
        # hàng chục nghìn dòng) + ghi SQLite — đồng bộ, chạy thẳng trong
        # route async sẽ chặn event loop CHUNG của backend giống hệt lớp lỗi
        # đã sửa ở on_upload (frontend). Bọc asyncio.to_thread như bước
        # parse+đối soát ngay phía trên.
        await asyncio.to_thread(
            save_recon_history,
            db, ngay_cham=ngay_cham, performed_by_id=current["id"],
            citad_file_names=citad_names, ipcas_file_names=ipcas_names, hub_file_names=hub_names,
            total_citad=len(citad_rows), total_ipcas=len(ipcas_rows), total_hub=len(hub_rows),
            n_khop=n_khop, lech_rows=lech,
        )
    except Exception as e:  # noqa: BLE001 — không để lỗi lưu lịch sử chặn mất kết quả đối soát
        history_saved, history_error = False, str(e)

    return {
        "n_khop": n_khop,
        "n_lech": len(lech),
        "total_citad": len(citad_rows),
        "total_ipcas": len(ipcas_rows),
        "total_hub": len(hub_rows),
        "lech": lech,
        "history_saved": history_saved,
        "history_error": history_error,
        # Vẫn còn rows đọc được nên không rơi vào nhánh 422 ở trên, nhưng
        # 1 phần file bị lỗi — phải báo cho người dùng biết kết quả có thể
        # THIẾU dữ liệu, không được coi là đối soát đầy đủ.
        "parse_warnings": errors,
    }


@router.post("/export")
# KHÔNG async — exporters.export_doiSoat() đồng bộ, có thể mất vài giây với
# danh sách lệch lớn. FastAPI tự đẩy hàm `def` thường (không async) vào
# threadpool, không chặn event loop dùng chung — đúng cách endpoint export
# của doi_chieu_citad.py đã làm sẵn (không async, không bị lỗi này).
def export_excel(
    payload: ExportIn,
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    """Nhận lại `ngay_cham`, `n_khop`, `lech` mà frontend đang giữ trong state
    (kết quả của lần /reconcile gần nhất) — không bắt người dùng upload lại
    file, giống hệt hành vi bản gốc (đối soát xong mới bấm Xuất Excel)."""
    ngay_cham = payload.ngay_cham
    n_khop = payload.n_khop
    lech = payload.lech
    if not lech and not n_khop:
        raise HTTPException(400, "Chưa có dữ liệu đối soát để xuất")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    try:
        exporters.export_doiSoat(lech, n_khop, ngay_cham, out_path)
        with open(out_path, "rb") as f:
            content = f.read()
    finally:
        # try/finally — nếu export_doiSoat() raise (dữ liệu bất thường), file
        # tạm vẫn phải bị xoá, không thì rò rỉ đĩa dần qua mỗi lượt export lỗi.
        os.remove(out_path)

    fname = _safe_filename(f"DoiSoat_CITAD_IPCAS_{ngay_cham.replace('/', '-')}.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/history", response_model=List[HistoryOut])
async def get_history(
    limit: int = 100,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    # list_recon_history() json.loads() từng dòng lịch sử — đồng bộ, chặn
    # event loop chung nếu chạy thẳng. Xem ghi chú tương tự ở do_reconcile().
    return await asyncio.to_thread(list_recon_history, db, limit)


@router.get("/history/{history_id}")
async def get_history_detail(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    # get_recon_detail() json.loads() snapshot lech_json có thể rất lớn —
    # đồng bộ, chặn event loop chung nếu chạy thẳng. Xem ghi chú tương tự ở
    # do_reconcile().
    detail = await asyncio.to_thread(get_recon_detail, db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")
    return detail


@router.get("/history/{history_id}/export")
# KHÔNG async — cùng lý do với export_excel() ở trên.
def export_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    """Sinh Excel TỪ ĐÚNG snapshot `lech` đã lưu tại thời điểm đối soát
    (không tính lại từ file gốc) — đảm bảo đúng y hệt dữ liệu audit."""
    detail = get_recon_detail(db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    try:
        exporters.export_doiSoat(detail["lech_records"], detail["n_khop"], detail["ngay_cham"], out_path)
        with open(out_path, "rb") as f:
            content = f.read()
    finally:
        os.remove(out_path)

    fname = f"DoiSoat_CITAD_IPCAS_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
