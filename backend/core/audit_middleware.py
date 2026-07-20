"""Middleware ghi nhật ký thao tác — mọi request thay đổi dữ liệu vào bảng audit_logs.

Ghi tập trung tại 1 điểm thay vì rải write_audit khắp các endpoint:
mỗi POST/PUT/PATCH/DELETE thành công/thất bại đều để lại 1 dòng (ai, làm gì,
kết quả HTTP, IP, thời gian). Các thao tác có write_audit ngữ nghĩa riêng
(quản lý User, đổi mật khẩu, đăng nhập) được bỏ qua ở đây để tránh trùng.
"""
import sqlite3
from starlette.middleware.base import BaseHTTPMiddleware

from backend.database import DB_PATH, _vn_now
from backend.core.security import decode_token

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Prefix tự ghi audit riêng hoặc đã có nhật ký khác → middleware bỏ qua
_SKIP_PREFIXES = (
    "/api/auth",    # login/logout → login_logs; đổi mật khẩu → write_audit
    "/api/staff",   # tạo/sửa/xóa/import User → write_audit ngữ nghĩa
)


def _client_ip(request) -> str | None:
    # X-Client-IP do frontend NiceGUI chuyển tiếp — IP thật của browser
    return (
        request.headers.get("X-Client-IP", "").strip()
        or (request.client.host if request.client else None)
    )


def _actor_id(request):
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    payload = decode_token(auth[7:].strip())
    if not payload:
        return None
    sub = payload.get("sub")
    try:
        return int(sub) if sub is not None else None
    except (ValueError, TypeError):
        return None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        method = request.method
        path = request.url.path
        if method not in _MUTATING or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return response
        # 404/405 = không khớp route → không có thao tác thực sự, khỏi ghi
        if response.status_code in (404, 405):
            return response

        try:
            db = sqlite3.connect(DB_PATH, timeout=30)
            try:
                db.execute("PRAGMA busy_timeout=30000")
                db.execute(
                    "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, ip_address, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        _actor_id(request),
                        method,
                        path,
                        None,
                        f"HTTP {response.status_code}",
                        _client_ip(request),
                        _vn_now(),
                    ),
                )
                db.commit()
            finally:
                db.close()
        except Exception:
            # Ghi audit không được phép làm hỏng request nghiệp vụ
            import logging
            logging.getLogger("audit").warning("Không ghi được audit cho %s %s", method, path, exc_info=True)

        return response
