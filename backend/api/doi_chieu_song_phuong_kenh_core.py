"""API endpoints — "Đối chiếu đến" (Kênh↔Hub + Hub↔Core chạy tự động nối tiếp trong 1 job).

Thay hẳn 2 router cũ `doi_chieu_song_phuong_kenh.py`/`_core.py` (đã xoá) — xem docstring
`doi_chieu_song_phuong_kenh_core_service.py` cho lý do hợp nhất.
"""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.services import doi_chieu_song_phuong_kenh_core_service as svc

router = APIRouter(prefix="/api/doi_chieu_song_phuong_kenh_core", tags=["doi_chieu_song_phuong_kenh_core"])

_MAX_UPLOAD = 800 * 1024 * 1024  # 800 MB tổng — GL02 zip thật ~150-160MB, nhiều file/lượt


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


class FolderRequest(BaseModel):
    folder_path: str
    ngay: str      # YYYYMMDD
    ma_nh: str     # 1 trong 4 ngân hàng — mỗi lần chạy chỉ 1 NH


@router.post("/start_folder")
def start_from_folder(
    req: FolderRequest,
    _=Depends(require_feature("doi_chieu_song_phuong_kenh_core.process")),
):
    """Chạy "Đối chiếu đến" (Kênh↔Hub rồi Hub↔Core) cho 1 ngân hàng, 1 ngày, từ thư mục gốc
    server (chứa thư mục con theo ngày)."""
    p = Path(req.folder_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {req.folder_path}")
    if not (len(req.ngay) == 8 and req.ngay.isdigit()):
        raise HTTPException(400, f"Ngày không hợp lệ (cần dạng YYYYMMDD): {req.ngay}")

    try:
        job_id = svc.start(str(p), req.ngay, req.ma_nh)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@router.post("/start_upload")
async def start_from_upload(
    files: list[UploadFile],
    ngay: str = Form(...),
    ma_nh: str = Form(...),
    _=Depends(require_feature("doi_chieu_song_phuong_kenh_core.process")),
):
    """Chạy "Đối chiếu đến" từ file tải lên qua trình duyệt (thay vì chọn thư mục server) —
    quyết định 2026-08-28: chọn thư mục qua dialog duyệt "rất khó khăn", cho phép tải thẳng
    nhiều file (HUB zip, kênh xlsx, GL02 zip/CSV, OSB xlsx) cùng lúc.

    LƯU Ý: khi route có `list[UploadFile]`, FastAPI không tự suy luận tham số đơn giản khác là
    Form field — `ngay`/`ma_nh` PHẢI khai báo `Form(...)` tường minh (bẫy đã dính ở ACH, xem
    `backend/api/ach.py::start_job`)."""
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file.")
    if not (len(ngay) == 8 and ngay.isdigit()):
        raise HTTPException(400, f"Ngày không hợp lệ (cần dạng YYYYMMDD): {ngay}")

    items: list[tuple[str, bytes]] = []
    total_size = 0
    for f in files:
        data = await f.read()
        total_size += len(data)
        if total_size > _MAX_UPLOAD:
            raise HTTPException(413, "Tổng kích thước file vượt quá 800 MB — dùng chế độ thư mục server thay thế.")
        items.append((f.filename or f"file_{len(items)}", data))

    try:
        job_id = svc.start_upload(items, ngay, ma_nh)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@router.get("/poll/{job_id}")
def poll_job(
    job_id: str,
    since: int = 0,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Polling tiến độ. `since` = số dòng log đã nhận rồi."""
    job = svc.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job không tồn tại hoặc đã hết hạn.")
    return {
        "status": job["status"],
        "logs": job["logs"][since:],
        "files": job["files"],
        "error": job["error"],
        "ngay": job["ngay"],
        "ma_nh": job["ma_nh"],
        "ket_qua": job["ket_qua"],
        "stage": job["stage"],
        "stage_labels": svc.STAGE_LABELS,
    }


@router.post("/cancel/{job_id}")
def cancel_job(
    job_id: str,
    _=Depends(require_feature("doi_chieu_song_phuong_kenh_core.process")),
):
    ok = svc.cancel_job(job_id)
    if not ok:
        raise HTTPException(404, "Job không tồn tại hoặc đã kết thúc.")
    return {"ok": True}


_MEDIA_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}


@router.get("/download/{job_id}/{filename}")
def download_file(
    job_id: str,
    filename: str,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Tải 1 file kết quả (Kênh↔Hub: tổng hợp .xlsx + chi tiết .csv/.xlsx; Hub↔Core: .xlsx)."""
    path = svc.get_output_file(job_id, filename)
    if path is None:
        raise HTTPException(404, "File không tồn tại hoặc job đã hết hạn.")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers=_dl_headers(filename),
    )
