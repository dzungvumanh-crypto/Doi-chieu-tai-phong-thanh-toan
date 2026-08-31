"""Service Đối chiếu Song phương — định tuyến lệnh IPCAS theo ngân hàng + chiều.

Logic port từ processor.py của app gốc (Doi_Chieu_Song_Phuong), GIỮ NGUYÊN
ngữ nghĩa định tuyến. Khác biệt: chạy 1 luồng nền in-process (bỏ WinRAR +
multiprocessing của bản desktop), I/O làm việc với bytes từ HTTP upload.

Mỗi dòng IPCAS thuộc 1 trong 4 ngân hàng (theo CUSTOMER) được đưa vào:
  - file ĐẾN nếu CRAMOUNT = 0   (tiền ghi Có = 0 → lệnh nhận về)
  - file ĐI  nếu DRAMOUNT = 0   (tiền ghi Nợ = 0 → lệnh chuyển đi)
Một dòng có cả 2 số = 0 sẽ xuất hiện ở cả 2 file (giữ nguyên bản gốc).
"""

import csv
import io
import logging
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from backend.services.doi_chieu_song_phuong_common import do_thoi_gian

try:
    import pyzipper
    _open_zip = lambda buf: pyzipper.AESZipFile(buf)   # noqa: E731
except ImportError:
    _open_zip = lambda buf: zipfile.ZipFile(buf)       # noqa: E731

# ─── Config ───────────────────────────────────────────────────────────────────
TEMP_DIR      = Path("data/temp_doi_chieu_song_phuong")
ZIP_PASSWORD  = b"DACwLdHi"
CLEANUP_HOURS = 2

# Cột chuẩn IPCAS — đảm bảo mọi file xuất ra luôn có đủ 10 cột này
COLS = ["BUSCD", "UNIT", "TRCD", "CUSTOMER", "TRTP",
        "REFERENCE", "REMARK", "DRAMOUNT", "CRAMOUNT", "CRTDTM"]

# CUSTOMER (mã TK nội bộ) → mã ngân hàng đối chiếu
BANK_MAP = {
    "1000-003046287": "201",
    "1000-003046328": "202",
    "1000-000035720": "203",
    "1000-003398630": "311",
}
BANK_NAME = {
    "201": "Vietinbank",
    "202": "BIDV",
    "203": "Vietcombank",
    "311": "MBBank",
}
DIRECTIONS    = ("DEN", "DI")
ZERO_AMOUNTS  = {"0", "0.0", "0.00", ""}
REQUIRED_COLS = {"CUSTOMER", "CRAMOUNT", "DRAMOUNT"}
# ─────────────────────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)


# ─── Public API ───────────────────────────────────────────────────────────────

def process_zip(zip_bytes: bytes, log_callback=lambda msg: None) -> dict:
    """Nhận bytes ZIP → định tuyến → ghi 8 CSV → trả metadata."""
    _cleanup_old_results()
    t0 = time.time()

    # ── Kiểm tra magic bytes ──────────────────────────────────────────────────
    if zip_bytes[:4] != b"PK\x03\x04":
        raise ValueError("File tải lên không phải định dạng ZIP hợp lệ.")

    log_callback("Đang giải mã và đọc dữ liệu...")

    buffers = {(c, d): [] for c in BANK_MAP for d in DIRECTIONS}
    counts  = {(c, d): 0  for c in BANK_MAP for d in DIRECTIONS}
    hdr_line   = None
    total_rows = 0

    buf = io.BytesIO(zip_bytes)
    try:
        zf = _open_zip(buf)
    except Exception as e:
        raise ValueError(f"Không mở được file ZIP: {e}")

    # Tách riêng 2 nhãn đo thời gian (2026-08-31, yêu cầu khảo sát hiệu năng) — trước gộp chung
    # "giải mã + định tuyến" vào 1 khối, không biết chi phí chính nằm ở giải nén AES/zlib hay ở
    # vòng lặp Python thuần `_route_file()`. Cộng dồn thủ công qua nhiều file thay vì bọc
    # `do_thoi_gian` mỗi file (tránh log rác n dòng), chỉ log tổng 1 lần sau vòng lặp.
    t_giai_nen = 0.0
    t_dinh_tuyen = 0.0
    with zf:
        try:
            zf.setpassword(ZIP_PASSWORD)
        except AttributeError:
            pass  # zipfile thường không cần setpassword riêng
        csv_names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        if not csv_names:
            raise ValueError("Không tìm thấy file CSV nào trong ZIP.")

        n = len(csv_names)
        for i, name in enumerate(csv_names):
            t0 = time.perf_counter()
            try:
                raw = zf.read(name, pwd=ZIP_PASSWORD)
            except Exception as e:
                raise ValueError(
                    f"Không giải mã được '{name}' — sai mật khẩu hoặc file hỏng ({e})."
                )
            t_giai_nen += time.perf_counter() - t0

            t0 = time.perf_counter()
            reader = csv.reader(io.TextIOWrapper(
                io.BytesIO(raw), encoding="utf-8-sig", newline=""))
            file_hdr, routed = _route_file(reader, buffers, counts, name)
            t_dinh_tuyen += time.perf_counter() - t0

            if hdr_line is None and file_hdr:
                hdr_line = file_hdr
            total_rows += routed
            log_callback(f"Đã xử lý {i + 1}/{n}: {name} ({routed:,} dòng)")
    log_callback(f"[TIMING] giải mã ZIP (đọc+giải nén AES): {t_giai_nen:.1f}s")
    log_callback(f"[TIMING] định tuyến từng dòng (vòng lặp Python): {t_dinh_tuyen:.1f}s")

    # ── Ghi 8 file CSV (kể cả file rỗng → chỉ header) ─────────────────────────
    log_callback(f"Đang ghi 8 file CSV ({total_rows:,} dòng)...")
    if hdr_line is None:
        hdr_line = ",".join(COLS) + "\r\n"

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

    with do_thoi_gian(log_callback, "ghi 8 file CSV"):
        for (cust, chieu), lines in buffers.items():
            ma   = BANK_MAP[cust]
            path = out_dir / f"{ma}_{chieu}.csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(hdr_line)
                fh.writelines(lines)

    # ── Thống kê + danh sách file ─────────────────────────────────────────────
    stats = [
        {
            "ma_nh":       ma,
            "ten_nh":      BANK_NAME[ma],
            "so_lenh_den": counts[(cust, "DEN")],
            "so_lenh_di":  counts[(cust, "DI")],
            "tong":        counts[(cust, "DEN")] + counts[(cust, "DI")],
        }
        for cust, ma in BANK_MAP.items()
    ]
    files = [
        {
            "file_key": f"{BANK_MAP[cust]}_{chieu}",
            "ma_nh":    BANK_MAP[cust],
            "ten_nh":   BANK_NAME[BANK_MAP[cust]],
            "chieu":    chieu,
            "rows":     counts[(cust, chieu)],
        }
        for cust in BANK_MAP for chieu in DIRECTIONS
    ]

    result = {
        "token":        result_token,
        "stats":        stats,
        "files":        files,
        "total_rows":   total_rows,
        "elapsed_s":    round(time.time() - t0, 1),
        "process_date": datetime.now().strftime("%Y%m%d"),
    }

    log_callback("Hoàn thành!")
    return result


# ─── Job hàng loạt (nhiều file / thư mục server) ───────────────────────────────
# Mỗi ZIP là 1 ngày độc lập — chạy tuần tự qua process_zip(), lỗi 1 file không chặn
# các file còn lại (giống triết lý "bỏ qua thiếu, không crash cả job" của
# ach_service/doi_chieu_song_phuong_kenh_service). Pattern job in-memory + thread
# nền + TTL cleanup giống hệt 2 service đó — giữ nhất quán codebase.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_JOB_CLEANUP_TTL = 4 * 3600


def _new_job() -> tuple[str, dict]:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "status": "pending",   # pending | running | done | error | cancelled
        "logs": [],
        "results": [],         # list kết quả process_zip() (kèm "source_name"), theo thứ tự
        "error": None,
        "cancel_event": threading.Event(),
        "_ts": time.time(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    return job_id, job


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job and job["status"] in ("pending", "running"):
        job["cancel_event"].set()
        return True
    return False


def start_batch(files: list[tuple[str, bytes]]) -> str:
    """Chạy process_zip() tuần tự cho từng file đã tải lên `(filename, bytes)`. Trả job_id."""
    job_id, job = _new_job()
    sources = [("upload", name, data) for name, data in files]
    threading.Thread(target=_run_batch, args=(job_id, sources), daemon=True).start()
    return job_id


def start_batch_folder(folder_path: str) -> str:
    """Tìm mọi file `*.zip` trong thư mục server, chạy tuần tự process_zip(). Trả job_id.

    Đọc bytes từ đĩa BÊN TRONG luồng nền (không load hết vào RAM ngay lúc này) — mỗi
    GL02 zip thật ~150-160MB, thư mục nhiều ngày cùng lúc dễ tốn hàng trăm MB nếu đọc
    trước hết."""
    zip_paths = sorted(Path(folder_path).glob("*.zip"))
    if not zip_paths:
        raise ValueError(f"Không tìm thấy file .zip nào trong thư mục: {folder_path}")
    job_id, job = _new_job()
    sources = [("path", p, None) for p in zip_paths]
    threading.Thread(target=_run_batch, args=(job_id, sources), daemon=True).start()
    return job_id


def _run_batch(job_id: str, sources: list[tuple]) -> None:
    job = get_job(job_id)
    if job is None:
        return
    job["status"] = "running"

    def log(msg: str) -> None:
        with _jobs_lock:
            job["logs"].append(msg)

    n = len(sources)
    for i, (kind, ref, data) in enumerate(sources, 1):
        if job["cancel_event"].is_set():
            job["status"] = "cancelled"
            log("Đã dừng theo yêu cầu.")
            job["_ts"] = time.time()
            _cleanup_old_jobs()
            return

        name = ref.name if kind == "path" else ref
        log(f"[{i}/{n}] Đang xử lý {name}...")
        try:
            zip_bytes = ref.read_bytes() if kind == "path" else data
            result = process_zip(zip_bytes, log_callback=lambda m, nhan=f"[{i}/{n}]": log(f"{nhan} {m}"))
            result["source_name"] = name
            job["results"].append(result)
            log(f"[{i}/{n}] Xong {name} — {result['total_rows']:,} dòng, {result['elapsed_s']}s")
        except Exception as e:
            job["results"].append({"source_name": name, "error": str(e)})
            log(f"[{i}/{n}] LỖI {name}: {e}")

    job["status"] = "done"
    log(f"Hoàn thành {n} file.")
    job["_ts"] = time.time()
    _cleanup_old_jobs()


def _cleanup_old_jobs() -> None:
    cutoff = time.time() - _JOB_CLEANUP_TTL
    with _jobs_lock:
        expired = [jid for jid, j in _jobs.items()
                   if j["status"] in ("done", "error", "cancelled") and j["_ts"] < cutoff]
        for jid in expired:
            del _jobs[jid]


# ─── Internal ─────────────────────────────────────────────────────────────────

def _route_file(reader, buffers: dict, counts: dict, name: str):
    """Đọc 1 CSV đã parse, đưa dòng vào buffers/counts theo NH + chiều.

    Trả (hdr_line, số dòng đã định tuyến). Ngữ nghĩa giữ nguyên bản gốc:
    - Bổ sung cột thiếu trong COLS vào cuối header (không xoá cột thừa).
    - Dòng có CRAMOUNT=0 → ĐẾN; DRAMOUNT=0 → ĐI (có thể vào cả hai).
    """
    raw_header = next(reader, None)
    if raw_header is None:
        return None, 0

    header = [c.strip().upper() for c in raw_header]
    for col in COLS:
        if col not in header:
            raw_header.append(col)
            header.append(col)
    n_cols = len(raw_header)

    try:
        ci  = header.index("CUSTOMER")
        cri = header.index("CRAMOUNT")
        dri = header.index("DRAMOUNT")
    except ValueError:
        missing = REQUIRED_COLS - set(header)
        raise ValueError(
            f"File '{name}' thiếu cột bắt buộc: {', '.join(sorted(missing))}."
        )

    hdr_line = ",".join(raw_header) + "\r\n"
    routed   = 0

    for row in reader:
        while len(row) < n_cols:
            row.append("")
        cust = row[ci]
        if cust not in BANK_MAP:
            continue
        routed += 1
        line = ",".join(row) + "\r\n"
        if row[cri] in ZERO_AMOUNTS:
            buffers[(cust, "DEN")].append(line)
            counts[(cust, "DEN")] += 1
        if row[dri] in ZERO_AMOUNTS:
            buffers[(cust, "DI")].append(line)
            counts[(cust, "DI")] += 1

    return hdr_line, routed


def _cleanup_old_results() -> None:
    """Xóa thư mục kết quả cũ hơn CLEANUP_HOURS giờ."""
    cutoff = time.time() - CLEANUP_HOURS * 3600

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            if sub.is_dir() and sub.stat().st_mtime < cutoff:
                try:
                    shutil.rmtree(sub)
                except Exception as e:
                    log.warning("Không xóa được %s: %s", sub, e)
