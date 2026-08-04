"""Middleware ghi nhật ký thao tác — mọi request thay đổi dữ liệu vào bảng audit_logs.

Ghi tập trung tại 1 điểm thay vì rải write_audit khắp các endpoint:
mỗi POST/PUT/PATCH/DELETE thành công/thất bại đều để lại 1 dòng (ai, làm gì,
kết quả HTTP, IP, thời gian). Các thao tác có write_audit ngữ nghĩa riêng
(quản lý User, đổi mật khẩu, đăng nhập) được bỏ qua ở đây để tránh trùng.

Middleware này KHÔNG tự ghi DB. Nó chỉ bỏ dòng vào hàng đợi rồi trả response
ngay — xem `backend/core/audit_queue.py` để biết vì sao.
"""
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core import audit_queue

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Prefix tự ghi audit riêng hoặc đã có nhật ký khác → middleware bỏ qua
_SKIP_PREFIXES = (
    "/api/auth",    # login/logout → login_logs; đổi mật khẩu → write_audit
    "/api/staff",   # tạo/sửa/xóa/import User → write_audit ngữ nghĩa
    # Đối chiếu CITAD (Extension) — 2 endpoint này xác thực bằng header
    # X-Extension-Token, không phải JWT, nên _actor_id() ở dưới luôn trả
    # None cho chúng dù backend tra được đúng người từ token. Đã tự ghi
    # audit đúng actor_id trong _resolve_extension_owner()
    # (backend/api/doi_chieu_citad.py) — bỏ qua ở đây để tránh ghi trùng.
    "/api/doi-chieu-citad/citad-buffer",
    "/api/doi-chieu-citad/paymenthub-buffer",
)


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

        # Đọc sẵn mọi thứ cần từ request: luồng ghi nền không được đụng vào
        # đối tượng Request, và tất cả những gì nó cần đều là giá trị đơn giản.
        audit_queue.enqueue(
            method,
            path,
            response.status_code,
            request.headers.get("Authorization", ""),
            request.headers.get("X-Client-IP", "").strip() or None,
            request.client.host if request.client else None,
        )
        return response
