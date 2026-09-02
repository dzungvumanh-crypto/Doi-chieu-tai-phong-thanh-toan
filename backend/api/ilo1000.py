"""API endpoints cho Chấm ILO1000."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.deps import require_feature
from backend.core.uploads import MAX_REQUEST_BYTES, safe_filename, save_upload_to, so_mb
from backend.services import ilo1000_service

router = APIRouter(prefix='/api/ilo1000', tags=['ilo1000'])

_MB = 1024 * 1024

# Trần TỔNG dung lượng một lượt upload ILO1000. Chỉnh bằng ILO1000_MAX_UPLOAD_MB trong .env.
# Luôn kẹp nhỏ hơn MAX_REQUEST_BYTES (xem backend/api/ach.py::_MAX_UPLOAD cho lý do đầy đủ) —
# hằng số 1 GB cũ ở đây không bao giờ đạt tới được vì BodySizeLimitMiddleware đã chặn ở
# MAX_REQUEST_MB (mặc định 600) từ trước, khiến thông báo lỗi tự mâu thuẫn với chính nó.
_MAX_UPLOAD = max(_MB, min(so_mb('ILO1000_MAX_UPLOAD_MB', 500) * _MB, MAX_REQUEST_BYTES - 8 * _MB))


def _dl_headers(filename: str) -> dict:
    fallback = ''.join(ch if ord(ch) < 128 and ch not in '\\"' else '_' for ch in filename)
    return {
        'Content-Disposition': (
            f'attachment; filename="{fallback}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }


@router.post('/start')
async def start_job(
    files: list[UploadFile],
    _=Depends(require_feature('menu.cham_ilo1000')),
):
    """
    Nhận nhiều file (pHub XLSX, UUID CSV, EICP XLS, GL02 CSV/ZIP).
    Pipeline tự nhận dạng loại file + nhóm theo ngày.
    Trả {job_id} ngay, xử lý nền.

    Ghi THẲNG từng khối xuống thư mục job (`save_upload_to`), không gom vào RAM trước — cùng
    khuôn mẫu `backend/api/ach.py::start_job()` (2026-09-02, review khanhbq693 PR#70 mục A/B:
    trước đây `read_limited()` vẫn giữ trọn từng file trong RAM dù có kiểm trần).
    """
    if not files:
        raise HTTPException(400, 'Cần upload ít nhất 1 file.')

    job_id, input_dir = ilo1000_service.tao_job()
    try:
        total_size = 0
        da_luu: set[str] = set()
        for f in files:
            filename = safe_filename(f.filename, f'file_{len(da_luu)}.dat')
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
                    413, f'Tổng kích thước file vượt quá {_MAX_UPLOAD // (1024 * 1024)} MB.')
    except BaseException:
        ilo1000_service.bo_job(job_id)
        raise

    ilo1000_service.chay_job(job_id)
    return {'job_id': job_id}


@router.get('/poll/{job_id}')
def poll_job(
    job_id: str,
    since: int = 0,
    _=Depends(require_feature('menu.cham_ilo1000')),
):
    """Polling tiến độ. since = số log đã nhận rồi."""
    job = ilo1000_service.get_job(job_id)
    if job is None:
        raise HTTPException(404, 'Job không tồn tại hoặc đã hết hạn.')
    return {
        'status': job['status'],
        'logs':   job['logs'][since:],
        'files':  job['files'],
        'error':  job['error'],
    }


@router.post('/cancel/{job_id}')
def cancel_job(
    job_id: str,
    _=Depends(require_feature('menu.cham_ilo1000')),
):
    ok = ilo1000_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(404, 'Job không tồn tại hoặc đã kết thúc.')
    return {'ok': True}


@router.get('/download/{job_id}/{filename}')
def download_file(
    job_id: str,
    filename: str,
    _=Depends(require_feature('menu.cham_ilo1000')),
):
    """Tải file kết quả Excel."""
    path = ilo1000_service.get_output_file(job_id, filename)
    if path is None:
        raise HTTPException(404, 'File không tồn tại hoặc job đã hết hạn.')
    return Response(
        content=path.read_bytes(),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=_dl_headers(filename),
    )
