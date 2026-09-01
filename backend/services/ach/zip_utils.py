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


# ─── Nhật ký giải nén — vì sao phải đẩy ra LOG CỦA JOB ────────────────────────
# Ba bước B2/B4/B6 đều có nhánh dự phòng: không tìm thấy 7-Zip/WinRAR (hoặc gọi
# chúng thất bại) thì tự giải nén bằng pyzipper. Nhánh dự phòng đó nạp TRỌN file
# CSV vào bộ nhớ rồi mới đọc — đo được `dtype=str` phình gấp ~7 lần kích thước
# file, hai ZIP chạy song song thì gấp đôi nữa. Máy chủ 8-16 GB sẽ đổ sang bộ nhớ
# ảo và chậm tới mức mọi yêu cầu đều hết giờ chờ.
#
# Trước đây các dòng chẩn đoán này chỉ đi qua `print()`, tức chỉ nằm trong
# logs/backend.log trên máy chủ. Người bấm nút nhìn màn hình KHÔNG hề biết lượt
# chạy của mình vừa rẽ sang đường nguy hiểm — họ chỉ thấy một khoảng lặng dài
# rồi mất kết nối. Nay in cả hai chỗ: backend.log giữ nguyên cho người kỹ thuật,
# log của job hiện thẳng lên màn hình cho người vận hành.

def _ghi(log, msg: str) -> None:
    print(msg)
    if log:
        log(msg)


def bao_dung_cong_cu(buoc: str, zip_path: str, tool_type: str, tool_path: str, log=None) -> None:
    print(f'[{buoc}][DIAG] {tool_type}: {tool_path} | {os.path.basename(zip_path)}')
    _ghi(log, f'[{buoc}] Đang giải nén {os.path.basename(zip_path)} bằng {tool_type}...')


def bao_giai_nen_xong(buoc: str, zip_path: str, giay: float, rc: int, log=None) -> None:
    _ghi(log, f'[{buoc}] Giải nén xong {os.path.basename(zip_path)}: {giay:.1f}s (mã trả về {rc}).')


def bao_lui_ve_pyzipper(buoc: str, zip_path: str, ly_do: str, log=None) -> None:
    """`ly_do` rỗng nghĩa là máy không cài 7-Zip lẫn WinRAR."""
    ten = os.path.basename(zip_path)
    if ly_do:
        _ghi(log, f'[{buoc}] CẢNH BÁO: công cụ giải nén báo lỗi với {ten} ({ly_do}).')
    else:
        _ghi(log, f'[{buoc}] CẢNH BÁO: máy chủ không cài 7-Zip lẫn WinRAR.')
    _ghi(log,
         f'[{buoc}] CẢNH BÁO: phải giải nén {ten} bằng cách dự phòng — cách này nạp trọn '
         'file vào bộ nhớ (gấp khoảng 7 lần kích thước file), máy chủ có thể chậm hẳn '
         'hoặc không phản hồi. Cài 7-Zip lên máy chủ để tránh.')
