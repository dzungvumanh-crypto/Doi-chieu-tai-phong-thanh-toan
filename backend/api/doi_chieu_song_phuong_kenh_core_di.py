"""API endpoints — "Đối chiếu đi" (Kênh↔Hub + Hub↔Core chạy tự động nối tiếp trong 1 job).

Mirror `doi_chieu_song_phuong_kenh_core.py` (chiều đến) — xem docstring
`doi_chieu_song_phuong_kenh_core_di_service.py` cho lý do tách service/package riêng thay vì tham
số hoá `chieu` trong module đến.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.core.uploads import MAX_REQUEST_BYTES, safe_filename, save_upload_to, so_mb
from backend.services import doi_chieu_song_phuong_common as common
from backend.services import doi_chieu_song_phuong_kenh_core_di_service as svc

router = APIRouter(
    prefix="/api/doi_chieu_song_phuong_kenh_core_di", tags=["doi_chieu_song_phuong_kenh_core_di"],
)

_MB = 1024 * 1024

# Trần TỔNG dung lượng một lượt upload — cùng công thức/biến .env với "đến"
# (SONG_PHUONG_MAX_UPLOAD_MB) vì cùng loại dữ liệu nguồn (HUB zip, GL02 zip ~150-160MB).
_MAX_UPLOAD = max(_MB, min(so_mb("SONG_PHUONG_MAX_UPLOAD_MB", 500) * _MB, MAX_REQUEST_BYTES - 8 * _MB))


def _dl_headers(filename: str) -> dict:
    fallback = "".join(ch if ord(ch) < 128 and ch not in '\\"' else "_" for ch in filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


class ReadinessRequest(BaseModel):
    ngay: str
    ma_nh: str
    file_names: list[str]  # tên file đã chọn để upload (chỉ tên, chưa upload nội dung)


@router.post("/check_readiness")
def check_readiness(
    req: ReadinessRequest,
    _=Depends(require_feature("menu.doi_chieu_song_phuong")),
):
    """Dò TÊN file (không đọc byte) xem đã đủ dữ liệu chạy Kênh↔Hub / Hub↔Core CHIỀU ĐI chưa —
    cho banner cảnh báo TRƯỚC khi bấm "Chạy". KHÔNG chặn nút Chạy."""
    if not (len(req.ngay) == 8 and req.ngay.isdigit()):
        raise HTTPException(400, f"Ngày không hợp lệ (cần dạng YYYYMMDD): {req.ngay}")
    if not req.file_names:
        raise HTTPException(400, "Chưa chọn file nào.")

    return common.kiem_tra_du_lieu(req.file_names, req.ngay, req.ma_nh, chieu="DI")


@router.post("/start_upload")
async def start_from_upload(
    files: list[UploadFile],
    ngay: str = Form(...),
    ma_nh: str = Form(...),
    _=Depends(require_feature("doi_chieu_song_phuong_kenh_core_di.process")),
):
    """Chạy "Đối chiếu đi" từ file tải lên qua trình duyệt — cho phép tải thẳng nhiều file (HUB
    zip, kênh xlsx, GL02 zip/CSV đã phân loại, OSB xlsx) cùng lúc.

    Ghi THẲNG từng khối xuống thư mục job (`save_upload_to`), không gom vào RAM trước — cùng
    khuôn mẫu `backend/api/ach.py::start_job()`.

    LƯU Ý: khi route có `list[UploadFile]`, FastAPI không tự suy luận tham số đơn giản khác là
    Form field — `ngay`/`ma_nh` PHẢI khai báo `Form(...)` tường minh (bẫy đã dính ở ACH)."""
    if not files:
        raise HTTPException(400, "Cần chọn ít nhất 1 file.")
    if not (len(ngay) == 8 and ngay.isdigit()):
        raise HTTPException(400, f"Ngày không hợp lệ (cần dạng YYYYMMDD): {ngay}")

    try:
        job_id, input_dir = svc.tao_job(ngay, ma_nh)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        total_size = 0
        da_luu: set[str] = set()
        for f in files:
            filename = safe_filename(f.filename, f"file_{len(da_luu)}.dat")
            if filename in da_luu:
                raise HTTPException(
                    400,
                    f"Có hai file cùng tên '{filename}' trong một lượt tải lên — "
                    "đổi tên hoặc bỏ bớt rồi thử lại.",
                )
            da_luu.add(filename)
            try:
                total_size += await save_upload_to(
                    f, input_dir / filename, _MAX_UPLOAD - total_size)
            except HTTPException as e:
                if e.status_code != 413:
                    raise
                raise HTTPException(
                    413, f"Tổng kích thước file vượt quá {_MAX_UPLOAD // (1024 * 1024)} MB.")
    except BaseException:
        svc.bo_job(job_id)
        raise

    svc.chay_job(job_id)
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
    _=Depends(require_feature("doi_chieu_song_phuong_kenh_core_di.process")),
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
    """Tải 1 file kết quả (Kênh↔Hub: tổng hợp .xlsx + chi tiết .csv; Hub↔Core: .xlsx + .csv)."""
    path = svc.get_output_file(job_id, filename)
    if path is None:
        raise HTTPException(404, "File không tồn tại hoặc job đã hết hạn.")
    media_type = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        headers=_dl_headers(filename),
    )
