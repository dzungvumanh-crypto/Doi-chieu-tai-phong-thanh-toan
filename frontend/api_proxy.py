"""Reverse-proxy /api/doi-chieu-citad*/ — chuyển tiếp sang backend nội bộ.

Một số máy chủ production chỉ mở tường lửa cổng FRONTEND (NiceGUI) ra máy
trạm, không mở cổng BACKEND (FastAPI) — Extension CITAD chạy trên máy trạm
chỉ gọi được đúng 1 link chính thức (cổng frontend). Route ở đây cho tiến
trình frontend tự làm proxy sang backend chạy cùng máy (BACKEND_URL, xem
frontend/api_client.py) — máy trạm/Extension không cần biết cổng backend.

CHỈ mở đúng các tiền tố khai trong `_PREFIXES` — KHÔNG mở /api/{full_path:path}
cho toàn hệ thống. Cổng backend bị tường lửa chặn là 1 lớp phòng thủ theo
chiều sâu (nghỉ phép, chấm công, bàn giao...) — mở hết qua proxy sẽ xoá lớp
đó. Cần thêm module khác dùng qua proxy thì thêm đúng tiền tố của module đó
vào `_PREFIXES`, không mở rộng thành wildcard.

Gồm 2 tiền tố — SONG SONG, độc lập, tự thêm tiền tố mới KHÔNG được rơi vào
bẫy "chỉ thêm prefix mà quên nhớ Extension của module mới cũng cần nó": module
Đối chiếu CITAD - PaymentHub N&V (Phòng QLTK Nostro, Vostro,
`backend/api/doi_chieu_citad_nostro.py`) ban đầu KHÔNG có trong danh sách này
— Extension `extension_citad_nv/` gọi thẳng origin của trang frontend
(`window.location.origin`, xem `frontend/pages/doi_chieu_citad_nostro.py::_try_auto_connect_extension`)
nên mọi request từ máy trạm rơi đúng vào "lỗ hổng" 404 này ở các máy chủ chỉ
mở cổng frontend — Extension coi 404 là lỗi tạm thời (không phải 403) nên cứ
báo "chưa gửi được, sẽ tự thử lại" vô thời hạn, không bao giờ tự hết vì đây
không phải lỗi mạng nhất thời. Vá bằng cách thêm tiền tố thứ 2 bên dưới.
"""
import httpx
from nicegui import app
from starlette.requests import Request
from starlette.responses import Response

from frontend.api_client import BACKEND_URL

_PREFIXES = ("/api/doi-chieu-citad/", "/api/doi-chieu-citad-nostro/")

# Header hop-by-hop — không forward, để tầng ASGI/httpx tự tính lại đúng.
# content-encoding: httpx tự giải nén .content trước khi trả về, nhưng
# header gốc vẫn ghi "còn nén" — trình duyệt cố giải nén lần 2 sẽ hỏng nếu
# backend sau này bật GZipMiddleware. Chưa xảy ra nhưng phòng trước rẻ.
_HOP_BY_HOP = {
    "host", "content-length", "content-encoding",
    "connection", "transfer-encoding", "keep-alive",
}

# 60s, không phải 30s: /export của module này generate Excel qua run_heavy
# (backend/core/concurrency.py, MAX_HEAVY=4) — khi bể đầy request phải xếp
# hàng, cộng thời gian sinh file có thể vượt 30s. Endpoint UI thường (không
# qua proxy này, frontend vẫn gọi BACKEND_URL trực tiếp qua api_client.py)
# không bị giới hạn này.
_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))


@app.on_shutdown
async def _close_proxy_client():
    await _client.aclose()


async def _do_proxy(prefix: str, sub_path: str, request: Request) -> Response:
    # body/response đọc trọn vào RAM tiến trình frontend (dùng chung cho mọi
    # người đang mở web) — chấp nhận được vì phạm vi proxy chỉ còn 2 module
    # CITAD: buffer POST là JSON nhỏ, export là file Excel/zip một ngày dữ
    # liệu, không phải nơi upload file lớn (đối soát CITAD/IPCAS upload qua
    # /api/doi-soat-citad/, KHÔNG nằm trong các tiền tố proxy này). Nếu sau
    # này mở thêm tiền tố có upload file lớn, cần đổi sang stream ở đây trước.
    # Phải LOẠI header x-client-ip client tự gửi trước khi lọc, không chỉ gán
    # đè — dict Python phân biệt hoa/thường nhưng HTTP header thì không, nên
    # "x-client-ip" (client gửi) và "X-Client-IP" (gán bên dưới) là 2 khoá
    # khác nhau trong dict này, httpx gửi cả 2 header, backend đọc trúng cái
    # đi trước (của client) — giả mạo được IP trong audit_logs. Đã đo thực
    # tế xác nhận, xem review PR #17.
    _strip = _HOP_BY_HOP | {"x-client-ip"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _strip}
    # Backend thấy request này tới từ tiến trình frontend (localhost) — mất
    # IP thật của máy trạm/Extension nếu không gắn thêm. X-Client-IP là cơ
    # chế đã có sẵn cho đúng tình huống này (xem frontend/api_client.py,
    # backend/core/audit_queue.py::_real_ip).
    #
    # request.client.host là IP của bên kết nối TRỰC TIẾP tới tiến trình
    # frontend — đúng là máy trạm VÌ NiceGUI đang lắng nghe thẳng, không qua
    # proxy nào khác. Nếu sau này đặt nginx/IIS trước cổng 8080, giá trị này
    # sẽ thành IP của nginx/IIS đó, mọi dòng audit_logs mang cùng 1 IP — lúc
    # đó phải đổi sang đọc X-Forwarded-For.
    headers["X-Client-IP"] = request.client.host if request.client else ""
    body = await request.body()

    upstream = await _client.request(
        request.method,
        f"{BACKEND_URL}{prefix}{sub_path}",
        # request.query_params là multi-dict (1 key có thể lặp nhiều lần) —
        # truyền thẳng object này cho httpx sẽ bị hiểu như dict thường, MẤT
        # các giá trị trùng key, chỉ giữ lại giá trị cuối. multi_items() giữ
        # đúng toàn bộ cặp key-value kể cả key lặp lại (đã kiểm chứng qua test).
        params=list(request.query_params.multi_items()),
        headers=headers,
        content=body,
    )

    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
    )


# Không có OPTIONS: preflight CORS vào 2 cổng này sẽ nhận 405 — chưa ảnh
# hưởng vì Extension gọi từ service worker (không phát sinh preflight), và
# cổng 8000 (có CORSMiddleware) vẫn là cửa cho mọi thứ cần CORS thật. Ai gỡ
# lỗi CORS qua cổng 8080 sau này cần biết cổng này không xử lý preflight.
@app.api_route(_PREFIXES[0] + "{sub_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def _proxy_api(sub_path: str, request: Request) -> Response:
    return await _do_proxy(_PREFIXES[0], sub_path, request)


@app.api_route(_PREFIXES[1] + "{sub_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def _proxy_api_nostro(sub_path: str, request: Request) -> Response:
    return await _do_proxy(_PREFIXES[1], sub_path, request)
