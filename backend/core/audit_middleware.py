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
from backend.core.sessions import get_session_ip

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Prefix tự ghi audit riêng hoặc đã có nhật ký khác → middleware bỏ qua
_SKIP_PREFIXES = (
    "/api/auth",    # login/logout → login_logs; đổi mật khẩu → write_audit
    "/api/staff",   # tạo/sửa/xóa/import User → write_audit ngữ nghĩa
)


def _real_ip(request, db, actor_id) -> str | None:
    # Frontend NiceGUI gọi backend từ chính server → request.client.host = 127.0.0.1.
    # IP thật của browser đã được lưu ở login_sessions lúc đăng nhập → tra theo actor
    # để khớp với Nhật ký đăng nhập. Thứ tự ưu tiên: header → session → client.host.
    hdr = request.headers.get("X-Client-IP", "").strip()
    if hdr:
        return hdr
    if actor_id is not None:
        try:
            sess_ip = get_session_ip(db, actor_id)
            if sess_ip:
                return sess_ip
        except Exception:
            pass
    return request.client.host if request.client else None


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
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA busy_timeout=30000")
                actor = _actor_id(request)
                db.execute(
                    "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, ip_address, created_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        actor,
                        method,
                        path,
                        None,
                        f"HTTP {response.status_code}",
                        _real_ip(request, db, actor),
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
