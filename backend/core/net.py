"""Xác định IP thật của người dùng — và chỉ tin header khi ĐÁNG tin.

`X-Client-IP` là cơ chế nội bộ: tiến trình frontend (NiceGUI) gọi backend từ
chính máy chủ nên `request.client.host` luôn là 127.0.0.1; IP thật của trình
duyệt được frontend gắn vào header này (xem frontend/api_client.py và
frontend/api_proxy.py).

Vấn đề: header thì AI GỬI CŨNG ĐƯỢC. Trước đây backend nhận vô điều kiện, nên
khi `BACKEND_HOST=0.0.0.0` (mặc định trong mã, dù .env.example khuyên
127.0.0.1) thì bất kỳ ai gọi thẳng cổng 8000 cũng tự khai mình là IP nào tuỳ
thích. Hệ quả: `login_logs` và `audit_logs` ghi IP giả — nhật ký để truy vết
lại thành nhật ký do người bị truy vết tự viết; và cảnh báo "tài khoản đang
được dùng tại IP khác" bị lách bằng đúng một dòng header.

Luật ở đây: chỉ đọc header khi bên kết nối TRỰC TIẾP là máy chủ này (hoặc một
proxy được khai báo tường minh). Ngoài ra, dùng địa chỉ của chính kết nối.
"""
import os
import re

# Bên gọi được phép khai IP hộ người khác. Mặc định chỉ có chính máy này —
# tiến trình frontend. Đặt TRUSTED_PROXY_IPS trong .env (phân cách bằng dấu
# phẩy) khi có nginx/IIS đứng trước cổng backend.
_MAC_DINH_TIN = ("127.0.0.1", "::1", "localhost")
TRUSTED_PEERS = frozenset(
    [p.strip() for p in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if p.strip()]
    + list(_MAC_DINH_TIN)
)

# Chỉ nhận chuỗi trông như địa chỉ IP. Giá trị này đi thẳng vào cột
# ip_address của login_logs/audit_logs rồi hiện lên màn hình nhật ký — thả
# chuỗi tuỳ ý vào đó là mở đường bơm rác (hoặc chữ gây hiểu nhầm) vào bằng
# chứng kiểm soát nội bộ.
_DANG_IP = re.compile(r"^[0-9a-fA-F.:]{3,45}$")


def _hop_le(gia_tri: str) -> bool:
    return bool(gia_tri) and bool(_DANG_IP.match(gia_tri))


def header_ip_dang_tin(peer: str | None, header: str | None) -> str | None:
    """IP lấy từ `X-Client-IP`, hoặc None nếu không đủ điều kiện tin."""
    if not peer or peer not in TRUSTED_PEERS:
        return None
    gia_tri = (header or "").strip()
    return gia_tri if _hop_le(gia_tri) else None


def client_ip(request) -> str:
    """IP để ghi nhật ký cho một request. Không bao giờ trả chuỗi rỗng."""
    peer = request.client.host if request.client else ""
    return header_ip_dang_tin(peer, request.headers.get("X-Client-IP")) or peer or "unknown"
