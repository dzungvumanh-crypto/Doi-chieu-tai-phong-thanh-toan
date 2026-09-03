"""Middleware ghi nhật ký thao tác — mọi request thay đổi dữ liệu vào bảng audit_logs.

Ghi tập trung tại 1 điểm thay vì rải write_audit khắp các endpoint:
mỗi POST/PUT/PATCH/DELETE thành công/thất bại đều để lại 1 dòng (ai, làm gì,
kết quả HTTP, IP, thời gian). Các thao tác có write_audit ngữ nghĩa riêng
(quản lý User, đổi mật khẩu, đăng nhập) được bỏ qua ở đây để tránh trùng.

Middleware này KHÔNG tự ghi DB. Nó chỉ bỏ dòng vào hàng đợi rồi trả response
ngay — xem `backend/core/audit_queue.py` để biết vì sao.

Kèm theo mỗi dòng là tóm tắt dữ liệu gửi lên (query + body JSON nhỏ, đã che
khoá nhạy cảm) — xem `backend/core/audit_body.py`.
"""
import re

from starlette.middleware.base import BaseHTTPMiddleware

from backend.core import audit_body, audit_queue
from backend.core.net import header_ip_dang_tin

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Prefix tự ghi audit riêng hoặc đã có nhật ký khác → middleware bỏ qua
_SKIP_PREFIXES = (
    "/api/auth",    # login/logout → login_logs; đổi mật khẩu → write_audit
    "/api/staff",   # tạo/sửa/xóa/import User → write_audit ngữ nghĩa
    # Đối chiếu CITAD (Extension) — 2 endpoint này xác thực bằng header
    # X-Extension-Token, không phải JWT, nên _actor_id() ở dưới luôn trả
    # None cho chúng dù backend tra được đúng người từ token.
    # _resolve_extension_owner() (backend/api/doi_chieu_citad.py) tự ghi audit
    # với actor_id đúng — nhưng CHỈ cho lượt THẤT BẠI (token sai/bị thu hồi).
    # Lượt THÀNH CÔNG cố ý không ghi ở đâu cả: đây là 2 endpoint tần suất cao
    # nhất hệ thống, ghi mỗi lượt sẽ làm trôi mất dòng audit của mọi module
    # khác (audit_logs dùng chung, dọn theo hạn lưu). Vết của việc lưu thật
    # nằm ở POST /session — đường đó KHÔNG bị bỏ qua, vẫn ghi bình thường.
    "/api/doi-chieu-citad/citad-buffer",
    "/api/doi-chieu-citad/paymenthub-buffer",
    # Đối chiếu CITAD - PaymentHub Phòng QLTK Nostro, Vostro — cùng lý do
    # như 2 dòng trên, xem _resolve_extension_owner() trong
    # backend/api/doi_chieu_citad_nostro.py.
    "/api/doi-chieu-citad-nostro/citad-buffer",
    "/api/doi-chieu-citad-nostro/paymenthub-buffer",
    # Ôn tập trắc nghiệm — cùng lý do với 4 dòng trên, nhưng gay hơn nhiều:
    # `PATCH /attempts/{id}/progress` chạy sau MỖI CÂU trả lời, tức một bài 550
    # câu để lại 550 dòng. Đo trên máy thật: vài giờ chạy thử sinh 1.634 dòng,
    # bằng 36% toàn bộ bảng audit_logs tích luỹ từ trước tới nay — nhật ký của
    # mọi module khác sẽ bị trôi mất trong lúc bảng vẫn dọn theo cùng hạn lưu.
    #
    # Bỏ cả nhánh là an toàn: những thao tác thực sự cần tra sau này đều đã tự
    # ghi `write_audit` ngữ nghĩa trong backend/api/quiz.py — tải bộ câu hỏi
    # lên, đổi tên bộ, xoá bộ, và nộp bài. Phần bị bỏ chỉ là tạo lượt làm bài,
    # lưu tiến độ và bỏ bài dở: đều là thao tác của một người trên bài của
    # chính họ, không ai cần tra soát.
    "/api/quiz",
)

_ID_RE = re.compile(r"/\d+")

# Đường dẫn ĐƠN LẺ đã tự ghi write_audit ngữ nghĩa nhưng nằm trong nhánh không
# được bỏ qua. Bỏ cả prefix "/api/leaves" thì mất nhật ký của toàn bộ nghỉ phép,
# nên chặn đúng một đường. So khớp trên path đã chuẩn hoá số → /{id}.
_SKIP_EXACT = {
    ("PATCH", "/api/leaves/quotas/staff/{id}/join-date"),
}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        method = request.method
        path = request.url.path
        bo_qua = (
            method not in _MUTATING
            or any(path.startswith(p) for p in _SKIP_PREFIXES)
            or (method, _ID_RE.sub("/{id}", path)) in _SKIP_EXACT
        )

        # Body phải đọc TRƯỚC call_next: sau đó route đã hút hết luồng, đọc lại
        # là chờ vô hạn. Starlette bọc request bằng _CachedRequest nên gọi
        # `body()` ở đây là hợp lệ — bản đã đọc được phát lại cho route bên
        # dưới. Vẫn phải nuốt lỗi: client ngắt giữa chừng thì `body()` ném
        # ClientDisconnect, mà nhật ký không được phép làm hỏng request.
        body = None
        if not bo_qua and audit_body.nen_doc_body(request.headers):
            try:
                body = await request.body()
            except Exception:
                body = None

        response = await call_next(request)

        if bo_qua:
            return response
        # 404/405 = không khớp route → không có thao tác thực sự, khỏi ghi
        if response.status_code in (404, 405):
            return response

        # Đọc sẵn mọi thứ cần từ request: luồng ghi nền không được đụng vào
        # đối tượng Request, và tất cả những gì nó cần đều là giá trị đơn giản.
        peer = request.client.host if request.client else None
        audit_queue.enqueue(
            method,
            path,
            response.status_code,
            request.headers.get("Authorization", ""),
            # None khi header không đáng tin → audit_queue tự lui về IP đã lưu
            # lúc đăng nhập, rồi mới tới địa chỉ của kết nối.
            header_ip_dang_tin(peer, request.headers.get("X-Client-IP")),
            peer,
            noi_dung=audit_body.tom_tat(request.url.query, body),
        )
        return response
