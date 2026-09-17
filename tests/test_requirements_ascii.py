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


# ── Mọi dòng requirement phải có chặn trên ───────────────────────────────────
# Khai `>=X` không chặn trên nghĩa là máy cài mới hôm nay kéo về bất kỳ bản nào.
# Đã xảy ra âm thầm: pypdfium2 nhảy 4.x -> 5.13.0, Pillow 10.x -> 12.3.0,
# python-calamine 0.2 -> 0.8.2 — không ai quyết định, không ai hay. Rà thủ công
# một lượt thì lần sau vẫn lọt; test này canh để không phải rà lại.
_MIEN_TRU: set[str] = set()   # khai tên gói ở đây kèm lý do NGAY TRÊN dòng này


def _cac_dong_yeu_cau(path: Path):
    for so, dong in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        dong = dong.split("#", 1)[0].strip()
        if dong and not dong.startswith("-"):
            yield so, dong


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.name)
def test_moi_yeu_cau_deu_co_chan_tren(path: Path):
    thieu = [
        f"  {path.name}:{so}  {dong}"
        for so, dong in _cac_dong_yeu_cau(path)
        if "<" not in dong and "==" not in dong
        and dong.split("[")[0].split(">")[0].split("=")[0].strip() not in _MIEN_TRU
    ]
    assert not thieu, (
        "Dòng requirement thiếu chặn trên — bản mới của thư viện sẽ tự kéo về máy "
        "cài mới mà không ai quyết định:\n" + "\n".join(thieu) +
        "\n\nThêm `,<N` (major kế tiếp; với gói 0.x thì minor kế tiếp), hoặc ghim "
        "`==`. Nếu thật sự phải để mở, khai tên gói vào _MIEN_TRU kèm lý do."
    )
