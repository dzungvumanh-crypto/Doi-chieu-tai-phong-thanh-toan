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
    # mkdtemp() nằm NGOÀI try để except còn dọn được. Mọi lỗi phía sau đều xoá
    # thư mục trước khi ném lên — trước đây zip hỏng / zip-slip / zip có mật khẩu
    # đều để lại thư mục tạm vĩnh viễn, mỗi lần upload lỗi là một thư mục rác.
    extract_dir = tempfile.mkdtemp(prefix="swiftrecon_")
    try:
        chosen_path = _extract_and_pick(raw, extract_dir)
    except Exception:
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise
    return chosen_path, lambda: shutil.rmtree(extract_dir, ignore_errors=True)


def _extract_and_pick(raw: bytes, extract_dir: str) -> str:
    """Giải nén raw vào extract_dir, trả path file .xls/.htm/.html phù hợp nhất.

    Mọi lỗi do file người dùng đều ném `UnknownFileFormat` → API trả 422 kèm
    thông báo tiếng Việt, thay vì 500 kèm stack trace.
    """
    zip_path = os.path.join(extract_dir, "upload.zip")
    with open(zip_path, "wb") as f:
        f.write(raw)

    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise parsers.UnknownFileFormat(
            "File tải lên không phải file .zip hợp lệ — có thể tải bị lỗi, "
            "bị cắt dở, hoặc chỉ được đổi đuôi tên thành .zip."
        ) from e

    with archive as zf:
        extract_root_abs = os.path.abspath(extract_dir)
        for member in zf.namelist():
            member_path = os.path.abspath(os.path.join(extract_dir, member))
            if not member_path.startswith(extract_root_abs + os.sep) and member_path != extract_root_abs:
                raise parsers.UnknownFileFormat(f"File .zip chứa đường dẫn không an toàn: {member}")
        try:
            zf.extractall(extract_dir)
        except RuntimeError as e:
            raise parsers.UnknownFileFormat(
                "File .zip có đặt mật khẩu — hãy giải nén ra rồi tải lại file bên trong."
            ) from e
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
        raise parsers.UnknownFileFormat("File .zip tải lên không chứa file .xls/.htm/.html nào cả.")

    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def _safe_remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
