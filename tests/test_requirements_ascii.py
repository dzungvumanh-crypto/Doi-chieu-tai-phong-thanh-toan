"""
requirements*.txt phải THUẦN ASCII.

pip đọc requirements.txt bằng encoding **locale của Windows** (cp1252 trên máy vận hành),
không phải UTF-8. Một ký tự tiếng Việt trong dòng comment làm pip chết ngay lúc *đọc file*
với `UnicodeDecodeError: 'charmap' codec can't decode byte 0x90` — trước khi nó kịp gọi ra
mạng. Đã xảy ra thật: comment "# Đơn nghỉ phép..." làm `start.bat` báo "kiem tra ket noi
internet" trong khi mạng hoàn toàn bình thường.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_FILES = sorted(_ROOT.glob("requirements*.txt"))


def test_co_it_nhat_mot_file_requirements():
    assert _FILES, "Không tìm thấy requirements*.txt ở gốc dự án"


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_requirements_thuan_ascii(path: Path):
    raw = path.read_bytes()
    bad = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not bad, (
        f"{path.name} có {len(bad)} byte ngoài ASCII (byte đầu: vị trí {bad[0][0]}, "
        f"0x{bad[0][1]:02X}) — pip sẽ chết khi đọc file. Viết comment không dấu."
    )


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_pip_doc_duoc_bang_cp1252(path: Path):
    """Mô phỏng đúng cách pip decode: encoding locale, không phải UTF-8."""
    path.read_bytes().decode("cp1252")
