# -*- coding: utf-8 -*-
"""
upload_utils.py
---------------
Port nguyên logic `_save_upload()` trong web_app.py gốc: nhận file người
dùng tải lên (UploadFile của FastAPI), lưu ra đĩa, và nếu là .zip (trường
hợp file Quản lý điện xuất kiểu "Web Page, Complete" kèm thư mục "..._files")
thì tự giải nén và tìm đúng file .xls/.htm/.html bên trong.

Trả về đường dẫn file THẬT để đưa vào parsers.load_file(), và 1 hàm cleanup
để xoá sạch (file tạm hoặc cả thư mục giải nén).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import UploadFile

from backend.services.swift_recon import parsers


def save_upload_to_path(upload: UploadFile) -> tuple[str, callable]:
    """Trả về (path, cleanup_fn). Hỗ trợ .xls / .xlsx / .zip (zip chứa
    file .xls/.htm/.html, có thể kèm thư mục "..._files")."""
    suffix = Path(upload.filename or "").suffix.lower() or ".xls"
    raw = upload.file.read()

    if suffix != ".zip":
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw)
            path = tmp.name
        return path, lambda: _safe_remove_file(path)

    # ── .zip: giải nén, tự tìm file .xls/.htm/.html bên trong ──────────────
    extract_dir = tempfile.mkdtemp(prefix="swiftrecon_")
    zip_path = os.path.join(extract_dir, "upload.zip")
    with open(zip_path, "wb") as f:
        f.write(raw)

    with zipfile.ZipFile(zip_path) as zf:
        extract_root_abs = os.path.abspath(extract_dir)
        for member in zf.namelist():
            member_path = os.path.abspath(os.path.join(extract_dir, member))
            if not member_path.startswith(extract_root_abs + os.sep) and member_path != extract_root_abs:
                raise parsers.UnknownFileFormat(f"File .zip chứa đường dẫn không an toàn: {member}")
        zf.extractall(extract_dir)
    os.remove(zip_path)

    candidates = []
    for root, _dirs, files in os.walk(extract_dir):
        rel_root = os.path.relpath(root, extract_dir)
        in_files_subfolder = any(part.endswith("_files") for part in Path(rel_root).parts)
        for fname in files:
            if Path(fname).suffix.lower() in (".xls", ".htm", ".html"):
                depth = 0 if rel_root == "." else len(Path(rel_root).parts)
                candidates.append((in_files_subfolder, depth, os.path.join(root, fname)))

    if not candidates:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise parsers.UnknownFileFormat("File .zip tải lên không chứa file .xls/.htm/.html nào cả.")

    candidates.sort(key=lambda c: (c[0], c[1]))
    chosen_path = candidates[0][2]
    return chosen_path, lambda: shutil.rmtree(extract_dir, ignore_errors=True)


def _safe_remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
