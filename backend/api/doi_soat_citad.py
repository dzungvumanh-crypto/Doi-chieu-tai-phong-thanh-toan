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

VIỆC NẶNG — đọc trước khi sửa file này:
  Mọi endpoint ở đây khai `async def` và đẩy TOÀN BỘ phần nặng (đọc file
  upload, giải nén, parse Excel/CSV, đối soát, sinh xlsx, json.dumps/loads
  danh sách lệch hàng chục nghìn dòng) vào `await run_heavy(...)`.

  KHÔNG dùng `asyncio.to_thread` và KHÔNG khai endpoint `def` thường cho
  việc nặng: cả hai đều lọt ra ngoài `CapacityLimiter` riêng ở
  `backend/core/concurrency.py` (MAX_HEAVY=4). Endpoint `def` rơi vào bể 40
  token chung của anyio — 40 việc nặng đồng thời từng làm `/api/auth/me`
  kẹt 38 giây (số đo trong commit "perf: gỡ nghẽn backend"). Cùng khuôn mẫu
  `backend/api/swift_recon.py` đang dùng.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.database import get_db
from backend.core.concurrency import run_heavy
from backend.core.uploads import safe_filename, save_upload_to_sync
from backend.core.deps import require_feature
from backend.schemas.doi_soat_citad import ExportAllIn, ExportIn, HistoryOut, ReconcileResultOut
from backend.services.doi_soat_citad import exporters, parsers, reconcile, temp_files
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


def _save_uploads(files: Optional[List[UploadFile]], dich: Path) -> tuple[list[str], list[str]]:
    """Lưu danh sách UploadFile vào `dich` trên máy chủ, trả về
    (đường dẫn, tên gốc).

    parsers.py tự xử lý .zip nội bộ (CITAD/IPCAS) nên ở đây chỉ cần ghi ra đúng
    phần mở rộng gốc — không cần giải nén ở lớp API.

    Ghi theo từng khối thẳng xuống đĩa (`save_upload_to_sync`) thay vì
    `read_limited_sync()` rồi mới ghi: một lượt đối soát có thể kèm nhiều file
    CITAD/IPCAS/HUB, gom hết vào RAM trước là đỉnh bộ nhớ gấp đôi mà không đổi
    lại được gì — đằng nào parsers.py cũng chỉ nhận đường dẫn.

    Tên file giữ nguyên bản gốc (đã qua `safe_filename`) để người vận hành mở
    thư mục lượt ra là biết file nào của ai — khác hẳn tên ngẫu nhiên của
    `tempfile`. Trùng tên trong cùng một nhóm thì thêm hậu tố số thứ tự, không
    ghi đè. Dọn dẹp là việc của người tạo thư mục lượt (xem caller).
    """
    if not files:
        return [], []

    paths, names = [], []
    for i, f in enumerate(files):
        ten = safe_filename(f.filename, f"file_{i}.dat")
        dest = dich / ten
        if dest.exists():
            goc, duoi = os.path.splitext(ten)
            dest = dich / f"{goc}_{i}{duoi}"
        save_upload_to_sync(f, dest)
        paths.append(str(dest))
        names.append(f.filename or dest.name)

    return paths, names


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
    # lý. Gộp hết vào 1 hàm sync, chạy qua run_heavy() để vừa nhường lại
    # event loop, vừa nằm trong giới hạn việc nặng dùng chung (xem docstring
    # đầu file).
    def _blocking_parse_and_reconcile():
        # Một thư mục cho cả lượt, ba thư mục con theo nguồn — mở ra là đọc
        # được ngay lượt đó gồm file nào. Xoá cả cụm trong `finally`; lịch dọn
        # 23h chỉ phải hứng những lượt chết giữa chừng.
        luot = temp_files.tao_thu_muc_luot()
        try:
            citad_paths, citad_names = _save_uploads(citad_files, luot / "citad")
            ipcas_paths, ipcas_names = _save_uploads(ipcas_files, luot / "ipcas")
            hub_paths, hub_names = _save_uploads(hub_files, luot / "hub")
            citad_rows, citad_errors = parsers.parse_citad_files(citad_paths, ngay_cham)
            ipcas_rows, ipcas_errors = parsers.parse_ipcas_files(ipcas_paths, ngay_cham)
            hub_rows, hub_errors = parsers.parse_hub_files(hub_paths, ngay_cham)
        finally:
            temp_files.xoa(luot)
        errors = citad_errors + ipcas_errors + hub_errors
        n_khop, lech, khop = reconcile.run_doiSoat_ram(citad_rows, ipcas_rows, hub_rows)
        return (
            citad_rows, ipcas_rows, hub_rows, citad_names, ipcas_names, hub_names,
            errors, n_khop, lech, khop,
        )

    (
        citad_rows, ipcas_rows, hub_rows, citad_names, ipcas_names, hub_names,
        errors, n_khop, lech, khop,
    ) = await run_heavy(_blocking_parse_and_reconcile)

    if errors and not (citad_rows or ipcas_rows or hub_rows):
        raise HTTPException(422, "; ".join(errors))

    history_saved, history_error = True, None
    try:
        # save_recon_history() json.dumps() nguyên danh sách lech (có thể
        # hàng chục nghìn dòng) + ghi SQLite — đồng bộ, chạy thẳng trong
        # route async sẽ chặn event loop CHUNG của backend giống hệt lớp lỗi
        # đã sửa ở on_upload (frontend). Bọc run_heavy() như bước
        # parse+đối soát ngay phía trên.
        await run_heavy(
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
        # Chi tiết từng dòng ĐÃ khớp — chỉ để phục vụ nút "Xuất tất cả lệnh"
        # (frontend giữ trong state, gửi lại /export-all, KHÔNG lưu vào lịch
        # sử — bảng doi_soat_citad_history vẫn chỉ lưu `lech`, tránh phình
        # dung lượng DB thêm ~1000 lần mỗi lượt chấm chỉ để phục vụ 1 nút
        # xuất tùy chọn ít dùng).
        "khop_rows": khop,
        "history_saved": history_saved,
        "history_error": history_error,
        # Vẫn còn rows đọc được nên không rơi vào nhánh 422 ở trên, nhưng
        # 1 phần file bị lỗi — phải báo cho người dùng biết kết quả có thể
        # THIẾU dữ liệu, không được coi là đối soát đầy đủ.
        "parse_warnings": errors,
    }


def _build_doisoat_xlsx(lech, n_khop, ngay_cham) -> bytes:
    """Sinh xlsx ra file tạm rồi đọc lại thành bytes. Hàm ĐỒNG BỘ — luôn gọi
    qua `run_heavy()`, không gọi thẳng trong route async."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    try:
        exporters.export_doiSoat(lech, n_khop, ngay_cham, out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        # try/finally — nếu export_doiSoat() raise (dữ liệu bất thường), file
        # tạm vẫn phải bị xoá, không thì rò rỉ đĩa dần qua mỗi lượt export lỗi.
        os.remove(out_path)


@router.post("/export")
async def export_excel(
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

    content = await run_heavy(_build_doisoat_xlsx, lech, n_khop, ngay_cham)

    fname = _safe_filename(f"DoiSoat_CITAD_IPCAS_{ngay_cham.replace('/', '-')}.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


def _build_doisoat_xlsx_full(lech, khop_rows, ngay_cham) -> bytes:
    """Như _build_doisoat_xlsx() nhưng gọi export_doiSoat_full() — xem
    docstring hàm đó (lech.py::exporters) để biết khác biệt."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as out:
        out_path = out.name
    try:
        exporters.export_doiSoat_full(lech, khop_rows, ngay_cham, out_path)
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        os.remove(out_path)


@router.post("/export-all")
async def export_excel_all(
    payload: ExportAllIn,
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    """"Xuất tất cả lệnh" — cùng cơ chế với /export (frontend gửi lại đúng
    kết quả /reconcile gần nhất đang giữ trong state, không upload lại
    file), nhưng gồm ĐỦ cả 2 danh sách khớp + lệch (xem
    ReconcileResultOut.khop_rows) thay vì chỉ lệch."""
    ngay_cham = payload.ngay_cham
    lech = payload.lech
    khop_rows = payload.khop_rows
    if not lech and not khop_rows:
        raise HTTPException(400, "Chưa có dữ liệu đối soát để xuất")

    content = await run_heavy(_build_doisoat_xlsx_full, lech, khop_rows, ngay_cham)

    fname = _safe_filename(f"DoiSoat_CITAD_IPCAS_TatCa_{ngay_cham.replace('/', '-')}.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/history", response_model=List[HistoryOut])
async def get_history(
    limit: int = 100,
    tu_ngay: str | None = None,
    den_ngay: str | None = None,
    nguoi_thuc_hien: str | None = None,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    """tu_ngay/den_ngay lọc theo "ngày chấm" (dd/mm/yyyy, để trống = không
    giới hạn đầu/cuối). nguoi_thuc_hien khớp gần đúng theo tên đầy đủ,
    không phân biệt hoa/thường."""
    # list_recon_history() json.loads() từng dòng lịch sử — đồng bộ, chặn
    # event loop chung nếu chạy thẳng. Xem ghi chú tương tự ở do_reconcile().
    return await run_heavy(list_recon_history, db, limit, tu_ngay, den_ngay, nguoi_thuc_hien)


@router.get("/history/{history_id}")
async def get_history_detail(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    # get_recon_detail() json.loads() snapshot lech_json có thể rất lớn —
    # đồng bộ, chặn event loop chung nếu chạy thẳng. Xem ghi chú tương tự ở
    # do_reconcile().
    detail = await run_heavy(get_recon_detail, db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")
    return detail


@router.get("/history/{history_id}/export")
async def export_from_history(
    history_id: int,
    db=Depends(get_db),
    current: dict = Depends(require_feature("menu.doi_soat_citad")),
):
    """Sinh Excel TỪ ĐÚNG snapshot `lech` đã lưu tại thời điểm đối soát
    (không tính lại từ file gốc) — đảm bảo đúng y hệt dữ liệu audit."""
    detail = await run_heavy(get_recon_detail, db, history_id)
    if not detail:
        raise HTTPException(404, "Không tìm thấy")

    content = await run_heavy(
        _build_doisoat_xlsx, detail["lech_records"], detail["n_khop"], detail["ngay_cham"]
    )

    fname = f"DoiSoat_CITAD_IPCAS_lichsu_{history_id}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
