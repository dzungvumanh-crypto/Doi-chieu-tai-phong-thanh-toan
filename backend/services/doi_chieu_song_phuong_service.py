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
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from backend.core.config import BASE_DIR, zip_password   # mật khẩu ZIP đọc từ .env

try:
    import pyzipper
    _open_zip = lambda buf: pyzipper.AESZipFile(buf)   # noqa: E731
except ImportError:
    _open_zip = lambda buf: zipfile.ZipFile(buf)       # noqa: E731

# ─── Config ───────────────────────────────────────────────────────────────────
TEMP_DIR      = BASE_DIR / "data" / "temp_doi_chieu_song_phuong"
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

# ─── In-memory progress store ─────────────────────────────────────────────────
# key = task_token; value = {pct, msg, done, error, result, _ts}
_progress: dict[str, dict] = {}


def init_progress() -> str:
    task_token = str(uuid.uuid4())
    _progress[task_token] = {
        "pct": 0, "msg": "Đang khởi tạo...",
        "done": False, "error": None, "result": None,
        "_ts": time.time(),
    }
    return task_token


def get_progress(task_token: str) -> dict | None:
    p = _progress.get(task_token)
    if p is None:
        return None
    return {k: v for k, v in p.items() if not k.startswith("_")}


def _set_prog(task_token: str | None, pct: int, msg: str) -> None:
    if task_token and task_token in _progress:
        _progress[task_token]["pct"] = pct
        _progress[task_token]["msg"] = msg


# ─── Public API ───────────────────────────────────────────────────────────────

def run_process(zip_bytes: bytes, task_token: str) -> None:
    """Chạy process_zip trong background thread; cập nhật progress và bắt lỗi."""
    try:
        process_zip(zip_bytes, task_token)
    except Exception as e:
        log.error("process_zip lỗi [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e),
                "msg": "Lỗi xử lý — xem log server",
            })


def process_zip(zip_bytes: bytes, task_token: str | None = None) -> dict:
    """Nhận bytes ZIP → định tuyến → ghi 8 CSV → trả metadata."""
    _cleanup_old_results()
    t0 = time.time()

    # ── Kiểm tra magic bytes ──────────────────────────────────────────────────
    if zip_bytes[:4] != b"PK\x03\x04":
        raise ValueError("File tải lên không phải định dạng ZIP hợp lệ.")

    _set_prog(task_token, 5, "Đang giải mã và đọc dữ liệu...")

    buffers = {(c, d): [] for c in BANK_MAP for d in DIRECTIONS}
    counts  = {(c, d): 0  for c in BANK_MAP for d in DIRECTIONS}
    hdr_line   = None
    total_rows = 0

    buf = io.BytesIO(zip_bytes)
    try:
        zf = _open_zip(buf)
    except Exception as e:
        raise ValueError(f"Không mở được file ZIP: {e}")

    with zf:
        try:
            zf.setpassword(zip_password())
        except AttributeError:
            pass  # zipfile thường không cần setpassword riêng
        csv_names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        if not csv_names:
            raise ValueError("Không tìm thấy file CSV nào trong ZIP.")

        n = len(csv_names)
        for i, name in enumerate(csv_names):
            try:
                raw = zf.read(name, pwd=zip_password())
            except Exception as e:
                raise ValueError(
                    f"Không giải mã được '{name}' — sai mật khẩu hoặc file hỏng ({e})."
                )
            reader = csv.reader(io.TextIOWrapper(
                io.BytesIO(raw), encoding="utf-8-sig", newline=""))
            file_hdr, routed = _route_file(reader, buffers, counts, name)
            if hdr_line is None and file_hdr:
                hdr_line = file_hdr
            total_rows += routed
            _set_prog(task_token, int(5 + (i + 1) * 75 / n),
                      f"Đã xử lý {i + 1}/{n}: {name} ({routed:,} dòng)")

    # ── Ghi 8 file CSV (kể cả file rỗng → chỉ header) ─────────────────────────
    _set_prog(task_token, 85, f"Đang ghi 8 file CSV ({total_rows:,} dòng)...")
    if hdr_line is None:
        hdr_line = ",".join(COLS) + "\r\n"

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

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

    if task_token and task_token in _progress:
        _progress[task_token].update({
            "pct": 100, "msg": "Hoàn thành!",
            "done": True, "result": result,
        })
    return result


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
    """Xóa thư mục kết quả và progress entry cũ hơn CLEANUP_HOURS giờ."""
    cutoff = time.time() - CLEANUP_HOURS * 3600

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            if sub.is_dir() and sub.stat().st_mtime < cutoff:
                try:
                    shutil.rmtree(sub)
                except Exception as e:
                    log.warning("Không xóa được %s: %s", sub, e)

    stale = [k for k, v in _progress.items() if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)
