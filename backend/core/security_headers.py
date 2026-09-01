"""Header an toàn cho mọi phản hồi HTTP — dùng chung cho backend và frontend.

Ba việc, không cái nào cần cấu hình:

1. `X-Frame-Options: DENY` + `frame-ancestors 'none'` — chặn nhúng trang vào
   iframe của trang khác. Không có nó thì kẻ tấn công dựng một trang mồi, đặt
   trang thật của hệ thống trong iframe trong suốt bên trên, người dùng tưởng
   mình bấm nút trên trang mồi nhưng thực ra đang bấm nút "Xoá" / "Duyệt" trong
   phiên đăng nhập thật của chính họ. Đã rà: không chỗ nào trong phần mềm tự
   nhúng trang của mình vào iframe, nên DENY không làm hỏng gì.

2. `X-Content-Type-Options: nosniff` — cấm trình duyệt tự đoán lại kiểu file.
   Ảnh chữ ký, file Excel, ZIP người dùng tải lên rồi tải xuống mà bị đoán
   thành HTML là chạy được mã trong đó.

3. `Referrer-Policy` — không để địa chỉ trang nội bộ (kèm số hiệu đơn, id cán
   bộ trên thanh địa chỉ) rò sang trang ngoài khi người dùng bấm link ra.

CỐ Ý KHÔNG đặt `Content-Security-Policy` đầy đủ (script-src/style-src): NiceGUI
dựng giao diện bằng script và style nội tuyến, còn `/docs` nạp Swagger từ CDN —
siết hai chỉ thị đó là trắng màn hình, mà lợi ích thì nhỏ hơn nhiều so với công
sức duy trì danh sách nguồn. Chỉ giữ `frame-ancestors` vì nó không đụng gì tới
việc nạp tài nguyên.

CŨNG KHÔNG đặt `Strict-Transport-Security`: hệ thống đang chạy HTTP thuần. Gửi
HSTS trên HTTP vừa vô nghĩa (trình duyệt bỏ qua) vừa nguy hiểm nếu sau này ai
bật nhầm trên đúng cổng — trình duyệt sẽ nhớ và từ chối mọi kết nối HTTP tới máy
chủ đó, không có cách gỡ từ phía máy chủ. Thêm nó CÙNG LÚC với TLS, không sớm hơn.

Viết bằng ASGI thuần (không phải BaseHTTPMiddleware) để không phải dựng
Request/Response cho từng lượt gọi — giống BodySizeLimitMiddleware ở uploads.py.
"""

_HEADER = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message):
            if message["type"] == "http.response.start":
                # Giữ nguyên header do route tự đặt: chỉ thêm cái CHƯA có.
                # Nếu sau này có endpoint cần được nhúng iframe, nó tự đặt
                # x-frame-options là ở đây không đè lên.
                san_co = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in _HEADER if k not in san_co
                ]
            await send(message)

        await self.app(scope, receive, _send)
