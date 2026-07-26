"""Job management cho pipeline đối chiếu ACH.

Mỗi job:
  - Nhận các file đã upload (lưu vào temp dir)
  - Chạy pipeline trong background thread
  - Trả log theo dạng polling
  - Hỗ trợ cancel và download kết quả
"""

import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.services.ach.pipeline import main_from_dir

TEMP_DIR    = Path('data/temp_ach')
CLEANUP_TTL = 4 * 3600  # giữ file kết quả tối đa 4 giờ

# ─── In-memory job store ─────────────────────────────────────────────────────
# {job_id: {status, logs, files, error, cancel_event, _ts, output_dir}}
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _new_job() -> tuple[str, dict]:
    job_id = uuid.uuid4().hex[:12]
    job    = {
        # pending | running | awaiting_confirmation | done | error | cancelled
        'status':        'pending',
        'logs':          [],
        'files':         [],
        'error':         None,
        'cancel_event':  threading.Event(),
        '_ts':           time.time(),
        'output_dir':    str(TEMP_DIR / job_id / 'output'),
        'input_dir':     None,   # dùng lại cho lần chạy tiếp (Checkpoint Bước 3)
        'ngay':          None,
        'xac_nhan_file': None,   # tên file <ngày>_ACH_XacNhan.xlsx khi đang chờ xác nhận
    }
    with _lock:
        _jobs[job_id] = job
    return job_id, job


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job is None:
        return False
    if job['status'] == 'running':
        job['cancel_event'].set()
        return True
    if job['status'] == 'awaiting_confirmation':
        # Không có thread đang chạy để báo dừng — hủy trực tiếp tại chỗ.
        job['status'] = 'cancelled'
        job['_ts']    = time.time()
        return True
    return False


def start_job(saved_files: dict[str, bytes], ngay: str | None) -> str:
    """
    Tạo job mới, lưu file vào disk, chạy pipeline trong background thread.
    saved_files: {filename: bytes}
    Trả về job_id. Luôn chạy ở chế độ Checkpoint (dừng sau khop_voi_gw() chờ xác
    nhận thủ công nhánh Timeout) — thay cho việc tự động phân loại toàn bộ.
    """
    job_id, job = _new_job()

    input_dir = TEMP_DIR / job_id / 'input'
    input_dir.mkdir(parents=True, exist_ok=True)
    Path(job['output_dir']).mkdir(parents=True, exist_ok=True)

    for filename, data in saved_files.items():
        (input_dir / filename).write_bytes(data)

    job['input_dir'] = str(input_dir)
    job['ngay']      = ngay

    thread = threading.Thread(
        target=_run,
        args=(job_id, str(input_dir), job['output_dir'], ngay),
        kwargs={'dung_sau_khop_gw': True},
        daemon=True,
    )
    thread.start()
    return job_id


def start_from_folder(folder_path: str, ngay: str | None) -> str:
    """Chạy pipeline trực tiếp từ thư mục server (không cần upload file). Trả job_id.
    Luôn chạy ở chế độ Checkpoint — xem `start_job()`."""
    job_id, job = _new_job()
    Path(job['output_dir']).mkdir(parents=True, exist_ok=True)

    job['input_dir'] = folder_path
    job['ngay']      = ngay

    thread = threading.Thread(
        target=_run,
        args=(job_id, folder_path, job['output_dir'], ngay),
        kwargs={'dung_sau_khop_gw': True},
        daemon=True,
    )
    thread.start()
    return job_id


def continue_job(job_id: str, xac_nhan_bytes: bytes, xac_nhan_filename: str) -> None:
    """Checkpoint Bước 3 — nhận file xác nhận đã điền, chạy lại TOÀN BỘ pipeline
    (không resume state) áp dụng xác nhận đó rồi tiếp tục Phase 2 + báo cáo cuối.
    Raise LookupError nếu job không tồn tại, ValueError nếu job không ở trạng thái
    chờ xác nhận."""
    job = get_job(job_id)
    if job is None:
        raise LookupError('Job không tồn tại hoặc đã hết hạn.')
    if job['status'] != 'awaiting_confirmation':
        raise ValueError(f"Job đang ở trạng thái '{job['status']}', không thể chạy tiếp.")

    xac_nhan_dir = TEMP_DIR / job_id / 'xac_nhan_in'
    xac_nhan_dir.mkdir(parents=True, exist_ok=True)
    safe_name  = os.path.basename(xac_nhan_filename) or 'xac_nhan.xlsx'
    saved_path = xac_nhan_dir / safe_name
    saved_path.write_bytes(xac_nhan_bytes)

    job['status'] = 'running'
    job['error']  = None

    thread = threading.Thread(
        target=_run,
        args=(job_id, job['input_dir'], job['output_dir'], job['ngay']),
        kwargs={'xac_nhan_path': str(saved_path)},
        daemon=True,
    )
    thread.start()


def _run(job_id: str, input_dir: str, output_dir: str, ngay: str | None,
        dung_sau_khop_gw: bool = False, xac_nhan_path: str | None = None):
    job = get_job(job_id)
    if job is None:
        return

    job['status'] = 'running'

    def log(msg: str):
        with _lock:
            job['logs'].append(msg)

    try:
        log(f'[JOB {job_id}] Bắt đầu xử lý...')
        output_path = main_from_dir(
            input_dir=input_dir,
            output_dir=output_dir,
            ngay=ngay,
            log_callback=log,
            cancel_event=job['cancel_event'],
            dung_sau_khop_gw=dung_sau_khop_gw,
            xac_nhan_path=xac_nhan_path,
        )

        if output_path is None:
            # Pipeline trả None khi bị cancel
            job['status'] = 'cancelled'
            log('[JOB] Đã dừng theo yêu cầu.')
            return

        if dung_sau_khop_gw:
            # Dừng ở Checkpoint — chờ người dùng tải + điền + upload lại file xác nhận.
            job['xac_nhan_file'] = os.path.basename(output_path)
            job['files']         = [job['xac_nhan_file']]
            job['status']        = 'awaiting_confirmation'
            log('[JOB] Đang chờ xác nhận thủ công nhánh Timeout.')
            return

        # Thu thập các file kết quả (xlsx + CSV)
        result_files = []
        base = os.path.basename(output_path).replace('.xlsx', '')
        for fname in os.listdir(output_dir):
            if fname.endswith('.xlsx') or (fname.endswith('.csv') and base.replace('doi_chieu_', '') in fname):
                result_files.append(fname)
        result_files.sort()

        job['files']  = result_files
        job['status'] = 'done'

    except Exception as e:
        import traceback
        if xac_nhan_path is not None and isinstance(e, ValueError):
            # Lỗi do file xác nhận điền sai/thiếu (ap_dung_xac_nhan) — quay lại chờ
            # xác nhận để người dùng sửa và upload lại, không coi là lỗi chung cuộc.
            job['status'] = 'awaiting_confirmation'
            job['error']  = str(e)
            log(f'[LỖI XÁC NHẬN] {e}')
        else:
            job['error']  = str(e)
            job['status'] = 'error'
            log(f'[ERROR] {e}')
            log(traceback.format_exc())

    finally:
        job['_ts'] = time.time()
        _cleanup_old_jobs()


def get_output_file(job_id: str, filename: str) -> Path | None:
    """Trả về Path đến file nếu tồn tại, None nếu không."""
    job = get_job(job_id)
    if not job:
        return None
    # Security: chỉ cho phép file trong output_dir
    safe_name = os.path.basename(filename)
    path      = Path(job['output_dir']) / safe_name
    return path if path.exists() else None


def _cleanup_old_jobs():
    """Xóa job cũ hơn CLEANUP_TTL khỏi memory + disk."""
    now = time.time()
    with _lock:
        expired = [jid for jid, j in _jobs.items()
                   if j['status'] in ('done', 'error', 'cancelled', 'awaiting_confirmation')
                   and now - j['_ts'] > CLEANUP_TTL]
        for jid in expired:
            del _jobs[jid]
    for jid in expired:
        job_dir = TEMP_DIR / jid
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
