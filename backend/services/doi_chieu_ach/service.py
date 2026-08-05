"""Lớp dịch vụ Đối chiếu ACH — chạy nền theo token, poll tiến độ, tải kết quả.

Vì sao chạy trên ThreadPoolExecutor riêng (1 luồng) thay vì BackgroundTasks như
`doi_chieu_song_phuong`:
- Một lần đối chiếu ACH mất vài phút và tự mở thêm 4 luồng con. Nếu dùng
  BackgroundTasks, việc này chiếm luồng của bể chung anyio (40 token) suốt thời
  gian đó — đúng vấn đề mà `backend/core/concurrency.py` mô tả.
- max_workers=1: hai lần chạy song song vừa tốn RAM gấp đôi (mỗi lần giữ vài
  triệu dòng pandas) vừa không nhanh hơn vì pandas giữ GIL. Job thứ hai xếp hàng
  và giao diện vẫn thấy tiến độ "đang chờ".
"""

import io
import logging
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .engine import chay_doi_chieu

log = logging.getLogger(__name__)

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
TEMP_DIR = Path("data/temp_doi_chieu_ach")
CLEANUP_HOURS = 4          # kết quả giữ 4 giờ rồi tự xoá
MAX_LOG_LINES = 300        # số dòng log giữ lại cho giao diện

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doi-chieu-ach")

# key = token; value = {pct, msg, logs, done, error, result, _ts}
_progress: dict[str, dict] = {}
_cancel_events: dict[str, threading.Event] = {}
_lock = threading.Lock()

# ─── Mốc tiến độ theo log của engine ──────────────────────────────────────────
# Các bước B2/B3/B6 chạy song song nên log không về theo thứ tự — pct luôn được
# lấy max() để thanh tiến độ không bao giờ tụt lùi.
_MOC_PCT = [
    ("[B1] Session",       8),
    ("[B4] Đọc MIS_DI",    12),
    ("[B3] GW",            28),
    ("[B2] GL02",          38),
    ("[B4] MIS_DI →",      50),
    ("[B6] MIS_DEN",       56),
    ("[TIMING] Pha 1",     60),
    ("[B5] Khớp",          68),
    ("[B7] Khớp",          72),
    ("[TIMING] Pha 2",     75),
    ("[DONE]",             96),
]


def _pct_tu_log(msg: str) -> int | None:
    """Suy % tiến độ từ một dòng log. Trả None nếu dòng đó không phải mốc."""
    if msg.startswith("[EXCEL] ("):
        # dạng: [EXCEL] (3/11) Ghi sheet: ...
        try:
            frac = msg.split("(", 1)[1].split(")", 1)[0]
            i, n = (int(x) for x in frac.split("/"))
            return 76 + int(i * 19 / n)
        except (ValueError, IndexError):
            return None
    for prefix, pct in _MOC_PCT:
        if msg.startswith(prefix):
            return pct
    return None


# ─── Vòng đời job ─────────────────────────────────────────────────────────────

def tao_job() -> str:
    """Tạo token + thư mục input/output rỗng cho một lần chạy."""
    _don_dep_cu()
    token = str(uuid.uuid4())
    (TEMP_DIR / token / "input").mkdir(parents=True, exist_ok=True)
    (TEMP_DIR / token / "output").mkdir(parents=True, exist_ok=True)
    with _lock:
        _progress[token] = {
            "pct": 0, "msg": "Đang nhận file...", "logs": [],
            "done": False, "error": None, "cancelled": False, "result": None,
            "_ts": time.time(),
        }
    return token


def _job_dir(token: str) -> Path:
    """Thư mục job, đã kiểm tra token nằm đúng 1 cấp dưới TEMP_DIR.

    Token đi thẳng từ URL vào đường dẫn nên phải chặn cả `..`; kiểm tra sau khi
    resolve() là cách duy nhất đúng trên Windows (còn có `%2f`, `\\`, tên 8.3).
    """
    root = TEMP_DIR.resolve()
    d = (root / token).resolve()
    if d.parent != root or d == root:
        raise KeyError(token)
    return d


def duong_dan_input(token: str) -> Path:
    """Thư mục input của job. Chỉ chấp nhận token do `tao_job` phát ra."""
    with _lock:
        if token not in _progress:
            raise KeyError(token)
    return _job_dir(token) / "input"


def da_bat_dau(token: str) -> bool:
    """True khi job đã được đưa vào hàng đợi / đang chạy / đã xong."""
    with _lock:
        p = _progress.get(token)
        return bool(p and p.get("_started"))


def liet_ke_input(token: str) -> list[dict]:
    d = duong_dan_input(token)
    if not d.is_dir():
        return []
    return sorted(
        ({"name": f.name, "size": f.stat().st_size} for f in d.iterdir() if f.is_file()),
        key=lambda f: f["name"],
    )


def xoa_file_input(token: str, filename: str) -> bool:
    """Xoá 1 file đã tải lên (người dùng chọn nhầm). Chỉ xoá trong thư mục input.

    Trên Windows, file vừa ghi xong có thể còn bị phần mềm diệt virus hoặc bộ
    lập chỉ mục giữ vài trăm ms → unlink ném WinError 5/32. Thử lại vài nhịp
    thay vì báo hỏng ngay; vẫn không xoá được thì để lỗi nổi lên cho người dùng
    biết, KHÔNG nuốt (nuốt thì giao diện báo đã xoá mà máy chủ vẫn giữ file).
    """
    in_dir = duong_dan_input(token).resolve()
    path = (in_dir / Path(filename).name).resolve()
    if path.parent != in_dir or not path.is_file():
        return False

    for lan in range(4):
        try:
            path.unlink()
            return True
        except OSError as e:
            if lan == 3:
                log.warning("Không xoá được %s sau 4 lần thử: %s", path, e)
                raise
            time.sleep(0.3)
    return True


def get_progress(token: str) -> dict | None:
    with _lock:
        p = _progress.get(token)
        if p is None:
            return None
        return {k: (list(v) if isinstance(v, list) else v)
                for k, v in p.items() if not k.startswith("_")}


def huy_job(token: str) -> bool:
    """Đặt cờ huỷ. Engine dừng ở mốc kiểm tra gần nhất, không kill giữa chừng."""
    ev = _cancel_events.get(token)
    if ev is None:
        return False
    ev.set()
    _ghi_log(token, "[CANCELLED] Đã gửi yêu cầu dừng, chờ bước hiện tại kết thúc...")
    return True


def chay_nen(token: str, ngay: str | None) -> None:
    """Đưa job vào hàng đợi 1 luồng. Trả về ngay, không chờ."""
    ev = threading.Event()
    _cancel_events[token] = ev
    with _lock:
        p = _progress.get(token)
        if p is not None:
            p["_started"] = True
            p["msg"] = "Đang xếp hàng chờ xử lý..."
    _executor.submit(_chay, token, ngay, ev)


# ─── Thực thi ─────────────────────────────────────────────────────────────────

def _ghi_log(token: str, msg: str) -> None:
    with _lock:
        p = _progress.get(token)
        if p is None:
            return
        p["logs"].append(msg)
        if len(p["logs"]) > MAX_LOG_LINES:
            del p["logs"][:-MAX_LOG_LINES]
        p["msg"] = msg
        pct = _pct_tu_log(msg)
        if pct is not None and pct > p["pct"]:
            p["pct"] = pct


def _chay(token: str, ngay: str | None, cancel_ev: threading.Event) -> None:
    job_dir = TEMP_DIR / token
    out_dir = job_dir / "output"

    def emit(msg: str):
        _ghi_log(token, str(msg))

    try:
        _ghi_log(token, "Bắt đầu xử lý...")
        ket_qua = chay_doi_chieu(
            input_dir=str(job_dir / "input"),
            output_dir=str(out_dir),
            ngay=ngay,
            log_callback=emit,
            cancel_event=cancel_ev,
        )

        if ket_qua is None:
            # Huỷ là hành động có chủ đích, KHÔNG phải lỗi — để vào `error` thì
            # giao diện bật thông báo đỏ, người dùng tưởng hệ thống hỏng.
            with _lock:
                p = _progress.get(token)
                if p is not None:
                    p.update({"done": True, "cancelled": True, "error": None,
                              "msg": "Đã huỷ theo yêu cầu người dùng"})
            _xoa_thu_muc(job_dir / "input")
            return

        output_path, summary = ket_qua
        files = sorted(
            ({"name": f.name, "size": f.stat().st_size} for f in out_dir.iterdir() if f.is_file()),
            # File Excel luôn đứng đầu, CSV phụ xếp sau
            key=lambda f: (not f["name"].endswith(".xlsx"), f["name"]),
        )
        with _lock:
            p = _progress.get(token)
            if p is not None:
                p.update({
                    "pct": 100, "msg": "Hoàn thành!", "done": True,
                    "result": {"token": token, "files": files, "summary": summary},
                })
        # File đầu vào có thể vài trăm MB — xoá ngay khi có kết quả
        _xoa_thu_muc(job_dir / "input")

    except Exception as e:
        log.error("Đối chiếu ACH lỗi [%s]: %s", token, e, exc_info=True)
        with _lock:
            p = _progress.get(token)
            if p is not None:
                p.update({"done": True, "error": str(e), "msg": "Lỗi xử lý — xem chi tiết bên dưới"})
        _xoa_thu_muc(job_dir / "input")
    finally:
        _cancel_events.pop(token, None)


# ─── Tải kết quả ──────────────────────────────────────────────────────────────

def doc_file_ket_qua(token: str, filename: str) -> bytes:
    """Đọc 1 file kết quả. Chặn path traversal cả ở token lẫn tên file."""
    try:
        out_dir = (_job_dir(token) / "output").resolve()
    except KeyError:
        raise FileNotFoundError("File không tồn tại hoặc đã hết hạn")
    path = (out_dir / Path(filename).name).resolve()
    if path.parent != out_dir or not path.is_file():
        raise FileNotFoundError("File không tồn tại hoặc đã hết hạn")
    return path.read_bytes()


def dong_goi_zip(token: str) -> bytes:
    """Gộp toàn bộ file kết quả thành 1 ZIP trong bộ nhớ."""
    try:
        out_dir = _job_dir(token) / "output"
    except KeyError:
        raise FileNotFoundError("Không còn kết quả cho lần chạy này")
    if not out_dir.is_dir():
        raise FileNotFoundError("Không còn kết quả cho lần chạy này")
    files = [f for f in out_dir.iterdir() if f.is_file()]
    if not files:
        raise FileNotFoundError("Không còn kết quả cho lần chạy này")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    buf.seek(0)
    return buf.getvalue()


# ─── Dọn dẹp ──────────────────────────────────────────────────────────────────

def _xoa_thu_muc(path: Path) -> None:
    """Xoá thư mục; nếu Windows còn khoá file thì ghi cảnh báo chứ không im lặng.

    `ignore_errors=True` một mình sẽ nuốt lỗi hoàn toàn — mỗi lần chạy để lại
    vài trăm MB trong `data/` mà không ai biết cho tới khi hết đĩa.
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        log.warning(
            "Còn sót thư mục tạm %s (file đang bị chương trình khác giữ). "
            "Sẽ dọn ở lần chạy sau.", path,
        )


def _don_dep_cu() -> None:
    """Xoá thư mục job và progress entry cũ hơn CLEANUP_HOURS giờ."""
    cutoff = time.time() - CLEANUP_HOURS * 3600

    if TEMP_DIR.exists():
        for sub in TEMP_DIR.iterdir():
            if not sub.is_dir():
                continue
            if sub.name in _cancel_events:      # job đang chạy — không đụng vào
                continue
            try:
                if sub.stat().st_mtime < cutoff:
                    _xoa_thu_muc(sub)
            except OSError as e:
                log.warning("Không đọc được %s: %s", sub, e)

    with _lock:
        stale = [k for k, v in _progress.items()
                 if v.get("_ts", 0) < cutoff and k not in _cancel_events]
        for k in stale:
            _progress.pop(k, None)
