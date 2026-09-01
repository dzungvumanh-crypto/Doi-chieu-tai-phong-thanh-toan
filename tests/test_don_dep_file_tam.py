"""Test file tạm luôn được xoá, kể cả khi việc ghi Excel thất bại.

`backend/api/swift_recon.py` từng lặp 8 lần cùng một mẫu: tạo file tạm → ghi
Excel → đọc lại → `os.remove()`. Hàm ghi ném lỗi là dòng `os.remove()` không bao
giờ chạy tới, file .xlsx nằm lại %TEMP% vĩnh viễn — mỗi lượt xuất lỗi một file,
không tiến trình nào dọn.

Chạy: .venv/Scripts/python.exe -m pytest tests/test_don_dep_file_tam.py -v
"""

import os

import pytest

from backend.api.swift_recon import _xuat_xlsx


def test_ghi_thanh_cong_thi_tra_bytes_va_xoa_file():
    duong_dan = {}

    def _ghi(p):
        duong_dan["p"] = p
        with open(p, "wb") as f:
            f.write(b"noi-dung-excel")

    assert _xuat_xlsx(_ghi) == b"noi-dung-excel"
    assert not os.path.exists(duong_dan["p"])


def test_ham_ghi_nem_loi_thi_van_xoa_file_tam():
    duong_dan = {}

    def _ghi(p):
        duong_dan["p"] = p
        with open(p, "wb") as f:
            f.write(b"ghi-do-dang")
        raise ValueError("dữ liệu bất thường")

    with pytest.raises(ValueError):
        _xuat_xlsx(_ghi)
    assert not os.path.exists(duong_dan["p"]), "file tạm bị bỏ lại khi hàm ghi lỗi"


def test_ham_ghi_khong_tao_file_thi_khong_vo_them():
    """Lỗi thật phải nổi lên nguyên vẹn, không bị lỗi dọn dẹp che mất."""
    def _ghi(p):
        os.remove(p)                 # hàm ghi tự xoá rồi mới hỏng
        raise RuntimeError("hỏng giữa chừng")

    with pytest.raises(RuntimeError, match="hỏng giữa chừng"):
        _xuat_xlsx(_ghi)
