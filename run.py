#!/usr/bin/env python3
"""
Script khởi chạy toàn bộ hệ thống PAYMENT CENTER

Cách dùng:
  python run.py          # Chạy cả backend + frontend (auto-restart)
  python run.py backend  # Chỉ backend
  python run.py frontend # Chỉ frontend
  python run.py init     # Khởi tạo database
"""
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT          = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

LOGS_DIR      = os.path.join(ROOT, "logs")
MAX_RESTARTS  = 5
RESTART_DELAY = 3
# Chết nhanh hơn ngần này giây = hỏng ngay lúc khởi động (thường là cổng bị
# chiếm), không phải sự cố lúc đang chạy → thử lại vô ích, dừng sớm cho rõ.
FAST_FAIL_SEC   = 5
MAX_FAST_FAILS  = 2
BACKEND_PORT  = os.getenv("BACKEND_PORT", "8000")
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "8080")
BACKEND_HOST  = os.getenv("BACKEND_HOST", "0.0.0.0").strip() or "0.0.0.0"
BACKEND_URL   = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL  = f"http://localhost:{FRONTEND_PORT}"
# Địa chỉ để TỰ GỌI kiểm tra, KHÔNG dùng để hiển thị.
# Không dùng `localhost`: trên Windows nó phân giải ra ::1 (IPv6) trước, mà uvicorn
# chỉ lắng nghe IPv4 → mỗi kết nối mới tốn ~2 giây chờ IPv6 thất bại rồi mới quay
# sang IPv4. Đo được: localhost 2062ms vs 127.0.0.1 18ms.
# 0.0.0.0 nghĩa là "mọi giao diện" — không gọi thẳng vào đó được, phải gõ 127.0.0.1.
# Còn nếu bind vào một IP cụ thể thì phải gọi đúng IP đó, 127.0.0.1 sẽ không ai nghe.
_PROBE_HOST    = "127.0.0.1" if BACKEND_HOST in ("0.0.0.0", "::") else BACKEND_HOST
BACKEND_PROBE  = f"http://{_PROBE_HOST}:{BACKEND_PORT}"
FRONTEND_PROBE = f"http://127.0.0.1:{FRONTEND_PORT}"   # frontend luôn bind 0.0.0.0
POLL_TIMEOUT  = 40   # giây chờ mỗi service sẵn sàng

_stop_event = threading.Event()
_print_lock = threading.Lock()


# ── Output helpers ────────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _print(msg: str):
    with _print_lock:
        print(msg, flush=True)


def _info(msg: str):
    _print(f"  [{_ts()}] {msg}")


def _ok(msg: str):
    _print(f"  [{_ts()}] ✓ {msg}")


def _warn(msg: str):
    _print(f"  [{_ts()}] ⚠ {msg}")


def _err(msg: str):
    _print(f"  [{_ts()}] ✗ {msg}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_dirs():
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)


def _log_path(name: str) -> str:
    return os.path.join(LOGS_DIR, f"{name}.log")


def _open_log(name: str):
    return open(_log_path(name), "a", encoding="utf-8", buffering=1)


def _port_in_use(port, host: str = "127.0.0.1") -> bool:
    """True nếu đã có tiến trình nào đó đang lắng nghe trên cổng này."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, int(port))) == 0


def _check_ports_free(*cap) -> bool:
    """Kiểm tra cổng trước khi khởi động. In hướng dẫn và trả False nếu bị chiếm.

    Không có bước này, khởi động lần hai sẽ nói dối trắng trợn: con của nó chết
    vì không bind được cổng, nhưng `_poll()` lại gõ trúng INSTANCE ĐANG CHẠY và
    báo "sẵn sàng"; rồi sau vài vòng restart nó kết luận "Hệ thống đã dừng hoàn
    toàn" trong khi hệ thống thật vẫn đang phục vụ bình thường.
    """
    # Mỗi mục: (tên, cổng) hoặc (tên, cổng, địa-chỉ-để-thử)
    ban = [m[:2] for m in cap
           if _port_in_use(m[1], m[2] if len(m) > 2 else "127.0.0.1")]
    if not ban:
        return True
    _print("")
    for ten, cong in ban:
        _err(f"Cổng {cong} ({ten}) đang bị chiếm.")
    _print("")
    _info("Nhiều khả năng hệ thống ĐÃ CHẠY SẴN. Kiểm tra bằng cách mở:")
    _info(f"    {FRONTEND_URL}")
    _info("Nếu muốn khởi động lại, hãy tắt tiến trình cũ trước:")
    _info(f"    netstat -ano | findstr :{ban[0][1]}       (xem PID)")
    _info("    taskkill /PID <PID> /F")
    _print("")
    return False


def _poll(url: str, timeout: int = POLL_TIMEOUT) -> bool:
    """Poll GET url cho đến khi HTTP 200 hoặc timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _stop_event.is_set():
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _run_with_restart(name: str, cmd: list, max_restarts: int = MAX_RESTARTS):
    """Vòng lặp restart subprocess. Ghi stdout+stderr vào logs/{name}.log."""
    restarts = 0
    fast_fails = 0
    while not _stop_event.is_set():
        log_file = _open_log(name)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        # Chỉ in banner restart khi restart thật sự (không phải lần đầu)
        if restarts > 0:
            msg = f"\n[{ts}] ─── Restart {name} (lần {restarts + 1}) ───\n"
            log_file.write(msg)
            log_file.flush()
            _warn(f"Restart {name} (lần {restarts + 1}/{max_restarts})...")
        else:
            log_file.write(f"\n[{ts}] ─── Khởi động {name} ───\n")
            log_file.flush()

        t_start = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )

        while proc.poll() is None:
            if _stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                log_file.close()
                return
            time.sleep(0.5)

        exit_code = proc.returncode
        log_file.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {name} thoát với code {exit_code}\n")
        log_file.close()

        if _stop_event.is_set():
            return

        # Chết trong vài giây đầu = hỏng lúc khởi động (cổng bị chiếm, thiếu
        # biến môi trường, lỗi cú pháp). Thử lại chỉ tổ mất 25 giây rồi vẫn hỏng.
        song = time.time() - t_start
        fast_fails = fast_fails + 1 if song < FAST_FAIL_SEC else 0
        if fast_fails >= MAX_FAST_FAILS:
            _err(f"{name} chết ngay khi vừa khởi động, {fast_fails} lần liên tiếp — dừng.")
            _err(f"Xem nguyên nhân ở {_log_path(name)}")
            _stop_event.set()
            return

        restarts += 1
        if restarts > max_restarts:
            _err(f"{name} đã crash {max_restarts} lần — dừng. Xem {_log_path(name)}")
            _stop_event.set()
            return

        _warn(f"{name} crash (code={exit_code}). Thử lại sau {RESTART_DELAY}s...")
        time.sleep(RESTART_DELAY)


# ── Signal handler ────────────────────────────────────────────────────────────

def _signal_handler(sig, frame):
    _print("\n")
    _info("Nhận tín hiệu dừng — đang tắt hệ thống...")
    _stop_event.set()


signal.signal(signal.SIGINT, _signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _signal_handler)


# ── Commands ──────────────────────────────────────────────────────────────────

def run_backend():
    _run_with_restart(
        name="backend",
        cmd=[sys.executable, "-m", "uvicorn", "backend.main:app",
             "--host", BACKEND_HOST, "--port", BACKEND_PORT],
    )


def run_frontend():
    _run_with_restart(
        name="frontend",
        cmd=[sys.executable, "frontend/main.py"],
    )


def _run_one(ten: str, cong, ham, host: str = "127.0.0.1"):
    """Chạy riêng backend hoặc frontend, có kiểm tra cổng trước."""
    _ensure_dirs()
    if not _check_ports_free((ten, cong, host)):
        return
    _info(f"Khởi động {ten} (standalone)...")
    ham()


def run_all():
    _ensure_dirs()

    sep = "─" * 54
    _print(f"\n  {'═' * 54}")
    _print(f"    PAYMENT CENTER  —  Hệ thống Trung tâm Thanh toán")
    _print(f"  {'═' * 54}")
    _print(f"    Backend   →  {BACKEND_URL}")
    _print(f"    Frontend  →  {FRONTEND_URL}")
    _print(f"    Nhật ký   →  logs/backend.log  |  logs/frontend.log")
    _print(f"  {sep}\n")

    if not _check_ports_free(("backend", BACKEND_PORT, _PROBE_HOST),
                             ("frontend", FRONTEND_PORT)):
        return

    # ── Backend ──
    _info("Đang khởi động backend...")
    be_thread = threading.Thread(target=run_backend, name="backend", daemon=False)
    be_thread.start()

    if not _poll(BACKEND_PROBE + "/"):
        if not _stop_event.is_set():
            _err(f"Backend không phản hồi sau {POLL_TIMEOUT}s — kiểm tra logs/backend.log")
            _stop_event.set()
        be_thread.join()
        return
    _ok(f"Backend sẵn sàng    →  {BACKEND_URL}/docs")

    # ── Frontend ──
    _info("Đang khởi động frontend...")
    fe_thread = threading.Thread(target=run_frontend, name="frontend", daemon=False)
    fe_thread.start()

    if not _poll(FRONTEND_PROBE + "/"):
        if not _stop_event.is_set():
            _warn(f"Frontend chưa phản hồi sau {POLL_TIMEOUT}s — có thể vẫn đang tải.")
        # Không abort — frontend vẫn đang chạy, chỉ là chậm hơn
    else:
        _ok(f"Frontend sẵn sàng  →  {FRONTEND_URL}")

    # Một trong hai tiến trình đã chết trong lúc chờ → đừng báo "sẵn sàng"
    if _stop_event.is_set():
        _err("Khởi động thất bại — xem logs/backend.log và logs/frontend.log")
        be_thread.join()
        fe_thread.join()
        return

    _print(f"\n  {'═' * 54}")
    _print(f"    HỆ THỐNG ĐÃ SẴN SÀNG  —  Mở trình duyệt:")
    _print(f"    {FRONTEND_URL}")
    _print(f"    Nhấn Ctrl+C để dừng hệ thống.")
    _print(f"  {'═' * 54}\n")

    # Main thread chờ stop_event
    try:
        while not _stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        _stop_event.set()

    _info("Đang dừng các tiến trình...")
    be_thread.join()
    fe_thread.join()
    _print(f"\n  {'─' * 54}")
    _info("Hệ thống đã dừng hoàn toàn.")
    _print(f"  {'─' * 54}\n")


def run_init():
    _print("\n  Đang khởi tạo cơ sở dữ liệu...")
    _ensure_dirs()
    subprocess.run([sys.executable, "init_db.py"], cwd=ROOT)
    _ok("Khởi tạo hoàn tất.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "init":
        run_init()
    elif cmd == "backend":
        _run_one("backend", BACKEND_PORT, run_backend, _PROBE_HOST)
    elif cmd == "frontend":
        _run_one("frontend", FRONTEND_PORT, run_frontend)
    else:
        run_all()
