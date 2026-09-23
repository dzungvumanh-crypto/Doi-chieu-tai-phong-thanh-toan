"""Job management cho pipeline đối chiếu ACH.

Mỗi job:
  - Nhận các file đã upload (lưu vào temp dir)
  - Chạy pipeline trong background thread
  - Trả log theo dạng polling
  - Hỗ trợ cancel và download kết quả
"""

import gc
import logging
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from backend.core.uploads import safe_filename
from backend.services.ach.pipeline import main_from_dir
from backend.services.ach.b4_xu_ly_mis_di import _doc_sheet_confirm_mis_di
from backend.services.ach.so_tien import LoiDinhDangSoTien
from backend.services.ach import phub_gop

from backend.core.config import BASE_DIR
from backend.core.don_dep import moc_don_gan_nhat

TEMP_DIR    = BASE_DIR / 'data' / 'temp_ach'

# Sau bao lâu thì một job bỏ dở coi như đã chết và KHÔNG còn chiếm máy chủ nữa.
# Đây KHÔNG phải hạn giữ file: file sống tới 23h theo `moc_don_gan_nhat()`
# (backend/core/don_dep.py). Hai con số này từng là một, nên nới hạn giữ file
# lên hết ngày sẽ vô tình khoá chết tính năng cả ngày vì một phiên ai đó bỏ dở.
CLEANUP_TTL = 4 * 3600

# ─── Stage/progress — 5 giai đoạn thật của pipeline (không phải 6 bước UI chung
# chung) — mốc log → (stage, %), tăng dần, không lùi lại. `stage` là index nhãn
# trong STAGE_LABELS, dùng cho stepper phía UI.
STAGE_LABELS = [
    'Đọc dữ liệu',
    'Chuẩn hoá & xử lý',
    'Đối chiếu & phân loại',
    'Tổng hợp báo cáo',
    'Hoàn tất',
]
_STAGE_MARKERS = [
    (re.compile(r'^Ngày đối chiếu:'),               0, 0.05),
    (re.compile(r'^\[B1\] Session:'),                0, 0.10),
    (re.compile(r'^Tìm thấy: GL02='),                0, 0.15),
    (re.compile(r'\[TIMING\] Phase 1 IO:'),          1, 0.45),
    (re.compile(r'^\[JOB\] Đang chờ xác nhận'),      2, 0.50),
    (re.compile(r'\[TIMING\] Phase 2 đối chiếu:'),   2, 0.65),
    (re.compile(r'\[TIMING\] Phase 3 Excel:'),       3, 0.97),
    (re.compile(r'^Hoàn thành:'),                    4, 1.0),
]
_EXCEL_STEP_RE = re.compile(r'\[EXCEL\] \((\d+)/(\d+)\)')


def _bump_stage(stage: int, progress: float, line: str) -> tuple[int, float]:
    m = _EXCEL_STEP_RE.search(line)
    if m:
        i, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            progress = max(progress, 0.65 + 0.30 * (i / total))
            stage    = max(stage, 3)
    for pattern, st, pct in _STAGE_MARKERS:
        if pattern.search(line):
            stage    = max(stage, st)
            progress = max(progress, pct)
    return stage, progress


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
        'stage':         0,      # index trong STAGE_LABELS
        'progress':      0.0,    # 0.0 - 1.0
        'summary':       None,   # dict số liệu nhóm nghiệp vụ — có từ cuối stage 2
        'cancel_event':  threading.Event(),
        '_ts':           time.time(),
        'output_dir':    str(TEMP_DIR / job_id / 'output'),
        'input_dir':     None,   # dùng lại cho lần chạy tiếp (Checkpoint Bước 3)
        'ngay':          None,
        'xac_nhan_file':  None,   # tên file <ngày>_ACH_ConfirmMISdi.xlsx khi đang chờ xác nhận
        'xac_nhan_count': None,   # số giao dịch MIS_đi cần chấm (đọc từ sheet MIS_DI_CONFIRM) — None nếu không đếm được
        'xac_nhan_tong_tien': None,  # tổng SO_TIEN các giao dịch cần chấm — None nếu không đếm được
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


# Job còn ở một trong các trạng thái này là còn CHIẾM máy chủ: hoặc thread pipeline
# đang chạy, hoặc file đầu vào vẫn nằm chờ để chạy tiếp sau xác nhận MIS_đi.
_DANG_CHIEM = ('pending', 'running', 'awaiting_confirmation')


def job_dang_chay() -> dict | None:
    """Job ACH đang chiếm máy chủ, None nếu rảnh.

    Chỉ chỗ này biết được câu trả lời: `_jobs` nằm trong RAM của backend, còn
    frontend chỉ nhớ job của RIÊNG tab trình duyệt đang mở — F5 một cái là quên
    sạch, người khác chạy thì lại càng không biết. Thiếu nó, hai pipeline pandas
    cùng ôm vài trăm MB chạy song song, backend hết RAM và chết giữa lúc đang
    nhận file của lượt thứ hai (26/08/2026).
    """
    with _lock:
        for job_id, job in _jobs.items():
            if job['status'] not in _DANG_CHIEM:
                continue
            # Job quá cũ coi như đã chết: `_cleanup_old_jobs()` cũng sẽ xoá file của
            # nó theo đúng mốc này. Không có ngoại lệ này thì một phiên bị bỏ dở ở
            # bước chờ xác nhận (người dùng đóng trình duyệt rồi đi) khoá chết tính
            # năng cho tới khi ai đó restart backend — không ai đoán ra vì sao.
            if time.time() - job['_ts'] > CLEANUP_TTL:
                continue
            return {
                'job_id':    job_id,
                'status':    job['status'],
                'tuoi_giay': max(0, int(time.time() - job['_ts'])),
            }
    return None


def tao_job() -> tuple[str, Path]:
    """Đăng ký một job mới ở trạng thái 'pending' và trả về (job_id, input_dir).

    Tách khỏi `chay_job()` để lớp API ghi THẲNG từng khối file tải lên vào
    `input_dir`, thay vì gom trọn vài trăm MB vào RAM rồi mới đưa xuống đây.

    Job có mặt trong `_jobs` NGAY từ lúc bắt đầu nhận file, nên `job_dang_chay()`
    chặn được người thứ hai bấm chạy trong lúc người thứ nhất còn đang upload —
    trước đây khoảng thời gian đó là một lỗ hổng: hai lượt upload lớn cùng lúc
    vẫn lọt qua cửa kiểm tra rồi mới tranh nhau RAM.

    Upload hỏng giữa chừng thì lớp API phải gọi `bo_job()` để trả lại chỗ.
    """
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


def chay_job(job_id: str, ngay: str | None, bo_qua_checkpoint: bool = False,
            tao_gw_cho_phub: bool = False) -> None:
    """Khởi chạy pipeline cho job đã nhận đủ file (xem `tao_job()`).

    Chạy giản lược theo file đang có LUÔN bật (2026-09-16, thay cờ
    `chi_tim_timeout` trước đây phải tự tay tick) — `main_from_dir()` tự động
    chạy phần còn tính được khi thiếu GL02/MIS_đến/MIS_đi, không cần báo trước.

    tao_gw_cho_phub — ô tick tuỳ chọn Tab 1 (A4, 23.09.2026), mặc định TẮT,
    xem docstring `main_from_dir()`."""
    job = get_job(job_id)
    if job is None:
        raise LookupError('Job không tồn tại.')
    job['ngay'] = ngay
    # Ghi lại lựa chọn ô tick vào job — Checkpoint (`continue_job()`) chạy lại
    # TOÀN BỘ pipeline từ đầu (không resume state), phải đọc lại đúng lựa chọn
    # ban đầu, không phải luôn mặc định False (thiếu bước này là ô tick vô tác
    # dụng lặng lẽ mỗi khi job đi qua Checkpoint — xem PLAN.md rủi ro 10).
    job['tao_gw_cho_phub'] = tao_gw_cho_phub
    thread = threading.Thread(
        target=_run,
        args=(job_id, job['input_dir'], job['output_dir'], ngay),
        kwargs={'dung_sau_mis_di': not bo_qua_checkpoint, 'tao_gw_cho_phub': tao_gw_cho_phub},
        daemon=True,
    )
    thread.start()


def start_job(saved_files: dict[str, bytes], ngay: str | None,
             bo_qua_checkpoint: bool = False) -> str:
    """
    Tạo job mới, lưu file vào disk, chạy pipeline trong background thread.
    saved_files: {filename: bytes}
    Trả về job_id. Mặc định chạy ở chế độ Checkpoint (dừng sau
    `_process_mis_di()` chờ xác nhận thủ công MIS_đi) — thay cho việc tự động
    phân loại toàn bộ.

    bo_qua_checkpoint=True (2026-07-31, xem
    project_ach_chay_thang_bo_qua_checkpoint) — chạy thẳng một mạch tới báo cáo
    cuối, coi toàn bộ MIS_đi mặc định đúng, KHÔNG dừng lại chờ xác nhận. Đây là
    nhánh code ĐÃ CHẠY THẬT hàng ngày (giống hệt `_run()` khi `continue_job()`
    gọi lại không truyền `dung_sau_mis_di`, mặc định `False`) — chỉ khác là được
    phép chọn ngay từ lần chạy đầu tiên, không phải chờ qua Checkpoint trước.
    """
    job_id, input_dir = tao_job()

    # safe_filename() lần hai: API đã lọc, nhưng hàm này là public và có thể
    # được gọi từ chỗ khác — đường ghi ra đĩa tự bảo vệ lấy mình.
    for filename, data in saved_files.items():
        (input_dir / safe_filename(filename)).write_bytes(data)

    chay_job(job_id, ngay, bo_qua_checkpoint=bo_qua_checkpoint)
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
    safe_name  = safe_filename(xac_nhan_filename, 'xac_nhan.xlsx')
    saved_path = xac_nhan_dir / safe_name
    saved_path.write_bytes(xac_nhan_bytes)

    job['status'] = 'running'
    job['error']  = None

    thread = threading.Thread(
        target=_run,
        args=(job_id, job['input_dir'], job['output_dir'], job['ngay']),
        kwargs={
            'xac_nhan_path': str(saved_path),
            'tao_gw_cho_phub': job.get('tao_gw_cho_phub', False),
        },
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


def _run(job_id: str, input_dir: str, output_dir: str, ngay: str | None,
        dung_sau_mis_di: bool = False, xac_nhan_path: str | None = None,
        tao_gw_cho_phub: bool = False):
    job = get_job(job_id)
    if job is None:
        return

    job['status'] = 'running'

    def log(msg: str):
        with _lock:
            job['logs'].append(msg)
            job['stage'], job['progress'] = _bump_stage(job['stage'], job['progress'], msg)

    def on_summary(summary: dict):
        job['summary'] = summary

    try:
        log(f'[JOB {job_id}] Bắt đầu xử lý...')
        output_path = main_from_dir(
            input_dir=input_dir,
            output_dir=output_dir,
            ngay=ngay,
            log_callback=log,
            summary_callback=on_summary,
            cancel_event=job['cancel_event'],
            dung_sau_mis_di=dung_sau_mis_di,
            xac_nhan_path=xac_nhan_path,
            tao_gw_cho_phub=tao_gw_cho_phub,
        )

        if output_path is None:
            # Pipeline trả None khi bị cancel
            job['status'] = 'cancelled'
            log('[JOB] Đã dừng theo yêu cầu.')
            return

        # Dừng ở Checkpoint hay không phải xét theo TÊN FILE main_from_dir() thật
        # sự trả về, KHÔNG phải tham số đầu vào dung_sau_mis_di — 2026-09-16, thiếu
        # MIS_đi khiến pipeline tự bỏ qua Checkpoint và chạy thẳng tới báo cáo cuối
        # (xem `if dung_sau_mis_di and df_mis_di_data is not None` trong
        # pipeline.py::main_from_dir()) dù dung_sau_mis_di vẫn là True ở đây — tin
        # vào tham số đầu vào sẽ gắn nhầm job ĐÃ XONG thành "đang chờ xác nhận" và
        # đưa file báo cáo cuối ra dưới vỏ bọc "file cần xác nhận".
        if dung_sau_mis_di and os.path.basename(output_path).endswith('_ACH_ConfirmMISdi.xlsx'):
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

        job['status'] = 'done'

    except Exception as e:
        import traceback
        if xac_nhan_path is not None and isinstance(e, ValueError) and not isinstance(e, LoiDinhDangSoTien):
            # Lỗi do file xác nhận điền sai/thiếu (ap_dung_confirm_mis_di) — quay lại
            # chờ xác nhận để người dùng sửa và upload lại, không coi là lỗi chung cuộc.
            # LoiDinhDangSoTien (GL02/GW đọc lại khi chạy tiếp) loại trừ riêng: đó là lỗi
            # file gốc, không phải file xác nhận — báo nhầm sẽ tạo vòng lặp không lối ra.
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
        # Trả RAM lại NGAY, không đợi CPython tự thấy. Các DataFrame lớn của pandas
        # thường nằm trong vòng tham chiếu nên đếm tham chiếu không thu hồi được —
        # phải gọi bộ thu gom. Cả tính năng này chặn "một phiên một lúc" cũng chỉ vì
        # RAM, nên người bấm Dừng xong phải nhận lại bộ nhớ thật, không phải trên
        # giấy tờ.
        gc.collect()
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


def _cleanup_old_jobs(cutoff: float | None = None):
    """Xóa job cũ hơn `cutoff` khỏi memory + disk, kèm thư mục mồ côi.

    `cutoff` mặc định là mốc 23h gần nhất đã trôi qua (backend/core/don_dep.py):
    kết quả sống hết ngày làm việc, 23h dọn sạch. Trước đây là TTL 4 giờ — người
    chạy ACH lúc 8h sáng quay lại tải báo cáo lúc 2h chiều thì file đã bị hệ
    thống xoá mất, không có thông báo nào.

    Vì `cutoff` không bao giờ rơi vào trong ngày đang chạy, hàm này gọi được ngay
    trong `finally` của một job mà không thể xoá nhầm kết quả của phiên khác vừa
    xong cùng ngày.

    `_jobs` nằm trong RAM nên khởi động lại là mất sạch — mà thư mục trên đĩa thì
    còn nguyên. Bản cũ chỉ xoá thư mục của job nó CÒN NHỚ, nên mọi job đang dở
    lúc tắt máy đều để lại thư mục không ai xoá được nữa (đo được: hai thư mục
    rỗng trong `data/temp_ach` từ lần chạy trước). Nay quét thêm theo thời gian
    sửa đổi, giống cách `cham459901_service` vẫn làm.
    """
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff
    with _lock:
        expired = [jid for jid, j in _jobs.items()
                   if j['status'] in ('done', 'error', 'cancelled', 'awaiting_confirmation')
                   and j['_ts'] < cutoff]
        for jid in expired:
            del _jobs[jid]
        con_song = set(_jobs)
    for jid in expired:
        job_dir = TEMP_DIR / jid
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)

    # Thư mục mồ côi: không thuộc job nào đang chạy và đã quá hạn giữ
    if not TEMP_DIR.exists():
        return
    for d in TEMP_DIR.iterdir():
        if not d.is_dir() or d.name in con_song:
            continue
        try:
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError as e:
            log_orphan = f'Không xoá được thư mục ACH mồ côi {d}: {e}'
            logging.getLogger(__name__).warning(log_orphan)


# Khai với chốt chặn dùng chung — xem backend/core/phien_doi_chieu.py.
# `job_dang_chay()` vốn đã có từ 26/08/2026; nay nó vừa phục vụ cửa 409 của
# chính ACH, vừa là nguồn đếm cho chốt chung của cả bốn module.
from backend.core.phien_doi_chieu import dang_ky_nguon  # noqa: E402

dang_ky_nguon('ach', 'Đối chiếu ACH', job_dang_chay)


# ─── Gộp kết quả pHub nhiều ngày — bản-3 (Luồng C, 23.09.2026) ────────────────
# Bản-2 "kho 30 ngày" (`danh_sach_ngay_phub()`, `gop_phub()` đọc kho,
# `tai_ket_qua_gop()`) đã bị gỡ (Luồng A). Bản-3: nhận N file TRONG 1 request,
# KHÔNG lưu gì trên server ngoài đúng kết quả cuối — chạy ĐỒNG BỘ (C-K đã
# chốt, KHÔNG chiếm khoá `gianh_cho('ach')`, xem docstring endpoint ở
# backend/api/ach.py + docs/Implementation-notes.html card 147).

def gop_phub(files: list[tuple[str, bytes]]) -> dict:
    """Gộp N file TIMEOUT + N file GW-cho-pHub + 1 file pHub (đã đọc sẵn vào
    RAM ở lớp API — không ghi input xuống đĩa, đúng nguyên tắc "không lưu gì
    trên server" của bản-3). Ghi DUY NHẤT file kết quả ra
    `TEMP_DIR/phubgop_<mã>/` (tái dùng `TEMP_DIR`, KHÔNG tạo thư mục mới nào
    khác dưới `data/`) — thư mục này không nằm trong `_jobs` nên tự rơi vào
    nhánh "thư mục mồ côi" của `_cleanup_old_jobs()`, dọn 23h như mọi output
    ACH khác (C-R đã chốt, không cần hạn riêng).

    Trả `{'ma', 'tong_ket', 'canh_bao', 'ten_file'}`. Raise `ValueError` khi
    input không hợp lệ (0/≥2 file pHub, file lạ, không xác định được ngày nào
    để gộp) — lớp API map sang 400."""
    _cleanup_old_jobs()   # dọn kết quả gộp cũ (mồ côi) trước khi ghi thêm

    df_phub, df_gw, df_timeout, canh_bao = phub_gop.phan_loai_file_gop(files)

    # ngay_list — QUYẾT ĐỊNH TỰ CHỌN (PLAN.md không nêu, C-a chỉ trả 4 giá trị,
    # không có ngay_list): suy ra từ NGAY_TIMEOUT thực tế có trong df_timeout
    # (sau khi đã loại các file thiếu cột NGAY_DOI_CHIEU). Hạn chế đã biết: nếu
    # TOÀN BỘ file Timeout của lượt gộp đều có 0 dòng (R6 — mọi giao dịch trong
    # ngày đã khớp GW, không gì rơi vào Timeout) VÀ đó là ngày DUY NHẤT trong
    # lượt, ngay_list sẽ rỗng vì không còn cách nào khác lấy được ngày từ nội
    # dung file (C-N cấm đọc tên file/gõ tay) — raise lỗi rõ ràng thay vì để
    # `xuat_excel_phub_gop()` crash IndexError khi ngay_sorted[0]. Xem
    # pipeline/CODE_REPORT.md phần Luồng C để biết lý do đầy đủ.
    ngay_list = sorted({n for n in df_timeout['NGAY_TIMEOUT'] if n}) if len(df_timeout) else []
    if not ngay_list:
        raise ValueError(
            'Không xác định được ngày nào từ các file TIMEOUT đã nạp (thiếu cột NGAY_DOI_CHIEU '
            'hoặc không có dòng dữ liệu nào) — không có gì để gộp.'
        )

    df_ketqua, thong_ke = phub_gop.gop_phub(df_phub, df_gw, df_timeout, ngay_list)

    ma = 'phubgop_' + uuid.uuid4().hex[:12]
    out_dir = TEMP_DIR / ma
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = phub_gop.xuat_excel_phub_gop(str(out_dir), ngay_list, df_ketqua, canh_bao)

    return {
        'ma':       ma,
        'tong_ket': thong_ke,
        'canh_bao': canh_bao,
        'ten_file': os.path.basename(out_path),
    }


def tai_ket_qua_gop(ma: str, filename: str) -> Path | None:
    """Tải 1 file kết quả của lượt Gộp `ma` — chặn path traversal bằng
    `os.path.basename()` cho CẢ `ma` lẫn `filename` (mẫu `get_output_file()`)."""
    safe_ma   = os.path.basename(ma)
    safe_name = os.path.basename(filename)
    path = TEMP_DIR / safe_ma / safe_name
    return path if path.exists() else None
