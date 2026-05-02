#!/usr/bin/env python3
"""
Script khởi chạy toàn bộ hệ thống KSNB&HTVH

Cách dùng:
  python run.py          # Chạy cả backend + frontend
  python run.py backend  # Chỉ backend
  python run.py frontend # Chỉ frontend
  python run.py init     # Khởi tạo database
"""
import sys
import os
import subprocess
import threading
import time

ROOT = os.path.dirname(__file__)
sys.path.insert(0, ROOT)


def run_backend():
    print("🚀 Khởi động Backend (port 8000)...")
    os.chdir(ROOT)
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "backend.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
    ])


def run_frontend():
    print("🎨 Khởi động Frontend (port 8080)...")
    time.sleep(2)  # Chờ backend start
    os.chdir(ROOT)
    subprocess.run([sys.executable, "frontend/main.py"])


def run_init():
    print("🔧 Khởi tạo database...")
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    subprocess.run([sys.executable, "init_db.py"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "init":
        run_init()

    elif cmd == "backend":
        run_backend()

    elif cmd == "frontend":
        run_frontend()

    else:  # all
        # Khởi tạo DB trước
        os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

        # Chạy backend trong thread riêng
        backend_thread = threading.Thread(target=run_backend, daemon=True)
        backend_thread.start()

        # Chạy frontend (blocking)
        run_frontend()
