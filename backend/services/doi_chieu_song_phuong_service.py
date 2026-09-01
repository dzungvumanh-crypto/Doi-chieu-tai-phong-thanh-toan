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
import struct
import threading
import time
import uuid
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

from backend.services.doi_chieu_song_phuong_common import do_thoi_gian

try:
    import pyzipper
    _open_zip = lambda buf: pyzipper.AESZipFile(buf)   # noqa: E731
except ImportError:
    _open_zip = lambda buf: zipfile.ZipFile(buf)       # noqa: E731

# numba là dependency TÙY CHỌN (2026-09-01, theo review khanhbq693 PR#68 vòng 3) — chỉ dùng để
# tăng tốc giải mã ZipCrypto cổ điển (card 100). Module này được nạp lúc khởi động qua
# `backend/api/doi_chieu_song_phuong.py` — thiếu numba/numpy (VD môi trường mới chưa `pip
# install` kịp) KHÔNG được làm sập cả backend, chỉ được rơi về `zf.read()` gốc của pyzipper
# (chậm hơn nhưng vẫn đúng) cho riêng module này.
try:
    import numpy as np
    from numba import njit
    _CO_NUMBA = True
except ImportError:
    _CO_NUMBA = False

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
    t_start = time.time()

    # ── Kiểm tra magic bytes ──────────────────────────────────────────────────
    if zip_bytes[:4] != b"PK\x03\x04":
        raise ValueError("File tải lên không phải định dạng ZIP hợp lệ.")

    log_callback("Đang giải mã và đọc dữ liệu...")

    try:
        with io.BytesIO(zip_bytes) as buf, _open_zip(buf) as zf:
            try:
                zf.setpassword(ZIP_PASSWORD)
            except AttributeError:
                pass  # zipfile thường không cần setpassword riêng
            csv_names = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
    except Exception as e:
        raise ValueError(f"Không mở được file ZIP: {e}")
    if not csv_names:
        raise ValueError("Không tìm thấy file CSV nào trong ZIP.")

    result_token = str(uuid.uuid4())
    out_dir = TEMP_DIR / result_token
    out_dir.mkdir(parents=True, exist_ok=True)

    hdr_line, total_rows, counts = _giai_ma_tuan_tu(zip_bytes, csv_names, out_dir, log_callback)

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
        "elapsed_s":    round(time.time() - t_start, 1),
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

def _giai_ma_tuan_tu(
    zip_bytes: bytes, csv_names: list[str], out_dir: Path, log_callback,
) -> tuple[str, int, dict]:
    """Đọc lần lượt từng file thành viên. Giải mã qua `_doc_1_file_thanh_vien()` — dùng đường
    tắt numba cho ZipCrypto cổ điển (2026-09-01, xem Implementation-notes.html card 100, nhanh
    ~39 lần so với vòng lặp Python thuần của pyzipper), tự rơi về `zf.read()` gốc cho mọi trường
    hợp khác (AES thật, STORED...) — không đoán, chỉ dùng đường tắt khi chắc chắn đúng thuật
    toán."""
    buffers = {(c, d): [] for c in BANK_MAP for d in DIRECTIONS}
    counts = {(c, d): 0 for c in BANK_MAP for d in DIRECTIONS}
    hdr_line = None
    total_rows = 0

    # Tách riêng 2 nhãn đo thời gian (2026-08-31, yêu cầu khảo sát hiệu năng) — trước gộp chung
    # "giải mã + định tuyến" vào 1 khối, không biết chi phí chính nằm ở giải nén hay ở vòng lặp
    # Python thuần `_route_file()`. Cộng dồn thủ công qua nhiều file thay vì bọc `do_thoi_gian`
    # mỗi file (tránh log rác n dòng), chỉ log tổng 1 lần sau vòng lặp.
    t_giai_nen = 0.0
    t_dinh_tuyen = 0.0
    with io.BytesIO(zip_bytes) as buf, _open_zip(buf) as zf:
        try:
            zf.setpassword(ZIP_PASSWORD)
        except AttributeError:
            pass
        n = len(csv_names)
        for i, name in enumerate(csv_names):
            t0 = time.perf_counter()
            try:
                raw = _doc_1_file_thanh_vien(zf, name, ZIP_PASSWORD)
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
    log_callback(f"[TIMING] giải mã ZIP (đọc+giải nén): {t_giai_nen:.1f}s")
    log_callback(f"[TIMING] định tuyến từng dòng (vòng lặp Python): {t_dinh_tuyen:.1f}s")

    log_callback(f"Đang ghi 8 file CSV ({total_rows:,} dòng)...")
    if hdr_line is None:
        hdr_line = ",".join(COLS) + "\r\n"

    with do_thoi_gian(log_callback, "ghi 8 file CSV"):
        for (cust, chieu), lines in buffers.items():
            ma = BANK_MAP[cust]
            path = out_dir / f"{ma}_{chieu}.csv"
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(hdr_line)
                fh.writelines(lines)

    return hdr_line, total_rows, counts


# ─── Giải mã nhanh (numba) cho ZipCrypto cổ điển ────────────────────────────────
# Phát hiện 2026-09-01 (Implementation-notes.html card 100): dù dùng `pyzipper.AESZipFile` và
# đặt tên "AES" khắp nơi trong code/tài liệu, file GL02 THẬT lại dùng mã hoá PKWARE ZipCrypto cổ
# điển (compress_type=8, KHÔNG phải 99 = mã AES thật của pyzipper) — không phải AES-256 như tài
# liệu cũ ghi. `pyzipper` giải mã kiểu này bằng vòng lặp Python xử lý TỪNG BYTE MỘT
# (profiling: 184 triệu lượt gọi `update_keys()`/`crc32()` cho 1 file GL02) — đây mới là nguyên
# nhân thật của 190s+ đo được, không phải vì bản chất phép toán mã hoá chậm (AES-NI phần cứng đo
# riêng đạt ~974 MB/s). Viết lại đúng thuật toán ZipCrypto (RFC lược sử PKZIP, giống hệt
# `pyzipper.zipfile.CRCZipDecrypter`) bằng `numba.njit` — biên dịch máy JIT, không cần compiler
# hệ thống, không cần binary ngoài (khác rủi ro WinRAR/7-Zip "chưa chắc có trên server" đã ghi ở
# card 30) — nhanh hơn ~39 lần khi verify trên dữ liệu GL02 thật, output byte-for-byte giống hệt.
#
# CHỈ áp dụng khi CHẮC CHẮN đúng thuật toán: `compress_type == ZIP_DEFLATED` (8) — loại trừ AES
# thật (compress_type == 99, tài liệu pyzipper) và STORED — mọi trường hợp khác rơi về
# `zf.read()` gốc của pyzipper (không đoán, không tự ý mở rộng đường tắt cho case chưa xác nhận).

def _crc32_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
        table.append(c)
    return np.array(table, dtype=np.uint64) if _CO_NUMBA else table


_CRC_TABLE = _crc32_table()


if _CO_NUMBA:
    @njit(cache=True)
    def _zipcrypto_decrypt_numba(data: np.ndarray, key0: int, key1: int, key2: int,
                                  crc_table: np.ndarray) -> np.ndarray:
        """Đúng thuật toán PKWARE ZipCrypto (xem `pyzipper.zipfile.CRCZipDecrypter.decrypt`/
        `update_keys`) — biên dịch JIT bằng numba để chạy tốc độ gần mã máy thay vì vòng lặp
        bytecode Python."""
        n = data.shape[0]
        out = np.empty(n, dtype=np.uint8)
        for i in range(n):
            k = key2 | 2
            c = data[i] ^ (((k * (k ^ 1)) >> 8) & 0xFF)
            key0 = (crc_table[(key0 ^ c) & 0xFF] ^ (key0 >> 8)) & 0xFFFFFFFF
            key1 = (key1 + (key0 & 0xFF)) & 0xFFFFFFFF
            key1 = (key1 * 134775813 + 1) & 0xFFFFFFFF
            key2 = (crc_table[(key2 ^ (key1 >> 24)) & 0xFF] ^ (key2 >> 8)) & 0xFFFFFFFF
            out[i] = c
        return out


def _zipcrypto_derive_keys(pwd: bytes) -> tuple[int, int, int]:
    key0, key1, key2 = 305419896, 591751049, 878082192
    for p in pwd:
        key0 = (int(_CRC_TABLE[(key0 ^ p) & 0xFF]) ^ (key0 >> 8)) & 0xFFFFFFFF
        key1 = (key1 + (key0 & 0xFF)) & 0xFFFFFFFF
        key1 = (key1 * 134775813 + 1) & 0xFFFFFFFF
        key2 = (int(_CRC_TABLE[(key2 ^ (key1 >> 24)) & 0xFF]) ^ (key2 >> 8)) & 0xFFFFFFFF
    return key0, key1, key2


def _doc_raw_ciphertext(zf, info) -> bytes:
    """Đọc thẳng byte mã hoá (compressed, kèm 12 byte header mã hoá ZipCrypto) từ `zf.fp` bằng vị
    trí `header_offset` — hoạt động với cả file thật lẫn `io.BytesIO` trong bộ nhớ (không cần
    đường dẫn trên đĩa)."""
    zf.fp.seek(info.header_offset)
    local_header = zf.fp.read(30)
    (_sig, _ver, _flag, _comp, _mtime, _mdate, _crc, _csize, _usize, nlen, elen) = \
        struct.unpack("<IHHHHHIIIHH", local_header)
    zf.fp.seek(info.header_offset + 30 + nlen + elen)
    return zf.fp.read(info.compress_size)


def _doc_1_file_thanh_vien(zf, name: str, pwd: bytes) -> bytes:
    """Đọc + giải mã + giải nén 1 file thành viên trong ZIP đang mở `zf`. Dùng đường tắt numba
    (ZipCrypto cổ điển, xem block comment phía trên) khi entry chắc chắn khớp thuật toán, ngược
    lại rơi về `zf.read()` gốc của pyzipper (bao gồm cả AES thật, thiếu numba, lẫn mọi trường hợp
    không chắc chắn)."""
    if not _CO_NUMBA:
        return zf.read(name, pwd=pwd)

    info = zf.getinfo(name)
    # ⚠️ `info.compress_type` KHÔNG đủ để phân biệt AES thật với ZipCrypto — pyzipper tự giải mã
    # extra field AES (0x9901) và GHI ĐÈ `compress_type` bằng phương pháp nén THẬT bên trong (vd
    # 8 = DEFLATE), giống hệt giá trị của entry ZipCrypto thường. Verify trực tiếp: file GL02 thật
    # (ZipCrypto) và 1 fixture test tạo bằng `pyzipper.AESZipFile(..., encryption=WZ_AES)` đều trả
    # `compress_type=8` — chỉ có `wz_aes_version` (pyzipper set khi decode được extra field AES,
    # mặc định `None`) mới phân biệt đúng được 2 trường hợp.
    is_zip_crypto = (
        bool(info.flag_bits & 0x1)               # bit 0 = có mã hoá
        and not bool(info.flag_bits & 0x40)      # bit 6 = strong encryption (không dùng ở đây)
        and getattr(info, "wz_aes_version", None) is None   # KHÔNG phải AES thật
        and info.compress_type == zipfile.ZIP_DEFLATED
    )
    if not is_zip_crypto:
        return zf.read(name, pwd=pwd)

    ciphertext = _doc_raw_ciphertext(zf, info)
    key0, key1, key2 = _zipcrypto_derive_keys(pwd)
    cipher_arr = np.frombuffer(ciphertext, dtype=np.uint8)
    plain = _zipcrypto_decrypt_numba(cipher_arr, key0, key1, key2, _CRC_TABLE)

    # 12 byte đầu là header mã hoá (không phải dữ liệu thật) — byte cuối dùng để kiểm tra mật
    # khẩu đúng/sai, giống hệt `CRCZipDecrypter.__init__` của pyzipper.
    use_datadescriptor = bool(info.flag_bits & 0x8)
    check_byte = ((info._raw_time >> 8) & 0xFF) if use_datadescriptor else ((info.CRC >> 24) & 0xFF)
    if int(plain[11]) != check_byte:
        raise ValueError(f"Sai mật khẩu cho file '{name}' trong ZIP")

    decompressed = zlib.decompressobj(-15).decompress(plain[12:].tobytes())
    actual_crc = zlib.crc32(decompressed) & 0xFFFFFFFF
    if actual_crc != info.CRC:
        raise ValueError(
            f"CRC không khớp sau khi giải mã '{name}' — dữ liệu có thể hỏng "
            f"(expected={info.CRC:x}, actual={actual_crc:x})"
        )
    return decompressed


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
    """Xóa thư mục kết quả cũ hơn CLEANUP_HOURS giờ — kể cả file `_tmp_gl02_*.zip` bị bỏ sót nếu
    tiến trình chết giữa chừng lúc giải mã song song (`_giai_ma_song_song` tự dọn ở nhánh chạy
    bình thường qua `finally`, đây chỉ là lưới an toàn cho trường hợp crash)."""
    cutoff = time.time() - CLEANUP_HOURS * 3600

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            if sub.stat().st_mtime >= cutoff:
                continue
            if sub.is_dir():
                try:
                    shutil.rmtree(sub)
                except Exception as e:
                    log.warning("Không xóa được %s: %s", sub, e)
            elif sub.name.startswith("_tmp_gl02_") and sub.suffix == ".zip":
                try:
                    sub.unlink()
                except Exception as e:
                    log.warning("Không xóa được %s: %s", sub, e)
