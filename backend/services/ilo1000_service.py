"""Job management cho pipeline Chấm ILO1000.

Pattern giống ach_service.py:
  - In-memory job store (_jobs dict)
  - Background thread + cancel_event
  - Incremental log via polling
  - Auto-cleanup sau TTL
"""

import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.core.uploads import safe_filename
from backend.services.ilo1000.pipeline import main_from_dir
from backend.services.ilo1000.config import CLEANUP_TTL

TEMP_DIR = Path('data/temp_ilo1000')

# ─── In-memory job store ──────────────────────────────────────────────────────
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _new_job() -> tuple[str, dict]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        'status':       'pending',
        'logs':         [],
        'files':        [],
        'error':        None,
        'cancel_event': threading.Event(),
        '_ts':          time.time(),
        'output_dir':   str(TEMP_DIR / job_id / 'output'),
    }
    with _lock:
        _jobs[job_id] = job
    return job_id, job


def get_job(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job and job['status'] == 'running':
        job['cancel_event'].set()
        return True
    return False


def tao_job() -> tuple[str, Path]:
    """Đăng ký một job mới ở trạng thái 'pending' và trả về (job_id, input_dir).

    Tách khỏi `chay_job()` để lớp API ghi THẲNG từng khối file tải lên vào `input_dir`
    (`save_upload_to()`, backend/core/uploads.py), thay vì gom trọn file vào RAM rồi mới đưa
    xuống đây (2026-09-02, review khanhbq693 PR#70 mục B — cùng lỗi/cách sửa đã áp dụng cho
    `ach_service.py::tao_job()`).

    Upload hỏng giữa chừng thì lớp API phải gọi `bo_job()` để trả lại chỗ."""
    job_id, job = _new_job()
    input_dir = TEMP_DIR / job_id / 'input'
    input_dir.mkdir(parents=True, exist_ok=True)
    Path(job['output_dir']).mkdir(parents=True, exist_ok=True)
    job['input_dir'] = str(input_dir)
    return job_id, input_dir


def bo_job(job_id: str) -> None:
    """Huỷ một job chưa chạy (upload lỗi/đứt) — xoá khỏi store và xoá thư mục."""
    with _lock:
        _jobs.pop(job_id, None)
    shutil.rmtree(TEMP_DIR / job_id, ignore_errors=True)


def chay_job(job_id: str) -> None:
    """Khởi chạy pipeline cho job đã nhận đủ file (xem `tao_job()`)."""
    job = get_job(job_id)
    if job is None:
        raise LookupError('Job không tồn tại.')
    threading.Thread(
        target=_run,
        args=(job_id, job['input_dir'], job['output_dir']),
        daemon=True,
    ).start()


def _run(job_id: str, input_dir: str, output_dir: str):
    job = get_job(job_id)
    if job is None:
        return

    job['status'] = 'running'

    def log(msg: str):
        with _lock:
            job['logs'].append(msg)

    try:
        log(f'[JOB {job_id}] Bắt đầu xử lý ILO1000...')
        output_path = main_from_dir(
            input_dir=input_dir,
            output_dir=output_dir,
            log_callback=log,
            cancel_event=job['cancel_event'],
        )

        if output_path is None:
            job['status'] = 'cancelled' if job['cancel_event'].is_set() else 'error'
            job['error']  = 'Không có output — kiểm tra file đầu vào.' if job['status'] == 'error' else None
            log(f'[JOB] {"Đã dừng." if job["status"] == "cancelled" else "Không có kết quả."}')
            return

        # Thu thập tất cả file .xlsx trong output_dir
        result_files = sorted(
            f for f in os.listdir(output_dir)
            if f.endswith('.xlsx')
        )
        job['files']  = result_files
        job['status'] = 'done'
        log(f'[JOB] Hoàn thành. {len(result_files)} file kết quả.')

    except Exception as e:
        import traceback
        job['error']  = str(e)
        job['status'] = 'error'
        log(f'[ERROR] {e}')
        log(traceback.format_exc())

    finally:
        job['_ts'] = time.time()
        _cleanup_old_jobs()


def get_output_file(job_id: str, filename: str) -> Path | None:
    job = get_job(job_id)
    if not job:
        return None
    path = Path(job['output_dir']) / safe_filename(filename)
    return path if path.is_file() else None


def _cleanup_old_jobs():
    now = time.time()
    with _lock:
        expired = [
            jid for jid, j in _jobs.items()
            if j['status'] in ('done', 'error', 'cancelled')
            and now - j['_ts'] > CLEANUP_TTL
        ]
        for jid in expired:
            del _jobs[jid]
    for jid in expired:
        job_dir = TEMP_DIR / jid
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
