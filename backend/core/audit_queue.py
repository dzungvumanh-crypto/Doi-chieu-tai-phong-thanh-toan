"""Hàng đợi ghi nhật ký thao tác — một luồng ghi duy nhất, không chặn response.

Trước đây middleware `await` việc ghi audit rồi mới trả response. Đo thực tế:
khi một lệnh ghi khác đang giữ khoá DB, mọi POST chậm thêm **5,5 giây** — đúng
bằng `busy_timeout` của audit. Người dùng phải chờ cho một dòng nhật ký mà họ
không hề quan tâm.

Ở đây middleware chỉ **bỏ vào hàng đợi rồi đi tiếp**. Một luồng nền lấy ra ghi.

Ba tính chất quan trọng:

* **Một người ghi duy nhất** — audit là bảng chỉ thêm, không cần ghi song song.
  Một luồng nghĩa là không bao giờ có hai kết nối audit tranh khoá lẫn nhau.
* **Hàng đợi có trần** — đầy thì bỏ dòng mới và ghi WARNING, không bao giờ ăn
  hết RAM. Mất một dòng nhật ký còn hơn sập cả hệ thống.
* **Xả khi tắt máy** — `stop()` được gọi trong `lifespan` để dòng đang chờ kịp
  xuống đĩa thay vì bay theo tiến trình.
"""
import logging
import queue
import sqlite3
import threading

from backend.database import DB_PATH, _vn_now
from backend.core.security import decode_token
from backend.core.sessions import get_session_ip

_log = logging.getLogger("audit")

MAX_QUEUE = 2000       # ~vài trăm KB; đầy nghĩa là DB hỏng hoặc kẹt rất lâu
_WRITE_TIMEOUT = 10    # luồng nền chờ khoá được lâu hơn, vì không ai đợi nó

_q: "queue.Queue[tuple | None]" = queue.Queue(maxsize=MAX_QUEUE)
_worker: threading.Thread | None = None
_lock = threading.Lock()
_da_canh_bao_day = False


def enqueue(method: str, path: str, status_code: int,
            auth_header: str, hdr_ip: str | None, client_ip: str | None) -> None:
    """Bỏ một dòng audit vào hàng đợi. Không bao giờ chặn, không bao giờ raise."""
    global _da_canh_bao_day
    try:
        _q.put_nowait((method, path, status_code, auth_header, hdr_ip, client_ip))
        _da_canh_bao_day = False
    except queue.Full:
        # Chỉ kêu 1 lần mỗi đợt đầy — tránh biến log thành bãi rác
        if not _da_canh_bao_day:
            _da_canh_bao_day = True
            _log.warning(
                "Hàng đợi audit đầy (%d dòng) — đang bỏ bớt dòng mới. "
                "Nhiều khả năng DB bị khoá lâu hoặc đĩa có vấn đề.", MAX_QUEUE,
            )


def _actor_id(auth_header: str):
    if not auth_header.lower().startswith("bearer "):
        return None
    payload = decode_token(auth_header[7:].strip())
    if not payload:
        return None
    sub = payload.get("sub")
    try:
        return int(sub) if sub is not None else None
    except (ValueError, TypeError):
        return None


def _real_ip(db, actor_id, hdr_ip, client_ip) -> str | None:
    # Frontend NiceGUI gọi backend từ chính server → client.host = 127.0.0.1.
    # IP thật của browser lưu ở login_sessions lúc đăng nhập → tra theo actor
    # để khớp với Nhật ký đăng nhập. Ưu tiên: header → session → client.host.
    if hdr_ip:
        return hdr_ip
    if actor_id is not None:
        try:
            sess_ip = get_session_ip(db, actor_id)
            if sess_ip:
                return sess_ip
        except Exception:
            pass
    return client_ip


def _vong_lap() -> None:
    """Luồng nền: giữ MỘT kết nối, ghi từng dòng cho tới khi nhận tín hiệu dừng."""
    db = None
    try:
        while True:
            item = _q.get()
            if item is None:            # tín hiệu dừng
                _q.task_done()
                return
            try:
                if db is None:
                    db = sqlite3.connect(DB_PATH, timeout=_WRITE_TIMEOUT)
                    db.row_factory = sqlite3.Row
                    db.execute(f"PRAGMA busy_timeout={_WRITE_TIMEOUT * 1000}")
                method, path, status_code, auth_header, hdr_ip, client_ip = item
                actor = _actor_id(auth_header)
                db.execute(
                    "INSERT INTO audit_logs (actor_id, action, target_type, target_id,"
                    " detail, ip_address, created_at) VALUES (?,?,?,?,?,?,?)",
                    (actor, method, path, None, f"HTTP {status_code}",
                     _real_ip(db, actor, hdr_ip, client_ip), _vn_now()),
                )
                db.commit()
            except Exception:
                _log.warning("Không ghi được audit cho %s %s", item[0], item[1], exc_info=True)
                # Kết nối có thể đã hỏng — bỏ đi, vòng sau tự mở lại
                try:
                    if db is not None:
                        db.close()
                except Exception:
                    pass
                db = None
            finally:
                _q.task_done()
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def start() -> None:
    """Khởi động luồng ghi nền. Gọi nhiều lần cũng chỉ tạo một luồng."""
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_vong_lap, daemon=True, name="audit-writer")
        _worker.start()
        _log.info("Luồng ghi audit đã khởi động (hàng đợi tối đa %d dòng)", MAX_QUEUE)


def stop(timeout: float = 5.0) -> None:
    """Xả nốt hàng đợi rồi dừng luồng — gọi khi tắt app."""
    global _worker
    with _lock:
        w = _worker
        _worker = None
    if w is None or not w.is_alive():
        return
    try:
        _q.put_nowait(None)
    except queue.Full:
        return          # đầy tới mức không nhét nổi tín hiệu dừng → cứ để daemon chết theo
    w.join(timeout=timeout)
    if w.is_alive():
        _log.warning("Luồng ghi audit chưa xả hết sau %.1fs — còn %d dòng chưa ghi",
                     timeout, _q.qsize())
