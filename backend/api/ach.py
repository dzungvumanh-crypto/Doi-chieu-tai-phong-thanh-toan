"""API endpoints cho tính năng Chấm đối chiếu ACH."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.core.uploads import read_limited, safe_filename
from backend.services import ach_service
from backend.services.ach.validate import validate_required_files

router = APIRouter(prefix='/api/ach', tags=['ach'])

# Hai mức quyền — giống cham459901 / doi_chieu_song_phuong:
#   menu.cham_ach     = vào xem trang, kiểm tra file, theo dõi tiến độ, tải kết quả
#   cham_ach.process  = khởi động / tiếp tục / dừng một lần chạy
# Tách ra để cấp được quyền chỉ-xem cho người theo dõi kết quả mà không cho chạy.
_XEM  = require_feature('menu.cham_ach')
_CHAY = require_feature('cham_ach.process')

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
    ngay_doi_chieu: str = Form(''),
    bo_qua_checkpoint: bool = Form(False),
    chi_tim_timeout: bool = Form(False),
    _=Depends(_CHAY),
):
    """
    Nhận nhiều file (PDF, GL02.zip, GW.xlsx, MIS_DI.zip x2, MIS_DEN.zip x2).
    Trả về {job_id} ngay lập tức, pipeline chạy nền.

    bo_qua_checkpoint=True — chạy thẳng một mạch tới báo cáo cuối, coi toàn bộ
    MIS_đi mặc định đúng, KHÔNG dừng lại chờ xác nhận thủ công (tính năng mới
    2026-07-31, xem project_ach_chay_thang_bo_qua_checkpoint). Mặc định False —
    hành vi Checkpoint bắt buộc như từ trước tới nay không đổi.

    chi_tim_timeout=True (2026-08-21, xem project_ach_gl02_optional_tiered_deps)
    — người dùng xác nhận tay (checkbox) đang thiếu GL02/MIS_đến, chỉ muốn chạy
    để tìm "Timeout không đi kênh" (Tầng 0). Mặc định False — vẫn bắt buộc đủ
    file như cũ, không đổi hành vi.

    LƯU Ý (bug thật phát hiện 2026-07-31, sửa cùng lúc): `ngay_doi_chieu`/
    `bo_qua_checkpoint` PHẢI khai báo `Form(...)` tường minh — khi route có
    `list[UploadFile]`, FastAPI KHÔNG tự suy luận tham số kiểu đơn giản khác là
    Form field (khác giả định trước đó); để mặc định thường sẽ luôn nhận giá trị
    default, không đọc được dữ liệu client gửi lên.
    """
    if not files:
        raise HTTPException(400, 'Cần upload ít nhất 1 file.')

    saved: dict[str, bytes] = {}
    total_size = 0
    for f in files:
        # Trần cho TỪNG file = phần dung lượng còn lại của cả lượt: đọc theo
        # khối và dừng đúng lúc, thay vì nạp trọn file vào RAM rồi mới đo.
        # Thông điệp phải tự viết: read_limited() nêu con số nó nhận được, mà ở
        # đây con số đó là phần CÒN LẠI ("vượt quá 137 MB") — người đọc không
        # hiểu 137 ở đâu ra.
        try:
            data = await read_limited(f, _MAX_UPLOAD - total_size)
        except HTTPException as e:
            # Chỉ 413 (vượt trần) mới đổi thông điệp — bắt rộng "mọi HTTPException"
            # sẽ biến lỗi tương lai khác của read_limited() thành "vượt 500 MB" sai
            # lệch chẩn đoán (review PR#54, khanhbq693).
            if e.status_code != 413:
                raise
            raise HTTPException(
                413, f'Tổng kích thước file vượt quá {_MAX_UPLOAD // (1024 * 1024)} MB.')
        total_size += len(data)
        # Tên file do client đặt — phải cắt hết thành phần đường dẫn trước khi
        # ghép vào thư mục job, xem backend/core/uploads.py.
        filename = safe_filename(f.filename, f'file_{len(saved)}.dat')
        if filename in saved:
            raise HTTPException(
                400,
                f"Có hai file cùng tên '{filename}' trong một lượt tải lên — "
                "đổi tên hoặc bỏ bớt rồi thử lại.",
            )
        saved[filename] = data

    ngay = ngay_doi_chieu.strip() or None
    job_id = ach_service.start_job(
        saved, ngay, bo_qua_checkpoint=bo_qua_checkpoint, chi_tim_timeout=chi_tim_timeout,
    )
    return {'job_id': job_id}


class ValidateRequest(BaseModel):
    filenames: list[str]


@router.post('/validate')
def validate_files(
    req: ValidateRequest,
    _=Depends(_XEM),
):
    """Kiểm tra sớm theo tên file đã chọn (mode upload) — chưa cần upload nội dung."""
    return validate_required_files(req.filenames)


@router.post('/continue/{job_id}')
async def continue_job(
    job_id: str,
    file: UploadFile,
    _=Depends(_CHAY),
):
    """Checkpoint xác nhận thủ công tại MIS_đi (Bước 3) — nhận file
    <ngày>_ACH_ConfirmMISdi.xlsx đã điền cột LOAI_BO (và REFHUB bổ sung nếu có),
    chạy lại toàn bộ pipeline áp dụng MIS_đi chuẩn rồi tiếp tục tới báo cáo cuối."""
    data = await read_limited(file, ten='File xác nhận')
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
    _=Depends(_XEM),
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
        'xac_nhan_count':      job.get('xac_nhan_count'),
        'xac_nhan_tong_tien':  job.get('xac_nhan_tong_tien'),
        'stage':            job.get('stage', 0),
        'progress':         job.get('progress', 0.0),
        'summary':          job.get('summary'),
    }


@router.post('/cancel/{job_id}')
def cancel_job(
    job_id: str,
    _=Depends(_CHAY),
):
    ok = ach_service.cancel_job(job_id)
    if not ok:
        raise HTTPException(404, 'Job không tồn tại hoặc đã kết thúc.')
    return {'ok': True}


@router.get('/download/{job_id}/{filename}')
def download_file(
    job_id: str,
    filename: str,
    _=Depends(_XEM),
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
