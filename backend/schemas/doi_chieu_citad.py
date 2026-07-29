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

## Xác thực Extension — đã thiết kế lại sau review bảo mật

Bản trước dùng 1 khoá tĩnh dùng chung (`CITAD_EXTENSION_KEY`) cho mọi người
+ field `owner` do CHÍNH Extension tự khai trong payload — nghĩa là bất kỳ
ai có khoá cũng ghi được buffer dưới bất kỳ tên nào, kể cả cố tình chèn số
liệu giả để dòng chênh lệch ra đúng 0 (rủi ro nặng nhất, do reviewer chỉ ra).

Thiết kế mới: mỗi người tự tạo 1 "mã kết nối" (token) cá nhân ngay trên
trang `/doi_chieu_citad` (sau khi đã đăng nhập thật bằng JWT), dán 1 lần vào
Extension. Backend chỉ tra được `owner` từ token hợp lệ trong DB — KHÔNG còn
field `owner` do client tự khai trong payload nữa, xem `CitadBufferIn`/
`PaymentHubBufferIn` bên dưới đã bỏ field này. Token bị lộ chỉ ảnh hưởng
đúng 1 người, thu hồi được riêng lẻ (không cần đổi khoá chung cho cả phòng).
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
    """Payload Extension gửi khi tự động lưu số liệu CITAD. Không còn field
    `owner` — chủ buffer được suy ra từ token hợp lệ (header
    `X-Extension-Token`), không phải do client tự khai."""
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


class ExtensionTokenOut(BaseModel):
    """Trả về NGUYÊN VĂN đúng 1 lần lúc tạo — không lưu plaintext ở backend
    (chỉ lưu SHA-256 hash), nên không thể xem lại token cũ, chỉ có thể tạo
    mã mới (tự động thu hồi mã cũ)."""
    token: str


class ExtensionTokenStatus(BaseModel):
    connected: bool
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
