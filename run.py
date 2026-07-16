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
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from dotenv import load_dotenv

ROOT          = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

LOGS_DIR      = os.path.join(ROOT, "logs")
MAX_RESTARTS  = 5
RESTART_DELAY = 3
BACKEND_PORT  = os.getenv("BACKEND_PORT", "8000")
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "8080")
BACKEND_URL   = f"http://localhost:{BACKEND_PORT}"
FRONTEND_URL  = f"http://localhost:{FRONTEND_PORT}"
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
             "--host", "0.0.0.0", "--port", BACKEND_PORT],
    )


def run_frontend():
    _run_with_restart(
        name="frontend",
        cmd=[sys.executable, "frontend/main.py"],
    )


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

    # ── Backend ──
    _info("Đang khởi động backend...")
    be_thread = threading.Thread(target=run_backend, name="backend", daemon=False)
    be_thread.start()

    if not _poll(BACKEND_URL + "/"):
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

    if not _poll(FRONTEND_URL + "/"):
        if not _stop_event.is_set():
            _warn(f"Frontend chưa phản hồi sau {POLL_TIMEOUT}s — có thể vẫn đang tải.")
        # Không abort — frontend vẫn đang chạy, chỉ là chậm hơn
    else:
        _ok(f"Frontend sẵn sàng  →  {FRONTEND_URL}")

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
        _ensure_dirs()
        _info("Khởi động backend (standalone)...")
        run_backend()
    elif cmd == "frontend":
        _ensure_dirs()
        _info("Khởi động frontend (standalone)...")
        run_frontend()
    else:
        run_all()
