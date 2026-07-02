"""API endpoints cho Chấm ILO1000."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.deps import require_feature
from backend.services import ilo1000_service

router = APIRouter(prefix='/api/ilo1000', tags=['ilo1000'])

_MAX_UPLOAD = 1_000 * 1024 * 1024  # 1 GB


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
    """
    if not files:
        raise HTTPException(400, 'Cần upload ít nhất 1 file.')

    saved: dict[str, bytes] = {}
    total_size = 0
    for f in files:
        data = await f.read()
        total_size += len(data)
        if total_size > _MAX_UPLOAD:
            raise HTTPException(413, 'Tổng kích thước file vượt quá 1 GB.')
        filename = f.filename or f'file_{len(saved)}'
        saved[filename] = data

    job_id = ilo1000_service.start_job(saved)
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
