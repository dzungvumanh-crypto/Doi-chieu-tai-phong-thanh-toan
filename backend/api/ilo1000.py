"""API endpoints cho Chấm ILO1000."""

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.services import ilo1000_service

router = APIRouter(prefix='/api/ilo1000', tags=['ilo1000'])

_MAX_UPLOAD = 1_000 * 1024 * 1024  # 1 GB
_CHUNK_SIZE = 1024 * 1024  # 1 MB/lần đọc


async def _read_limited(f: UploadFile, max_bytes: int) -> bytes:
    """Đọc theo khối, dừng NGAY khi vượt `max_bytes` — không nạp trọn file vào RAM
    trước khi biết đã vượt trần (review PR#68 mục P68-5, khanhbq693: `await f.read()`
    trần đọc hết file oversized vào RAM RỒI mới kiểm dung lượng, quá muộn). Cùng ý
    tưởng `backend/core/uploads.py::read_limited()` mà develop đã có (dùng ở ACH) —
    viết lại cục bộ vì module đó chưa tồn tại trên nhánh này (gộp lại khi rebase,
    xem Implementation-notes.html card 68)."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await f.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f'Tổng kích thước file vượt quá {_MAX_UPLOAD // (1024 * 1024)} MB.')
        chunks.append(chunk)
    return b''.join(chunks)


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
        data = await _read_limited(f, _MAX_UPLOAD - total_size)
        total_size += len(data)
        filename = f.filename or f'file_{len(saved)}'
        saved[filename] = data

    job_id = ilo1000_service.start_job(saved)
    return {'job_id': job_id}


class FolderRequest(BaseModel):
    folder_path: str


@router.post('/start_folder')
def start_from_folder(
    req: FolderRequest,
    _=Depends(require_feature('menu.cham_ilo1000')),
):
    """
    Chạy pipeline từ thư mục server (không upload file).
    Thư mục phải tồn tại và chứa file ILO1000 hợp lệ.
    """
    p = Path(req.folder_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f'Thư mục không tồn tại: {req.folder_path}')

    job_id = ilo1000_service.start_from_folder(str(p))
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
