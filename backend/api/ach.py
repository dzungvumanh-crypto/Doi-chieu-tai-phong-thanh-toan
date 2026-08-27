"""API endpoints cho tính năng Chấm đối chiếu ACH."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from backend.core.deps import require_feature
from backend.core.uploads import (
    MAX_REQUEST_BYTES,
    read_limited,
    safe_filename,
    save_upload_to,
    so_mb,
)
from backend.services import ach_service
from backend.services.ach.validate import validate_required_files

router = APIRouter(prefix='/api/ach', tags=['ach'])

# Hai mức quyền — giống cham459901 / doi_chieu_song_phuong:
#   menu.cham_ach     = vào xem trang, kiểm tra file, theo dõi tiến độ, tải kết quả
#   cham_ach.process  = khởi động / tiếp tục / dừng một lần chạy
# Tách ra để cấp được quyền chỉ-xem cho người theo dõi kết quả mà không cho chạy.
_XEM  = require_feature('menu.cham_ach')
_CHAY = require_feature('cham_ach.process')

_MB = 1024 * 1024

# Trần TỔNG dung lượng một lượt upload ACH. Chỉnh bằng ACH_MAX_UPLOAD_MB trong .env.
#
# Phải luôn NHỎ HƠN trần thân request của BodySizeLimitMiddleware, chừa chỗ cho
# phần bao multipart. Nếu ngược lại thì middleware chặn trước — nó trả 413 rồi
# đóng luôn kết nối mà KHÔNG đọc nốt thân request đang gửi dở, nên client không
# bao giờ đọc được câu trả lời đó: httpx chỉ thấy socket đứt và báo
# "[WinError 10054] An existing connection was forcibly closed by the remote host".
# Đo được 26/08/2026 (uvicorn + httpx, trần 1 MB, gửi 60 MB): client nhận
# ReadError/WinError, KHÔNG nhận 413, trong khi log máy chủ vẫn ghi 413.
# max(_MB, ...) chỉ để chặn cấu hình vô nghĩa (MAX_REQUEST_MB=4) làm trần thành số âm.
_MAX_UPLOAD = max(_MB, min(so_mb('ACH_MAX_UPLOAD_MB', 500) * _MB, MAX_REQUEST_BYTES - 8 * _MB))


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
    _=Depends(_CHAY),
):
    """
    Nhận nhiều file (PDF, GL02.zip, GW.xlsx, MIS_DI.zip x2, MIS_DEN.zip x2).
    Trả về {job_id} ngay lập tức, pipeline chạy nền.

    bo_qua_checkpoint=True — chạy thẳng một mạch tới báo cáo cuối, coi toàn bộ
    MIS_đi mặc định đúng, KHÔNG dừng lại chờ xác nhận thủ công (tính năng mới
    2026-07-31, xem project_ach_chay_thang_bo_qua_checkpoint). Mặc định False —
    hành vi Checkpoint bắt buộc như từ trước tới nay không đổi.

    LƯU Ý (bug thật phát hiện 2026-07-31, sửa cùng lúc): `ngay_doi_chieu`/
    `bo_qua_checkpoint` PHẢI khai báo `Form(...)` tường minh — khi route có
    `list[UploadFile]`, FastAPI KHÔNG tự suy luận tham số kiểu đơn giản khác là
    Form field (khác giả định trước đó); để mặc định thường sẽ luôn nhận giá trị
    default, không đọc được dữ liệu client gửi lên.
    """
    if not files:
        raise HTTPException(400, 'Cần upload ít nhất 1 file.')

    # Một phiên tại một thời điểm. Hai pipeline pandas cùng ôm vài trăm MB là
    # backend hết RAM và chết ngay giữa lúc đang nhận file của lượt thứ hai —
    # người dùng chỉ thấy "[WinError 10054]", không thấy lỗi nào có nghĩa.
    #
    # Chặn ở ĐÂY chứ không chỉ ở frontend: frontend chỉ nhớ job của tab đang mở,
    # F5 hoặc người khác chạy là nó không biết gì.
    #
    # Thứ tự quan trọng: đặt TRƯỚC vòng read_limited(). Tới được dòng này thì
    # Starlette đã nhận xong thân request (spool ra đĩa khi quá 1 MB) nên client
    # đọc được 409 đàng hoàng; read_limited() mới là chỗ kéo file lên RAM.
    dang = ach_service.job_dang_chay()
    if dang:
        raise HTTPException(409, {
            'message': (
                f"Máy chủ đang bận với một phiên đối chiếu khác (job {dang['job_id']}, "
                f"trạng thái '{dang['status']}'). Chờ phiên đó xong hoặc dừng nó rồi chạy lại."
            ),
            'job': dang,
        })

    # Ghi THẲNG từng khối xuống thư mục job, không gom vào RAM trước. Bản cũ
    # giữ cả lượt (tới 500 MB) trong một dict bytes rồi mới đưa xuống đĩa: đỉnh
    # bộ nhớ gấp đôi dung lượng thật, đúng lúc pipeline lượt trước có thể còn
    # đang ôm DataFrame. Xem save_upload_to() trong backend/core/uploads.py.
    #
    # Job được đăng ký TRƯỚC khi đọc byte đầu tiên, nên trong suốt lúc upload
    # (vài phút với file lớn) `job_dang_chay()` đã báo bận — cửa 409 ở trên
    # trước đây bỏ trống đúng khoảng thời gian này.
    job_id, input_dir = ach_service.tao_job()
    try:
        total_size = 0
        da_luu: set[str] = set()
        for f in files:
            # Tên file do client đặt — phải cắt hết thành phần đường dẫn trước
            # khi ghép vào thư mục job, xem backend/core/uploads.py.
            filename = safe_filename(f.filename, f'file_{len(da_luu)}.dat')
            if filename in da_luu:
                raise HTTPException(
                    400,
                    f"Có hai file cùng tên '{filename}' trong một lượt tải lên — "
                    "đổi tên hoặc bỏ bớt rồi thử lại.",
                )
            da_luu.add(filename)
            # Trần cho TỪNG file = phần dung lượng còn lại của cả lượt: ghi theo
            # khối và dừng đúng lúc. Thông điệp phải tự viết: save_upload_to()
            # nêu con số nó nhận được, mà ở đây con số đó là phần CÒN LẠI
            # ("vượt quá 137 MB") — người đọc không hiểu 137 ở đâu ra.
            try:
                total_size += await save_upload_to(
                    f, input_dir / filename, _MAX_UPLOAD - total_size)
            except HTTPException:
                raise HTTPException(
                    413, f'Tổng kích thước file vượt quá {_MAX_UPLOAD // (1024 * 1024)} MB.')
    except BaseException:
        # Upload hỏng hoặc client cắt kết nối: trả lại chỗ ngay, không để một
        # job 'pending' chết khoá tính năng tới khi hết CLEANUP_TTL.
        ach_service.bo_job(job_id)
        raise

    ngay = ngay_doi_chieu.strip() or None
    ach_service.chay_job(job_id, ngay, bo_qua_checkpoint=bo_qua_checkpoint)
    return {'job_id': job_id}


class ValidateRequest(BaseModel):
    filenames: list[str]


@router.get('/dang-chay')
def job_dang_chay(_=Depends(_XEM)):
    """Máy chủ có đang bận phiên nào không — frontend hỏi TRƯỚC khi upload.

    Không có nó thì cách duy nhất để biết là gửi hết vài trăm MB lên rồi ăn 409.
    """
    return {'job': ach_service.job_dang_chay()}


@router.post('/validate')
def validate_files(
    req: ValidateRequest,
    _=Depends(_XEM),
):
    """Kiểm tra sớm theo tên file đã chọn (mode upload) — chưa cần upload nội dung."""
    res = validate_required_files(req.filenames)
    # Kèm trần dung lượng để frontend chặn TRƯỚC khi gửi: gửi rồi mới bị chặn thì
    # người dùng chỉ nhận được lỗi socket khó hiểu (xem chú thích ở _MAX_UPLOAD).
    res['max_total_mb'] = _MAX_UPLOAD // _MB
    return res


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
