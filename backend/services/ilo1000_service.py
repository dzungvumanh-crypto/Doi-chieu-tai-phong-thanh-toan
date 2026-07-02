"""Job management cho pipeline Chấm ILO1000.

Pattern giống ach_service.py:
  - In-memory job store (_jobs dict)
  - Background thread + cancel_event
  - Incremental log via polling
  - Auto-cleanup sau TTL
"""

import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

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


def start_job(saved_files: dict[str, bytes]) -> str:
    """Lưu file upload, chạy pipeline trong background thread. Trả job_id."""
    job_id, job = _new_job()

    input_dir = TEMP_DIR / job_id / 'input'
    input_dir.mkdir(parents=True, exist_ok=True)
    Path(job['output_dir']).mkdir(parents=True, exist_ok=True)

    for filename, data in saved_files.items():
        (input_dir / filename).write_bytes(data)

    threading.Thread(
        target=_run,
        args=(job_id, str(input_dir), job['output_dir']),
        daemon=True,
    ).start()
    return job_id


def start_from_folder(folder_path: str) -> str:
    """Chạy pipeline trực tiếp từ thư mục server (không cần upload file). Trả job_id."""
    job_id, job = _new_job()
    Path(job['output_dir']).mkdir(parents=True, exist_ok=True)

    threading.Thread(
        target=_run,
        args=(job_id, folder_path, job['output_dir']),
        daemon=True,
    ).start()
    return job_id


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
    safe_name = os.path.basename(filename)
    path = Path(job['output_dir']) / safe_name
    return path if path.exists() else None


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
