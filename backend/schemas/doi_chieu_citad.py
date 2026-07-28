"""Schemas Đối chiếu CITAD ↔ PaymentHub — Phòng Thanh toán.

Port từ `server.py::SessionIn` / `ExportIn` / `CitadBufferIn` của tool desktop
gốc (xem `extension_citad/README.md` để biết bối cảnh). Field giữ NGUYÊN
tên/kiểu như bản gốc để không phải đổi logic tính toán ở frontend hay
`build_xlsx()` — chỉ bỏ `user_id: str` nhập tay (bản gốc hard code 'default')
vì giờ đã có `current["id"]`/`current["username"]` từ JWT.

Đã bỏ 12 field `napas_di_*`/`napas_den_il_*`/`ebank_*` (trừ `napas_m/t`,
`ebank_m/t`) — bản gốc khai báo nhưng không có nơi nào đọc/ghi (dead field,
tương ứng 12 ô nhập liệu chết đã bỏ khỏi giao diện, xem
`frontend/pages/doi_chieu_citad.py`).
"""
from typing import Optional
from pydantic import BaseModel


class SessionIn(BaseModel):
    ngay: str
    lap_bang: Optional[str] = ""
    kiem_soat: Optional[str] = ""
    gD: dict = {}
    phD: dict = {}
    napas_m: float = 0
    napas_t: float = 0
    ebank_m: float = 0
    ebank_t: float = 0


class CitadBufferIn(BaseModel):
    """Payload Extension gửi khi tự động lưu số liệu CITAD.

    `owner`: username TTTT của người đang dùng Extension (cấu hình 1 lần
    trong `extension_citad/content.js::STAFF_USERNAME`) — dùng để tách buffer
    theo từng người, tránh 2 người dùng chung cổng ghi đè/xoá dữ liệu của
    nhau (buffer trước đây là 1 dict toàn cục dùng chung cho cả server).
    """
    owner: str
    key: str
    cong: str
    loai: str
    chieu: str
    tien: str
    soMon: float = 0
    soTien: float = 0
    fMon: str = ""
    fTien: str = ""
    ts: str = ""


class PaymentHubBufferIn(BaseModel):
    owner: str
    items: list = []
    ts: str = ""


class ExportIn(BaseModel):
    day_str: str = ""
    sheet_name: str = "Sheet1"
    lb: str = ""
    ks: str = ""
    gD: dict = {}
    phD: dict = {}
    nm: float = 0
    nt: float = 0
    em: float = 0
    et: float = 0
