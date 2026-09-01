"""Khoá đồng bộ giữa 2 bản classify_upload_filename() — backend (logic phân loại
THẬT) và frontend (bản sao chỉ để hiển thị nhãn UX, xem docstring
frontend/pages/cham_459901.py::_classify_upload_filename).

Vì sao cần (review PR#43, khanhbq693 mục 3): 2 bản hiện giống hệt nhau từng dòng,
nhưng không có gì canh — sửa luật ở service.py mà quên frontend thì nhãn hiển thị
sai lệch âm thầm với phân loại thật của server, không lỗi không log.

Chạy: .venv\\Scripts\\python.exe -m pytest tests/test_classify_filename_frontend_backend_sync.py -v
"""

from backend.services.cham459901_service import classify_upload_filename as backend_fn
from frontend.pages.cham_459901 import _classify_upload_filename as frontend_fn

_MAU_TEN_FILE = [
    "GL02_20260824_1000.zip",
    "gl02_thang8.ZIP",
    "459_TON_T7.xlsx",
    "459_ton_thang8.xlsx",
    "Quay_danh sach giao dich chuyen tien di 24.8.xlsx",
    "chuyen tien di 25.8.xlsx",
    "chuyen_tien_di_26.xlsx",
    "Danh_sach giao dich den 24.8.xlsx",
    "giao dich den 25.8.xlsx",
    "danh_sach_den_26.xlsx",
    "danh sach den 27.xlsx",
    "khong_nhan_dien_duoc.xlsx",
    "bao_cao_khac.zip",
    "readme.txt",
]


def test_hai_ban_ra_cung_ket_qua_tren_bo_ten_file_mau():
    lech = [
        (ten, backend_fn(ten), frontend_fn(ten))
        for ten in _MAU_TEN_FILE
        if backend_fn(ten) != frontend_fn(ten)
    ]
    assert not lech, (
        "2 bản classify_upload_filename() (backend/services/cham459901_service.py và "
        "frontend/pages/cham_459901.py) ra kết quả KHÁC nhau — nhãn hiển thị sẽ sai "
        f"lệch với phân loại thật của server:\n  {lech}"
    )
