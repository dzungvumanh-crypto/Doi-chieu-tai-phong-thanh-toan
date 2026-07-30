"""API endpoints cho tính năng Chấm đối chiếu ACH."""

import glob
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.services import ach_service
from backend.services.ach.validate import validate_required_files

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


class ValidateRequest(BaseModel):
    filenames: list[str]


@router.post('/validate')
def validate_files(
    req: ValidateRequest,
    _=Depends(require_feature('menu.cham_ach')),
):
    """Kiểm tra sớm theo tên file đã chọn (mode upload) — chưa cần upload nội dung."""
    return validate_required_files(req.filenames)


class FolderRequest(BaseModel):
    folder_path: str
    ngay_doi_chieu: str = ''


@router.post('/validate_folder')
def validate_folder(
    req: FolderRequest,
    _=Depends(require_feature('menu.cham_ach')),
):
    """Kiểm tra sớm theo tên file có trong thư mục server (mode folder)."""
    p = Path(req.folder_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f'Thư mục không tồn tại: {req.folder_path}')

    filenames = [
        os.path.basename(f)
        for f in glob.glob(os.path.join(str(p), '**', '*'), recursive=True)
        if os.path.isfile(f)
    ]
    return validate_required_files(filenames)


@router.post('/start_folder')
def start_from_folder(
    req: FolderRequest,
    _=Depends(require_feature('menu.cham_ach')),
):
    """Chạy pipeline từ thư mục server (không upload file)."""
    p = Path(req.folder_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(400, f'Thư mục không tồn tại: {req.folder_path}')

    ngay = req.ngay_doi_chieu.strip() or None
    job_id = ach_service.start_from_folder(str(p), ngay)
    return {'job_id': job_id}


@router.post('/continue/{job_id}')
async def continue_job(
    job_id: str,
    file: UploadFile,
    _=Depends(require_feature('menu.cham_ach')),
):
    """Checkpoint xác nhận thủ công (Bước 3) — nhận file <ngày>_ACH_XacNhan.xlsx đã
    điền cột KET_QUA_XAC_NHAN (và MSGREF bổ sung nếu có), chạy lại toàn bộ pipeline
    áp dụng xác nhận rồi tiếp tục tới báo cáo cuối."""
    data = await file.read()
    try:
        ach_service.continue_job(job_id, data, file.filename or 'xac_nhan.xlsx')
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {'ok': True}


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
        'status':           job['status'],
        'logs':             job['logs'][since:],
        'files':            job['files'],
        'error':            job['error'],
        'xac_nhan_count':   job.get('xac_nhan_count'),
        'mode':             job.get('mode'),
        'final_output_dir': job.get('final_output_dir'),
        'copy_error':       job.get('copy_error'),
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
