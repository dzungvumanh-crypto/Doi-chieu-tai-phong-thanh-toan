"""Shared ZIP utilities dùng chung cho b2, b4, b6."""
import os
import shutil

import pyzipper

_7ZIP_CANDIDATES = [
    r'C:\Program Files\7-Zip\7z.exe',
    r'C:\Program Files (x86)\7-Zip\7z.exe',
]
_WINRAR_CANDIDATES = [
    r'C:\Program Files\WinRAR\WinRAR.exe',
    r'C:\Program Files (x86)\WinRAR\WinRAR.exe',
]

NULL_SESSION = frozenset({'', 'nan', 'None', 'NaN'})


def find_zip_tool() -> tuple | None:
    """Trả về (path, tool_type) hoặc None. Ưu tiên 7-Zip trước WinRAR."""
    for p in _7ZIP_CANDIDATES:
        if os.path.exists(p):
            return (p, '7z')
    found_7z = shutil.which('7z.exe') or shutil.which('7z')
    if found_7z:
        return (found_7z, '7z')
    for p in _WINRAR_CANDIDATES:
        if os.path.exists(p):
            return (p, 'winrar')
    found_rar = shutil.which('WinRAR.exe') or shutil.which('winrar.exe')
    if found_rar:
        return (found_rar, 'winrar')
    return None


def build_extract_cmd(tool_path: str, tool_type: str, zip_path: str,
                      out_dir: str, pwd: str) -> list:
    if tool_type == '7z':
        return [tool_path, 'e', f'-p{pwd}', f'-o{out_dir}', zip_path, '-y', '-bso0', '-bsp0']
    return [tool_path, 'e', f'-p{pwd}', '-o+', '-ibck', '-inul', zip_path, out_dir]


def detect_encoding_from_bytes(raw: bytes) -> str:
    """Detect encoding từ 512 bytes đầu."""
    if raw[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    try:
        raw.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'cp1252'


def detect_encoding_path(path: str) -> str:
    with open(path, 'rb') as f:
        raw = f.read(512)
    return detect_encoding_from_bytes(raw)


def detect_encoding(z: pyzipper.AESZipFile, name: str) -> str:
    with z.open(name) as f:
        raw = f.read(512)
    return detect_encoding_from_bytes(raw)
