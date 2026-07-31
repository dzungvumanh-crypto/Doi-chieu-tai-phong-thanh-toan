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

import pandas as pd

from backend.services.ach.pipeline import main_from_dir
from backend.services.ach.b4_xu_ly_mis_di import _doc_sheet_confirm_mis_di

TEMP_DIR    = Path('data/temp_ach')
CLEANUP_TTL = 4 * 3600  # giữ file kết quả tối đa 4 giờ
_OUTPUT_SUBFOLDER = 'Output'  # tên thư mục con khi copy kết quả về thư mục dữ liệu (mode folder)

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
        'xac_nhan_file':  None,   # tên file <ngày>_ACH_ConfirmMISdi.xlsx khi đang chờ xác nhận
        'xac_nhan_count': None,   # số giao dịch MIS_đi cần chấm (đọc từ sheet MIS_DI_CONFIRM) — None nếu không đếm được
        'xac_nhan_tong_tien': None,  # tổng SO_TIEN các giao dịch cần chấm — None nếu không đếm được
        'mode':           'upload',  # 'upload' | 'folder' — quyết định có copy kết quả về thư mục nguồn hay không
        'source_folder':  None,   # đường dẫn thư mục người dùng chọn (chỉ có ở mode folder)
        'final_output_dir': None,  # nơi kết quả cuối THỰC SỰ nằm sau khi copy (mode folder, copy thành công)
        'copy_error':     None,   # lý do copy về thư mục nguồn thất bại (nếu có)
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
    job['mode']      = 'upload'

    thread = threading.Thread(
        target=_run,
        args=(job_id, str(input_dir), job['output_dir'], ngay),
        kwargs={'dung_sau_mis_di': True},
        daemon=True,
    )
    thread.start()
    return job_id


def start_from_folder(folder_path: str, ngay: str | None) -> str:
    """Chạy pipeline trực tiếp từ thư mục server (không cần upload file). Trả job_id.
    Luôn chạy ở chế độ Checkpoint — xem `start_job()`. Kết quả cuối sẽ được copy về
    lại `folder_path` (xem `_copy_results_to_source()`)."""
    job_id, job = _new_job()
    Path(job['output_dir']).mkdir(parents=True, exist_ok=True)

    job['input_dir']     = folder_path
    job['ngay']           = ngay
    job['mode']           = 'folder'
    job['source_folder']  = folder_path

    thread = threading.Thread(
        target=_run,
        args=(job_id, folder_path, job['output_dir'], ngay),
        kwargs={'dung_sau_mis_di': True},
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


def _thong_ke_mis_di_can_confirm(xac_nhan_path: str) -> tuple[int | None, int | None]:
    """Đếm tổng số giao dịch + tổng số tiền trên sheet MIS_DI_CONFIRM của file
    Checkpoint vừa tạo — CHỈ phục vụ hiển thị UX ("Có XX giao dịch, YY VND cần
    chấm"), không dùng để quyết định gì trong pipeline. Tái dùng đúng parser đã có
    (`_doc_sheet_confirm_mis_di`) thay vì viết lại logic đọc sheet. Trả (None, None)
    nếu không đếm được (file lỗi/thiếu) — không được để lỗi ở đây làm gián đoạn
    luồng Checkpoint chính."""
    try:
        df, _refhub_bo_sung = _doc_sheet_confirm_mis_di(xac_nhan_path)
        so_luong  = len(df)
        tong_tien = int(pd.to_numeric(df['SO_TIEN'], errors='coerce').fillna(0).sum()) if so_luong else 0
        return so_luong, tong_tien
    except Exception:
        return None, None


def _copy_results_to_source(job: dict, output_dir: str, result_files: list[str], log) -> None:
    """Bước 4 (UX) — copy toàn bộ file kết quả cuối về `<source_folder>/Output/` để
    người dùng không phải tìm trong `data/temp_ach/...`. CHỈ áp dụng mode folder.
    Không ảnh hưởng `job['files']`/`job['status']` đã có — nút tải trong
    `data/temp_ach` (qua `/api/ach/download/...`) vẫn luôn hoạt động độc lập, dùng
    làm phương án dự phòng nếu copy lỗi (VD ổ mạng mất kết nối)."""
    dest_dir = Path(job['source_folder']) / _OUTPUT_SUBFOLDER
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for fname in result_files:
            shutil.copy2(Path(output_dir) / fname, dest_dir / fname)
        job['final_output_dir'] = str(dest_dir)
        job['copy_error']       = None
        log(f'[JOB] Đã copy {len(result_files):,} file kết quả về: {dest_dir}')
    except Exception as e:
        job['final_output_dir'] = None
        job['copy_error']       = str(e)
        log(f'[JOB][LỖI] Không copy được kết quả về {dest_dir}: {e} — '
            f'vẫn tải được qua nút bên dưới.')


def _run(job_id: str, input_dir: str, output_dir: str, ngay: str | None,
        dung_sau_mis_di: bool = False, xac_nhan_path: str | None = None):
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
            dung_sau_mis_di=dung_sau_mis_di,
            xac_nhan_path=xac_nhan_path,
        )

        if output_path is None:
            # Pipeline trả None khi bị cancel
            job['status'] = 'cancelled'
            log('[JOB] Đã dừng theo yêu cầu.')
            return

        if dung_sau_mis_di:
            # Dừng ở Checkpoint — chờ người dùng tải + điền + upload lại file xác nhận.
            # LƯU Ý: phải tính xac_nhan_count/tong_tien TRƯỚC khi đổi status — nơi
            # khác (API poll) có thể đọc job ngay khi thấy status đổi, không được để race.
            job['xac_nhan_file'] = os.path.basename(output_path)
            job['files']         = [job['xac_nhan_file']]
            job['xac_nhan_count'], job['xac_nhan_tong_tien'] = _thong_ke_mis_di_can_confirm(output_path)
            job['status']        = 'awaiting_confirmation'
            log('[JOB] Đang chờ xác nhận thủ công MIS_đi.')
            return

        # Thu thập các file kết quả (xlsx + CSV)
        result_files = []
        base = os.path.basename(output_path).replace('.xlsx', '')
        for fname in os.listdir(output_dir):
            if fname.endswith('.xlsx') or (fname.endswith('.csv') and base.replace('doi_chieu_', '') in fname):
                result_files.append(fname)
        result_files.sort()

        job['files'] = result_files

        # LƯU Ý: copy TRƯỚC khi đổi status='done' — polling có thể dừng lại ngay khi
        # thấy 'done' (xem frontend `_stop_timer()`), không được để race làm mất
        # thông tin final_output_dir/copy_error ở lần poll đầu tiên bắt được 'done'.
        if job['mode'] == 'folder' and job['source_folder']:
            _copy_results_to_source(job, output_dir, result_files, log)

        job['status'] = 'done'

    except Exception as e:
        import traceback
        if xac_nhan_path is not None and isinstance(e, ValueError):
            # Lỗi do file xác nhận điền sai/thiếu (ap_dung_confirm_mis_di) — quay lại
            # chờ xác nhận để người dùng sửa và upload lại, không coi là lỗi chung cuộc.
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
