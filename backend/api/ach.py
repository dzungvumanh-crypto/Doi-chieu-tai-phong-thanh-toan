"""API endpoints cho tính năng Chấm đối chiếu ACH."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from backend.core.deps import require_feature
from backend.services import ach_service

router = APIRouter(prefix='/api/ach', tags=['ach'])

_MAX_UPLOAD = 500 * 1024 * 1024  # 500 MB tổng


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
    ngay_doi_chieu: str = '',
    _=Depends(require_feature('menu.cham_ach')),
):
    """
    Nhận nhiều file (PDF, GL02.zip, GW.xlsx, MIS_DI.zip x2, MIS_DEN.zip x2).
    Trả về {job_id} ngay lập tức, pipeline chạy nền.
    """
    if not files:
        raise HTTPException(400, 'Cần upload ít nhất 1 file.')

    saved: dict[str, bytes] = {}
    total_size = 0
    for f in files:
        data = await f.read()
        total_size += len(data)
        if total_size > _MAX_UPLOAD:
            raise HTTPException(413, 'Tổng kích thước file vượt quá 500 MB.')
        filename = f.filename or f'file_{len(saved)}'
        saved[filename] = data

    ngay = ngay_doi_chieu.strip() or None
    job_id = ach_service.start_job(saved, ngay)
    return {'job_id': job_id}


@router.get('/poll/{job_id}')
def poll_job(
    job_id: str,
    since: int = 0,
    _=Depends(require_feature('menu.cham_ach')),
):
    """
    Polling tiến độ.
    since: chỉ trả log từ dòng thứ `since` trở đi (tránh gửi lại log cũ).
    Trả về {status, logs, files, error}.
    """
    job = ach_service.get_job(job_id)
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
    _=Depends(require_feature('menu.cham_ach')),
):
    ok = ach_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(404, 'Job không tồn tại hoặc đã kết thúc.')
    return {'ok': True}


@router.get('/download/{job_id}/{filename}')
def download_file(
    job_id: str,
    filename: str,
    _=Depends(require_feature('menu.cham_ach')),
):
    """Tải file kết quả (.xlsx hoặc .csv)."""
    path = ach_service.get_output_file(job_id, filename)
    if path is None:
        raise HTTPException(404, 'File không tồn tại hoặc job đã hết hạn.')

    if filename.endswith('.xlsx'):
        media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        media = 'text/csv; charset=utf-8-sig'

    return Response(
        content=path.read_bytes(),
        media_type=media,
        headers=_dl_headers(filename),
    )
