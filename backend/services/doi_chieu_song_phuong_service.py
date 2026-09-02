"""Service Đối chiếu Song phương — định tuyến lệnh IPCAS theo ngân hàng + chiều.

Logic port từ processor.py của app gốc (Doi_Chieu_Song_Phuong), GIỮ NGUYÊN
ngữ nghĩa định tuyến. Khác biệt: chạy 1 luồng nền in-process (bỏ WinRAR +
multiprocessing của bản desktop), I/O làm việc với ĐƯỜNG DẪN file đã nằm trên
máy chủ (`backend/api/doi_chieu_song_phuong.py` ghi thẳng từng khối xuống
`data/temp_doi_chieu_song_phuong/upload_<token>/`). Nhận bytes như trước là ôm
trọn file ZIP trong RAM suốt thời gian xử lý, trong khi zipfile đọc từ đĩa được.

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
import time
import uuid
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

from backend.core.config import BASE_DIR, zip_password   # mật khẩu ZIP đọc từ .env
from backend.core.don_dep import moc_don_gan_nhat

try:
    import pyzipper
    _open_zip = lambda buf: pyzipper.AESZipFile(buf)   # noqa: E731
except ImportError:
    _open_zip = lambda buf: zipfile.ZipFile(buf)       # noqa: E731

# numba là dependency TÙY CHỌN (2026-09-01) — chỉ dùng để tăng tốc giải mã ZipCrypto cổ điển
# (phát hiện: file GL02 thật dùng PKWARE ZipCrypto, không phải AES-256 như tên lớp
# `pyzipper.AESZipFile` gợi ý — pyzipper tự chọn thuật toán theo entry). Module này được nạp lúc
# khởi động qua `backend/api/doi_chieu_song_phuong.py` — thiếu numba/numpy KHÔNG được làm sập cả
# backend, chỉ rơi về đọc streaming gốc của pyzipper (chậm hơn nhưng vẫn đúng) cho riêng module
# này.
try:
    import numpy as np
    from numba import njit
    _CO_NUMBA = True
except ImportError:
    _CO_NUMBA = False

# ─── Config ───────────────────────────────────────────────────────────────────
TEMP_DIR      = BASE_DIR / "data" / "temp_doi_chieu_song_phuong"

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


def tao_thu_muc_upload(task_token: str) -> Path:
    """Thư mục nhận file tải lên của một lượt: `upload_<token>/` trong TEMP_DIR.

    Nằm cùng chỗ với thư mục kết quả nên `_cleanup_old_results()` trông coi luôn,
    không phải thêm đường dọn thứ hai.
    """
    d = TEMP_DIR / f"upload_{task_token}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bo_luot(task_token: str) -> None:
    """Huỷ một lượt chưa chạy (upload lỗi/đứt): xoá thư mục và entry tiến độ."""
    shutil.rmtree(TEMP_DIR / f"upload_{task_token}", ignore_errors=True)
    _progress.pop(task_token, None)


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

def run_process(zip_path: Path, task_token: str) -> None:
    """Chạy process_zip trong background thread; cập nhật progress và bắt lỗi."""
    try:
        process_zip(zip_path, task_token)
    except Exception as e:
        log.error("process_zip lỗi [%s]: %s", task_token, e, exc_info=True)
        if task_token in _progress:
            _progress[task_token].update({
                "done": True, "error": str(e),
                "msg": "Lỗi xử lý — xem log server",
            })


def process_zip(
    zip_path: Path, task_token: str | None = None, log_callback=lambda msg: None,
) -> dict:
    """Nhận đường dẫn file ZIP trên máy chủ → định tuyến → ghi 8 CSV → trả metadata.

    `log_callback` (2026-09-01): hook tuỳ chọn để module khác gọi thẳng hàm này lấy log chi
    tiết theo dòng (VD `doi_chieu_song_phuong_core/pipeline.py::_doc_core`, giải mã lại GL02 khi
    chưa có CSV phân loại sẵn) — độc lập với `task_token`/`_progress` (dùng cho UI "Phân loại dữ
    liệu" gốc). Mặc định no-op, không đổi hành vi cũ.
    """
    _cleanup_old_results()
    t0 = time.time()

    # ── Kiểm tra magic bytes ──────────────────────────────────────────────────
    # Đọc đúng 4 byte đầu, không nạp cả file: chỗ này chạy TRƯỚC khi mở ZIP nên
    # nó là cửa duy nhất chặn được file người dùng chọn nhầm (PDF, Excel) —
    # thông báo "không phải ZIP" rõ hơn nhiều so với lỗi giải nén ném ra sau đó.
    with open(zip_path, "rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise ValueError("File tải lên không phải định dạng ZIP hợp lệ.")

    _set_prog(task_token, 5, "Đang giải mã và đọc dữ liệu...")
    log_callback("Đang giải mã và đọc dữ liệu...")

    buffers = {(c, d): [] for c in BANK_MAP for d in DIRECTIONS}
    counts  = {(c, d): 0  for c in BANK_MAP for d in DIRECTIONS}
    hdr_line   = None
    total_rows = 0
    so_file_numba = 0

    try:
        zf = _open_zip(str(zip_path))
    except Exception as e:
        raise ValueError(f"Không mở được file ZIP: {e}")

    t_giai_ma0 = time.perf_counter()
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
            # Ưu tiên đường tắt numba cho ZipCrypto cổ điển (tải trọn ĐÚNG 1 file thành viên vào
            # RAM — không phải cả 8 — để giải mã bằng mảng numpy; ~20-25MB nén/~140MB giải nén
            # cho GL02 thật, đủ nhỏ để chấp nhận đổi lấy tốc độ nhanh hơn ~35 lần). Không chắc
            # chắn (AES thật, thiếu numba...) thì rơi về `zf.open()` streaming gốc — không tải cả
            # file vào RAM, giữ đúng tinh thần thiết kế hiện tại.
            try:
                nguon, dung_numba = _mo_doc_1_file_thanh_vien(zf, name, zip_password())
            except Exception as e:
                raise ValueError(
                    f"Không giải mã được '{name}' — sai mật khẩu hoặc file hỏng ({e})."
                )
            if dung_numba:
                so_file_numba += 1
            with nguon:
                reader = csv.reader(io.TextIOWrapper(
                    nguon, encoding="utf-8-sig", newline=""))
                file_hdr, routed = _route_file(reader, buffers, counts, name)
            if hdr_line is None and file_hdr:
                hdr_line = file_hdr
            total_rows += routed
            msg = f"Đã xử lý {i + 1}/{n}: {name} ({routed:,} dòng)"
            _set_prog(task_token, int(5 + (i + 1) * 75 / n), msg)
            log_callback(msg)
    if _CO_NUMBA:
        log_callback(
            f"[TIMING] giải mã+định tuyến ZIP GL02 ({so_file_numba}/{n} file dùng đường tắt "
            f"numba): {time.perf_counter() - t_giai_ma0:.1f}s"
        )

    # ── Ghi 8 file CSV (kể cả file rỗng → chỉ header) ─────────────────────────
    _set_prog(task_token, 85, f"Đang ghi 8 file CSV ({total_rows:,} dòng)...")
    log_callback(f"Đang ghi 8 file CSV ({total_rows:,} dòng)...")
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
    log_callback("Hoàn thành!")
    return result


# ─── Giải mã nhanh (numba) cho ZipCrypto cổ điển ────────────────────────────────
# Phát hiện 2026-09-01: dù dùng `pyzipper.AESZipFile` và đặt tên "AES" khắp nơi trong code/tài
# liệu cũ, file GL02 THẬT lại dùng mã hoá PKWARE ZipCrypto cổ điển (compress_type=8, KHÔNG phải
# 99 = mã AES thật của pyzipper) — không phải AES-256. `pyzipper` giải mã kiểu này bằng vòng lặp
# Python xử lý TỪNG BYTE MỘT (profiling: hàng trăm triệu lượt gọi `update_keys()`/`crc32()` cho 8
# file GL02 thật) — đây mới là nguyên nhân chậm, không phải bản chất phép toán mã hoá (AES-NI
# phần cứng qua pycryptodomex đo riêng đạt ~974 MB/s). Viết lại đúng thuật toán ZipCrypto (giống
# hệt `pyzipper.zipfile.CRCZipDecrypter`) bằng `numba.njit` — biên dịch máy JIT, không cần
# compiler/binary hệ thống ngoài — nhanh hơn ~35 lần khi verify trên dữ liệu GL02 thật, output
# byte-for-byte giống hệt.
#
# CHỈ áp dụng khi CHẮC CHẮN đúng thuật toán: `compress_type == ZIP_DEFLATED` (8) và
# `wz_aes_version is None` (loại trừ AES thật — pyzipper GHI ĐÈ compress_type bằng phương pháp
# nén thật bên trong extra field AES, cũng ra 8, nên compress_type một mình không đủ phân biệt).
# Mọi trường hợp khác (AES thật, STORED, thiếu numba...) rơi về `zf.open()` streaming gốc của
# pyzipper — không đoán, không tự ý mở rộng đường tắt cho case chưa xác nhận.

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
    trí `header_offset` — hoạt động với cả file thật lẫn `io.BytesIO` trong bộ nhớ."""
    zf.fp.seek(info.header_offset)
    local_header = zf.fp.read(30)
    (_sig, _ver, _flag, _comp, _mtime, _mdate, _crc, _csize, _usize, nlen, elen) = \
        struct.unpack("<IHHHHHIIIHH", local_header)
    zf.fp.seek(info.header_offset + 30 + nlen + elen)
    return zf.fp.read(info.compress_size)


def _mo_doc_1_file_thanh_vien(zf, name: str, pwd: bytes):
    """Trả `(stream, dung_numba)` — `stream` là 1 file-like object mở được bằng `with` rồi bọc
    `io.TextIOWrapper` cho `csv.reader` (giống hệt cách gọi `zf.open()` trước đây). Dùng đường
    tắt numba (tải trọn 1 file thành viên vào RAM) khi chắc chắn đúng ZipCrypto cổ điển, ngược
    lại trả `zf.open()` streaming gốc (không tải cả file vào RAM) — xem block comment phía trên."""
    if not _CO_NUMBA:
        return zf.open(name, pwd=pwd), False

    info = zf.getinfo(name)
    is_zip_crypto = (
        bool(info.flag_bits & 0x1)               # bit 0 = có mã hoá
        and not bool(info.flag_bits & 0x40)      # bit 6 = strong encryption (không dùng ở đây)
        and getattr(info, "wz_aes_version", None) is None   # KHÔNG phải AES thật
        and info.compress_type == zipfile.ZIP_DEFLATED
    )
    if not is_zip_crypto:
        return zf.open(name, pwd=pwd), False

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
    return io.BytesIO(decompressed), True


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


def _cleanup_old_results(cutoff: float | None = None) -> None:
    """Xóa thư mục kết quả và progress entry cũ hơn `cutoff`.

    Mặc định là mốc 23h gần nhất đã trôi qua (backend/core/don_dep.py) — kết quả
    sống hết ngày làm việc thay vì tự bốc hơi sau 2 giờ như trước. Vì mốc đó
    không bao giờ rơi vào trong ngày đang chạy, hàm này vẫn gọi được ngay đầu
    một lượt xử lý mới mà không xoá mất kết quả người khác vừa chạy sáng nay.
    """
    cutoff = moc_don_gan_nhat() if cutoff is None else cutoff

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            # stat() nằm TRONG try, dù `is_dir()` đã chặn phần lớn: hai lượt dọn
            # chạy sát nhau (mỗi lượt xử lý mới đều gọi hàm này) vẫn có kẽ hở
            # giữa is_dir() và stat() để lượt kia xoá xong thư mục. Rơi vào kẽ
            # đó thì OSError ném thẳng ra giữa `process_files()` và người dùng
            # nhận lỗi 500 chẳng liên quan gì tới file họ vừa tải lên. Phòng xa,
            # chưa gặp thật — cùng cách `ach_service._cleanup_old_jobs()` làm.
            try:
                if sub.is_dir() and sub.stat().st_mtime < cutoff:
                    shutil.rmtree(sub)
            except OSError as e:
                log.warning("Không xóa được %s: %s", sub, e)

    stale = [k for k, v in _progress.items() if v.get("_ts", 0) < cutoff]
    for k in stale:
        _progress.pop(k, None)
